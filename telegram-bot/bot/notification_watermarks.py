"""Destination-scoped notification watermark helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

POLL_OVERLAP_SECONDS = 5.0


def watermark_key(event_type: str, destination: str) -> str:
    return f"clawdev:wm:{destination}:{event_type}"


def seen_key(event_type: str, destination: str) -> str:
    return f"clawdev:seen:{destination}:{event_type}"


async def get_watermark(notification_redis, event_type: str, destination: str) -> float:
    if notification_redis is None:
        return 0.0
    value = await notification_redis.get(watermark_key(event_type, destination))
    return float(value) if value else 0.0


async def set_watermark(notification_redis, event_type: str, ts: float, destination: str) -> None:
    if notification_redis is None:
        return
    await notification_redis.set(watermark_key(event_type, destination), str(ts))


async def has_seen_event(notification_redis, event_type: str, destination: str, event_id: str) -> bool:
    if notification_redis is None:
        return False
    return bool(await notification_redis.sismember(seen_key(event_type, destination), event_id))


async def mark_seen_event(notification_redis, event_type: str, destination: str, event_id: str) -> None:
    if notification_redis is None:
        return
    await notification_redis.sadd(seen_key(event_type, destination), event_id)


def _parse_iso_datetime(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().replace("Z", "+00:00")
    if not normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).timestamp()


def extract_event_ts(event_type: str, payload: dict[str, Any]) -> float | None:
    if event_type == "approval":
        return _parse_iso_datetime(payload.get("resolved_at")) or _parse_iso_datetime(
            payload.get("created_at"),
        )
    if event_type in {"build_failed", "run_success"}:
        return _parse_iso_datetime(payload.get("finished_at")) or _parse_iso_datetime(
            payload.get("created_at"),
        )
    if event_type == "unblocked":
        return _parse_iso_datetime(payload.get("unblocked_at"))
    return _parse_iso_datetime(payload.get("created_at"))


def extract_event_id(event_type: str, payload: dict[str, Any]) -> str | None:
    if event_type == "unblocked":
        return str(payload.get("event_id") or payload.get("id") or payload.get("task_id") or "") or None
    return str(payload.get("id") or "") or None


def advance_watermark(previous_ts: float, event_type: str, events: list[dict[str, Any]]) -> float:
    timestamps = [ts for ts in (extract_event_ts(event_type, event) for event in events) if ts is not None]
    if not timestamps:
        return previous_ts
    next_ts = max(timestamps)
    return next_ts if next_ts > previous_ts else previous_ts


def build_poll_since(previous_ts: float, *, overlap_seconds: float = POLL_OVERLAP_SECONDS) -> float:
    if previous_ts <= 0:
        return 0.0
    return max(0.0, previous_ts - overlap_seconds)
