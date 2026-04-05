# ruff: noqa: INP001
"""Regression tests for agent runtime template auth contract."""

from __future__ import annotations

from pathlib import Path


def test_agent_runtime_templates_use_x_agent_token_only() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    template_paths = [
        repo_root / "backend" / "templates" / "BOARD_AGENTS.md.j2",
        repo_root / "backend" / "templates" / "BOARD_BOOTSTRAP.md.j2",
        repo_root / "backend" / "templates" / "BOARD_HEARTBEAT.md.j2",
    ]

    for path in template_paths:
        content = path.read_text(encoding="utf-8")
        assert "X-Agent-Token" in content
        assert "Authorization: Bearer {{ auth_token }}" not in content
