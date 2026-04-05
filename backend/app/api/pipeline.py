"""Pipeline API endpoints for orchestration and validation."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import ACTOR_DEP, AUTH_DEP, ActorContext, resolve_actor_task_execution_agent
from app.api.utils import http_status_for_value_error
from app.db.session import get_session
from app.models.tasks import Task
from app.services.pipeline import PipelineService
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


@router.post(
    "/tasks/{task_id}/execute",
    tags=["pipeline", "agent-lead", "agent-worker"],
    operation_id="executePipelineStage",
    openapi_extra={
        "x-llm-intent": "pipeline_stage_execute",
        "x-required-actor": "user_or_board_agent",
        "x-when-to-use": [
            "Execute a plan, build, or test stage for a board task.",
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
                "input": {"intent": "lead triggers test stage for teammate work", "required_privilege": "board_lead"},
                "decision": "pipeline_stage_execute",
            },
        ],
    },
)
async def execute_pipeline_stage(
    task_id: UUID,
    stage: str = Query(..., description="Pipeline stage: plan, build, or test"),
    runtime: str = Query(default="acp"),
    agent_id: UUID | None = Query(default=None),
    model: str | None = Query(default=None),
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = ACTOR_DEP,
) -> dict:
    """Execute a pipeline stage for a task."""
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
        result = await service.execute_stage(
            task_id=task_id,
            stage=stage,
            runtime=runtime,
            agent_id=effective_agent_id,
            model=model,
        )
    except ValueError as exc:
        message = str(exc)
        raise HTTPException(
            status_code=http_status_for_value_error(message), detail=message
        ) from exc
    return result


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
    _actor: AuthContext = USER_DEP,
) -> dict:
    """Validate pipeline discipline for a task or status change."""
    if stage:
        result = await validate_pipeline_stage(session, task_id, stage)
    elif new_status:
        result = await validate_task_status_change(session, task_id, new_status)
    else:
        result = await validate_pipeline_stage(session, task_id, "build")

    return {
        "valid": result.valid,
        "warnings": [
            {"stage": w.stage, "message": w.message, "severity": w.severity}
            for w in result.warnings
        ],
        "blockers": result.blockers,
    }
