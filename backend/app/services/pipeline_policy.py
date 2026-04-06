"""Shared board execution policy helpers for pipeline orchestration."""

from __future__ import annotations

from typing import Any

from app.models.boards import Board

KNOWN_PIPELINE_RUNTIMES = ("opencode_cli", "acp", "openrouter")
DEFAULT_EXECUTION_POLICY: dict[str, Any] = {
    "default_runtime": "opencode_cli",
    "allowed_runtimes": ["opencode_cli"],
    "build_approval_mode": "high_risk_only",
    "auto_run_next_stage": True,
    "show_runs_debug_ui": True,
}


def normalize_execution_policy(policy: dict[str, Any] | None) -> dict[str, Any]:
    """Return a sanitized board execution policy with defaults applied."""
    normalized: dict[str, Any] = {
        "default_runtime": DEFAULT_EXECUTION_POLICY["default_runtime"],
        "allowed_runtimes": list(DEFAULT_EXECUTION_POLICY["allowed_runtimes"]),
        "build_approval_mode": DEFAULT_EXECUTION_POLICY["build_approval_mode"],
        "auto_run_next_stage": DEFAULT_EXECUTION_POLICY["auto_run_next_stage"],
        "show_runs_debug_ui": DEFAULT_EXECUTION_POLICY["show_runs_debug_ui"],
    }
    if not isinstance(policy, dict):
        return normalized

    runtime = policy.get("default_runtime")
    if isinstance(runtime, str) and runtime in KNOWN_PIPELINE_RUNTIMES:
        normalized["default_runtime"] = runtime

    allowed = policy.get("allowed_runtimes")
    if isinstance(allowed, list):
        filtered = [
            value
            for value in allowed
            if isinstance(value, str) and value in KNOWN_PIPELINE_RUNTIMES
        ]
        if filtered:
            normalized["allowed_runtimes"] = filtered

    if normalized["default_runtime"] not in normalized["allowed_runtimes"]:
        normalized["allowed_runtimes"] = [
            normalized["default_runtime"],
            *[
                value
                for value in normalized["allowed_runtimes"]
                if value != normalized["default_runtime"]
            ],
        ]

    build_mode = policy.get("build_approval_mode")
    if build_mode in {"always", "high_risk_only"}:
        normalized["build_approval_mode"] = build_mode

    if "auto_run_next_stage" in policy:
        normalized["auto_run_next_stage"] = bool(policy.get("auto_run_next_stage"))
    if "show_runs_debug_ui" in policy:
        normalized["show_runs_debug_ui"] = bool(policy.get("show_runs_debug_ui"))

    return normalized


def board_execution_policy(board: Board | None) -> dict[str, Any]:
    """Return a normalized execution policy for the given board."""
    if board is None:
        return normalize_execution_policy(None)
    return normalize_execution_policy(board.execution_policy)


def default_pipeline_runtime(board: Board | None) -> str:
    """Return the default runtime for ordinary pipeline execution."""
    return str(board_execution_policy(board).get("default_runtime") or "opencode_cli")


def is_pipeline_runtime_allowed(board: Board | None, runtime: str) -> bool:
    """Return whether the requested runtime is allowed for normal pipeline execution."""
    return runtime in set(board_execution_policy(board).get("allowed_runtimes") or [])


def build_approval_mode(board: Board | None) -> str:
    """Return the build approval mode for a board."""
    return str(board_execution_policy(board).get("build_approval_mode") or "high_risk_only")
