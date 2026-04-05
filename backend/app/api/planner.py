"""Planner API endpoints for backlog generation and application."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import col

from app.api.deps import AUTH_DEP
from app.db.pagination import paginate
from app.db.session import get_session
from app.models.planner_outputs import PlannerOutput
from app.schemas.pagination import DefaultLimitOffsetPage
from app.schemas.planner import (
    PlannerApplyRequest,
    PlannerExpandRequest,
    PlannerExpansionRunRead,
    PlannerGenerateRequest,
    PlannerOutputRead,
    PlannerUpdateRequest,
)
from app.schemas.common import OkResponse
from app.services.planner import (
    apply_planner_output,
    generate_backlog,
    list_planner_expansion_runs,
    queue_planner_expansion,
)
from app.services.artifacts import get_artifact_by_id
from app.services.planner_crud import (
    delete_planner_output,
    get_planner_output_by_id,
    list_planner_outputs,
    update_planner_output,
)

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.core.auth import AuthContext

router = APIRouter(prefix="/planner", tags=["planner"])

SESSION_DEP = Depends(get_session)
USER_DEP = AUTH_DEP


@router.post(
    "/generate", response_model=PlannerOutputRead, status_code=status.HTTP_202_ACCEPTED
)
async def generate_backlog_endpoint(
    payload: PlannerGenerateRequest,
    force: bool = Query(
        default=False, description="Force regenerate even if draft exists"
    ),
    session: AsyncSession = SESSION_DEP,
    user: AuthContext = USER_DEP,
) -> PlannerOutput:
    """Queue background backlog generation from a spec artifact."""
    artifact = await get_artifact_by_id(session, payload.artifact_id)
    if not artifact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found"
        )

    try:
        result = await generate_backlog(
            session,
            artifact_id=payload.artifact_id,
            board_id=artifact.board_id,
            max_tasks=payload.max_tasks,
            created_by=user.user.id if user.user else None,
            force=force,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return result


@router.get("", response_model=DefaultLimitOffsetPage[PlannerOutputRead])
async def list_planner_outputs_endpoint(
    board_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    session: AsyncSession = SESSION_DEP,
    _actor: AuthContext = USER_DEP,
) -> DefaultLimitOffsetPage[PlannerOutputRead]:
    """List planner outputs with optional filtering."""
    statement = PlannerOutput.objects.all()
    if board_id is not None:
        statement = statement.filter(col(PlannerOutput.board_id) == board_id)
    if status is not None:
        statement = statement.filter(col(PlannerOutput.status) == status)
    statement = statement.order_by(col(PlannerOutput.created_at).desc())
    return await paginate(session, statement.statement)


@router.get("/{planner_output_id}", response_model=PlannerOutputRead)
async def get_planner_output(
    planner_output_id: UUID,
    session: AsyncSession = SESSION_DEP,
    _actor: AuthContext = USER_DEP,
) -> PlannerOutput:
    """Get a planner output by ID."""
    output = await get_planner_output_by_id(session, planner_output_id)
    if not output:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Planner output not found"
        )
    return output


@router.patch("/{planner_output_id}", response_model=PlannerOutputRead)
async def update_planner_output_endpoint(
    planner_output_id: UUID,
    payload: PlannerUpdateRequest,
    session: AsyncSession = SESSION_DEP,
    _actor: AuthContext = USER_DEP,
) -> PlannerOutput:
    """Update a draft planner output's tasks and epics."""
    output = await get_planner_output_by_id(session, planner_output_id)
    if not output:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Planner output not found"
        )

    try:
        output = await update_planner_output(
            session,
            output,
            tasks=payload.tasks,
            epics=payload.epics,
            expansion_policy=payload.expansion_policy,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return output


@router.post("/{planner_output_id}/apply", response_model=PlannerOutputRead)
async def apply_planner_output_endpoint(
    planner_output_id: UUID,
    payload: PlannerApplyRequest,
    session: AsyncSession = SESSION_DEP,
    _actor: AuthContext = USER_DEP,
) -> PlannerOutput:
    """Apply a planner output, creating real tasks on the board."""
    output = await get_planner_output_by_id(session, planner_output_id)
    if not output:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Planner output not found"
        )

    try:
        output = await apply_planner_output(
            session,
            output,
            tasks_override=payload.tasks,
            epics_override=payload.epics,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return output


@router.get(
    "/{planner_output_id}/expansions",
    response_model=list[PlannerExpansionRunRead],
)
async def list_planner_expansion_runs_endpoint(
    planner_output_id: UUID,
    session: AsyncSession = SESSION_DEP,
    _actor: AuthContext = USER_DEP,
) -> list[PlannerExpansionRunRead]:
    """List recent planner expansion runs for a planner output."""
    output = await get_planner_output_by_id(session, planner_output_id)
    if not output:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Planner output not found"
        )
    return await list_planner_expansion_runs(
        session,
        planner_output_id=planner_output_id,
    )


@router.post("/{planner_output_id}/expand", response_model=PlannerOutputRead)
async def expand_planner_output_endpoint(
    planner_output_id: UUID,
    payload: PlannerExpandRequest,
    session: AsyncSession = SESSION_DEP,
    _actor: AuthContext = USER_DEP,
) -> PlannerOutput:
    """Queue the next planner expansion batch."""
    output = await get_planner_output_by_id(session, planner_output_id)
    if not output:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Planner output not found"
        )
    try:
        output = await queue_planner_expansion(
            session,
            planner_output=output,
            trigger=payload.trigger or "manual",
            max_new_tasks=payload.max_new_tasks,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return output


@router.delete("/{planner_output_id}", response_model=OkResponse)
async def delete_planner_output_endpoint(
    planner_output_id: UUID,
    session: AsyncSession = SESSION_DEP,
    _actor: AuthContext = USER_DEP,
) -> OkResponse:
    """Delete a draft planner output."""
    output = await get_planner_output_by_id(session, planner_output_id)
    if not output:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Planner output not found"
        )

    try:
        await delete_planner_output(session, output)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return OkResponse(ok=True)
