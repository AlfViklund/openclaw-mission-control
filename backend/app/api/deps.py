"""Reusable FastAPI dependencies for auth and board/task access.

These dependencies are the main "policy wiring" layer for the API.

They:
- resolve the authenticated actor (human user vs agent)
- enforce organization/board access rules
- provide common "load or 404" helpers (board/task)

Why this exists:
- Keeping authorization logic centralized makes it easier to reason about (and
  audit) permissions as the API surface grows.
- Some routes allow either human users or agents; others require user auth.

If you're adding a new endpoint, prefer composing from these dependencies instead
of re-implementing permission checks in the router.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status

from app.core.agent_auth import get_agent_auth_context_optional
from app.core.auth import AuthContext, get_auth_context, get_auth_context_optional
from app.db.session import get_session
from app.models.agents import Agent
from app.models.boards import Board
from app.models.organizations import Organization
from app.models.tasks import Task
from app.services.admin_access import require_user_actor
from app.services.organizations import (
    OrganizationContext,
    ensure_member_for_user,
    get_active_membership,
    is_org_admin,
    require_board_access,
)

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.models.agents import Agent
    from app.models.users import User

AUTH_DEP = Depends(get_auth_context)
SESSION_DEP = Depends(get_session)


def require_user_auth(auth: AuthContext = AUTH_DEP) -> AuthContext:
    """Require an authenticated human user (not an agent)."""
    require_user_actor(auth)
    return auth


@dataclass
class ActorContext:
    """Authenticated actor context for user or agent callers."""

    actor_type: Literal["user", "agent"]
    user: User | None = None
    agent: Agent | None = None
    auth_variant: Literal["legacy", "signed_active", "signed_pending"] | None = None
    token_version: int | None = None


async def require_user_or_agent(
    request: Request,
    session: AsyncSession = SESSION_DEP,
) -> ActorContext:
    """Authorize either a human user or an authenticated agent.

    User auth is resolved first so normal bearer-token user traffic does not
    also trigger agent-token verification on mixed user/agent routes.
    """
    auth = await get_auth_context_optional(
        request=request,
        credentials=None,
        session=session,
    )
    if auth is not None:
        require_user_actor(auth)
        return ActorContext(actor_type="user", user=auth.user)
    agent_auth = await get_agent_auth_context_optional(
        request=request,
        agent_token=request.headers.get("X-Agent-Token"),
        authorization=request.headers.get("Authorization"),
        session=session,
    )
    if agent_auth is not None:
        return ActorContext(
            actor_type="agent",
            agent=agent_auth.agent,
            auth_variant=agent_auth.auth_variant,
            token_version=agent_auth.token_version,
        )
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


ACTOR_DEP = Depends(require_user_or_agent)


async def require_org_member(
    auth: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> OrganizationContext:
    """Resolve and require active organization membership for the current user."""
    if auth.user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    member = await get_active_membership(session, auth.user)
    if member is None:
        member = await ensure_member_for_user(session, auth.user)
    if member is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    organization = await Organization.objects.by_id(member.organization_id).first(
        session,
    )
    if organization is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return OrganizationContext(organization=organization, member=member)


ORG_MEMBER_DEP = Depends(require_org_member)


async def require_org_admin(
    ctx: OrganizationContext = ORG_MEMBER_DEP,
) -> OrganizationContext:
    """Require organization-admin membership privileges."""
    if not is_org_admin(ctx.member):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return ctx


async def get_board_or_404(
    board_id: str,
    session: AsyncSession = SESSION_DEP,
) -> Board:
    """Load a board by id or raise HTTP 404."""
    board = await Board.objects.by_id(board_id).first(session)
    if board is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return board


async def get_board_for_actor_read(
    board_id: str,
    session: AsyncSession = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> Board:
    """Load a board and enforce actor read access."""
    board = await Board.objects.by_id(board_id).first(session)
    if board is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if actor.actor_type == "agent":
        if actor.agent and actor.agent.board_id and actor.agent.board_id != board.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        return board
    if actor.user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    await require_board_access(session, user=actor.user, board=board, write=False)
    return board


async def get_board_for_actor_write(
    board_id: str,
    session: AsyncSession = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> Board:
    """Load a board and enforce actor write access."""
    board = await Board.objects.by_id(board_id).first(session)
    if board is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if actor.actor_type == "agent":
        if actor.agent and actor.agent.board_id and actor.agent.board_id != board.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        return board
    if actor.user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    await require_board_access(session, user=actor.user, board=board, write=True)
    return board


async def get_board_for_user_read(
    board_id: str,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = AUTH_DEP,
) -> Board:
    """Load a board and enforce authenticated-user read access."""
    board = await Board.objects.by_id(board_id).first(session)
    if board is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if auth.user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    await require_board_access(session, user=auth.user, board=board, write=False)
    return board


async def get_board_for_user_write(
    board_id: str,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = AUTH_DEP,
) -> Board:
    """Load a board and enforce authenticated-user write access."""
    board = await Board.objects.by_id(board_id).first(session)
    if board is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if auth.user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    await require_board_access(session, user=auth.user, board=board, write=True)
    return board


BOARD_READ_DEP = Depends(get_board_for_actor_read)


async def get_task_or_404(
    task_id: UUID,
    board: Board = BOARD_READ_DEP,
    session: AsyncSession = SESSION_DEP,
) -> Task:
    """Load a task for a board or raise HTTP 404."""
    task = await Task.objects.by_id(task_id).first(session)
    if task is None or task.board_id != board.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return task


async def resolve_actor_task_execution_agent(
    session: AsyncSession,
    *,
    actor: ActorContext,
    task: Task,
    requested_agent_id: UUID | None,
) -> UUID | None:
    """Validate task execution scope and normalize the effective agent id.

    Human users may target any agent on the same board as the task.
    Board agents may execute only on their own board; non-leads may execute only
    as themselves, while leads may target teammates on the same board.
    """
    effective_agent_id = requested_agent_id

    if actor.actor_type == "agent":
        agent = actor.agent
        if agent is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        if task.board_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Agent execution is only allowed for board tasks.",
            )
        if agent.board_id and agent.board_id != task.board_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Agent cannot execute work for a different board.",
            )
        if effective_agent_id is None and not agent.is_board_lead:
            effective_agent_id = agent.id

    if effective_agent_id is None:
        return None

    target_agent = await Agent.objects.by_id(effective_agent_id).first(session)
    if target_agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    if task.board_id and target_agent.board_id != task.board_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Target agent must belong to the same board as the task.",
        )

    if actor.actor_type == "agent":
        actor_agent = actor.agent
        if actor_agent is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        if not actor_agent.is_board_lead and target_agent.id != actor_agent.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only board leads can execute work for other agents.",
            )

    return target_agent.id
