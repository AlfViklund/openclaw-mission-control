from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.agents import Agent
from app.services.openclaw.lifecycle_orchestrator import AgentLifecycleOrchestrator
from app.services.openclaw.provisioning_db import AgentLifecycleService
from app.services.openclaw.gateway_rpc import OpenClawGatewayError


class _FakeSession:
    def add(self, _obj: object) -> None:
        return None

    async def exec(self, _statement: object) -> SimpleNamespace:
        return SimpleNamespace(first=lambda: None)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def refresh(self, _obj: object) -> None:
        return None


def _make_agent(*, status: str = "provisioning") -> Agent:
    return Agent(
        id=uuid4(),
        board_id=uuid4(),
        gateway_id=uuid4(),
        name="Developer - cardflow",
        status=status,
        agent_auth_mode="signed",
        agent_token_version=1,
    )


@pytest.mark.asyncio
async def test_lifecycle_gateway_error_marks_agent_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession()
    service = AgentLifecycleOrchestrator(session)  # type: ignore[arg-type]
    agent = _make_agent()
    gateway = SimpleNamespace(
        id=agent.gateway_id,
        organization_id=uuid4(),
        url="ws://gateway.example/ws",
    )
    board = SimpleNamespace(id=agent.board_id)

    async def _fake_lock_agent(*, agent_id: object) -> Agent:
        assert agent_id == agent.id
        return agent

    async def _fake_apply_agent_lifecycle(*_args: object, **_kwargs: object) -> None:
        raise OpenClawGatewayError("connection refused")

    monkeypatch.setattr(service, "_lock_agent", _fake_lock_agent)
    monkeypatch.setattr(
        "app.services.openclaw.lifecycle_orchestrator.OpenClawGatewayProvisioner.apply_agent_lifecycle",
        _fake_apply_agent_lifecycle,
    )

    result = await service.run_lifecycle(
        gateway=gateway,  # type: ignore[arg-type]
        agent_id=agent.id,
        board=board,  # type: ignore[arg-type]
        user=None,
        action="provision",
        auth_token="agt1-test",
        raise_gateway_errors=False,
    )

    assert result.status == "offline"
    assert result.last_provision_error == "connection refused"


def test_with_computed_status_marks_failed_unseen_agent_offline() -> None:
    service = AgentLifecycleService(_FakeSession())  # type: ignore[arg-type]
    agent = _make_agent()
    agent.last_provision_error = "[Errno 111] Connection refused"
    agent.last_seen_at = None

    computed = service.with_computed_status(agent)

    assert computed.status == "offline"
