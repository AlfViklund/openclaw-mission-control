from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.watchdog import recover_orphaned_running_runs
from app.services.watchdog import resume_idle_board_queues


class _FakeSession:
    def __init__(self) -> None:
        self.add = MagicMock()
        self.commit = AsyncMock()


@pytest.mark.asyncio
async def test_recover_orphaned_running_runs_marks_local_runtime_runs_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = SimpleNamespace(
        id=uuid4(),
        task_id=uuid4(),
        runtime="opencode_cli",
        status="running",
        finished_at=None,
        failure_kind=None,
        error_message=None,
    )
    session = _FakeSession()

    monkeypatch.setattr(
        "app.models.runs.Run.objects",
        SimpleNamespace(
            filter=lambda *_args, **_kwargs: SimpleNamespace(all=AsyncMock(return_value=[run]))
        ),
    )
    resume_mock = AsyncMock(return_value={uuid4()})
    monkeypatch.setattr("app.services.watchdog.resume_affected_board_queues", resume_mock)

    recovered = await recover_orphaned_running_runs(session)  # type: ignore[arg-type]

    assert len(recovered) == 1
    assert recovered[0]["run_id"] == str(run.id)
    assert run.status == "failed"
    assert run.failure_kind == "runtime_restarted"
    assert "backend restart" in run.error_message
    session.add.assert_called_once_with(run)
    session.commit.assert_awaited_once()
    resume_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_resume_idle_board_queues_schedules_each_idle_board(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    board_ids = {uuid4(), uuid4()}
    scheduled: list[UUID] = []

    async def _fake_queued_board_ids_without_running(_session: object) -> set[UUID]:
        return board_ids

    def _fake_create_task(coro):
        frame = getattr(coro, "cr_frame", None)
        if frame is not None and "board_id" in frame.f_locals:
            scheduled.append(frame.f_locals["board_id"])
        coro.close()
        return SimpleNamespace()

    monkeypatch.setattr(
        "app.services.watchdog._queued_board_ids_without_running",
        _fake_queued_board_ids_without_running,
    )
    monkeypatch.setattr("app.services.watchdog.asyncio.create_task", _fake_create_task)

    resumed = await resume_idle_board_queues(object())  # type: ignore[arg-type]

    assert resumed == board_ids
    assert set(scheduled) == board_ids
