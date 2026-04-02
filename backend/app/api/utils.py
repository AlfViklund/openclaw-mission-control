"""Shared API utilities."""

from __future__ import annotations

from fastapi import status


def http_status_for_value_error(message: str) -> int:
    """Map a ValueError message to an appropriate HTTP status code.

    - "not found" / "does not exist" → 404
    - "paused" / "requires" / "missing required" / "no successful" / "awaiting_approval" → 409
    - everything else → 400
    """
    lowered = message.lower()
    if "not found" in lowered or "does not exist" in lowered:
        return status.HTTP_404_NOT_FOUND
    if (
        "paused" in lowered
        or "requires" in lowered
        or "missing required" in lowered
        or "no successful" in lowered
        or "awaiting_approval" in lowered
    ):
        return status.HTTP_409_CONFLICT
    return status.HTTP_400_BAD_REQUEST
