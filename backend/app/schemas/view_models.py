"""Composite read models assembled for board and board-group views."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlmodel import Field, SQLModel

from app.schemas.activity_events import ActivityEventRead
from app.schemas.agents import AgentRead
from app.schemas.approvals import ApprovalRead
from app.schemas.board_groups import BoardGroupRead
from app.schemas.board_memory import BoardMemoryRead
from app.schemas.boards import BoardRead
from app.schemas.tags import TagRef
from app.schemas.tasks import TaskRead

RUNTIME_ANNOTATION_TYPES = (
    datetime,
    UUID,
    ActivityEventRead,
    AgentRead,
    ApprovalRead,
    BoardGroupRead,
    BoardMemoryRead,
    BoardRead,
    TagRef,
)


class TaskCardRead(TaskRead):
    """Task read model enriched with assignee and approval counters."""

    assignee: str | None = None
    approvals_count: int = 0
    approvals_pending_count: int = 0


class BoardSnapshot(SQLModel):
    """Aggregated board payload used by board snapshot endpoints."""

    board: BoardRead
    tasks: list[TaskCardRead]
    agents: list[AgentRead]
    approvals: list[ApprovalRead]
    chat_messages: list[BoardMemoryRead]
    coordination_messages: list[BoardMemoryRead] = Field(default_factory=list)
    runtime_messages: list[BoardMemoryRead] = Field(default_factory=list)
    runtime_events: list[ActivityEventRead] = Field(default_factory=list)
    runtime_integrity: BoardRuntimeIntegrity | None = None
    pending_approvals_count: int = 0


class BoardRuntimeAgentState(SQLModel):
    """Runtime/operator state for one agent on a board."""

    agent_id: UUID
    name: str
    role_key: str
    role_label: str
    status: str
    agent_auth_mode: str | None = None
    pending_agent_token_version: int | None = None
    wake_reason: str | None = None
    last_seen_at: datetime | None = None
    last_provision_error: str | None = None
    agent_auth_last_error: str | None = None
    agent_auth_last_synced_at: datetime | None = None
    assigned_task_count: int = 0
    has_active_run: bool = False
    workspace_path: str | None = None
    workspace_exists: bool = False
    template_sync_state: Literal["ok", "drifted", "missing"] = "missing"
    runtime_blocker: str | None = None


class BoardRuntimeIntegrity(SQLModel):
    """Board-level team/runtime integrity rollup for operator visibility."""

    provision_mode: str | None = None
    expected_roles: list[str] = Field(default_factory=list)
    actual_roles: list[str] = Field(default_factory=list)
    healthy_roles: list[str] = Field(default_factory=list)
    missing_roles: list[str] = Field(default_factory=list)
    stale_roles: list[str] = Field(default_factory=list)
    auth_drift_agent_ids: list[UUID] = Field(default_factory=list)
    template_drift_agent_ids: list[UUID] = Field(default_factory=list)
    missing_first_heartbeat_agent_ids: list[UUID] = Field(default_factory=list)
    platform_blocked_agent_ids: list[UUID] = Field(default_factory=list)
    workspace_missing_agent_ids: list[UUID] = Field(default_factory=list)
    worker_capacity: int = 0
    actual_worker_count: int = 0
    healthy_worker_count: int = 0
    board_max_agents_counts_workers_only: bool = True
    agents: list[BoardRuntimeAgentState] = Field(default_factory=list)


class BoardGroupTaskSummary(SQLModel):
    """Task summary row used inside board-group snapshot responses."""

    id: UUID
    board_id: UUID
    board_name: str
    title: str
    status: str
    priority: str
    assigned_agent_id: UUID | None = None
    assignee: str | None = None
    due_at: datetime | None = None
    in_progress_at: datetime | None = None
    tags: list[TagRef] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class BoardGroupBoardSnapshot(SQLModel):
    """Board-level rollup embedded within a board-group snapshot."""

    board: BoardRead
    task_counts: dict[str, int] = Field(default_factory=dict)
    tasks: list[BoardGroupTaskSummary] = Field(default_factory=list)


class BoardGroupSnapshot(SQLModel):
    """Top-level board-group snapshot response payload."""

    group: BoardGroupRead | None = None
    boards: list[BoardGroupBoardSnapshot] = Field(default_factory=list)
