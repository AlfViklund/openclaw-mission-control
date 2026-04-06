"""Pipeline orchestration service for task-first plan/build execution."""

from __future__ import annotations

import asyncio
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import desc
from sqlmodel import col, select

from app.core.time import utcnow
from app.models.activity_events import ActivityEvent
from app.models.agents import Agent
from app.models.approvals import Approval
from app.models.boards import Board
from app.models.runs import Run
from app.models.tasks import Task
from app.schemas.pipeline import (
    CompletionReportRead,
    PipelineStageStateRead,
    PipelineTaskSummaryRead,
)
from app.schemas.runs import RunRead
from app.services.activity_log import record_activity
from app.services.pipeline_policy import (
    board_execution_policy,
    build_approval_mode,
    default_pipeline_runtime,
)
from app.services.pipeline_runtime_state import (
    clear_runtime_state,
    parse_cooldown_until,
    runtime_state_for_board,
    set_runtime_state,
)
from app.services.pipeline_validation import validate_pipeline_stage
from app.services.runs import (
    claim_next_queued_board_run,
    complete_run,
    create_run,
    get_board_id_for_run,
    get_board_run_queue_position,
    get_running_board_run,
    mark_run_queued,
    start_run,
)
from app.services.task_dependencies import (
    blocked_by_dependency_ids,
    dependency_ids_by_task_id,
    dependency_status_by_id,
)
from app.services.runtime_adapters.base import RunResult

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger(__name__)

NORMAL_STAGE_ORDER = ["plan", "build"]
ALL_STAGE_ORDER = ["plan", "build"]

STAGE_TO_TASK_STATUS = {
    "plan": "in_progress",
    "build": "in_progress",
}

STAGE_PROMPTS = {
    "plan": "Create a detailed implementation plan. Do not modify files.",
    "build": "Implement the task according to the plan. Make file changes and run checks.",
}

STAGE_TO_RUNTIME_AGENT = {
    "plan": "plan",
    "build": "build",
}

RUN_FAILURE_PATTERNS = {
    "quota_exhausted": (
        "quota",
        "daily limit",
        "credits",
        "billing",
    ),
    "binary_missing": (
        "cli not found",
        "no such file or directory: 'opencode'",
        "opencode cli not found",
    ),
    "workspace_missing": (
        "workspace",
        "cwd",
        "working directory",
    ),
    "permissions_error": (
        "permission denied",
        "operation not permitted",
        "eacces",
        "eperm",
    ),
    "timeout": (
        "timed out",
        "timeout",
    ),
}
TRANSIENT_RATE_LIMIT_PATTERNS = (
    "rate limit",
    "too many requests",
    "rate increased too quickly",
)
RUN_FAILURE_RETRYABLE = {
    "timeout": True,
    "quota_exhausted": False,
    "binary_missing": False,
    "workspace_missing": False,
    "permissions_error": False,
    "execution_error": True,
    "unknown": False,
}
OPENCODE_RETRY_DELAYS_SECONDS = (15.0, 30.0)
DEGRADED_RUNTIME_FAILURE_KINDS = {
    "quota_exhausted",
    "timeout",
    "binary_missing",
    "workspace_missing",
    "permissions_error",
}


def _resolve_local_workspace_path(workspace_path: str | None) -> str | None:
    """Resolve a workspace path for local execution inside the backend container."""
    if not workspace_path:
        return None
    return str(Path(workspace_path).expanduser())


def _classify_run_failure(error_message: str | None, *, runtime: str, stage: str) -> tuple[str, bool]:
    normalized = (error_message or "").strip().lower()
    if runtime == "opencode_cli":
        if any(pattern in normalized for pattern in TRANSIENT_RATE_LIMIT_PATTERNS):
            return "quota_exhausted", True
        for failure_kind, patterns in RUN_FAILURE_PATTERNS.items():
            if any(pattern in normalized for pattern in patterns):
                return failure_kind, RUN_FAILURE_RETRYABLE[failure_kind]
    if "timed out" in normalized or "timeout" in normalized:
        return "timeout", RUN_FAILURE_RETRYABLE["timeout"]
    if normalized:
        return "execution_error", RUN_FAILURE_RETRYABLE["execution_error"]
    return "unknown", RUN_FAILURE_RETRYABLE["unknown"]


def _retry_delay_for_failure(
    *,
    runtime: str,
    failure_kind: str | None,
    retryable: bool | None,
    attempt_index: int,
) -> float | None:
    if runtime != "opencode_cli" or not retryable:
        return None
    if failure_kind not in {"quota_exhausted", "timeout"}:
        return None
    if attempt_index >= len(OPENCODE_RETRY_DELAYS_SECONDS):
        return None
    return OPENCODE_RETRY_DELAYS_SECONDS[attempt_index]


def _parse_runtime_state_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _is_degraded_runtime_failure(failure_kind: str | None) -> bool:
    return failure_kind in DEGRADED_RUNTIME_FAILURE_KINDS


