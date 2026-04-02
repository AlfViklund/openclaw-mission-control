"""Tests for planner service — _wait_for_agent_response request correlation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest


class TestWaitForAgentResponse:
    """Tests for _wait_for_agent_response with request correlation markers."""

    @pytest.mark.asyncio
    async def test_returns_response_with_matching_marker(self) -> None:
        from app.services.planner import _wait_for_agent_response

        call_count = 0

        async def fake_openclaw_call(method, params=None, config=None):
            nonlocal call_count
            call_count += 1
            return {
                "total": 4,
                "messages": [
                    {"role": "user", "content": "hello"},
                    {"role": "assistant", "content": "old response"},
                    {"role": "user", "content": "new prompt [PLANNER_REQUEST:abc123]"},
                    {"role": "assistant", "content": "Here is the plan [PLANNER_RESPONSE:abc123]\nStep 1: do X"},
                ],
            }

        with patch("app.services.openclaw.gateway_rpc.openclaw_call", fake_openclaw_call):
            result = await _wait_for_agent_response(
                session_key="test-session",
                config=None,
                history_cursor=1,
                request_marker="[PLANNER_RESPONSE:abc123]",
                timeout=10,
            )

        assert "Here is the plan" in result
        assert "[PLANNER_RESPONSE:abc123]" not in result

    @pytest.mark.asyncio
    async def test_falls_back_to_first_assistant_without_marker(self) -> None:
        from app.services.planner import _wait_for_agent_response

        async def fake_openclaw_call(method, params=None, config=None):
            return {
                "total": 3,
                "messages": [
                    {"role": "user", "content": "hello"},
                    {"role": "assistant", "content": "Here is the response"},
                ],
            }

        with patch("app.services.openclaw.gateway_rpc.openclaw_call", fake_openclaw_call):
            result = await _wait_for_agent_response(
                session_key="test-session",
                config=None,
                history_cursor=1,
                timeout=10,
            )

        assert result == "Here is the response"

    @pytest.mark.asyncio
    async def test_raises_on_timeout(self) -> None:
        from app.services.planner import _wait_for_agent_response

        async def fake_openclaw_call(method, params=None, config=None):
            return {"total": 1, "messages": [{"role": "user", "content": "hello"}]}

        with patch("app.services.openclaw.gateway_rpc.openclaw_call", fake_openclaw_call):
            with pytest.raises(RuntimeError, match="Timeout"):
                await _wait_for_agent_response(
                    session_key="test-session",
                    config=None,
                    history_cursor=1,
                    request_marker="[PLANNER_RESPONSE:xyz]",
                    timeout=1,
                )

    @pytest.mark.asyncio
    async def test_ignores_non_assistant_roles(self) -> None:
        from app.services.planner import _wait_for_agent_response

        async def fake_openclaw_call(method, params=None, config=None):
            return {
                "total": 3,
                "messages": [
                    {"role": "user", "content": "hello"},
                    {"role": "system", "content": "system msg"},
                    {"role": "assistant", "content": "actual response"},
                ],
            }

        with patch("app.services.openclaw.gateway_rpc.openclaw_call", fake_openclaw_call):
            result = await _wait_for_agent_response(
                session_key="test-session",
                config=None,
                history_cursor=1,
                timeout=10,
            )

        assert result == "actual response"
