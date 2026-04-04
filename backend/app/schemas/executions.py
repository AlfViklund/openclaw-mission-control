"""Schemas for Mission Control execution runs and evidence artifacts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlmodel import Field, SQLModel

ExecutionScope = Literal["task", "board"]
ExecutionStatus = Literal["pending", "running", "blocked", "failed", "paused", "done"]
ExecutionPhase = Literal["plan", "build", "test", "review", "done"]
ArtifactKind = Literal["plan", "build", "test", "review", "log", "diff", "checkpoint", "heartbeat"]


class ExecutionRunBase(SQLModel):
    """Shared execution run fields."""

    task_id: UUID | None = None
    agent_id: UUID | None = None
    scope: ExecutionScope = "task"
    runtime_kind: str = "opencode"
    runtime_session_key: str | None = None
    status: ExecutionStatus = "pending"
    current_phase: ExecutionPhase = "plan"
    plan_summary: str | None = None
    build_summary: str | None = None
    test_summary: str | None = None
    last_error: str | None = None
    retry_count: int = 0
    last_heartbeat_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    execution_state: dict[str, Any] | None = Field(default=None)
    recovery_state: dict[str, Any] | None = Field(default=None)


class ExecutionRunCreate(ExecutionRunBase):
    """Payload for creating an execution run."""


class ExecutionRunStart(SQLModel):
    """Payload for starting an execution run."""

    runtime_session_key: str | None = None
    execution_state_patch: dict[str, Any] | None = Field(default=None)
    recovery_state_patch: dict[str, Any] | None = Field(default=None)


class ExecutionHeartbeatCreate(SQLModel):
    """Payload for recording a run heartbeat."""

    message: str | None = None
    runtime_session_key: str | None = None
    source: str = "operator"


class ExecutionRunUpdate(SQLModel):
    """Partial update payload for execution runs."""

    agent_id: UUID | None = None
    scope: ExecutionScope | None = None
    runtime_kind: str | None = None
    runtime_session_key: str | None = None
    status: ExecutionStatus | None = None
    current_phase: ExecutionPhase | None = None
    plan_summary: str | None = None
    build_summary: str | None = None
    test_summary: str | None = None
    last_error: str | None = None
    retry_count: int | None = None
    last_heartbeat_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    execution_state: dict[str, Any] | None = None
    recovery_state: dict[str, Any] | None = None


class ExecutionRunRead(ExecutionRunBase):
    """Payload returned by execution run endpoints."""

    id: UUID
    board_id: UUID
    is_stale: bool = False
    can_resume: bool = False
    can_heartbeat: bool = False
    heartbeat_age_seconds: float | None = None
    created_at: datetime
    updated_at: datetime


class ExecutionArtifactBase(SQLModel):
    """Shared artifact fields."""

    kind: ArtifactKind
    title: str
    body: str | None = None
    artifact_state: dict[str, Any] | None = Field(default=None)


class ExecutionArtifactCreate(ExecutionArtifactBase):
    """Payload for creating a run artifact."""


class ExecutionPhaseResultCreate(SQLModel):
    """Payload for recording the evidence produced by a completed phase."""

    title: str
    body: str | None = None
    artifact_state: dict[str, Any] | None = Field(default=None)
    execution_state_patch: dict[str, Any] | None = Field(default=None)
    recovery_state_patch: dict[str, Any] | None = Field(default=None)
    runtime_session_key: str | None = None


class ExecutionArtifactRead(ExecutionArtifactBase):
    """Payload returned by run artifact endpoints."""

    id: UUID
    execution_run_id: UUID
    created_at: datetime
    updated_at: datetime
