"""Tests for AgentProvisioningService with gateway lifecycle integration."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.services.agent_provisioning import (
    AgentProvisioningService,
    TeamProvisionResult,
)
from app.services.agent_presets import AGENT_ROLE_PRESETS


def _make_gateway() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        name="test-gateway",
        url="ws://gateway.example/ws",
        token="gw-token",
        workspace_root="/tmp/openclaw",
        allow_insecure_tls=False,
        disable_device_pairing=False,
        organization_id=uuid4(),
    )


def _make_board(gateway_id: UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        name="test-board",
        gateway_id=gateway_id or uuid4(),
    )


def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


class TestCreateAgentWithPreset:
    """Tests for create_agent_with_preset() with full gateway lifecycle."""

    @pytest.mark.asyncio
    async def test_raises_on_unknown_preset(self) -> None:
        session = _make_session()
        service = AgentProvisioningService(session)

        with pytest.raises(ValueError, match="Unknown preset"):
            await service.create_agent_with_preset(
                name="test",
                preset="nonexistent",
                board_id=uuid4(),
                gateway_id=uuid4(),
            )

    @pytest.mark.asyncio
    async def test_raises_on_missing_gateway(self) -> None:
        session = _make_session()
        service = AgentProvisioningService(session)

        with patch.object(
            service, "_require_gateway", AsyncMock(side_effect=ValueError("Gateway not found"))
        ):
            with pytest.raises(ValueError, match="Gateway not found"):
                await service.create_agent_with_preset(
                    name="test",
                    preset="developer",
                    board_id=uuid4(),
                    gateway_id=uuid4(),
                )

    @pytest.mark.asyncio
    async def test_raises_on_missing_board(self) -> None:
        session = _make_session()
        gateway = _make_gateway()
        service = AgentProvisioningService(session)

        with (
            patch.object(service, "_require_gateway", AsyncMock(return_value=gateway)),
            patch.object(
                service, "_require_board", AsyncMock(side_effect=ValueError("Board not found"))
            ),
        ):
            with pytest.raises(ValueError, match="Board not found"):
                await service.create_agent_with_preset(
                    name="test",
                    preset="developer",
                    board_id=uuid4(),
                    gateway_id=gateway.id,
                )

    @pytest.mark.asyncio
    async def test_calls_lifecycle_orchestrator(self) -> None:
        session = _make_session()
        gateway = _make_gateway()
        board = _make_board(gateway.id)

        created_agent = SimpleNamespace(
            id=uuid4(),
            name="test-agent",
            board_id=board.id,
            gateway_id=gateway.id,
            identity_profile={"role": "Developer"},
            heartbeat_config={"every": "10m"},
            is_board_lead=False,
            status="provisioning",
        )

        lifecycle_agent = SimpleNamespace(
            id=created_agent.id,
            name="test-agent",
            board_id=board.id,
            gateway_id=gateway.id,
            identity_profile={"role": "Developer"},
            heartbeat_config={"every": "10m"},
            is_board_lead=False,
            status="online",
            lifecycle_generation=1,
            last_provision_error=None,
        )

        mock_lifecycle = AsyncMock(return_value=lifecycle_agent)
        mock_orch = MagicMock()
        mock_orch.return_value.run_lifecycle = mock_lifecycle

        service = AgentProvisioningService(session)

        with (
            patch.object(service, "_require_gateway", AsyncMock(return_value=gateway)),
            patch.object(service, "_require_board", AsyncMock(return_value=board)),
            patch.object(service, "_resolve_template_user", AsyncMock(return_value=None)),
            patch(
                "app.services.agent_provisioning.AgentLifecycleOrchestrator",
                mock_orch,
            ),
        ):
            result = await service.create_agent_with_preset(
                name="test-agent",
                preset="developer",
                board_id=board.id,
                gateway_id=gateway.id,
            )

        assert mock_lifecycle.call_count == 1
        call_kwargs = mock_lifecycle.call_args.kwargs
        assert call_kwargs["gateway"] == gateway
        assert call_kwargs["board"] == board
        assert call_kwargs["action"] == "provision"
        assert call_kwargs["wake"] is True
        assert call_kwargs["deliver_wakeup"] is True
        assert call_kwargs["raise_gateway_errors"] is True

    @pytest.mark.asyncio
    async def test_mints_token_before_lifecycle(self) -> None:
        session = _make_session()
        gateway = _make_gateway()
        board = _make_board(gateway.id)

        created_agent = SimpleNamespace(
            id=uuid4(),
            name="test-agent",
            board_id=board.id,
            gateway_id=gateway.id,
            identity_profile={"role": "Developer"},
            heartbeat_config={"every": "10m"},
            is_board_lead=False,
            status="provisioning",
        )

        lifecycle_agent = SimpleNamespace(
            id=created_agent.id,
            name="test-agent",
            board_id=board.id,
            gateway_id=gateway.id,
            identity_profile={"role": "Developer"},
            heartbeat_config={"every": "10m"},
            is_board_lead=False,
            status="online",
            lifecycle_generation=1,
            last_provision_error=None,
        )

        mock_lifecycle = AsyncMock(return_value=lifecycle_agent)
        mock_orch = MagicMock()
        mock_orch.return_value.run_lifecycle = mock_lifecycle

        service = AgentProvisioningService(session)

        with (
            patch.object(service, "_require_gateway", AsyncMock(return_value=gateway)),
            patch.object(service, "_require_board", AsyncMock(return_value=board)),
            patch.object(service, "_resolve_template_user", AsyncMock(return_value=None)),
            patch(
                "app.services.agent_provisioning.AgentLifecycleOrchestrator",
                mock_orch,
            ),
            patch(
                "app.services.agent_provisioning.mint_agent_token",
                return_value="test-token-123",
            ) as mock_mint,
        ):
            await service.create_agent_with_preset(
                name="test-agent",
                preset="developer",
                board_id=board.id,
                gateway_id=gateway.id,
            )

        assert mock_mint.call_count == 1
        assert mock_lifecycle.call_args.kwargs["auth_token"] == "test-token-123"


class TestProvisionFullTeam:
    """Tests for provision_full_team() with gateway lifecycle per agent."""

    @pytest.mark.asyncio
    async def test_returns_team_provision_result(self) -> None:
        session = _make_session()
        gateway = _make_gateway()
        board = _make_board(gateway.id)

        lifecycle_agent = SimpleNamespace(
            id=uuid4(),
            name="test",
            board_id=board.id,
            gateway_id=gateway.id,
            identity_profile={"role": "Developer"},
            heartbeat_config={"every": "10m"},
            is_board_lead=False,
            status="online",
            lifecycle_generation=1,
            last_provision_error=None,
        )

        mock_lifecycle = AsyncMock(return_value=lifecycle_agent)
        mock_orch = MagicMock()
        mock_orch.return_value.run_lifecycle = mock_lifecycle

        service = AgentProvisioningService(session)

        with (
            patch.object(service, "_require_gateway", AsyncMock(return_value=gateway)),
            patch.object(service, "_require_board", AsyncMock(return_value=board)),
            patch.object(service, "_resolve_template_user", AsyncMock(return_value=None)),
            patch(
                "app.services.agent_provisioning.AgentLifecycleOrchestrator",
                mock_orch,
            ),
            patch(
                "app.models.agents.Agent.objects",
                new_callable=lambda: SimpleNamespace(
                    filter_by=lambda **_kw: SimpleNamespace(
                        all=AsyncMock(return_value=[])
                    )
                ),
            ),
        ):
            result = await service.provision_full_team(
                board_id=board.id,
                gateway_id=gateway.id,
                roles=["developer"],
            )

        assert isinstance(result, TeamProvisionResult)
        assert result.created >= 0
        assert isinstance(result.agents, list)
        assert isinstance(result.errors, list)

    @pytest.mark.asyncio
    async def test_collects_errors_on_failure(self) -> None:
        session = _make_session()
        gateway = _make_gateway()
        board = _make_board(gateway.id)

        mock_lifecycle = AsyncMock(side_effect=RuntimeError("gateway unreachable"))
        mock_orch = MagicMock()
        mock_orch.return_value.run_lifecycle = mock_lifecycle

        service = AgentProvisioningService(session)

        with (
            patch.object(service, "_require_gateway", AsyncMock(return_value=gateway)),
            patch.object(service, "_require_board", AsyncMock(return_value=board)),
            patch.object(service, "_resolve_template_user", AsyncMock(return_value=None)),
            patch(
                "app.services.agent_provisioning.AgentLifecycleOrchestrator",
                mock_orch,
            ),
            patch(
                "app.models.agents.Agent.objects",
                new_callable=lambda: SimpleNamespace(
                    filter_by=lambda **_kw: SimpleNamespace(
                        all=AsyncMock(return_value=[])
                    )
                ),
            ),
        ):
            result = await service.provision_full_team(
                board_id=board.id,
                gateway_id=gateway.id,
                roles=["developer"],
            )

        assert result.created == 0
        assert len(result.errors) == 1
        assert "gateway unreachable" in result.errors[0]["error"]
        assert result.errors[0]["role"] == "developer"

    @pytest.mark.asyncio
    async def test_skips_existing_roles(self) -> None:
        session = _make_session()
        gateway = _make_gateway()
        board = _make_board(gateway.id)

        existing_agent = SimpleNamespace(
            id=uuid4(),
            identity_profile={"role": "Developer"},
        )

        service = AgentProvisioningService(session)

        with (
            patch.object(service, "_require_gateway", AsyncMock(return_value=gateway)),
            patch.object(service, "_require_board", AsyncMock(return_value=board)),
            patch.object(service, "_resolve_template_user", AsyncMock(return_value=None)),
            patch(
                "app.models.agents.Agent.objects",
                new_callable=lambda: SimpleNamespace(
                    filter_by=lambda **_kw: SimpleNamespace(
                        all=AsyncMock(return_value=[existing_agent])
                    )
                ),
            ),
        ):
            result = await service.provision_full_team(
                board_id=board.id,
                gateway_id=gateway.id,
                roles=["developer"],
            )

        assert result.created == 0
        assert len(result.agents) == 0
        assert len(result.errors) == 0

    @pytest.mark.asyncio
    async def test_continues_on_partial_failure(self) -> None:
        session = _make_session()
        gateway = _make_gateway()
        board = _make_board(gateway.id)

        lifecycle_agent = SimpleNamespace(
            id=uuid4(),
            name="test",
            board_id=board.id,
            gateway_id=gateway.id,
            identity_profile={"role": "QA Engineer"},
            heartbeat_config={"every": "10m"},
            is_board_lead=False,
            status="online",
            lifecycle_generation=1,
            last_provision_error=None,
        )

        call_count = 0

        async def flaky_lifecycle(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("first agent fails")
            return lifecycle_agent

        mock_orch = MagicMock()
        mock_orch.return_value.run_lifecycle = flaky_lifecycle

        service = AgentProvisioningService(session)

        with (
            patch.object(service, "_require_gateway", AsyncMock(return_value=gateway)),
            patch.object(service, "_require_board", AsyncMock(return_value=board)),
            patch.object(service, "_resolve_template_user", AsyncMock(return_value=None)),
            patch(
                "app.services.agent_provisioning.AgentLifecycleOrchestrator",
                mock_orch,
            ),
            patch(
                "app.models.agents.Agent.objects",
                new_callable=lambda: SimpleNamespace(
                    filter_by=lambda **_kw: SimpleNamespace(
                        all=AsyncMock(return_value=[])
                    )
                ),
            ),
        ):
            result = await service.provision_full_team(
                board_id=board.id,
                gateway_id=gateway.id,
                roles=["developer", "qa_engineer"],
            )

        assert result.created == 1
        assert len(result.errors) == 1
        assert result.errors[0]["role"] == "developer"
