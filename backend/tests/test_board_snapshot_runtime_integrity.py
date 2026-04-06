# ruff: noqa: INP001
"""Unit tests for board snapshot runtime-integrity helpers."""

from __future__ import annotations

from pathlib import Path

from app.schemas.board_onboarding import BoardOnboardingTeamPlan
from app.services import board_snapshot


def test_workspace_template_sync_state_detects_bearer_drift(tmp_path: Path) -> None:
    (tmp_path / "HEARTBEAT.md").write_text(
        'curl -H "Authorization: Bearer token"',
        encoding="utf-8",
    )

    state, exists = board_snapshot._workspace_template_sync_state(tmp_path)

    assert state == "drifted"
    assert exists is True


def test_expected_role_keys_follow_selected_roles_team_plan() -> None:
    plan = BoardOnboardingTeamPlan(
        provision_mode="selected_roles",
        roles=["developer", "technical_writer", "board_lead", "unknown_role"],
    )

    roles = board_snapshot._expected_role_keys(plan)

    assert roles == ["board_lead", "developer", "technical_writer"]


def test_runtime_blocker_marks_unhealthy_assigned_agent_as_checkin_blocked() -> None:
    blocker = board_snapshot._runtime_blocker(
        status="offline",
        wake_reason="assigned_in_progress_task",
        last_provision_error=None,
        agent_auth_last_error=None,
        pending_agent_token_version=None,
        workspace_exists=True,
        template_sync_state="ok",
    )

    assert blocker == "PlatformBlocked(Check-in)"


def test_runtime_blocker_treats_gateway_rate_limit_as_provisioning_not_auth() -> None:
    blocker = board_snapshot._runtime_blocker(
        status="offline",
        wake_reason=None,
        last_provision_error=None,
        agent_auth_last_error="rate limit exceeded for config.patch; retry after 10s",
        pending_agent_token_version=None,
        workspace_exists=True,
        template_sync_state="ok",
    )

    assert blocker == "PlatformBlocked(Provisioning)"


def test_runtime_blocker_treats_pending_token_connection_failure_as_checkin_blocked() -> None:
    blocker = board_snapshot._runtime_blocker(
        status="offline",
        wake_reason=None,
        last_provision_error="[Errno 111] Connection refused",
        agent_auth_last_error=None,
        pending_agent_token_version=1,
        workspace_exists=True,
        template_sync_state="ok",
    )

    assert blocker == "PlatformBlocked(Check-in)"


def test_runtime_blocker_marks_token_mismatch_as_auth_blocked() -> None:
    blocker = board_snapshot._runtime_blocker(
        status="offline",
        wake_reason=None,
        last_provision_error="Token readback mismatch: expected abc..., got def...",
        agent_auth_last_error=None,
        pending_agent_token_version=1,
        workspace_exists=True,
        template_sync_state="ok",
    )

    assert blocker == "PlatformBlocked(Auth)"
