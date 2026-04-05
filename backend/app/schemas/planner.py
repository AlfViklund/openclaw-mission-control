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
    max_tasks: int | None = PydanticField(default=None, ge=1, le=200)
    granularity: str = PydanticField(default="task")


class PlannerApplyRequest(SQLModel):
    """Request to apply a planner output as real tasks on a board."""

    tasks: list[dict] | None = None
    epics: list[dict] | None = None


class PlannerUpdateRequest(SQLModel):
    """Request to update a draft planner output."""

    tasks: list[dict] | None = None
    epics: list[dict] | None = None
    expansion_policy: dict[str, object] | None = None


class PlannerExpandRequest(SQLModel):
    """Request to expand the next planner task batch."""

    trigger: str | None = None
    max_new_tasks: int | None = PydanticField(default=None, ge=1, le=50)


class PlannerEpicStateRead(SQLModel):
    """Execution state for an epic within an approved planner package."""

    epic_id: str
    status: str
    coverage_summary: str | None = None
    remaining_work_summary: str | None = None
    materialized_tasks: int = 0
    done_tasks: int = 0
    open_acceptance_items: list[str] = PydanticField(default_factory=list)
    next_focus_roles: list[str] = PydanticField(default_factory=list)


class PlannerExpansionRunRead(SQLModel):
    """Single planner expansion run for history/audit views."""

    id: UUID
    planner_output_id: UUID
    board_id: UUID
    round_number: int
    status: str
    trigger: str
    source_epic_ids: list[str] = PydanticField(default_factory=list)
    created_task_ids: list[str] = PydanticField(default_factory=list)
    summary: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class PlannerExecutionCoverageRead(SQLModel):
    """Board-level execution coverage summary for the latest applied planner package."""

    board_id: UUID
    planner_output_id: UUID | None = None
    planner_status: str | None = None
    docs_count: int = 0
    epics_total: int = 0
    epics_active: int = 0
    epics_completed: int = 0
    materialized_tasks: int = 0
    done_tasks: int = 0
    in_progress_tasks: int = 0
    review_tasks: int = 0
    inbox_tasks: int = 0
    remaining_scope_count: int | None = None
    remaining_scope_summary: str | None = None
    active_epics: list[PlannerEpicStateRead] = PydanticField(default_factory=list)
    next_expansion_eligible: bool = False
    next_expansion_reason: str | None = None
    auto_expand_enabled: bool = False
    expansion_policy: dict[str, object] = PydanticField(default_factory=dict)
    last_expansion_run: PlannerExpansionRunRead | None = None


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
    epic_states: list[dict]
    expansion_policy: dict[str, object]
    parallelism_groups: list[dict]
    materialized_task_count: int
    remaining_scope_count: int | None = None
    error_message: str | None = None
    created_at: datetime
    created_by: UUID | None = None
    applied_at: datetime | None = None
    latest_expansion_at: datetime | None = None


class PlannerOutputListResponse(SQLModel):
    """Paginated list of planner outputs."""

    items: list[PlannerOutputRead]
    total: int
