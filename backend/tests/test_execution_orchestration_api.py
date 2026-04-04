from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_board_for_actor_read, get_board_for_actor_write
from app.api.execution_runs import router as execution_runs_router
from app.db.session import get_session
from app.models.boards import Board
from app.models.execution_runs import ExecutionArtifact, ExecutionRun
from app.models.organizations import Organization


async def _make_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine


async def _seed_board(session: AsyncSession) -> Board:
    organization = Organization(id=uuid4(), name="Runtime Org")
    board = Board(
        id=uuid4(),
        organization_id=organization.id,
        name="Runtime board",
        slug="runtime-board",
        description="Board for runtime API tests.",
    )
    session.add(organization)
    session.add(board)
    await session.commit()
    return board


def _build_test_app(session_maker: async_sessionmaker[AsyncSession]) -> FastAPI:
    app = FastAPI()
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(execution_runs_router)
    app.include_router(api_v1)

    async def _override_get_session() -> AsyncSession:
        async with session_maker() as session:
            yield session

    async def _override_board_dep(
        board_id: str,
        session: AsyncSession = Depends(get_session),
    ) -> Board:
        loaded = await Board.objects.by_id(UUID(board_id)).first(session)
        if loaded is None:
            from fastapi import HTTPException, status

            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return loaded

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_board_for_actor_read] = _override_board_dep
    app.dependency_overrides[get_board_for_actor_write] = _override_board_dep
    return app


@pytest.mark.asyncio
async def test_execution_run_start_dispatch_and_phase_result_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent_messages: list[dict[str, object]] = []

    class _DummyGatewayDispatchService:
        def __init__(self, session: AsyncSession) -> None:
            self.session = session

        async def require_gateway_config_for_board(self, board: Board) -> tuple[object, object]:
            return object(), object()

        async def send_agent_message(
            self,
            *,
            session_key: str,
            config: object,
            agent_name: str,
            message: str,
            deliver: bool = False,
            idempotency_key: str | None = None,
        ) -> None:
            sent_messages.append(
                {
                    "session_key": session_key,
                    "agent_name": agent_name,
                    "message": message,
                    "deliver": deliver,
                    "idempotency_key": idempotency_key,
                },
            )

    monkeypatch.setattr(
        "app.services.execution_orchestration.GatewayDispatchService",
        _DummyGatewayDispatchService,
    )

    engine = await _make_engine()
    session_maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_maker() as session:
        board = await _seed_board(session)
        run = ExecutionRun(board_id=board.id)
        session.add(run)
        await session.commit()
        await session.refresh(run)

    app = _build_test_app(session_maker)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        start_response = await client.post(
            f"/api/v1/boards/{board.id}/execution-runs/{run.id}/start",
            json={
                "runtime_session_key": "opencode:run-1",
                "execution_state_patch": {"runner": "opencode"},
                "recovery_state_patch": {"attempt": 1},
            },
        )
        assert start_response.status_code == 200
        start_payload = start_response.json()
        assert start_payload["status"] == "running"
        assert start_payload["current_phase"] == "plan"
        assert start_payload["runtime_session_key"] == "opencode:run-1"
        assert start_payload["is_stale"] is False
        assert start_payload["can_heartbeat"] is True
        assert start_payload["execution_state"] == {"runner": "opencode"}
        assert start_payload["recovery_state"] == {"attempt": 1}

        dispatch_response = await client.post(
            f"/api/v1/boards/{board.id}/execution-runs/{run.id}/dispatch",
        )
        assert dispatch_response.status_code == 201
        dispatch_payload = dispatch_response.json()
        assert dispatch_payload["kind"] == "checkpoint"
        assert dispatch_payload["title"] == "Dispatched Plan instruction"
        assert "PLAN -> BUILD -> TEST -> REVIEW -> DONE" in dispatch_payload["body"]
        assert sent_messages[0]["session_key"] == "opencode:run-1"
        assert sent_messages[0]["deliver"] is True
        assert sent_messages[0]["idempotency_key"] == f"execution-run:{run.id}:plan"

        plan_response = await client.post(
            f"/api/v1/boards/{board.id}/execution-runs/{run.id}/phases/plan",
            json={
                "title": "Plan evidence",
                "body": "Plan the implementation and verification steps.",
                "artifact_state": {"step": 1},
                "execution_state_patch": {"plan": "ready"},
            },
        )
        assert plan_response.status_code == 201
        plan_payload = plan_response.json()
        assert plan_payload["kind"] == "plan"
        assert plan_payload["title"] == "Plan evidence"

        repeated_plan_response = await client.post(
            f"/api/v1/boards/{board.id}/execution-runs/{run.id}/phases/plan",
            json={
                "title": "Plan evidence replay",
                "body": "This should be rejected because the run already advanced.",
            },
        )
        assert repeated_plan_response.status_code == 409

    async with session_maker() as session:
        refreshed_run = await session.get(ExecutionRun, run.id)
        assert refreshed_run is not None
        assert refreshed_run.current_phase == "build"
        assert refreshed_run.plan_summary == "Plan the implementation and verification steps."
        assert refreshed_run.execution_state is not None
        assert refreshed_run.execution_state["plan"] == "ready"
        assert refreshed_run.execution_state["last_dispatched_phase"] == "plan"
        assert refreshed_run.execution_state["last_dispatched_runtime_kind"] == "opencode"

        artifacts = list(
            await session.exec(
                select(ExecutionArtifact)
                .where(ExecutionArtifact.execution_run_id == run.id)
                .order_by(ExecutionArtifact.created_at),
            ),
        )
        assert [artifact.kind for artifact in artifacts] == ["checkpoint", "plan"]
        assert artifacts[0].artifact_state is not None
        assert artifacts[0].artifact_state["phase"] == "plan"
        assert artifacts[1].artifact_state == {"step": 1}


