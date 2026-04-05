from __future__ import annotations

import json

import pytest

import app.services.openclaw.provisioning as agent_provisioning


def test_gateway_heartbeat_payload_filters_internal_policy_keys() -> None:
    payload = agent_provisioning._gateway_heartbeat_payload(
        {
            "every": "5m",
            "target": "last",
            "includeReasoning": False,
            "online_every_seconds": 300,
            "idle_every_seconds": 1800,
            "dormant_every_seconds": 21600,
            "wake_on_approvals": True,
            "wake_on_review": True,
            "allow_assist_mode": False,
        },
    )

    assert payload == {
        "every": "5m",
        "target": "last",
        "includeReasoning": False,
    }


@pytest.mark.asyncio
async def test_patch_agent_heartbeats_sends_sanitized_gateway_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_raw: list[str] = []

    async def _fake_openclaw_call(method, params=None, config=None):
        _ = config
        if method == "config.get":
            return {"hash": None, "config": {"agents": {"list": []}}}
        if method == "config.patch":
            captured_raw.append(params["raw"])
            return {"ok": True}
        raise AssertionError(f"Unexpected method: {method}")

    monkeypatch.setattr(agent_provisioning, "openclaw_call", _fake_openclaw_call)

    cp = agent_provisioning.OpenClawGatewayControlPlane(
        agent_provisioning.GatewayClientConfig(url="ws://gateway.example/ws", token=None),
    )
    await cp.patch_agent_heartbeats(
        [
            (
                "lead-agent",
                "/tmp/workspace-lead-agent",
                {
                    "every": "5m",
                    "target": "last",
                    "includeReasoning": False,
                    "online_every_seconds": 300,
                    "idle_every_seconds": 1800,
                    "wake_on_approvals": True,
                },
            ),
        ],
    )

    patch = json.loads(captured_raw[0])
    heartbeat = patch["agents"]["list"][0]["heartbeat"]
    assert heartbeat == {
        "every": "5m",
        "target": "last",
        "includeReasoning": False,
    }
