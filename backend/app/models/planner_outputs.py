"""PlannerOutput model representing generated backlog from a specification."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column
from sqlmodel import Field

from app.core.time import utcnow
from app.models.base import QueryModel

PLANNER_STATUSES = frozenset(
    {"generating", "draft", "applied", "rejected", "failed"}
)


class PlannerOutput(QueryModel, table=True):
    """Generated backlog structure from a specification artifact."""

    __tablename__ = "planner_outputs"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    board_id: UUID = Field(foreign_key="boards.id", index=True)
    artifact_id: UUID | None = Field(
        default=None, foreign_key="artifacts.id", index=True
    )

    status: str = Field(default="draft", index=True)
    json_schema_version: int = Field(default=1)

    epics: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    tasks: list[dict] = Field(default_factory=list, sa_column=Column(JSON))

    # Computed parallelism levels (which tasks can run simultaneously)
    parallelism_groups: list[dict] = Field(default_factory=list, sa_column=Column(JSON))

    error_message: str | None = None

    created_at: datetime = Field(default_factory=utcnow)
    created_by: UUID | None = Field(
        default=None,
        foreign_key="users.id",
        index=True,
    )
    applied_at: datetime | None = None
