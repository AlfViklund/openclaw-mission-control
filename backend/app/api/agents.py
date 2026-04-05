"""Thin API wrappers for async agent lifecycle operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sse_starlette.sse import EventSourceResponse

from app.api.deps import ActorContext, require_org_admin, require_user_or_agent
from app.core.auth import AuthContext, get_auth_context
from app.core.time import utcnow
from app.db.session import get_session
from app.models.boards import Board
from app.schemas.agents import (
    AgentAuthRepairResponse,
    AgentCreate,
    AgentHeartbeat,
    AgentHeartbeatCreate,
    AgentRead,
    AgentUpdate,
)
from app.schemas.common import OkResponse
from app.schemas.pagination import DefaultLimitOffsetPage
from app.services.agent_presets import AGENT_ROLE_PRESETS
from app.services.agent_provisioning import AgentProvisioningService
from app.services.openclaw.provisioning_db import AgentLifecycleService, AgentUpdateOptions
from app.services.organizations import OrganizationContext

if TYPE_CHECKING:
    from fastapi_pagination.limit_offset import LimitOffsetPage
    from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter(prefix="/agents", tags=["agents"])

BOARD_ID_QUERY = Query(default=None)
GATEWAY_ID_QUERY = Query(default=None)
SINCE_QUERY = Query(default=None)
SESSION_DEP = Depends(get_session)
ORG_ADMIN_DEP = Depends(require_org_admin)
ACTOR_DEP = Depends(require_user_or_agent)
AUTH_DEP = Depends(get_auth_context)


@dataclass(frozen=True, slots=True)
class _AgentUpdateParams:
    force: bool
    auth: AuthContext
    ctx: OrganizationContext


def _agent_update_params(
    *,
    force: bool = False,
    auth: AuthContext = AUTH_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> _AgentUpdateParams:
    return _AgentUpdateParams(force=force, auth=auth, ctx=ctx)


AGENT_UPDATE_PARAMS_DEP = Depends(_agent_update_params)


@router.get("", response_model=DefaultLimitOffsetPage[AgentRead])
async def list_agents(
    board_id: UUID | None = BOARD_ID_QUERY,
    gateway_id: UUID | None = GATEWAY_ID_QUERY,
    session: AsyncSession = SESSION_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> LimitOffsetPage[AgentRead]:
    """List agents visible to the active organization admin."""
    service = AgentLifecycleService(session)
    return await service.list_agents(
        board_id=board_id,
        gateway_id=gateway_id,
        ctx=ctx,
    )


@router.get("/stream")
async def stream_agents(
    request: Request,
    board_id: UUID | None = BOARD_ID_QUERY,
    since: str | None = SINCE_QUERY,
    session: AsyncSession = SESSION_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> EventSourceResponse:
    """Stream agent updates as SSE events."""
    service = AgentLifecycleService(session)
    return await service.stream_agents(
        request=request,
        board_id=board_id,
        since=since,
        ctx=ctx,
    )


@router.post("", response_model=AgentRead)
async def create_agent(
    payload: AgentCreate,
    session: AsyncSession = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> AgentRead:
    """Create and provision an agent."""
    service = AgentLifecycleService(session)
    return await service.create_agent(payload=payload, actor=actor)


@router.get("/{agent_id}", response_model=AgentRead)
async def get_agent(
    agent_id: str,
    session: AsyncSession = SESSION_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> AgentRead:
    """Get a single agent by id."""
    service = AgentLifecycleService(session)
    return await service.get_agent(agent_id=agent_id, ctx=ctx)


@router.patch("/{agent_id}", response_model=AgentRead)
async def update_agent(
    agent_id: str,
    payload: AgentUpdate,
    params: _AgentUpdateParams = AGENT_UPDATE_PARAMS_DEP,
    session: AsyncSession = SESSION_DEP,
) -> AgentRead:
    """Update agent metadata and optionally reprovision."""
    service = AgentLifecycleService(session)
    return await service.update_agent(
        agent_id=agent_id,
        payload=payload,
        options=AgentUpdateOptions(
            force=params.force,
            user=params.auth.user,
            context=params.ctx,
        ),
    )


@router.post("/{agent_id}/heartbeat", response_model=dict)
async def heartbeat_agent(
    agent_id: str,
    payload: AgentHeartbeat,
    session: AsyncSession = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> dict:
    """Record a heartbeat for a specific agent.

    Returns the agent profile plus an ``is_busy`` flag indicating whether
    the agent already has a running pipeline run (in which case the agent
    should skip heavy work cycles and stay in presence-only mode).
    """
    from uuid import UUID
    from app.models.agents import Agent
    from app.models.runs import Run
    from sqlmodel import col, select

    service = AgentLifecycleService(session)
    agent_read = await service.heartbeat_agent(agent_id=agent_id, payload=payload, actor=actor)

    if actor.actor_type == "agent" and actor.auth_variant == "signed_pending":
        from app.services.openclaw.db_agent_state import promote_pending_token
        agent_obj = await Agent.objects.by_id(agent_read.id).first(session)
        if agent_obj is not None:
            promote_pending_token(agent_obj)
            session.add(agent_obj)
            await session.commit()
            await session.refresh(agent_obj)
            agent_read = service.to_agent_read(service.with_computed_status(agent_obj))

    busy_statement = (
        select(Run)
        .where(col(Run.agent_id) == agent_read.id, col(Run.status) == "running")
        .limit(1)
    )
    is_busy = (await session.exec(busy_statement)).first() is not None

    result = agent_read.model_dump(mode="json")
    result["is_busy"] = is_busy
    return result


@router.post("/heartbeat", response_model=AgentRead)
async def heartbeat_or_create_agent(
    payload: AgentHeartbeatCreate,
    session: AsyncSession = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> AgentRead:
    """Heartbeat an existing agent or create/provision one if needed."""
    service = AgentLifecycleService(session)
    return await service.heartbeat_or_create_agent(payload=payload, actor=actor)


@router.get("/{agent_id}/work-snapshot")
async def get_agent_work_snapshot(
    agent_id: str,
    session: AsyncSession = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> dict:
    """Return a lightweight work snapshot for an agent.

    Answers "should this agent wake up?" without reasoning, memory pulls,
    or assist-mode overhead.  Includes busy-gating: if the agent already
    has a running run, should_wake is false.

    Authorization:
    - Agent token: can read only own snapshot
    - Board lead: can read snapshots of team agents on same board
    - Board admin/owner: can read snapshots of agents on their board
    - Org admin: full access
    """
    from uuid import UUID

    target_id = UUID(agent_id)

    # Agent token self-access
    if actor.agent and actor.agent.id == target_id:
        from app.services.agent_work import get_work_snapshot
        return await get_work_snapshot(session, target_id)

    # Board lead agent can read snapshots of team agents on same board
    if actor.agent:
        from app.models.agents import Agent
        from app.services.agent_work import get_work_snapshot

        target = await Agent.objects.by_id(target_id).first(session)
        if target is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
        if target.board_id and actor.agent.board_id == target.board_id:
            lead_agents = await Agent.objects.filter_by(
                board_id=target.board_id, is_board_lead=True,
            ).all(session)
            if any(a.id == actor.agent.id for a in lead_agents):
                return await get_work_snapshot(session, target_id)

    # User-based access: verify board-level permissions
    from app.api.deps import require_user
    require_user(actor)

    from app.models.agents import Agent
    target = await Agent.objects.by_id(target_id).first(session)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    # Org admin / board owner
    if actor.user:
        from app.services.organizations import is_org_admin, has_board_access
        if await is_org_admin(session, actor.user.id):
            from app.services.agent_work import get_work_snapshot
            return await get_work_snapshot(session, target_id)
        if target.board_id and await has_board_access(session, actor.user.id, target.board_id):
            from app.services.agent_work import get_work_snapshot
            return await get_work_snapshot(session, target_id)

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")


@router.get("/boards/{board_id}/work-snapshots")
async def get_board_work_snapshots(
    board_id: str,
    session: AsyncSession = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> dict:
    """Return work-snapshots for all agents on a board.

    Batch endpoint so the UI can fetch real wake reasons for every agent
    in a single call instead of N individual requests.
    """
    from uuid import UUID
    from app.models.agents import Agent
    from sqlmodel import col

    require_user(actor)
    bid = UUID(board_id)
    agents = await Agent.objects.filter(col(Agent.board_id) == bid).all(session)
    from app.services.agent_work import get_work_snapshot

    snapshots: dict[str, dict] = {}
    for agent in agents:
        try:
            snapshots[str(agent.id)] = await get_work_snapshot(session, agent.id)
        except ValueError:
            snapshots[str(agent.id)] = {"should_wake": False, "reason": "error"}
    return {"snapshots": snapshots}


@router.delete("/{agent_id}", response_model=OkResponse)
async def delete_agent(
    agent_id: str,
    session: AsyncSession = SESSION_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> OkResponse:
    """Delete an agent and clean related task state."""
    service = AgentLifecycleService(session)
    return await service.delete_agent(agent_id=agent_id, ctx=ctx)


@router.get("/presets")
async def list_agent_presets(
    _ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> dict:
    """List available agent role presets."""
    return {
        "presets": {
            key: {
                "label": val["label"],
                "description": val["description"],
                "emoji": val["emoji"],
                "is_board_lead": val["is_board_lead"],
            }
            for key, val in AGENT_ROLE_PRESETS.items()
        }
    }


@router.post("/presets/{preset}/create")
async def create_agent_from_preset(
    preset: str,
    name: str = Query(...),
    board_id: UUID = Query(...),
    gateway_id: UUID = Query(...),
    session: AsyncSession = SESSION_DEP,
    _ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> AgentRead:
    """Create an agent using a role preset and run full gateway provisioning."""
    service = AgentProvisioningService(session)
    agent = await service.create_agent_with_preset(
        name=name,
        preset=preset,
        board_id=board_id,
        gateway_id=gateway_id,
    )
    return AgentRead.model_validate(agent)


@router.post("/boards/{board_id}/team/provision")
async def provision_team(
    board_id: UUID,
    roles: list[str] | None = Query(default=None),
    gateway_id: UUID = Query(...),
    session: AsyncSession = SESSION_DEP,
    _ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> dict:
    """Provision a full team of agents for a board with gateway lifecycle.

    Each agent is created, provisioned on the gateway, and woken up.
    Partial failures are collected in the ``errors`` list while successful
    agents continue provisioning.
    """
    service = AgentProvisioningService(session)
    result = await service.provision_full_team(
        board_id=board_id,
        gateway_id=gateway_id,
        roles=roles,
    )
    return {
        "created": result.created,
        "errors": result.errors,
        "agents": [AgentRead.model_validate(a).model_dump() for a in result.agents],
    }


@router.post("/{agent_id}/repair-auth-sync", response_model=AgentAuthRepairResponse)
async def repair_agent_auth_sync(
    agent_id: str,
    session: AsyncSession = SESSION_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> AgentAuthRepairResponse:
    """Repair agent auth sync for a drifted agent.

    Healing/idempotent operation — resets to a known good state:
    - legacy_hash: rollback any stale pending, start fresh migration,
      reprovision with new pending token, reset + wake
    - signed: rollback any stale pending, reprovision with current active
      token (does NOT bump version), reset + wake
    """
    from app.models.agents import Agent
    from app.models.gateways import Gateway

    from app.services.openclaw.constants import DEFAULT_HEARTBEAT_CONFIG
    from app.services.openclaw.db_agent_state import (
        begin_signed_migration,
        current_agent_runtime_token,
        rollback_pending_token,
    )
    from app.services.openclaw.gateway_resolver import (
        require_gateway_for_board,
    )

    agent = await Agent.objects.by_id(agent_id).first(session)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    if agent.board_id is None:
        gateway = await Gateway.objects.by_id(agent.gateway_id).first(session)
        if gateway is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Gateway not found for gateway-main agent",
            )
        board = None
    else:
        board = await Board.objects.by_id(agent.board_id).first(session)
        gateway = await require_gateway_for_board(
            session,
            board,
            require_workspace_root=True,
        )

    if agent.agent_auth_mode == "legacy_hash":
        rollback_pending_token(agent, "repair: starting fresh migration")
        begin_signed_migration(agent)
        session.add(agent)
        await session.flush()
    elif agent.agent_auth_mode == "signed":
        rollback_pending_token(agent, "repair: reverting to active token")
        session.add(agent)
        await session.flush()

    if agent.heartbeat_config is None:
        agent.heartbeat_config = DEFAULT_HEARTBEAT_CONFIG.copy()
        session.add(agent)
        await session.flush()

    try:
        raw_token = current_agent_runtime_token(agent)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Cannot resolve runtime token: {exc}",
        ) from exc

    from pathlib import Path
    import re

    workspace_dir = Path.home() / ".openclaw" / f"workspace-gateway-{gateway.id}"
    heartbeat_path = workspace_dir / "HEARTBEAT.md"
    tools_path = workspace_dir / "TOOLS.md"
    agents_path = workspace_dir / "AGENTS.md"
    workspace_dir.mkdir(parents=True, exist_ok=True)

    def _replace_token(text: str, key: str, token: str) -> str:
        if key == "HEARTBEAT.md":
            pattern = r"(X-Agent-Token:\s*`?)[^`\s]+(`?)"
            if "X-Agent-Token" not in text:
                return text.rstrip() + f"\nX-Agent-Token: {token}\n"
            def repl(match: re.Match[str]) -> str:
                return f"{match.group(1)}{token}{match.group(2)}"

            return re.sub(pattern, repl, text)
        if key == "TOOLS.md":
            pattern = r"(AUTH_TOKEN\s*[:=]\s*`?)[^`\s]+(`?)"
            if "AUTH_TOKEN" not in text:
                return text.rstrip() + f"\nAUTH_TOKEN={token}\n"
            def repl(match: re.Match[str]) -> str:
                return f"{match.group(1)}{token}{match.group(2)}"

            return re.sub(pattern, repl, text)
        if key == "AGENTS.md":
            updated_lines: list[str] = []
            for line in text.splitlines():
                stripped = line.lstrip()
                indent = line[: len(line) - len(stripped)]
                if stripped.startswith("- `AUTH_TOKEN`:"):
                    updated_lines.append(f"{indent}- `AUTH_TOKEN`: {token}")
                    continue
                if stripped.startswith("- Always include header:"):
                    updated_lines.append(f"{indent}- Always include header: `X-Agent-Token: {token}`")
                    continue
                if stripped.startswith('-H "X-Agent-Token:'):
                    trailer = " \\" if stripped.endswith("\\") else ""
                    updated_lines.append(f'{indent}-H "X-Agent-Token: {token}"{trailer}')
                    continue
                updated_lines.append(line)
            return "\n".join(updated_lines) + ("\n" if text.endswith("\n") else "")

        return text

    live_heartbeat_text = heartbeat_path.read_text(encoding="utf-8") if heartbeat_path.exists() else ""
    live_tools_text = tools_path.read_text(encoding="utf-8") if tools_path.exists() else ""
    live_agents_text = agents_path.read_text(encoding="utf-8") if agents_path.exists() else ""
    live_heartbeat_token = ""
    live_tools_token = ""
    live_agents_token = ""

    heartbeat_match = re.search(r"X-Agent-Token:\s*`?([^`\s]+)`?", live_heartbeat_text)
    if heartbeat_match:
        live_heartbeat_token = heartbeat_match.group(1).strip()
    tools_match = re.search(r"AUTH_TOKEN\s*[:=]\s*`?([^`\s]+)`?", live_tools_text)
    if tools_match:
        live_tools_token = tools_match.group(1).strip()
    agents_match = re.search(r"X-Agent-Token:\s*`?([^`\s]+)`?", live_agents_text)
    if agents_match:
        live_agents_token = agents_match.group(1).strip()

    if (
        live_heartbeat_token != raw_token
        or live_tools_token != raw_token
        or live_agents_token != raw_token
    ):
        heartbeat_path.write_text(_replace_token(live_heartbeat_text, "HEARTBEAT.md", raw_token), encoding="utf-8")
        tools_path.write_text(_replace_token(live_tools_text, "TOOLS.md", raw_token), encoding="utf-8")
        if agents_path.exists():
            agents_path.write_text(_replace_token(live_agents_text, "AGENTS.md", raw_token), encoding="utf-8")

    heartbeat_after = heartbeat_path.read_text(encoding="utf-8") if heartbeat_path.exists() else ""
    tools_after = tools_path.read_text(encoding="utf-8") if tools_path.exists() else ""
    agents_after = agents_path.read_text(encoding="utf-8") if agents_path.exists() else ""
    if (
        raw_token not in heartbeat_after
        or raw_token not in tools_after
        or (agents_path.exists() and raw_token not in agents_after)
    ):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Gateway update failed: live auth files were not updated",
        )

    agent.last_provision_error = None
    agent.agent_auth_last_error = None
    agent.agent_auth_last_synced_at = utcnow()
    agent.updated_at = utcnow()
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return AgentAuthRepairResponse(
        agent_id=agent.id,
        agent_auth_mode=agent.agent_auth_mode,
        agent_token_version=agent.agent_token_version,
        pending_agent_token_version=agent.pending_agent_token_version,
        status=agent.status,
        agent_auth_last_error=agent.agent_auth_last_error,
    )


@router.post("/{agent_id}/rotate-auth-token", response_model=AgentAuthRepairResponse)
async def rotate_agent_auth_token(
    agent_id: str,
    session: AsyncSession = SESSION_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> AgentAuthRepairResponse:
    """Rotate agent auth token via staged rotation.

    Creates a new pending token version, reprovisions templates,
    resets session, and wakes the agent. The old token remains valid
    until the first successful heartbeat with the new token.
    """
    from app.models.agents import Agent
    from app.models.gateways import Gateway

    from app.services.openclaw.constants import DEFAULT_HEARTBEAT_CONFIG
    from app.services.openclaw.db_agent_state import (
        begin_signed_rotation,
        current_agent_runtime_token,
        rollback_pending_token,
    )
    from app.services.openclaw.lifecycle_orchestrator import AgentLifecycleOrchestrator
    from app.services.openclaw.gateway_resolver import (
        require_gateway_for_board,
    )

    agent = await Agent.objects.by_id(agent_id).first(session)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    if agent.agent_auth_mode != "signed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Token rotation requires agent to be in signed auth mode. "
                   "Use repair-auth-sync first to migrate from legacy.",
        )

    if agent.board_id is None:
        gateway = await Gateway.objects.by_id(agent.gateway_id).first(session)
        if gateway is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Gateway not found for gateway-main agent",
            )
        board = None
    else:
        board = await Board.objects.by_id(agent.board_id).first(session)
        gateway = await require_gateway_for_board(
            session,
            board,
            require_workspace_root=True,
        )

    begin_signed_rotation(agent)
    session.add(agent)
    await session.flush()

    if agent.heartbeat_config is None:
        agent.heartbeat_config = DEFAULT_HEARTBEAT_CONFIG.copy()
        session.add(agent)
        await session.flush()

    try:
        raw_token = current_agent_runtime_token(agent)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Cannot resolve runtime token: {exc}",
        ) from exc

    from app.models.users import User
    template_user: User | None = None

    orchestrator = AgentLifecycleOrchestrator(session)
    try:
        await orchestrator.run_lifecycle(
            gateway=gateway,
            agent_id=agent.id,
            board=board,
            user=template_user,
            action="update",
            auth_token=raw_token,
            force_bootstrap=False,
            reset_session=True,
            wake=True,
            deliver_wakeup=True,
            wakeup_verb="rotated",
            clear_confirm_token=False,
            raise_gateway_errors=True,
        )
    except HTTPException as exc:
        rollback_pending_token(agent, str(exc.detail))
        agent.updated_at = utcnow()
        session.add(agent)
        await session.commit()
        await session.refresh(agent)
        raise

    await session.refresh(agent)
    return AgentAuthRepairResponse(
        agent_id=agent.id,
        agent_auth_mode=agent.agent_auth_mode,
        agent_token_version=agent.agent_token_version,
        pending_agent_token_version=agent.pending_agent_token_version,
        status=agent.status,
        agent_auth_last_error=agent.agent_auth_last_error,
    )
