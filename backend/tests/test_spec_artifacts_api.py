# ruff: noqa: INP001
"""Integration tests for spec artifact planner endpoints."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_board_for_actor_read, get_board_for_actor_write
from app.api.spec_artifacts import router as spec_artifacts_router
from app.db.session import get_session
from app.models.boards import Board
from app.models.organizations import Organization
from app.models.spec_artifacts import SpecArtifact
from app.models.task_dependencies import TaskDependency
from app.models.tasks import Task
from app.services.spec_planner import build_planner_draft


async def _make_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine


def _build_test_app(
    session_maker: async_sessionmaker[AsyncSession],
    board: Board,
) -> FastAPI:
    app = FastAPI()
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(spec_artifacts_router)
    app.include_router(api_v1)

    async def _override_get_session() -> AsyncSession:
        async with session_maker() as session:
            yield session

    async def _override_board_dep(
        board_id: str,
        session: AsyncSession = Depends(get_session),
    ) -> Board:
        loaded = await Board.objects.by_id(UUID(board_id)).first(session)
        if loaded is None:
            from fastapi import HTTPException, status

            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return loaded

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_board_for_actor_read] = _override_board_dep
    app.dependency_overrides[get_board_for_actor_write] = _override_board_dep
    return app


async def _seed_board(session: AsyncSession) -> Board:
    organization = Organization(id=uuid4(), name="Spec Org")
    board = Board(
        id=uuid4(),
        organization_id=organization.id,
        name="Planner board",
        slug="planner-board",
        description="Board for planner tests.",
    )
    session.add(organization)
    session.add(board)
    await session.commit()
    return board


@pytest.mark.asyncio
async def test_spec_artifact_router_is_registered() -> None:
    assert spec_artifacts_router.prefix == "/boards/{board_id}/spec-artifacts"


@pytest.mark.asyncio
async def test_build_planner_draft_extracts_outline_hierarchy() -> None:
    artifact = SpecArtifact(
        id=uuid4(),
        board_id=uuid4(),
        title="Launch dashboard",
        body=(
            "# Launch dashboard\n"
            "## Backend\n"
            "- Add planner API\n"
            "- Add tests\n"
            "## Frontend\n"
            "- Add dashboard widget\n"
        ),
        source="markdown",
    )

    draft = build_planner_draft(artifact)

    assert draft.spec_artifact_id == artifact.id
    assert draft.node_count == 6
    assert [node.title for node in draft.nodes] == [
        "Launch dashboard",
        "Backend",
        "Add planner API",
        "Add tests",
        "Frontend",
        "Add dashboard widget",
    ]
    assert draft.nodes[1].depends_on_keys == ["node-1"]
    assert draft.nodes[2].depends_on_keys == ["node-2"]
    assert draft.nodes[4].depends_on_keys == ["node-1"]
    assert draft.nodes[5].depends_on_keys == ["node-5"]


@pytest.mark.asyncio
async def test_spec_artifact_apply_creates_tasks_and_dependencies() -> None:
    engine = await _make_engine()
    session_maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_maker() as session:
        board = await _seed_board(session)

    app = _build_test_app(session_maker, board)
    spec_body = (
        "# Launch dashboard\n"
        "## Backend\n"
        "- Add planner API\n"
        "- Add tests\n"
        "## Frontend\n"
        "- Add dashboard widget\n"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        create_response = await client.post(
            f"/api/v1/boards/{board.id}/spec-artifacts/",
            json={
                "title": "Launch dashboard",
                "body": spec_body,
                "source": "markdown",
            },
        )
        assert create_response.status_code == 201
        spec_artifact_id = create_response.json()["id"]

        draft_response = await client.post(
            f"/api/v1/boards/{board.id}/spec-artifacts/{spec_artifact_id}/draft",
        )
        assert draft_response.status_code == 200
        draft_payload = draft_response.json()
        assert draft_payload["node_count"] == 6

        apply_response = await client.post(
            f"/api/v1/boards/{board.id}/spec-artifacts/{spec_artifact_id}/apply",
        )
        assert apply_response.status_code == 200
        tasks = apply_response.json()
        assert len(tasks) == 6
        assert tasks[0]["depends_on_task_ids"] == []
        assert tasks[1]["depends_on_task_ids"] == [tasks[0]["id"]]
        assert tasks[2]["depends_on_task_ids"] == [tasks[1]["id"]]
        assert tasks[3]["depends_on_task_ids"] == [tasks[1]["id"]]
        assert tasks[4]["depends_on_task_ids"] == [tasks[0]["id"]]
        assert tasks[5]["depends_on_task_ids"] == [tasks[4]["id"]]

    async with session_maker() as session:
        task_rows = list(
            await session.exec(
                select(Task).where(Task.board_id == board.id).order_by(Task.created_at),
            ),
        )
        dependency_rows = list(
            await session.exec(
                select(TaskDependency).where(TaskDependency.board_id == board.id),
            ),
        )
        assert len(task_rows) == 6
        assert len(dependency_rows) == 5
