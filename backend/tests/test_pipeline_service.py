"""Tests for PipelineService execute_stage, auto_run_next_stage, resume_after_approval."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.pipeline import (
    ALL_STAGE_ORDER,
    NORMAL_STAGE_ORDER,
    PipelineService,
    _classify_run_failure,
    _retry_delay_for_failure,
)


def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.exec = AsyncMock()
    return session


class TestAutoRunNextStage:
    """Tests for _auto_run_next_stage logic."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_next_stage(self) -> None:
        session = _make_session()
        run = SimpleNamespace(
            id=uuid4(),
            task_id=uuid4(),
            agent_id=uuid4(),
            runtime="acp",
            stage="build",
            status="succeeded",
            model=None,
        )

        with patch(
            "app.models.runs.Run.objects",
            new_callable=lambda: SimpleNamespace(
                by_id=lambda _id: SimpleNamespace(first=AsyncMock(return_value=run))
            ),
        ):
            svc = PipelineService(session)
            result = await svc._auto_run_next_stage(run.id)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_run_not_succeeded(self) -> None:
        session = _make_session()
        run = SimpleNamespace(
            id=uuid4(),
            task_id=uuid4(),
            agent_id=uuid4(),
            runtime="acp",
            stage="plan",
            status="failed",
            model=None,
        )

        with patch(
            "app.models.runs.Run.objects",
            new_callable=lambda: SimpleNamespace(
                by_id=lambda _id: SimpleNamespace(first=AsyncMock(return_value=run))
            ),
        ):
            svc = PipelineService(session)
            result = await svc._auto_run_next_stage(run.id)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_run_is_none(self) -> None:
        session = _make_session()

        with patch(
            "app.models.runs.Run.objects",
            new_callable=lambda: SimpleNamespace(
                by_id=lambda _id: SimpleNamespace(first=AsyncMock(return_value=None))
            ),
        ):
            svc = PipelineService(session)
            result = await svc._auto_run_next_stage(uuid4())

        assert result is None

    @pytest.mark.asyncio
    async def test_auto_runs_build_after_plan_for_normal_task(self) -> None:
        session = _make_session()
        task = SimpleNamespace(id=uuid4(), board_id=uuid4(), status="in_progress")
        board = SimpleNamespace(id=task.board_id, execution_policy={"auto_run_next_stage": True})
        plan_run = SimpleNamespace(
            id=uuid4(),
            task_id=task.id,
            agent_id=uuid4(),
            runtime="opencode_cli",
            stage="plan",
            status="succeeded",
            model=None,
            run_metadata={},
        )
        build_run = SimpleNamespace(
            id=uuid4(),
            task_id=task.id,
            agent_id=plan_run.agent_id,
            runtime=plan_run.runtime,
            stage="build",
            status="queued",
            model=None,
            run_metadata={},
        )
        runs_by_id = {
            plan_run.id: plan_run,
            build_run.id: build_run,
        }

        def _by_id(run_id):
            return SimpleNamespace(first=AsyncMock(return_value=runs_by_id.get(run_id)))

        with patch(
            "app.models.runs.Run.objects",
            new_callable=lambda: SimpleNamespace(
                by_id=_by_id
            ),
        ), patch(
            "app.models.tasks.Task.objects",
            new_callable=lambda: SimpleNamespace(
                by_id=lambda _id: SimpleNamespace(first=AsyncMock(return_value=task))
            ),
        ), patch(
            "app.models.boards.Board.objects",
            new_callable=lambda: SimpleNamespace(
                by_id=lambda _id: SimpleNamespace(first=AsyncMock(return_value=board))
            ),
        ), patch(
            "app.services.pipeline.create_run",
            AsyncMock(return_value=build_run),
        ), patch(
            "app.services.pipeline.get_active_task_stage_run",
            AsyncMock(return_value=None),
        ) as create_run_mock, patch.object(
            PipelineService,
            "_drain_board_queue",
            AsyncMock(return_value={"run_id": str(build_run.id), "status": "running"}),
        ) as drain_mock, patch.object(
            PipelineService,
            "_build_requires_approval",
            AsyncMock(return_value=False),
        ):
            svc = PipelineService(session)
            result = await svc._auto_run_next_stage(plan_run.id)

        assert create_run_mock.await_count == 1
        assert create_run_mock.await_args_list[0].kwargs["stage"] == "build"
        drain_mock.assert_awaited_once()
        assert result == {"run_id": str(build_run.id), "status": "running"}

    @pytest.mark.asyncio
    async def test_execute_stage_queues_when_board_already_has_running_run(self) -> None:
        session = _make_session()
        task = SimpleNamespace(id=uuid4(), board_id=uuid4(), status="inbox", assigned_agent_id=uuid4(), in_progress_at=None, review_mode=None)
        board = SimpleNamespace(id=task.board_id, gateway_id=None, is_paused=False, execution_policy={"auto_run_next_stage": True})
        agent = SimpleNamespace(id=task.assigned_agent_id, gateway_id=uuid4())
        queued_run = SimpleNamespace(
            id=uuid4(),
            task_id=task.id,
            agent_id=agent.id,
            runtime="opencode_cli",
            stage="plan",
            status="queued",
            model=None,
            run_metadata={},
        )
        active_run = SimpleNamespace(id=uuid4())

        with patch(
            "app.services.pipeline.validate_pipeline_stage",
            AsyncMock(return_value=SimpleNamespace(blockers=[], warnings=[])),
        ), patch(
            "app.models.tasks.Task.objects",
            new_callable=lambda: SimpleNamespace(by_id=lambda _id: SimpleNamespace(first=AsyncMock(return_value=task))),
        ), patch(
            "app.models.boards.Board.objects",
            new_callable=lambda: SimpleNamespace(by_id=lambda _id: SimpleNamespace(first=AsyncMock(return_value=board))),
        ), patch(
            "app.models.agents.Agent.objects",
            new_callable=lambda: SimpleNamespace(
                by_id=lambda _id: SimpleNamespace(first=AsyncMock(return_value=agent)),
                filter_by=lambda **_kw: SimpleNamespace(first=AsyncMock(return_value=agent)),
            ),
        ), patch(
            "app.services.pipeline.create_run",
            AsyncMock(return_value=queued_run),
        ), patch(
            "app.services.pipeline.get_active_task_stage_run",
            AsyncMock(return_value=None),
        ), patch(
            "app.services.pipeline.get_running_board_run",
            AsyncMock(return_value=active_run),
        ), patch(
            "app.services.pipeline.get_board_run_queue_position",
            AsyncMock(return_value=1),
        ), patch(
            "app.services.pipeline.mark_run_queued",
            AsyncMock(return_value=queued_run),
        ) as mark_queued_mock:
            svc = PipelineService(session)
            result = await svc.execute_stage(task.id, stage="plan", runtime="opencode_cli", agent_id=agent.id)

        mark_queued_mock.assert_awaited_once()
        assert result["status"] == "queued"
        assert result["queue_position"] == 1

    @pytest.mark.asyncio
    async def test_execute_stage_reuses_existing_active_task_stage_run(self) -> None:
        session = _make_session()
        task = SimpleNamespace(id=uuid4(), board_id=uuid4(), status="inbox", assigned_agent_id=uuid4(), in_progress_at=None, review_mode=None)
        board = SimpleNamespace(id=task.board_id, gateway_id=None, is_paused=False, execution_policy={"auto_run_next_stage": True})
        agent = SimpleNamespace(id=task.assigned_agent_id, gateway_id=uuid4())
        queued_run = SimpleNamespace(
            id=uuid4(),
            task_id=task.id,
            agent_id=agent.id,
            runtime="opencode_cli",
            stage="plan",
            status="queued",
            model=None,
            run_metadata={"queue_reason": "board_has_active_run"},
        )

        with patch(
            "app.services.pipeline.validate_pipeline_stage",
            AsyncMock(return_value=SimpleNamespace(blockers=[], warnings=[])),
        ), patch(
            "app.models.tasks.Task.objects",
            new_callable=lambda: SimpleNamespace(by_id=lambda _id: SimpleNamespace(first=AsyncMock(return_value=task))),
        ), patch(
            "app.models.boards.Board.objects",
            new_callable=lambda: SimpleNamespace(by_id=lambda _id: SimpleNamespace(first=AsyncMock(return_value=board))),
        ), patch(
            "app.models.agents.Agent.objects",
            new_callable=lambda: SimpleNamespace(
                by_id=lambda _id: SimpleNamespace(first=AsyncMock(return_value=agent)),
                filter_by=lambda **_kw: SimpleNamespace(first=AsyncMock(return_value=agent)),
            ),
        ), patch(
            "app.services.pipeline.get_active_task_stage_run",
            AsyncMock(return_value=queued_run),
        ), patch(
            "app.services.pipeline.get_board_id_for_run",
            AsyncMock(return_value=board.id),
        ), patch(
            "app.services.pipeline.get_board_run_queue_position",
            AsyncMock(return_value=1),
        ), patch(
            "app.services.pipeline.create_run",
            AsyncMock(),
        ) as create_run_mock:
            svc = PipelineService(session)
            result = await svc.execute_stage(task.id, stage="plan", runtime="opencode_cli", agent_id=agent.id)

        create_run_mock.assert_not_awaited()
        assert result["run_id"] == str(queued_run.id)
        assert result["status"] == "queued"
        assert result["queue_position"] == 1
        assert result["queue_reason"] == "board_has_active_run"

    @pytest.mark.asyncio
    async def test_stops_for_pending_build_approval(self) -> None:
        session = _make_session()
        task = SimpleNamespace(id=uuid4(), board_id=uuid4(), status="in_progress")
        board = SimpleNamespace(execution_policy={"auto_run_next_stage": True})
        run = SimpleNamespace(
            id=uuid4(),
            task_id=task.id,
            agent_id=uuid4(),
            runtime="opencode_cli",
            stage="plan",
            status="succeeded",
            model=None,
            run_metadata={},
        )

        with patch(
            "app.models.runs.Run.objects",
            new_callable=lambda: SimpleNamespace(
                by_id=lambda _id: SimpleNamespace(first=AsyncMock(return_value=run))
            ),
        ), patch(
            "app.models.tasks.Task.objects",
            new_callable=lambda: SimpleNamespace(
                by_id=lambda _id: SimpleNamespace(first=AsyncMock(return_value=task))
            ),
        ), patch(
            "app.models.boards.Board.objects",
            new_callable=lambda: SimpleNamespace(
                by_id=lambda _id: SimpleNamespace(first=AsyncMock(return_value=board))
            ),
        ), patch.object(
            PipelineService,
            "_build_requires_approval",
            AsyncMock(return_value=True),
        ), patch.object(
            PipelineService,
            "_has_approved_build_approval",
            AsyncMock(return_value=False),
        ):
            svc = PipelineService(session)
            result = await svc._auto_run_next_stage(run.id)

        assert result == {
            "auto_triggered": False,
            "stage": "build",
            "reason": "awaiting_approval",
        }


