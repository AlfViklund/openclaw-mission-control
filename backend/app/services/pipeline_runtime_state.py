"""Persisted board runtime state for pipeline cooldown/degraded handling."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from app.core.time import utcnow
from app.models.boards import Board
from app.services.openclaw.error_classification import is_legacy_playwright_runtime_state

_DEFAULT_RUNTIME_STATE = {
    "runtime": "opencode_cli",
    "status": "ready",
    "failure_kind": None,
    "cooldown_until": None,
    "cooldown_message": None,
    "provider": None,
    "model": None,
    "updated_at": None,
}

_DURATION_PATTERNS: tuple[tuple[str, int], ...] = (
    ("hour", 3600),
    ("hr", 3600),
    ("minute", 60),
    ("min", 60),
    ("day", 86400),
)


def normalize_runtime_state(state: dict[str, Any] | None) -> dict[str, Any]:
    normalized = dict(_DEFAULT_RUNTIME_STATE)
    if isinstance(state, dict):
        normalized.update(state)
    if is_legacy_playwright_runtime_state(normalized):
        normalized = dict(_DEFAULT_RUNTIME_STATE)
        normalized["updated_at"] = utcnow().isoformat()
        return normalized
    cooldown_until = normalized.get("cooldown_until")
    if isinstance(cooldown_until, str):
        try:
            normalized["cooldown_until"] = cooldown_until
        except ValueError:
            normalized["cooldown_until"] = None
    if normalized.get("status") == "cooldown" and _cooldown_expired(normalized.get("cooldown_until")):
        normalized = dict(_DEFAULT_RUNTIME_STATE)
        normalized["updated_at"] = utcnow().isoformat()
    return normalized


def _cooldown_expired(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        return utcnow() >= datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return False


def parse_cooldown_until(
    message: str | None,
    *,
    fallback_minutes: int | None = 30,
) -> tuple[str | None, str | None]:
    if not message:
        return None, None
    lowered = message.lower()
    for unit, seconds in _DURATION_PATTERNS:
        match = re.search(rf"(?:after|in|wait|reset(?:s)?\s+in)\s+(\d+)\s*{unit}s?", lowered)
        if match:
            duration = int(match.group(1))
            cooldown_until = utcnow() + timedelta(seconds=duration * seconds)
            return cooldown_until.isoformat(), f"Provider cooldown in effect for about {duration} {unit}{'' if duration == 1 else 's'}."
    if fallback_minutes is None:
        return None, None
    fallback = utcnow() + timedelta(minutes=fallback_minutes)
    return fallback.isoformat(), "Provider cooldown in effect. Retry after the cooldown window or reset manually."


def is_runtime_quota_blocked(board: Board | None, *, runtime: str = "opencode_cli") -> bool:
    """Return whether persisted runtime state blocks new runs for the runtime."""
    if runtime != "opencode_cli":
        return False
    runtime_state = runtime_state_for_board(board)
    return (
        runtime_state.get("status") == "cooldown"
        and runtime_state.get("failure_kind") == "quota_exhausted"
    )


def runtime_state_for_board(board: Board | None) -> dict[str, Any]:
    if board is None:
        return normalize_runtime_state(None)
    return normalize_runtime_state(getattr(board, "execution_runtime_state", None))


def set_runtime_state(
    board: Board,
    *,
    runtime: str,
    status: str,
    failure_kind: str | None = None,
    cooldown_until: str | None = None,
    cooldown_message: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> None:
    board.execution_runtime_state = normalize_runtime_state(
        {
            "runtime": runtime,
            "status": status,
            "failure_kind": failure_kind,
            "cooldown_until": cooldown_until,
            "cooldown_message": cooldown_message,
            "provider": provider,
            "model": model,
            "updated_at": utcnow().isoformat(),
        }
    )
    board.updated_at = utcnow()


def clear_runtime_state(board: Board, *, runtime: str = "opencode_cli") -> None:
    board.execution_runtime_state = normalize_runtime_state(
        {
            "runtime": runtime,
            "updated_at": utcnow().isoformat(),
        }
    )
    board.updated_at = utcnow()


def clear_legacy_playwright_runtime_state(board: Board) -> bool:
    """Clear stale runtime degradation left behind by removed Playwright test runs."""

    if not is_legacy_playwright_runtime_state(board.execution_runtime_state):
        return False
    clear_runtime_state(board)
    return True
