"""Pipeline validation service for plan→build→test discipline.

Uses soft enforcement (warnings) — violations are reported but not blocked,
allowing flexibility during early development phases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

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

    Returns warnings for out-of-order execution but does NOT block.
    """
    warnings: list[PipelineWarning] = []

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
            warnings.append(PipelineWarning(
                stage=stage,
                message=f"No '{prev_stage}' run exists. Recommended order: {' → '.join(PIPELINE_ORDER)}.",
            ))
        elif not successful_runs:
            warnings.append(PipelineWarning(
                stage=stage,
                message=f"No successful '{prev_stage}' run found. Last status: {runs[0].status}.",
            ))

    return PipelineValidation(valid=True, warnings=warnings)


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
