"""Agent provisioning service for role-based team creation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.users import User
from app.services.agent_presets import AGENT_ROLE_PRESETS
from app.services.openclaw.db_agent_state import mint_agent_token
from app.services.openclaw.lifecycle_orchestrator import AgentLifecycleOrchestrator
from app.services.organizations import get_org_owner_user

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession


@dataclass
class TeamProvisionResult:
    """Result of provisioning a full team, including partial failures."""

    created: int = 0
    errors: list[dict] = field(default_factory=list)
    agents: list[Agent] = field(default_factory=list)


class AgentProvisioningService:
    """Provisions agents with role-based presets, including gateway lifecycle."""

    def __init__(self, session: AsyncSession):
        self._session = session

    # -- Helpers --

    async def _require_gateway(self, gateway_id: UUID) -> Gateway:
        gateway = await Gateway.objects.by_id(gateway_id).first(self._session)
        if gateway is None:
            raise ValueError(f"Gateway {gateway_id} not found")
        return gateway

    async def _require_board(self, board_id: UUID) -> Board:
        board = await Board.objects.by_id(board_id).first(self._session)
        if board is None:
            raise ValueError(f"Board {board_id} not found")
        return board

    async def _resolve_template_user(self, gateway: Gateway) -> User | None:
        return await get_org_owner_user(self._session, organization_id=gateway.organization_id)

    # -- Single agent --

    async def create_agent_with_preset(
        self,
        *,
        name: str,
        preset: str,
        board_id: UUID,
        gateway_id: UUID,
    ) -> Agent:
        """Create an agent using a role preset and run full gateway lifecycle."""
        if preset not in AGENT_ROLE_PRESETS:
            raise ValueError(
                f"Unknown preset '{preset}'. "
                f"Available: {', '.join(AGENT_ROLE_PRESETS.keys())}"
            )

        preset_config = AGENT_ROLE_PRESETS[preset]
        gateway = await self._require_gateway(gateway_id)
        board = await self._require_board(board_id)

        agent = Agent(
            name=name,
            board_id=board_id,
            gateway_id=gateway_id,
            identity_profile=dict(preset_config["identity_profile"]),
            heartbeat_config=dict(preset_config["heartbeat_config"]),
            is_board_lead=preset_config["is_board_lead"],
            status="provisioning",
        )

        self._session.add(agent)
        await self._session.commit()
        await self._session.refresh(agent)

        raw_token = mint_agent_token(agent)
        await self._session.commit()

        template_user = await self._resolve_template_user(gateway)
        agent = await AgentLifecycleOrchestrator(self._session).run_lifecycle(
            gateway=gateway,
            agent_id=agent.id,
            board=board,
            user=template_user,
            action="provision",
            auth_token=raw_token,
            force_bootstrap=False,
            reset_session=False,
            wake=True,
            deliver_wakeup=True,
            wakeup_verb=None,
            clear_confirm_token=False,
            raise_gateway_errors=True,
        )
        return agent

    # -- Full team --

    async def provision_full_team(
        self,
        *,
        board_id: UUID,
        gateway_id: UUID,
        roles: list[str] | None = None,
    ) -> TeamProvisionResult:
        """Provision a full team of agents with specified roles.

        Each agent goes through mint token → lifecycle orchestrator → gateway
        provisioning → wake. Partial failures are collected in ``errors`` while
        successful agents continue provisioning.

        Args:
            board_id: Board to create agents for.
            gateway_id: Gateway to run agents on.
            roles: List of role presets to create.
                   Defaults to all 5 roles if not specified.

        Returns:
            TeamProvisionResult with created agents and any errors.
        """
        if roles is None:
            roles = list(AGENT_ROLE_PRESETS.keys())

        gateway = await self._require_gateway(gateway_id)
        board = await self._require_board(board_id)
        template_user = await self._resolve_template_user(gateway)

        result = TeamProvisionResult()

        for role in roles:
            if role not in AGENT_ROLE_PRESETS:
                continue

            preset = AGENT_ROLE_PRESETS[role]
            label = preset["label"]
            agent_name = f"{label} - {board_id.hex[:8]}"

            existing = await Agent.objects.filter_by(
                board_id=board_id,
                is_board_lead=preset["is_board_lead"],
            ).all(self._session)

            role_exists = any(
                (a.identity_profile or {}).get("role") == label for a in existing
            )
            if role_exists:
                continue

            try:
                agent = Agent(
                    name=agent_name,
                    board_id=board_id,
                    gateway_id=gateway_id,
                    identity_profile=dict(preset["identity_profile"]),
                    heartbeat_config=dict(preset["heartbeat_config"]),
                    is_board_lead=preset["is_board_lead"],
                    status="provisioning",
                )
                self._session.add(agent)
                await self._session.commit()
                await self._session.refresh(agent)

                raw_token = mint_agent_token(agent)
                await self._session.commit()

                agent = await AgentLifecycleOrchestrator(self._session).run_lifecycle(
                    gateway=gateway,
                    agent_id=agent.id,
                    board=board,
                    user=template_user,
                    action="provision",
                    auth_token=raw_token,
                    force_bootstrap=False,
                    reset_session=False,
                    wake=True,
                    deliver_wakeup=True,
                    wakeup_verb=None,
                    clear_confirm_token=False,
                    raise_gateway_errors=False,
                )
                result.agents.append(agent)
                result.created += 1
            except Exception as exc:
                result.errors.append({
                    "role": role,
                    "agent_name": agent_name,
                    "error": str(exc),
                })

        return result
