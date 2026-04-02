"""Tests for destination-aware notification watermarks."""

from __future__ import annotations

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
