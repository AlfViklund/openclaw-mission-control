from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.deps import ActorContext
from app.api.pipeline import execute_pipeline_stage
from app.api.runs import create_and_start_run
from app.models.agents import Agent
from app.models.tasks import Task
from app.schemas.runs import RunCreate


def _agent_actor(*, board_id, is_board_lead: bool = False) -> ActorContext:
    return ActorContext(
        actor_type="agent",
        agent=Agent(
            id=uuid4(),
            board_id=board_id,
            gateway_id=uuid4(),
            name="Agent",
            is_board_lead=is_board_lead,
        ),
    )


@pytest.mark.asyncio
async def test_agent_create_run_defaults_to_self(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    board_id = uuid4()
    actor = _agent_actor(board_id=board_id)
    task_id = uuid4()
    task = Task(id=task_id, board_id=board_id, title="Task")
    created: dict[str, object] = {}
    run = SimpleNamespace(id=uuid4(), task_id=task_id, agent_id=actor.agent.id, stage="build", runtime="acp")

    monkeypatch.setattr(
        "app.api.runs.Task.objects",
        SimpleNamespace(by_id=lambda _id: SimpleNamespace(first=AsyncMock(return_value=task))),
    )
    monkeypatch.setattr(
        "app.api.deps.Agent.objects",
        SimpleNamespace(
            by_id=lambda _id: SimpleNamespace(
                first=AsyncMock(return_value=actor.agent if _id == actor.agent.id else None)
            )
        ),
    )

    async def _fake_create_run(_session, **kwargs):
        created.update(kwargs)
        return run

    async def _fake_start_run(_session, value):
        return value

    monkeypatch.setattr("app.api.runs.create_run", _fake_create_run)
    monkeypatch.setattr("app.api.runs.start_run", _fake_start_run)

    result = await create_and_start_run(
        payload=RunCreate(task_id=task_id, stage="build"),
        session=object(),  # type: ignore[arg-type]
        _actor=actor,
    )

    assert result == run
    assert created["agent_id"] == actor.agent.id


@pytest.mark.asyncio
async def test_agent_create_run_rejects_other_agent_for_non_lead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    board_id = uuid4()
    actor = _agent_actor(board_id=board_id, is_board_lead=False)
    other = Agent(id=uuid4(), board_id=board_id, gateway_id=uuid4(), name="Other")
    task = Task(id=uuid4(), board_id=board_id, title="Task")

    monkeypatch.setattr(
        "app.api.runs.Task.objects",
        SimpleNamespace(by_id=lambda _id: SimpleNamespace(first=AsyncMock(return_value=task))),
    )
    monkeypatch.setattr(
        "app.api.deps.Agent.objects",
        SimpleNamespace(
            by_id=lambda _id: SimpleNamespace(
                first=AsyncMock(return_value=other if _id == other.id else None)
            )
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        await create_and_start_run(
            payload=RunCreate(task_id=task.id, agent_id=other.id, stage="build"),
            session=object(),  # type: ignore[arg-type]
            _actor=actor,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Only board leads can execute work for other agents."


@pytest.mark.asyncio
async def test_agent_execute_pipeline_stage_defaults_to_self(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    board_id = uuid4()
    actor = _agent_actor(board_id=board_id)
    task = Task(id=uuid4(), board_id=board_id, title="Task")
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "app.api.pipeline.Task.objects",
        SimpleNamespace(by_id=lambda _id: SimpleNamespace(first=AsyncMock(return_value=task))),
    )
    monkeypatch.setattr(
        "app.api.deps.Agent.objects",
        SimpleNamespace(
            by_id=lambda _id: SimpleNamespace(
                first=AsyncMock(return_value=actor.agent if _id == actor.agent.id else None)
            )
        ),
    )

    class _FakeService:
        def __init__(self, _session):
            pass

        async def execute_stage(self, **kwargs):
            captured.update(kwargs)
            return {"ok": True}

    monkeypatch.setattr("app.api.pipeline.PipelineService", _FakeService)

    result = await execute_pipeline_stage(
        task_id=task.id,
        stage="build",
        runtime="acp",
        agent_id=None,
        model=None,
        session=object(),  # type: ignore[arg-type]
        _actor=actor,
    )

    assert result == {"ok": True}
    assert captured["agent_id"] == actor.agent.id


@pytest.mark.asyncio
async def test_agent_execute_pipeline_stage_rejects_foreign_board(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor = _agent_actor(board_id=uuid4())
    task = Task(id=uuid4(), board_id=uuid4(), title="Task")

    monkeypatch.setattr(
        "app.api.pipeline.Task.objects",
        SimpleNamespace(by_id=lambda _id: SimpleNamespace(first=AsyncMock(return_value=task))),
    )

    with pytest.raises(HTTPException) as exc_info:
        await execute_pipeline_stage(
            task_id=task.id,
            stage="build",
            runtime="acp",
            agent_id=None,
            model=None,
            session=object(),  # type: ignore[arg-type]
            _actor=actor,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Agent cannot execute work for a different board."
