"""Pipeline API endpoints for orchestration and validation."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import require_user
from app.db.session import get_session
from app.schemas.common import OkResponse
from app.services.pipeline import PipelineService
from app.services.pipeline_validation import (
    validate_pipeline_stage,
    validate_task_status_change,
)

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.api.deps import ActorContext

router = APIRouter(prefix="/pipeline", tags=["pipeline"])

SESSION_DEP = Depends(get_session)
USER_DEP = Depends(require_user)


def _http_status_for_value_error(message: str) -> int:
    lowered = message.lower()
    if "not found" in lowered or "does not exist" in lowered:
        return status.HTTP_404_NOT_FOUND
    if (
        "paused" in lowered
        or "requires" in lowered
        or "missing required" in lowered
        or "no successful" in lowered
        or "awaiting_approval" in lowered
    ):
        return status.HTTP_409_CONFLICT
    return status.HTTP_400_BAD_REQUEST


@router.post("/tasks/{task_id}/execute")
async def execute_pipeline_stage(
    task_id: UUID,
    stage: str = Query(..., description="Pipeline stage: plan, build, or test"),
    runtime: str = Query(default="acp"),
    agent_id: UUID | None = Query(default=None),
    model: str | None = Query(default=None),
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = USER_DEP,
) -> dict:
    """Execute a pipeline stage for a task."""
    service = PipelineService(session)
    try:
        result = await service.execute_stage(
            task_id=task_id,
            stage=stage,
            runtime=runtime,
            agent_id=agent_id,
            model=model,
        )
    except ValueError as exc:
        message = str(exc)
        raise HTTPException(status_code=_http_status_for_value_error(message), detail=message) from exc
    return result


@router.post("/runs/{run_id}/auto-next")
async def auto_trigger_next_stage(
    run_id: UUID,
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = USER_DEP,
) -> dict:
    """Auto-trigger the next pipeline stage after a successful run."""
    service = PipelineService(session)
    result = await service.auto_run_next_stage(run_id)
    if result is None:
        return {"auto_triggered": False, "reason": "No next stage or run not successful"}
    return result


@router.get("/tasks/{task_id}/validate")
async def validate_task_pipeline(
    task_id: UUID,
    stage: str | None = Query(default=None, description="Stage to validate"),
    new_status: str | None = Query(default=None, description="Target status to validate"),
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = USER_DEP,
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
