"""Artifact model representing uploaded/generated project documents and outputs."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field

from app.core.time import utcnow
from app.models.base import QueryModel

ARTIFACT_TYPES = frozenset({
    "spec",
    "plan",
    "diff",
    "test_report",
    "release_note",
    "other",
})

ARTIFACT_SOURCES = frozenset({
    "telegram",
    "web",
    "generated",
})


class Artifact(QueryModel, table=True):
    """Versioned document/artifact attached to a board and optionally a task."""

    __tablename__ = "artifacts"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    board_id: UUID = Field(foreign_key="boards.id", index=True)
    task_id: UUID | None = Field(default=None, foreign_key="tasks.id", index=True)

    type: str = Field(default="other", index=True)
    source: str = Field(default="web", index=True)

    filename: str
    mime_type: str | None = None
    size_bytes: int = Field(default=0)
    storage_path: str
    checksum: str | None = None

    version: int = Field(default=1)

    created_at: datetime = Field(default_factory=utcnow)
    created_by: UUID | None = Field(
        default=None,
        foreign_key="users.id",
        index=True,
    )
