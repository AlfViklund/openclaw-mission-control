from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, patch
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.activity_events import ActivityEvent
from app.models.agents import Agent
from app.models.approvals import Approval
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.runs import Run
from app.models.tasks import Task
from app.api.pipeline import execute_next_pipeline_stage
from app.services.pipeline import (
    PipelineRuntimeBlockedError,
    PipelineService,
    get_pipeline_task_summary,
)
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


@pytest.mark.asyncio
async def test_task_summary_prefers_manual_review_action_when_structured_evidence_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            _board, task, agent = await _seed_board_bundle(session)
            task.status = "in_progress"
            task.in_progress_at = task.in_progress_at or task.created_at
            session.add(task)
            session.add(
                ActivityEvent(
                    event_type="task.comment",
                    task_id=task.id,
                    board_id=task.board_id,
                    agent_id=agent.id,
                    message="Implemented with evidence.",
                    payload_json={
                        "kind": "completion_report",
                        "message": "Implemented with evidence.",
                        "completion_report": {
                            "summary": "Implemented with evidence.",
                            "files_touched": ["src/task.ts"],
                            "checks_run": ["npm test"],
                            "checks_result": "passed",
                            "artifacts": [],
                            "known_risks": [],
                        },
                    },
                )
            )
            await session.commit()

            monkeypatch.setattr("app.services.pipeline.shutil.which", lambda _value: "/usr/bin/opencode")
            with patch.object(
                PipelineService,
                "_workspace_path_for_agent",
                AsyncMock(return_value="/tmp"),
            ):
                summary = await get_pipeline_task_summary(session, task_id=task.id)

            assert summary.runtime_ready is True
            assert summary.next_required_stage == "build"
            assert summary.recommended_action == "request_manual_review"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_execute_stage_blocks_new_opencode_runs_when_daily_quota_is_active() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            board, task, agent = await _seed_board_bundle(session)
            task.status = "in_progress"
            task.in_progress_at = task.created_at
            board.execution_runtime_state = {
                "runtime": "opencode_cli",
                "status": "cooldown",
                "failure_kind": "quota_exhausted",
                "cooldown_until": None,
                "cooldown_message": "OpenCode CLI daily limit is active. New runs are blocked until the runtime is reset.",
                "updated_at": task.created_at.isoformat(),
            }
            session.add(board)
            session.add(task)
            await session.commit()

            service = PipelineService(session)

            with patch(
                "app.services.pipeline.validate_pipeline_stage",
                AsyncMock(return_value=type("Validation", (), {"valid": True, "blockers": [], "warnings": []})()),
            ), patch(
                "app.services.pipeline.create_run",
                AsyncMock(),
            ) as create_run_mock, pytest.raises(PipelineRuntimeBlockedError) as exc_info:
                await service.execute_stage(
                    task.id,
                    stage="plan",
                    runtime="opencode_cli",
                    agent_id=agent.id,
                )

            assert exc_info.value.detail["code"] == "runtime_quota_blocked"
            assert exc_info.value.detail["failure_kind"] == "quota_exhausted"
            create_run_mock.assert_not_awaited()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_daily_quota_failure_keeps_manual_reset_path_without_fallback_window() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            board, task, _agent = await _seed_board_bundle(session)
            task.status = "in_progress"
            task.in_progress_at = task.created_at
            session.add(task)
            await session.commit()

            service = PipelineService(session)
            await service._record_runtime_failure_state(
                board=board,
                runtime="opencode_cli",
                model="opencode/qwen",
                failure_kind="quota_exhausted",
                retryable=False,
                error_message="Daily limit reached for OpenCode CLI.",
            )
            await session.refresh(board)

            runtime_state = board.execution_runtime_state or {}
            assert runtime_state.get("status") == "cooldown"
            assert runtime_state.get("failure_kind") == "quota_exhausted"
            assert runtime_state.get("cooldown_until") is None
            assert "daily limit" in str(runtime_state.get("cooldown_message", "")).lower()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_daily_quota_failure_fails_queued_opencode_runs_for_board() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            board, task, agent = await _seed_board_bundle(session)
            task.status = "in_progress"
            task.in_progress_at = task.created_at
            session.add(task)
            queued_run = Run(
                task_id=task.id,
                agent_id=agent.id,
                runtime="opencode_cli",
                stage="build",
                status="queued",
            )
            session.add(queued_run)
            await session.commit()

            service = PipelineService(session)
            await service._record_runtime_failure_state(
                board=board,
                runtime="opencode_cli",
                model="opencode/qwen",
                failure_kind="quota_exhausted",
                retryable=False,
                error_message="Daily limit reached for OpenCode CLI.",
            )
            await session.refresh(queued_run)

            assert queued_run.status == "failed"
            assert queued_run.failure_kind == "quota_exhausted"
            assert queued_run.retryable is False
            assert "daily limit" in (queued_run.error_message or "").lower()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_execute_next_endpoint_returns_structured_409_for_quota_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = SimpleNamespace(id=uuid4(), board_id=uuid4())
    detail = {
        "code": "runtime_quota_blocked",
        "runtime": "opencode_cli",
        "failure_kind": "quota_exhausted",
        "cooldown_until": None,
        "message": "OpenCode CLI daily limit is active. New runs are blocked until the runtime is reset.",
    }
    session = AsyncMock()
    actor = SimpleNamespace(actor_type="agent", agent=SimpleNamespace(id=uuid4()))

    monkeypatch.setattr(
        "app.models.tasks.Task.objects",
        SimpleNamespace(by_id=lambda _id: SimpleNamespace(first=AsyncMock(return_value=task))),
    )
    monkeypatch.setattr(
        "app.api.pipeline.resolve_actor_task_execution_agent",
        AsyncMock(return_value=uuid4()),
    )
    with patch.object(
        PipelineService,
        "execute_next_stage",
        AsyncMock(side_effect=PipelineRuntimeBlockedError(detail)),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await execute_next_pipeline_stage(
                task_id=task.id,
                agent_id=None,
                model=None,
                session=session,  # type: ignore[arg-type]
                _actor=actor,  # type: ignore[arg-type]
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == detail
