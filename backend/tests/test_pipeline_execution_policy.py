from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.agents import Agent
from app.models.approvals import Approval
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.runs import Run
from app.models.tasks import Task
from app.services.pipeline import PipelineService, get_pipeline_task_summary
from app.services.pipeline_validation import validate_pipeline_stage


async def _make_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine


async def _make_session(engine: AsyncEngine) -> AsyncSession:
    return AsyncSession(engine, expire_on_commit=False)


async def _seed_board_bundle(session: AsyncSession) -> tuple[Board, Task, Agent]:
    org_id = uuid4()
    gateway_id = uuid4()
    board_id = uuid4()
    agent_id = uuid4()
    task_id = uuid4()

    session.add(Organization(id=org_id, name="org"))
    session.add(
        Gateway(
            id=gateway_id,
            organization_id=org_id,
            name="gateway",
            url="https://gateway.local",
            workspace_root="/tmp/workspace",
        ),
    )
    board = Board(
        id=board_id,
        organization_id=org_id,
        name="board",
        slug="board",
        description="CLI-first board",
        gateway_id=gateway_id,
    )
    agent = Agent(
        id=agent_id,
        board_id=board_id,
        gateway_id=gateway_id,
        name="Developer",
        status="online",
    )
    task = Task(
        id=task_id,
        board_id=board_id,
        title="Implement task",
        status="inbox",
        assigned_agent_id=agent_id,
    )
    session.add(board)
    session.add(agent)
    session.add(task)
    await session.commit()
    return board, task, agent


@pytest.mark.asyncio
async def test_build_stage_allows_without_explicit_pipeline_approval_marker() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            _board, task, agent = await _seed_board_bundle(session)
            session.add(
                Run(
                    task_id=task.id,
                    agent_id=agent.id,
                    runtime="opencode_cli",
                    stage="plan",
                    status="succeeded",
                )
            )
            await session.commit()

            validation = await validate_pipeline_stage(session, task.id, "build")

            assert validation.valid is True
            assert validation.requires_approval is False
            assert validation.blockers == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_build_stage_requires_existing_high_risk_pipeline_approval_marker() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            board, task, agent = await _seed_board_bundle(session)
            session.add(
                Run(
                    task_id=task.id,
                    agent_id=agent.id,
                    runtime="opencode_cli",
                    stage="plan",
                    status="succeeded",
                )
            )
            session.add(
                Approval(
                    id=uuid4(),
                    board_id=board.id,
                    task_id=task.id,
                    action_type="pipeline.build",
                    confidence=95,
                    status="pending",
                )
            )
            await session.commit()

            validation = await validate_pipeline_stage(session, task.id, "build")

            assert validation.valid is False
            assert validation.requires_approval is True
            assert validation.approval_reason == "Build requires an approved pipeline.build approval."
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_task_summary_reports_cli_blocker_when_opencode_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            _board, task, _agent = await _seed_board_bundle(session)
            monkeypatch.setattr("app.services.pipeline.shutil.which", lambda _value: None)

            summary = await get_pipeline_task_summary(session, task_id=task.id)

            assert summary.recommended_runtime == "opencode_cli"
            assert summary.next_required_stage == "plan"
            assert summary.runtime_ready is False
            assert summary.runtime_blocker_code == "opencode_missing"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_task_summary_marks_assigned_inbox_as_start_work() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            _board, task, _agent = await _seed_board_bundle(session)

            summary = await get_pipeline_task_summary(session, task_id=task.id)

            assert summary.work_state == "assigned_inbox"
            assert summary.can_start_work is True
            assert summary.use_start_work is True
            assert summary.recommended_action == "start_work"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_start_work_moves_assigned_inbox_to_in_progress_without_runs() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            _board, task, agent = await _seed_board_bundle(session)
            service = PipelineService(session)

            result = await service.start_work(task.id, actor_agent=agent)
            await session.refresh(task)

            assert result["status"] == "started"
            assert task.status == "in_progress"
            assert task.in_progress_at is not None
            runs = (await session.exec(select(Run).where(Run.task_id == task.id))).all()
            assert runs == []
    finally:
        await engine.dispose()
