"""Run API endpoints for agent execution tracking."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import col, select

from app.api.deps import require_user_auth
from app.db.pagination import paginate
from app.db.session import get_session
from app.models.agents import Agent
from app.models.runs import Run
from app.models.tasks import Task
from app.schemas.pagination import DefaultLimitOffsetPage
from app.schemas.runs import RunCreate, RunEvidenceRead, RunRead, RunUpdate
from app.schemas.common import OkResponse
from app.services.runs import (
    cancel_run,
    complete_run,
    create_run,
    get_run_by_id,
    list_runs,
    start_run,
    update_run,
)

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.api.deps import ActorContext

router = APIRouter(prefix="/runs", tags=["runs"])

SESSION_DEP = Depends(get_session)
USER_DEP = Depends(require_user_auth)


@router.post("", response_model=RunRead, status_code=status.HTTP_201_CREATED)
async def create_and_start_run(
    payload: RunCreate,
    session: AsyncSession = SESSION_DEP,
    user: ActorContext = USER_DEP,
) -> Run:
    """Create and start a new run for a task stage."""
    task = await Task.objects.by_id(payload.task_id).first(session)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    if payload.agent_id:
        agent = await Agent.objects.by_id(payload.agent_id).first(session)
        if not agent:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    run = await create_run(
        session,
        task_id=payload.task_id,
        agent_id=payload.agent_id,
        runtime=payload.runtime,
        stage=payload.stage,
        model=payload.model,
        temperature=payload.temperature,
        permissions_profile=payload.permissions_profile,
    )

    run = await start_run(session, run)

    return run


@router.get("", response_model=DefaultLimitOffsetPage[RunRead])
async def list_runs_endpoint(
    board_id: UUID | None = Query(default=None),
    task_id: UUID | None = Query(default=None),
    agent_id: UUID | None = Query(default=None),
    stage: str | None = Query(default=None),
    status: str | None = Query(default=None),
    since: datetime | None = Query(default=None, description="Filter by finished_at or created_at after this time"),
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = USER_DEP,
) -> DefaultLimitOffsetPage[RunRead]:
    """List runs with optional filtering."""
    statement = Run.objects.all()
    if board_id is not None:
        task_ids = select(Task.id).where(col(Task.board_id) == board_id)
        statement = statement.filter(col(Run.task_id).in_(task_ids))
    if task_id is not None:
        statement = statement.filter(col(Run.task_id) == task_id)
    if agent_id is not None:
        statement = statement.filter(col(Run.agent_id) == agent_id)
    if stage is not None:
        statement = statement.filter(col(Run.stage) == stage)
    if status is not None:
        statement = statement.filter(col(Run.status) == status)
    if since is not None:
        statement = statement.filter(
            (col(Run.finished_at) >= since) | (col(Run.created_at) >= since)
        )
    statement = statement.order_by(col(Run.created_at).desc())
    return await paginate(session, statement.statement)


@router.get("/by-task/{task_id}", response_model=DefaultLimitOffsetPage[RunRead])
async def list_task_runs(
    task_id: UUID,
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = USER_DEP,
) -> DefaultLimitOffsetPage[RunRead]:
    """List all runs for a specific task."""
    statement = Run.objects.filter(col(Run.task_id) == task_id)
    statement = statement.order_by(col(Run.created_at).desc())
    return await paginate(session, statement.statement)


@router.get("/{run_id}", response_model=RunRead)
async def get_run(
    run_id: UUID,
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = USER_DEP,
) -> Run:
    """Get a run by ID."""
    run = await get_run_by_id(session, run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return run


@router.get("/{run_id}/evidence", response_model=RunEvidenceRead)
async def get_run_evidence(
    run_id: UUID,
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = USER_DEP,
) -> RunEvidenceRead:
    """Get evidence paths for a run."""
    run = await get_run_by_id(session, run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return RunEvidenceRead(run_id=run.id, evidence=run.evidence_paths)


@router.post("/{run_id}/cancel", response_model=RunRead)
async def cancel_run_endpoint(
    run_id: UUID,
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = USER_DEP,
) -> Run:
    """Cancel a running run."""
    run = await get_run_by_id(session, run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    if run.status not in ("queued", "running"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel run in '{run.status}' status",
        )
    return await cancel_run(session, run)


@router.patch("/{run_id}", response_model=RunRead)
async def update_run_endpoint(
    run_id: UUID,
    payload: RunUpdate,
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = USER_DEP,
) -> Run:
    """Update run metadata."""
    run = await get_run_by_id(session, run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return await update_run(
        session,
        run,
        status=payload.status,
        summary=payload.summary,
    )
