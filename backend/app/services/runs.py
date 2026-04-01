"""CRUD operations for Run model."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlmodel import col

from app.core.time import utcnow
from app.models.runs import Run

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
) -> Run:
    """Create a new run record in queued status."""
    run = Run(
        task_id=task_id,
        agent_id=agent_id,
        runtime=runtime,
        stage=stage,
        model=model,
        temperature=temperature,
        permissions_profile=permissions_profile,
        status="queued",
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


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
