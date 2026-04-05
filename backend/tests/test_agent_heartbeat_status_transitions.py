from __future__ import annotations

from uuid import uuid4

import pytest

from app.models.agents import Agent
from app.services.openclaw.provisioning_db import AgentLifecycleService


class _FakeSession:
    def add(self, _obj: object) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def refresh(self, _obj: object) -> None:
        return None


@pytest.mark.asyncio
async def test_commit_heartbeat_promotes_updating_agent_to_online(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = AgentLifecycleService(_FakeSession())  # type: ignore[arg-type]
    monkeypatch.setattr(service, "record_heartbeat", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(service, "to_agent_read", lambda agent: agent)
    monkeypatch.setattr(service, "with_computed_status", lambda agent: agent)

    agent = Agent(
        id=uuid4(),
        board_id=None,
        gateway_id=uuid4(),
        name="Primary gateway Gateway Agent",
        status="updating",
        agent_auth_mode="signed",
        agent_token_version=1,
    )

    result = await service.commit_heartbeat(agent=agent, status_value=None)

    assert result.status == "online"
    assert agent.wake_attempts == 0
    assert agent.checkin_deadline_at is None


@pytest.mark.asyncio
async def test_commit_heartbeat_keeps_explicit_status_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = AgentLifecycleService(_FakeSession())  # type: ignore[arg-type]
    monkeypatch.setattr(service, "record_heartbeat", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(service, "to_agent_read", lambda agent: agent)
    monkeypatch.setattr(service, "with_computed_status", lambda agent: agent)

    agent = Agent(
        id=uuid4(),
        board_id=None,
        gateway_id=uuid4(),
        name="Primary gateway Gateway Agent",
        status="updating",
        agent_auth_mode="signed",
        agent_token_version=1,
    )

    result = await service.commit_heartbeat(agent=agent, status_value="idle")

    assert result.status == "idle"
