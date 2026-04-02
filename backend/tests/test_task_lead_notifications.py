# ruff: noqa: S101
"""Tests for lead task notifications using canonical agent sends."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

import pytest

from app.api import tasks as tasks_api
from app.models.agents import Agent
from app.models.boards import Board
from app.models.tasks import Task


@dataclass
class _FakeSession:
    added: list[object] = field(default_factory=list)
    commits: int = 0

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.commits += 1


def _lead_agent(board_id, gateway_id) -> Agent:
    return Agent(
        id=uuid4(),
        board_id=board_id,
        gateway_id=gateway_id,
        name="Lead Agent",
        openclaw_session_id="stale-session-key",
        is_board_lead=True,
    )


def _board() -> Board:
    return Board(
        id=uuid4(),
        organization_id=uuid4(),
        name="Platform",
        slug="platform",
        gateway_id=uuid4(),
    )


def _task(board_id) -> Task:
    return Task(id=uuid4(), board_id=board_id, title="Ship it", status="inbox")


class _LeadQuery:
    def __init__(self, lead: Agent) -> None:
        self._lead = lead

    def filter(self, *_args, **_kwargs):
        return self

    async def first(self, _session):
        return self._lead


class _LeadObjects:
    def __init__(self, lead: Agent) -> None:
        self._lead = lead

    def filter_by(self, *_args, **_kwargs):
        return _LeadQuery(self._lead)


@pytest.mark.asyncio
async def test_notify_lead_on_task_create_uses_canonical_agent_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    board = _board()
    task = _task(board.id)
    lead = _lead_agent(board.id, board.gateway_id)
    session = _FakeSession()
    calls: list[dict] = []

    async def _fake_try_send_to_agent(self, *, agent: Agent, message: str, deliver: bool = False):
        _ = self
        calls.append({"agent_id": agent.id, "message": message, "deliver": deliver})
        return None

    monkeypatch.setattr(tasks_api.Agent, "objects", _LeadObjects(lead))
    monkeypatch.setattr(tasks_api.GatewayDispatchService, "try_send_to_agent", _fake_try_send_to_agent)

    await tasks_api._notify_lead_on_task_create(session=session, board=board, task=task)  # type: ignore[arg-type]

    assert session.commits == 1
    assert len(calls) == 1
    assert calls[0]["agent_id"] == lead.id
    assert "NEW TASK ADDED" in calls[0]["message"]
    assert "Ship it" in calls[0]["message"]


@pytest.mark.asyncio
async def test_notify_lead_on_task_unassigned_uses_canonical_agent_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    board = _board()
    task = _task(board.id)
    lead = _lead_agent(board.id, board.gateway_id)
    session = _FakeSession()
    calls: list[dict] = []

    async def _fake_try_send_to_agent(self, *, agent: Agent, message: str, deliver: bool = False):
        _ = self
        calls.append({"agent_id": agent.id, "message": message, "deliver": deliver})
        return None

    monkeypatch.setattr(tasks_api.Agent, "objects", _LeadObjects(lead))
    monkeypatch.setattr(tasks_api.GatewayDispatchService, "try_send_to_agent", _fake_try_send_to_agent)

    await tasks_api._notify_lead_on_task_unassigned(session=session, board=board, task=task)  # type: ignore[arg-type]

    assert session.commits == 1
    assert len(calls) == 1
    assert calls[0]["agent_id"] == lead.id
    assert "TASK BACK IN INBOX" in calls[0]["message"]
