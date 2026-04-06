from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.core.time import utcnow
from app.services.watchdog import recover_orphaned_running_runs
from app.services.watchdog import resume_idle_board_queues
from app.services.watchdog import retry_stuck_runs


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


@pytest.mark.asyncio
async def test_retry_stuck_runs_skips_opencode_plan_before_extended_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = utcnow()
    run = SimpleNamespace(
        id=uuid4(),
        task_id=uuid4(),
        runtime="opencode_cli",
        stage="plan",
        status="running",
        started_at=now - timedelta(minutes=45),
        finished_at=None,
        error_message=None,
        evidence_paths=[],
    )
    session = _FakeSession()

    monkeypatch.setattr(
        "app.models.runs.Run.objects",
        SimpleNamespace(
            filter_by=lambda **kwargs: SimpleNamespace(
                all=AsyncMock(return_value=[run] if kwargs == {"status": "running"} else [])
            )
        ),
    )
    monkeypatch.setattr("app.services.watchdog.resume_affected_board_queues", AsyncMock())

    retried = await retry_stuck_runs(session)  # type: ignore[arg-type]

    assert retried == []
    assert run.status == "running"
    session.add.assert_not_called()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_retry_stuck_runs_times_out_build_with_default_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = utcnow()
    run = SimpleNamespace(
        id=uuid4(),
        task_id=uuid4(),
        runtime="opencode_cli",
        stage="build",
        status="running",
        started_at=now - timedelta(minutes=45),
        finished_at=None,
        error_message=None,
        evidence_paths=[],
    )
    session = _FakeSession()

    monkeypatch.setattr(
        "app.models.runs.Run.objects",
        SimpleNamespace(
            filter_by=lambda **kwargs: SimpleNamespace(
                all=AsyncMock(return_value=[run] if kwargs == {"status": "running"} else [])
            )
        ),
    )
    resume_mock = AsyncMock(return_value={uuid4()})
    monkeypatch.setattr("app.services.watchdog.resume_affected_board_queues", resume_mock)

    retried = await retry_stuck_runs(session)  # type: ignore[arg-type]

    assert len(retried) == 1
    assert retried[0]["reason"] == "timeout"
    assert run.status == "failed"
    assert "45" not in (run.error_message or "")
    assert "30 minutes" in (run.error_message or "")
    session.add.assert_called_once_with(run)
    session.commit.assert_awaited_once()
    resume_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_retry_stuck_runs_skips_non_retryable_failed_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = utcnow()
    failed_run = SimpleNamespace(
        id=uuid4(),
        task_id=uuid4(),
        runtime="opencode_cli",
        stage="plan",
        status="failed",
        started_at=None,
        finished_at=now - timedelta(minutes=10),
        error_message="Daily limit reached",
        evidence_paths=[],
        retryable=False,
    )
    session = _FakeSession()

    monkeypatch.setattr(
        "app.models.runs.Run.objects",
        SimpleNamespace(
            filter_by=lambda **kwargs: SimpleNamespace(
                all=AsyncMock(return_value=[] if kwargs == {"status": "running"} else [failed_run])
            )
        ),
    )
    monkeypatch.setattr("app.services.watchdog.resume_affected_board_queues", AsyncMock())

    retried = await retry_stuck_runs(session)  # type: ignore[arg-type]

    assert retried == []
    assert failed_run.status == "failed"
    session.add.assert_not_called()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_retry_stuck_runs_skips_opencode_runs_while_board_quota_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = utcnow()
    failed_run = SimpleNamespace(
        id=uuid4(),
        task_id=uuid4(),
        runtime="opencode_cli",
        stage="build",
        status="failed",
        started_at=None,
        finished_at=now - timedelta(minutes=10),
        error_message="rate limit",
        evidence_paths=[],
        retryable=True,
    )
    board_id = uuid4()
    board = SimpleNamespace(
        id=board_id,
        execution_runtime_state={
            "runtime": "opencode_cli",
            "status": "cooldown",
            "failure_kind": "quota_exhausted",
            "cooldown_message": "Daily limit reached",
        },
    )
    session = _FakeSession()

    monkeypatch.setattr(
        "app.models.runs.Run.objects",
        SimpleNamespace(
            filter_by=lambda **kwargs: SimpleNamespace(
                all=AsyncMock(return_value=[] if kwargs == {"status": "running"} else [failed_run])
            )
        ),
    )
    monkeypatch.setattr("app.services.watchdog.get_board_id_for_run", AsyncMock(return_value=board_id))
    monkeypatch.setattr(
        "app.models.boards.Board.objects",
        SimpleNamespace(
            by_id=lambda _id: SimpleNamespace(first=AsyncMock(return_value=board))
        ),
    )
    monkeypatch.setattr("app.services.watchdog.resume_affected_board_queues", AsyncMock())

    retried = await retry_stuck_runs(session)  # type: ignore[arg-type]

    assert retried == []
    assert failed_run.status == "failed"
    session.add.assert_not_called()
    session.commit.assert_not_awaited()
