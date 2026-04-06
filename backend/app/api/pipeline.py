"""Pipeline API endpoints for orchestration and validation."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import ACTOR_DEP, AUTH_DEP, ActorContext, resolve_actor_task_execution_agent
from app.api.deps import require_user_or_agent
from app.api.utils import http_status_for_value_error
from app.db.session import get_session
from app.services.pipeline_policy import is_pipeline_runtime_allowed
from app.schemas.pipeline import PipelineTaskSummaryRead
from app.models.tasks import Task
from app.services.pipeline import PipelineService, get_pipeline_task_summary
from app.services.pipeline import PipelineRuntimeBlockedError
from app.services.pipeline_validation import (
    validate_pipeline_stage,
    validate_task_status_change,
)

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.core.auth import AuthContext

router = APIRouter(prefix="/pipeline", tags=["pipeline"])

SESSION_DEP = Depends(get_session)
USER_DEP = AUTH_DEP
ACTOR_OR_USER_DEP = Depends(require_user_or_agent)


@router.post(
    "/tasks/{task_id}/execute",
    tags=["pipeline", "agent-lead", "agent-worker"],
    operation_id="executePipelineStage",
    openapi_extra={
        "x-llm-intent": "pipeline_stage_execute",
        "x-required-actor": "user_or_board_agent",
        "x-when-to-use": [
            "Execute a plan or build stage for a board task.",
            "Let a board agent run its next stage without switching to a user session.",
        ],
        "x-negative-guidance": [
            "Do not target a task outside the authenticated agent's board.",
            "Do not provide another agent_id unless the caller is board lead.",
        ],
        "x-routing-policy": [
            "Use this endpoint when you want validation, run creation, and runtime dispatch in one call.",
            "Board agents should prefer this over raw run creation when executing task stages.",
        ],
        "x-routing-policy-examples": [
            {
                "input": {"intent": "run build for my assigned task", "required_privilege": "any_agent"},
                "decision": "pipeline_stage_execute",
            },
            {
                "input": {"intent": "lead triggers build stage for teammate work", "required_privilege": "board_lead"},
                "decision": "pipeline_stage_execute",
            },
        ],
    },
)
async def execute_pipeline_stage(
    task_id: UUID,
    stage: str = Query(..., description="Pipeline stage: plan or build"),
    runtime: str | None = Query(default=None),
    agent_id: UUID | None = Query(default=None),
    model: str | None = Query(default=None),
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = ACTOR_DEP,
) -> dict:
    """Execute a pipeline stage for a task."""
    task = await Task.objects.by_id(task_id).first(session)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    if runtime is not None and _actor.actor_type == "agent":
        from app.models.boards import Board

        board = await Board.objects.by_id(task.board_id).first(session) if task.board_id else None
        if not is_pipeline_runtime_allowed(board, runtime):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Board agents cannot override the board execution runtime policy.",
            )
    effective_agent_id = await resolve_actor_task_execution_agent(
        session,
        actor=_actor,
        task=task,
        requested_agent_id=agent_id,
    )
    service = PipelineService(session)
    try:
        result = await service.execute_stage(
            task_id=task_id,
            stage=stage,
            runtime=runtime,
            agent_id=effective_agent_id,
            model=model,
        )
    except PipelineRuntimeBlockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.detail,
        ) from exc
    except ValueError as exc:
        message = str(exc)
        raise HTTPException(
            status_code=http_status_for_value_error(message), detail=message
        ) from exc
    return result


@router.post(
    "/tasks/{task_id}/start-work",
    response_model=dict,
    tags=["pipeline", "agent-lead", "agent-worker"],
)
async def start_pipeline_task_work(
    task_id: UUID,
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = ACTOR_DEP,
) -> dict:
    """Claim an assigned inbox task and move it to in_progress without executing a run."""
    task = await Task.objects.by_id(task_id).first(session)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    actor_agent = _actor.agent if _actor.actor_type == "agent" else None
    if actor_agent is not None:
        if actor_agent.board_id is not None and task.board_id is not None and actor_agent.board_id != task.board_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent can only start work on tasks for their board.")
    service = PipelineService(session)
    try:
        return await service.start_work(task_id=task_id, actor_agent=actor_agent)
    except ValueError as exc:
        message = str(exc)
        raise HTTPException(
            status_code=http_status_for_value_error(message), detail=message
        ) from exc


@router.post(
    "/tasks/{task_id}/execute-next",
    response_model=dict,
    tags=["pipeline", "agent-lead", "agent-worker"],
)
async def execute_next_pipeline_stage(
    task_id: UUID,
    agent_id: UUID | None = Query(default=None),
    model: str | None = Query(default=None),
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = ACTOR_DEP,
) -> dict:
    """Execute the next required stage using the board execution policy."""
    task = await Task.objects.by_id(task_id).first(session)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    effective_agent_id = await resolve_actor_task_execution_agent(
        session,
        actor=_actor,
        task=task,
        requested_agent_id=agent_id,
    )
    service = PipelineService(session)
    try:
        return await service.execute_next_stage(
            task_id=task_id,
            agent_id=effective_agent_id,
            model=model,
        )
    except PipelineRuntimeBlockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.detail,
        ) from exc
    except ValueError as exc:
        message = str(exc)
        raise HTTPException(
            status_code=http_status_for_value_error(message), detail=message
        ) from exc


@router.post(
    "/tasks/{task_id}/request-review",
    response_model=dict,
    tags=["pipeline", "agent-lead", "agent-worker"],
)
async def request_pipeline_review(
    task_id: UUID,
    agent_id: UUID | None = Query(default=None),
    model: str | None = Query(default=None),
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = ACTOR_DEP,
) -> dict:
    """Move a task into review via pipeline stages or degraded fallback."""
    task = await Task.objects.by_id(task_id).first(session)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    effective_agent_id = await resolve_actor_task_execution_agent(
        session,
        actor=_actor,
        task=task,
        requested_agent_id=agent_id,
    )
    service = PipelineService(session)
    try:
        return await service.request_review(
            task_id=task_id,
            agent_id=effective_agent_id,
            model=model,
        )
    except ValueError as exc:
        message = str(exc)
        raise HTTPException(
            status_code=http_status_for_value_error(message), detail=message
        ) from exc


@router.get(
    "/tasks/{task_id}/summary",
    response_model=PipelineTaskSummaryRead,
    tags=["pipeline", "agent-lead", "agent-worker"],
)
async def get_task_pipeline_summary(
    task_id: UUID,
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = ACTOR_OR_USER_DEP,
) -> PipelineTaskSummaryRead:
    """Return task-first pipeline state for UI and board agents."""
    task = await Task.objects.by_id(task_id).first(session)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return await get_pipeline_task_summary(session, task_id=task_id)


@router.post("/runs/{run_id}/auto-next")
async def auto_trigger_next_stage(
    run_id: UUID,
    session: AsyncSession = SESSION_DEP,
    _actor: AuthContext = USER_DEP,
) -> dict:
    """Auto-trigger the next pipeline stage after a successful run."""
    service = PipelineService(session)
    result = await service.auto_run_next_stage(run_id)
    if result is None:
        return {
            "auto_triggered": False,
            "reason": "No next stage or run not successful",
        }
    return result


@router.get("/tasks/{task_id}/validate")
async def validate_task_pipeline(
    task_id: UUID,
    stage: str | None = Query(default=None, description="Stage to validate"),
    new_status: str | None = Query(
        default=None, description="Target status to validate"
    ),
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = ACTOR_OR_USER_DEP,
) -> dict:
    """Validate pipeline discipline for a task or status change."""
    if stage:
        result = await validate_pipeline_stage(session, task_id, stage)
    elif new_status:
        result = await validate_task_status_change(session, task_id, new_status)
    else:
        result = await validate_pipeline_stage(session, task_id, "build")

    summary = await get_pipeline_task_summary(session, task_id=task_id)
    return {
        "valid": result.valid,
        "warnings": [
            {"stage": w.stage, "message": w.message, "severity": w.severity}
            for w in result.warnings
        ],
        "blockers": result.blockers,
        "next_required_stage": result.next_required_stage,
        "requires_approval": result.requires_approval,
        "approval_reason": result.approval_reason,
        "runtime_ready": summary.runtime_ready,
        "runtime_blocker_code": summary.runtime_blocker_code,
        "runtime_blocker": summary.runtime_blocker,
        "latest_failed_stage": summary.latest_failed_stage,
        "latest_failure_kind": summary.latest_failure_kind,
        "ready_for_review": summary.ready_for_review,
        "can_start_work": summary.can_start_work,
        "use_start_work": summary.use_start_work,
        "queue_state": summary.queue_state,
        "queue_position": summary.queue_position,
        "execution_mode": summary.execution_mode,
        "cooldown_until": summary.cooldown_until,
        "cooldown_message": summary.cooldown_message,
        "degraded_allowed": summary.degraded_allowed,
        "recommended_action": summary.recommended_action,
        "latest_completion_report": (
            summary.latest_completion_report.model_dump(mode="json")
            if summary.latest_completion_report is not None
            else None
        ),
    }
