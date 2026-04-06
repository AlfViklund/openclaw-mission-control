"""Schemas for task-first pipeline summary and execution actions."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import Field, SQLModel

from app.schemas.runs import RunRead


class CompletionReportRead(SQLModel):
    """Machine-readable completion evidence attached to a task comment."""

    summary: str
    files_touched: list[str] = Field(default_factory=list)
    checks_run: list[str] = Field(default_factory=list)
    checks_result: str
    artifacts: list[str] = Field(default_factory=list)
    known_risks: list[str] = Field(default_factory=list)


class PipelineStageStateRead(SQLModel):
    """Latest execution state for one pipeline stage."""

    stage: str
    status: str
    latest_run: RunRead | None = None


class PipelineTaskSummaryRead(SQLModel):
    """Task-first execution summary used by UI and board agents."""

    task_id: UUID
    task_status: str
    work_state: str | None = None
    can_start_work: bool = False
    use_start_work: bool = False
    recommended_runtime: str
    next_required_stage: str | None = None
    requires_approval: bool = False
    approval_reason: str | None = None
    ready_for_review: bool = False
    latest_failed_stage: str | None = None
    latest_failure_kind: str | None = None
    runtime_ready: bool = False
    runtime_blocker_code: str | None = None
    runtime_blocker: str | None = None
    execution_mode: str = "pipeline"
    cooldown_until: datetime | None = None
    cooldown_message: str | None = None
    degraded_allowed: bool = False
    recommended_action: str | None = None
    queue_state: str | None = None
    queue_position: int | None = None
    latest_completion_report: CompletionReportRead | None = None
    stages: list[PipelineStageStateRead] = Field(default_factory=list)
