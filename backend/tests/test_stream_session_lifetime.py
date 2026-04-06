from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sse_starlette.sse import EventSourceResponse

from app.api import agents as agents_api
from app.api import tasks as tasks_api
from app.services.openclaw import provisioning_db


class _SessionContext:
    def __init__(self, session: object) -> None:
        self.session = session
        self.entered = 0
        self.exited = 0

    async def __aenter__(self) -> object:
        self.entered += 1
        return self.session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        _ = (exc_type, exc, tb)
        self.exited += 1
        setattr(self.session, "closed", True)


class _DisconnectAfterOne:
    def __init__(self) -> None:
        self.calls = 0

    async def is_disconnected(self) -> bool:
        self.calls += 1
        return self.calls > 1


class _CapturedSSE:
    def __init__(self, iterator, *, ping: int) -> None:
        self.iterator = iterator
        self.ping = ping


@pytest.mark.asyncio
async def test_agent_stream_endpoint_resolves_access_with_short_lived_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = SimpleNamespace(closed=False)
    context = _SessionContext(session)
    response = object()
    ctx = SimpleNamespace(member=SimpleNamespace())

    class _FakeService:
        def __init__(self, bound_session: object) -> None:
            assert bound_session is session

        async def stream_agents(self, **kwargs: object) -> object:
            assert kwargs["ctx"] is ctx
            return response

    monkeypatch.setattr(agents_api, "async_session_maker", lambda: context)
    monkeypatch.setattr(agents_api, "get_auth_context", AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(agents_api, "require_org_member", AsyncMock(return_value=ctx))
    monkeypatch.setattr(agents_api, "require_org_admin", AsyncMock(return_value=ctx))
    monkeypatch.setattr(agents_api, "AgentLifecycleService", _FakeService)

    result = await agents_api.stream_agents(
        request=SimpleNamespace(),
        board_id=None,
        since=None,
    )

    assert result is response
    assert context.entered == 1
    assert context.exited == 1
    assert session.closed is True


@pytest.mark.asyncio
async def test_task_stream_endpoint_resolves_board_with_short_lived_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    board_id = uuid4()
    session = SimpleNamespace(closed=False)
    context = _SessionContext(session)
    actor = SimpleNamespace(actor_type="agent")
    board = SimpleNamespace(id=board_id)

    monkeypatch.setattr(tasks_api, "async_session_maker", lambda: context)
    monkeypatch.setattr(tasks_api, "require_user_or_agent", AsyncMock(return_value=actor))
    monkeypatch.setattr(tasks_api, "get_board_for_actor_read", AsyncMock(return_value=board))

    response = await tasks_api.stream_tasks(
        request=SimpleNamespace(),
        board_id=board_id,
        since=None,
    )

    assert isinstance(response, EventSourceResponse)
    assert context.entered == 1
    assert context.exited == 1
    assert session.closed is True


@pytest.mark.asyncio
async def test_lifecycle_stream_agents_computes_wake_reason_before_session_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    board_id = uuid4()
    agent = SimpleNamespace(
        id=uuid4(),
        board_id=board_id,
        updated_at=datetime(2026, 4, 6, 12, 0, tzinfo=UTC).replace(tzinfo=None),
        last_seen_at=None,
    )
    stream_session = SimpleNamespace(closed=False)
    context = _SessionContext(stream_session)
    ctx = SimpleNamespace(member=SimpleNamespace())

    async def _fake_fetch_agent_events(self, board_id_filter, last_seen):
        _ = (self, board_id_filter, last_seen)
        return [agent]

    def _fake_serialize_agent(self, value, *, wake_reason=None):
        _ = self
        return {"id": str(value.id), "wake_reason": wake_reason}

    async def _fake_get_work_snapshot(session, agent_id):
        assert session is stream_session
        assert getattr(session, "closed", False) is False
        assert agent_id == agent.id
        return {"wake_reason": "assigned_in_progress_task"}

    monkeypatch.setattr(provisioning_db, "EventSourceResponse", _CapturedSSE)
    monkeypatch.setattr(provisioning_db, "async_session_maker", lambda: context)
    monkeypatch.setattr(
        provisioning_db,
        "list_accessible_board_ids",
        AsyncMock(return_value=[board_id]),
    )
    monkeypatch.setattr(
        provisioning_db.AgentLifecycleService,
        "fetch_agent_events",
        _fake_fetch_agent_events,
    )
    monkeypatch.setattr(
        provisioning_db.AgentLifecycleService,
        "serialize_agent",
        _fake_serialize_agent,
    )
    monkeypatch.setattr(
        "app.services.agent_work.get_work_snapshot",
        _fake_get_work_snapshot,
    )

    service = provisioning_db.AgentLifecycleService(SimpleNamespace())
    service.logger = SimpleNamespace()
    response = await service.stream_agents(
        request=_DisconnectAfterOne(),
        board_id=board_id,
        since=None,
        ctx=ctx,
    )

    event = await anext(response.iterator)

    assert context.entered == 1
    assert context.exited == 1
    assert '"wake_reason": "assigned_in_progress_task"' in event["data"]
