"""Tests for PipelineService execute_stage, auto_run_next_stage, resume_after_approval."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.pipeline import PipelineService, STAGE_ORDER


def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.exec = AsyncMock()
    return session


class TestAutoRunNextStage:
    """Tests for _auto_run_next_stage logic."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_next_stage(self) -> None:
        session = _make_session()
        run = SimpleNamespace(
            id=uuid4(),
            task_id=uuid4(),
            agent_id=uuid4(),
            runtime="acp",
            stage="test",
            status="succeeded",
            model=None,
        )

        with patch(
            "app.models.runs.Run.objects",
            new_callable=lambda: SimpleNamespace(
                by_id=lambda _id: SimpleNamespace(first=AsyncMock(return_value=run))
            ),
        ):
            svc = PipelineService(session)
            result = await svc._auto_run_next_stage(run.id)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_run_not_succeeded(self) -> None:
        session = _make_session()
        run = SimpleNamespace(
            id=uuid4(),
            task_id=uuid4(),
            agent_id=uuid4(),
            runtime="acp",
            stage="plan",
            status="failed",
            model=None,
        )

        with patch(
            "app.models.runs.Run.objects",
            new_callable=lambda: SimpleNamespace(
                by_id=lambda _id: SimpleNamespace(first=AsyncMock(return_value=run))
            ),
        ):
            svc = PipelineService(session)
            result = await svc._auto_run_next_stage(run.id)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_run_is_none(self) -> None:
        session = _make_session()

        with patch(
            "app.models.runs.Run.objects",
            new_callable=lambda: SimpleNamespace(
                by_id=lambda _id: SimpleNamespace(first=AsyncMock(return_value=None))
            ),
        ):
            svc = PipelineService(session)
            result = await svc._auto_run_next_stage(uuid4())

        assert result is None


class TestResumeAfterApproval:
    """Tests for resume_after_approval logic."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_plan_run(self) -> None:
        session = _make_session()
        task_id = uuid4()

        chain = SimpleNamespace(
            order_by=lambda _x: SimpleNamespace(first=AsyncMock(return_value=None))
        )

        with patch(
            "app.models.runs.Run.objects",
            new_callable=lambda: SimpleNamespace(
                filter_by=lambda **_kw: chain
            ),
        ):
            svc = PipelineService(session)
            result = await svc.resume_after_approval(task_id)

        assert result is None


class TestStageOrder:
    """Tests for STAGE_ORDER consistency."""

    def test_plan_comes_before_build(self) -> None:
        assert STAGE_ORDER.index("plan") < STAGE_ORDER.index("build")

    def test_build_comes_before_test(self) -> None:
        assert STAGE_ORDER.index("build") < STAGE_ORDER.index("test")

    def test_three_stages(self) -> None:
        assert len(STAGE_ORDER) == 3
