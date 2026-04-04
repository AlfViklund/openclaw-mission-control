from uuid import uuid4

from app.api.execution_runs import router as execution_runs_router
from app.main import app
from app.models.execution_runs import ExecutionArtifact, ExecutionRun
from app.schemas.executions import ExecutionArtifactCreate, ExecutionRunCreate


def test_execution_router_is_registered() -> None:
    assert execution_runs_router.prefix == "/boards/{board_id}/execution-runs"
    assert any(
        getattr(route, "path", None) == "/api/v1/boards/{board_id}/execution-runs/"
        for route in app.routes
    )


def test_execution_run_model_defaults() -> None:
    run = ExecutionRun(board_id=uuid4())
    assert run.scope == "task"
    assert run.runtime_kind == "opencode"
    assert run.status == "pending"
    assert run.current_phase == "plan"
    assert run.retry_count == 0


def test_execution_artifact_model_defaults_and_schemas() -> None:
    artifact_create = ExecutionArtifactCreate(kind="plan", title="Plan", body="Plan body")
    assert artifact_create.kind == "plan"
    assert artifact_create.title == "Plan"

    artifact = ExecutionArtifact(execution_run_id=uuid4(), kind="plan", title="Plan")
    assert artifact.kind == "plan"
    assert artifact.title == "Plan"


def test_execution_run_create_schema_defaults() -> None:
    payload = ExecutionRunCreate()
    assert payload.scope == "task"
    assert payload.runtime_kind == "opencode"
    assert payload.status == "pending"
    assert payload.current_phase == "plan"
