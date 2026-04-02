"""Board automation policy sync helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlmodel import col

from app.core.logging import get_logger
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.services.openclaw.provisioning import OpenClawGatewayError, OpenClawGatewayProvisioner

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class BoardAutomationSyncResult:
    agents_updated: int
    gateway_syncs_succeeded: int
    gateway_syncs_failed: int


def _heartbeat_update(automation: dict[str, Any]) -> dict[str, Any]:
    update: dict[str, Any] = {}
    for source_key, target_key in (
        ("online_every_seconds", "online_every_seconds"),
        ("idle_every_seconds", "idle_every_seconds"),
        ("dormant_every_seconds", "dormant_every_seconds"),
        ("wake_on_approvals", "wake_on_approvals"),
        ("wake_on_review", "wake_on_review"),
        ("allow_assist_mode", "allow_assist_mode"),
    ):
        if source_key in automation:
            update[target_key] = automation[source_key]
    return update


async def sync_board_automation_policy(
    session: AsyncSession,
    board: Board,
) -> BoardAutomationSyncResult:
    """Persist board automation policy into agent heartbeat config and gateway runtime."""
    automation = getattr(board, "automation_config", None) or {}
    if not isinstance(automation, dict):
        return BoardAutomationSyncResult(agents_updated=0, gateway_syncs_succeeded=0, gateway_syncs_failed=0)

    hb_update = _heartbeat_update(automation)
    if not hb_update:
        return BoardAutomationSyncResult(agents_updated=0, gateway_syncs_succeeded=0, gateway_syncs_failed=0)

    agents = await Agent.objects.filter(col(Agent.board_id) == board.id).all(session)
    if not agents:
        return BoardAutomationSyncResult(agents_updated=0, gateway_syncs_succeeded=0, gateway_syncs_failed=0)

    for agent in agents:
        current_hb = getattr(agent, "heartbeat_config", None) or {}
        if not isinstance(current_hb, dict):
            current_hb = {}
        agent.heartbeat_config = {**current_hb, **hb_update}
        session.add(agent)

    await session.commit()

    if board.gateway_id is None:
        logger.warning("board.automation.sync_skipped board_id=%s reason=no_gateway", board.id)
        return BoardAutomationSyncResult(
            agents_updated=len(agents),
            gateway_syncs_succeeded=0,
            gateway_syncs_failed=1,
        )

    gateway = await Gateway.objects.by_id(board.gateway_id).first(session)
    if gateway is None:
        logger.warning("board.automation.sync_skipped board_id=%s reason=gateway_missing", board.id)
        return BoardAutomationSyncResult(
            agents_updated=len(agents),
            gateway_syncs_succeeded=0,
            gateway_syncs_failed=1,
        )

    try:
        await OpenClawGatewayProvisioner().sync_gateway_agent_heartbeats(gateway, agents)
    except OpenClawGatewayError as exc:
        logger.warning(
            "board.automation.gateway_sync_failed board_id=%s gateway_id=%s error=%s",
            board.id,
            gateway.id,
            exc,
        )
        return BoardAutomationSyncResult(
            agents_updated=len(agents),
            gateway_syncs_succeeded=0,
            gateway_syncs_failed=1,
        )

    return BoardAutomationSyncResult(
        agents_updated=len(agents),
        gateway_syncs_succeeded=1,
        gateway_syncs_failed=0,
    )
