"""Runtime orchestration scaffolding for Mission Control execution runs.

This module provides the first reusable seam between persisted execution runs,
phase-by-phase runtime instructions, and evidence capture. It is intentionally
small: the goal for Phase 3 is to keep the orchestration contract explicit
without binding the backend to a specific runner implementation yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, TYPE_CHECKING, cast
from uuid import UUID

from fastapi import HTTPException, status
from sqlmodel import col, select

from app.core.time import utcnow
from app.core.config import settings
from app.models.boards import Board
from app.models.execution_runs import ExecutionArtifact, ExecutionRun
from app.models.tasks import Task
from app.schemas.executions import ArtifactKind, ExecutionPhase
from app.services.openclaw.gateway_dispatch import GatewayDispatchService
from app.services.openclaw.db_service import OpenClawDBService

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession


_PHASE_SEQUENCE: tuple[ExecutionPhase, ...] = (
    "plan",
    "build",
    "test",
    "review",
    "done",
)
_PHASE_SUMMARY_FIELD: dict[ExecutionPhase, str] = {
    "plan": "plan_summary",
    "build": "build_summary",
    "test": "test_summary",
}
_PHASE_STATE_KEY: dict[ExecutionPhase, str] = {
    "review": "review_summary",
    "done": "completion_summary",
}


def _normalize_phase(value: str) -> ExecutionPhase:
    """Coerce persisted phase strings into the typed execution-phase literal."""

    if value in _PHASE_SEQUENCE:
        return cast(ExecutionPhase, value)
    return "plan"


_PHASE_ARTIFACT_KIND: dict[ExecutionPhase, ArtifactKind] = {
    "plan": "plan",
    "build": "build",
    "test": "test",
    "review": "review",
    "done": "checkpoint",
}


@dataclass(frozen=True, slots=True)
class RuntimeInstruction:
    """Runner-facing prompt and evidence contract for a single execution phase."""

    runtime_kind: str
    phase: ExecutionPhase
    prompt: str
    evidence_kind: ArtifactKind
    evidence_title: str


class RuntimeAdapter(Protocol):
    """Adapter interface for runtime-specific orchestration prompts."""

    runtime_kind: str

    def build_instruction(
        self,
        *,
        run: ExecutionRun,
        board_title: str,
        task_title: str | None = None,
        context: str | None = None,
    ) -> RuntimeInstruction:
        """Build the next prompt/evidence contract for a run."""


class _BaseRuntimeAdapter:
    """Shared prompt construction for the OpenCode/ACP adapter scaffold."""

    runtime_kind: str = "runtime"
    channel_label: str = "runtime"

    def build_instruction(
        self,
        *,
        run: ExecutionRun,
        board_title: str,
        task_title: str | None = None,
        context: str | None = None,
    ) -> RuntimeInstruction:
        title = task_title or board_title
        prompt_lines = [
            f"Mission Control {self.channel_label} instruction for execution run {run.id}.",
            f"Board: {board_title}",
            f"Target: {title}",
            f"Current phase: {run.current_phase}",
            "",
            "Follow the phase contract strictly:",
            "PLAN -> BUILD -> TEST -> REVIEW -> DONE",
            "Capture evidence for the current phase before advancing.",
        ]
        if context:
            prompt_lines.extend(("", "Context:", context.strip()))
        phase = _normalize_phase(run.current_phase)
        return RuntimeInstruction(
            runtime_kind=self.runtime_kind,
            phase=phase,
            prompt="\n".join(prompt_lines).strip(),
            evidence_kind=_PHASE_ARTIFACT_KIND[phase],
            evidence_title=f"{phase.title()} evidence for {title}",
        )


class OpenCodeRuntimeAdapter(_BaseRuntimeAdapter):
    """Prompt scaffolding for the OpenCode CLI runner."""

    runtime_kind = "opencode"
    channel_label = "OpenCode"


class AcpRuntimeAdapter(_BaseRuntimeAdapter):
    """Prompt scaffolding for ACP harness sessions."""

    runtime_kind = "acp"
    channel_label = "ACP"


class ExecutionOrchestrationService(OpenClawDBService):
    """Persisted lifecycle helpers for phase-by-phase execution orchestration."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    def next_phase(phase: ExecutionPhase) -> ExecutionPhase:
        """Return the next phase in the plan/build/test/review/done sequence."""

        index = _PHASE_SEQUENCE.index(phase)
        if index >= len(_PHASE_SEQUENCE) - 1:
            return "done"
        return _PHASE_SEQUENCE[index + 1]

    @staticmethod
    def phase_summary_field(phase: ExecutionPhase) -> str | None:
        """Return the execution-run summary field for a phase."""

        return _PHASE_SUMMARY_FIELD.get(phase)

    @staticmethod
    def stale_after_seconds() -> float:
        """Return the configured runtime staleness threshold."""

        return float(settings.execution_run_stale_after_seconds)

    @classmethod
    def is_run_stale(cls, run: ExecutionRun, *, now: datetime | None = None) -> bool:
        """Return whether a run has missed its heartbeat window."""

        if run.status != "running" or run.last_heartbeat_at is None:
            return False
        current_time = now or utcnow()
        stale_after = cls.stale_after_seconds()
        return (current_time - run.last_heartbeat_at).total_seconds() >= stale_after

    async def _get_run_or_404(self, *, board_id: UUID, run_id: UUID) -> ExecutionRun:
        statement = select(ExecutionRun).where(
            col(ExecutionRun.id) == run_id,
            col(ExecutionRun.board_id) == board_id,
        )
        run = (await self.session.exec(statement)).one_or_none()
        if run is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Run not found"
            )
        return run

    async def _load_board_and_task_titles(
        self,
        *,
        board_id: UUID,
        task_id: UUID | None,
    ) -> tuple[Board, str | None]:
        board = await Board.objects.by_id(board_id).first(self.session)
        if board is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Board not found")
        task_title: str | None = None
        if task_id is not None:
            task = await Task.objects.by_id(task_id).first(self.session)
            if task is not None and task.board_id == board_id:
                task_title = task.title
        return board, task_title

    async def build_runtime_instruction(
        self,
        *,
        board_id: UUID,
        run_id: UUID,
        context: str | None = None,
    ) -> RuntimeInstruction:
        """Build the next runtime instruction for a persisted run."""

        run = await self._get_run_or_404(board_id=board_id, run_id=run_id)
        board, task_title = await self._load_board_and_task_titles(
            board_id=board_id,
            task_id=run.task_id,
        )
        adapter = build_default_runtime_adapter(run.runtime_kind)
        return adapter.build_instruction(
            run=run,
            board_title=board.name,
            task_title=task_title,
            context=context,
        )

    async def start_run(
        self,
        *,
        board_id: UUID,
        run_id: UUID,
        runtime_session_key: str | None = None,
        execution_state_patch: dict[str, Any] | None = None,
        recovery_state_patch: dict[str, Any] | None = None,
    ) -> ExecutionRun:
        """Mark a run as active and seed its orchestration state."""

        run = await self._get_run_or_404(board_id=board_id, run_id=run_id)
        now = utcnow()
        run.status = "running"
        run.current_phase = "plan"
        run.runtime_session_key = runtime_session_key or run.runtime_session_key
        run.started_at = run.started_at or now
        run.last_heartbeat_at = now
        if execution_state_patch:
            execution_state = dict(run.execution_state or {})
            execution_state.update(execution_state_patch)
            run.execution_state = execution_state
        if recovery_state_patch:
            recovery_state = dict(run.recovery_state or {})
            recovery_state.update(recovery_state_patch)
            run.recovery_state = recovery_state
        run.updated_at = now
        self.session.add(run)
        await self.session.commit()
        await self.session.refresh(run)
        return run

    async def dispatch_run_instruction(
        self,
        *,
        board_id: UUID,
        run_id: UUID,
        context: str | None = None,
    ) -> ExecutionArtifact:
        """Send the current phase instruction to the runtime session and persist evidence."""

        run = await self._get_run_or_404(board_id=board_id, run_id=run_id)
        if run.status == "done":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Completed runs cannot be dispatched.",
            )
        if not run.runtime_session_key:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Run has no runtime session key.",
            )

        instruction = await self.build_runtime_instruction(
            board_id=board_id,
            run_id=run_id,
            context=context,
        )
        board, _task_title = await self._load_board_and_task_titles(
            board_id=board_id,
            task_id=run.task_id,
        )
        dispatch_service = GatewayDispatchService(self.session)
        _gateway, config = await dispatch_service.require_gateway_config_for_board(board)
        await dispatch_service.send_agent_message(
            session_key=run.runtime_session_key,
            config=config,
            agent_name=f"{instruction.runtime_kind}:{run.id}",
            message=instruction.prompt,
            deliver=True,
            idempotency_key=f"execution-run:{run.id}:{instruction.phase}",
        )

        now = utcnow()
        run.execution_state = {
            **(run.execution_state or {}),
            "last_dispatched_phase": instruction.phase,
            "last_dispatched_runtime_kind": instruction.runtime_kind,
            "last_dispatched_at": now.isoformat(),
        }
        run.last_heartbeat_at = now
        run.updated_at = now
        artifact = ExecutionArtifact(
            execution_run_id=run.id,
            kind="checkpoint",
            title=f"Dispatched {instruction.phase.title()} instruction",
            body=instruction.prompt,
            artifact_state={
                "phase": instruction.phase,
                "runtime_kind": instruction.runtime_kind,
                "runtime_session_key": run.runtime_session_key,
                "evidence_kind": instruction.evidence_kind,
            },
        )
        self.session.add(run)
        self.session.add(artifact)
        await self.session.commit()
        await self.session.refresh(run)
        await self.session.refresh(artifact)
        return artifact

    async def record_phase_result(
        self,
        *,
        board_id: UUID,
        run_id: UUID,
        phase: ExecutionPhase,
        title: str,
        body: str | None = None,
        artifact_state: dict[str, Any] | None = None,
        execution_state_patch: dict[str, Any] | None = None,
        recovery_state_patch: dict[str, Any] | None = None,
        runtime_session_key: str | None = None,
    ) -> ExecutionArtifact:
        """Store evidence for a phase and advance the run to the next step."""

        run = await self._get_run_or_404(board_id=board_id, run_id=run_id)
        now = utcnow()
        current_phase = _normalize_phase(run.current_phase)
        if current_phase != phase:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Run is at phase {current_phase}, not {phase}.",
            )
        summary_value = body or title
        summary_field = self.phase_summary_field(phase)
        if summary_field is not None:
            setattr(run, summary_field, summary_value)
        else:
            execution_state = dict(run.execution_state or {})
            execution_state[_PHASE_STATE_KEY[phase]] = summary_value
            run.execution_state = execution_state
        if execution_state_patch:
            execution_state = dict(run.execution_state or {})
            execution_state.update(execution_state_patch)
            run.execution_state = execution_state
        if recovery_state_patch:
            recovery_state = dict(run.recovery_state or {})
            recovery_state.update(recovery_state_patch)
            run.recovery_state = recovery_state
        if runtime_session_key:
            run.runtime_session_key = runtime_session_key
        run.last_heartbeat_at = now
        run.started_at = run.started_at or now
        run.status = "done" if phase == "review" else "running"
        run.current_phase = self.next_phase(phase)
        if phase == "review" or run.current_phase == "done":
            run.status = "done"
            run.completed_at = now
        run.updated_at = now

        artifact = ExecutionArtifact(
            execution_run_id=run.id,
            kind=_PHASE_ARTIFACT_KIND[phase],
            title=title,
            body=body,
            artifact_state=artifact_state,
        )
        self.session.add(run)
        self.session.add(artifact)
        await self.session.commit()
        await self.session.refresh(run)
        await self.session.refresh(artifact)
        return artifact

    async def mark_failed(
        self,
        *,
        board_id: UUID,
        run_id: UUID,
        last_error: str,
        artifact_title: str = "Failure evidence",
        artifact_body: str | None = None,
        artifact_state: dict[str, Any] | None = None,
        execution_state_patch: dict[str, Any] | None = None,
        recovery_state_patch: dict[str, Any] | None = None,
    ) -> ExecutionArtifact:
        """Record a failure snapshot for the run and freeze the phase."""

        run = await self._get_run_or_404(board_id=board_id, run_id=run_id)
        now = utcnow()
        run.status = "failed"
        run.last_error = last_error
        run.last_heartbeat_at = now
        run.updated_at = now
        if execution_state_patch:
            execution_state = dict(run.execution_state or {})
            execution_state.update(execution_state_patch)
            run.execution_state = execution_state
        if recovery_state_patch:
            recovery_state = dict(run.recovery_state or {})
            recovery_state.update(recovery_state_patch)
            run.recovery_state = recovery_state
        artifact = ExecutionArtifact(
            execution_run_id=run.id,
            kind="log",
            title=artifact_title,
            body=artifact_body or last_error,
            artifact_state={"last_error": last_error, **(artifact_state or {})},
        )
        self.session.add(run)
        self.session.add(artifact)
        await self.session.commit()
        await self.session.refresh(run)
        await self.session.refresh(artifact)
        return artifact

    async def resume_run(
        self,
        *,
        board_id: UUID,
        run_id: UUID,
        context: str | None = None,
        force: bool = False,
        dispatch: bool = True,
    ) -> ExecutionRun:
        """Resume a paused, failed, or stale run safely."""

        run = await self._get_run_or_404(board_id=board_id, run_id=run_id)
        now = utcnow()
        stale = self.is_run_stale(run, now=now)
        resumable = force or run.status in {"paused", "failed"} or stale
        if not resumable:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Run is not resumable yet.",
            )
        if run.runtime_session_key is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Run has no runtime session key.",
            )

        recovery_state = dict(run.recovery_state or {})
        resume_count = int(recovery_state.get("resume_count", 0)) + 1
        recovery_state.update(
            {
                "resume_count": resume_count,
                "last_resumed_at": now.isoformat(),
                "last_resume_reason": "stale" if stale else run.status,
                "last_resume_phase": run.current_phase,
                "last_resume_forced": force,
            },
        )
        if stale:
            recovery_state["last_stale_at"] = now.isoformat()
        run.recovery_state = recovery_state
        run.retry_count = (run.retry_count or 0) + 1
        run.status = "running"
        run.last_heartbeat_at = now
        run.updated_at = now
        self.session.add(run)
        await self.session.commit()
        await self.session.refresh(run)

        if dispatch:
            await self.dispatch_run_instruction(
                board_id=board_id,
                run_id=run_id,
                context=context,
            )
        return run

    async def record_heartbeat(
        self,
        *,
        board_id: UUID,
        run_id: UUID,
        message: str | None = None,
        runtime_session_key: str | None = None,
        source: str = "operator",
    ) -> ExecutionArtifact:
        """Record a heartbeat for a running execution and persist it as evidence."""

        run = await self._get_run_or_404(board_id=board_id, run_id=run_id)
        if run.status != "running":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Heartbeats are only recorded for running runs.",
            )

        now = utcnow()
        if runtime_session_key:
            run.runtime_session_key = runtime_session_key

        recovery_state = dict(run.recovery_state or {})
        heartbeat_count = int(recovery_state.get("heartbeat_count", 0)) + 1
        recovery_state.update(
            {
                "heartbeat_count": heartbeat_count,
                "last_heartbeat_at": now.isoformat(),
                "last_heartbeat_message": message,
                "last_heartbeat_source": source,
            },
        )
        run.recovery_state = recovery_state
        run.last_heartbeat_at = now
        run.updated_at = now

        artifact = ExecutionArtifact(
            execution_run_id=run.id,
            kind="heartbeat",
            title=f"Heartbeat from {source}",
            body=message,
            artifact_state={
                "source": source,
                "heartbeat_count": heartbeat_count,
                "runtime_session_key": run.runtime_session_key,
            },
        )
        self.session.add(run)
        self.session.add(artifact)
        await self.session.commit()
        await self.session.refresh(run)
        await self.session.refresh(artifact)
        return artifact


def build_default_runtime_adapter(runtime_kind: str) -> RuntimeAdapter:
    """Return the adapter for a runtime kind, defaulting to OpenCode semantics."""

    if runtime_kind == "acp":
        return AcpRuntimeAdapter()
    return OpenCodeRuntimeAdapter()
