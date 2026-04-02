"""Tests for notification client board-scoped polling helpers."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")

from bot.api_client import MissionControlClient


@pytest.mark.asyncio
async def test_list_runs_for_notifications_accepts_board_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MissionControlClient()
    calls: list[dict] = []

    async def _fake_get(path: str, params: dict | None = None):
        calls.append({"path": path, "params": params})
        return {"items": []}

    monkeypatch.setattr(client, "_get", _fake_get)

    await client.list_runs_for_notifications(status="succeeded", since="2026-04-02T12:00:00Z", board_id="board-1")

    assert calls == [
        {
            "path": "/api/v1/runs",
            "params": {
                "board_id": "board-1",
                "status": "succeeded",
                "since": "2026-04-02T12:00:00Z",
            },
        }
    ]


@pytest.mark.asyncio
async def test_list_failed_build_runs_accepts_board_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MissionControlClient()
    calls: list[dict] = []

    async def _fake_get(path: str, params: dict | None = None):
        calls.append({"path": path, "params": params})
        return {"items": []}

    monkeypatch.setattr(client, "_get", _fake_get)

    await client.list_failed_build_runs(since="2026-04-02T12:00:00Z", board_id="board-1")

    assert calls == [
        {
            "path": "/api/v1/runs",
            "params": {
                "status": "failed",
                "stage": "build",
                "board_id": "board-1",
                "since": "2026-04-02T12:00:00Z",
            },
        }
    ]


@pytest.mark.asyncio
async def test_list_unblocked_tasks_accepts_board_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MissionControlClient()
    calls: list[dict] = []

    async def _fake_get(path: str, params: dict | None = None):
        calls.append({"path": path, "params": params})
        return []

    monkeypatch.setattr(client, "_get", _fake_get)

    await client.list_unblocked_tasks(since="2026-04-02T12:00:00Z", board_id="board-1")

    assert calls == [
        {
            "path": "/api/v1/boards/board-1/tasks/unblocked-transitions",
            "params": {"since": "2026-04-02T12:00:00Z"},
        }
    ]
