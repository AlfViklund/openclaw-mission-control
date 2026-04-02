# ruff: noqa: S101
"""Tests for syncing board automation config to live agent runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest

from app.api import boards
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway


@dataclass
class _FakeSession:
    added: list[object] = field(default_factory=list)
    commits: int = 0

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_sync_automation_to_agents_updates_db_and_gateway_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    board_id = uuid4()
    gateway_id = uuid4()
    board = Board(
        id=board_id,
        organization_id=uuid4(),
        name="Platform",
        slug="platform",
        gateway_id=gateway_id,
        automation_config={
            "online_every_seconds": 120,
            "idle_every_seconds": 900,
            "wake_on_review": False,
            "allow_assist_mode": True,
        },
    )
    session = _FakeSession()
    agent_one = Agent(
        id=uuid4(),
        board_id=board_id,
        gateway_id=gateway_id,
        name="Worker 1",
        heartbeat_config={"every": "10m", "target": "last"},
    )
    agent_two = Agent(
        id=uuid4(),
        board_id=board_id,
        gateway_id=gateway_id,
        name="Worker 2",
        heartbeat_config={"every": "15m"},
    )
    gateway = Gateway(
        id=gateway_id,
        organization_id=board.organization_id,
        name="Main Gateway",
        url="wss://gateway.example/ws",
        workspace_root="/workspace",
    )
    sync_calls: list[dict[str, Any]] = []

    class _FakeAgentQuery:
        async def all(self, _session: object) -> list[Agent]:
            return [agent_one, agent_two]

    class _FakeAgentObjects:
        @staticmethod
        def filter(*_args: Any, **_kwargs: Any) -> _FakeAgentQuery:
            return _FakeAgentQuery()

    class _FakeGatewayQuery:
        async def first(self, _session: object) -> Gateway | None:
            return gateway

    class _FakeGatewayObjects:
        @staticmethod
        def by_id(*_args: Any, **_kwargs: Any) -> _FakeGatewayQuery:
            return _FakeGatewayQuery()

    async def _fake_sync(
        self: boards.OpenClawGatewayProvisioner,
        target_gateway: Gateway,
        agents: list[Agent],
    ) -> None:
        _ = self
        sync_calls.append(
            {
                "gateway_id": target_gateway.id,
                "workspace_root": target_gateway.workspace_root,
                "heartbeat_configs": [dict(agent.heartbeat_config or {}) for agent in agents],
            },
        )

    monkeypatch.setattr(boards.Agent, "objects", _FakeAgentObjects())
    monkeypatch.setattr(boards.Gateway, "objects", _FakeGatewayObjects())
    monkeypatch.setattr(
        boards.OpenClawGatewayProvisioner,
        "sync_gateway_agent_heartbeats",
        _fake_sync,
    )

    await boards._sync_automation_to_agents(session, board)

    assert session.commits == 1
    assert len(session.added) == 2
    assert agent_one.heartbeat_config == {
        "every": "10m",
        "target": "last",
        "online_every_seconds": 120,
        "idle_every_seconds": 900,
        "wake_on_review": False,
        "allow_assist_mode": True,
    }
    assert agent_two.heartbeat_config == {
        "every": "15m",
        "online_every_seconds": 120,
        "idle_every_seconds": 900,
        "wake_on_review": False,
        "allow_assist_mode": True,
    }
    assert len(sync_calls) == 1
    assert sync_calls[0]["gateway_id"] == gateway_id
    assert sync_calls[0]["workspace_root"] == "/workspace"
    assert sync_calls[0]["heartbeat_configs"][0]["online_every_seconds"] == 120
