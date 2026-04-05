# ruff: noqa: INP001, SLF001
"""Tests for staged auth migration: legacy → signed via pending token."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.core import agent_tokens
from app.core.config import settings
from app.services.openclaw import db_agent_state

AGENT_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")


def _make_agent(**overrides: object) -> SimpleNamespace:
    defaults = {
        "id": AGENT_ID,
        "agent_auth_mode": "legacy_hash",
        "agent_token_version": 1,
        "pending_agent_token_version": None,
        "agent_token_hash": "pbkdf2_sha256$200000$abc$def",
        "agent_auth_last_synced_at": None,
        "agent_auth_last_error": None,
        "updated_at": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_begin_signed_migration_sets_pending() -> None:
    agent = _make_agent()
    db_agent_state.begin_signed_migration(agent)
    assert agent.pending_agent_token_version == 1


def test_begin_signed_migration_idempotent() -> None:
    agent = _make_agent(pending_agent_token_version=1)
    db_agent_state.begin_signed_migration(agent)
    assert agent.pending_agent_token_version == 1


def test_current_runtime_token_returns_pending_when_exists() -> None:
    original = settings.agent_auth_secret
    try:
        settings.agent_auth_secret = original or ("test-" + "a" * 40)
        agent = _make_agent(
            agent_auth_mode="legacy_hash",
            pending_agent_token_version=1,
        )
        token = db_agent_state.current_agent_runtime_token(agent)
        expected = agent_tokens.issue_signed_agent_token(
            agent_id=AGENT_ID, version=1, secret=settings.agent_auth_secret,
        )
        assert token == expected
    finally:
        settings.agent_auth_secret = original


def test_current_runtime_token_returns_active_for_signed() -> None:
    original = settings.agent_auth_secret
    try:
        settings.agent_auth_secret = original or ("test-" + "a" * 40)
        agent = _make_agent(
            agent_auth_mode="signed",
            agent_token_version=3,
            pending_agent_token_version=None,
        )
        token = db_agent_state.current_agent_runtime_token(agent)
        expected = agent_tokens.issue_signed_agent_token(
            agent_id=AGENT_ID, version=3, secret=settings.agent_auth_secret,
        )
        assert token == expected
    finally:
        settings.agent_auth_secret = original


def test_current_runtime_token_raises_for_legacy_no_pending() -> None:
    agent = _make_agent(
        agent_auth_mode="legacy_hash",
        pending_agent_token_version=None,
    )
    with pytest.raises(RuntimeError, match="begin_signed_migration"):
        db_agent_state.current_agent_runtime_token(agent)


def test_promote_pending_token() -> None:
    agent = _make_agent(pending_agent_token_version=1)
    db_agent_state.promote_pending_token(agent)
    assert agent.agent_token_version == 1
    assert agent.pending_agent_token_version is None
    assert agent.agent_auth_mode == "signed"
    assert agent.agent_token_hash is None
    assert agent.agent_auth_last_error is None


def test_promote_pending_noop_when_no_pending() -> None:
    agent = _make_agent(pending_agent_token_version=None, agent_token_version=5)
    db_agent_state.promote_pending_token(agent)
    assert agent.agent_token_version == 5
    assert agent.agent_auth_mode == "legacy_hash"


def test_rollback_pending_token() -> None:
    agent = _make_agent(pending_agent_token_version=1)
    db_agent_state.rollback_pending_token(agent, "test error")
    assert agent.pending_agent_token_version is None
    assert agent.agent_auth_last_error == "test error"


def test_legacy_token_invalid_after_promote() -> None:
    agent = _make_agent(pending_agent_token_version=1)
    db_agent_state.promote_pending_token(agent)
    legacy_token = agent_tokens.generate_agent_token()
    assert agent.agent_token_hash is None
    assert not agent_tokens.verify_agent_token(legacy_token, agent.agent_token_hash or "")
