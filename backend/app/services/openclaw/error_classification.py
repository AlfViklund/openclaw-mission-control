"""Helpers for classifying lifecycle, auth, and legacy runtime errors."""

from __future__ import annotations

from typing import Any

_TRANSIENT_GATEWAY_ERROR_PATTERNS = (
    "rate limit",
    "too many requests",
    "rate increased too quickly",
    "retry after",
)
_AUTH_SYNC_ERROR_PATTERNS = (
    "token readback mismatch",
    "auth_token not found",
    "invalid agent token",
    "agent token is invalid",
    "x-agent-token",
    "unauthorized",
    "401",
    "cannot resolve runtime token",
    "cannot resolve signed token",
)
_SESSION_RECOVERY_ERROR_PATTERNS = (
    "connection refused",
    "session recovery failed",
    "sessions.reset",
    "unknown session",
    "no such session",
    "session does not exist",
    "ensure session",
    "send_message",
    "did not check in after wake",
)
_LEGACY_PLAYWRIGHT_RUNTIME_PATTERNS = (
    "playwright not installed",
    "npx playwright not found",
    "playwright cannot run",
    "playwright: permission denied",
)


def _normalized_message(message: str | None) -> str:
    return (message or "").strip().lower()


def is_transient_gateway_error(message: str | None) -> bool:
    normalized = _normalized_message(message)
    if not normalized:
        return False
    return any(pattern in normalized for pattern in _TRANSIENT_GATEWAY_ERROR_PATTERNS)


def is_auth_sync_error(message: str | None) -> bool:
    normalized = _normalized_message(message)
    if not normalized or is_transient_gateway_error(normalized):
        return False
    return any(pattern in normalized for pattern in _AUTH_SYNC_ERROR_PATTERNS)


def is_session_recovery_error(message: str | None) -> bool:
    normalized = _normalized_message(message)
    if not normalized:
        return False
    return any(pattern in normalized for pattern in _SESSION_RECOVERY_ERROR_PATTERNS)


def is_legacy_playwright_runtime_state(state: dict[str, Any] | None) -> bool:
    if not isinstance(state, dict):
        return False
    status = str(state.get("status") or "").strip().lower()
    message = _normalized_message(str(state.get("cooldown_message") or ""))
    if status not in {"degraded", "unavailable"} or not message:
        return False
    return any(pattern in message for pattern in _LEGACY_PLAYWRIGHT_RUNTIME_PATTERNS)
