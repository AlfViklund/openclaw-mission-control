from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.task_dependencies import TaskDependency
from app.models.tasks import Task
from app.services.agent_work import get_work_snapshot


async def _make_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine


async def _make_session(engine: AsyncEngine) -> AsyncSession:
    return AsyncSession(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_worker_blocked_inbox_task_does_not_wake_agent() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            org_id = uuid4()
            gateway_id = uuid4()
            board_id = uuid4()
            worker_id = uuid4()
            blocked_task_id = uuid4()
            dependency_id = uuid4()

            session.add(Organization(id=org_id, name="org"))
            session.add(
                Gateway(
                    id=gateway_id,
                    organization_id=org_id,
                    name="gateway",
                    url="https://gateway.local",
                    workspace_root="/tmp/workspace",
                )
            )
            session.add(
                Board(
                    id=board_id,
                    organization_id=org_id,
                    gateway_id=gateway_id,
                    name="board",
                    slug="board",
                )
            )
            session.add(
                Agent(
                    id=worker_id,
                    board_id=board_id,
                    gateway_id=gateway_id,
                    name="worker",
                    status="idle",
                )
            )
            session.add(
                Task(
                    id=dependency_id,
                    board_id=board_id,
                    title="dependency",
                    status="in_progress",
                )
            )
            session.add(
                Task(
                    id=blocked_task_id,
                    board_id=board_id,
                    title="blocked inbox",
                    status="inbox",
                    assigned_agent_id=worker_id,
                )
            )
            session.add(
                TaskDependency(
                    board_id=board_id,
                    task_id=blocked_task_id,
                    depends_on_task_id=dependency_id,
                )
            )
            await session.commit()

            snapshot = await get_work_snapshot(session, worker_id)

            assert snapshot["assigned_inbox_task_ids"] == []
            assert snapshot["should_wake"] is False
            assert snapshot["reason"] == "idle_no_work"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_lead_prefers_review_queue_when_only_inbox_tasks_are_blocked() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            org_id = uuid4()
            gateway_id = uuid4()
            board_id = uuid4()
            lead_id = uuid4()
            blocked_task_id = uuid4()
            dependency_id = uuid4()
            review_task_id = uuid4()

            session.add(Organization(id=org_id, name="org"))
            session.add(
                Gateway(
                    id=gateway_id,
                    organization_id=org_id,
                    name="gateway",
                    url="https://gateway.local",
                    workspace_root="/tmp/workspace",
                )
            )
            session.add(
                Board(
                    id=board_id,
                    organization_id=org_id,
                    gateway_id=gateway_id,
                    name="board",
                    slug="board",
                )
            )
            session.add(
                Agent(
                    id=lead_id,
                    board_id=board_id,
                    gateway_id=gateway_id,
                    name="lead",
                    status="online",
                    is_board_lead=True,
                )
            )
            session.add(
                Task(
                    id=dependency_id,
                    board_id=board_id,
                    title="dependency",
                    status="in_progress",
                )
            )
            session.add(
                Task(
                    id=blocked_task_id,
                    board_id=board_id,
                    title="blocked inbox",
                    status="inbox",
                    assigned_agent_id=lead_id,
                )
            )
            session.add(
                Task(
                    id=review_task_id,
                    board_id=board_id,
                    title="review task",
                    status="review",
                    assigned_agent_id=lead_id,
                )
            )
            session.add(
                TaskDependency(
                    board_id=board_id,
                    task_id=blocked_task_id,
                    depends_on_task_id=dependency_id,
                )
            )
            await session.commit()

            snapshot = await get_work_snapshot(session, lead_id)

            assert snapshot["assigned_inbox_task_ids"] == []
            assert snapshot["review_tasks_count"] == 1
            assert snapshot["should_wake"] is True
            assert snapshot["reason"] == "review_queue"
    finally:
        await engine.dispose()
