"""Tests for destination-aware notification watermarks."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bot import notification_watermarks as watermarks


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value: str):
        self.values[key] = value


@pytest.mark.asyncio
async def test_watermarks_are_destination_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_redis = _FakeRedis()
    _ = monkeypatch

    await watermarks.set_watermark(fake_redis, "approval", 123.0, destination="board-1")
    await watermarks.set_watermark(fake_redis, "approval", 456.0, destination="board-2")

    assert fake_redis.values == {
        "clawdev:wm:board-1:approval": "123.0",
        "clawdev:wm:board-2:approval": "456.0",
    }
    assert await watermarks.get_watermark(fake_redis, "approval", destination="board-1") == 123.0
    assert await watermarks.get_watermark(fake_redis, "approval", destination="board-2") == 456.0


def test_advance_watermark_uses_max_event_timestamp() -> None:
    events = [
        {"id": "a", "created_at": datetime(2026, 4, 2, 12, 0, tzinfo=UTC).isoformat()},
        {"id": "b", "created_at": datetime(2026, 4, 2, 12, 5, tzinfo=UTC).isoformat()},
    ]

    next_ts = watermarks.advance_watermark(0.0, "approval", events)

    assert next_ts == datetime(2026, 4, 2, 12, 5, tzinfo=UTC).timestamp()


def test_advance_watermark_leaves_empty_poll_unchanged() -> None:
    assert watermarks.advance_watermark(123.0, "run_success", []) == 123.0


def test_build_poll_since_overlaps_recent_watermark() -> None:
    assert watermarks.build_poll_since(123.0) == 118.0
    assert watermarks.build_poll_since(3.0) == 0.0


def test_extract_event_timestamp_handles_unblocked_payload() -> None:
    ts = watermarks.extract_event_ts(
        "unblocked",
        {"event_id": "evt-1", "unblocked_at": datetime(2026, 4, 2, 12, 7, tzinfo=UTC).isoformat()},
    )

    assert ts == datetime(2026, 4, 2, 12, 7, tzinfo=UTC).timestamp()
