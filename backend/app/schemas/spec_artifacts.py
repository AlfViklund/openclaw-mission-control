"""Schemas for persisted spec artifacts and planner DAG drafts."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import Field, SQLModel

from app.schemas.common import NonEmptyStr


class SpecArtifactBase(SQLModel):
    """Shared spec artifact payload fields."""

    title: NonEmptyStr
    body: NonEmptyStr
    source: str = "markdown"


class SpecArtifactCreate(SpecArtifactBase):
    """Payload for creating a spec artifact."""


class SpecArtifactRead(SpecArtifactBase):
    """Persisted spec artifact payload."""

    id: UUID
    board_id: UUID
    created_at: datetime
    updated_at: datetime


class PlannerDraftNodeRead(SQLModel):
    """Single node in a generated planner draft."""

    key: str
    title: str
    depth: int
    source_line: int
    parent_key: str | None = None
    depends_on_keys: list[str] = Field(default_factory=list)


class PlannerDraftRead(SQLModel):
    """Generated planner draft for a spec artifact."""

    spec_artifact_id: UUID
    spec_title: str
    node_count: int
    nodes: list[PlannerDraftNodeRead]
