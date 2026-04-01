"""Schemas for artifact create/read/update API payloads."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import SQLModel

RUNTIME_ANNOTATION_TYPES = (datetime, UUID)


class ArtifactCreate(SQLModel):
    """Payload for creating an artifact metadata record (file upload handled separately)."""

    board_id: UUID
    task_id: UUID | None = None
    type: str = "other"
    source: str = "web"
    filename: str
    mime_type: str | None = None
    size_bytes: int = 0
    checksum: str | None = None
    version: int = 1


class ArtifactUpdate(SQLModel):
    """Payload for updating artifact metadata."""

    task_id: UUID | None = None
    filename: str | None = None


class ArtifactRead(SQLModel):
    """Serialized artifact returned from read endpoints."""

    id: UUID
    board_id: UUID
    task_id: UUID | None = None
    type: str
    source: str
    filename: str
    mime_type: str | None = None
    size_bytes: int
    storage_path: str
    checksum: str | None = None
    version: int
    created_at: datetime
    created_by: UUID | None = None
