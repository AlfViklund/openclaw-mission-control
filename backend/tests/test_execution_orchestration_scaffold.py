from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.boards import Board
from app.models.execution_runs import ExecutionArtifact, ExecutionRun
from app.models.organizations import Organization
from app.services.execution_orchestration import (
    AcpRuntimeAdapter,
    ExecutionOrchestrationService,
    OpenCodeRuntimeAdapter,
)


async def _make_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine


async def _seed_board(session: AsyncSession) -> Board:
    organization = Organization(id=uuid4(), name="Runtime Org")
    board = Board(
        id=uuid4(),
        organization_id=organization.id,
        name="Runtime board",
        slug="runtime-board",
        description="Board for runtime scaffolding tests.",
    )
    session.add(organization)
    session.add(board)
    await session.commit()
    return board


@pytest.mark.asyncio
async def test_runtime_adapters_build_phase_instructions() -> None:
    run = ExecutionRun(board_id=uuid4())
    instruction = OpenCodeRuntimeAdapter().build_instruction(
        run=run,
        board_title="Mission Control",
        task_title="Ship runtime orchestration",
        context="Use the current execution state as input.",
    )

    assert instruction.runtime_kind == "opencode"
    assert instruction.phase == "plan"
    assert instruction.evidence_kind == "plan"
    assert "PLAN -> BUILD -> TEST -> REVIEW -> DONE" in instruction.prompt
    assert "Ship runtime orchestration" in instruction.prompt

    acp_instruction = AcpRuntimeAdapter().build_instruction(
        run=ExecutionRun(board_id=uuid4(), current_phase="review"),
        board_title="Mission Control",
    )
    assert acp_instruction.runtime_kind == "acp"
    assert acp_instruction.phase == "review"
    assert acp_instruction.evidence_kind == "review"
    assert "ACP" in acp_instruction.prompt


@pytest.mark.asyncio
async def test_execution_orchestration_service_records_phase_progress_and_evidence() -> None:
    engine = await _make_engine()
    session_maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_maker() as session:
        board = await _seed_board(session)
        run = ExecutionRun(board_id=board.id)
        session.add(run)
        await session.commit()
        await session.refresh(run)

        service = ExecutionOrchestrationService(session)

        started = await service.start_run(
            board_id=board.id,
            run_id=run.id,
            runtime_session_key="opencode:session-1",
            execution_state_patch={"runner": "opencode"},
            recovery_state_patch={"attempt": 1},
        )
        assert started.status == "running"
        assert started.current_phase == "plan"
        assert started.runtime_session_key == "opencode:session-1"
        assert started.execution_state == {"runner": "opencode"}
        assert started.recovery_state == {"attempt": 1}
        assert started.started_at is not None

        plan_artifact = await service.record_phase_result(
            board_id=board.id,
            run_id=run.id,
            phase="plan",
            title="Plan evidence",
            body="Plan the implementation and test approach.",
            artifact_state={"step": 1},
            execution_state_patch={"plan": "ready"},
        )
        assert plan_artifact.kind == "plan"

        build_artifact = await service.record_phase_result(
            board_id=board.id,
            run_id=run.id,
            phase="build",
            title="Build evidence",
            body="Implemented the runtime scaffold.",
            artifact_state={"step": 2},
        )
        assert build_artifact.kind == "build"

        test_artifact = await service.record_phase_result(
            board_id=board.id,
            run_id=run.id,
            phase="test",
            title="Test evidence",
            body="Verified the scaffold with automated checks.",
            artifact_state={"step": 3},
        )
        assert test_artifact.kind == "test"

        review_artifact = await service.record_phase_result(
            board_id=board.id,
            run_id=run.id,
            phase="review",
            title="Review evidence",
            body="Verified the scaffold and tests.",
            artifact_state={"step": 4},
        )
        assert review_artifact.kind == "review"

        refreshed_run = await session.get(ExecutionRun, run.id)
        assert refreshed_run is not None
        assert refreshed_run.status == "done"
        assert refreshed_run.current_phase == "done"
        assert refreshed_run.plan_summary == "Plan the implementation and test approach."
        assert refreshed_run.build_summary == "Implemented the runtime scaffold."
        assert refreshed_run.test_summary == "Verified the scaffold with automated checks."
        assert refreshed_run.execution_state is not None
        assert refreshed_run.execution_state["runner"] == "opencode"
        assert refreshed_run.execution_state["plan"] == "ready"
        assert refreshed_run.execution_state["review_summary"] == "Verified the scaffold and tests."
        assert refreshed_run.completed_at is not None

        artifacts = list(
            await session.exec(
                select(ExecutionArtifact)
                .where(ExecutionArtifact.execution_run_id == run.id)
                .order_by(ExecutionArtifact.created_at),
            ),
        )
        assert [artifact.kind for artifact in artifacts] == ["plan", "build", "test", "review"]
        assert artifacts[0].artifact_state == {"step": 1}
        assert artifacts[3].body == "Verified the scaffold and tests."
