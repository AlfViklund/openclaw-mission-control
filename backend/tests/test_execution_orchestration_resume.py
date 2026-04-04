from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.boards import Board
from app.models.execution_runs import ExecutionArtifact, ExecutionRun
from app.models.organizations import Organization
from app.core.time import utcnow
from app.services.execution_orchestration import ExecutionOrchestrationService


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
        description="Board for execution resume tests.",
    )
    session.add(organization)
    session.add(board)
    await session.commit()
    return board


@pytest.mark.asyncio
async def test_execution_orchestration_service_can_resume_a_stale_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
            runtime_session_key="opencode:run-1",
            last_heartbeat_at=utcnow() - timedelta(minutes=20),
            recovery_state={"resume_count": 1},
            execution_state={"last_dispatched_phase": "build"},
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)

        service = ExecutionOrchestrationService(session)

        assert service.is_run_stale(run)

        captured: list[dict[str, object]] = []

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
                captured.append(
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

        resumed = await service.resume_run(board_id=board.id, run_id=run.id)
        assert resumed.status == "running"
        assert resumed.current_phase == "build"
        assert resumed.recovery_state is not None
        assert resumed.recovery_state["resume_count"] == 2
        assert resumed.recovery_state["last_resume_reason"] == "stale"
        assert resumed.recovery_state["last_resume_phase"] == "build"
        assert resumed.recovery_state["last_stale_at"] is not None
        assert resumed.retry_count == 1
        assert resumed.execution_state is not None
        assert resumed.execution_state["last_dispatched_phase"] == "build"
        assert resumed.execution_state["last_dispatched_runtime_kind"] == "opencode"
        assert captured[0]["idempotency_key"] == f"execution-run:{run.id}:build"

        refreshed_run = await session.get(ExecutionRun, run.id)
        assert refreshed_run is not None
        assert refreshed_run.last_heartbeat_at is not None
        assert refreshed_run.last_heartbeat_at > utcnow() - timedelta(minutes=2)

        artifacts = list(
            await session.exec(
                select(ExecutionArtifact).where(ExecutionArtifact.execution_run_id == run.id),
            ),
        )
        assert any(artifact.kind == "checkpoint" for artifact in artifacts)


@pytest.mark.asyncio
async def test_execution_orchestration_service_rejects_fresh_running_resume() -> None:
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
            current_phase="plan",
            runtime_session_key="opencode:run-2",
            last_heartbeat_at=utcnow(),
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)

        service = ExecutionOrchestrationService(session)
        with pytest.raises(HTTPException) as exc_info:
            await service.resume_run(board_id=board.id, run_id=run.id)
        assert exc_info.value.status_code == 409
