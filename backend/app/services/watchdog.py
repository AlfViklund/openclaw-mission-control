"""Watchdog service for agent health monitoring and auto-recovery."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from sqlmodel import col, select

from app.core.time import utcnow
from app.models.agents import Agent
from app.models.runs import Run
from app.models.task_dependencies import TaskDependency
from app.models.tasks import Task

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger(__name__)

DEFAULT_MISSING_TOLERANCE_MULTIPLIER = 3
MAX_RUN_DURATION_MINUTES = 30
MAX_RETRY_ATTEMPTS = 3
ESCALATION_OFFLINE_MINUTES = 15
ESCALATION_BLOCKED_MINUTES = 60


async def check_agent_heartbeats(session: AsyncSession) -> list[dict]:
    """Check all agents for missed heartbeats and mark offline if needed."""
    now = utcnow()
    offline_transitions = []

    agents = await Agent.objects.filter(col(Agent.status).in_(["online", "idle", "dormant"])).all(session)

    for agent in agents:
        if not agent.last_seen_at:
            continue

        hb_config = agent.heartbeat_config or {}
        interval_str = hb_config.get("every", "10m")
        interval_minutes = _parse_interval(interval_str)
        tolerance = interval_minutes * DEFAULT_MISSING_TOLERANCE_MULTIPLIER
        if agent.status == "idle":
            tolerance *= 3
        elif agent.status == "dormant":
            tolerance *= 12

        missed = now - agent.last_seen_at
        if missed > timedelta(minutes=tolerance):
            logger.warning(
                "Agent %s (%s) missed heartbeat: last_seen=%s, tolerance=%sm",
                agent.name,
                agent.id,
                agent.last_seen_at,
                tolerance,
            )
            agent.status = "offline"
            session.add(agent)
            offline_transitions.append({
                "agent_id": str(agent.id),
                "agent_name": agent.name,
                "last_seen": agent.last_seen_at.isoformat(),
                "tolerance_minutes": tolerance,
            })

    if offline_transitions:
        await session.commit()

    return offline_transitions


async def retry_stuck_runs(session: AsyncSession) -> list[dict]:
    """Auto-retry runs that are stuck (running too long) or failed with retries left."""
    now = utcnow()
    retried = []

    stuck_runs = await Run.objects.filter_by(status="running").all(session)
    timed_out_ids: set[UUID] = set()
    for run in stuck_runs:
        if run.started_at and (now - run.started_at) > timedelta(minutes=MAX_RUN_DURATION_MINUTES):
            run.status = "failed"
            run.finished_at = now
            run.error_message = f"Run timed out after {MAX_RUN_DURATION_MINUTES} minutes"
            session.add(run)
            timed_out_ids.add(run.id)
            retried.append({
                "run_id": str(run.id),
                "task_id": str(run.task_id),
                "reason": "timeout",
            })

    failed_runs = await Run.objects.filter_by(status="failed").all(session)
    for run in failed_runs:
        if run.id in timed_out_ids:
            continue

        retry_count = sum(
            1 for e in run.evidence_paths if e.get("type") == "retry"
        ) if run.evidence_paths else 0

        if retry_count < MAX_RETRY_ATTEMPTS and run.finished_at:
            if now - run.finished_at > timedelta(minutes=5):
                run.status = "queued"
                run.started_at = None
                run.finished_at = None
                run.error_message = None
                run.evidence_paths.append({
                    "type": "retry",
                    "attempt": retry_count + 1,
                    "scheduled_at": now.isoformat(),
                })
                session.add(run)
                retried.append({
                    "run_id": str(run.id),
                    "task_id": str(run.task_id),
                    "reason": f"retry {retry_count + 1}/{MAX_RETRY_ATTEMPTS}",
                })

    if retried:
        await session.commit()

    return retried


async def reassign_tasks_from_offline_agents(session: AsyncSession) -> list[dict]:
    """Reassign in_progress tasks from offline agents back to inbox."""
    offline_agents = await Agent.objects.filter_by(status="offline").all(session)
    offline_ids = {a.id for a in offline_agents}

    if not offline_ids:
        return []

    tasks = await session.exec(select(Task).where(col(Task.status) == "in_progress")).all()
    reassigned = []

    for task in tasks:
        if task.assigned_agent_id in offline_ids:
            prev_agent = task.assigned_agent_id
            task.in_progress_at = None
            task.status = "inbox"
            task.assigned_agent_id = None
            session.add(task)
            reassigned.append({
                "task_id": str(task.id),
                "task_title": task.title,
                "previous_agent": str(prev_agent),
            })

    if reassigned:
        await session.commit()

    return reassigned


async def check_escalations(session: AsyncSession) -> list[dict]:
    """Check for conditions requiring human escalation."""
    now = utcnow()
    escalations = []

    offline_agents = await Agent.objects.filter_by(status="offline").all(session)
    for agent in offline_agents:
        if agent.last_seen_at:
            offline_duration = now - agent.last_seen_at
            if offline_duration > timedelta(minutes=ESCALATION_OFFLINE_MINUTES):
                escalations.append({
                    "type": "agent_offline",
                    "agent_id": str(agent.id),
                    "agent_name": agent.name,
                    "duration_minutes": offline_duration.total_seconds() / 60,
                    "severity": "high",
                })

    recent_cutoff = now - timedelta(hours=24)
    failed_runs = await session.exec(
        select(Run).where(
            col(Run.status) == "failed",
            col(Run.finished_at) >= recent_cutoff,
        )
    ).all()
    for run in failed_runs:
        retry_count = sum(
            1 for e in run.evidence_paths if e.get("type") == "retry"
        ) if run.evidence_paths else 0
        if retry_count >= MAX_RETRY_ATTEMPTS:
            escalations.append({
                "type": "run_failed_max_retries",
                "run_id": str(run.id),
                "task_id": str(run.task_id),
                "stage": run.stage,
                "severity": "high",
            })

    inbox_tasks = await session.exec(
        select(Task).where(col(Task.status) == "inbox")
    ).all()
    for task in inbox_tasks:
        deps_result = await session.exec(
            select(TaskDependency).where(col(TaskDependency.task_id) == task.id)
        )
        deps = deps_result.all()
        if not deps:
            continue

        dep_ids = [d.depends_on_task_id for d in deps]
        dep_tasks_result = await session.exec(
            select(Task).where(col(Task.id).in_(dep_ids))
        )
        dep_tasks = dep_tasks_result.all()
        all_blocked = all(t.status not in ("done", "review") for t in dep_tasks)
        if all_blocked and task.in_progress_at:
            blocked_since = now - task.in_progress_at
            if blocked_since > timedelta(minutes=ESCALATION_BLOCKED_MINUTES):
                escalations.append({
                    "type": "task_blocked",
                    "task_id": str(task.id),
                    "task_title": task.title,
                    "blocked_minutes": blocked_since.total_seconds() / 60,
                    "severity": "medium",
                })

    return escalations


async def template_sync_agent(session: AsyncSession, agent_id: UUID) -> dict:
    """Trigger template sync for an agent via gateway RPC."""
    agent = await Agent.objects.by_id(agent_id).first(session)
    if not agent:
        raise ValueError(f"Agent {agent_id} not found")

    agent.status = "provisioning"
    session.add(agent)
    await session.commit()

    try:
        from app.models.boards import Board
        from app.services.openclaw.provisioning_db import AgentLifecycleService

        board = await Board.objects.by_id(agent.board_id).first(session)
        if board:
            lifecycle = AgentLifecycleService(session)
            await lifecycle.sync_agent_templates(agent_id=str(agent_id), board_id=str(board.id))
            sync_status = "sync_completed"
        else:
            sync_status = "sync_db_only_no_board"
    except Exception as exc:
        logger.warning("Template sync gateway call failed for agent %s: %s", agent_id, exc)
        sync_status = "sync_db_only_gateway_failed"

    return {
        "agent_id": str(agent.id),
        "agent_name": agent.name,
        "status": sync_status,
    }


async def rotate_agent_tokens(session: AsyncSession, agent_id: UUID) -> dict:
    """Rotate auth tokens for an agent via gateway RPC."""
    agent = await Agent.objects.by_id(agent_id).first(session)
    if not agent:
        raise ValueError(f"Agent {agent_id} not found")

    agent.agent_token_hash = None
    agent.status = "provisioning"
    session.add(agent)
    await session.commit()

    try:
        from app.models.boards import Board
        from app.services.openclaw.provisioning_db import AgentLifecycleService

        board = await Board.objects.by_id(agent.board_id).first(session)
        if board:
            lifecycle = AgentLifecycleService(session)
            await lifecycle.rotate_agent_token(agent_id=str(agent_id), board_id=str(board.id))
            rotate_status = "rotation_completed"
        else:
            rotate_status = "rotation_db_only_no_board"
    except Exception as exc:
        logger.warning("Token rotation gateway call failed for agent %s: %s", agent_id, exc)
        rotate_status = "rotation_db_only_gateway_failed"

    return {
        "agent_id": str(agent.id),
        "agent_name": agent.name,
        "status": rotate_status,
    }


async def reset_agent_session(session: AsyncSession, agent_id: UUID) -> dict:
    """Reset an agent's session via gateway RPC."""
    agent = await Agent.objects.by_id(agent_id).first(session)
    if not agent:
        raise ValueError(f"Agent {agent_id} not found")

    agent.openclaw_session_id = None
    agent.status = "provisioning"
    session.add(agent)
    await session.commit()

    try:
        from app.models.boards import Board
        from app.services.openclaw.provisioning_db import AgentLifecycleService

        board = await Board.objects.by_id(agent.board_id).first(session)
        if board:
            lifecycle = AgentLifecycleService(session)
            await lifecycle.reset_agent_session(agent_id=str(agent_id), board_id=str(board.id))
            reset_status = "reset_completed"
        else:
            reset_status = "reset_db_only_no_board"
    except Exception as exc:
        logger.warning("Session reset gateway call failed for agent %s: %s", agent_id, exc)
        reset_status = "reset_db_only_gateway_failed"

    return {
        "agent_id": str(agent.id),
        "agent_name": agent.name,
        "status": reset_status,
    }


