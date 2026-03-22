"""Board memory CRUD and streaming endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func
from sqlmodel import col
from sse_starlette.sse import EventSourceResponse

from app.api.deps import (
    ActorContext,
    get_board_for_actor_read,
    get_board_for_actor_write,
    require_user_or_agent,
)
from app.core.config import settings
from app.core.time import utcnow
from app.db.pagination import paginate
from app.db.session import async_session_maker, get_session
from app.models.agents import Agent
from app.models.board_memory import BoardMemory
from app.schemas.board_memory import BoardMemoryCreate, BoardMemoryRead
from app.schemas.pagination import DefaultLimitOffsetPage
from app.services.mentions import extract_mentions, matches_agent_mention
from app.services.openclaw.gateway_dispatch import GatewayDispatchService
from app.services.openclaw.gateway_rpc import GatewayConfig as GatewayClientConfig
from app.services.openclaw.lifecycle_orchestrator import AgentLifecycleOrchestrator
from app.services.openclaw.provisioning_db import OFFLINE_AFTER, resolve_existing_agent_auth_token_or_raise

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi_pagination.limit_offset import LimitOffsetPage
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.models.boards import Board

router = APIRouter(prefix="/boards/{board_id}/memory", tags=["board-memory"])
logger = logging.getLogger(__name__)
MAX_SNIPPET_LENGTH = 800
STREAM_POLL_SECONDS = 2
IS_CHAT_QUERY = Query(default=None)
SINCE_QUERY = Query(default=None)
BOARD_READ_DEP = Depends(get_board_for_actor_read)
BOARD_WRITE_DEP = Depends(get_board_for_actor_write)
SESSION_DEP = Depends(get_session)
ACTOR_DEP = Depends(require_user_or_agent)
_RUNTIME_TYPE_REFERENCES = (UUID,)


def _parse_since(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    normalized = normalized.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _serialize_memory(memory: BoardMemory) -> dict[str, object]:
    return BoardMemoryRead.model_validate(
        memory,
        from_attributes=True,
    ).model_dump(mode="json")


async def _fetch_memory_events(
    session: AsyncSession,
    board_id: UUID,
    since: datetime,
    is_chat: bool | None = None,
) -> list[BoardMemory]:
    statement = (
        BoardMemory.objects.filter_by(board_id=board_id)
        # Old/invalid rows (empty/whitespace-only content) can exist; exclude them to
        # satisfy the NonEmptyStr response schema.
        .filter(func.length(func.trim(col(BoardMemory.content))) > 0)
    )
    if is_chat is not None:
        statement = statement.filter(col(BoardMemory.is_chat) == is_chat)
    statement = statement.filter(col(BoardMemory.created_at) >= since).order_by(
        col(BoardMemory.created_at),
    )
    return await statement.all(session)


async def _send_control_command(
    *,
    session: AsyncSession,
    board: Board,
    actor: ActorContext,
    dispatch: GatewayDispatchService,
    config: GatewayClientConfig,
    command: str,
) -> None:
    pause_targets: list[Agent] = await Agent.objects.filter_by(
        board_id=board.id,
    ).all(
        session,
    )
    for agent in pause_targets:
        if actor.actor_type == "agent" and actor.agent and agent.id == actor.agent.id:
            continue
        if not agent.openclaw_session_id:
            continue
        error = await dispatch.try_send_agent_message(
            session_key=agent.openclaw_session_id,
            config=config,
            agent_name=agent.name,
            message=command,
            deliver=True,
        )
        if error is not None:
            continue


def _chat_targets(
    *,
    agents: list[Agent],
    mentions: set[str],
    actor: ActorContext,
) -> dict[str, Agent]:
    targets: dict[str, Agent] = {}
    for agent in agents:
        if agent.is_board_lead:
            targets[str(agent.id)] = agent
            continue
        if mentions and matches_agent_mention(agent, mentions):
            targets[str(agent.id)] = agent
    if actor.actor_type == "agent" and actor.agent:
        targets.pop(str(actor.agent.id), None)
    return targets


def _actor_display_name(actor: ActorContext) -> str:
    if actor.actor_type == "agent" and actor.agent:
        return actor.agent.name
    if actor.user:
        return actor.user.preferred_name or actor.user.name or "User"
    return "User"


def _target_needs_wake(agent: Agent) -> bool:
    if agent.status in {"offline", "provisioning", "updating"}:
        return True
    if agent.last_seen_at is None:
        return True
    return utcnow() - agent.last_seen_at > OFFLINE_AFTER


async def _wake_chat_target_if_needed(
    *,
    session: AsyncSession,
    board: Board,
    agent: Agent,
    actor: ActorContext,
) -> bool:
    if not _target_needs_wake(agent):
        return True
    gateway = await GatewayDispatchService(session).require_gateway_config_for_board(board)
    gateway_model, _config = gateway
    auth_token = await resolve_existing_agent_auth_token_or_raise(
        session=session,
        agent=agent,
        gateway=gateway_model,
        timeout_context='board chat wake auth token lookup',
    )
    await AgentLifecycleOrchestrator(session).run_lifecycle(
        gateway=gateway_model,
        agent_id=agent.id,
        board=board,
        user=actor.user,
        action='update',
        auth_token=auth_token,
        force_bootstrap=False,
        reset_session=True,
        wake=True,
        deliver_wakeup=True,
        wakeup_verb='updated',
        clear_confirm_token=True,
        raise_gateway_errors=True,
    )
    return False


async def _notify_chat_targets(
    *,
    session: AsyncSession,
    board: Board,
    memory: BoardMemory,
    actor: ActorContext,
) -> None:
    if not memory.content:
        return
    dispatch = GatewayDispatchService(session)
    config = await dispatch.optional_gateway_config_for_board(board)
    if config is None:
        return

    normalized = memory.content.strip()
    command = normalized.lower()
    # Special-case control commands to reach all board agents.
    # These are intended to be parsed verbatim by agent runtimes.
    if command in {"/pause", "/resume"}:
        await _send_control_command(
            session=session,
            board=board,
            actor=actor,
            dispatch=dispatch,
            config=config,
            command=command,
        )
        return

    mentions = extract_mentions(memory.content)
    targets = _chat_targets(
        agents=await Agent.objects.filter_by(board_id=board.id).all(session),
        mentions=mentions,
        actor=actor,
    )
    if not targets:
        return
    actor_name = _actor_display_name(actor)
    snippet = memory.content.strip()
    if len(snippet) > MAX_SNIPPET_LENGTH:
        snippet = f"{snippet[: MAX_SNIPPET_LENGTH - 3]}..."
    base_url = settings.base_url
    for agent in targets.values():
        try:
            can_deliver_to_existing_session = await _wake_chat_target_if_needed(
                session=session,
                board=board,
                agent=agent,
                actor=actor,
            )
        except Exception as exc:
            logger.warning(
                "board.chat.wake.failed board_id=%s agent_id=%s agent_name=%s exc_type=%s exc=%s",
                board.id,
                agent.id,
                agent.name,
                type(exc).__name__,
                exc,
            )
            # Do not route board chat into a stale session if controlled wake/reset failed.
            continue
        if not can_deliver_to_existing_session:
            continue
        if not agent.openclaw_session_id:
            continue
        mentioned = matches_agent_mention(agent, mentions)
        header = "BOARD CHAT MENTION" if mentioned else "BOARD CHAT"
        message = (
            f"{header}\n"
            f"Board: {board.name}\n"
            f"From: {actor_name}\n\n"
            f"{snippet}\n\n"
            "Reply via board chat:\n"
            f"POST {base_url}/api/v1/agent/boards/{board.id}/memory\n"
            'Body: {"content":"...","tags":["chat"]}'
        )
        error = await dispatch.try_send_agent_message(
            session_key=agent.openclaw_session_id,
            config=config,
            agent_name=agent.name,
            message=message,
            deliver=True,
        )
        if error is not None:
            continue


@router.get("", response_model=DefaultLimitOffsetPage[BoardMemoryRead])
async def list_board_memory(
    *,
    is_chat: bool | None = IS_CHAT_QUERY,
    board: Board = BOARD_READ_DEP,
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = ACTOR_DEP,
) -> LimitOffsetPage[BoardMemoryRead]:
    """List board memory entries, optionally filtering chat entries."""
    statement = (
        BoardMemory.objects.filter_by(board_id=board.id)
        # Old/invalid rows (empty/whitespace-only content) can exist; exclude them to
        # satisfy the NonEmptyStr response schema.
        .filter(func.length(func.trim(col(BoardMemory.content))) > 0)
    )
    if is_chat is not None:
        statement = statement.filter(col(BoardMemory.is_chat) == is_chat)
    statement = statement.order_by(col(BoardMemory.created_at).desc())
    return await paginate(session, statement.statement)


@router.get("/stream")
async def stream_board_memory(
    request: Request,
    *,
    board: Board = BOARD_READ_DEP,
    _actor: ActorContext = ACTOR_DEP,
    since: str | None = SINCE_QUERY,
    is_chat: bool | None = IS_CHAT_QUERY,
) -> EventSourceResponse:
    """Stream board memory events over server-sent events."""
    since_dt = _parse_since(since) or utcnow()
    last_seen = since_dt

    async def event_generator() -> AsyncIterator[dict[str, str]]:
        nonlocal last_seen
        while True:
            if await request.is_disconnected():
                break
            async with async_session_maker() as session:
                memories = await _fetch_memory_events(
                    session,
                    board.id,
                    last_seen,
                    is_chat=is_chat,
                )
            for memory in memories:
                last_seen = max(memory.created_at, last_seen)
                payload = {"memory": _serialize_memory(memory)}
                yield {"event": "memory", "data": json.dumps(payload)}
            await asyncio.sleep(STREAM_POLL_SECONDS)

    return EventSourceResponse(event_generator(), ping=15)


@router.post("", response_model=BoardMemoryRead)
async def create_board_memory(
    payload: BoardMemoryCreate,
    board: Board = BOARD_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> BoardMemory:
    """Create a board memory entry and notify chat targets when needed."""
    is_chat = payload.tags is not None and "chat" in payload.tags
    source = payload.source
    if is_chat and not source:
        if actor.actor_type == "agent" and actor.agent:
            source = actor.agent.name
        elif actor.user:
            source = actor.user.preferred_name or actor.user.name or "User"
    memory = BoardMemory(
        board_id=board.id,
        content=payload.content,
        tags=payload.tags,
        is_chat=is_chat,
        source=source,
    )
    session.add(memory)
    await session.commit()
    await session.refresh(memory)
    if is_chat:
        await _notify_chat_targets(
            session=session,
            board=board,
            memory=memory,
            actor=actor,
        )
    return memory
