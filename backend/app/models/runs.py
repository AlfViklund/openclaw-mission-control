"""Run model representing a single agent execution for a task stage."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column
from sqlmodel import Field

from app.core.time import utcnow
from app.models.base import QueryModel

RUN_RUNTIMES = frozenset({"acp", "opencode_cli", "openrouter"})
RUN_STAGES = frozenset({"plan", "build", "test"})
RUN_STATUSES = frozenset({"queued", "running", "failed", "succeeded", "canceled"})


class Run(QueryModel, table=True):
    """Single execution run of a task stage on a specific runtime."""

    __tablename__ = "runs"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    task_id: UUID = Field(foreign_key="tasks.id", index=True)
    agent_id: UUID | None = Field(default=None, foreign_key="agents.id", index=True)

    runtime: str = Field(default="acp", index=True)
    stage: str = Field(default="plan", index=True)
    status: str = Field(default="queued", index=True)

    started_at: datetime | None = None
    finished_at: datetime | None = None

    model: str | None = None
    temperature: float | None = None
    permissions_profile: str | None = None

    evidence_paths: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    summary: str | None = None

    error_message: str | None = None

    run_metadata: dict = Field(
        default_factory=dict,
        sa_column=Column("run_metadata", JSON),
    )

    created_at: datetime = Field(default_factory=utcnow)
