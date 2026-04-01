"""Pipeline validation service for guarded plan→build→test discipline.

Stage execution may produce hard blockers (missing prerequisite runs, missing approval),
while manual task-status transitions remain guarded with owner override support.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from sqlmodel import col

from app.models.approvals import Approval
from app.models.runs import Run
from app.models.tasks import Task

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

PIPELINE_ORDER = ["plan", "build", "test"]


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

    if stage not in PIPELINE_ORDER:
        return PipelineValidation(
            valid=False,
            warnings=[PipelineWarning(stage=stage, message=f"Unknown stage: {stage}")],
        )

    stage_idx = PIPELINE_ORDER.index(stage)
    previous_stages = PIPELINE_ORDER[:stage_idx]

    for prev_stage in previous_stages:
        runs = await Run.objects.filter_by(task_id=task_id, stage=prev_stage).all(session)
        successful_runs = [r for r in runs if r.status == "succeeded"]

        if not runs:
            blockers.append(f"Missing required '{prev_stage}' run before '{stage}'.")
        elif not successful_runs:
            blockers.append(f"No successful '{prev_stage}' run found before '{stage}'.")

    if stage == "build":
        approval = await (
            Approval.objects.filter_by(task_id=task_id, action_type="pipeline.build", status="approved")
            .order_by(col(Approval.created_at).desc())
            .first(session)
        )
        if approval is None:
            blockers.append("Build requires an approved pipeline.build approval after planning.")

    return PipelineValidation(valid=not blockers, warnings=warnings, blockers=blockers)


async def validate_task_status_change(
    session: AsyncSession,
    task_id: UUID,
    new_status: str,
) -> PipelineValidation:
    """Validate task status change against pipeline discipline."""
    warnings: list[PipelineWarning] = []

    if new_status in ("review", "done"):
        test_runs = await Run.objects.filter_by(task_id=task_id, stage="test").all(session)
        successful_tests = [r for r in test_runs if r.status == "succeeded"]

        if not test_runs:
            warnings.append(PipelineWarning(
                stage="status_change",
                message=f"Moving to '{new_status}' without test runs.",
            ))
        elif not successful_tests:
            warnings.append(PipelineWarning(
                stage="status_change",
                message=f"Moving to '{new_status}' but no test run succeeded.",
            ))

    return PipelineValidation(valid=True, warnings=warnings)
