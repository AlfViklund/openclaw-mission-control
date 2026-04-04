"""Spec artifacts captured for planner input and backlog generation."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field

from app.core.time import utcnow
from app.models.tenancy import TenantScoped


class SpecArtifact(TenantScoped, table=True):
    """Persisted source spec that can be converted into a task DAG."""

    __tablename__ = "spec_artifacts"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    board_id: UUID = Field(foreign_key="boards.id", index=True)
    title: str = Field(max_length=255)
    body: str
    source: str = Field(default="markdown", index=True, max_length=32)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow, index=True)
