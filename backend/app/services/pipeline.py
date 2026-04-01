"""Pipeline orchestration service for plan→build→test execution."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.core.time import utcnow
from app.models.agents import Agent
from app.models.approvals import Approval
from app.models.boards import Board
from app.models.runs import Run
from app.models.tasks import Task
from app.services.pipeline_validation import validate_pipeline_stage
from app.services.runs import complete_run, create_run, start_run
from app.services.runtime_adapters.base import RunResult

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

STAGE_TO_RUNTIME_AGENT = {
    "plan": "plan",
    "build": "build",
    "test": "build",
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
        if validation.blockers:
            raise ValueError("; ".join(validation.blockers))

        task = await Task.objects.by_id(task_id).first(self._session)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        board = await Board.objects.by_id(task.board_id).first(self._session) if task.board_id else None
        if board and board.is_paused:
            raise ValueError(f"Board '{board.name}' is paused. Resume it before executing pipeline stages.")

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

        run = await create_run(
            self._session,
            task_id=task_id,
            agent_id=agent_id,
            runtime=runtime,
            stage=stage,
            model=model,
        )

        run = await start_run(self._session, run)

        if stage in ("plan", "build"):
            task.status = STAGE_TO_TASK_STATUS.get(stage, "in_progress")
            if task.in_progress_at is None:
                task.in_progress_at = utcnow()
            self._session.add(task)
            await self._session.commit()

        try:
            result = await self._execute_run(
                run=run,
                task=task,
                agent=agent,
                runtime=runtime,
                stage=stage,
                model=model,
                prompt=prompt,
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
                if stage == "plan":
                    await self._ensure_build_approval_request(task=task, agent=agent)
                await self._update_task_after_success(task=task, stage=stage)
                await self._auto_run_next_stage(run.id)

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

    async def _auto_run_next_stage(self, run_id: UUID) -> dict | None:
        """Execute the next pipeline stage after a successful run."""
        run = await Run.objects.by_id(run_id).first(self._session)
        if run is None or run.status != "succeeded":
            return None
        if run.stage not in STAGE_ORDER:
            return None

        current_idx = STAGE_ORDER.index(run.stage)
        if current_idx >= len(STAGE_ORDER) - 1:
            return None

        next_stage = STAGE_ORDER[current_idx + 1]

        if next_stage == "build":
            task = await Task.objects.by_id(run.task_id).first(self._session)
            if task is None or not await self._has_approved_build_approval(task.id):
                return {
                    "auto_triggered": False,
                    "stage": "build",
                    "reason": "awaiting_approval",
                }

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
        agent = await Agent.objects.by_id(run.agent_id).first(self._session) if run.agent_id else None
        if task and next_stage in ("plan", "build"):
            task.status = STAGE_TO_TASK_STATUS.get(next_stage, "in_progress")
            self._session.add(task)
            await self._session.commit()

        try:
            if task is None:
                raise ValueError(f"Task {run.task_id} not found for auto-next stage")

            result = await self._execute_run(
                run=next_run,
                task=task,
                agent=agent,
                runtime=run.runtime,
                stage=next_stage,
                model=run.model,
                prompt=None,
            )

            await complete_run(
                self._session,
                next_run,
                success=result.success,
                summary=result.output[:500] if result.output else None,
                evidence_paths=result.evidence_paths,
                error_message=result.error,
            )

            if result.success:
                await self._update_task_after_success(task=task, stage=next_stage)
                return await self._auto_run_next_stage(next_run.id)

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

    async def auto_run_next_stage(self, run_id: UUID) -> dict | None:
        """Public wrapper used by the API to auto-trigger the next stage."""
        return await self._auto_run_next_stage(run_id)

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
        if stage == "test":
            from app.services.qa import QAService

            report, evidence_paths, success, summary = await QAService(self._session).run_tests_for_existing_run(
                run,
            )
            return RunResult(
                success=success,
                output=summary,
                error=None if success else summary,
                evidence_paths=evidence_paths,
                metadata={
                    "qa": True,
                    "tests_total": report.total,
                    "tests_failed": report.failed,
                },
            )

        from app.services.openclaw.gateway_dispatch import GatewayDispatchService
        from app.services.openclaw.provisioning import _workspace_path as gateway_workspace_path
        from app.services.runtime_adapters.factory import RuntimeAdapterFactory

        adapter_kwargs: dict[str, Any] = {"runtime": runtime}
        board = await Board.objects.by_id(task.board_id).first(self._session) if task.board_id else None

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
                workdir = gateway_workspace_path(agent, gateway.workspace_root)
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

    async def _update_task_after_success(self, *, task: Task, stage: str) -> None:
        if stage == "test":
            task.status = "review"
            self._session.add(task)
            await self._session.commit()

    async def _has_approved_build_approval(self, task_id: UUID) -> bool:
        approval = await (
            Approval.objects.filter_by(task_id=task_id, action_type="pipeline.build", status="approved")
            .order_by(desc(col(Approval.created_at)))
            .first(self._session)
        )
        return approval is not None

    async def _ensure_build_approval_request(self, *, task: Task, agent: Agent | None) -> None:
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
