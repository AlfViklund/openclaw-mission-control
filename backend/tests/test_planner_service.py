"""Tests for planner service — _wait_for_agent_response request correlation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.planner_outputs import PlannerOutput
from app.models.tasks import Task


async def _build_session() -> tuple[AsyncSession, AsyncEngine]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    return AsyncSession(engine, expire_on_commit=False), engine


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


class TestPlannerGenerationLifecycle:
    @pytest.mark.asyncio
    async def test_generate_backlog_from_text_queues_background_generation(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.services.planner import generate_backlog_from_text

        session, engine = await _build_session()
        try:
            organization = Organization(name="Acme")
            board = Board(
                organization_id=organization.id,
                name="Planner Board",
                slug="planner-board",
                description="",
                board_type="general",
            )
            session.add(organization)
            session.add(board)
            await session.commit()

            queued: list[dict[str, object]] = []

            def _fake_launch(
                *,
                planner_output_id: object,
                board_id: object,
                spec_text: str,
                max_tasks: int,
            ) -> None:
                queued.append(
                    {
                        "planner_output_id": planner_output_id,
                        "board_id": board_id,
                        "spec_text": spec_text,
                        "max_tasks": max_tasks,
                    }
                )

            monkeypatch.setattr(
                "app.services.planner._launch_planner_generation",
                _fake_launch,
            )

            output = await generate_backlog_from_text(
                session,
                artifact_id=uuid4(),
                board_id=board.id,
                spec_text="# Spec",
                max_tasks=12,
                force=False,
            )

            assert output.status == "generating"
            assert output.tasks == []
            assert queued == [
                {
                    "planner_output_id": output.id,
                    "board_id": board.id,
                    "spec_text": "# Spec",
                    "max_tasks": 12,
                }
            ]
        finally:
            await session.close()
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_apply_planner_output_assigns_specialists_and_falls_back_to_lead(
        self,
    ) -> None:
        from app.services.planner import apply_planner_output

        session, engine = await _build_session()
        try:
            organization = Organization(name="Acme")
            gateway = Gateway(
                organization_id=organization.id,
                name="Gateway",
                url="http://gateway.local",
                token="token",
                workspace_root="/tmp/workspace",
            )
            board = Board(
                organization_id=organization.id,
                gateway_id=gateway.id,
                name="Planner Board",
                slug="planner-board",
                description="",
                board_type="general",
            )
            lead = Agent(
                board_id=board.id,
                gateway_id=gateway.id,
                name="Lead Agent",
                status="online",
                is_board_lead=True,
                identity_profile={"role": "Board Lead"},
            )
            developer = Agent(
                board_id=board.id,
                gateway_id=gateway.id,
                name="Developer",
                status="online",
                identity_profile={"role": "Developer"},
            )
            writer = Agent(
                board_id=board.id,
                gateway_id=gateway.id,
                name="Technical Writer",
                status="online",
                identity_profile={"role": "Technical Writer"},
            )
            planner_output = PlannerOutput(
                board_id=board.id,
                artifact_id=uuid4(),
                status="draft",
                epics=[{"id": "epic_1", "title": "Ship product"}],
                tasks=[
                    {
                        "id": "task_1",
                        "epic_id": "epic_1",
                        "title": "Implement feature",
                        "suggested_agent_role": "dev",
                        "depends_on": [],
                    },
                    {
                        "id": "task_2",
                        "epic_id": "epic_1",
                        "title": "Write README",
                        "suggested_agent_role": "docs",
                        "depends_on": ["task_1"],
                    },
                    {
                        "id": "task_3",
                        "epic_id": "epic_1",
                        "title": "Coordinate release",
                        "suggested_agent_role": "ops",
                        "depends_on": ["task_2"],
                    },
                ],
                parallelism_groups=[],
            )
            session.add(organization)
            session.add(gateway)
            session.add(board)
            session.add(lead)
            session.add(developer)
            session.add(writer)
            session.add(planner_output)
            await session.commit()

            updated = await apply_planner_output(session, planner_output)

            created_tasks = await Task.objects.filter_by(board_id=board.id).all(session)
            tasks_by_title = {task.title: task for task in created_tasks}

            assert updated.status == "applied"
            assert tasks_by_title["Implement feature"].assigned_agent_id == developer.id
            assert tasks_by_title["Write README"].assigned_agent_id == writer.id
            assert tasks_by_title["Coordinate release"].assigned_agent_id == lead.id
        finally:
            await session.close()
            await engine.dispose()
