"""Pipeline orchestration service for plan→build→test execution."""

from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)

STAGE_ORDER = ["plan", "build", "test"]

STAGE_TO_TASK_STATUS = {
    "plan": "in_progress",
    "build": "in_progress",
    "test": "review",
}


class PipelineService:
    """Orchestrates pipeline stage execution for tasks with real runtime dispatch."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def execute_stage(
        self,
        task_id: UUID,
        stage: str,
        runtime: str = "acp",
        agent_id: UUID | None = None,
        model: str | None = None,
        prompt: str | None = None,
    ) -> dict[str, Any]:
        """Execute a pipeline stage for a task using the specified runtime adapter.

        Returns dict with run info, execution result, and any pipeline warnings.
        """
        validation = await validate_pipeline_stage(self._session, task_id, stage)

        task = await Task.objects.by_id(task_id).first(self._session)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        if not agent_id and task.assigned_agent_id:
            agent_id = task.assigned_agent_id

        agent = None
        if agent_id:
            agent = await Agent.objects.by_id(agent_id).first(self._session)

        run = await create_run(
            self._session,
            task_id=task_id,
            agent_id=agent_id,
            runtime=runtime,
            stage=stage,
            model=model,
        )

        run = await start_run(self._session, run)

        task.status = STAGE_TO_TASK_STATUS.get(stage, "in_progress")
        if task.in_progress_at is None:
            task.in_progress_at = utcnow()
        self._session.add(task)
        await self._session.commit()

        try:
            from app.services.runtime_adapters.factory import RuntimeAdapterFactory

            adapter = RuntimeAdapterFactory.create(
                runtime=runtime,
                session=self._session,
            )

            result = await adapter.spawn(
                prompt=prompt or f"Execute {stage} stage for task {task_id}: {task.title}",
                model=model,
            )

            await complete_run(
                self._session,
                run,
                success=result.success,
                summary=result.output[:500] if result.output else None,
                evidence_paths=result.evidence_paths,
                error_message=result.error,
            )

            if result.success:
                await self._auto_run_next_stage(run)

            return {
                "run_id": str(run.id),
                "status": "succeeded" if result.success else "failed",
                "stage": stage,
                "runtime": runtime,
                "summary": result.output[:200] if result.output else None,
                "warnings": [
                    {"stage": w.stage, "message": w.message, "severity": w.severity}
                    for w in validation.warnings
                ],
            }

        except Exception as exc:
            logger.exception("Pipeline stage %s failed for task %s", stage, task_id)
            await complete_run(
                self._session,
                run,
                success=False,
                error_message=str(exc),
            )
            return {
                "run_id": str(run.id),
                "status": "failed",
                "stage": stage,
                "runtime": runtime,
                "error": str(exc),
                "warnings": [
                    {"stage": w.stage, "message": w.message, "severity": w.severity}
                    for w in validation.warnings
                ],
            }

    async def _auto_run_next_stage(self, run: Run) -> dict | None:
        """Automatically trigger the next pipeline stage after a successful run."""
        if run.status != "succeeded":
            return None

        if run.stage not in STAGE_ORDER:
            return None

        current_idx = STAGE_ORDER.index(run.stage)
        if current_idx >= len(STAGE_ORDER) - 1:
            return None

        next_stage = STAGE_ORDER[current_idx + 1]

        next_run = await create_run(
            self._session,
            task_id=run.task_id,
            agent_id=run.agent_id,
            runtime=run.runtime,
            stage=next_stage,
            model=run.model,
        )
        next_run = await start_run(self._session, next_run)

        task = await Task.objects.by_id(run.task_id).first(self._session)
        if task:
            task.status = STAGE_TO_TASK_STATUS.get(next_stage, "in_progress")
            self._session.add(task)
            await self._session.commit()

        return {
            "run_id": str(next_run.id),
            "stage": next_stage,
            "auto_triggered": True,
        }
