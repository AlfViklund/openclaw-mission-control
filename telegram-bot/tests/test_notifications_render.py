"""Tests for Telegram notification rendering."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")

from bot import notifications


@pytest.mark.asyncio
async def test_notify_task_unblocked_renders_enriched_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    messages: list[str] = []

    async def _fake_notify(message: str, parse_mode: str = "Markdown") -> None:
        _ = parse_mode
        messages.append(message)

    monkeypatch.setattr(notifications, "notify", _fake_notify)

    await notifications.notify_task_unblocked(
        {
            "task_title": "Prepare launch notes",
            "task_status": "review",
            "message": "Task unblocked: dependency completed (Design review).",
        },
    )

    assert len(messages) == 1
    assert "Prepare launch notes" in messages[0]
    assert "review" in messages[0]
    assert "dependency completed" in messages[0]
    assert "Untitled" not in messages[0]
    assert "inbox" not in messages[0]
