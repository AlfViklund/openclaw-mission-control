"""Execution run API for persisted plan/build/test/review state."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.db.session import get_session
from app.models.agents import Agent
from app.models.boards import Board
from app.models.execution_runs import ExecutionArtifact, ExecutionRun
from app.models.tasks import Task
from app.schemas.executions import (
    ExecutionHeartbeatCreate,
    ExecutionArtifactCreate,
    ExecutionArtifactRead,
    ExecutionPhaseResultCreate,
    ExecutionPhase,
    ExecutionRunCreate,
    ExecutionRunRead,
    ExecutionRunStart,
    ExecutionRunUpdate,
)
from app.services.execution_dispatch import QueuedExecutionRunDispatch
from app.services.execution_dispatch import enqueue_execution_dispatch
from app.services.execution_orchestration import ExecutionOrchestrationService

router = APIRouter(prefix="/boards/{board_id}/execution-runs", tags=["executions"])


async def _get_board_or_404(session: AsyncSession, board_id: UUID) -> Board:
    board = await session.get(Board, board_id)
    if board is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Board not found")
    return board


async def _get_execution_run_or_404(
    session: AsyncSession, board_id: UUID, run_id: UUID
) -> ExecutionRun:
    stmt = select(ExecutionRun).where(ExecutionRun.id == run_id, ExecutionRun.board_id == board_id)
    run = (await session.exec(stmt)).one_or_none()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution run not found")
    return run


def _to_execution_run_read(run: ExecutionRun) -> ExecutionRunRead:
    read = ExecutionRunRead.model_validate(run)
    heartbeat_age_seconds: float | None = None
    if run.last_heartbeat_at is not None:
        heartbeat_age_seconds = max(0.0, (utcnow() - run.last_heartbeat_at).total_seconds())
    is_stale = bool(
        run.status == "running"
        and heartbeat_age_seconds is not None
        and heartbeat_age_seconds >= ExecutionOrchestrationService.stale_after_seconds()
    )
    can_resume = bool(run.status in {"paused", "failed"} or is_stale)
    can_heartbeat = bool(run.status == "running" and not is_stale)
    return read.model_copy(
        update={
            "is_stale": is_stale,
            "can_resume": can_resume,
            "can_heartbeat": can_heartbeat,
            "heartbeat_age_seconds": heartbeat_age_seconds,
        },
    )


@router.get("/", response_model=list[ExecutionRunRead])
async def list_execution_runs(
    board_id: UUID, session: AsyncSession = Depends(get_session)
) -> list[ExecutionRunRead]:
    await _get_board_or_404(session, board_id)
    stmt = (
        select(ExecutionRun)
        .where(ExecutionRun.board_id == board_id)
        .order_by(desc(col(ExecutionRun.created_at)))
    )
    runs = (await session.exec(stmt)).all()
    return [_to_execution_run_read(run) for run in runs]


@router.post("/", response_model=ExecutionRunRead, status_code=status.HTTP_201_CREATED)
async def create_execution_run(
    board_id: UUID,
    payload: ExecutionRunCreate,
    session: AsyncSession = Depends(get_session),
) -> ExecutionRunRead:
    await _get_board_or_404(session, board_id)

    if payload.task_id is not None:
        task = await session.get(Task, payload.task_id)
        if task is None or task.board_id != board_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Task does not belong to board",
            )

    if payload.agent_id is not None:
        agent = await session.get(Agent, payload.agent_id)
        if agent is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent not found")

    run = ExecutionRun(board_id=board_id, **payload.model_dump(exclude_unset=True))
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return _to_execution_run_read(run)


@router.get("/{run_id}", response_model=ExecutionRunRead)
async def get_execution_run(
    board_id: UUID,
    run_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ExecutionRunRead:
    run = await _get_execution_run_or_404(session, board_id, run_id)
    return _to_execution_run_read(run)


@router.patch("/{run_id}", response_model=ExecutionRunRead)
async def update_execution_run(
    board_id: UUID,
    run_id: UUID,
    payload: ExecutionRunUpdate,
    session: AsyncSession = Depends(get_session),
) -> ExecutionRunRead:
    run = await _get_execution_run_or_404(session, board_id, run_id)

    data = payload.model_dump(exclude_unset=True)
    if "agent_id" in data and data["agent_id"] is not None:
        agent = await session.get(Agent, data["agent_id"])
        if agent is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent not found")

    for key, value in data.items():
        setattr(run, key, value)

    run.updated_at = utcnow()
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return _to_execution_run_read(run)


@router.get("/{run_id}/artifacts", response_model=list[ExecutionArtifactRead])
async def list_execution_artifacts(
    board_id: UUID,
    run_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> list[ExecutionArtifactRead]:
    await _get_execution_run_or_404(session, board_id, run_id)
    stmt = (
        select(ExecutionArtifact)
        .where(ExecutionArtifact.execution_run_id == run_id)
        .order_by(desc(col(ExecutionArtifact.created_at)))
    )
    artifacts = (await session.exec(stmt)).all()
    return [ExecutionArtifactRead.model_validate(item) for item in artifacts]


@router.post(
    "/{run_id}/artifacts",
    response_model=ExecutionArtifactRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_execution_artifact(
    board_id: UUID,
    run_id: UUID,
    payload: ExecutionArtifactCreate,
    session: AsyncSession = Depends(get_session),
) -> ExecutionArtifactRead:
    await _get_execution_run_or_404(session, board_id, run_id)

    artifact = ExecutionArtifact(execution_run_id=run_id, **payload.model_dump(exclude_unset=True))
    session.add(artifact)
    await session.commit()
    await session.refresh(artifact)
    return ExecutionArtifactRead.model_validate(artifact)


@router.post("/{run_id}/start", response_model=ExecutionRunRead)
async def start_execution_run(
    board_id: UUID,
    run_id: UUID,
    payload: ExecutionRunStart,
    session: AsyncSession = Depends(get_session),
) -> ExecutionRunRead:
    await _get_board_or_404(session, board_id)
    run = await ExecutionOrchestrationService(session).start_run(
        board_id=board_id,
        run_id=run_id,
        runtime_session_key=payload.runtime_session_key,
        execution_state_patch=payload.execution_state_patch,
        recovery_state_patch=payload.recovery_state_patch,
    )
    return _to_execution_run_read(run)


@router.post(
    "/{run_id}/dispatch",
    response_model=ExecutionArtifactRead,
    status_code=status.HTTP_201_CREATED,
)
async def dispatch_execution_run(
    board_id: UUID,
    run_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ExecutionArtifactRead:
    await _get_board_or_404(session, board_id)
    artifact = await ExecutionOrchestrationService(session).dispatch_run_instruction(
        board_id=board_id,
        run_id=run_id,
    )
    return ExecutionArtifactRead.model_validate(artifact)


@router.post("/{run_id}/dispatch/queue", status_code=status.HTTP_202_ACCEPTED)
async def queue_execution_run_dispatch(
    board_id: UUID,
    run_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    await _get_board_or_404(session, board_id)
    ok = enqueue_execution_dispatch(
        QueuedExecutionRunDispatch(board_id=board_id, run_id=run_id),
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to enqueue execution dispatch",
    )
    return {"status": "queued"}


@router.post("/{run_id}/resume", response_model=ExecutionRunRead)
async def resume_execution_run(
    board_id: UUID,
    run_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ExecutionRunRead:
    await _get_board_or_404(session, board_id)
    run = await ExecutionOrchestrationService(session).resume_run(
        board_id=board_id,
        run_id=run_id,
    )
    return _to_execution_run_read(run)


@router.post("/{run_id}/heartbeat", response_model=ExecutionArtifactRead, status_code=status.HTTP_201_CREATED)
async def record_execution_heartbeat(
    board_id: UUID,
    run_id: UUID,
    payload: ExecutionHeartbeatCreate,
    session: AsyncSession = Depends(get_session),
) -> ExecutionArtifactRead:
    await _get_board_or_404(session, board_id)
    artifact = await ExecutionOrchestrationService(session).record_heartbeat(
        board_id=board_id,
        run_id=run_id,
        message=payload.message,
        runtime_session_key=payload.runtime_session_key,
        source=payload.source,
    )
    return ExecutionArtifactRead.model_validate(artifact)


@router.post("/{run_id}/phases/{phase}", response_model=ExecutionArtifactRead, status_code=status.HTTP_201_CREATED)
async def record_execution_phase_result(
    board_id: UUID,
    run_id: UUID,
    phase: ExecutionPhase,
    payload: ExecutionPhaseResultCreate,
    session: AsyncSession = Depends(get_session),
) -> ExecutionArtifactRead:
    await _get_board_or_404(session, board_id)
    artifact = await ExecutionOrchestrationService(session).record_phase_result(
        board_id=board_id,
        run_id=run_id,
        phase=phase,
        title=payload.title,
        body=payload.body,
        artifact_state=payload.artifact_state,
        execution_state_patch=payload.execution_state_patch,
        recovery_state_patch=payload.recovery_state_patch,
        runtime_session_key=payload.runtime_session_key,
    )
    return ExecutionArtifactRead.model_validate(artifact)
