"""Planner expansion run audit records for progressive materialization."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column
from sqlmodel import Field

from app.core.time import utcnow
from app.models.base import QueryModel


class PlannerExpansionRun(QueryModel, table=True):
    """Track each planner expansion attempt for idempotency and operator review."""

    __tablename__ = "planner_expansion_runs"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    planner_output_id: UUID = Field(foreign_key="planner_outputs.id", index=True)
    board_id: UUID = Field(foreign_key="boards.id", index=True)
    round_number: int = Field(default=1)
    status: str = Field(default="running", index=True)
    trigger: str = Field(default="manual", index=True)
    source_epic_ids: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    created_task_ids: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    summary: str | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
