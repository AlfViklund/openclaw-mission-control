# ruff: noqa: S101
"""Tests for backend-computed agent wake reasons."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import pytest

from app.models.agents import Agent
from app.services import agent_work
from app.services.openclaw.provisioning_db import AgentLifecycleService


@dataclass
class _FakeSession:
    pass


@pytest.mark.asyncio
async def test_get_board_wake_reasons_uses_snapshot_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    board_id = uuid4()
    agent_one = Agent(id=uuid4(), board_id=board_id, gateway_id=uuid4(), name="Lead")
    agent_two = Agent(id=uuid4(), board_id=board_id, gateway_id=uuid4(), name="Worker")

    async def _fake_snapshot(session: object, agent_id: object) -> dict:
        _ = session
        return {
            str(agent_one.id): {"wake_reason": "pending_approval"},
            str(agent_two.id): {"reason": "busy_existing_run"},
        }[str(agent_id)]

    monkeypatch.setattr(agent_work, "get_work_snapshot", _fake_snapshot)

    reasons = await agent_work.get_board_wake_reasons(
        _FakeSession(),  # type: ignore[arg-type]
        board_id,
        agents=[agent_one, agent_two],
    )

    assert reasons == {
        str(agent_one.id): "pending_approval",
        str(agent_two.id): "busy_existing_run",
    }


def test_agent_read_can_carry_wake_reason() -> None:
    agent = Agent(
        id=uuid4(),
        board_id=uuid4(),
        gateway_id=uuid4(),
        name="Worker",
        status="idle",
    )

    read = AgentLifecycleService.to_agent_read(agent, wake_reason="idle_no_work")

    assert read.wake_reason == "idle_no_work"
    assert read.is_gateway_main is False
