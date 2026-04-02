"""Schemas used by the board-onboarding assistant flow."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator
from sqlmodel import SQLModel

from app.schemas.common import NonEmptyStr
from app.schemas.boards import BoardRead

_RUNTIME_TYPE_REFERENCES = (datetime, UUID, NonEmptyStr)


class BoardOnboardingStart(SQLModel):
    """Start signal for initializing onboarding conversation."""


class BoardOnboardingAnswer(SQLModel):
    """User answer payload for a single onboarding question."""

    answer: NonEmptyStr
    other_text: str | None = None


class BoardOnboardingConfirm(SQLModel):
    """Payload used to confirm generated onboarding draft fields."""

    board_type: str
    objective: str | None = None
    success_metrics: dict[str, object] | None = None
    target_date: datetime | None = None

    @model_validator(mode="after")
    def validate_goal_fields(self) -> Self:
        """Require goal metadata when the board type is `goal`."""
        if self.board_type == "goal" and (
            not self.objective or not self.success_metrics
        ):
            message = "Confirmed goal boards require objective and success_metrics"
            raise ValueError(message)
        return self


class BoardOnboardingQuestionOption(SQLModel):
    """Selectable option for an onboarding question."""

    id: NonEmptyStr
    label: NonEmptyStr


class BoardOnboardingAgentQuestion(SQLModel):
    """Question payload emitted by the onboarding assistant."""

    question: NonEmptyStr
    options: list[BoardOnboardingQuestionOption] = Field(min_length=1)


def _normalize_optional_text(value: object) -> object | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return value


class BoardOnboardingUserProfile(SQLModel):
    """User-profile preferences gathered during onboarding."""

    preferred_name: str | None = None
    pronouns: str | None = None
    timezone: str | None = None
    notes: str | None = None
    context: str | None = None

    @field_validator(
        "preferred_name",
        "pronouns",
        "timezone",
        "notes",
        "context",
        mode="before",
    )
    @classmethod
    def normalize_text(cls, value: object) -> object | None:
        """Trim optional free-form profile text fields."""
        return _normalize_optional_text(value)


LeadAgentAutonomyLevel = Literal["ask_first", "balanced", "autonomous"]
LeadAgentVerbosity = Literal["concise", "balanced", "detailed"]
LeadAgentOutputFormat = Literal["bullets", "mixed", "narrative"]
LeadAgentUpdateCadence = Literal["asap", "hourly", "daily", "weekly"]


class BoardOnboardingLeadAgentDraft(SQLModel):
    """Editable lead-agent draft configuration."""

    name: NonEmptyStr | None = None
    # role, communication_style, emoji are expected keys.
    identity_profile: dict[str, str] | None = None
    autonomy_level: LeadAgentAutonomyLevel | None = None
    verbosity: LeadAgentVerbosity | None = None
    output_format: LeadAgentOutputFormat | None = None
    update_cadence: LeadAgentUpdateCadence | None = None
    custom_instructions: str | None = None

    @field_validator(
        "autonomy_level",
        "verbosity",
        "output_format",
        "update_cadence",
        "custom_instructions",
        mode="before",
    )
    @classmethod
    def normalize_text_fields(cls, value: object) -> object | None:
        """Trim optional lead-agent preference fields."""
        return _normalize_optional_text(value)

    @field_validator("identity_profile", mode="before")
    @classmethod
    def normalize_identity_profile(
        cls,
        value: object,
    ) -> object | None:
        """Normalize identity profile keys and values as trimmed strings."""
        if value is None:
            return None
        if not isinstance(value, dict):
            return value
        normalized: dict[str, str] = {}
        for raw_key, raw_val in value.items():
            if raw_val is None:
                continue
            key = str(raw_key).strip()
            if not key:
                continue
            val = str(raw_val).strip()
            if val:
                normalized[key] = val
        return normalized or None


class BoardOnboardingTeamPlan(SQLModel):
    """Team shape and provisioning preferences gathered during onboarding."""

    roles: list[str] | None = None
    provision_full_team: bool = False
    optional_roles: list[str] = Field(default_factory=list)
    notes: str | None = None

    @field_validator("roles", "optional_roles", mode="before")
    @classmethod
    def normalize_roles(cls, value: object) -> object | None:
        if value is None:
            return None
        if not isinstance(value, list):
            return value
        return [str(v).strip() for v in value if str(v).strip()]

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_notes(cls, value: object) -> object | None:
        return _normalize_optional_text(value)


class BoardOnboardingPlanningPolicy(SQLModel):
    """Planner and backlog bootstrap preferences gathered during onboarding."""

    generate_initial_backlog: bool = False
    planner_mode: str | None = None
    bootstrap_after_confirm: bool = False
    notes: str | None = None

    @field_validator("planner_mode", "notes", mode="before")
    @classmethod
    def normalize_text_fields(cls, value: object) -> object | None:
        return _normalize_optional_text(value)


class BoardOnboardingQaPolicy(SQLModel):
    """QA and pipeline enforcement preferences gathered during onboarding."""

    level: str | None = None
    run_smoke_after_build: bool = True
    require_approval_for_done: bool | None = None

    @field_validator("level", mode="before")
    @classmethod
    def normalize_level(cls, value: object) -> object | None:
        return _normalize_optional_text(value)


class BoardOnboardingAutomationPolicy(SQLModel):
    """Automation and agent heartbeat preferences gathered during onboarding."""

    online_every_seconds: int | None = None
    idle_every_seconds: int | None = None
    dormant_every_seconds: int | None = None
    wake_on_approvals: bool = True
    wake_on_review_queue: bool = True
    allow_assist_mode_when_no_tasks: bool = False

    @field_validator(
        "online_every_seconds",
        "idle_every_seconds",
        "dormant_every_seconds",
        mode="before",
    )
    @classmethod
    def normalize_seconds(cls, value: object) -> object | None:
        if value is None:
            return None
        try:
            return int(value)  # type: ignore[arg-type]
        except (ValueError, TypeError):
            return None


class BoardOnboardingAgentComplete(BoardOnboardingConfirm):
    """Complete onboarding draft produced by the onboarding assistant."""

    status: Literal["complete"]
    user_profile: BoardOnboardingUserProfile | None = None
    lead_agent: BoardOnboardingLeadAgentDraft | None = None
    team_plan: BoardOnboardingTeamPlan | None = None
    planning_policy: BoardOnboardingPlanningPolicy | None = None
    qa_policy: BoardOnboardingQaPolicy | None = None
    automation_policy: BoardOnboardingAutomationPolicy | None = None


BoardOnboardingAgentUpdate = BoardOnboardingAgentComplete | BoardOnboardingAgentQuestion


class BoardOnboardingRead(SQLModel):
    """Stored onboarding session state returned by API endpoints."""

    id: UUID
    board_id: UUID
    session_key: str
    status: str
    messages: list[dict[str, object]] | None = None
    draft_goal: BoardOnboardingAgentComplete | None = None
    created_at: datetime
    updated_at: datetime


class BoardAutomationSyncResultData(SQLModel):
    """Automation sync result data included in bootstrap result."""

    status: Literal["success", "partial_failure", "failed", "not_run"] = "not_run"
    agents_updated: int = 0
    gateway_syncs_succeeded: int = 0
    gateway_syncs_failed: int = 0
    failed_agent_ids: list[UUID] = Field(default_factory=list)


class BoardBootstrapResult(SQLModel):
    """Bootstrap outcome returned after onboarding confirm."""

    lead_status: Literal["created", "updated", "unchanged"] = "unchanged"
    lead_agent_id: UUID | None = None
    team_status: Literal[
        "not_requested", "provisioned", "partial_failure", "failed"
    ] = "not_requested"
    team_agents_created: int = 0
    team_failed_roles: list[str] = Field(default_factory=list)
    planner_status: Literal["not_requested", "started", "failed"] = "not_requested"
    automation_sync: BoardAutomationSyncResultData | None = None


class BoardOnboardingBootstrapResponse(SQLModel):
    """Full response returned after onboarding confirm, including board and bootstrap outcome."""

    board: BoardRead
    bootstrap: BoardBootstrapResult
