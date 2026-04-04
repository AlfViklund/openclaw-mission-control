"""Spec artifact CRUD and planner draft generation endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_board_for_actor_read, get_board_for_actor_write
from app.core.time import utcnow
from app.db.session import get_session
from app.models.boards import Board
from app.models.spec_artifacts import SpecArtifact
from app.schemas.spec_artifacts import (
    PlannerDraftRead,
    SpecArtifactCreate,
    SpecArtifactRead,
)
from app.schemas.tasks import TaskRead
from app.services.spec_planner import apply_planner_draft, build_planner_draft

router = APIRouter(prefix="/boards/{board_id}/spec-artifacts", tags=["planner"])

BOARD_READ_DEP = Depends(get_board_for_actor_read)
BOARD_WRITE_DEP = Depends(get_board_for_actor_write)
SESSION_DEP = Depends(get_session)


async def _get_spec_artifact_or_404(
    session: AsyncSession,
    *,
    board_id: UUID,
    spec_artifact_id: UUID,
) -> SpecArtifact:
    stmt = select(SpecArtifact).where(
        SpecArtifact.id == spec_artifact_id,
        SpecArtifact.board_id == board_id,
    )
    spec_artifact = (await session.exec(stmt)).one_or_none()
    if spec_artifact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Spec artifact not found",
        )
    return spec_artifact


@router.get("/", response_model=list[SpecArtifactRead])
async def list_spec_artifacts(
    board_id: UUID,
    _: Board = BOARD_READ_DEP,
    session: AsyncSession = SESSION_DEP,
) -> list[SpecArtifactRead]:
    stmt = (
        select(SpecArtifact)
        .where(SpecArtifact.board_id == board_id)
        .order_by(desc(col(SpecArtifact.created_at)))
    )
    spec_artifacts = (await session.exec(stmt)).all()
    return [SpecArtifactRead.model_validate(item) for item in spec_artifacts]


@router.post("/", response_model=SpecArtifactRead, status_code=status.HTTP_201_CREATED)
async def create_spec_artifact(
    board_id: UUID,
    payload: SpecArtifactCreate,
    _: Board = BOARD_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
) -> SpecArtifactRead:
    spec_artifact = SpecArtifact(board_id=board_id, **payload.model_dump(exclude_unset=True))
    session.add(spec_artifact)
    await session.commit()
    await session.refresh(spec_artifact)
    return SpecArtifactRead.model_validate(spec_artifact)


@router.get("/{spec_artifact_id}", response_model=SpecArtifactRead)
async def get_spec_artifact(
    board_id: UUID,
    spec_artifact_id: UUID,
    _: Board = BOARD_READ_DEP,
    session: AsyncSession = SESSION_DEP,
) -> SpecArtifactRead:
    spec_artifact = await _get_spec_artifact_or_404(
        session,
        board_id=board_id,
        spec_artifact_id=spec_artifact_id,
    )
    return SpecArtifactRead.model_validate(spec_artifact)


@router.post("/{spec_artifact_id}/draft", response_model=PlannerDraftRead)
async def draft_spec_artifact(
    board_id: UUID,
    spec_artifact_id: UUID,
    _: Board = BOARD_READ_DEP,
    session: AsyncSession = SESSION_DEP,
) -> PlannerDraftRead:
    spec_artifact = await _get_spec_artifact_or_404(
        session,
        board_id=board_id,
        spec_artifact_id=spec_artifact_id,
    )
    return build_planner_draft(spec_artifact)


@router.post("/{spec_artifact_id}/apply", response_model=list[TaskRead])
async def apply_spec_artifact(
    board_id: UUID,
    spec_artifact_id: UUID,
    _: Board = BOARD_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
) -> list[TaskRead]:
    spec_artifact = await _get_spec_artifact_or_404(
        session,
        board_id=board_id,
        spec_artifact_id=spec_artifact_id,
    )
    draft = build_planner_draft(spec_artifact)
    created = await apply_planner_draft(
        session,
        board_id=board_id,
        spec_artifact=spec_artifact,
        draft=draft,
    )
    spec_artifact.updated_at = utcnow()
    session.add(spec_artifact)
    await session.commit()
    for task in created:
        await session.refresh(task)
    created_by_key = {node.key: task for node, task in zip(draft.nodes, created, strict=True)}
    task_reads: list[TaskRead] = []
    for node, task in zip(draft.nodes, created, strict=True):
        parent_task = created_by_key.get(node.parent_key) if node.parent_key else None
        dependency_ids = [parent_task.id] if parent_task is not None else []
        task_reads.append(
            TaskRead.model_validate(task, from_attributes=True).model_copy(
                update={
                    "depends_on_task_ids": dependency_ids,
                    "blocked_by_task_ids": dependency_ids,
                    "is_blocked": bool(dependency_ids),
                },
            ),
        )
    return task_reads
