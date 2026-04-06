from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.models.activity_events import ActivityEvent
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.tasks import Task
from app.services.pipeline import PipelineService, get_pipeline_task_summary
from app.services.pipeline_runtime_state import clear_legacy_playwright_runtime_state, runtime_state_for_board


async def _make_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine


async def _make_session(engine: AsyncEngine) -> AsyncSession:
    return AsyncSession(engine, expire_on_commit=False)


async def _seed_board_context(
    session: AsyncSession,
    *,
    runtime_state: dict | None = None,
    include_completion_report: bool = True,
) -> tuple[Board, Agent, Agent, Task]:
    org_id = uuid4()
    gateway_id = uuid4()
    board_id = uuid4()
    lead_id = uuid4()
    worker_id = uuid4()
    task_id = uuid4()

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
    board = Board(
        id=board_id,
        organization_id=org_id,
        gateway_id=gateway_id,
        name="board",
        slug="board",
        execution_runtime_state=runtime_state
        or {
            "runtime": "opencode_cli",
            "status": "cooldown",
            "failure_kind": "quota_exhausted",
            "cooldown_until": (utcnow() + timedelta(minutes=30)).isoformat(),
            "cooldown_message": "Provider cooldown in effect.",
            "provider": "opencode_cli",
            "model": "opencode/qwen3.6-plus-free",
            "updated_at": utcnow().isoformat(),
        },
    )
    lead = Agent(
        id=lead_id,
        board_id=board_id,
        gateway_id=gateway_id,
        name="lead",
        status="online",
        is_board_lead=True,
    )
    worker = Agent(
        id=worker_id,
        board_id=board_id,
        gateway_id=gateway_id,
        name="worker",
        status="online",
    )
    task = Task(
        id=task_id,
        board_id=board_id,
        title="task",
        status="in_progress",
        assigned_agent_id=worker_id,
        in_progress_at=utcnow(),
    )

    session.add(board)
    session.add(lead)
    session.add(worker)
    session.add(task)
    if include_completion_report:
        session.add(
            ActivityEvent(
                event_type="task.comment",
                task_id=task_id,
                board_id=board_id,
                agent_id=worker_id,
                message="Implementation complete with evidence.",
                payload_json={
                    "kind": "completion_report",
                    "message": "Implementation complete with evidence.",
                    "completion_report": {
                        "summary": "Implemented the task.",
                        "files_touched": ["src/app.ts"],
                        "checks_run": ["npm test"],
                        "checks_result": "passed",
                        "artifacts": ["coverage/report.txt"],
                        "known_risks": [],
                    },
                },
            )
        )
    await session.commit()
    return board, lead, worker, task


@pytest.mark.asyncio
async def test_task_summary_exposes_degraded_review_state() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            _board, _lead, _worker, task = await _seed_board_context(session)

            summary = await get_pipeline_task_summary(session, task_id=task.id)

            assert summary.runtime_ready is False
            assert summary.execution_mode == "degraded"
            assert summary.degraded_allowed is True
            assert summary.next_required_stage == "build"
            assert summary.recommended_action == "request_degraded_review"
            assert summary.latest_completion_report is not None
            assert summary.cooldown_message == "Provider cooldown in effect."
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_request_review_uses_degraded_flow_without_running_plan() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            _board, lead, worker, task = await _seed_board_context(session)
            service = PipelineService(session)

            with patch.object(
                PipelineService,
                "execute_next_stage",
                AsyncMock(),
            ) as execute_next_mock, patch.object(
                PipelineService,
                "_notify_lead_review_handoff",
                AsyncMock(),
            ):
                result = await service.request_review(task.id, agent_id=worker.id)

            refreshed = (
                await session.exec(select(Task).where(Task.id == task.id))
            ).first()
            assert refreshed is not None
            assert execute_next_mock.await_count == 0
            assert refreshed.status == "review"
            assert refreshed.review_mode == "degraded_pipeline"
            assert refreshed.assigned_agent_id == lead.id
            assert result["review_mode"] == "degraded_pipeline"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_request_review_uses_manual_evidence_flow_when_runtime_is_healthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            ready_runtime_state = {
                "runtime": "opencode_cli",
                "status": "ready",
                "failure_kind": None,
                "cooldown_until": None,
                "cooldown_message": None,
                "provider": "opencode_cli",
                "model": "opencode/qwen3.6-plus-free",
                "updated_at": utcnow().isoformat(),
            }
            _board, lead, worker, task = await _seed_board_context(
                session,
                runtime_state=ready_runtime_state,
            )
            service = PipelineService(session)

            monkeypatch.setattr("app.services.pipeline.shutil.which", lambda _value: "/usr/bin/opencode")
            with patch.object(
                PipelineService,
                "_workspace_path_for_agent",
                AsyncMock(return_value="/tmp"),
            ), patch.object(
                PipelineService,
                "execute_next_stage",
                AsyncMock(),
            ) as execute_next_mock, patch.object(
                PipelineService,
                "_notify_lead_review_handoff",
                AsyncMock(),
            ):
                summary = await service.get_task_summary(task.id)
                result = await service.request_review(task.id, agent_id=worker.id)

            refreshed = (
                await session.exec(select(Task).where(Task.id == task.id))
            ).first()
            assert refreshed is not None
            assert summary.recommended_action == "request_manual_review"
            assert execute_next_mock.await_count == 0
            assert refreshed.status == "review"
            assert refreshed.review_mode == "manual_evidence"
            assert refreshed.assigned_agent_id == lead.id
            assert result["review_mode"] == "manual_evidence"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_request_review_rejects_plain_comment_without_structured_completion_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            ready_runtime_state = {
                "runtime": "opencode_cli",
                "status": "ready",
                "failure_kind": None,
                "cooldown_until": None,
                "cooldown_message": None,
                "provider": "opencode_cli",
                "model": "opencode/qwen3.6-plus-free",
                "updated_at": utcnow().isoformat(),
            }
            _board, _lead, worker, task = await _seed_board_context(
                session,
                runtime_state=ready_runtime_state,
                include_completion_report=False,
            )
            session.add(
                ActivityEvent(
                    event_type="task.comment",
                    task_id=task.id,
                    board_id=task.board_id,
                    agent_id=worker.id,
                    message="Done. Ready for review.",
                    payload_json={"kind": "comment", "message": "Done. Ready for review."},
                )
            )
            await session.commit()

            service = PipelineService(session)
            monkeypatch.setattr("app.services.pipeline.shutil.which", lambda _value: "/usr/bin/opencode")
            with patch.object(
                PipelineService,
                "_workspace_path_for_agent",
                AsyncMock(return_value="/tmp"),
            ):
                summary = await service.get_task_summary(task.id)

                with pytest.raises(ValueError, match="Task is not ready for review yet."):
                    await service.request_review(task.id, agent_id=worker.id)

            assert summary.latest_completion_report is None
            assert summary.recommended_action == "run_next_step"
    finally:
        await engine.dispose()


def test_clear_legacy_playwright_runtime_state_resets_stale_degradation() -> None:
    board = Board(
        id=uuid4(),
        organization_id=uuid4(),
        name="board",
        slug="board",
        execution_runtime_state={
            "runtime": "opencode_cli",
            "status": "degraded",
            "failure_kind": "permissions_error",
            "cooldown_message": "Playwright not installed: sh: 1: playwright: Permission denied",
        },
    )

    changed = clear_legacy_playwright_runtime_state(board)

    assert changed is True
    assert runtime_state_for_board(board)["status"] == "ready"
