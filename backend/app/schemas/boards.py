"""Schemas for board create/update/read API operations."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import model_validator
from sqlmodel import Field, SQLModel

_ERR_GOAL_FIELDS_REQUIRED = "Confirmed goal boards require objective and success_metrics"
_ERR_GATEWAY_REQUIRED = "gateway_id is required"
_ERR_DESCRIPTION_REQUIRED = "description is required"
RUNTIME_ANNOTATION_TYPES = (datetime, UUID)


class BoardBase(SQLModel):
    """Shared board fields used across create and read payloads."""

    name: str
    slug: str
    description: str
    gateway_id: UUID | None = None
    board_group_id: UUID | None = None
    board_type: str = "goal"
    objective: str | None = None
    success_metrics: dict[str, object] | None = None
    target_date: datetime | None = None
    goal_confirmed: bool = False
    goal_source: str | None = None
    require_approval_for_done: bool = True
    require_review_before_done: bool = False
    comment_required_for_review: bool = False
    block_status_changes_with_pending_approval: bool = False
    only_lead_can_change_status: bool = False
    is_paused: bool = False
    paused_reason: str | None = None
    max_agents: int = Field(default=1, ge=0)


class BoardCreate(BoardBase):
    """Payload for creating a board."""

    gateway_id: UUID | None = None

    @model_validator(mode="after")
    def validate_goal_fields(self) -> Self:
        """Require gateway and goal details when creating a confirmed goal board."""
        description = self.description.strip()
        if not description:
            raise ValueError(_ERR_DESCRIPTION_REQUIRED)
        self.description = description
        if self.gateway_id is None:
            raise ValueError(_ERR_GATEWAY_REQUIRED)
        if (
            self.board_type == "goal"
            and self.goal_confirmed
            and (not self.objective or not self.success_metrics)
        ):
            raise ValueError(_ERR_GOAL_FIELDS_REQUIRED)
        return self


class BoardUpdate(SQLModel):
    """Payload for partial board updates."""

    name: str | None = None
    slug: str | None = None
    description: str | None = None
    gateway_id: UUID | None = None
    board_group_id: UUID | None = None
    board_type: str | None = None
    objective: str | None = None
    success_metrics: dict[str, object] | None = None
    target_date: datetime | None = None
    goal_confirmed: bool | None = None
    goal_source: str | None = None
    require_approval_for_done: bool | None = None
    require_review_before_done: bool | None = None
    comment_required_for_review: bool | None = None
    block_status_changes_with_pending_approval: bool | None = None
    only_lead_can_change_status: bool | None = None
    is_paused: bool | None = None
    paused_reason: str | None = None
    max_agents: int | None = Field(default=None, ge=0)
    automation_config: dict[str, object] | None = None

    @model_validator(mode="after")
    def validate_gateway_id(self) -> Self:
        """Reject explicit null gateway IDs in patch payloads."""
        # Treat explicit null like "unset" is invalid for patch updates.
        if "gateway_id" in self.model_fields_set and self.gateway_id is None:
            raise ValueError(_ERR_GATEWAY_REQUIRED)
        if "description" in self.model_fields_set:
            if self.description is None:
                raise ValueError(_ERR_DESCRIPTION_REQUIRED)
            description = self.description.strip()
            if not description:
                raise ValueError(_ERR_DESCRIPTION_REQUIRED)
            self.description = description
        return self


class BoardRead(BoardBase):
    """Board payload returned from read endpoints."""

    id: UUID
    organization_id: UUID
    created_at: datetime
    updated_at: datetime


class BoardAutomationSyncStatus(SQLModel):
    """Result of syncing a board automation policy to live agents."""

    status: Literal["success", "partial_failure", "failed", "not_run"] = "not_run"
    agents_updated: int = 0
    gateway_syncs_succeeded: int = 0
    gateway_syncs_failed: int = 0
    failed_agent_ids: list[UUID] = Field(default_factory=list)


class BoardUpdateResult(BoardRead):
    """Board update response including live automation sync status."""

    automation_sync: BoardAutomationSyncStatus = Field(
        default_factory=BoardAutomationSyncStatus,
    )
