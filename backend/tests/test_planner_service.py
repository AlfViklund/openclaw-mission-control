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
from app.models.tags import Tag
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

    @pytest.mark.asyncio
    async def test_handles_structured_assistant_blocks_without_marker(self) -> None:
        from app.services.planner import _wait_for_agent_response

        async def fake_openclaw_call(method, params=None, config=None):
            return {
                "total": 4,
                "messages": [
                    {"role": "user", "content": "hello"},
                    {
                        "role": "assistant",
                        "content": [
                            {"type": "thinking", "thinking": "..."},
                            {"type": "text", "text": "Structured planner response"},
                        ],
                    },
                ],
            }

        with patch("app.services.openclaw.gateway_rpc.openclaw_call", fake_openclaw_call):
            result = await _wait_for_agent_response(
                session_key="test-session",
                config=None,
                history_cursor=1,
                request_marker="[PLANNER_RESPONSE:missing]",
                timeout=10,
            )

        assert result == "Structured planner response"

    @pytest.mark.asyncio
    async def test_handles_history_payload_shape(self) -> None:
        from app.services.planner import _wait_for_agent_response

        async def fake_openclaw_call(method, params=None, config=None):
            assert params == {"sessionKey": "test-session", "limit": 20}
            return {
                "history": [
                    {"role": "user", "content": [{"type": "text", "text": "hello"}]},
                    {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "Reply from history field"}],
                    },
                ]
            }

        with patch("app.services.openclaw.gateway_rpc.openclaw_call", fake_openclaw_call):
            result = await _wait_for_agent_response(
                session_key="test-session",
                config=None,
                history_cursor=1,
                timeout=10,
            )

        assert result == "Reply from history field"


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
            assert output.pipeline_phase == "queued"
            assert output.tasks == []
            assert [phase["key"] for phase in output.phase_statuses] == [
                "digest",
                "dossier",
                "epics",
                "tasks",
                "ready",
            ]
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
    async def test_generate_backlog_from_text_force_replaces_existing_generating(
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
            artifact_id = uuid4()
            existing = PlannerOutput(
                board_id=board.id,
                artifact_id=artifact_id,
                status="generating",
                pipeline_phase="digest",
                epics=[],
                tasks=[],
                documents=[],
                phase_statuses=[],
                parallelism_groups=[],
            )
            session.add(organization)
            session.add(board)
            session.add(existing)
            await session.commit()

            queued: list[UUID] = []

            def _fake_launch(
                *,
                planner_output_id: UUID,
                board_id: object,
                spec_text: str,
                max_tasks: int,
            ) -> None:
                queued.append(planner_output_id)

            monkeypatch.setattr(
                "app.services.planner._launch_planner_generation",
                _fake_launch,
            )

            output = await generate_backlog_from_text(
                session,
                artifact_id=artifact_id,
                board_id=board.id,
                spec_text="# Spec",
                max_tasks=12,
                force=True,
            )

            await session.refresh(output)
            assert output.id != existing.id
            assert output.status == "generating"
            assert queued == [output.id]

            still_there = await session.get(PlannerOutput, existing.id)
            assert still_there is None
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
                        "tags": ["backend"],
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
            assert updated.materialized_task_count == 3
            assert tasks_by_title["Implement feature"].assigned_agent_id == developer.id
            assert tasks_by_title["Write README"].assigned_agent_id == writer.id
            assert tasks_by_title["Coordinate release"].assigned_agent_id == lead.id
            assert tasks_by_title["Implement feature"].planner_output_id == planner_output.id
            assert tasks_by_title["Implement feature"].planner_epic_id == "epic_1"
            assert tasks_by_title["Implement feature"].materialized_from == "initial"
            assert tasks_by_title["Implement feature"].expansion_round == 0
            tags = await Tag.objects.filter_by(organization_id=organization.id).all(session)
            assert [tag.slug for tag in tags] == ["backend"]
        finally:
            await session.close()
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_get_board_execution_coverage_summarizes_materialized_scope(self) -> None:
        from app.services.planner import get_board_execution_coverage

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
            planner_output = PlannerOutput(
                board_id=board.id,
                artifact_id=uuid4(),
                status="applied",
                applied_at=None,
                documents=[{"key": "spec_digest", "title": "Specification Digest"}],
                epics=[{"id": "epic_1", "title": "Ship product"}],
                tasks=[{"id": "epic_1_task_1", "epic_id": "epic_1", "title": "Implement feature"}],
                epic_states=[
                    {
                        "epic_id": "epic_1",
                        "status": "active",
                        "coverage_summary": "Core implementation started.",
                        "remaining_work_summary": "Need QA and docs follow-up.",
                        "materialized_tasks": 1,
                        "done_tasks": 0,
                        "open_acceptance_items": ["QA sign-off", "Docs handoff"],
                        "next_focus_roles": ["qa", "docs"],
                    }
                ],
                expansion_policy={
                    "auto_expand_enabled": True,
                    "initial_task_budget": 8,
                    "low_backlog_threshold": 4,
                    "max_new_tasks_per_round": 2,
                    "max_new_tasks_per_epic": 2,
                    "max_active_epics": 3,
                },
                materialized_task_count=1,
                remaining_scope_count=2,
            )
            task = Task(
                board_id=board.id,
                title="Implement feature",
                status="done",
                planner_task_id="epic_1_task_1",
                epic_id="epic_1",
                planner_output_id=planner_output.id,
                planner_epic_id="epic_1",
                materialized_from="initial",
                expansion_round=0,
            )
            session.add(organization)
            session.add(gateway)
            session.add(board)
            session.add(lead)
            session.add(planner_output)
            session.add(task)
            await session.commit()

            coverage = await get_board_execution_coverage(session, board_id=board.id)

            assert coverage["planner_output_id"] == planner_output.id
            assert coverage["docs_count"] == 1
            assert coverage["materialized_tasks"] == 1
            assert coverage["done_tasks"] == 1
            assert coverage["remaining_scope_count"] == 2
            assert coverage["auto_expand_enabled"] is True
            assert coverage["next_expansion_eligible"] is True
        finally:
            await session.close()
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_get_board_execution_coverage_backfills_existing_applied_tasks(self) -> None:
        from app.services.planner import get_board_execution_coverage

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
            planner_output = PlannerOutput(
                board_id=board.id,
                artifact_id=uuid4(),
                status="applied",
                epics=[{"id": "epic_1", "title": "Ship product"}],
                tasks=[{"id": "task_1", "epic_id": "epic_1", "title": "Implement feature"}],
                documents=[],
                epic_states=[],
            )
            task = Task(
                board_id=board.id,
                title="Implement feature",
                status="inbox",
                planner_task_id="task_1",
                epic_id="epic_1",
                auto_created=True,
                auto_reason=f"planner_output:{planner_output.id}",
            )
            session.add(organization)
            session.add(gateway)
            session.add(board)
            session.add(lead)
            session.add(planner_output)
            session.add(task)
            await session.commit()

            coverage = await get_board_execution_coverage(session, board_id=board.id)
            await session.refresh(task)
            await session.refresh(planner_output)

            assert coverage["materialized_tasks"] == 1
            assert coverage["epics_total"] == 1
            assert task.planner_output_id == planner_output.id
            assert task.materialized_from == "initial"
            assert planner_output.epic_states
            assert planner_output.epic_states[0]["epic_id"] == "epic_1"
        finally:
            await session.close()
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_queue_planner_expansion_creates_running_expansion_run(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.models.planner_expansion_runs import PlannerExpansionRun
        from app.services.planner import queue_planner_expansion

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
            planner_output = PlannerOutput(
                board_id=board.id,
                artifact_id=uuid4(),
                status="applied",
                epics=[{"id": "epic_1", "title": "Ship product"}],
                tasks=[{"id": "epic_1_task_1", "epic_id": "epic_1", "title": "Implement feature"}],
                documents=[],
                epic_states=[
                    {
                        "epic_id": "epic_1",
                        "status": "active",
                        "coverage_summary": "Core implementation started.",
                        "remaining_work_summary": "Need follow-up.",
                        "materialized_tasks": 1,
                        "done_tasks": 0,
                        "open_acceptance_items": ["Follow-up task"],
                        "next_focus_roles": ["qa"],
                    }
                ],
                expansion_policy={"auto_expand_enabled": True, "initial_task_budget": 8},
            )
            session.add(organization)
            session.add(gateway)
            session.add(board)
            session.add(lead)
            session.add(planner_output)
            await session.commit()

            launched: list[tuple[UUID, UUID, int | None]] = []

            def _fake_launch(*, planner_output_id: UUID, expansion_run_id: UUID, max_new_tasks: int | None) -> None:
                launched.append((planner_output_id, expansion_run_id, max_new_tasks))

            monkeypatch.setattr("app.services.planner._launch_planner_expansion", _fake_launch)

            updated = await queue_planner_expansion(
                session,
                planner_output=planner_output,
                trigger="manual",
                max_new_tasks=3,
            )

            runs = await PlannerExpansionRun.objects.filter_by(planner_output_id=planner_output.id).all(session)
            assert updated.id == planner_output.id
            assert len(runs) == 1
            assert runs[0].status == "running"
            assert runs[0].trigger == "manual"
            assert launched == [(planner_output.id, runs[0].id, 3)]
        finally:
            await session.close()
            await engine.dispose()
