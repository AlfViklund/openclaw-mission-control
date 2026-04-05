"""Schemas for planner output generate/read/apply API payloads."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field as PydanticField
from sqlmodel import SQLModel


class PlannerTaskItem(SQLModel):
    """Single task within a planner output."""

    id: str
    epic_id: str | None = None
    title: str
    description: str | None = None
    acceptance_criteria: list[str] = PydanticField(default_factory=list)
    depends_on: list[str] = PydanticField(default_factory=list)
    tags: list[str] = PydanticField(default_factory=list)
    estimate: str | None = None
    suggested_agent_role: str | None = None


class PlannerEpicItem(SQLModel):
    """Single epic grouping tasks."""

    id: str
    title: str
    description: str | None = None


class PlannerGenerateRequest(SQLModel):
    """Request to generate a backlog from a spec artifact."""

    artifact_id: UUID
    max_tasks: int = PydanticField(default=50, ge=1, le=200)
    granularity: str = PydanticField(default="task")


class PlannerApplyRequest(SQLModel):
    """Request to apply a planner output as real tasks on a board."""

    tasks: list[dict] | None = None
    epics: list[dict] | None = None


class PlannerUpdateRequest(SQLModel):
    """Request to update a draft planner output."""

    tasks: list[dict] | None = None
    epics: list[dict] | None = None


class PlannerOutputRead(SQLModel):
    """Serialized planner output returned from read endpoints."""

    id: UUID
    board_id: UUID
    artifact_id: UUID
    status: str
    pipeline_phase: str
    json_schema_version: int
    epics: list[dict]
    tasks: list[dict]
    documents: list[dict]
    phase_statuses: list[dict]
    parallelism_groups: list[dict]
    error_message: str | None = None
    created_at: datetime
    created_by: UUID | None = None
    applied_at: datetime | None = None


class PlannerOutputListResponse(SQLModel):
    """Paginated list of planner outputs."""

    items: list[PlannerOutputRead]
    total: int
