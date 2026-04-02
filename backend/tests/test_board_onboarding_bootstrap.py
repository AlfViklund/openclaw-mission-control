# ruff: noqa: INP001, S101
"""Tests for the new board onboarding bootstrap flow."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.schemas.board_onboarding import (
    AUTOMATION_PROFILE_DEFAULTS,
    QA_STRICTNESS_DEFAULTS,
    BoardOnboardingAgentComplete,
    BoardOnboardingAutomationPolicy,
    BoardOnboardingContext,
    BoardOnboardingDraftUpdate,
    BoardOnboardingLeadAgentDraft,
    BoardOnboardingPlanningPolicy,
    BoardOnboardingProjectInfo,
    BoardOnboardingQaPolicy,
    BoardOnboardingRefineQuestion,
    BoardOnboardingRefineResult,
    BoardOnboardingTeamPlan,
    BoardOnboardingUserProfile,
)
from app.services.agent_presets import AGENT_ROLE_PRESETS
from app.services.board_bootstrap import (
    _apply_qa_strictness,
    _automation_config_from_policy,
    _lead_options_from_draft,
    _require_approval_for_done_from_qa,
)
from app.services.openclaw.provisioning_db import LeadAgentOptions


class TestLeadOptionsFromDraft:
    """Tests for _lead_options_from_draft()."""

    def test_returns_default_options_when_no_draft(self) -> None:
        options = _lead_options_from_draft(None)
        assert options == LeadAgentOptions(action="provision")

    def test_extracts_lead_name_and_identity(self) -> None:
        draft = BoardOnboardingAgentComplete(
            status="complete",
            board_type="goal",
            objective="Build something great",
            success_metrics={"metric": "success", "target": "100%"},
            lead_agent=BoardOnboardingLeadAgentDraft(
                name="Ava",
                identity_profile={
                    "role": "Board Lead",
                    "communication_style": "structured",
                    "emoji": "🎯",
                },
                autonomy_level="balanced",
                verbosity="concise",
                output_format="bullets",
                update_cadence="daily",
            ),
        )
        options = _lead_options_from_draft(draft)
        assert options.agent_name == "Ava"
        assert options.identity_profile is not None
        assert options.identity_profile["role"] == "Board Lead"
        assert options.identity_profile["autonomy_level"] == "balanced"
        assert options.identity_profile["verbosity"] == "concise"
        assert options.identity_profile["output_format"] == "bullets"
        assert options.identity_profile["update_cadence"] == "daily"
        assert options.action == "provision"

    def test_extracts_heartbeat_config_from_automation_policy(self) -> None:
        draft = BoardOnboardingAgentComplete(
            status="complete",
            board_type="goal",
            objective="Test board",
            success_metrics={"metric": "done", "target": "1"},
            lead_agent=BoardOnboardingLeadAgentDraft(name="TestLead"),
            automation_policy=BoardOnboardingAutomationPolicy(
                online_every_seconds=120,
                idle_every_seconds=600,
                dormant_every_seconds=3600,
            ),
        )
        options = _lead_options_from_draft(draft)
        assert options.heartbeat_config is not None
        assert options.heartbeat_config["online_every_seconds"] == 120
        assert options.heartbeat_config["idle_every_seconds"] == 600
        assert options.heartbeat_config["dormant_every_seconds"] == 3600


class TestAutomationConfigFromPolicy:
    """Tests for _automation_config_from_policy()."""

    def test_returns_none_when_policy_is_none(self) -> None:
        assert _automation_config_from_policy(None) is None

    def test_maps_all_fields(self) -> None:
        policy = BoardOnboardingAutomationPolicy(
            online_every_seconds=300,
            idle_every_seconds=1800,
            dormant_every_seconds=21600,
            wake_on_approvals=True,
            wake_on_review_queue=True,
            allow_assist_mode_when_no_tasks=False,
        )
        config = _automation_config_from_policy(policy)
        assert config is not None
        assert config["online_every_seconds"] == 300
        assert config["idle_every_seconds"] == 1800
        assert config["dormant_every_seconds"] == 21600
        assert config["wake_on_approvals"] is True
        assert config["wake_on_review_queue"] is True
        assert config["allow_assist_mode"] is False

    def test_skips_none_values(self) -> None:
        policy = BoardOnboardingAutomationPolicy(
            online_every_seconds=300,
            wake_on_approvals=True,
            allow_assist_mode_when_no_tasks=False,
        )
        config = _automation_config_from_policy(policy)
        assert config is not None
        assert "online_every_seconds" in config
        assert config["online_every_seconds"] == 300
        assert config["wake_on_approvals"] is True


class TestRequireApprovalFromQa:
    """Tests for _require_approval_for_done_from_qa()."""

    def test_defaults_to_true_when_no_policy(self) -> None:
        assert _require_approval_for_done_from_qa(None) is True

    def test_uses_require_approval_for_done_when_set(self) -> None:
        assert (
            _require_approval_for_done_from_qa(
                BoardOnboardingQaPolicy(require_approval_for_done=True)
            )
            is True
        )
        assert (
            _require_approval_for_done_from_qa(
                BoardOnboardingQaPolicy(require_approval_for_done=False)
            )
            is False
        )


class TestAgentCompleteSchemaExtended:
    """Tests that BoardOnboardingAgentComplete accepts all new fields."""

    def test_accepts_team_plan(self) -> None:
        draft = BoardOnboardingAgentComplete(
            status="complete",
            board_type="goal",
            objective="Test",
            success_metrics={"metric": "done", "target": "1"},
            team_plan=BoardOnboardingTeamPlan(
                roles=["board_lead", "developer", "qa_engineer"],
                provision_full_team=True,
                optional_roles=["technical_writer"],
                notes="Full stack team",
            ),
        )
        assert draft.team_plan is not None
        assert draft.team_plan.provision_full_team is True
        assert draft.team_plan.roles == ["board_lead", "developer", "qa_engineer"]
        assert draft.team_plan.optional_roles == ["technical_writer"]

    def test_accepts_planning_policy(self) -> None:
        draft = BoardOnboardingAgentComplete(
            status="complete",
            board_type="goal",
            objective="Test",
            success_metrics={"metric": "done", "target": "1"},
            planning_policy=BoardOnboardingPlanningPolicy(
                generate_initial_backlog=True,
                planner_mode="spec_to_backlog",
                bootstrap_after_confirm=True,
            ),
        )
        assert draft.planning_policy is not None
        assert draft.planning_policy.generate_initial_backlog is True
        assert draft.planning_policy.planner_mode == "spec_to_backlog"

    def test_accepts_qa_policy(self) -> None:
        draft = BoardOnboardingAgentComplete(
            status="complete",
            board_type="goal",
            objective="Test",
            success_metrics={"metric": "done", "target": "1"},
            qa_policy=BoardOnboardingQaPolicy(
                level="standard",
                run_smoke_after_build=True,
                require_approval_for_done=True,
            ),
        )
        assert draft.qa_policy is not None
        assert draft.qa_policy.level == "standard"
        assert draft.qa_policy.require_approval_for_done is True

    def test_accepts_automation_policy(self) -> None:
        draft = BoardOnboardingAgentComplete(
            status="complete",
            board_type="goal",
            objective="Test",
            success_metrics={"metric": "done", "target": "1"},
            automation_policy=BoardOnboardingAutomationPolicy(
                online_every_seconds=300,
                wake_on_approvals=True,
            ),
        )
        assert draft.automation_policy is not None
        assert draft.automation_policy.online_every_seconds == 300

    def test_accepts_full_extended_payload(self) -> None:
        draft = BoardOnboardingAgentComplete(
            status="complete",
            board_type="goal",
            objective="Build a new feature",
            success_metrics={"metric": "PRs merged", "target": "10"},
            user_profile=BoardOnboardingUserProfile(
                preferred_name="Ars",
                pronouns="he/him",
                timezone="GMT+5",
            ),
            lead_agent=BoardOnboardingLeadAgentDraft(
                name="Ava",
                identity_profile={
                    "role": "Board Lead",
                    "emoji": "🎯",
                    "communication_style": "structured",
                },
                autonomy_level="balanced",
                verbosity="concise",
                output_format="bullets",
                update_cadence="daily",
            ),
            team_plan=BoardOnboardingTeamPlan(
                provision_full_team=True,
                roles=["board_lead", "developer"],
            ),
            planning_policy=BoardOnboardingPlanningPolicy(
                generate_initial_backlog=True,
                bootstrap_after_confirm=True,
            ),
            qa_policy=BoardOnboardingQaPolicy(
                level="standard",
                require_approval_for_done=True,
            ),
            automation_policy=BoardOnboardingAutomationPolicy(
                online_every_seconds=300,
                idle_every_seconds=1800,
                wake_on_approvals=True,
            ),
        )
        assert draft.objective == "Build a new feature"
        assert draft.user_profile is not None
        assert draft.user_profile.preferred_name == "Ars"
        assert draft.lead_agent is not None
        assert draft.lead_agent.name == "Ava"
        assert draft.team_plan is not None
        assert draft.team_plan.provision_full_team is True
        assert draft.planning_policy is not None
        assert draft.planning_policy.generate_initial_backlog is True
        assert draft.qa_policy is not None
        assert draft.qa_policy.require_approval_for_done is True
        assert draft.automation_policy is not None
        assert draft.automation_policy.online_every_seconds == 300

    def test_accepts_full_extended_payload_with_all_new_fields(self) -> None:
        draft = BoardOnboardingAgentComplete(
            status="complete",
            board_type="goal",
            objective="Build a new feature",
            success_metrics={"metric": "PRs merged", "target": "10"},
            user_profile=BoardOnboardingUserProfile(
                preferred_name="Ars",
                pronouns="he/him",
                timezone="GMT+5",
            ),
            lead_agent=BoardOnboardingLeadAgentDraft(
                name="Ava",
                identity_profile={
                    "role": "Board Lead",
                    "emoji": "🎯",
                    "communication_style": "structured",
                },
                autonomy_level="balanced",
                verbosity="concise",
                output_format="bullets",
                update_cadence="daily",
            ),
            team_plan=BoardOnboardingTeamPlan(
                provision_full_team=True,
                roles=["board_lead", "developer"],
            ),
            planning_policy=BoardOnboardingPlanningPolicy(
                generate_initial_backlog=True,
                bootstrap_after_confirm=True,
            ),
            qa_policy=BoardOnboardingQaPolicy(
                level="standard",
                require_approval_for_done=True,
            ),
            automation_policy=BoardOnboardingAutomationPolicy(
                online_every_seconds=300,
                idle_every_seconds=1800,
                wake_on_approvals=True,
            ),
        )
        assert draft.objective == "Build a new feature"
        assert draft.user_profile is not None
        assert draft.user_profile.preferred_name == "Ars"
        assert draft.lead_agent is not None
        assert draft.lead_agent.name == "Ava"
        assert draft.team_plan is not None
        assert draft.team_plan.provision_full_team is True
        assert draft.planning_policy is not None
        assert draft.planning_policy.generate_initial_backlog is True
        assert draft.qa_policy is not None
        assert draft.qa_policy.require_approval_for_done is True
        assert draft.automation_policy is not None
        assert draft.automation_policy.online_every_seconds == 300


class TestBoardLeadPresetIntegrity:
    """Tests that the board_lead preset has required fields for bootstrap base."""

    def test_board_lead_preset_has_required_identity_fields(self) -> None:
        preset = AGENT_ROLE_PRESETS["board_lead"]
        identity = preset["identity_profile"]
        assert identity["role"] == "Board Lead"
        assert identity["emoji"] == "🎯"
        assert identity["autonomy_level"] == "high"
        assert identity["update_cadence"] == "5m"

    def test_board_lead_preset_has_heartbeat_config(self) -> None:
        preset = AGENT_ROLE_PRESETS["board_lead"]
        assert "heartbeat_config" in preset
        assert preset["heartbeat_config"]["every"] == "5m"

    def test_board_lead_preset_is_marked_as_board_lead(self) -> None:
        preset = AGENT_ROLE_PRESETS["board_lead"]
        assert preset["is_board_lead"] is True


class TestQaStrictnessDefaults:
    """Tests for QA strictness profile defaults."""

    def test_flexible_maps_to_smoke_and_no_approval(self) -> None:
        defaults = QA_STRICTNESS_DEFAULTS["flexible"]
        assert defaults["level"] == "smoke"
        assert defaults["require_approval_for_done"] is False

    def test_balanced_maps_to_standard_and_approval(self) -> None:
        defaults = QA_STRICTNESS_DEFAULTS["balanced"]
        assert defaults["level"] == "standard"
        assert defaults["require_approval_for_done"] is True

    def test_strict_maps_to_strict_and_approval(self) -> None:
        defaults = QA_STRICTNESS_DEFAULTS["strict"]
        assert defaults["level"] == "strict"
        assert defaults["require_approval_for_done"] is True


class TestAutomationProfileDefaults:
    """Tests for automation profile defaults."""

    def test_economy_has_slow_heartbeat(self) -> None:
        defaults = AUTOMATION_PROFILE_DEFAULTS["economy"]
        assert defaults["online_every_seconds"] == 600
        assert defaults["idle_every_seconds"] == 3600
        assert defaults["dormant_every_seconds"] == 21600

    def test_normal_has_balanced_heartbeat(self) -> None:
        defaults = AUTOMATION_PROFILE_DEFAULTS["normal"]
        assert defaults["online_every_seconds"] == 300
        assert defaults["idle_every_seconds"] == 1800
        assert defaults["dormant_every_seconds"] == 21600

    def test_active_has_fast_heartbeat(self) -> None:
        defaults = AUTOMATION_PROFILE_DEFAULTS["active"]
        assert defaults["online_every_seconds"] == 120
        assert defaults["idle_every_seconds"] == 900
        assert defaults["dormant_every_seconds"] == 10800

    def test_aggressive_has_max_heartbeat(self) -> None:
        defaults = AUTOMATION_PROFILE_DEFAULTS["aggressive"]
        assert defaults["online_every_seconds"] == 60
        assert defaults["idle_every_seconds"] == 600
        assert defaults["dormant_every_seconds"] == 3600


class TestApplyQaStrictness:
    """Tests for _apply_qa_strictness helper."""

    def test_returns_default_policy_when_none(self) -> None:
        result = _apply_qa_strictness(None)
        assert result.strictness is None
        assert result.level is None

    def test_applies_flexible_defaults(self) -> None:
        policy = BoardOnboardingQaPolicy(strictness="flexible")
        result = _apply_qa_strictness(policy)
        assert result.strictness == "flexible"
        assert result.level == "smoke"
        assert result.require_approval_for_done is False

    def test_applies_balanced_defaults(self) -> None:
        policy = BoardOnboardingQaPolicy(strictness="balanced")
        result = _apply_qa_strictness(policy)
        assert result.strictness == "balanced"
        assert result.level == "standard"
        assert result.require_approval_for_done is True

    def test_applies_strict_defaults(self) -> None:
        policy = BoardOnboardingQaPolicy(strictness="strict")
        result = _apply_qa_strictness(policy)
        assert result.strictness == "strict"
        assert result.level == "strict"
        assert result.require_approval_for_done is True

    def test_explicit_values_override_defaults(self) -> None:
        policy = BoardOnboardingQaPolicy(
            strictness="balanced",
            level="smoke",
            require_approval_for_done=False,
        )
        result = _apply_qa_strictness(policy)
        assert result.strictness == "balanced"
        assert result.level == "smoke"
        assert result.require_approval_for_done is False


class TestBoardOnboardingProjectInfo:
    """Tests for BoardOnboardingProjectInfo schema."""

    def test_accepts_valid_project_mode(self) -> None:
        info = BoardOnboardingProjectInfo(project_mode="new_product")
        assert info.project_mode == "new_product"

    def test_accepts_all_project_stages(self) -> None:
        for stage in (
            "idea_only",
            "spec_exists",
            "codebase_exists",
            "active_development",
            "shipped_product",
        ):
            info = BoardOnboardingProjectInfo(project_stage=stage)
            assert info.project_stage == stage

    def test_accepts_all_milestone_types(self) -> None:
        for milestone in (
            "mvp",
            "architecture_plan",
            "key_feature",
            "stabilization",
            "research_prototype",
            "other",
        ):
            info = BoardOnboardingProjectInfo(first_milestone_type=milestone)
            assert info.first_milestone_type == milestone

    def test_accepts_all_delivery_modes(self) -> None:
        for mode in (
            "quality_first",
            "balanced",
            "fast_first_milestone",
            "aggressive_push",
        ):
            info = BoardOnboardingProjectInfo(delivery_mode=mode)
            assert info.delivery_mode == mode

    def test_accepts_all_deadline_modes(self) -> None:
        for mode in ("none", "few_days", "one_two_weeks", "one_month", "custom"):
            info = BoardOnboardingProjectInfo(deadline_mode=mode)
            assert info.deadline_mode == mode


class TestBoardOnboardingDraftUpdate:
    """Tests for BoardOnboardingDraftUpdate schema."""

    def test_accepts_partial_project_info(self) -> None:
        update = BoardOnboardingDraftUpdate.model_validate(
            {
                "project_info": {"project_mode": "new_product"},
            }
        )
        assert update.project_info is not None
        assert update.project_info.project_mode == "new_product"

    def test_accepts_partial_context(self) -> None:
        update = BoardOnboardingDraftUpdate.model_validate(
            {
                "context": {"description": "Test project"},
            }
        )
        assert update.context is not None
        assert update.context.description == "Test project"

    def test_accepts_partial_lead_agent(self) -> None:
        update = BoardOnboardingDraftUpdate.model_validate(
            {
                "lead_agent": {"name": "Ava", "autonomy_level": "balanced"},
            }
        )
        assert update.lead_agent is not None
        assert update.lead_agent.name == "Ava"
        assert update.lead_agent.autonomy_level == "balanced"

    def test_accepts_partial_team_plan(self) -> None:
        update = BoardOnboardingDraftUpdate.model_validate(
            {
                "team_plan": {"provision_mode": "full_team"},
            }
        )
        assert update.team_plan is not None
        assert update.team_plan.provision_mode == "full_team"

    def test_accepts_partial_planning_policy(self) -> None:
        update = BoardOnboardingDraftUpdate.model_validate(
            {
                "planning_policy": {"bootstrap_mode": "generate_backlog"},
            }
        )
        assert update.planning_policy is not None
        assert update.planning_policy.bootstrap_mode == "generate_backlog"

    def test_accepts_partial_qa_policy(self) -> None:
        update = BoardOnboardingDraftUpdate.model_validate(
            {
                "qa_policy": {"strictness": "strict"},
            }
        )
        assert update.qa_policy is not None
        assert update.qa_policy.strictness == "strict"

    def test_accepts_partial_automation_policy(self) -> None:
        update = BoardOnboardingDraftUpdate.model_validate(
            {
                "automation_policy": {"automation_profile": "active"},
            }
        )
        assert update.automation_policy is not None
        assert update.automation_policy.automation_profile == "active"


class TestBoardOnboardingRefineResult:
    """Tests for BoardOnboardingRefineResult schema."""

    def test_accepts_complete_status_with_draft(self) -> None:
        result = BoardOnboardingRefineResult(
            status="complete",
            draft=BoardOnboardingDraftUpdate.model_validate(
                {
                    "project_info": {"project_mode": "new_product"},
                }
            ),
            summary="Looks good",
        )
        assert result.status == "complete"
        assert result.draft is not None
        assert result.draft.project_info is not None
        assert result.summary == "Looks good"

    def test_accepts_questions_status(self) -> None:
        result = BoardOnboardingRefineResult(
            status="questions",
            questions=[
                BoardOnboardingRefineQuestion(
                    id="1",
                    question="What is the main goal?",
                    options=[],
                ),
            ],
        )
        assert result.status == "questions"
        assert len(result.questions) == 1
        assert result.questions[0].question == "What is the main goal?"

    def test_accepts_refining_status(self) -> None:
        result = BoardOnboardingRefineResult(status="refining")
        assert result.status == "refining"


class TestBoardOnboardingTeamPlanProvisionMode:
    """Tests for team plan provision_mode field."""

    def test_accepts_lead_only(self) -> None:
        plan = BoardOnboardingTeamPlan(provision_mode="lead_only")
        assert plan.provision_mode == "lead_only"

    def test_accepts_selected_roles(self) -> None:
        plan = BoardOnboardingTeamPlan(
            provision_mode="selected_roles",
            roles=["developer", "qa_engineer"],
        )
        assert plan.provision_mode == "selected_roles"
        assert plan.roles == ["developer", "qa_engineer"]

    def test_accepts_full_team(self) -> None:
        plan = BoardOnboardingTeamPlan(provision_mode="full_team")
        assert plan.provision_mode == "full_team"


class TestBoardOnboardingPlanningPolicyBootstrapMode:
    """Tests for planning policy bootstrap_mode field."""

    def test_accepts_all_bootstrap_modes(self) -> None:
        for mode in ("generate_backlog", "empty_board", "lead_only", "draft_only"):
            policy = BoardOnboardingPlanningPolicy(bootstrap_mode=mode)
            assert policy.bootstrap_mode == mode


class TestBoardOnboardingAutomationPolicyProfile:
    """Tests for automation policy automation_profile field."""

    def test_accepts_all_profiles(self) -> None:
        for profile in ("economy", "normal", "active", "aggressive"):
            policy = BoardOnboardingAutomationPolicy(automation_profile=profile)
            assert policy.automation_profile == profile


class TestLegacyBackwardCompatibility:
    """Tests that old onboarding payloads still validate and work."""

    def test_board_onboarding_confirm_validates_goal_boards(self) -> None:
        from app.schemas.board_onboarding import BoardOnboardingConfirm

        confirm = BoardOnboardingConfirm(
            board_type="goal",
            objective="Build a great product",
            success_metrics={"metric": "PRs merged"},
        )
        assert confirm.board_type == "goal"
        assert confirm.objective == "Build a great product"

    def test_board_onboarding_confirm_requires_objective_for_goal(self) -> None:
        from app.schemas.board_onboarding import BoardOnboardingConfirm
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            BoardOnboardingConfirm(
                board_type="goal",
                objective="",
                success_metrics={"metric": "PRs merged"},
            )

    def test_board_onboarding_confirm_allows_general_board_without_objective(
        self,
    ) -> None:
        from app.schemas.board_onboarding import BoardOnboardingConfirm

        confirm = BoardOnboardingConfirm(board_type="general")
        assert confirm.board_type == "general"
        assert confirm.objective is None

    def test_lead_options_from_draft_works_with_minimal_draft(self) -> None:
        from app.services.board_bootstrap import _lead_options_from_draft
        from app.schemas.board_onboarding import BoardOnboardingAgentComplete

        draft = BoardOnboardingAgentComplete(
            status="complete",
            board_type="general",
        )
        options = _lead_options_from_draft(draft)
        assert options.agent_name is None
        assert options.heartbeat_config is None

    def test_lead_options_from_draft_with_automation_profile_applies_defaults(
        self,
    ) -> None:
        from app.services.board_bootstrap import _lead_options_from_draft
        from app.schemas.board_onboarding import (
            BoardOnboardingAgentComplete,
            BoardOnboardingAutomationPolicy,
        )

        draft = BoardOnboardingAgentComplete.model_validate(
            {
                "status": "complete",
                "board_type": "general",
            }
        )
        draft.automation_policy = BoardOnboardingAutomationPolicy.model_validate(
            {
                "automation_profile": "active",
            }
        )
        options = _lead_options_from_draft(draft)
        assert options.heartbeat_config is not None
        assert options.heartbeat_config.get("online_every_seconds") == 120
        assert options.heartbeat_config.get("idle_every_seconds") == 900
        assert options.heartbeat_config.get("dormant_every_seconds") == 10800

    def test_lead_options_explicit_overrides_profile_defaults(self) -> None:
        from app.services.board_bootstrap import _lead_options_from_draft
        from app.schemas.board_onboarding import (
            BoardOnboardingAgentComplete,
            BoardOnboardingAutomationPolicy,
        )

        draft = BoardOnboardingAgentComplete.model_validate(
            {
                "status": "complete",
                "board_type": "general",
            }
        )
        draft.automation_policy = BoardOnboardingAutomationPolicy.model_validate(
            {
                "automation_profile": "active",
                "online_every_seconds": 30,
            }
        )
        options = _lead_options_from_draft(draft)
        assert options.heartbeat_config is not None
        assert options.heartbeat_config.get("online_every_seconds") == 30
        assert options.heartbeat_config.get("idle_every_seconds") == 900


class TestConfirmOnboardingMapping:
    """Tests for Phase 1.1: confirm_onboarding must NOT set board.objective to project_mode enum."""

    def test_confirm_onboarding_does_not_map_project_mode_to_objective(self) -> None:
        """board.objective must NOT be set to enum strings like 'new_product'."""
        from app.services.board_bootstrap import _lead_options_from_draft
        from app.schemas.board_onboarding import BoardOnboardingAgentComplete

        draft = BoardOnboardingAgentComplete.model_validate(
            {
                "status": "complete",
                "board_type": "general",
            }
        )

        options = _lead_options_from_draft(draft)
        identity = options.identity_profile or {}

        project_mode_value = identity.get("project_mode")
        assert project_mode_value != "new_product", (
            "identity_profile should not contain raw project_mode enum value"
        )

    def test_confirm_uses_context_description_for_objective(self) -> None:
        """When context.description is available, it should be used for board.objective."""
        from app.schemas.board_onboarding import BoardOnboardingContext

        ctx = BoardOnboardingContext(
            description="Build a modern SaaS platform for team collaboration",
        )
        assert ctx.description == "Build a modern SaaS platform for team collaboration"
        assert ctx.description != "new_product"
        assert ctx.description != "existing_product_evolution"

    def test_objective_never_set_to_enum_project_mode(self) -> None:
        """project_mode enum values must not be human-readable objectives."""
        from app.schemas.board_onboarding import BoardOnboardingProjectInfo

        modes = [
            "new_product",
            "existing_product_evolution",
            "new_feature",
            "stabilization",
            "research_prototype",
        ]
        for mode in modes:
            info = BoardOnboardingProjectInfo(project_mode=mode)
            assert info.project_mode == mode
            assert not _is_human_readable_objective(mode), (
                f"'{mode}' is an enum, not a human-readable objective"
            )

    def test_project_mode_preserved_separately_from_objective(self) -> None:
        """project_mode must be stored as semantic field, not mixed into objective."""
        from app.schemas.board_onboarding import (
            BoardOnboardingAgentComplete,
            BoardOnboardingProjectInfo,
            BoardOnboardingContext,
        )

        draft = BoardOnboardingAgentComplete.model_validate(
            {
                "status": "complete",
                "board_type": "general",
            }
        )
        draft.project_info = BoardOnboardingProjectInfo(
            project_mode="existing_product_evolution"
        )
        draft.context = BoardOnboardingContext(
            description="Improve our payment processing pipeline"
        )
        assert draft.project_info is not None
        assert draft.project_info.project_mode == "existing_product_evolution"
        assert draft.context is not None
        assert draft.context.description == "Improve our payment processing pipeline"


def _is_human_readable_objective(value: str) -> bool:
    """Return True if value looks like a human-written objective description."""
    words = value.lower().split()
    if len(words) <= 2:
        return False
    if value in (
        "new_product",
        "existing_product_evolution",
        "new_feature",
        "stabilization",
        "research_prototype",
    ):
        return False
    return True


class TestUnifiedLead:
    """Tests for Phase 1.3: existing and new lead must converge to same model."""

    def test_existing_lead_rebase_uses_preset_as_base(self) -> None:
        """Existing lead should use board_lead preset as base."""
        from app.services.agent_presets import AGENT_ROLE_PRESETS

        preset = AGENT_ROLE_PRESETS.get("board_lead", {})
        assert "identity_profile" in preset
        assert preset["identity_profile"].get("role") == "Board Lead"
        assert "heartbeat_config" in preset

    def test_new_lead_created_from_board_lead_preset(self) -> None:
        """New lead should be created from board_lead preset."""
        from app.services.agent_presets import AGENT_ROLE_PRESETS

        preset = AGENT_ROLE_PRESETS.get("board_lead", {})
        assert preset.get("is_board_lead") is True
        identity = preset.get("identity_profile", {})
        assert identity.get("role") == "Board Lead"
        assert identity.get("emoji") == "🎯"
        heartbeat = preset.get("heartbeat_config", {})
        assert "every" in heartbeat

    def test_lead_options_from_draft_with_override(self) -> None:
        """lead_options_from_draft should allow overrides on top of preset."""
        from app.services.board_bootstrap import _lead_options_from_draft
        from app.schemas.board_onboarding import (
            BoardOnboardingAgentComplete,
            BoardOnboardingLeadAgentDraft,
        )

        draft = BoardOnboardingAgentComplete.model_validate(
            {
                "status": "complete",
                "board_type": "general",
            }
        )
        draft.lead_agent = BoardOnboardingLeadAgentDraft.model_validate(
            {
                "name": "Ava",
                "autonomy_level": "autonomous",
            }
        )
        options = _lead_options_from_draft(draft)
        assert options.agent_name == "Ava"
        identity = options.identity_profile or {}
        assert identity.get("autonomy_level") == "autonomous"


class TestPlannerBootstrapHonesty:
    """Tests for Phase 1.2: planner status must be honest."""

    def test_planner_status_literal_includes_draft_created(self) -> None:
        """planner_status should include draft_created for honest semantics."""
        from app.schemas.board_onboarding import BoardBootstrapResult

        result = BoardBootstrapResult(planner_status="draft_created")
        assert result.planner_status == "draft_created"

    def test_planner_status_not_requested_when_planning_disabled(self) -> None:
        """When no planning policy, planner_status should be not_requested."""
        from app.schemas.board_onboarding import BoardBootstrapResult

        result = BoardBootstrapResult()
        assert result.planner_status == "not_requested"

    def test_planner_status_accepts_all_valid_statuses(self) -> None:
        """All planner status values should be accepted."""
        from app.schemas.board_onboarding import BoardBootstrapResult

        for status in ("not_requested", "draft_created", "queued", "started", "failed"):
            result = BoardBootstrapResult(planner_status=status)
            assert result.planner_status == status


class TestRefinePrompt:
    """Tests for Phase 2.2: refine prompt must not re-ask structured fields."""

    def test_refine_prompt_does_not_contain_questionnaire_phrases(self) -> None:
        """Refine prompt should not instruct agent to ask structured questions."""
        from app.services.openclaw.onboarding_service import (
            BoardOnboardingMessagingService,
        )
        import inspect

        source = inspect.getsource(BoardOnboardingMessagingService._build_refine_prompt)
        questionnaire_phrases = [
            "what is your project",
            "what are you building",
            "what type of project",
            "what stage is",
            "do you want to create a team",
            "how many people",
        ]
        source_lower = source.lower()
        for phrase in questionnaire_phrases:
            assert phrase.lower() not in source_lower, (
                f"Refine prompt should not contain questionnaire phrase: {phrase}"
            )

    def test_refine_prompt_mentions_draft_already_collected(self) -> None:
        """Refine prompt should indicate the wizard draft was already collected."""
        from app.services.openclaw.onboarding_service import (
            BoardOnboardingMessagingService,
        )
        import inspect

        source = inspect.getsource(BoardOnboardingMessagingService._build_refine_prompt)
        assert (
            "already collected via wizard" in source.lower()
            or "wizard" in source.lower()
        )

    def test_refine_prompt_limits_questions(self) -> None:
        """Refine prompt should limit AI to 1-2 clarifying questions."""
        from app.services.openclaw.onboarding_service import (
            BoardOnboardingMessagingService,
        )
        import inspect

        source = inspect.getsource(BoardOnboardingMessagingService._build_refine_prompt)
        assert "1-2" in source or "1–2" in source or "maximum 1-2" in source.lower()


class TestBackwardCompatibility:
    """Tests for Phase 2.3: legacy payloads must still work."""

    def test_legacy_confirm_payload_with_objective(self) -> None:
        """Legacy payload with board_type=goal and objective should work."""
        from app.schemas.board_onboarding import BoardOnboardingConfirm

        confirm = BoardOnboardingConfirm.model_validate(
            {
                "board_type": "goal",
                "objective": "Build a great product",
                "success_metrics": {"metric": "PRs merged", "target": "10"},
            }
        )
        assert confirm.board_type == "goal"
        assert confirm.objective == "Build a great product"
        assert confirm.success_metrics is not None

    def test_legacy_confirm_payload_general_board(self) -> None:
        """Legacy general board confirm should work without objective."""
        from app.schemas.board_onboarding import BoardOnboardingConfirm

        confirm = BoardOnboardingConfirm.model_validate(
            {
                "board_type": "general",
            }
        )
        assert confirm.board_type == "general"
        assert confirm.objective is None

    def test_legacy_onboarding_payload_without_new_fields(self) -> None:
        """Old payload missing new schema fields should still validate."""
        from app.schemas.board_onboarding import BoardOnboardingAgentComplete

        old_style = {
            "status": "complete",
            "board_type": "goal",
            "objective": "My project",
            "success_metrics": {"metric": "test"},
        }
        complete = BoardOnboardingAgentComplete.model_validate(old_style)
        assert complete.board_type == "goal"
        assert complete.objective == "My project"


class TestTeamStatus:
    """Tests for Phase 1.2: team status must be correct."""

    def test_team_status_literal_values_complete(self) -> None:
        """All expected team status values should be accepted."""
        from app.schemas.board_onboarding import BoardBootstrapResult

        for status in (
            "not_requested",
            "provisioned",
            "already_provisioned",
            "partial_failure",
            "failed",
        ):
            result = BoardBootstrapResult(team_status=status)
            assert result.team_status == status

    def test_team_result_tracks_created_skipped_failed_roles(self) -> None:
        """BoardBootstrapResult should track created/skipped/failed roles."""
        from app.schemas.board_onboarding import BoardBootstrapResult

        result = BoardBootstrapResult(
            team_status="provisioned",
            team_agents_created=2,
            team_created_roles=["developer", "qa_engineer"],
            team_skipped_roles=["technical_writer"],
            team_failed_roles=["ops_guardian"],
        )
        assert result.team_agents_created == 2
        assert "developer" in result.team_created_roles
        assert "technical_writer" in result.team_skipped_roles
        assert "ops_guardian" in result.team_failed_roles


class TestBootstrapSummary:
    """Tests for Phase A5: bootstrap_summary must be populated."""

    def test_bootstrap_summary_is_human_readable(self) -> None:
        """bootstrap_summary should be a non-empty human-readable string."""
        from app.services.board_bootstrap import _build_bootstrap_summary
        from app.schemas.board_onboarding import BoardBootstrapResult

        result = BoardBootstrapResult(
            lead_status="created",
            lead_name="Ava",
            team_status="provisioned",
            team_agents_created=3,
            team_created_roles=["developer", "qa_engineer", "technical_writer"],
            team_skipped_roles=[],
            planner_status="draft_created",
            bootstrap_summary=None,
        )
        summary = _build_bootstrap_summary(result)
        assert isinstance(summary, str)
        assert len(summary) > 0
        assert "Ava" in summary
        assert "provisioned" in summary.lower()

    def test_bootstrap_summary_reflects_partial_failure(self) -> None:
        """Partial failure should be reflected in the summary."""
        from app.services.board_bootstrap import _build_bootstrap_summary
        from app.schemas.board_onboarding import BoardBootstrapResult

        result = BoardBootstrapResult(
            lead_status="unchanged",
            team_status="partial_failure",
            team_agents_created=1,
            team_created_roles=["developer"],
            team_skipped_roles=["qa_engineer"],
            team_failed_roles=["ops_guardian"],
            planner_status="not_requested",
        )
        summary = _build_bootstrap_summary(result)
        assert "partial" in summary.lower()
        assert "developer" in summary
        assert "ops_guardian" in summary

    def test_bootstrap_summary_not_requested_cases(self) -> None:
        """Summary should handle not_requested cases gracefully."""
        from app.services.board_bootstrap import _build_bootstrap_summary
        from app.schemas.board_onboarding import BoardBootstrapResult

        result = BoardBootstrapResult(
            lead_status="created",
            lead_name="Nova",
            team_status="not_requested",
            planner_status="not_requested",
        )
        summary = _build_bootstrap_summary(result)
        assert isinstance(summary, str)
        assert len(summary) > 0


class TestOnboardingProvisionOrder:
    """Tests for Phase A2: lead must be identical regardless of onboarding/provision order."""

    def test_lead_options_identical_for_same_draft(self) -> None:
        """_lead_options_from_draft must produce identical options for the same draft."""
        from app.services.board_bootstrap import _lead_options_from_draft
        from app.schemas.board_onboarding import BoardOnboardingAgentComplete

        draft = BoardOnboardingAgentComplete.model_validate(
            {
                "status": "complete",
                "board_type": "goal",
                "objective": "Build a great product",
                "success_metrics": {"metric": "PRs merged", "target": "10"},
                "lead_agent": {
                    "name": "Ava",
                    "autonomy_level": "autonomous",
                    "verbosity": "concise",
                    "output_format": "bullets",
                    "update_cadence": "daily",
                },
                "automation_policy": {
                    "automation_profile": "active",
                },
            }
        )

        options_a = _lead_options_from_draft(draft)
        options_b = _lead_options_from_draft(draft)

        assert options_a.agent_name == options_b.agent_name
        hb_a = options_a.heartbeat_config
        hb_b = options_b.heartbeat_config
        assert hb_a is not None and hb_b is not None
        assert hb_a.get("online_interval_seconds") == hb_b.get(
            "online_interval_seconds"
        )
        id_a = options_a.identity_profile
        id_b = options_b.identity_profile
        assert id_a is not None and id_b is not None
        assert id_a.get("verbosity") == id_b.get("verbosity")
