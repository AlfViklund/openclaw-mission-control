# ruff: noqa: S101
"""Tests for unblocked task transition payloads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.api import tasks as tasks_api
from app.models.activity_events import ActivityEvent
from app.models.boards import Board


@dataclass
class _FakeResult:
    rows: list[tuple[ActivityEvent, str | None, str | None]]

    def all(self) -> list[tuple[ActivityEvent, str | None, str | None]]:
        return self.rows


@dataclass
class _FakeSession:
    rows: list[tuple[ActivityEvent, str | None, str | None]]

    async def exec(self, _query):
        return _FakeResult(self.rows)


@pytest.mark.asyncio
async def test_unblocked_transitions_include_title_status_and_message() -> None:
    board = Board(
        id=uuid4(),
        organization_id=uuid4(),
        name="Platform",
        slug="platform",
        gateway_id=None,
    )
    event = ActivityEvent(
        id=uuid4(),
        event_type="task.unblocked",
        message="Task unblocked: dependency completed (Design review).",
        board_id=board.id,
        task_id=uuid4(),
        created_at=datetime(2026, 4, 2, 12, 0, tzinfo=UTC),
    )
    session = _FakeSession(rows=[(event, "Prepare launch notes", "inbox")])

    result = await tasks_api.list_unblocked_transitions(
        since=None,
        board=board,
        session=session,  # type: ignore[arg-type]
        _actor=object(),  # type: ignore[arg-type]
    )

    assert result == [
        {
            "id": str(event.task_id),
            "task_id": str(event.task_id),
            "board_id": str(board.id),
            "task_title": "Prepare launch notes",
            "task_status": "inbox",
            "unblocked_at": event.created_at.isoformat(),
            "message": event.message,
        }
    ]
