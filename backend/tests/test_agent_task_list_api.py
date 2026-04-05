from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.api import agent as agent_api
from app.core.agent_auth import AgentAuthContext
from app.models.agents import Agent
from app.models.boards import Board


def _agent_ctx(*, board_id: UUID, is_board_lead: bool = False) -> AgentAuthContext:
    return AgentAuthContext(
        actor_type="agent",
        agent=Agent(
            id=uuid4(),
            board_id=board_id,
            gateway_id=uuid4(),
            name="Worker",
            is_board_lead=is_board_lead,
        ),
    )


@pytest.mark.asyncio
async def test_agent_list_tasks_passes_plain_none_since(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    board_id = uuid4()
    captured: dict[str, object] = {}

    async def _fake_list_tasks(**kwargs: object) -> object:
        captured.update(kwargs)
        return SimpleNamespace(items=[], total=0, limit=50, offset=0)

    monkeypatch.setattr(agent_api.tasks_api, "list_tasks", _fake_list_tasks)

    await agent_api.list_tasks(
        filters=agent_api.AgentTaskListFilters(),
        board=Board(id=board_id, organization_id=uuid4(), name="Board", slug="board"),
        session=object(),  # type: ignore[arg-type]
        agent_ctx=_agent_ctx(board_id=board_id),
    )

    assert captured["since"] is None


@pytest.mark.asyncio
async def test_agent_list_tasks_forwards_since_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    board_id = uuid4()
    since = datetime(2026, 4, 5, 12, 30, tzinfo=UTC)
    captured: dict[str, object] = {}

    async def _fake_list_tasks(**kwargs: object) -> object:
        captured.update(kwargs)
        return SimpleNamespace(items=[], total=0, limit=50, offset=0)

    monkeypatch.setattr(agent_api.tasks_api, "list_tasks", _fake_list_tasks)

    await agent_api.list_tasks(
        filters=agent_api.AgentTaskListFilters(since=since),
        board=Board(id=board_id, organization_id=uuid4(), name="Board", slug="board"),
        session=object(),  # type: ignore[arg-type]
        agent_ctx=_agent_ctx(board_id=board_id),
    )

    assert captured["since"] == since
