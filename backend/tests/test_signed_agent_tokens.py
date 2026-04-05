# ruff: noqa: INP001, SLF001
"""Tests for deterministic signed agent token engine."""

from __future__ import annotations

import uuid

import pytest

from app.core import agent_tokens

SECRET = "test-signing-secret-" + "a" * 40
AGENT_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")


def test_signed_token_is_deterministic() -> None:
    t1 = agent_tokens.issue_signed_agent_token(agent_id=AGENT_ID, version=1, secret=SECRET)
    t2 = agent_tokens.issue_signed_agent_token(agent_id=AGENT_ID, version=1, secret=SECRET)
    assert t1 == t2


def test_signed_token_format() -> None:
    token = agent_tokens.issue_signed_agent_token(agent_id=AGENT_ID, version=1, secret=SECRET)
    parts = token.split(".")
    assert len(parts) == 4
    assert parts[0] == "agt1"
    assert parts[1] == str(AGENT_ID).lower()
    assert parts[2] == "1"
    assert len(parts[3]) > 0


def test_different_version_gives_different_token() -> None:
    t1 = agent_tokens.issue_signed_agent_token(agent_id=AGENT_ID, version=1, secret=SECRET)
    t2 = agent_tokens.issue_signed_agent_token(agent_id=AGENT_ID, version=2, secret=SECRET)
    assert t1 != t2


def test_wrong_secret_invalid() -> None:
    token = agent_tokens.issue_signed_agent_token(agent_id=AGENT_ID, version=1, secret=SECRET)
    assert not agent_tokens.verify_signed_agent_token(
        token=token,
        agent_id=AGENT_ID,
        version=1,
        secret="wrong-secret-" + "b" * 40,
    )


def test_wrong_agent_id_invalid() -> None:
    token = agent_tokens.issue_signed_agent_token(agent_id=AGENT_ID, version=1, secret=SECRET)
    other_id = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    assert not agent_tokens.verify_signed_agent_token(
        token=token,
        agent_id=other_id,
        version=1,
        secret=SECRET,
    )


def test_wrong_version_invalid() -> None:
    token = agent_tokens.issue_signed_agent_token(agent_id=AGENT_ID, version=1, secret=SECRET)
    assert not agent_tokens.verify_signed_agent_token(
        token=token,
        agent_id=AGENT_ID,
        version=2,
        secret=SECRET,
    )


def test_tampered_signature_invalid() -> None:
    token = agent_tokens.issue_signed_agent_token(agent_id=AGENT_ID, version=1, secret=SECRET)
    parts = token.split(".")
    parts[3] = "TAMPERED"
    tampered = ".".join(parts)
    assert not agent_tokens.verify_signed_agent_token(
        token=tampered,
        agent_id=AGENT_ID,
        version=1,
        secret=SECRET,
    )


def test_parse_signed_token_success() -> None:
    token = agent_tokens.issue_signed_agent_token(agent_id=AGENT_ID, version=1, secret=SECRET)
    parsed = agent_tokens.parse_signed_agent_token(token)
    assert parsed is not None
    assert parsed.agent_id == AGENT_ID
    assert parsed.version == 1


def test_parse_invalid_format_returns_none() -> None:
    assert agent_tokens.parse_signed_agent_token("not-a-signed-token") is None
    assert agent_tokens.parse_signed_agent_token("agt1.bad-version.1.sig") is None
    assert agent_tokens.parse_signed_agent_token("agt2.11111111-2222-3333-4444-555555555555.1.sig") is None


def test_valid_token_roundtrip() -> None:
    token = agent_tokens.issue_signed_agent_token(agent_id=AGENT_ID, version=3, secret=SECRET)
    assert agent_tokens.verify_signed_agent_token(
        token=token,
        agent_id=AGENT_ID,
        version=3,
        secret=SECRET,
    )


def test_legacy_token_still_works() -> None:
    raw = agent_tokens.generate_agent_token()
    hashed = agent_tokens.hash_agent_token(raw)
    assert agent_tokens.verify_agent_token(raw, hashed)
    assert not agent_tokens.verify_agent_token("wrong-token", hashed)
