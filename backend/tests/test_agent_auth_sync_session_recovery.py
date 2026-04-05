from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest

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
