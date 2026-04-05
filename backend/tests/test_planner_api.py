# ruff: noqa: S101
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.planner import generate_backlog_endpoint
from app.schemas.planner import PlannerGenerateRequest


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