class PipelineService:
    """Orchestrates pipeline stage execution for tasks with real runtime dispatch."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def start_work(
        self,
        task_id: UUID,
        *,
        actor_agent: Agent | None = None,
    ) -> dict[str, Any]:
        """Claim an assigned inbox task and mark it in progress without creating a run."""
        task = await Task.objects.by_id(task_id).first(self._session)
        if task is None:
            raise ValueError(f"Task {task_id} not found")
        if task.status != "inbox":
            return {
                "status": "noop",
                "task_id": str(task.id),
                "task_status": task.status,
                "task_summary": (await self.get_task_summary(task_id)).model_dump(mode="json"),
            }
        if task.assigned_agent_id is None:
            raise ValueError("Only assigned inbox tasks can be started.")
        if actor_agent is not None and not actor_agent.is_board_lead and actor_agent.id != task.assigned_agent_id:
            raise ValueError("Only the assigned worker or board lead can start work.")
        if not await self._can_start_work(task=task):
            raise ValueError("Task is blocked by incomplete dependencies.")

        validation = await validate_pipeline_stage(self._session, task_id, "plan")
        if validation.blockers:
            raise ValueError("; ".join(validation.blockers))

        task.status = "in_progress"
        task.review_mode = None
        task.in_progress_at = task.in_progress_at or utcnow()
        task.updated_at = utcnow()
        self._session.add(task)
        record_activity(
            self._session,
            event_type="task.status_changed",
            task_id=task.id,
            message=f"Task moved to in_progress: {task.title}.",
            agent_id=actor_agent.id if actor_agent is not None else task.assigned_agent_id,
            board_id=task.board_id,
        )
        await self._session.commit()
        await self._session.refresh(task)
        return {
            "status": "started",
            "task_id": str(task.id),
            "task_status": task.status,
            "task_summary": (await self.get_task_summary(task_id)).model_dump(mode="json"),
        }

    async def _task_has_started_work(
        self,
        *,
        task: Task,
        latest_completion_report: CompletionReportRead | None,
    ) -> bool:
        if task.status in {"in_progress", "review", "done"}:
            return True
        if task.in_progress_at is not None or task.previous_in_progress_at is not None:
            return True
        return latest_completion_report is not None

    async def _queue_state_for_task(
        self,
        *,
        task_id: UUID,
    ) -> tuple[str | None, int | None]:
        queued_run = await (
            Run.objects.filter_by(task_id=task_id, status="queued")
            .order_by(desc(col(Run.created_at)))
            .first(self._session)
        )
        if queued_run is not None:
            board_id = await get_board_id_for_run(self._session, queued_run)
            position = (
                await get_board_run_queue_position(self._session, board_id=board_id, run_id=queued_run.id)
                if board_id is not None
                else None
            )
            return "queued", position
        running_run = await (
            Run.objects.filter_by(task_id=task_id, status="running")
            .order_by(desc(col(Run.created_at)))
            .first(self._session)
        )
        if running_run is not None:
            return "running", None
        return None, None

    def _task_work_state(self, *, task: Task) -> str:
        if task.status == "in_progress":
            return "in_progress"
        if task.status == "review":
            return "review_queue"
        if task.status == "inbox" and task.assigned_agent_id is not None:
            return "assigned_inbox"
        return "idle_no_work"

    async def _can_start_work(self, *, task: Task) -> bool:
        if task.status != "inbox" or task.assigned_agent_id is None or task.board_id is None:
            return False
        deps_by_task_id = await dependency_ids_by_task_id(
            self._session,
            board_id=task.board_id,
            task_ids=[task.id],
        )
        dependency_ids = deps_by_task_id.get(task.id, [])
        if not dependency_ids:
            return True
        dependency_statuses = await dependency_status_by_id(
            self._session,
            board_id=task.board_id,
            dependency_ids=dependency_ids,
        )
        blocked_by = blocked_by_dependency_ids(
            dependency_ids=dependency_ids,
            status_by_id=dependency_statuses,
        )
        return not blocked_by

    async def execute_stage(
        self,
        task_id: UUID,
        stage: str,
        runtime: str | None = None,
        agent_id: UUID | None = None,
        model: str | None = None,
        prompt: str | None = None,
    ) -> dict[str, Any]:
        """Execute or enqueue a pipeline stage for a task."""
        validation = await validate_pipeline_stage(self._session, task_id, stage)
        validation_valid = getattr(validation, "valid", not bool(getattr(validation, "blockers", [])))
        if not validation_valid:
            message = "; ".join(validation.blockers)
            if not message and validation.warnings:
                message = "; ".join(warning.message for warning in validation.warnings)
            raise ValueError(message or f"Unknown stage: {stage}")
        if validation.blockers:
            raise ValueError("; ".join(validation.blockers))

        task = await Task.objects.by_id(task_id).first(self._session)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        board = await Board.objects.by_id(task.board_id).first(self._session) if task.board_id else None
        if board and board.is_paused:
            raise ValueError(f"Board '{board.name}' is paused. Resume it before executing pipeline stages.")
        effective_runtime = runtime or default_pipeline_runtime(board)

        if not agent_id and task.assigned_agent_id:
            agent_id = task.assigned_agent_id

        if not agent_id and task.board_id is not None:
            lead_agent = await Agent.objects.filter_by(
                board_id=task.board_id,
                is_board_lead=True,
            ).first(self._session)
            if lead_agent is not None:
                agent_id = lead_agent.id

        agent = None
        if agent_id:
            agent = await Agent.objects.by_id(agent_id).first(self._session)

        # Compute workspace path for runs that execute in a project workspace.
        workspace_path: str | None = None
        if agent is not None and board is not None and board.gateway_id:
            from app.models.gateways import Gateway
            from app.services.openclaw.provisioning import _workspace_path as gateway_workspace_path

            gateway = await Gateway.objects.by_id(board.gateway_id).first(self._session)
            if gateway is not None:
                workspace_path = gateway_workspace_path(agent, gateway.workspace_root)

        run = await create_run(
            self._session,
            task_id=task_id,
            agent_id=agent_id,
            runtime=effective_runtime,
            stage=stage,
            model=model,
            workspace_path=workspace_path,
            prompt=prompt,
        )
        return await self._queue_or_execute_run(
            run=run,
            task=task,
            board=board,
            agent=agent,
            validation=validation,
        )

    async def _queue_or_execute_run(
        self,
        *,
        run: Run,
        task: Task,
        board: Board | None,
        agent: Agent | None,
        validation: Any | None = None,
    ) -> dict[str, Any]:
        if board is not None:
            active_run = await get_running_board_run(
                self._session,
                board_id=board.id,
                exclude_run_id=run.id,
            )
            if active_run is not None:
                queue_position = await get_board_run_queue_position(
                    self._session,
                    board_id=board.id,
                    run_id=run.id,
                )
                queued_run = await mark_run_queued(
                    self._session,
                    run=run,
                    queue_reason="board_has_active_run",
                    queue_position=queue_position,
                )
                return {
                    "run_id": str(queued_run.id),
                    "status": "queued",
                    "stage": queued_run.stage,
                    "runtime": queued_run.runtime,
                    "queue_position": queue_position,
                    "queue_reason": "board_has_active_run",
                    "warnings": [
                        {"stage": w.stage, "message": w.message, "severity": w.severity}
                        for w in (validation.warnings if validation is not None else [])
                    ],
                }

        started_run = await start_run(self._session, run)
        return await self._execute_started_run(
            run=started_run,
            task=task,
            board=board,
            agent=agent,
            validation=validation,
        )

    async def _execute_started_run(
        self,
        *,
        run: Run,
        task: Task,
        board: Board | None,
        agent: Agent | None,
        validation: Any | None = None,
    ) -> dict[str, Any]:
        stage = run.stage
        effective_runtime = run.runtime
        if stage in ("plan", "build"):
            task.status = STAGE_TO_TASK_STATUS.get(stage, "in_progress")
            task.review_mode = None
            if task.in_progress_at is None:
                task.in_progress_at = utcnow()
            self._session.add(task)
            await self._session.commit()

        try:
            result, failure_kind, retryable = await self._execute_run_with_retry(
                run=run,
                task=task,
                agent=agent,
                runtime=effective_runtime,
                stage=stage,
                model=run.model,
                prompt=(run.run_metadata or {}).get("prompt"),
            )
            await complete_run(
                self._session,
                run,
                success=result.success,
                summary=result.output[:500] if result.output else None,
                evidence_paths=result.evidence_paths,
                error_message=result.error,
                failure_kind=failure_kind,
                retryable=retryable,
            )

            if result.success:
                if board is not None and effective_runtime == "opencode_cli":
                    clear_runtime_state(board, runtime=effective_runtime)
                    self._session.add(board)
                    await self._session.commit()
                if stage == "plan":
                    await self._ensure_build_approval_request(task=task, agent=agent)
                await self._update_task_after_success(
                    task=task,
                    stage=stage,
                    acting_agent=agent,
                    board=board,
                )
                auto_result = await self._auto_run_next_stage(run.id)
                if board is not None and auto_result is None:
                    await self._drain_board_queue(board.id)
            elif board is not None:
                await self._record_runtime_failure_state(
                    board=board,
                    runtime=effective_runtime,
                    model=run.model,
                    failure_kind=failure_kind,
                    error_message=result.error or result.output,
                )
                await self._drain_board_queue(board.id)

            return {
                "run_id": str(run.id),
                "status": "succeeded" if result.success else "failed",
                "stage": stage,
                "runtime": effective_runtime,
                "summary": result.output[:200] if result.output else None,
                "failure_kind": failure_kind,
                "retryable": retryable,
                "queue_position": None,
                "warnings": [
                    {"stage": w.stage, "message": w.message, "severity": w.severity}
                    for w in (validation.warnings if validation is not None else [])
                ],
            }

        except Exception as exc:
            logger.exception("Pipeline stage %s failed for task %s", stage, task.id)
            failure_kind, retryable = _classify_run_failure(
                str(exc),
                runtime=effective_runtime,
                stage=stage,
            )
            await complete_run(
                self._session,
                run,
                success=False,
                error_message=str(exc),
                failure_kind=failure_kind,
                retryable=retryable,
            )
            if board is not None:
                await self._record_runtime_failure_state(
                    board=board,
                    runtime=effective_runtime,
                    model=run.model,
                    failure_kind=failure_kind,
                    error_message=str(exc),
                )
                await self._drain_board_queue(board.id)
            return {
                "run_id": str(run.id),
                "status": "failed",
                "stage": stage,
                "runtime": effective_runtime,
                "error": str(exc),
                "failure_kind": failure_kind,
                "retryable": retryable,
                "queue_position": None,
                "warnings": [
                    {"stage": w.stage, "message": w.message, "severity": w.severity}
                    for w in (validation.warnings if validation is not None else [])
                ],
            }

    async def _drain_board_queue(self, board_id: UUID) -> dict[str, Any] | None:
        """Claim and execute the next queued run for a board."""
        next_run = await claim_next_queued_board_run(self._session, board_id=board_id)
        if next_run is None:
            return None
        task = await Task.objects.by_id(next_run.task_id).first(self._session)
        if task is None:
            return None
        board = await Board.objects.by_id(board_id).first(self._session)
        agent = await Agent.objects.by_id(next_run.agent_id).first(self._session) if next_run.agent_id else None
        return await self._execute_started_run(
            run=next_run,
            task=task,
            board=board,
            agent=agent,
            validation=None,
        )

    async def _auto_run_next_stage(self, run_id: UUID, *, allow_build_auto: bool = False) -> dict | None:
        """Execute the next pipeline stage after a successful run."""
        run = await Run.objects.by_id(run_id).first(self._session)
        if run is None or run.status != "succeeded":
            return None
        if run.stage not in NORMAL_STAGE_ORDER:
            return None

        current_idx = NORMAL_STAGE_ORDER.index(run.stage)
        if current_idx >= len(NORMAL_STAGE_ORDER) - 1:
            return None

        next_stage = NORMAL_STAGE_ORDER[current_idx + 1]
        task = await Task.objects.by_id(run.task_id).first(self._session)
        board = await Board.objects.by_id(task.board_id).first(self._session) if task and task.board_id else None
        policy = board_execution_policy(board)

        if next_stage == "build":
            if task is None:
                return {
                    "auto_triggered": False,
                    "stage": "build",
                    "reason": "missing_task",
                }
            requires_approval = await self._build_requires_approval(task, board)
            if requires_approval and not await self._has_approved_build_approval(task.id):
                return {
                    "auto_triggered": False,
                    "stage": "build",
                    "reason": "awaiting_approval",
                }
            if not allow_build_auto and not bool(policy.get("auto_run_next_stage")):
                return {
                    "auto_triggered": False,
                    "stage": "build",
                    "reason": "manual_execute_required",
                }
        next_run = await create_run(
            self._session,
            task_id=run.task_id,
            agent_id=run.agent_id,
            runtime=run.runtime,
            stage=next_stage,
            model=run.model,
            workspace_path=(getattr(run, "run_metadata", None) or {}).get("workspace_path"),
        )
        if board is not None:
            drained = await self._drain_board_queue(board.id)
            if drained is not None:
                return drained
        return {
            "run_id": str(next_run.id),
            "stage": next_stage,
            "auto_triggered": True,
            "status": "queued",
        }

    async def auto_run_next_stage(self, run_id: UUID) -> dict | None:
        """Public wrapper used by the API to auto-trigger the next stage."""
        return await self._auto_run_next_stage(run_id)

    async def resume_after_approval(self, task_id: UUID) -> dict | None:
        """Resume pipeline execution after build approval is granted.

        Finds the latest successful plan run for the task and attempts auto-next.
        """
        plan_run = await (
            Run.objects.filter_by(task_id=task_id, stage="plan", status="succeeded")
            .order_by(desc(col(Run.finished_at)))
            .first(self._session)
        )
        if plan_run is None:
            return None
        return await self._auto_run_next_stage(plan_run.id, allow_build_auto=True)

    async def execute_next_stage(
        self,
        task_id: UUID,
        *,
        agent_id: UUID | None = None,
        model: str | None = None,
        prompt: str | None = None,
    ) -> dict[str, Any]:
        """Execute the next required pipeline stage for a task."""
        summary = await self.get_task_summary(task_id)
        if summary.next_required_stage is None:
            return {
                "status": "ready_for_review" if summary.ready_for_review else "noop",
                "task_id": str(task_id),
                "summary": summary.model_dump(mode="json"),
            }
        if summary.use_start_work and summary.can_start_work:
            raise ValueError("Use start-work before executing pipeline stages for an assigned inbox task.")
        if not summary.runtime_ready:
            raise ValueError(summary.runtime_blocker or "Runtime is not ready for execution.")
        result = await self.execute_stage(
            task_id=task_id,
            stage=summary.next_required_stage,
            runtime=None,
            agent_id=agent_id,
            model=model,
            prompt=prompt,
        )
        result["task_summary"] = (await self.get_task_summary(task_id)).model_dump(mode="json")
        return result

    async def request_review(
        self,
        task_id: UUID,
        *,
        agent_id: UUID | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Advance a task into review via normal pipeline or degraded fallback."""
        task = await Task.objects.by_id(task_id).first(self._session)
        if task is None:
            raise ValueError(f"Task {task_id} not found")
        board = await Board.objects.by_id(task.board_id).first(self._session) if task.board_id else None
        agent = await Agent.objects.by_id(agent_id).first(self._session) if agent_id else None

        summary = await self.get_task_summary(task_id)
        if task.status == "review":
            return {
                "status": "already_in_review",
                "task_id": str(task.id),
                "review_mode": task.review_mode or "pipeline",
                "task_summary": summary.model_dump(mode="json"),
            }

        should_auto_execute = (
            summary.execution_mode == "pipeline"
            and summary.next_required_stage is not None
            and summary.runtime_ready
        )
        if should_auto_execute:
            await self.execute_next_stage(task_id, agent_id=agent_id, model=model)
            task = await Task.objects.by_id(task_id).first(self._session)
            if task is None:
                raise ValueError(f"Task {task_id} not found")
            summary = await self.get_task_summary(task_id)
            if task.status == "review":
                return {
                    "status": "review_requested",
                    "task_id": str(task.id),
                    "review_mode": task.review_mode or "pipeline",
                    "task_summary": summary.model_dump(mode="json"),
                }

        if summary.ready_for_review:
            await self._move_task_to_review(
                task=task,
                acting_agent=agent,
                board=board,
                review_mode="pipeline",
            )
            refreshed_summary = await self.get_task_summary(task_id)
            return {
                "status": "review_requested",
                "task_id": str(task.id),
                "review_mode": "pipeline",
                "task_summary": refreshed_summary.model_dump(mode="json"),
            }

        if summary.degraded_allowed and summary.latest_completion_report is not None:
            await self._move_task_to_review(
                task=task,
                acting_agent=agent,
                board=board,
                review_mode="degraded_pipeline",
            )
            refreshed_summary = await self.get_task_summary(task_id)
            return {
                "status": "review_requested",
                "task_id": str(task.id),
                "review_mode": "degraded_pipeline",
                "task_summary": refreshed_summary.model_dump(mode="json"),
            }

        if summary.degraded_allowed and summary.latest_completion_report is None:
            raise ValueError("Completion evidence is required before degraded review can be requested.")
        if not summary.runtime_ready:
            raise ValueError(summary.runtime_blocker or "Runtime is blocked. Wait for recovery or use degraded review with evidence.")
        raise ValueError("Task is not ready for review yet.")

    async def get_task_summary(self, task_id: UUID) -> PipelineTaskSummaryRead:
        """Return a task-first execution summary for UI and agents."""
        task = await Task.objects.by_id(task_id).first(self._session)
        if task is None:
            raise ValueError(f"Task {task_id} not found")
        board = await Board.objects.by_id(task.board_id).first(self._session) if task.board_id else None
        recommended_runtime = default_pipeline_runtime(board)
        latest_runs = await self._latest_runs_by_stage(task_id)
        latest_completion_report = await self._latest_completion_report(task=task)
        task_has_started_work = await self._task_has_started_work(
            task=task,
            latest_completion_report=latest_completion_report,
        )
        next_required_stage = self._next_required_stage_from_runs(
            latest_runs,
            task_has_started_work=task_has_started_work,
        )
        (
            runtime_ready,
            runtime_blocker_code,
            runtime_blocker,
            cooldown_until,
            cooldown_message,
            degraded_allowed,
        ) = await self._runtime_readiness(
            task=task,
            board=board,
            runtime=recommended_runtime,
            next_required_stage=next_required_stage,
            latest_completion_report=latest_completion_report,
        )

        requires_approval = False
        approval_reason: str | None = None
        if next_required_stage is not None:
            validation = await validate_pipeline_stage(self._session, task_id, next_required_stage)
            requires_approval = validation.requires_approval
            approval_reason = validation.approval_reason

        latest_failed_stage = None
        latest_failure_kind = None
        latest_failed_run: Run | None = None
        for stage_name in ALL_STAGE_ORDER:
            run = latest_runs.get(stage_name)
            if run is not None and run.status == "failed":
                if latest_failed_run is None or run.created_at > latest_failed_run.created_at:
                    latest_failed_run = run
                    latest_failed_stage = stage_name
                    latest_failure_kind = run.failure_kind

        stages: list[PipelineStageStateRead] = []
        for stage_name in ALL_STAGE_ORDER:
            run = latest_runs.get(stage_name)
            stages.append(
                PipelineStageStateRead(
                    stage=stage_name,
                    status=run.status if run is not None else "pending",
                    latest_run=RunRead.model_validate(run, from_attributes=True) if run is not None else None,
                )
            )

        build_run = latest_runs.get("build")
        ready_for_review = build_run is not None and build_run.status == "succeeded"
        execution_mode = "degraded" if (not runtime_ready and degraded_allowed) else "pipeline"
        queue_state, queue_position = await self._queue_state_for_task(task_id=task.id)
        can_start_work = await self._can_start_work(task=task)
        use_start_work = can_start_work and not task_has_started_work
        recommended_action = self._recommended_action(
            task=task,
            next_required_stage=next_required_stage,
            runtime_ready=runtime_ready,
            ready_for_review=ready_for_review,
            degraded_allowed=degraded_allowed,
            latest_completion_report=latest_completion_report,
            latest_failed_stage=latest_failed_stage,
            use_start_work=use_start_work,
        )

        return PipelineTaskSummaryRead(
            task_id=task.id,
            task_status=task.status,
            work_state=self._task_work_state(task=task),
            can_start_work=can_start_work,
            use_start_work=use_start_work,
            recommended_runtime=recommended_runtime,
            next_required_stage=next_required_stage,
            requires_approval=requires_approval,
            approval_reason=approval_reason,
            ready_for_review=ready_for_review,
            latest_failed_stage=latest_failed_stage,
            latest_failure_kind=latest_failure_kind,
            runtime_ready=runtime_ready,
            runtime_blocker_code=runtime_blocker_code,
            runtime_blocker=runtime_blocker,
            execution_mode=execution_mode,
            cooldown_until=cooldown_until,
            cooldown_message=cooldown_message,
            degraded_allowed=degraded_allowed,
            recommended_action=recommended_action,
            queue_state=queue_state,
            queue_position=queue_position,
            latest_completion_report=latest_completion_report,
            stages=stages,
        )

    async def _latest_runs_by_stage(self, task_id: UUID) -> dict[str, Run | None]:
        latest: dict[str, Run | None] = {}
        for stage_name in ALL_STAGE_ORDER:
            latest[stage_name] = await (
                Run.objects.filter_by(task_id=task_id, stage=stage_name)
                .order_by(desc(col(Run.created_at)))
                .first(self._session)
            )
        return latest

    def _next_required_stage_from_runs(
        self,
        latest_runs: dict[str, Run | None],
        *,
        task_has_started_work: bool,
    ) -> str | None:
        for stage_name in NORMAL_STAGE_ORDER:
            if stage_name == "plan" and task_has_started_work:
                continue
            run = latest_runs.get(stage_name)
            if run is None or run.status != "succeeded":
                return stage_name
        return None

    async def _runtime_readiness(
        self,
        *,
        task: Task,
        board: Board | None,
        runtime: str,
        next_required_stage: str | None,
        latest_completion_report: CompletionReportRead | None,
    ) -> tuple[bool, str | None, str | None, datetime | None, str | None, bool]:
        if next_required_stage is None:
            return True, None, None, None, None, latest_completion_report is not None
        if runtime != "opencode_cli":
            return True, None, None, None, None, latest_completion_report is not None

        runtime_state = runtime_state_for_board(board)
        cooldown_until = _parse_runtime_state_datetime(runtime_state.get("cooldown_until"))
        cooldown_message = runtime_state.get("cooldown_message")
        failure_kind = runtime_state.get("failure_kind") if isinstance(runtime_state.get("failure_kind"), str) else None
        degraded_allowed = _is_degraded_runtime_failure(failure_kind)
        if runtime_state.get("status") == "cooldown":
            blocker = cooldown_message or "OpenCode CLI provider cooldown is active."
            return (
                False,
                "cooldown",
                blocker,
                cooldown_until,
                cooldown_message,
                degraded_allowed,
            )
        if runtime_state.get("status") in {"degraded", "unavailable"}:
            blocker = cooldown_message or "OpenCode CLI runtime is degraded right now."
            return (
                False,
                "runtime_degraded",
                blocker,
                cooldown_until,
                cooldown_message,
                degraded_allowed,
            )

        if shutil.which("opencode") is None:
            return (
                False,
                "opencode_missing",
                "OpenCode CLI is not installed or not available in PATH.",
                cooldown_until,
                cooldown_message,
                latest_completion_report is not None,
            )

        agent = None
        if task.assigned_agent_id:
            agent = await Agent.objects.by_id(task.assigned_agent_id).first(self._session)
        if agent is None and task.board_id is not None:
            agent = await Agent.objects.filter_by(board_id=task.board_id, is_board_lead=True).first(self._session)
        if agent is None:
            return (
                False,
                "unassigned_agent",
                "Assign an agent before running the CLI pipeline.",
                cooldown_until,
                cooldown_message,
                False,
            )

        workspace_path = await self._workspace_path_for_agent(agent=agent, board=board)
        if not workspace_path:
            return (
                False,
                "workspace_missing",
                "The assigned agent does not have a workspace path yet.",
                cooldown_until,
                cooldown_message,
                latest_completion_report is not None,
            )
        resolved_workspace_path = _resolve_local_workspace_path(workspace_path)
        if not resolved_workspace_path:
            return (
                False,
                "workspace_missing",
                "The assigned agent workspace is missing on disk.",
                cooldown_until,
                cooldown_message,
                latest_completion_report is not None,
            )
        if not Path(resolved_workspace_path).exists():
            return (
                False,
                "workspace_missing",
                "The assigned agent workspace is missing on disk.",
                cooldown_until,
                cooldown_message,
                latest_completion_report is not None,
            )

        return True, None, None, cooldown_until, cooldown_message, degraded_allowed

    async def _workspace_path_for_agent(self, *, agent: Agent | None, board: Board | None) -> str | None:
        if agent is None or board is None or not board.gateway_id:
            return None
        from app.models.gateways import Gateway
        from app.services.openclaw.provisioning import _workspace_path as gateway_workspace_path

        gateway = await Gateway.objects.by_id(board.gateway_id).first(self._session)
        if gateway is None:
            return None
        return _resolve_local_workspace_path(gateway_workspace_path(agent, gateway.workspace_root))

    async def _latest_completion_report(self, *, task: Task) -> CompletionReportRead | None:
        statement = (
            select(ActivityEvent)
            .where(
                col(ActivityEvent.task_id) == task.id,
                col(ActivityEvent.event_type) == "task.comment",
            )
            .order_by(col(ActivityEvent.created_at).desc())
        )
        events = list((await self._session.exec(statement)).all())
        for event in events:
            payload = event.payload_json or {}
            if not isinstance(payload, dict):
                continue
            if payload.get("kind") != "completion_report":
                continue
            completion_report = payload.get("completion_report")
            if not isinstance(completion_report, dict):
                continue
            if (
                task.status != "review"
                and task.assigned_agent_id is not None
                and event.agent_id not in {task.assigned_agent_id, None}
            ):
                continue
            if task.in_progress_at is not None and event.created_at < task.in_progress_at:
                continue
            try:
                parsed = CompletionReportRead.model_validate(completion_report)
            except Exception:
                continue
            if not parsed.checks_run and not parsed.artifacts:
                continue
            return parsed
        return None

    def _recommended_action(
        self,
        *,
        task: Task,
        next_required_stage: str | None,
        runtime_ready: bool,
        ready_for_review: bool,
        degraded_allowed: bool,
        latest_completion_report: CompletionReportRead | None,
        latest_failed_stage: str | None,
        use_start_work: bool,
    ) -> str | None:
        if task.status == "review":
            return "await_lead_review"
        if use_start_work:
            return "start_work"
        if ready_for_review:
            return "request_review"
        if degraded_allowed and latest_completion_report is not None:
            return "request_degraded_review"
        if degraded_allowed and not runtime_ready:
            return "submit_completion_evidence"
        if next_required_stage is not None and runtime_ready and latest_failed_stage == next_required_stage:
            return "retry_stage"
        if next_required_stage is not None and runtime_ready:
            return "run_next_step"
        if not runtime_ready:
            return "wait_for_runtime_recovery"
        return None

    async def _record_runtime_failure_state(
        self,
        *,
        board: Board,
        runtime: str,
        model: str | None,
        failure_kind: str | None,
        error_message: str | None,
    ) -> None:
        if runtime != "opencode_cli":
            return
        if failure_kind == "quota_exhausted":
            cooldown_until, cooldown_message = parse_cooldown_until(error_message)
            set_runtime_state(
                board,
                runtime=runtime,
                status="cooldown",
                failure_kind=failure_kind,
                cooldown_until=cooldown_until,
                cooldown_message=cooldown_message,
                provider="opencode_cli",
                model=model,
            )
        elif failure_kind in {"timeout", "binary_missing", "workspace_missing", "permissions_error"}:
            set_runtime_state(
                board,
                runtime=runtime,
                status="degraded",
                failure_kind=failure_kind,
                cooldown_message=error_message,
                provider="opencode_cli",
                model=model,
            )
        else:
            return
        self._session.add(board)
        await self._session.commit()

    async def _execute_run(
        self,
        *,
        run: Run,
        task: Task,
        agent: Agent | None,
        runtime: str,
        stage: str,
        model: str | None,
        prompt: str | None,
    ) -> RunResult:
        board = await Board.objects.by_id(task.board_id).first(self._session) if task.board_id else None

        from app.services.openclaw.gateway_dispatch import GatewayDispatchService
        from app.services.openclaw.provisioning import _workspace_path as gateway_workspace_path
        from app.services.runtime_adapters.factory import RuntimeAdapterFactory

        adapter_kwargs: dict[str, Any] = {"runtime": runtime}

        if runtime == "acp":
            if agent is None or task.board_id is None:
                raise ValueError("ACP runtime requires an assigned agent and board context")
            if board is None or not agent.openclaw_session_id:
                raise ValueError("ACP runtime requires gateway-backed board and active agent session")
            dispatch = GatewayDispatchService(self._session)
            _gateway, config = await dispatch.require_gateway_config_for_board(board)
            adapter_kwargs.update(
                {
                    "session": self._session,
                    "dispatch": dispatch,
                    "gateway_config": config,
                    "session_key": agent.openclaw_session_id,
                    "agent_name": agent.name,
                }
            )
        elif runtime == "opencode_cli":
            if agent is None:
                raise ValueError("OpenCode CLI runtime requires an assigned agent")
            gateway = None
            workdir = None
            if board is not None and board.gateway_id:
                from app.models.gateways import Gateway

                gateway = await Gateway.objects.by_id(board.gateway_id).first(self._session)
            if gateway is not None:
                workdir = _resolve_local_workspace_path(
                    gateway_workspace_path(agent, gateway.workspace_root)
                )
            if not workdir:
                raise ValueError("OpenCode CLI runtime requires an existing workspace path")
            if not Path(workdir).exists():
                raise ValueError(f"OpenCode CLI workspace is missing: {workdir}")
            adapter_kwargs["workdir"] = workdir
        elif runtime == "openrouter":
            adapter_kwargs["api_key"] = None

        adapter = RuntimeAdapterFactory.create(**adapter_kwargs)

        task_prompt = prompt or STAGE_PROMPTS.get(stage, f"Execute {stage} for: {task.title}")
        if task.description:
            task_prompt += f"\n\nTask: {task.description}"

        spawn_kwargs: dict[str, Any] = {"prompt": task_prompt, "model": model}
        if runtime == "opencode_cli":
            spawn_kwargs["agent"] = STAGE_TO_RUNTIME_AGENT.get(stage, "build")

        return await adapter.spawn(**spawn_kwargs)

    async def _execute_run_with_retry(
        self,
        *,
        run: Run,
        task: Task,
        agent: Agent | None,
        runtime: str,
        stage: str,
        model: str | None,
        prompt: str | None,
    ) -> tuple[RunResult, str | None, bool | None]:
        """Execute a run and retry transient opencode failures with backoff."""
        attempt_index = 0
        while True:
            result = await self._execute_run(
                run=run,
                task=task,
                agent=agent,
                runtime=runtime,
                stage=stage,
                model=model,
                prompt=prompt,
            )
            if result.success:
                return result, None, None

            failure_kind, retryable = _classify_run_failure(
                result.error or result.output,
                runtime=runtime,
                stage=stage,
            )
            retry_delay = _retry_delay_for_failure(
                runtime=runtime,
                failure_kind=failure_kind,
                retryable=retryable,
                attempt_index=attempt_index,
            )
            if retry_delay is None:
                return result, failure_kind, retryable

            logger.warning(
                "Retrying pipeline stage after transient runtime failure",
                extra={
                    "task_id": str(task.id),
                    "run_id": str(run.id),
                    "stage": stage,
                    "runtime": runtime,
                    "failure_kind": failure_kind,
                    "attempt": attempt_index + 1,
                    "retry_delay_seconds": retry_delay,
                },
            )
            await asyncio.sleep(retry_delay)
            attempt_index += 1

    async def _update_task_after_success(
        self,
        *,
        task: Task,
        stage: str,
        acting_agent: Agent | None,
        board: Board | None,
    ) -> None:
        del task, stage, acting_agent, board
        return

    async def _move_task_to_review(
        self,
        *,
        task: Task,
        acting_agent: Agent | None,
        board: Board | None,
        review_mode: str,
    ) -> None:
        previous_assigned = task.assigned_agent_id
        task.status = "review"
        task.review_mode = review_mode
        task.updated_at = utcnow()

        lead: Agent | None = None
        if task.board_id is not None:
            lead = await (
                Agent.objects.filter_by(board_id=task.board_id)
                .filter(col(Agent.is_board_lead).is_(True))
                .first(self._session)
            )
            if lead is not None:
                task.assigned_agent_id = lead.id

        self._session.add(task)
        record_activity(
            self._session,
            event_type="task.status_changed",
            task_id=task.id,
            message=f"Task moved to review ({review_mode}): {task.title}.",
            agent_id=acting_agent.id if acting_agent is not None else previous_assigned,
            board_id=task.board_id,
        )
        await self._session.commit()
        await self._session.refresh(task)

        if board is not None and lead is not None:
            await self._notify_lead_review_handoff(
                board=board,
                task=task,
                lead=lead,
                previous_assigned=previous_assigned,
            )

    async def _notify_lead_review_handoff(
        self,
        *,
        board: Board,
        task: Task,
        lead: Agent,
        previous_assigned: UUID | None,
    ) -> None:
        from app.services.openclaw.gateway_dispatch import GatewayDispatchService
        from app.services.openclaw.provisioning_db import AgentLifecycleService

        try:
            await AgentLifecycleService(self._session).commit_heartbeat(agent=lead, status_value="online")
            record_activity(
                self._session,
                event_type="task.assignee_woken",
                message="Lead heartbeat set online (review_handoff).",
                agent_id=lead.id,
                task_id=task.id,
                board_id=board.id,
            )
            await self._session.commit()
        except Exception as exc:  # pragma: no cover - best effort wake path
            logger.warning("Failed to wake lead for review handoff: %s", exc)

        description = (task.description or "").strip()
        details = [
            f"Board: {board.name}",
            f"Task: {task.title}",
            f"Task ID: {task.id}",
            f"Status: {task.status}",
        ]
        if description:
            details.append(f"Description: {description[:500]}")
        message = (
            f"TASK READY FOR LEAD REVIEW{' (DEGRADED PIPELINE)' if task.review_mode == 'degraded_pipeline' else ''}\n"
            + "\n".join(details)
            + "\n\nTake action: review the deliverables now. Approve by moving to done or return to inbox with clear feedback."
        )

        error = await GatewayDispatchService(self._session).try_send_to_agent(
            agent=lead,
            message=message,
            deliver=True,
        )
        if error is None:
            if previous_assigned != lead.id:
                record_activity(
                    self._session,
                    event_type="task.assignee_notified",
                    message="Lead notified for review handoff.",
                    agent_id=lead.id,
                    task_id=task.id,
                    board_id=board.id,
                )
            else:
                record_activity(
                    self._session,
                    event_type="task.review_notified",
                    message="Lead reminded about task in review.",
                    agent_id=lead.id,
                    task_id=task.id,
                    board_id=board.id,
                )
        else:
            record_activity(
                self._session,
                event_type="task.assignee_notify_failed",
                message=f"Lead review notify failed: {error}",
                agent_id=lead.id,
                task_id=task.id,
                board_id=board.id,
            )
        await self._session.commit()

    async def _build_requires_approval(self, task: Task, board: Board | None) -> bool:
        if build_approval_mode(board) != "high_risk_only":
            return True
        latest = await (
            Approval.objects.filter_by(task_id=task.id, action_type="pipeline.build")
            .order_by(desc(col(Approval.created_at)))
            .first(self._session)
        )
        return latest is not None

    async def _has_approved_build_approval(self, task_id: UUID) -> bool:
        approval = await (
            Approval.objects.filter_by(task_id=task_id, action_type="pipeline.build", status="approved")
            .order_by(desc(col(Approval.created_at)))
            .first(self._session)
        )
        return approval is not None

    async def _ensure_build_approval_request(self, *, task: Task, agent: Agent | None) -> None:
        board = await Board.objects.by_id(task.board_id).first(self._session) if task.board_id else None
        if not await self._build_requires_approval(task, board):
            return
        existing = await (
            Approval.objects.filter_by(task_id=task.id, action_type="pipeline.build")
            .filter(col(Approval.status).in_(["pending", "approved"]))
            .first(self._session)
        )
        if existing is not None:
            return

        board_id = task.board_id
        if board_id is None:
            return

        approval = Approval(
            board_id=board_id,
            task_id=task.id,
            agent_id=agent.id if agent else None,
            action_type="pipeline.build",
            payload={
                "reason": "Plan completed. Human approval required before build stage.",
                "task_title": task.title,
                "stage": "build",
            },
            confidence=90.0,
            status="pending",
        )
        self._session.add(approval)
        await self._session.commit()


async def get_pipeline_task_summary(
    session: AsyncSession,
    *,
    task_id: UUID,
) -> PipelineTaskSummaryRead:
    """Build a task-first execution summary outside API classes."""
    return await PipelineService(session).get_task_summary(task_id)