@pytest.mark.asyncio
async def test_resume_execution_run_route_resumes_stale_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent_messages: list[dict[str, object]] = []

    class _DummyGatewayDispatchService:
        def __init__(self, session: AsyncSession) -> None:
            self.session = session

        async def require_gateway_config_for_board(self, board: Board) -> tuple[object, object]:
            return object(), object()

        async def send_agent_message(
            self,
            *,
            session_key: str,
            config: object,
            agent_name: str,
            message: str,
            deliver: bool = False,
            idempotency_key: str | None = None,
        ) -> None:
            sent_messages.append(
                {
                    "session_key": session_key,
                    "agent_name": agent_name,
                    "message": message,
                    "deliver": deliver,
                    "idempotency_key": idempotency_key,
                },
            )

    monkeypatch.setattr(
        "app.services.execution_orchestration.GatewayDispatchService",
        _DummyGatewayDispatchService,
    )

    engine = await _make_engine()
    session_maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_maker() as session:
        board = await _seed_board(session)
        run = ExecutionRun(
            board_id=board.id,
            status="running",
            current_phase="build",
            runtime_session_key="opencode:run-2",
            last_heartbeat_at=datetime.now(UTC) - timedelta(minutes=20),
            recovery_state={"resume_count": 1},
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)

    app = _build_test_app(session_maker)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resume_response = await client.post(
            f"/api/v1/boards/{board.id}/execution-runs/{run.id}/resume",
        )
        assert resume_response.status_code == 200
        resume_payload = resume_response.json()
        assert resume_payload["status"] == "running"
        assert resume_payload["current_phase"] == "build"
        assert resume_payload["recovery_state"]["resume_count"] == 2
        assert resume_payload["recovery_state"]["last_resume_reason"] == "stale"
        assert resume_payload["is_stale"] is False
        assert resume_payload["can_resume"] is False
        assert sent_messages[0]["idempotency_key"] == f"execution-run:{run.id}:build"

    async with session_maker() as session:
        refreshed_run = await session.get(ExecutionRun, run.id)
        assert refreshed_run is not None
        assert refreshed_run.last_heartbeat_at is not None
        assert refreshed_run.recovery_state is not None
        assert refreshed_run.recovery_state["last_resume_phase"] == "build"
