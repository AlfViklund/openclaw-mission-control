"""DB-backed gateway config resolution and message dispatch helpers.

This module exists to keep `app.api.*` thin: APIs should call OpenClaw services, not
directly orchestrate gateway RPC calls.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.services.openclaw.db_service import OpenClawDBService
from app.services.openclaw.gateway_resolver import (
    gateway_client_config,
    get_gateway_for_board,
    optional_gateway_client_config,
    require_gateway_for_board,
)
from app.services.openclaw.gateway_rpc import GatewayConfig as GatewayClientConfig
from app.services.openclaw.gateway_rpc import OpenClawGatewayError, ensure_session, send_message
from app.services.openclaw.internal.session_keys import resolve_canonical_agent_session

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession


class GatewayDispatchService(OpenClawDBService):
    """Resolve gateway config for boards and dispatch messages to agent sessions."""

    async def optional_gateway_config_for_board(
        self,
        board: Board,
    ) -> GatewayClientConfig | None:
        gateway = await get_gateway_for_board(self.session, board)
        return optional_gateway_client_config(gateway)

    async def require_gateway_config_for_board(
        self,
        board: Board,
    ) -> tuple[Gateway, GatewayClientConfig]:
        gateway = await require_gateway_for_board(self.session, board)
        return gateway, gateway_client_config(gateway)

    async def send_agent_message(
        self,
        *,
        session_key: str,
        config: GatewayClientConfig,
        agent_name: str,
        message: str,
        deliver: bool = False,
    ) -> None:
        await ensure_session(session_key, config=config, label=agent_name)
        await send_message(message, session_key=session_key, config=config, deliver=deliver)

    async def send_to_agent(
        self,
        *,
        agent: Agent,
        message: str,
        deliver: bool = False,
    ) -> None:
        """Send a message to an agent using its canonical session key.

        This is the **only** entry point for agent-directed sends.  It
        always resolves the canonical session key, so even if
        ``agent.openclaw_session_id`` has drifted in the database the
        message still reaches the correct session.
        """
        canonical_key = resolve_canonical_agent_session(agent)
        board = None
        if agent.board_id:
            board = await Board.objects.by_id(agent.board_id).first(self.session)
        if board is None or not board.gateway_id:
            raise ValueError(f"Agent {agent.id} has no board or gateway")
        gateway = await Gateway.objects.by_id(board.gateway_id).first(self.session)
        if gateway is None:
            raise ValueError(f"Gateway not found for board {board.id}")
        config = gateway_client_config(gateway)
        await self.send_agent_message(
            session_key=canonical_key,
            config=config,
            agent_name=agent.name,
            message=message,
            deliver=deliver,
        )

    async def try_send_agent_message(
        self,
        *,
        session_key: str,
        config: GatewayClientConfig,
        agent_name: str,
        message: str,
        deliver: bool = False,
    ) -> OpenClawGatewayError | None:
        try:
            await self.send_agent_message(
                session_key=session_key,
                config=config,
                agent_name=agent_name,
                message=message,
                deliver=deliver,
            )
        except OpenClawGatewayError as exc:
            return exc
        return None

    @staticmethod
    def resolve_trace_id(correlation_id: str | None, *, prefix: str) -> str:
        normalized = (correlation_id or "").strip()
        if normalized:
            return normalized
        return f"{prefix}:{uuid4().hex[:12]}"
