from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.watchdog import recover_orphaned_running_runs


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

    recovered = await recover_orphaned_running_runs(session)  # type: ignore[arg-type]

    assert len(recovered) == 1
    assert recovered[0]["run_id"] == str(run.id)
    assert run.status == "failed"
    assert run.failure_kind == "runtime_restarted"
    assert "backend restart" in run.error_message
    session.add.assert_called_once_with(run)
    session.commit.assert_awaited_once()
