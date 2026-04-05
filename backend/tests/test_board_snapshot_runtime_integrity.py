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
        workspace_exists=True,
        template_sync_state="ok",
    )

    assert blocker == "PlatformBlocked(Check-in)"
