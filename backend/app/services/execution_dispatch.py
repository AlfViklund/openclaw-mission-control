"""Queue helpers and worker handler for execution run dispatch handoff."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status

from app.core.config import settings
from app.core.logging import get_logger
from app.core.time import utcnow
from app.db.session import async_session_maker
from app.models.execution_runs import ExecutionRun
from app.services.execution_orchestration import ExecutionOrchestrationService
from app.services.queue import QueuedTask, enqueue_task, requeue_if_failed

logger = get_logger(__name__)
TASK_TYPE = "execution_run_dispatch"


@dataclass(frozen=True)
class QueuedExecutionRunDispatch:
    """Queued payload for dispatching the current execution phase."""

    board_id: UUID
    run_id: UUID
    context: str | None = None
    attempts: int = 0


def _task_from_payload(payload: QueuedExecutionRunDispatch) -> QueuedTask:
    return QueuedTask(
        task_type=TASK_TYPE,
        payload={
            "board_id": str(payload.board_id),
            "run_id": str(payload.run_id),
            "context": payload.context,
        },
        created_at=utcnow(),
        attempts=payload.attempts,
    )


def decode_execution_dispatch_task(task: QueuedTask) -> QueuedExecutionRunDispatch:
    if task.task_type not in {TASK_TYPE, "legacy"}:
        raise ValueError(f"Unexpected task_type={task.task_type!r}; expected {TASK_TYPE!r}")
    payload = task.payload
    return QueuedExecutionRunDispatch(
        board_id=UUID(str(payload["board_id"])),
        run_id=UUID(str(payload["run_id"])),
        context=payload.get("context") if isinstance(payload.get("context"), str) else None,
        attempts=int(payload.get("attempts", task.attempts)),
    )


def enqueue_execution_dispatch(payload: QueuedExecutionRunDispatch) -> bool:
    queued = _task_from_payload(payload)
    return enqueue_task(
        queued,
        settings.rq_queue_name,
        redis_url=settings.rq_redis_url,
    )


def requeue_execution_dispatch(task: QueuedTask, *, delay_seconds: float = 0) -> bool:
    return requeue_if_failed(
        task,
        settings.rq_queue_name,
        max_retries=settings.rq_dispatch_max_retries,
        redis_url=settings.rq_redis_url,
        delay_seconds=max(0.0, delay_seconds),
    )


async def process_execution_dispatch_queue_task(task: QueuedTask) -> None:
    """Dispatch the current run phase into the runtime session."""

    payload = decode_execution_dispatch_task(task)
    async with async_session_maker() as session:
        run = await session.get(ExecutionRun, payload.run_id)
        if run is None:
            logger.info(
                "execution.dispatch.skip_missing_run",
                extra={"run_id": str(payload.run_id)},
            )
            return
        if run.board_id != payload.board_id:
            logger.info(
                "execution.dispatch.skip_board_mismatch",
                extra={"run_id": str(payload.run_id), "board_id": str(payload.board_id)},
            )
            return
        if run.status == "done":
            logger.info(
                "execution.dispatch.skip_done",
                extra={"run_id": str(payload.run_id)},
            )
            return
        try:
            await ExecutionOrchestrationService(session).dispatch_run_instruction(
                board_id=payload.board_id,
                run_id=payload.run_id,
                context=payload.context,
            )
        except HTTPException as exc:
            if exc.status_code in {
                status.HTTP_404_NOT_FOUND,
                status.HTTP_409_CONFLICT,
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            }:
                logger.info(
                    "execution.dispatch.skip_http_error",
                    extra={
                        "run_id": str(payload.run_id),
                        "status_code": exc.status_code,
                    },
                )
                return
            raise
