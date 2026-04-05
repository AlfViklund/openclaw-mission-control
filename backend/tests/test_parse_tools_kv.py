# ruff: noqa: INP001, SLF001
"""Tests for parse_tools_kv helper — markdown bullet format support."""

from __future__ import annotations

from app.services.openclaw.provisioning import _template_env
from app.services.openclaw.constants import parse_tools_kv


def test_parse_plain_kv() -> None:
    content = "AUTH_TOKEN=abc123\nBASE_URL=http://localhost\n"
    result = parse_tools_kv(content)
    assert result["AUTH_TOKEN"] == "abc123"
    assert result["BASE_URL"] == "http://localhost"


def test_parse_markdown_bullet_no_backticks() -> None:
    content = "- AUTH_TOKEN=abc123\n- BASE_URL=http://localhost\n"
    result = parse_tools_kv(content)
    assert result["AUTH_TOKEN"] == "abc123"
    assert result["BASE_URL"] == "http://localhost"


def test_parse_markdown_bullet_with_backticks() -> None:
    content = "- `AUTH_TOKEN=abc123`\n- `BASE_URL=http://localhost`\n"
    result = parse_tools_kv(content)
    assert result["AUTH_TOKEN"] == "abc123"
    assert result["BASE_URL"] == "http://localhost"


def test_parse_mixed_format() -> None:
    content = (
        "# TOOLS.md\n"
        "- `AUTH_TOKEN=secret-token`\n"
        "- `AGENT_NAME=test-agent`\n"
        "- `BASE_URL=http://localhost:8000`\n"
        "## OpenAPI refresh\n"
        "- Required tools: `curl`, `jq`\n"
    )
    result = parse_tools_kv(content)
    assert result["AUTH_TOKEN"] == "secret-token"
    assert result["AGENT_NAME"] == "test-agent"
    assert result["BASE_URL"] == "http://localhost:8000"


def test_parse_ignores_comments() -> None:
    content = "# This is a comment\nAUTH_TOKEN=abc\n# Another comment\n"
    result = parse_tools_kv(content)
    assert result == {"AUTH_TOKEN": "abc"}


def test_parse_ignores_empty_lines() -> None:
    content = "\n\nAUTH_TOKEN=abc\n\n"
    result = parse_tools_kv(content)
    assert result == {"AUTH_TOKEN": "abc"}


def test_parse_signed_token_format() -> None:
    token = "agt1.11111111-2222-3333-4444-555555555555.1.dGhpc2lzYXNpZ25hdHVyZQ"
    content = f"- `AUTH_TOKEN={token}`\n"
    result = parse_tools_kv(content)
    assert result["AUTH_TOKEN"] == token


def test_parse_empty_content() -> None:
    assert parse_tools_kv("") == {}
    assert parse_tools_kv("\n\n") == {}


def test_rendered_tools_template_is_machine_safe() -> None:
    rendered = _template_env().get_template("BOARD_TOOLS.md.j2").render(
        base_url="http://127.0.0.1:8000",
        auth_token="agt1.agent-id.1.signature",
        agent_name="Lead Agent",
        agent_id="agent-id",
        board_id="board-id",
        workspace_root="~/.openclaw",
        workspace_path="~/.openclaw/workspace-lead-board-id",
        is_board_lead="true",
        is_main_agent="false",
    )
    lines = [line.strip() for line in rendered.splitlines() if line.strip()]

    assert "AUTH_TOKEN=agt1.agent-id.1.signature" in lines
    assert all("`AUTH_TOKEN=" not in line for line in lines)
    assert all(not line.startswith("- `AUTH_TOKEN=") for line in lines)
