# ruff: noqa: INP001, SLF001
"""Tests for staged auth rotation: active + pending dual acceptance."""

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
        "agent_auth_mode": "signed",
        "agent_token_version": 1,
        "pending_agent_token_version": None,
        "agent_token_hash": None,
        "agent_auth_last_synced_at": None,
        "agent_auth_last_error": None,
        "updated_at": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_begin_signed_rotation_increments_version() -> None:
    agent = _make_agent(agent_token_version=3)
    db_agent_state.begin_signed_rotation(agent)
    assert agent.pending_agent_token_version == 4


def test_backend_accepts_both_versions_during_rotation() -> None:
    secret = settings.agent_auth_secret or ("test-" + "a" * 40)
    agent = _make_agent(agent_token_version=1, pending_agent_token_version=2)

    active_token = agent_tokens.issue_signed_agent_token(agent_id=AGENT_ID, version=1, secret=secret)
    pending_token = agent_tokens.issue_signed_agent_token(agent_id=AGENT_ID, version=2, secret=secret)

    assert active_token != pending_token

    assert agent_tokens.verify_signed_agent_token(
        token=active_token, agent_id=AGENT_ID, version=1, secret=secret,
    )
    assert agent_tokens.verify_signed_agent_token(
        token=pending_token, agent_id=AGENT_ID, version=2, secret=secret,
    )


def test_promote_makes_pending_active() -> None:
    agent = _make_agent(agent_token_version=1, pending_agent_token_version=2)
    db_agent_state.promote_pending_token(agent)
    assert agent.agent_token_version == 2
    assert agent.pending_agent_token_version is None
    assert agent.agent_auth_mode == "signed"


def test_old_version_invalid_after_promote() -> None:
    secret = settings.agent_auth_secret or ("test-" + "a" * 40)
    agent = _make_agent(agent_token_version=1, pending_agent_token_version=2)

    old_token = agent_tokens.issue_signed_agent_token(agent_id=AGENT_ID, version=1, secret=secret)
    db_agent_state.promote_pending_token(agent)

    assert not agent_tokens.verify_signed_agent_token(
        token=old_token, agent_id=AGENT_ID, version=2, secret=secret,
    )
