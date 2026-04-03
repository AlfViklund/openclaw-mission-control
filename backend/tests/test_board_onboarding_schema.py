# ruff: noqa: INP001, S101
"""Service-level integration tests for the onboarding bootstrap flow.

These tests exercise bootstrap_board_from_onboarding() with mocked
database sessions and gateway services to validate end-to-end orchestration.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.schemas.board_onboarding import (
    BoardAutomationSyncResultData,
    BoardBootstrapResult,
    BoardOnboardingAgentComplete,
    BoardOnboardingAutomationPolicy,
    BoardOnboardingLeadAgentDraft,
    BoardOnboardingPlanningPolicy,
    BoardOnboardingQaPolicy,
    BoardOnboardingTeamPlan,
)
from app.services.agent_provisioning import TeamProvisionResult
from app.services.board_bootstrap import bootstrap_board_from_onboarding
from app.services.board_automation import BoardAutomationSyncResult


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


class TestBootstrapBoardFromOnboardingService:
    """Service-level tests for bootstrap_board_from_onboarding().

    These tests use mocks to exercise the full orchestration path without
    a real database or gateway, covering: lead creation, team provisioning,
    planner bootstrap, automation sync, and bootstrap_summary population.
    """

    def _mock_session(self, existing_lead: Any = None) -> MagicMock:
        """Create a mock AsyncSession with exec/query support."""
        session = MagicMock()
        session.exec = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        result_mock = MagicMock()
        result_mock.first = MagicMock(return_value=existing_lead)
        session.exec.return_value = result_mock
        return session

    def _mock_gateway(self) -> tuple[MagicMock, MagicMock]:
        """Return (gateway, gateway_config) pair."""
        gateway = MagicMock()
        gateway.id = uuid4()
        gateway.name = "test-gateway"
        gateway_config = MagicMock()
        gateway_config.api_key = "test-key"
        return gateway, gateway_config

    def _mock_board(
        self,
        automation_config: dict[str, Any] | None = None,
    ) -> MagicMock:
        """Create a mock Board."""
        board = MagicMock()
        board.id = uuid4()
        board.name = "Test Board"
        board.automation_config = automation_config
        board.require_approval_for_done = False
        return board

    def _mock_agent(self, name: str = "Test Lead", is_lead: bool = True) -> MagicMock:
        agent = MagicMock()
        agent.id = uuid4()
        agent.name = name
        agent.is_board_lead = is_lead
        return agent

    @pytest.mark.asyncio
    async def test_lead_only_path(self) -> None:
        """Lead-only provision mode: lead created, team not_requested."""
        board = self._mock_board()
        draft = BoardOnboardingAgentComplete(
            status="complete",
            board_type="goal",
            objective="Build something",
            success_metrics={"metric": "done"},
            lead_agent=BoardOnboardingLeadAgentDraft(name="Ava"),
            team_plan=BoardOnboardingTeamPlan(provision_mode="lead_only"),
        )
        session = self._mock_session(existing_lead=None)
        gateway, gateway_config = self._mock_gateway()
        mock_lead_agent = self._mock_agent("Ava")

        with (
            patch("app.services.board_bootstrap.GatewayDispatchService") as mock_gw_cls,
            patch(
                "app.services.board_bootstrap.OpenClawProvisioningService"
            ) as mock_prov_cls,
            patch(
                "app.services.board_bootstrap.sync_board_automation_policy",
                new_callable=AsyncMock,
            ) as mock_sync,
            patch(
                "app.services.openclaw.provisioning_db.AgentLifecycleOrchestrator"
            ) as mock_orch_cls,
        ):
            mock_gw_svc = MagicMock()
            mock_gw_svc.require_gateway_config_for_board = AsyncMock(
                return_value=(gateway, gateway_config)
            )
            mock_gw_cls.return_value = mock_gw_svc

            mock_prov = MagicMock()
            mock_prov.ensure_board_lead_agent = AsyncMock(
                return_value=(mock_lead_agent, True)
            )
            mock_prov_cls.return_value = mock_prov

            mock_orch = MagicMock()
            mock_orch.run_lifecycle = AsyncMock(
                return_value=MagicMock(id=mock_lead_agent.id)
            )
            mock_orch_cls.return_value = mock_orch

            mock_sync.return_value = BoardAutomationSyncResult(
                status="not_run",
                agents_updated=0,
                gateway_syncs_succeeded=0,
                gateway_syncs_failed=0,
                failed_agent_ids=[],
            )

            result = await bootstrap_board_from_onboarding(session, board, draft, None)

            assert result.lead_status == "created"
            assert result.lead_agent_id == mock_lead_agent.id
            assert result.lead_name == "Ava"
            assert result.team_status == "not_requested"
            assert result.planner_status == "not_requested"
            assert result.automation_sync is not None
            assert result.bootstrap_summary is not None
            assert "Ava" in result.bootstrap_summary

    @pytest.mark.asyncio
    async def test_full_team_provisioned_path(self) -> None:
        """Full team provision: lead created, team provisioned, planner queued."""
        board = self._mock_board(automation_config={"online_every_seconds": 300})
        draft = BoardOnboardingAgentComplete(
            status="complete",
            board_type="goal",
            objective="Build something",
            success_metrics={"metric": "done"},
            lead_agent=BoardOnboardingLeadAgentDraft(name="Nova"),
            team_plan=BoardOnboardingTeamPlan(
                provision_mode="full_team",
                roles=["developer", "qa_engineer"],
            ),
            planning_policy=BoardOnboardingPlanningPolicy(
                generate_initial_backlog=True,
                bootstrap_after_confirm=True,
            ),
            automation_policy=BoardOnboardingAutomationPolicy(
                automation_profile="normal",
            ),
        )
        session = self._mock_session(existing_lead=None)
        gateway, gateway_config = self._mock_gateway()
        mock_lead_agent = self._mock_agent("Nova")
        mock_team_result = TeamProvisionResult(
            created=2,
            created_roles=["developer", "qa_engineer"],
            skipped_roles=["technical_writer"],
            errors=[],
            agents=[],
        )
        mock_sync_result = BoardAutomationSyncResult(
            status="success",
            agents_updated=3,
            gateway_syncs_succeeded=3,
            gateway_syncs_failed=0,
            failed_agent_ids=[],
        )

        with (
            patch("app.services.board_bootstrap.GatewayDispatchService") as mock_gw_cls,
            patch(
                "app.services.board_bootstrap.OpenClawProvisioningService"
            ) as mock_prov_cls,
            patch(
                "app.services.board_bootstrap.AgentProvisioningService"
            ) as mock_agent_prov_cls,
            patch(
                "app.services.board_bootstrap.sync_board_automation_policy",
                new_callable=AsyncMock,
            ) as mock_sync,
            patch(
                "app.services.openclaw.provisioning_db.AgentLifecycleOrchestrator"
            ) as mock_orch_cls,
        ):
            mock_gw_svc = MagicMock()
            mock_gw_svc.require_gateway_config_for_board = AsyncMock(
                return_value=(gateway, gateway_config)
            )
            mock_gw_cls.return_value = mock_gw_svc

            mock_prov = MagicMock()
            mock_prov.ensure_board_lead_agent = AsyncMock(
                return_value=(mock_lead_agent, True)
            )
            mock_prov_cls.return_value = mock_prov

            mock_orch = MagicMock()
            mock_orch.run_lifecycle = AsyncMock(
                return_value=MagicMock(id=mock_lead_agent.id)
            )
            mock_orch_cls.return_value = mock_orch

            mock_agent_prov = MagicMock()
            mock_agent_prov.provision_full_team = AsyncMock(
                return_value=mock_team_result
            )
            mock_agent_prov_cls.return_value = mock_agent_prov

            mock_sync.return_value = mock_sync_result

            result = await bootstrap_board_from_onboarding(session, board, draft, None)

            assert result.lead_status == "created"
            assert result.lead_name == "Nova"
            assert result.team_status == "provisioned"
            assert result.team_agents_created == 2
            assert "developer" in result.team_created_roles
            assert "qa_engineer" in result.team_created_roles
            assert result.planner_status == "draft_created"
            assert result.planner_output_id is not None
            assert result.automation_sync is not None
            assert result.automation_sync.status == "success"
            assert result.automation_sync.agents_updated == 3
            assert result.bootstrap_summary is not None
            assert "provisioned" in result.bootstrap_summary.lower()
            assert "Planner draft created" in result.bootstrap_summary

    @pytest.mark.asyncio
    async def test_partial_failure_path(self) -> None:
        """Team provision with some role failures → partial_failure status."""
        board = self._mock_board()
        draft = BoardOnboardingAgentComplete(
            status="complete",
            board_type="goal",
            objective="Build something",
            success_metrics={"metric": "done"},
            team_plan=BoardOnboardingTeamPlan(
                provision_mode="full_team",
                roles=["developer", "qa_engineer", "ops_guardian"],
            ),
        )
        session = self._mock_session(existing_lead=None)
        gateway, gateway_config = self._mock_gateway()
        mock_lead_agent = self._mock_agent("Lead")
        mock_team_result = TeamProvisionResult(
            created=2,
            created_roles=["developer", "qa_engineer"],
            skipped_roles=[],
            errors=[{"role": "ops_guardian", "error": "Gateway timeout"}],
            agents=[],
        )

        with (
            patch("app.services.board_bootstrap.GatewayDispatchService") as mock_gw_cls,
            patch(
                "app.services.board_bootstrap.OpenClawProvisioningService"
            ) as mock_prov_cls,
            patch(
                "app.services.board_bootstrap.AgentProvisioningService"
            ) as mock_agent_prov_cls,
            patch(
                "app.services.board_bootstrap.sync_board_automation_policy",
                new_callable=AsyncMock,
            ) as mock_sync,
            patch(
                "app.services.openclaw.provisioning_db.AgentLifecycleOrchestrator"
            ) as mock_orch_cls,
        ):
            mock_gw_svc = MagicMock()
            mock_gw_svc.require_gateway_config_for_board = AsyncMock(
                return_value=(gateway, gateway_config)
            )
            mock_gw_cls.return_value = mock_gw_svc

            mock_prov = MagicMock()
            mock_prov.ensure_board_lead_agent = AsyncMock(
                return_value=(mock_lead_agent, True)
            )
            mock_prov_cls.return_value = mock_prov

            mock_orch = MagicMock()
            mock_orch.run_lifecycle = AsyncMock(
                return_value=MagicMock(id=mock_lead_agent.id)
            )
            mock_orch_cls.return_value = mock_orch

            mock_agent_prov = MagicMock()
            mock_agent_prov.provision_full_team = AsyncMock(
                return_value=mock_team_result
            )
            mock_agent_prov_cls.return_value = mock_agent_prov

            mock_sync.return_value = BoardAutomationSyncResult(
                status="not_run",
                agents_updated=0,
                gateway_syncs_succeeded=0,
                gateway_syncs_failed=0,
                failed_agent_ids=[],
            )

            result = await bootstrap_board_from_onboarding(session, board, draft, None)

            assert result.team_status == "partial_failure"
            assert result.team_agents_created == 2
            assert "ops_guardian" in result.team_failed_roles
            assert result.bootstrap_summary is not None
            assert "partial" in result.bootstrap_summary.lower()

    @pytest.mark.asyncio
    async def test_already_provisioned_path(self) -> None:
        """Team already exists → already_provisioned status."""
        board = self._mock_board()
        draft = BoardOnboardingAgentComplete(
            status="complete",
            board_type="goal",
            objective="Build something",
            success_metrics={"metric": "done"},
            team_plan=BoardOnboardingTeamPlan(
                provision_mode="full_team",
                roles=["developer", "qa_engineer"],
            ),
        )
        session = self._mock_session(existing_lead=None)
        gateway, gateway_config = self._mock_gateway()
        mock_lead_agent = self._mock_agent("Lead")
        mock_team_result = TeamProvisionResult(
            created=0,
            created_roles=[],
            skipped_roles=["developer", "qa_engineer"],
            errors=[],
            agents=[],
        )

        with (
            patch("app.services.board_bootstrap.GatewayDispatchService") as mock_gw_cls,
            patch(
                "app.services.board_bootstrap.OpenClawProvisioningService"
            ) as mock_prov_cls,
            patch(
                "app.services.board_bootstrap.AgentProvisioningService"
            ) as mock_agent_prov_cls,
            patch(
                "app.services.board_bootstrap.sync_board_automation_policy",
                new_callable=AsyncMock,
            ) as mock_sync,
            patch(
                "app.services.openclaw.provisioning_db.AgentLifecycleOrchestrator"
            ) as mock_orch_cls,
        ):
            mock_gw_svc = MagicMock()
            mock_gw_svc.require_gateway_config_for_board = AsyncMock(
                return_value=(gateway, gateway_config)
            )
            mock_gw_cls.return_value = mock_gw_svc

            mock_prov = MagicMock()
            mock_prov.ensure_board_lead_agent = AsyncMock(
                return_value=(mock_lead_agent, True)
            )
            mock_prov_cls.return_value = mock_prov

            mock_orch = MagicMock()
            mock_orch.run_lifecycle = AsyncMock(
                return_value=MagicMock(id=mock_lead_agent.id)
            )
            mock_orch_cls.return_value = mock_orch

            mock_agent_prov = MagicMock()
            mock_agent_prov.provision_full_team = AsyncMock(
                return_value=mock_team_result
            )
            mock_agent_prov_cls.return_value = mock_agent_prov

            mock_sync.return_value = BoardAutomationSyncResult(
                status="not_run",
                agents_updated=0,
                gateway_syncs_succeeded=0,
                gateway_syncs_failed=0,
                failed_agent_ids=[],
            )

            result = await bootstrap_board_from_onboarding(session, board, draft, None)

            assert result.team_status == "already_provisioned"
            assert result.team_agents_created == 0
            assert result.bootstrap_summary is not None
            assert "already provisioned" in result.bootstrap_summary.lower()

    @pytest.mark.asyncio
    async def test_existing_lead_updated(self) -> None:
        """Existing lead → lead_status = updated, not created."""
        board = self._mock_board()
        existing_lead = self._mock_agent("Old Name")
        draft = BoardOnboardingAgentComplete(
            status="complete",
            board_type="goal",
            objective="Build something",
            success_metrics={"metric": "done"},
            lead_agent=BoardOnboardingLeadAgentDraft(name="New Name"),
            team_plan=BoardOnboardingTeamPlan(provision_mode="lead_only"),
        )
        session = self._mock_session(existing_lead=existing_lead)
        gateway, gateway_config = self._mock_gateway()
        updated_lead = self._mock_agent("New Name")
        updated_lead.id = existing_lead.id

        with (
            patch("app.services.board_bootstrap.GatewayDispatchService") as mock_gw_cls,
            patch(
                "app.services.board_bootstrap.OpenClawProvisioningService"
            ) as mock_prov_cls,
            patch(
                "app.services.board_bootstrap.sync_board_automation_policy",
                new_callable=AsyncMock,
            ) as mock_sync,
            patch(
                "app.services.openclaw.provisioning_db.AgentLifecycleOrchestrator"
            ) as mock_orch_cls,
        ):
            mock_gw_svc = MagicMock()
            mock_gw_svc.require_gateway_config_for_board = AsyncMock(
                return_value=(gateway, gateway_config)
            )
            mock_gw_cls.return_value = mock_gw_svc

            mock_prov = MagicMock()
            mock_prov.ensure_board_lead_agent = AsyncMock(
                return_value=(updated_lead, False)
            )
            mock_prov_cls.return_value = mock_prov

            mock_orch = MagicMock()
            mock_orch.run_lifecycle = AsyncMock(
                return_value=MagicMock(id=updated_lead.id)
            )
            mock_orch_cls.return_value = mock_orch

            mock_sync.return_value = BoardAutomationSyncResult(
                status="not_run",
                agents_updated=0,
                gateway_syncs_succeeded=0,
                gateway_syncs_failed=0,
                failed_agent_ids=[],
            )

            result = await bootstrap_board_from_onboarding(session, board, draft, None)

            assert result.lead_status == "updated"
            assert result.lead_agent_id == updated_lead.id
            assert result.lead_name == "New Name"

    @pytest.mark.asyncio
    async def test_no_gateway_means_lead_not_created(self) -> None:
        """Without gateway, lead is not created/provisioned."""
        board = self._mock_board()
        draft = BoardOnboardingAgentComplete(
            status="complete",
            board_type="goal",
            objective="Build something",
            success_metrics={"metric": "done"},
            lead_agent=BoardOnboardingLeadAgentDraft(name="Orphan"),
            team_plan=BoardOnboardingTeamPlan(provision_mode="lead_only"),
        )
        session = self._mock_session(existing_lead=None)

        with (
            patch("app.services.board_bootstrap.GatewayDispatchService") as mock_gw_cls,
            patch(
                "app.services.board_bootstrap.sync_board_automation_policy",
                new_callable=AsyncMock,
            ) as mock_sync,
        ):
            mock_gw_svc = MagicMock()
            mock_gw_svc.require_gateway_config_for_board = AsyncMock(
                side_effect=Exception("No gateway configured")
            )
            mock_gw_cls.return_value = mock_gw_svc

            mock_sync.return_value = BoardAutomationSyncResult(
                status="not_run",
                agents_updated=0,
                gateway_syncs_succeeded=0,
                gateway_syncs_failed=0,
                failed_agent_ids=[],
            )

            result = await bootstrap_board_from_onboarding(session, board, draft, None)

            assert result.lead_status == "unchanged"
            assert result.lead_agent_id is None
            assert result.team_status == "not_requested"
            assert result.automation_sync is not None
            assert result.automation_sync.status == "not_run"

    @pytest.mark.asyncio
    async def test_planner_draft_created_when_policy_requests_it(self) -> None:
        """planning_policy.generate_initial_backlog → planner_status = draft_created."""
        board = self._mock_board()
        draft = BoardOnboardingAgentComplete(
            status="complete",
            board_type="goal",
            objective="Build something",
            success_metrics={"metric": "done"},
            planning_policy=BoardOnboardingPlanningPolicy(
                generate_initial_backlog=True,
            ),
        )
        session = self._mock_session()

        with (
            patch("app.services.board_bootstrap.GatewayDispatchService") as mock_gw_cls,
            patch(
                "app.services.board_bootstrap.sync_board_automation_policy",
                new_callable=AsyncMock,
            ) as mock_sync,
        ):
            mock_gw_cls.return_value.require_gateway_config_for_board = AsyncMock(
                side_effect=Exception("no gateway")
            )
            mock_sync.return_value = BoardAutomationSyncResult(
                status="not_run",
                agents_updated=0,
                gateway_syncs_succeeded=0,
                gateway_syncs_failed=0,
                failed_agent_ids=[],
            )

            result = await bootstrap_board_from_onboarding(session, board, draft, None)

            assert result.planner_status == "draft_created"
            assert result.planner_output_id is not None

    @pytest.mark.asyncio
    async def test_planner_not_requested_when_no_policy(self) -> None:
        """No planning_policy → planner_status = not_requested."""
        board = self._mock_board()
        draft = BoardOnboardingAgentComplete(
            status="complete",
            board_type="goal",
            objective="Build something",
            success_metrics={"metric": "done"},
        )
        session = self._mock_session()

        with (
            patch("app.services.board_bootstrap.GatewayDispatchService") as mock_gw_cls,
            patch(
                "app.services.board_bootstrap.sync_board_automation_policy",
                new_callable=AsyncMock,
            ) as mock_sync,
        ):
            mock_gw_cls.return_value.require_gateway_config_for_board = AsyncMock(
                side_effect=Exception("no gateway")
            )
            mock_sync.return_value = BoardAutomationSyncResult(
                status="not_run",
                agents_updated=0,
                gateway_syncs_succeeded=0,
                gateway_syncs_failed=0,
                failed_agent_ids=[],
            )

            result = await bootstrap_board_from_onboarding(session, board, draft, None)

            assert result.planner_status == "not_requested"
            assert result.planner_output_id is None

    @pytest.mark.asyncio
    async def test_automation_sync_success_surfaced(self) -> None:
        """Automation sync success → automation_sync.status = success."""
        board = self._mock_board(automation_config={"online_every_seconds": 300})
        draft = BoardOnboardingAgentComplete(
            status="complete",
            board_type="goal",
            objective="Build something",
            success_metrics={"metric": "done"},
        )
        session = self._mock_session()
        gateway, gateway_config = self._mock_gateway()

        with (
            patch("app.services.board_bootstrap.GatewayDispatchService") as mock_gw_cls,
            patch(
                "app.services.openclaw.provisioning_db.AgentLifecycleOrchestrator"
            ) as mock_orch_cls,
            patch(
                "app.services.board_bootstrap.sync_board_automation_policy",
                new_callable=AsyncMock,
            ) as mock_sync,
        ):
            mock_gw_svc = MagicMock()
            mock_gw_svc.require_gateway_config_for_board = AsyncMock(
                return_value=(gateway, gateway_config)
            )
            mock_gw_cls.return_value = mock_gw_svc

            mock_orch = MagicMock()
            mock_orch.run_lifecycle = AsyncMock(return_value=MagicMock(id=uuid4()))
            mock_orch_cls.return_value = mock_orch

            mock_sync.return_value = BoardAutomationSyncResult(
                status="success",
                agents_updated=5,
                gateway_syncs_succeeded=5,
                gateway_syncs_failed=0,
                failed_agent_ids=[],
            )

            result = await bootstrap_board_from_onboarding(session, board, draft, None)

            assert result.automation_sync is not None
            assert result.automation_sync.status == "success"
            assert result.automation_sync.agents_updated == 5
            assert result.automation_sync.gateway_syncs_succeeded == 5
            assert result.automation_sync.gateway_syncs_failed == 0
            assert result.automation_sync.failed_agent_ids == []

    @pytest.mark.asyncio
    async def test_automation_sync_partial_failure_surfaced(self) -> None:
        """Automation sync partial failure → automation_sync.status = partial_failure."""
        board = self._mock_board(automation_config={"online_every_seconds": 300})
        draft = BoardOnboardingAgentComplete(
            status="complete",
            board_type="goal",
            objective="Build something",
            success_metrics={"metric": "done"},
        )
        session = self._mock_session()
        gateway, gateway_config = self._mock_gateway()
        failed_agent_id = uuid4()

        with (
            patch("app.services.board_bootstrap.GatewayDispatchService") as mock_gw_cls,
            patch(
                "app.services.openclaw.provisioning_db.AgentLifecycleOrchestrator"
            ) as mock_orch_cls,
            patch(
                "app.services.board_bootstrap.sync_board_automation_policy",
                new_callable=AsyncMock,
            ) as mock_sync,
        ):
            mock_gw_svc = MagicMock()
            mock_gw_svc.require_gateway_config_for_board = AsyncMock(
                return_value=(gateway, gateway_config)
            )
            mock_gw_cls.return_value = mock_gw_svc

            mock_orch = MagicMock()
            mock_orch.run_lifecycle = AsyncMock(return_value=MagicMock(id=uuid4()))
            mock_orch_cls.return_value = mock_orch

            mock_sync.return_value = BoardAutomationSyncResult(
                status="partial_failure",
                agents_updated=3,
                gateway_syncs_succeeded=3,
                gateway_syncs_failed=1,
                failed_agent_ids=[failed_agent_id],
            )

            result = await bootstrap_board_from_onboarding(session, board, draft, None)

            assert result.automation_sync is not None
            assert result.automation_sync.status == "partial_failure"
            assert result.automation_sync.gateway_syncs_failed == 1
            assert failed_agent_id in result.automation_sync.failed_agent_ids

    @pytest.mark.asyncio
    async def test_bootstrap_summary_includes_all_components(self) -> None:
        """Bootstrap summary reflects lead, team, planner, and automation."""
        board = self._mock_board(automation_config={"online_every_seconds": 300})
        draft = BoardOnboardingAgentComplete(
            status="complete",
            board_type="goal",
            objective="Build something",
            success_metrics={"metric": "done"},
            lead_agent=BoardOnboardingLeadAgentDraft(name="Ava"),
            team_plan=BoardOnboardingTeamPlan(
                provision_mode="full_team",
                roles=["developer", "qa_engineer"],
            ),
            planning_policy=BoardOnboardingPlanningPolicy(
                generate_initial_backlog=True,
            ),
        )
        session = self._mock_session(existing_lead=None)
        gateway, gateway_config = self._mock_gateway()
        mock_lead_agent = self._mock_agent("Ava")
        mock_team_result = TeamProvisionResult(
            created=2,
            created_roles=["developer", "qa_engineer"],
            skipped_roles=[],
            errors=[],
            agents=[],
        )

        with (
            patch("app.services.board_bootstrap.GatewayDispatchService") as mock_gw_cls,
            patch(
                "app.services.board_bootstrap.OpenClawProvisioningService"
            ) as mock_prov_cls,
            patch(
                "app.services.board_bootstrap.AgentProvisioningService"
            ) as mock_agent_prov_cls,
            patch(
                "app.services.board_bootstrap.sync_board_automation_policy",
                new_callable=AsyncMock,
            ) as mock_sync,
        ):
            mock_gw_svc = MagicMock()
            mock_gw_svc.require_gateway_config_for_board = AsyncMock(
                return_value=(gateway, gateway_config)
            )
            mock_gw_cls.return_value = mock_gw_svc

            mock_prov = MagicMock()
            mock_prov.ensure_board_lead_agent = AsyncMock(
                return_value=(mock_lead_agent, True)
            )
            mock_prov_cls.return_value = mock_prov

            mock_agent_prov = MagicMock()
            mock_agent_prov.provision_full_team = AsyncMock(
                return_value=mock_team_result
            )
            mock_agent_prov_cls.return_value = mock_agent_prov

            mock_sync.return_value = BoardAutomationSyncResult(
                status="success",
                agents_updated=3,
                gateway_syncs_succeeded=3,
                gateway_syncs_failed=0,
                failed_agent_ids=[],
            )

            result = await bootstrap_board_from_onboarding(session, board, draft, None)

            assert result.bootstrap_summary is not None
            assert len(result.bootstrap_summary) > 0
            assert "Ava" in result.bootstrap_summary
            assert "provisioned" in result.bootstrap_summary.lower()
            assert "Planner" in result.bootstrap_summary
            assert "Automation" in result.bootstrap_summary
            assert ";" in result.bootstrap_summary

    @pytest.mark.asyncio
    async def test_qa_strictness_applies_require_approval_for_done(self) -> None:
        """QA strictness sets board.require_approval_for_done correctly."""
        board = self._mock_board()
        draft = BoardOnboardingAgentComplete(
            status="complete",
            board_type="goal",
            objective="Build something",
            success_metrics={"metric": "done"},
            qa_policy=BoardOnboardingQaPolicy(strictness="strict"),
        )
        session = self._mock_session()

        with (
            patch("app.services.board_bootstrap.GatewayDispatchService") as mock_gw_cls,
            patch(
                "app.services.board_bootstrap.sync_board_automation_policy",
                new_callable=AsyncMock,
            ) as mock_sync,
        ):
            mock_gw_cls.return_value.require_gateway_config_for_board = AsyncMock(
                side_effect=Exception("no gateway")
            )
            mock_sync.return_value = BoardAutomationSyncResult(
                status="not_run",
                agents_updated=0,
                gateway_syncs_succeeded=0,
                gateway_syncs_failed=0,
                failed_agent_ids=[],
            )

            result = await bootstrap_board_from_onboarding(session, board, draft, None)

            assert board.require_approval_for_done is True
            assert result.planner_status == "not_requested"
