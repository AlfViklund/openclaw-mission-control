"""Execution lifecycle models for Mission Control task runs and artifacts."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column
from sqlmodel import Field

from app.core.time import utcnow
from app.models.base import QueryModel
from app.models.tenancy import TenantScoped


class ExecutionRun(TenantScoped, table=True):
    """A persisted execution attempt for a task or board-level workflow."""

    __tablename__ = "execution_runs"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    board_id: UUID = Field(foreign_key="boards.id", index=True)
    task_id: UUID | None = Field(default=None, foreign_key="tasks.id", index=True)
    agent_id: UUID | None = Field(default=None, foreign_key="agents.id", index=True)
    scope: str = Field(default="task", index=True)
    runtime_kind: str = Field(default="opencode", index=True)
    runtime_session_key: str | None = Field(default=None, index=True)
    status: str = Field(default="pending", index=True)
    current_phase: str = Field(default="plan", index=True)
    plan_summary: str | None = None
    build_summary: str | None = None
    test_summary: str | None = None
    last_error: str | None = None
    retry_count: int = Field(default=0)
    last_heartbeat_at: datetime | None = Field(default=None, index=True)
    started_at: datetime | None = Field(default=None, index=True)
    completed_at: datetime | None = Field(default=None, index=True)
    execution_state: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
    recovery_state: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow, index=True)


class ExecutionArtifact(QueryModel, table=True):
    """Evidence or intermediate artifact produced by an execution run."""

    __tablename__ = "execution_artifacts"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    execution_run_id: UUID = Field(foreign_key="execution_runs.id", index=True)
    kind: str = Field(index=True)
    title: str
    body: str | None = None
    artifact_state: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow, index=True)
