# ruff: noqa: INP001, S101
"""Tests for the new board onboarding bootstrap flow."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.schemas.board_onboarding import (
    BoardOnboardingAgentComplete,
    BoardOnboardingAutomationPolicy,
    BoardOnboardingLeadAgentDraft,
    BoardOnboardingPlanningPolicy,
    BoardOnboardingQaPolicy,
    BoardOnboardingTeamPlan,
    BoardOnboardingUserProfile,
)
from app.services.agent_presets import AGENT_ROLE_PRESETS
from app.services.board_bootstrap import (
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
