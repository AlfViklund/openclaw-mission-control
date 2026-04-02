"""Thin API wrappers for async agent lifecycle operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sse_starlette.sse import EventSourceResponse

from app.api.deps import ActorContext, require_org_admin, require_user_or_agent
from app.core.auth import AuthContext, get_auth_context
from app.db.session import get_session
from app.schemas.agents import (
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


@router.post("/{agent_id}/heartbeat", response_model=AgentRead)
async def heartbeat_agent(
    agent_id: str,
    payload: AgentHeartbeat,
    session: AsyncSession = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> AgentRead:
    """Record a heartbeat for a specific agent."""
    service = AgentLifecycleService(session)
    return await service.heartbeat_agent(agent_id=agent_id, payload=payload, actor=actor)


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
    """
    from uuid import UUID
    from app.api.deps import require_user

    require_user(actor)
    from app.services.agent_work import get_work_snapshot

    return await get_work_snapshot(session, UUID(agent_id))


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
