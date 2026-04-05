# ruff: noqa: INP001, SLF001
"""Tests for signed agent auth lookup — O(1) by agent_id + legacy fallback."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core import agent_auth, agent_tokens
from app.core.agent_auth import AgentAuthContext

SECRET = "test-signing-secret-" + "a" * 40
AGENT_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")


def _make_agent(**overrides: object) -> SimpleNamespace:
    defaults = {
        "id": AGENT_ID,
        "agent_auth_mode": "signed",
        "agent_token_version": 1,
        "pending_agent_token_version": None,
        "agent_token_hash": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.mark.asyncio
async def test_signed_token_lookup_by_agent_id(monkeypatch: pytest.MonkeyPatch) -> None:
    token = agent_tokens.issue_signed_agent_token(agent_id=AGENT_ID, version=1, secret=SECRET)
    agent = _make_agent()

    monkeypatch.setattr(agent_tokens, "issue_signed_agent_token", lambda **kw: token if kw["agent_id"] == AGENT_ID and kw["version"] == 1 and kw["secret"] == SECRET else "other")
    monkeypatch.setattr(agent_auth, "settings", SimpleNamespace(agent_auth_secret=SECRET))

    class _FakeSession:
        async def exec(self, stmt):
            return _FakeResult(agent)

    class _FakeResult:
        def __init__(self, val):
            self._val = val
        def first(self):
            return self._val

    ctx = await agent_auth._find_agent_for_token(_FakeSession(), token)
    assert ctx is not None
    assert ctx.auth_variant == "signed_active"
    assert ctx.token_version == 1


@pytest.mark.asyncio
async def test_signed_pending_token_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    pending_token = agent_tokens.issue_signed_agent_token(agent_id=AGENT_ID, version=2, secret=SECRET)
    agent = _make_agent(
        agent_token_version=1,
        pending_agent_token_version=2,
    )

    def _fake_issue(*, agent_id, version, secret):
        return agent_tokens.issue_signed_agent_token.__wrapped__(agent_id=agent_id, version=version, secret=secret)

    monkeypatch.setattr(agent_auth, "settings", SimpleNamespace(agent_auth_secret=SECRET))

    class _FakeSession:
        async def exec(self, stmt):
            return _FakeResult(agent)

    class _FakeResult:
        def __init__(self, val):
            self._val = val
        def first(self):
            return self._val

    ctx = await agent_auth._find_agent_for_token(_FakeSession(), pending_token)
    assert ctx is not None
    assert ctx.auth_variant == "signed_pending"
    assert ctx.token_version == 2


@pytest.mark.asyncio
async def test_legacy_fallback_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    raw_token = agent_tokens.generate_agent_token()
    hashed = agent_tokens.hash_agent_token(raw_token)
    agent = _make_agent(
        agent_auth_mode="legacy_hash",
        agent_token_hash=hashed,
    )

    monkeypatch.setattr(agent_auth, "settings", SimpleNamespace(agent_auth_secret=SECRET))

    class _FakeSession:
        async def exec(self, stmt):
            return _FakeResult([agent])

    class _FakeResult:
        def __init__(self, val):
            self._val = val
        def all(self):
            return self._val

    ctx = await agent_auth._find_agent_for_token(_FakeSession(), raw_token)
    assert ctx is not None
    assert ctx.auth_variant == "legacy"


@pytest.mark.asyncio
async def test_unknown_agent_id_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    other_id = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    token = agent_tokens.issue_signed_agent_token(agent_id=other_id, version=1, secret=SECRET)
    monkeypatch.setattr(agent_auth, "settings", SimpleNamespace(agent_auth_secret=SECRET))

    class _FakeSession:
        async def exec(self, stmt):
            return _FakeResult(None)

    class _FakeResult:
        def __init__(self, val):
            self._val = val
        def first(self):
            return self._val

    ctx = await agent_auth._find_agent_for_token(_FakeSession(), token)
    assert ctx is None
