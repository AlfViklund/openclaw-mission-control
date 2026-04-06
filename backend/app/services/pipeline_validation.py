"""Pipeline validation service for guarded plan→build discipline.

Stage execution may produce hard blockers (missing prerequisite runs, missing approval),
while manual task-status transitions remain guarded with owner override support.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from sqlmodel import col

from app.models.approvals import Approval
from app.models.boards import Board
from app.models.runs import Run
from app.models.tasks import Task
from app.services.pipeline_policy import build_approval_mode

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

PIPELINE_ORDER = ["plan", "build"]
NORMAL_PIPELINE_ORDER = ["plan", "build"]


@dataclass
class PipelineWarning:
    """A pipeline discipline warning."""

    stage: str
    message: str
    severity: str = "warning"


@dataclass
class PipelineValidation:
    """Result of pipeline stage validation."""

    valid: bool
    warnings: list[PipelineWarning] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    next_required_stage: str | None = None
    requires_approval: bool = False
    approval_reason: str | None = None


async def _load_stage_runs(
    session: AsyncSession,
    *,
    task_id: UUID,
) -> dict[str, list[Run]]:
    return {
        stage_name: await Run.objects.filter_by(task_id=task_id, stage=stage_name).all(session)
        for stage_name in PIPELINE_ORDER
    }


def _first_missing_success(stage_runs: dict[str, list[Run]]) -> str | None:
    for stage_name in NORMAL_PIPELINE_ORDER:
        runs = stage_runs.get(stage_name, [])
        if not any(run.status == "succeeded" for run in runs):
            return stage_name
    return None


async def _build_stage_requires_approval(
    session: AsyncSession,
    *,
    task: Task,
    stage: str,
) -> tuple[bool, str | None]:
    if stage != "build":
        return False, None
    board = await Board.objects.by_id(task.board_id).first(session) if task.board_id else None
    if build_approval_mode(board) != "high_risk_only":
        return True, "Build requires an approved pipeline.build approval."

    approval = await (
        Approval.objects.filter_by(task_id=task.id, action_type="pipeline.build")
        .order_by(col(Approval.created_at).desc())
        .first(session)
    )
    if approval is None:
        return False, None
    if approval.status == "approved":
        return False, None
    if approval.status == "rejected":
        return True, "Build is blocked because pipeline.build approval was rejected."
    return True, "Build requires an approved pipeline.build approval."


async def validate_pipeline_stage(
    session: AsyncSession,
    task_id: UUID,
    stage: str,
) -> PipelineValidation:
    """Validate whether a pipeline stage can be executed.

    Returns blockers for invalid stage execution order and missing approval gates.
    """
    warnings: list[PipelineWarning] = []
    blockers: list[str] = []

    task = await Task.objects.by_id(task_id).first(session)
    if not task:
        return PipelineValidation(valid=False, blockers=["Task not found"])
    stage_runs = await _load_stage_runs(session, task_id=task_id)
    next_required_stage = _first_missing_success(stage_runs)

    if stage not in PIPELINE_ORDER:
        return PipelineValidation(
            valid=False,
            blockers=[f"Unknown stage: {stage}"],
            next_required_stage=next_required_stage,
        )

    stage_idx = PIPELINE_ORDER.index(stage)
    previous_stages = PIPELINE_ORDER[:stage_idx]

    for prev_stage in previous_stages:
        runs = stage_runs.get(prev_stage, [])
        successful_runs = [r for r in runs if r.status == "succeeded"]

        if not runs:
            blockers.append(f"Missing required '{prev_stage}' run before '{stage}'.")
        elif not successful_runs:
            blockers.append(f"No successful '{prev_stage}' run found before '{stage}'.")

    requires_approval, approval_reason = await _build_stage_requires_approval(
        session,
        task=task,
        stage=stage,
    )
    if requires_approval:
        blockers.append(approval_reason or "Build requires an approved pipeline.build approval.")

    return PipelineValidation(
        valid=not blockers,
        warnings=warnings,
        blockers=blockers,
        next_required_stage=next_required_stage,
        requires_approval=requires_approval,
        approval_reason=approval_reason,
    )


async def validate_task_status_change(
    session: AsyncSession,
    task_id: UUID,
    new_status: str,
) -> PipelineValidation:
    """Validate task status change against pipeline discipline."""
    warnings: list[PipelineWarning] = []

    if new_status in ("review", "done"):
        stage_runs = await _load_stage_runs(session, task_id=task_id)
        build_runs = stage_runs.get("build", [])
        successful_builds = [r for r in build_runs if r.status == "succeeded"]

        if not build_runs:
            warnings.append(PipelineWarning(
                stage="status_change",
                message=f"Moving to '{new_status}' without build runs.",
            ))
        elif not successful_builds:
            warnings.append(PipelineWarning(
                stage="status_change",
                message=f"Moving to '{new_status}' but no build run succeeded.",
            ))
    return PipelineValidation(
        valid=True,
        warnings=warnings,
        next_required_stage=await _determine_next_required_stage(session, task_id=task_id),
    )


async def _determine_next_required_stage(
    session: AsyncSession,
    *,
    task_id: UUID,
) -> str | None:
    stage_runs = await _load_stage_runs(session, task_id=task_id)
    return _first_missing_success(stage_runs)
