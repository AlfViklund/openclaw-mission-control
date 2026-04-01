"""Agent provisioning service for role-based team creation."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from app.models.agents import Agent
from app.services.agent_presets import AGENT_ROLE_PRESETS

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession


class AgentProvisioningService:
    """Provisions agents with role-based presets."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create_agent_with_preset(
        self,
        *,
        name: str,
        preset: str,
        board_id: UUID,
        gateway_id: UUID,
    ) -> Agent:
        """Create an agent using a role preset configuration."""
        if preset not in AGENT_ROLE_PRESETS:
            raise ValueError(
                f"Unknown preset '{preset}'. "
                f"Available: {', '.join(AGENT_ROLE_PRESETS.keys())}"
            )

        preset_config = AGENT_ROLE_PRESETS[preset]

        agent = Agent(
            name=name,
            board_id=board_id,
            gateway_id=gateway_id,
            identity_profile=preset_config["identity_profile"],
            heartbeat_config=preset_config["heartbeat_config"],
            is_board_lead=preset_config["is_board_lead"],
            status="provisioning",
        )

        self._session.add(agent)
        await self._session.commit()
        await self._session.refresh(agent)
        return agent

    async def provision_full_team(
        self,
        *,
        board_id: UUID,
        gateway_id: UUID,
        roles: list[str] | None = None,
    ) -> list[Agent]:
        """Provision a full team of agents with specified roles.

        Args:
            board_id: Board to create agents for.
            gateway_id: Gateway to run agents on.
            roles: List of role presets to create.
                   Defaults to all 5 roles if not specified.

        Returns:
            List of created Agent records.
        """
        if roles is None:
            roles = list(AGENT_ROLE_PRESETS.keys())

        agents = []
        for role in roles:
            if role not in AGENT_ROLE_PRESETS:
                continue

            preset = AGENT_ROLE_PRESETS[role]
            label = preset["label"]
            name = f"{label} - {board_id.hex[:8]}"

            existing = await Agent.objects.filter_by(
                board_id=board_id,
                is_board_lead=preset["is_board_lead"],
            ).all(self._session)

            role_exists = any(
                a.identity_profile.get("role") == label for a in existing
            )
            if role_exists:
                continue

            agent = Agent(
                name=name,
                board_id=board_id,
                gateway_id=gateway_id,
                identity_profile=preset["identity_profile"],
                heartbeat_config=preset["heartbeat_config"],
                is_board_lead=preset["is_board_lead"],
                status="provisioning",
            )
            self._session.add(agent)
            agents.append(agent)

        if agents:
            await self._session.commit()
            for agent in agents:
                await self._session.refresh(agent)

        return agents
