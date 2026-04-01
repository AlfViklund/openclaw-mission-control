"""Schemas for run create/read/update API payloads."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import SQLModel


class RunCreate(SQLModel):
    """Payload for creating and starting a run."""

    task_id: UUID
    agent_id: UUID | None = None
    runtime: str = "acp"
    stage: str = "plan"
    model: str | None = None
    temperature: float | None = None
    permissions_profile: str | None = None


class RunUpdate(SQLModel):
    """Payload for updating run metadata."""

    status: str | None = None
    summary: str | None = None


class RunRead(SQLModel):
    """Serialized run returned from read endpoints."""

    id: UUID
    task_id: UUID
    agent_id: UUID | None = None
    runtime: str
    stage: str
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    model: str | None = None
    temperature: float | None = None
    permissions_profile: str | None = None
    evidence_paths: list[dict]
    summary: str | None = None
    error_message: str | None = None
    created_at: datetime


class RunEvidenceRead(SQLModel):
    """Evidence paths for a run."""

    run_id: UUID
    evidence: list[dict]
