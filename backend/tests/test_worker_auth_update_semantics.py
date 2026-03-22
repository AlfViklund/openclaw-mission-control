# ruff: noqa: S101
from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core.agent_tokens import hash_agent_token
from app.schemas.gateways import GatewayTemplatesSyncResult
from app.services.openclaw.gateway_rpc import OpenClawGatewayError
from app.services.openclaw.lifecycle_orchestrator import AgentLifecycleOrchestrator
from app.services.openclaw.provisioning_db import (
    AgentLifecycleService,
    _resolve_agent_auth_token,
    resolve_existing_agent_auth_token_or_raise,
)


@dataclass
class _FakeSession:
    committed: int = 0
    flushed: int = 0
    added: list[object] = field(default_factory=list)

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flushed += 1

    async def commit(self) -> None:
        self.committed += 1

    async def refresh(self, _value: object) -> None:
        return None


@dataclass
class _AgentStub:
    id: object
    name: str = 'Worker'
    gateway_id: object | None = None
    board_id: object | None = None
    lifecycle_generation: int = 0
    last_provision_error: str | None = None
    status: str = 'offline'
    checkin_deadline_at: object | None = None
    wake_attempts: int = 0
    last_wake_sent_at: object | None = None
    updated_at: object | None = None
    last_seen_at: object | None = None
    openclaw_session_id: str | None = None
    agent_token_hash: str | None = None
    provision_confirm_token_hash: str | None = None
    heartbeat_config: dict[str, object] | None = None


