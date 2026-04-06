"""CRUD operations for Run model."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlmodel import col, select

from app.core.time import utcnow
from app.models.runs import Run
from app.models.tasks import Task

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession


async def create_run(
    session: AsyncSession,
    *,
    task_id: UUID,
    agent_id: UUID | None = None,
    runtime: str = "acp",
    stage: str = "plan",
    model: str | None = None,
    temperature: float | None = None,
    permissions_profile: str | None = None,
    workspace_path: str | None = None,
    prompt: str | None = None,
    queue_reason: str | None = None,
) -> Run:
    """Create a new run record in queued status."""
    metadata: dict = {}
    if workspace_path:
        metadata["workspace_path"] = workspace_path
    if prompt:
        metadata["prompt"] = prompt
    if queue_reason:
        metadata["queue_reason"] = queue_reason
    run = Run(
        task_id=task_id,
        agent_id=agent_id,
        runtime=runtime,
        stage=stage,
        model=model,
        temperature=temperature,
        permissions_profile=permissions_profile,
        status="queued",
        run_metadata=metadata,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


async def get_active_task_stage_run(
    session: AsyncSession,
    *,
    task_id: UUID,
    stage: str,
) -> Run | None:
    """Return the canonical active run for a task-stage pair, if any.

    Active means ``queued`` or ``running``. Prefer a currently running run;
    otherwise keep the oldest queued entry as the canonical queue record.
    """
    running = (
        await session.exec(
            select(Run)
            .where(
                col(Run.task_id) == task_id,
                col(Run.stage) == stage,
                col(Run.status) == "running",
            )
            .order_by(col(Run.started_at).desc(), col(Run.created_at).desc())
            .limit(1)
        )
    ).first()
    if running is not None:
        return running

    queued = (
        await session.exec(
            select(Run)
            .where(
                col(Run.task_id) == task_id,
                col(Run.stage) == stage,
                col(Run.status) == "queued",
            )
            .order_by(col(Run.created_at))
            .limit(1)
        )
    ).first()
    return queued


async def get_run_by_id(session: AsyncSession, run_id: UUID) -> Run | None:
    """Fetch a single run by its ID."""
    return await Run.objects.by_id(run_id).first(session)


async def list_runs(
    session: AsyncSession,
    *,
    task_id: UUID | None = None,
    agent_id: UUID | None = None,
    stage: str | None = None,
    status: str | None = None,
) -> list[Run]:
    """List runs with optional filters."""
    statement = Run.objects.all()
    if task_id is not None:
        statement = statement.filter(col(Run.task_id) == task_id)
    if agent_id is not None:
        statement = statement.filter(col(Run.agent_id) == agent_id)
    if stage is not None:
        statement = statement.filter(col(Run.stage) == stage)
    if status is not None:
        statement = statement.filter(col(Run.status) == status)
    statement = statement.order_by(col(Run.created_at).desc())
    return await statement.all(session)


async def start_run(session: AsyncSession, run: Run) -> Run:
    """Mark a run as started."""
    run.status = "running"
    run.started_at = utcnow()
    if isinstance(run.run_metadata, dict):
        run.run_metadata.pop("queue_reason", None)
        run.run_metadata.pop("queue_position", None)
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


async def complete_run(
    session: AsyncSession,
    run: Run,
    *,
    success: bool,
    summary: str | None = None,
    evidence_paths: list[dict] | None = None,
    error_message: str | None = None,
    failure_kind: str | None = None,
    retryable: bool | None = None,
) -> Run:
    """Mark a run as completed (succeeded or failed)."""
    run.status = "succeeded" if success else "failed"
    run.finished_at = utcnow()
    if summary is not None:
        run.summary = summary
    if evidence_paths is not None:
        run.evidence_paths = evidence_paths
    if error_message is not None:
        run.error_message = error_message
    if failure_kind is not None:
        run.failure_kind = failure_kind
    if retryable is not None:
        run.retryable = retryable
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


async def cancel_run(session: AsyncSession, run: Run) -> Run:
    """Cancel a running run."""
    run.status = "canceled"
    run.finished_at = utcnow()
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


async def update_run(
    session: AsyncSession,
    run: Run,
    *,
    status: str | None = None,
    summary: str | None = None,
) -> Run:
    """Update run metadata fields."""
    if status is not None:
        run.status = status
    if summary is not None:
        run.summary = summary
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


async def get_board_id_for_run(session: AsyncSession, run: Run) -> UUID | None:
    """Resolve board id for a run via its task."""
    return await session.scalar(select(Task.board_id).where(col(Task.id) == run.task_id))


async def get_running_board_run(
    session: AsyncSession,
    *,
    board_id: UUID,
    exclude_run_id: UUID | None = None,
) -> Run | None:
    """Return the currently running run for a board, if any."""
    statement = (
        select(Run)
        .join(Task, col(Task.id) == col(Run.task_id))
        .where(col(Task.board_id) == board_id, col(Run.status) == "running")
        .order_by(col(Run.started_at).desc(), col(Run.created_at).desc())
        .limit(1)
    )
    if exclude_run_id is not None:
        statement = statement.where(col(Run.id) != exclude_run_id)
    return (await session.exec(statement)).first()


async def get_board_run_queue_position(
    session: AsyncSession,
    *,
    board_id: UUID,
    run_id: UUID,
) -> int | None:
    """Return 1-based queue position among queued runs for a board."""
    queued_runs = (
        await session.exec(
            select(Run)
            .join(Task, col(Task.id) == col(Run.task_id))
            .where(col(Task.board_id) == board_id, col(Run.status) == "queued")
            .order_by(col(Run.created_at))
        )
    ).all()
    for idx, queued_run in enumerate(queued_runs, start=1):
        if queued_run.id == run_id:
            return idx
    return None


async def mark_run_queued(
    session: AsyncSession,
    *,
    run: Run,
    queue_reason: str,
    queue_position: int | None = None,
) -> Run:
    """Persist queue metadata for a queued run."""
    metadata: dict[str, Any] = dict(run.run_metadata or {})
    metadata["queue_reason"] = queue_reason
    if queue_position is not None:
        metadata["queue_position"] = queue_position
    else:
        metadata.pop("queue_position", None)
    run.run_metadata = metadata
    run.status = "queued"
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


async def claim_next_queued_board_run(
    session: AsyncSession,
    *,
    board_id: UUID,
) -> Run | None:
    """Claim the oldest queued run for a board if no run is currently active."""
    running = await get_running_board_run(session, board_id=board_id)
    if running is not None:
        return None
    next_run = (
        await session.exec(
            select(Run)
            .join(Task, col(Task.id) == col(Run.task_id))
            .where(col(Task.board_id) == board_id, col(Run.status) == "queued")
            .order_by(col(Run.created_at))
            .limit(1)
        )
    ).first()
    if next_run is None:
        return None
    return await start_run(session, next_run)
