# ruff: noqa: INP001, SLF001
"""Tests for lifecycle auth stability: no implicit rotation, rollback on failure."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.core import agent_tokens
from app.core.config import settings
from app.services.openclaw import db_agent_state
from app.services.openclaw.lifecycle_orchestrator import _resolve_token_for_lifecycle

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


def test_update_does_not_change_token_version() -> None:
    secret = settings.agent_auth_secret or ("test-" + "a" * 40)
    agent = _make_agent(agent_token_version=5)
    token = db_agent_state.current_agent_runtime_token(agent)
    assert agent.agent_token_version == 5
    assert agent.pending_agent_token_version is None

    expected = agent_tokens.issue_signed_agent_token(agent_id=AGENT_ID, version=5, secret=secret)
    assert token == expected


def test_failed_provisioning_rolls_back_pending() -> None:
    agent = _make_agent(pending_agent_token_version=2, agent_token_version=1)
    db_agent_state.rollback_pending_token(agent, "provision failed")
    assert agent.pending_agent_token_version is None
    assert agent.agent_token_version == 1
    assert agent.agent_auth_last_error == "provision failed"


def test_resolve_token_with_explicit_auth_token() -> None:
    agent = _make_agent()
    result = _resolve_token_for_lifecycle(agent, "explicit-token")
    assert result == "explicit-token"


def test_resolve_token_with_pending_version() -> None:
    secret = settings.agent_auth_secret or ("test-" + "a" * 40)
    agent = _make_agent(pending_agent_token_version=2)
    result = _resolve_token_for_lifecycle(agent, None)
    expected = agent_tokens.issue_signed_agent_token(agent_id=AGENT_ID, version=2, secret=secret)
    assert result == expected


def test_resolve_token_for_signed_no_pending() -> None:
    secret = settings.agent_auth_secret or ("test-" + "a" * 40)
    agent = _make_agent(agent_token_version=3)
    result = _resolve_token_for_lifecycle(agent, None)
    expected = agent_tokens.issue_signed_agent_token(agent_id=AGENT_ID, version=3, secret=secret)
    assert result == expected


def test_resolve_token_fails_for_legacy_without_migration() -> None:
    agent = _make_agent(agent_auth_mode="legacy_hash", pending_agent_token_version=None)
    with pytest.raises(RuntimeError, match="begin_signed_migration"):
        _resolve_token_for_lifecycle(agent, None)
