"""CRUD operations for PlannerOutput model."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlmodel import col

from app.models.planner_outputs import PlannerOutput

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession


async def get_planner_output_by_id(
    session: AsyncSession, planner_output_id: UUID
) -> PlannerOutput | None:
    """Fetch a single planner output by its ID."""
    return await PlannerOutput.objects.by_id(planner_output_id).first(session)


async def list_planner_outputs(
    session: AsyncSession,
    *,
    board_id: UUID | None = None,
    status: str | None = None,
) -> list[PlannerOutput]:
    """List planner outputs with optional filters."""
    statement = PlannerOutput.objects.all()
    if board_id is not None:
        statement = statement.filter(col(PlannerOutput.board_id) == board_id)
    if status is not None:
        statement = statement.filter(col(PlannerOutput.status) == status)
    statement = statement.order_by(col(PlannerOutput.created_at).desc())
    return await statement.all(session)


async def update_planner_output(
    session: AsyncSession,
    planner_output: PlannerOutput,
    *,
    tasks: list[dict] | None = None,
    epics: list[dict] | None = None,
) -> PlannerOutput:
    """Update a draft planner output's tasks and epics."""
    if planner_output.status != "draft":
        raise ValueError("Only draft planner outputs can be edited")
    if tasks is not None:
        planner_output.tasks = tasks
    if epics is not None:
        planner_output.epics = epics
    session.add(planner_output)
    await session.commit()
    await session.refresh(planner_output)
    return planner_output


async def delete_planner_output(
    session: AsyncSession, planner_output: PlannerOutput
) -> None:
    """Delete a planner output record."""
    if planner_output.status == "applied":
        raise ValueError("Cannot delete an applied planner output")
    await session.delete(planner_output)
    await session.commit()
