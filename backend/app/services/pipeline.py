"""Pipeline orchestration service for plan→build→test execution."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.core.time import utcnow
from app.models.agents import Agent
from app.models.boards import Board
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

STAGE_PROMPTS = {
    "plan": "Create a detailed implementation plan. Do not modify files.",
    "build": "Implement the task according to the plan. Make file changes and run checks.",
    "test": "Run tests to verify the implementation. Report failures.",
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

            adapter_kwargs: dict[str, Any] = {"runtime": runtime}

            if runtime == "acp" and agent:
                from app.services.openclaw.gateway_dispatch import GatewayDispatchService

                board = None
                if task.board_id:
                    board = await Board.objects.by_id(task.board_id).first(self._session)
                if board and agent.openclaw_session_id:
                    dispatch = GatewayDispatchService(self._session)
                    gateway, config = await dispatch.require_gateway_config_for_board(board)
                    adapter_kwargs.update({
                        "session": self._session,
                        "dispatch": dispatch,
                        "gateway_config": config,
                        "session_key": agent.openclaw_session_id,
                        "agent_name": agent.name,
                    })
                else:
                    raise ValueError(
                        f"ACP runtime requires agent with active session and board with gateway. "
                        f"Agent '{agent.name}' session_id={agent.openclaw_session_id}, board_id={task.board_id}"
                    )
            elif runtime == "opencode_cli":
                adapter_kwargs["workdir"] = None
            elif runtime == "openrouter":
                adapter_kwargs["api_key"] = None

            adapter = RuntimeAdapterFactory.create(**adapter_kwargs)

            task_prompt = prompt or STAGE_PROMPTS.get(stage, f"Execute {stage} for: {task.title}")
            if task.description:
                task_prompt += f"\n\nTask: {task.description}"

            result = await adapter.spawn(prompt=task_prompt, model=model)

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
        """Execute the next pipeline stage after a successful run."""
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

        try:
            from app.services.runtime_adapters.factory import RuntimeAdapterFactory

            adapter_kwargs: dict[str, Any] = {"runtime": run.runtime}

            if run.runtime == "acp" and run.agent_id:
                from app.services.openclaw.gateway_dispatch import GatewayDispatchService

                agent = await Agent.objects.by_id(run.agent_id).first(self._session)
                if agent and task and task.board_id:
                    board = await Board.objects.by_id(task.board_id).first(self._session)
                    if board and agent.openclaw_session_id:
                        dispatch = GatewayDispatchService(self._session)
                        gateway, config = await dispatch.require_gateway_config_for_board(board)
                        adapter_kwargs.update({
                            "session": self._session,
                            "dispatch": dispatch,
                            "gateway_config": config,
                            "session_key": agent.openclaw_session_id,
                            "agent_name": agent.name,
                        })

            adapter = RuntimeAdapterFactory.create(**adapter_kwargs)

            task_prompt = STAGE_PROMPTS.get(next_stage, f"Execute {next_stage}")
            if task and task.description:
                task_prompt += f"\n\nTask: {task.description}"

            result = await adapter.spawn(prompt=task_prompt, model=run.model)

            await complete_run(
                self._session,
                next_run,
                success=result.success,
                summary=result.output[:500] if result.output else None,
                evidence_paths=result.evidence_paths,
                error_message=result.error,
            )

            if result.success:
                return await self._auto_run_next_stage(next_run)

            return {
                "run_id": str(next_run.id),
                "stage": next_stage,
                "auto_triggered": True,
                "status": "failed",
            }

        except Exception as exc:
            logger.exception("Auto-execution of stage %s failed for run %s", next_stage, run.id)
            await complete_run(
                self._session,
                next_run,
                success=False,
                error_message=str(exc),
            )
            return {
                "run_id": str(next_run.id),
                "stage": next_stage,
                "auto_triggered": True,
                "status": "failed",
                "error": str(exc),
            }