class TestResumeAfterApproval:
    """Tests for resume_after_approval logic."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_plan_run(self) -> None:
        session = _make_session()
        task_id = uuid4()

        chain = SimpleNamespace(
            order_by=lambda _x: SimpleNamespace(first=AsyncMock(return_value=None))
        )

        with patch(
            "app.models.runs.Run.objects",
            new_callable=lambda: SimpleNamespace(
                filter_by=lambda **_kw: chain
            ),
        ):
            svc = PipelineService(session)
            result = await svc.resume_after_approval(task_id)

        assert result is None


class TestStageOrder:
    """Tests for STAGE_ORDER consistency."""

    def test_plan_comes_before_build(self) -> None:
        assert NORMAL_STAGE_ORDER.index("plan") < NORMAL_STAGE_ORDER.index("build")

    def test_pipeline_stops_at_build(self) -> None:
        assert ALL_STAGE_ORDER == ["plan", "build"]
        assert NORMAL_STAGE_ORDER == ["plan", "build"]


class TestRuntimeFailureClassification:
    def test_transient_rate_limit_is_retryable_quota_exhausted(self) -> None:
        failure_kind, retryable = _classify_run_failure(
            "Upstream error from Alibaba: Request rate increased too quickly.",
            runtime="opencode_cli",
            stage="build",
        )

        assert failure_kind == "quota_exhausted"
        assert retryable is True

    def test_daily_limit_quota_remains_non_retryable(self) -> None:
        failure_kind, retryable = _classify_run_failure(
            "Daily limit reached for this provider.",
            runtime="opencode_cli",
            stage="build",
        )

        assert failure_kind == "quota_exhausted"
        assert retryable is False


class TestRetryDelayPolicy:
    def test_retry_delay_enabled_for_retryable_opencode_quota_failure(self) -> None:
        delay = _retry_delay_for_failure(
            runtime="opencode_cli",
            failure_kind="quota_exhausted",
            retryable=True,
            attempt_index=0,
        )

        assert delay == 15.0

    def test_retry_delay_disabled_for_non_retryable_failure(self) -> None:
        delay = _retry_delay_for_failure(
            runtime="opencode_cli",
            failure_kind="quota_exhausted",
            retryable=False,
            attempt_index=0,
        )

        assert delay is None


class TestRunWorkspaceBinding:
    """Tests for run workspace_path binding via run_metadata."""

    def test_run_metadata_stores_workspace_path(self) -> None:
        """Verify that create_run accepts and stores workspace_path in run_metadata."""
        from app.models.runs import Run
        run = Run(
            task_id=uuid4(),
            agent_id=uuid4(),
            runtime="acp",
            stage="build",
            status="queued",
            run_metadata={"workspace_path": "/tmp/workspace/agent-x"},
        )
        assert run.run_metadata.get("workspace_path") == "/tmp/workspace/agent-x"

    def test_run_metadata_empty_by_default(self) -> None:
        """Verify run_metadata defaults to empty dict."""
        from app.models.runs import Run
        run = Run(
            task_id=uuid4(),
            agent_id=uuid4(),
            runtime="acp",
            stage="plan",
            status="queued",
        )
        assert run.run_metadata == {}

    def test_run_metadata_can_be_empty_without_workspace(self) -> None:
        """Verify that run metadata may omit a workspace path."""
        from app.services.pipeline import PipelineService
        from app.services.runs import create_run

        session = _make_session()

        async def _run_test() -> None:
            run = await create_run(
                session,
                task_id=uuid4(),
                agent_id=uuid4(),
                runtime="acp",
                stage="build",
            )
            assert not run.run_metadata.get("workspace_path")

        import asyncio
        asyncio.run(_run_test())


class TestReviewHandoff:
    @pytest.mark.asyncio
    async def test_stage_success_does_not_auto_move_task_to_review(self) -> None:
        session = _make_session()
        svc = PipelineService(session)
        task = SimpleNamespace(
            id=uuid4(),
            board_id=uuid4(),
            title="Review me",
            description="Ship it",
            status="in_progress",
            assigned_agent_id=uuid4(),
            updated_at=None,
        )
        board = SimpleNamespace(id=task.board_id, name="CardFlow")
        await svc._update_task_after_success(
            task=task,
            stage="build",
            acting_agent=SimpleNamespace(id=task.assigned_agent_id),
            board=board,
        )

        assert task.status == "in_progress"
