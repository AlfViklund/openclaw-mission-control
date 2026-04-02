# ruff: noqa: INP001, S101
"""Schema-level integration tests for the onboarding bootstrap flow.

These tests validate the schema layer without hitting the database,
so they can run in any environment without aiosqlite or a running DB.
"""

from __future__ import annotations

import pytest


class TestOnboardingDraftUpdateSchema:
    """Schema validation tests for structured draft updates."""

    def test_draft_update_accepts_project_info(self) -> None:
        """DraftUpdate should accept project_info object."""
        from app.schemas.board_onboarding import BoardOnboardingDraftUpdate

        update = BoardOnboardingDraftUpdate.model_validate(
            {
                "project_info": {
                    "project_mode": "new_product",
                    "project_stage": "codebase_exists",
                    "first_milestone_type": "mvp",
                    "delivery_mode": "balanced",
                    "deadline_mode": "none",
                },
            }
        )
        assert update.project_info is not None
        assert update.project_info.project_mode == "new_product"
        assert update.project_info.project_stage == "codebase_exists"

    def test_draft_update_accepts_full_context(self) -> None:
        """DraftUpdate should accept full context fields."""
        from app.schemas.board_onboarding import BoardOnboardingDraftUpdate

        update = BoardOnboardingDraftUpdate.model_validate(
            {
                "context": {
                    "description": "Build a SaaS product for teams",
                    "existing_artifacts": "README.md, SPEC.md",
                    "constraints": "Must be cloud-native",
                    "special_instructions": "Focus on developer experience",
                    "extra_context": "Initial team is 3 engineers",
                },
            }
        )
        assert update.context is not None
        assert update.context.description == "Build a SaaS product for teams"
        assert update.context.existing_artifacts == "README.md, SPEC.md"
        assert update.context.constraints == "Must be cloud-native"

    def test_draft_update_accepts_team_plan(self) -> None:
        """DraftUpdate should accept team plan with provision_mode."""
        from app.schemas.board_onboarding import BoardOnboardingDraftUpdate

        update = BoardOnboardingDraftUpdate.model_validate(
            {
                "team_plan": {"provision_mode": "full_team"},
            }
        )
        assert update.team_plan is not None
        assert update.team_plan.provision_mode == "full_team"

    def test_draft_update_accepts_planning_policy(self) -> None:
        """DraftUpdate should accept planning_policy with bootstrap_mode."""
        from app.schemas.board_onboarding import BoardOnboardingDraftUpdate

        update = BoardOnboardingDraftUpdate.model_validate(
            {
                "planning_policy": {
                    "bootstrap_mode": "generate_backlog",
                    "planner_mode": "spec_to_backlog",
                },
            }
        )
        assert update.planning_policy is not None
        assert update.planning_policy.bootstrap_mode == "generate_backlog"

    def test_draft_update_accepts_qa_policy(self) -> None:
        """DraftUpdate should accept qa_policy with strictness."""
        from app.schemas.board_onboarding import BoardOnboardingDraftUpdate

        update = BoardOnboardingDraftUpdate.model_validate(
            {
                "qa_policy": {"strictness": "balanced"},
            }
        )
        assert update.qa_policy is not None
        assert update.qa_policy.strictness == "balanced"

    def test_draft_update_accepts_automation_policy(self) -> None:
        """DraftUpdate should accept automation_policy with automation_profile."""
        from app.schemas.board_onboarding import BoardOnboardingDraftUpdate

        update = BoardOnboardingDraftUpdate.model_validate(
            {
                "automation_policy": {"automation_profile": "active"},
            }
        )
        assert update.automation_policy is not None
        assert update.automation_policy.automation_profile == "active"

    def test_draft_update_accepts_lead_agent(self) -> None:
        """DraftUpdate should accept lead_agent with autonomy_level."""
        from app.schemas.board_onboarding import BoardOnboardingDraftUpdate

        update = BoardOnboardingDraftUpdate.model_validate(
            {
                "lead_agent": {
                    "name": "Ava",
                    "autonomy_level": "autonomous",
                    "verbosity": "concise",
                    "output_format": "bullets",
                    "update_cadence": "daily",
                },
            }
        )
        assert update.lead_agent is not None
        assert update.lead_agent.name == "Ava"
        assert update.lead_agent.autonomy_level == "autonomous"


class TestBootstrapResultSchema:
    """Tests for BoardBootstrapResult schema."""

    def test_bootstrap_result_all_planner_statuses(self) -> None:
        """All planner status values should be valid."""
        from app.schemas.board_onboarding import BoardBootstrapResult

        for status in (
            "not_requested",
            "draft_created",
            "queued",
            "started",
            "failed",
        ):
            result = BoardBootstrapResult(planner_status=status)
            assert result.planner_status == status

    def test_bootstrap_result_all_team_statuses(self) -> None:
        """All team status values should be valid."""
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

    def test_bootstrap_result_all_lead_statuses(self) -> None:
        """All lead status values should be valid."""
        from app.schemas.board_onboarding import BoardBootstrapResult

        for status in ("created", "updated", "unchanged"):
            result = BoardBootstrapResult(lead_status=status)
            assert result.lead_status == status

    def test_bootstrap_result_automation_sync(self) -> None:
        """BootstrapResult should include automation_sync with status and agents_updated."""
        from app.schemas.board_onboarding import (
            BoardAutomationSyncResultData,
            BoardBootstrapResult,
        )

        result = BoardBootstrapResult(
            automation_sync=BoardAutomationSyncResultData(
                status="success",
                agents_updated=3,
            ),
        )
        assert result.automation_sync is not None
        assert result.automation_sync.status == "success"
        assert result.automation_sync.agents_updated == 3

    def test_bootstrap_result_bootstrap_summary(self) -> None:
        """BootstrapResult should include bootstrap_summary field."""
        from app.schemas.board_onboarding import BoardBootstrapResult

        result = BoardBootstrapResult(
            bootstrap_summary="Lead created, team provisioned, planner queued",
        )
        assert (
            result.bootstrap_summary == "Lead created, team provisioned, planner queued"
        )