async def wake_agent(session: AsyncSession, agent_id: UUID) -> dict:
    """Wake a sleeping/offline agent via gateway RPC."""
    agent = await Agent.objects.by_id(agent_id).first(session)
    if not agent:
        raise ValueError(f"Agent {agent_id} not found")

    agent.wake_attempts = (agent.wake_attempts or 0) + 1
    agent.last_wake_sent_at = utcnow()
    agent.checkin_deadline_at = utcnow() + timedelta(seconds=30)
    session.add(agent)
    await session.commit()

    try:
        from app.models.boards import Board
        from app.services.openclaw.provisioning_db import AgentLifecycleService

        board = await Board.objects.by_id(agent.board_id).first(session)
        if board:
            lifecycle = AgentLifecycleService(session)
            await lifecycle.wake_agent(agent_id=str(agent_id), board_id=str(board.id))
            wake_status = "wake_completed"
        else:
            wake_status = "wake_db_only_no_board"
    except Exception as exc:
        logger.warning("Wake gateway call failed for agent %s: %s", agent_id, exc)
        wake_status = "wake_db_only_gateway_failed"

    return {
        "agent_id": str(agent.id),
        "agent_name": agent.name,
        "status": wake_status,
        "wake_attempts": agent.wake_attempts,
    }


def _parse_interval(interval_str: str) -> float:
    """Parse interval string like '5m', '10m', '2h' to minutes."""
    interval_str = interval_str.strip().lower()
    if interval_str.endswith("h"):
        return float(interval_str[:-1]) * 60
    if interval_str.endswith("m"):
        return float(interval_str[:-1])
    if interval_str.endswith("s"):
        return float(interval_str[:-1]) / 60
    return float(interval_str)
