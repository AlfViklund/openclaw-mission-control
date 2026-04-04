from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_board_for_actor_read, get_board_for_actor_write
from app.api.execution_runs import router as execution_runs_router
from app.db.session import get_session
from app.models.boards import Board
from app.models.execution_runs import ExecutionRun
from app.models.organizations import Organization
from app.services.execution_dispatch import (
    QueuedExecutionRunDispatch,
    enqueue_execution_dispatch,
    process_execution_dispatch_queue_task,
)
from app.services.queue import QueuedTask


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
        description="Board for execution dispatch queue tests.",
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
async def test_queue_execution_run_dispatch_route_enqueues_payload(
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
        run = ExecutionRun(board_id=board.id)
        session.add(run)
        await session.commit()
        await session.refresh(run)

    captured: list[QueuedExecutionRunDispatch] = []

    def _capture_enqueue(payload: QueuedExecutionRunDispatch) -> bool:
        captured.append(payload)
        return True

    monkeypatch.setattr("app.api.execution_runs.enqueue_execution_dispatch", _capture_enqueue)

    app = _build_test_app(session_maker)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/boards/{board.id}/execution-runs/{run.id}/dispatch/queue",
        )

    assert response.status_code == 202
    assert response.json() == {"status": "queued"}
    assert captured == [QueuedExecutionRunDispatch(board_id=board.id, run_id=run.id)]


@pytest.mark.asyncio
async def test_execution_dispatch_worker_delegates_to_orchestration(
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
        run = ExecutionRun(board_id=board.id, runtime_session_key="opencode:run-1")
        session.add(run)
        await session.commit()
        await session.refresh(run)

    calls: list[dict[str, object]] = []

    async def _capture_dispatch(self, *, board_id: UUID, run_id: UUID, context: str | None = None):
        calls.append({"board_id": board_id, "run_id": run_id, "context": context})
        return object()

    monkeypatch.setattr(
        "app.services.execution_dispatch.async_session_maker",
        session_maker,
    )
    monkeypatch.setattr(
        "app.services.execution_dispatch.ExecutionOrchestrationService.dispatch_run_instruction",
        _capture_dispatch,
    )

    task = QueuedTask(
        task_type="execution_run_dispatch",
        payload={"board_id": str(board.id), "run_id": str(run.id), "context": "resume"},
        created_at=datetime.now(UTC),
    )
    await process_execution_dispatch_queue_task(task)

    assert calls == [{"board_id": board.id, "run_id": run.id, "context": "resume"}]
