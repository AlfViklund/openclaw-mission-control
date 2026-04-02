"""Watchdog API endpoints for health monitoring and ops commands."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import require_org_admin
from app.api.utils import http_status_for_value_error
from app.db.session import get_session
from app.schemas.common import OkResponse
from app.services.watchdog import (
    check_agent_heartbeats,
    check_escalations,
    reassign_tasks_from_offline_agents,
    reset_agent_session,
    retry_stuck_runs,
    rotate_agent_tokens,
    template_sync_agent,
    wake_agent,
)
from app.services.evidence_cleanup import cleanup_old_evidence

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.services.organizations import OrganizationContext

router = APIRouter(prefix="/watchdog", tags=["watchdog"])

SESSION_DEP = Depends(get_session)
ADMIN_DEP = Depends(require_org_admin)


@router.post("/check-heartbeats")
async def check_heartbeats(
    session: AsyncSession = SESSION_DEP,
    _ctx: OrganizationContext = ADMIN_DEP,
) -> dict:
    """Check all agent heartbeats and mark offline if needed."""
    transitions = await check_agent_heartbeats(session)
    return {
        "offline_transitions": transitions,
        "count": len(transitions),
    }


@router.post("/retry-stuck-runs")
async def retry_stuck(
    session: AsyncSession = SESSION_DEP,
    _ctx: OrganizationContext = ADMIN_DEP,
) -> dict:
    """Auto-retry stuck or failed runs."""
    retried = await retry_stuck_runs(session)
    return {
        "retried": retried,
        "count": len(retried),
    }


@router.post("/reassign-tasks")
async def reassign_tasks(
    session: AsyncSession = SESSION_DEP,
    _ctx: OrganizationContext = ADMIN_DEP,
) -> dict:
    """Reassign tasks from offline agents back to inbox."""
    reassigned = await reassign_tasks_from_offline_agents(session)
    return {
        "reassigned": reassigned,
        "count": len(reassigned),
    }


@router.get("/escalations")
async def get_escalations(
    session: AsyncSession = SESSION_DEP,
    _ctx: OrganizationContext = ADMIN_DEP,
) -> dict:
    """Check for conditions requiring human escalation."""
    escalations = await check_escalations(session)
    return {
        "escalations": escalations,
        "count": len(escalations),
    }


@router.post("/agents/{agent_id}/template-sync")
async def sync_agent_templates(
    agent_id: UUID,
    session: AsyncSession = SESSION_DEP,
    _ctx: OrganizationContext = ADMIN_DEP,
) -> dict:
    """Trigger template sync for an agent."""
    try:
        return await template_sync_agent(session, agent_id)
    except ValueError as exc:
        message = str(exc)
        raise HTTPException(status_code=http_status_for_value_error(message), detail=message) from exc


@router.post("/agents/{agent_id}/rotate-tokens")
async def rotate_tokens(
    agent_id: UUID,
    session: AsyncSession = SESSION_DEP,
    _ctx: OrganizationContext = ADMIN_DEP,
) -> dict:
    """Rotate auth tokens for an agent."""
    try:
        return await rotate_agent_tokens(session, agent_id)
    except ValueError as exc:
        message = str(exc)
        raise HTTPException(status_code=http_status_for_value_error(message), detail=message) from exc


@router.post("/agents/{agent_id}/reset-session")
async def reset_session(
    agent_id: UUID,
    session: AsyncSession = SESSION_DEP,
    _ctx: OrganizationContext = ADMIN_DEP,
) -> dict:
    """Reset an agent's session."""
    try:
        return await reset_agent_session(session, agent_id)
    except ValueError as exc:
        message = str(exc)
        raise HTTPException(status_code=http_status_for_value_error(message), detail=message) from exc


@router.post("/agents/{agent_id}/wake")
async def wake(
    agent_id: UUID,
    session: AsyncSession = SESSION_DEP,
    _ctx: OrganizationContext = ADMIN_DEP,
) -> dict:
    """Wake a sleeping/offline agent."""
    try:
        return await wake_agent(session, agent_id)
    except ValueError as exc:
        message = str(exc)
        raise HTTPException(status_code=http_status_for_value_error(message), detail=message) from exc


@router.post("/cleanup-evidence")
async def cleanup_evidence(
    retention_days: int = Query(default=30, ge=1),
    _ctx: OrganizationContext = ADMIN_DEP,
) -> dict:
    """Archive evidence files older than retention period."""
    return cleanup_old_evidence(retention_days=retention_days)


@router.post("/health-check")
async def full_health_check(
    session: AsyncSession = SESSION_DEP,
    _ctx: OrganizationContext = ADMIN_DEP,
) -> dict:
    """Run full watchdog health check: heartbeats, retries, reassign, escalations."""
    heartbeats = await check_agent_heartbeats(session)
    retried = await retry_stuck_runs(session)
    reassigned = await reassign_tasks_from_offline_agents(session)
    escalations = await check_escalations(session)

    return {
        "heartbeats": {
            "offline_transitions": heartbeats,
            "count": len(heartbeats),
        },
        "retries": {
            "retried_runs": retried,
            "count": len(retried),
        },
        "reassignments": {
            "reassigned_tasks": reassigned,
            "count": len(reassigned),
        },
        "escalations": {
            "events": escalations,
            "count": len(escalations),
        },
    }
