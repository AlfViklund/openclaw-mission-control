from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_board_for_actor_read, get_board_for_actor_write
from app.api.execution_runs import router as execution_runs_router
from app.core.time import utcnow
from app.db.session import get_session
from app.models.boards import Board
from app.models.execution_runs import ExecutionArtifact, ExecutionRun
from app.models.organizations import Organization
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
        description="Board for execution heartbeat tests.",
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
            raise HTTPException(status_code=404, detail="Board not found")
        return loaded

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_board_for_actor_read] = _override_board_dep
    app.dependency_overrides[get_board_for_actor_write] = _override_board_dep
    return app


@pytest.mark.asyncio
async def test_execution_orchestration_service_records_heartbeat() -> None:
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
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)

        service = ExecutionOrchestrationService(session)
        artifact = await service.record_heartbeat(
            board_id=board.id,
            run_id=run.id,
            message="still working",
            source="operator",
        )

        assert artifact.kind == "heartbeat"
        assert artifact.title == "Heartbeat from operator"
        assert artifact.body == "still working"
        assert artifact.artifact_state is not None
        assert artifact.artifact_state["heartbeat_count"] == 1

        refreshed_run = await session.get(ExecutionRun, run.id)
        assert refreshed_run is not None
        assert refreshed_run.last_heartbeat_at is not None
        assert refreshed_run.recovery_state is not None
        assert refreshed_run.recovery_state["last_heartbeat_message"] == "still working"

        artifacts = list(
            await session.exec(
                select(ExecutionArtifact).where(ExecutionArtifact.execution_run_id == run.id),
            ),
        )
        assert any(item.kind == "heartbeat" for item in artifacts)


@pytest.mark.asyncio
async def test_execution_orchestration_heartbeat_route_records_artifact() -> None:
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
            last_heartbeat_at=utcnow() - timedelta(minutes=20),
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)

    app = _build_test_app(session_maker)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/boards/{board.id}/execution-runs/{run.id}/heartbeat",
            json={"message": "ping", "source": "operator"},
        )

    assert response.status_code == 201
    assert response.json()["kind"] == "heartbeat"