@pytest.mark.asyncio
async def test_create_lifecycle_mints_token_and_marks_online(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession()
    service = AgentLifecycleOrchestrator(session)  # type: ignore[arg-type]
    agent = _AgentStub(id=uuid4(), gateway_id=uuid4(), board_id=uuid4())
    captured: dict[str, object] = {}

    async def _fake_lock_agent(self, *, agent_id: object) -> _AgentStub:
        _ = (self, agent_id)
        return agent

    async def _fake_apply(self, **kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(AgentLifecycleOrchestrator, '_lock_agent', _fake_lock_agent)
    monkeypatch.setattr(
        'app.services.openclaw.lifecycle_orchestrator.OpenClawGatewayProvisioner.apply_agent_lifecycle',
        _fake_apply,
    )
    monkeypatch.setattr(
        'app.services.openclaw.lifecycle_orchestrator.enqueue_lifecycle_reconcile',
        lambda *_args, **_kwargs: None,
    )

    gateway = SimpleNamespace(id=uuid4(), url='ws://gateway.example/ws', organization_id=uuid4())

    async def _fake_get_org_owner_user(*_args: object, **_kwargs: object) -> object:
        return SimpleNamespace(id=uuid4())

    monkeypatch.setattr(
        'app.services.openclaw.lifecycle_orchestrator.get_org_owner_user',
        _fake_get_org_owner_user,
    )
    out = await service.run_lifecycle(
        gateway=gateway,
        agent_id=agent.id,
        board=None,
        user=None,
        action='create',
        auth_token=None,
        wake=False,
        deliver_wakeup=False,
    )

    assert out.status == 'online'
    assert isinstance(captured.get('auth_token'), str)
    assert captured.get('action') == 'create'


@pytest.mark.asyncio
async def test_update_lifecycle_requires_explicit_token(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession()
    service = AgentLifecycleOrchestrator(session)  # type: ignore[arg-type]
    agent = _AgentStub(id=uuid4(), gateway_id=uuid4(), board_id=uuid4())

    async def _fake_lock_agent(self, *, agent_id: object) -> _AgentStub:
        _ = (self, agent_id)
        return agent

    monkeypatch.setattr(AgentLifecycleOrchestrator, '_lock_agent', _fake_lock_agent)

    gateway = SimpleNamespace(id=uuid4(), url='ws://gateway.example/ws')
    with pytest.raises(HTTPException) as exc_info:
        await service.run_lifecycle(
            gateway=gateway,
            agent_id=agent.id,
            board=SimpleNamespace(id=uuid4()),
            user=None,
            action='update',
            auth_token=None,
            wake=False,
            deliver_wakeup=False,
        )

    assert exc_info.value.status_code == 409
    assert 'Implicit token rotation' in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_update_lifecycle_preserves_explicit_token(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession()
    service = AgentLifecycleOrchestrator(session)  # type: ignore[arg-type]
    agent = _AgentStub(id=uuid4(), gateway_id=uuid4(), board_id=uuid4())
    captured: dict[str, object] = {}

    async def _fake_lock_agent(self, *, agent_id: object) -> _AgentStub:
        _ = (self, agent_id)
        return agent

    async def _fake_apply(self, **kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(AgentLifecycleOrchestrator, '_lock_agent', _fake_lock_agent)
    monkeypatch.setattr(
        'app.services.openclaw.lifecycle_orchestrator.OpenClawGatewayProvisioner.apply_agent_lifecycle',
        _fake_apply,
    )
    monkeypatch.setattr(
        'app.services.openclaw.lifecycle_orchestrator.enqueue_lifecycle_reconcile',
        lambda *_args, **_kwargs: None,
    )

    gateway = SimpleNamespace(id=uuid4(), url='ws://gateway.example/ws')
    await service.run_lifecycle(
        gateway=gateway,
        agent_id=agent.id,
        board=SimpleNamespace(id=uuid4()),
        user=None,
        action='update',
        auth_token='existing-token',
        wake=False,
        deliver_wakeup=False,
    )

    assert captured.get('auth_token') == 'existing-token'
    assert captured.get('action') == 'update'


@pytest.mark.asyncio
async def test_resolve_existing_agent_auth_token_or_raise_fails_closed_on_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession()
    service = AgentLifecycleService(session)  # type: ignore[arg-type]
    agent = _AgentStub(
        id=uuid4(),
        gateway_id=uuid4(),
        board_id=uuid4(),
        agent_token_hash=hash_agent_token('good-token'),
    )
    gateway = SimpleNamespace(
        id=uuid4(),
        url='ws://gateway.example/ws',
        token=None,
        allow_insecure_tls=False,
        disable_device_pairing=False,
    )

    async def _fake_get_existing_auth_token(**_kwargs: object) -> str:
        return 'bad-token'

    monkeypatch.setattr(
        'app.services.openclaw.provisioning_db._get_existing_auth_token',
        _fake_get_existing_auth_token,
    )

    with pytest.raises(HTTPException) as exc_info:
        await resolve_existing_agent_auth_token_or_raise(
            session=session,  # type: ignore[arg-type]
            agent=agent,  # type: ignore[arg-type]
            gateway=gateway,  # type: ignore[arg-type]
            timeout_context='test',
        )

    assert exc_info.value.status_code == 409
    assert 'AUTH_TOKEN drift detected' in str(exc_info.value.detail)
    assert session.committed == 1
    assert agent.last_provision_error is not None


@pytest.mark.asyncio
async def test_explicit_rotate_path_still_rekeys_when_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession()
    agent = _AgentStub(id=uuid4(), agent_token_hash=hash_agent_token('good-token'))
    board = SimpleNamespace(id=uuid4())
    ctx = SimpleNamespace(
        session=session,
        control_plane=object(),
        backoff=None,
        options=SimpleNamespace(rotate_tokens=True),
    )
    result = GatewayTemplatesSyncResult(
        gateway_id=uuid4(),
        include_main=False,
        reset_sessions=False,
        agents_updated=0,
        agents_skipped=0,
        main_updated=False,
        errors=[],
    )

    async def _fake_get_existing_auth_token(**_kwargs: object) -> str:
        return 'bad-token'

    async def _fake_rotate_agent_token(_session: object, _agent: object) -> str:
        return 'new-token'

    monkeypatch.setattr(
        'app.services.openclaw.provisioning_db._get_existing_auth_token',
        _fake_get_existing_auth_token,
    )
    monkeypatch.setattr(
        'app.services.openclaw.provisioning_db._rotate_agent_token',
        _fake_rotate_agent_token,
    )

    token, fatal = await _resolve_agent_auth_token(
        ctx,
        result,
        agent,  # type: ignore[arg-type]
        board,  # type: ignore[arg-type]
        agent_gateway_id='agent:test',
    )

    assert fatal is False
    assert token == 'new-token'


@pytest.mark.asyncio
async def test_update_failure_does_not_mark_agent_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession()
    service = AgentLifecycleOrchestrator(session)  # type: ignore[arg-type]
    agent = _AgentStub(id=uuid4(), gateway_id=uuid4(), board_id=uuid4())

    async def _fake_lock_agent(self, *, agent_id: object) -> _AgentStub:
        _ = (self, agent_id)
        return agent

    async def _fake_apply(self, **_kwargs: object) -> None:
        raise OpenClawGatewayError('pairing required')

    monkeypatch.setattr(AgentLifecycleOrchestrator, '_lock_agent', _fake_lock_agent)
    monkeypatch.setattr(
        'app.services.openclaw.lifecycle_orchestrator.OpenClawGatewayProvisioner.apply_agent_lifecycle',
        _fake_apply,
    )

    gateway = SimpleNamespace(id=uuid4(), url='ws://gateway.example/ws')
    with pytest.raises(HTTPException) as exc_info:
        await service.run_lifecycle(
            gateway=gateway,
            agent_id=agent.id,
            board=SimpleNamespace(id=uuid4()),
            user=None,
            action='update',
            auth_token='existing-token',
            wake=False,
            deliver_wakeup=False,
        )

    assert exc_info.value.status_code == 502
    assert agent.status != 'online'
    assert agent.last_provision_error == 'pairing required'
