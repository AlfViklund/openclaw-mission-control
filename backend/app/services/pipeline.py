"""Pipeline orchestration service for plan→build→test execution."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.core.time import utcnow
from app.models.agents import Agent
from app.models.runs import Run
from app.models.tasks import Task
from app.services.pipeline_validation import validate_pipeline_stage
from app.services.runs import complete_run, create_run, start_run

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession


class PipelineService:
    """Orchestrates pipeline stage execution for tasks."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def execute_stage(
        self,
        task_id: UUID,
        stage: str,
        runtime: str = "acp",
        agent_id: UUID | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Execute a pipeline stage for a task.

        Returns dict with run info and any pipeline warnings.
        """
        validation = await validate_pipeline_stage(self._session, task_id, stage)

        task = await Task.objects.by_id(task_id).first(self._session)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        if not agent_id and task.assigned_agent_id:
            agent_id = task.assigned_agent_id

        run = await create_run(
            self._session,
            task_id=task_id,
            agent_id=agent_id,
            runtime=runtime,
            stage=stage,
            model=model,
        )

        run = await start_run(self._session, run)

        return {
            "run_id": str(run.id),
            "status": run.status,
            "stage": stage,
            "runtime": runtime,
            "warnings": [
                {"stage": w.stage, "message": w.message, "severity": w.severity}
                for w in validation.warnings
            ],
        }

    async def auto_run_next_stage(
        self,
        run_id: UUID,
    ) -> dict[str, Any] | None:
        """Automatically trigger the next pipeline stage after a successful run.

        After a successful 'build' run, creates a 'test' run.
        Returns the new run info or None if no next stage.
        """
        run = await Run.objects.by_id(run_id).first(self._session)
        if not run:
            return None

        if run.status != "succeeded":
            return None

        stage_order = ["plan", "build", "test"]
        if run.stage not in stage_order:
            return None

        current_idx = stage_order.index(run.stage)
        if current_idx >= len(stage_order) - 1:
            return None

        next_stage = stage_order[current_idx + 1]

        test_run = await create_run(
            self._session,
            task_id=run.task_id,
            agent_id=run.agent_id,
            runtime=run.runtime,
            stage=next_stage,
            model=run.model,
        )
        test_run = await start_run(self._session, test_run)
        return {
            "run_id": str(test_run.id),
            "stage": next_stage,
            "auto_triggered": True,
        }
