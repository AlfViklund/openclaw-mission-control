# ruff: noqa: S101
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.planner import expand_planner_output_endpoint, generate_backlog_endpoint
from app.schemas.planner import PlannerExpandRequest, PlannerGenerateRequest


@pytest.mark.asyncio
async def test_generate_backlog_endpoint_uses_artifact_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_id = uuid4()
    board_id = uuid4()
    artifact = SimpleNamespace(id=artifact_id, board_id=board_id)
    planner_output = SimpleNamespace(id=uuid4(), artifact_id=artifact_id, board_id=board_id)

    async def _fake_get_artifact_by_id(session: object, value: object) -> object:
        assert session is not None
        assert value == artifact_id
        return artifact

    monkeypatch.setattr("app.api.planner.get_artifact_by_id", _fake_get_artifact_by_id)

    async def _fake_generate_backlog(
        session: object,
        *,
        artifact_id: object,
        board_id: object,
        max_tasks: int,
        created_by: object,
        force: bool,
    ) -> object:
        assert artifact_id == artifact.id
        assert board_id == artifact.board_id
        assert max_tasks == 50
        assert created_by == "user-1"
        assert force is True
        assert session is not None
        return planner_output

    monkeypatch.setattr("app.api.planner.generate_backlog", _fake_generate_backlog)

    result = await generate_backlog_endpoint(
        payload=PlannerGenerateRequest(artifact_id=artifact_id, max_tasks=50),
        force=True,
        session=object(),  # type: ignore[arg-type]
        user=SimpleNamespace(user=SimpleNamespace(id="user-1")),  # type: ignore[arg-type]
    )

    assert result == planner_output


@pytest.mark.asyncio
async def test_generate_backlog_endpoint_raises_404_when_artifact_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_id = uuid4()

    async def _fake_get_artifact_by_id(_session: object, value: object) -> object | None:
        assert value == artifact_id
        return None

    monkeypatch.setattr("app.api.planner.get_artifact_by_id", _fake_get_artifact_by_id)

    with pytest.raises(HTTPException) as exc_info:
        await generate_backlog_endpoint(
            payload=PlannerGenerateRequest(artifact_id=artifact_id, max_tasks=50),
            force=False,
            session=object(),  # type: ignore[arg-type]
            user=SimpleNamespace(user=None),  # type: ignore[arg-type]
        )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_expand_planner_output_endpoint_queues_expansion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner_output_id = uuid4()
    planner_output = SimpleNamespace(id=planner_output_id, status="applied")

    async def _fake_get_planner_output_by_id(_session: object, value: object) -> object:
        assert value == planner_output_id
        return planner_output

    async def _fake_queue_planner_expansion(
        session: object,
        *,
        planner_output: object,
        trigger: str,
        max_new_tasks: int | None,
    ) -> object:
        assert session is not None
        assert planner_output is not None
        assert trigger == "manual"
        assert max_new_tasks == 5
        return planner_output

    monkeypatch.setattr(
        "app.api.planner.get_planner_output_by_id",
        _fake_get_planner_output_by_id,
    )
    monkeypatch.setattr(
        "app.api.planner.queue_planner_expansion",
        _fake_queue_planner_expansion,
    )

    result = await expand_planner_output_endpoint(
        planner_output_id=planner_output_id,
        payload=PlannerExpandRequest(trigger="manual", max_new_tasks=5),
        session=object(),  # type: ignore[arg-type]
        _actor=SimpleNamespace(),
    )

    assert result == planner_output
