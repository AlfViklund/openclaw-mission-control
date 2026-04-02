"""Destination-scoped notification watermark helpers."""

from __future__ import annotations


def watermark_key(event_type: str, destination: str) -> str:
    return f"clawdev:wm:{destination}:{event_type}"


async def get_watermark(notification_redis, event_type: str, destination: str) -> float:
    if notification_redis is None:
        return 0.0
    value = await notification_redis.get(watermark_key(event_type, destination))
    return float(value) if value else 0.0


async def set_watermark(notification_redis, event_type: str, ts: float, destination: str) -> None:
    if notification_redis is None:
        return
    await notification_redis.set(watermark_key(event_type, destination), str(ts))
