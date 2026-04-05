# ruff: noqa: INP001, SLF001
"""Tests for repair vs rotate separation."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.services.openclaw import db_agent_state

AGENT_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")


def _make_agent(**overrides: object) -> SimpleNamespace:
    defaults = {
        "id": AGENT_ID,
        "agent_auth_mode": "signed",
        "agent_token_version": 3,
        "pending_agent_token_version": None,
        "agent_token_hash": None,
        "agent_auth_last_synced_at": None,
        "agent_auth_last_error": None,
        "updated_at": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_repair_signed_rolls_back_pending() -> None:
    agent = _make_agent(pending_agent_token_version=5)
    db_agent_state.rollback_pending_token(agent, "repair: reverting to active token")
    assert agent.pending_agent_token_version is None
    assert agent.agent_token_version == 3
    assert agent.agent_auth_last_error == "repair: reverting to active token"


def test_repair_signed_does_not_bump_version() -> None:
    agent = _make_agent(agent_token_version=3, pending_agent_token_version=None)
    db_agent_state.rollback_pending_token(agent, "repair: reverting to active token")
    assert agent.agent_token_version == 3
    assert agent.pending_agent_token_version is None


def test_repair_legacy_rolls_back_then_starts_migration() -> None:
    agent = _make_agent(
        agent_auth_mode="legacy_hash",
        pending_agent_token_version=99,
        agent_token_hash="pbkdf2_hash",
    )
    db_agent_state.rollback_pending_token(agent, "repair: starting fresh migration")
    assert agent.pending_agent_token_version is None

    db_agent_state.begin_signed_migration(agent)
    assert agent.pending_agent_token_version == 1


def test_rotate_bumps_version() -> None:
    agent = _make_agent(agent_token_version=3)
    db_agent_state.begin_signed_rotation(agent)
    assert agent.pending_agent_token_version == 4
    assert agent.agent_token_version == 3


def test_repair_legacy_idempotent_migration() -> None:
    agent = _make_agent(agent_auth_mode="legacy_hash", pending_agent_token_version=None)
    db_agent_state.begin_signed_migration(agent)
    assert agent.pending_agent_token_version == 1
    db_agent_state.begin_signed_migration(agent)
    assert agent.pending_agent_token_version == 1
