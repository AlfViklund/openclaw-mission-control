# ruff: noqa: S101
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.deps import ActorContext
from app.api.board_memory import (
    _notify_chat_targets,
    _target_needs_wake,
    _wake_chat_target_if_needed,
)
from app.services.openclaw.provisioning_db import _parse_tools_md


@dataclass
class _AgentStub:
    id: object
    name: str
    status: str = "offline"
    is_board_lead: bool = False
    openclaw_session_id: str | None = None
    last_seen_at: datetime | None = None


@dataclass
class _BoardStub:
    id: object
    name: str = "CardFlowAI"


@dataclass
class _MemoryStub:
    content: str


class _AgentQuery:
    def __init__(self, agents: list[_AgentStub]) -> None:
        self._agents = agents

    async def all(self, _session: object) -> list[_AgentStub]:
        return list(self._agents)


@pytest.fixture
def actor_user() -> ActorContext:
    user = SimpleNamespace(id=uuid4(), preferred_name="Local", name="Local")
    return ActorContext(actor_type="user", user=user, agent=None)


def test_parse_tools_md_accepts_real_markdown_bullet_format() -> None:
    content = """
# Tools
- `BASE_URL=http://127.0.0.1:8000`
- `AUTH_TOKEN=abc123-token-value`
"""
    parsed = _parse_tools_md(content)
    assert parsed["BASE_URL"] == "http://127.0.0.1:8000"
    assert parsed["AUTH_TOKEN"] == "abc123-token-value"


def test_target_needs_wake_for_offline_and_stale_agents() -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    offline = _AgentStub(id=uuid4(), name="Offline", status="offline")
    stale = _AgentStub(
        id=uuid4(),
        name="Stale",
        status="online",
        last_seen_at=now - timedelta(minutes=30),
    )
    healthy = _AgentStub(
        id=uuid4(),
        name="Healthy",
        status="online",
        last_seen_at=now,
    )

    assert _target_needs_wake(offline) is True
    assert _target_needs_wake(stale) is True
    assert _target_needs_wake(healthy) is False


@pytest.mark.asyncio
async def test_wake_chat_target_uses_controlled_wake_with_reset_session(
    monkeypatch: pytest.MonkeyPatch,
    actor_user: ActorContext,
) -> None:
    board = _BoardStub(id=uuid4())
    agent = _AgentStub(id=uuid4(), name="Frontend Specialist", status="offline")
    captured: dict[str, object] = {}

    async def _fake_require_gateway_config_for_board(self, _board):
        _ = self
        gateway = SimpleNamespace(id=uuid4(), url="ws://gateway.example/ws")
        return gateway, SimpleNamespace(url="ws://gateway.example/ws")

    async def _fake_resolve_existing_agent_auth_token_or_raise(**_kwargs: object) -> str:
        return "token-ok"

    async def _fake_run_lifecycle(self, **kwargs: object):
        _ = self
        captured.update(kwargs)
        return SimpleNamespace(status="online")

    monkeypatch.setattr(
        "app.api.board_memory.GatewayDispatchService.require_gateway_config_for_board",
        _fake_require_gateway_config_for_board,
    )
    monkeypatch.setattr(
        "app.api.board_memory.resolve_existing_agent_auth_token_or_raise",
        _fake_resolve_existing_agent_auth_token_or_raise,
    )
    monkeypatch.setattr(
        "app.api.board_memory.AgentLifecycleOrchestrator.run_lifecycle",
        _fake_run_lifecycle,
    )

    can_deliver = await _wake_chat_target_if_needed(
        session=object(),
        board=board,  # type: ignore[arg-type]
        agent=agent,  # type: ignore[arg-type]
        actor=actor_user,
    )

    assert can_deliver is False
    assert captured["wake"] is True
    assert captured["deliver_wakeup"] is True
    assert captured["reset_session"] is True
    assert captured["action"] == "update"


