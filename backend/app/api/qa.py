"""QA API endpoints for test execution and reports."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import require_user
from app.db.session import get_session
from app.models.runs import Run
from app.schemas.common import OkResponse
from app.services.qa import QAService

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.api.deps import ActorContext

router = APIRouter(prefix="/qa", tags=["qa"])

SESSION_DEP = Depends(get_session)
USER_DEP = Depends(require_user)


@router.post("/test")
async def run_tests(
    task_id: UUID = Query(...),
    agent_id: UUID | None = Query(default=None),
    test_dir: str | None = Query(default=None),
    browsers: str | None = Query(default=None),
    grep: str | None = Query(default=None),
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = USER_DEP,
) -> dict:
    """Run Playwright tests for a task."""
    service = QAService(session)
    browser_list = browsers.split(",") if browsers else None
    try:
        result = await service.run_tests_for_task(
            task_id=task_id,
            agent_id=agent_id,
            test_dir=test_dir,
            browsers=browser_list,
            grep=grep,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return result


@router.get("/test/{run_id}/report")
async def get_test_report(
    run_id: UUID,
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = USER_DEP,
) -> dict:
    """Get the test report for a run."""
    run = await Run.objects.by_id(run_id).first(session)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    if run.stage != "test":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Run is not a test run",
        )
    return {
        "run_id": str(run.id),
        "status": run.status,
        "summary": run.summary,
        "evidence": run.evidence_paths,
        "error": run.error_message,
    }


@router.delete("/test/{run_id}/report")
async def delete_test_report(
    run_id: UUID,
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = USER_DEP,
) -> OkResponse:
    """Placeholder: delete test report evidence files."""
    return OkResponse(ok=True)
