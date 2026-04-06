from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.api import agents as agents_api


@pytest.mark.asyncio
async def test_repaired_gateway_main_session_is_reset_and_woken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []

    async def _fake_openclaw_call(method: str, payload: dict[str, object], *, config: object) -> None:
        calls.append(("reset", method, payload["key"], config))

    async def _fake_ensure_session(session_key: str, *, config: object, label: str | None = None) -> None:
        calls.append(("ensure", session_key, label, config))

    async def _fake_send_message(
        message: str,
        *,
        session_key: str,
        config: object,
        deliver: bool,
    ) -> None:
        calls.append(("send", session_key, deliver, config, message))

    monkeypatch.setattr("app.services.openclaw.gateway_rpc.openclaw_call", _fake_openclaw_call)
    monkeypatch.setattr("app.services.openclaw.gateway_rpc.ensure_session", _fake_ensure_session)
    monkeypatch.setattr("app.services.openclaw.gateway_rpc.send_message", _fake_send_message)

    gateway = SimpleNamespace(
        id=UUID("13f973c6-7f8c-40ee-8398-5f2a14a97687"),
        url="http://127.0.0.1:18789",
        token="gateway-token",
        allow_insecure_tls=False,
        disable_device_pairing=False,
    )
    agent = SimpleNamespace(
        id=UUID("44528167-e615-42c0-9db4-4be88b323429"),
        board_id=None,
        gateway_id=gateway.id,
        name="Primary gateway Gateway Agent",
        openclaw_session_id="agent:mc-gateway-13f973c6-7f8c-40ee-8398-5f2a14a97687:main",
    )

    await agents_api._reset_and_wake_repaired_agent_session(agent=agent, gateway=gateway)

    assert calls[0][:3] == (
        "reset",
        "sessions.reset",
        "agent:mc-gateway-13f973c6-7f8c-40ee-8398-5f2a14a97687:main",
    )
    assert calls[1][:3] == (
        "ensure",
        "agent:mc-gateway-13f973c6-7f8c-40ee-8398-5f2a14a97687:main",
        "Primary gateway Gateway Agent",
    )
    assert calls[2][:3] == (
        "send",
        "agent:mc-gateway-13f973c6-7f8c-40ee-8398-5f2a14a97687:main",
        True,
    )
    assert "read AGENTS.md" in calls[2][4]


def test_prepare_agent_for_auth_repair_preserves_signed_rotation_state_without_auth_error() -> None:
    agent = SimpleNamespace(
        agent_auth_mode="signed",
        pending_agent_token_version=4,
        agent_auth_last_error="old error",
        last_provision_error="old provisioning error",
        heartbeat_config=None,
        updated_at=None,
    )

    agents_api._prepare_agent_for_auth_repair(agent)

    assert agent.pending_agent_token_version is None
    assert agent.agent_auth_last_error is None
    assert agent.last_provision_error is None
    assert isinstance(agent.heartbeat_config, dict)


def test_record_repair_session_failure_keeps_pending_token_and_uses_provision_error() -> None:
    agent = SimpleNamespace(
        status="online",
        pending_agent_token_version=1,
        agent_auth_last_error=None,
        last_provision_error=None,
        updated_at=None,
    )

    agents_api._record_repair_session_failure(agent, "[Errno 111] Connection refused")

    assert agent.status == "offline"
    assert agent.pending_agent_token_version == 1
    assert agent.agent_auth_last_error is None
    assert agent.last_provision_error == "[Errno 111] Connection refused"


def test_mark_repair_wake_dispatched_tracks_checkin_deadline() -> None:
    agent = SimpleNamespace(
        status="idle",
        wake_attempts=1,
        checkin_deadline_at=None,
        last_wake_sent_at=None,
        updated_at=None,
    )

    deadline = agents_api._mark_repair_wake_dispatched(agent)

    assert agent.status == "online"
    assert agent.wake_attempts == 2
    assert agent.last_wake_sent_at is not None
    assert agent.checkin_deadline_at == deadline
    assert deadline > agent.last_wake_sent_at


class _FakeSession:
    def add(self, _obj: object) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def refresh(self, _obj: object) -> None:
        return None


@pytest.mark.asyncio
async def test_repair_agent_templates_with_retry_serializes_and_retries_gateway_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = SimpleNamespace(
        id=UUID("44528167-e615-42c0-9db4-4be88b323429"),
        agent_auth_mode="legacy_hash",
        pending_agent_token_version=None,
        agent_auth_last_error=None,
        last_provision_error=None,
        heartbeat_config=None,
        updated_at=None,
    )
    gateway = SimpleNamespace(id=UUID("13f973c6-7f8c-40ee-8398-5f2a14a97687"))
    board = SimpleNamespace(id=UUID("2f5f2d8d-9236-4df7-a680-e2b6d3b0e851"))
    calls: list[dict[str, object]] = []
    sleeps: list[float] = []

    async def _fake_repair_agent_templates(
        *,
        session: object,
        agent: object,
        gateway: object,
        board: object,
        auth_token: str,
    ) -> object:
        calls.append(
            {
                "session": session,
                "agent": agent,
                "gateway": gateway,
                "board": board,
                "auth_token": auth_token,
            }
        )
        if len(calls) == 1:
            raise HTTPException(
                status_code=502,
                detail="Gateway update failed: rate limit exceeded for config.patch; retry after 1s",
            )
        return agent

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(agents_api, "_repair_agent_templates", _fake_repair_agent_templates)
    monkeypatch.setattr(agents_api.asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr(
        "app.services.openclaw.db_agent_state.current_agent_runtime_token",
        lambda current_agent: f"token-v{current_agent.pending_agent_token_version or current_agent.agent_auth_mode}",
    )

    result = await agents_api._repair_agent_templates_with_retry(
        session=_FakeSession(),  # type: ignore[arg-type]
        agent=agent,
        gateway=gateway,
        board=board,
    )

    assert result is agent
    assert len(calls) == 2
    assert calls[0]["board"] is board
    assert sleeps == [1.0]