@pytest.mark.asyncio
async def test_notify_chat_targets_does_not_reuse_stale_session_after_controlled_wake(
    monkeypatch: pytest.MonkeyPatch,
    actor_user: ActorContext,
) -> None:
    board = _BoardStub(id=uuid4())
    stale = _AgentStub(
        id=uuid4(),
        name="Backend Specialist",
        status="offline",
        openclaw_session_id="agent:stale:backend",
    )
    memory = _MemoryStub(content="@backend wake now")
    send_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        "app.api.board_memory.Agent",
        SimpleNamespace(objects=SimpleNamespace(filter_by=lambda **_kwargs: _AgentQuery([stale]))),
    )
    monkeypatch.setattr(
        "app.api.board_memory.extract_mentions",
        lambda _content: {"backend"},
    )
    monkeypatch.setattr(
        "app.api.board_memory.matches_agent_mention",
        lambda _agent, _mentions: True,
    )

    async def _fake_optional_gateway_config_for_board(self, _board):
        _ = self
        return SimpleNamespace(url="ws://gateway.example/ws")

    async def _fake_wake_chat_target_if_needed(**_kwargs: object) -> bool:
        return False

    async def _fake_try_send_agent_message(self, **kwargs: object):
        _ = self
        send_calls.append(kwargs)
        return None

    monkeypatch.setattr(
        "app.api.board_memory.GatewayDispatchService.optional_gateway_config_for_board",
        _fake_optional_gateway_config_for_board,
    )
    monkeypatch.setattr(
        "app.api.board_memory._wake_chat_target_if_needed",
        _fake_wake_chat_target_if_needed,
    )
    monkeypatch.setattr(
        "app.api.board_memory.GatewayDispatchService.try_send_agent_message",
        _fake_try_send_agent_message,
    )

    await _notify_chat_targets(
        session=object(),
        board=board,  # type: ignore[arg-type]
        memory=memory,  # type: ignore[arg-type]
        actor=actor_user,
    )

    assert send_calls == []


@pytest.mark.asyncio
async def test_notify_chat_targets_healthy_agent_uses_existing_session_delivery(
    monkeypatch: pytest.MonkeyPatch,
    actor_user: ActorContext,
) -> None:
    board = _BoardStub(id=uuid4())
    healthy = _AgentStub(
        id=uuid4(),
        name="Frontend Specialist",
        status="online",
        openclaw_session_id="agent:frontend:session",
        last_seen_at=datetime.now(UTC).replace(tzinfo=None),
    )
    memory = _MemoryStub(content="@frontend please reply")
    send_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        "app.api.board_memory.Agent",
        SimpleNamespace(objects=SimpleNamespace(filter_by=lambda **_kwargs: _AgentQuery([healthy]))),
    )
    monkeypatch.setattr(
        "app.api.board_memory.extract_mentions",
        lambda _content: {"frontend"},
    )
    monkeypatch.setattr(
        "app.api.board_memory.matches_agent_mention",
        lambda _agent, _mentions: True,
    )

    async def _fake_optional_gateway_config_for_board(self, _board):
        _ = self
        return SimpleNamespace(url="ws://gateway.example/ws")

    async def _fake_try_send_agent_message(self, **kwargs: object):
        _ = self
        send_calls.append(kwargs)
        return None

    monkeypatch.setattr(
        "app.api.board_memory.GatewayDispatchService.optional_gateway_config_for_board",
        _fake_optional_gateway_config_for_board,
    )
    monkeypatch.setattr(
        "app.api.board_memory.GatewayDispatchService.try_send_agent_message",
        _fake_try_send_agent_message,
    )

    await _notify_chat_targets(
        session=object(),
        board=board,  # type: ignore[arg-type]
        memory=memory,  # type: ignore[arg-type]
        actor=actor_user,
    )

    assert len(send_calls) == 1
    assert send_calls[0]["session_key"] == "agent:frontend:session"
    assert send_calls[0]["deliver"] is True
