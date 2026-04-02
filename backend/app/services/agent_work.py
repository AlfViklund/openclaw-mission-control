"""Agent work-snapshot service — cheap data-driven decision about whether an agent should wake."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlmodel import col, select

from app.models.agents import Agent
from app.models.approvals import Approval
from app.models.runs import Run
from app.models.tasks import Task

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession


WAKE_REASONS = frozenset({
    "assigned_in_progress_task",
    "assigned_inbox_task",
    "pending_approval",
    "manual_nudge",
    "watchdog_recovery",
    "new_spec_artifact",
    "planner_output_ready",
    "review_queue",
    "busy_existing_run",
    "idle_no_work",
})


async def get_work_snapshot(
    session: AsyncSession,
    agent_id: UUID,
) -> dict:
    """Return a lightweight work snapshot for an agent.

    This endpoint answers the question "should this agent wake up and do
    heavy work?" without any reasoning, memory pulls, or assist-mode
    overhead.

    Returns a dict suitable for JSON serialization containing:
    - board_id, board_paused
    - assigned_in_progress_task_id
    - assigned_inbox_task_ids
    - pending_approvals_count
    - review_tasks_count
    - active_run_id (busy gating)
    - should_wake, reason
    """
    agent = await Agent.objects.by_id(agent_id).first(session)
    if agent is None:
        raise ValueError(f"Agent {agent_id} not found")

    board_id = agent.board_id
    if board_id is None:
        return _empty_snapshot(agent_id)

    # -- Board pause state --
    from app.models.boards import Board
    board = await Board.objects.by_id(board_id).first(session)
    board_paused = bool(board and getattr(board, "is_paused", False))

    # -- Busy gating: is there an active run for this agent? --
    active_run_statement = (
        select(Run)
        .where(col(Run.agent_id) == agent_id, col(Run.status) == "running")
        .order_by(col(Run.created_at).desc())
        .limit(1)
    )
    active_run = (await session.exec(active_run_statement)).first()
    active_run_id = str(active_run.id) if active_run else None

    if active_run_id:
        return {
            "board_id": str(board_id),
            "board_paused": board_paused,
            "assigned_in_progress_task_id": None,
            "assigned_inbox_task_ids": [],
            "pending_approvals_count": 0,
            "review_tasks_count": 0,
            "active_run_id": active_run_id,
            "should_wake": False,
            "reason": "busy_existing_run",
        }

    # -- Assigned tasks --
    tasks_statement = (
        select(Task)
        .where(
            col(Task.assigned_agent_id) == agent_id,
            col(Task.board_id) == board_id,
            col(Task.status).in_(["in_progress", "inbox", "review"]),
        )
    )
    tasks = (await session.exec(tasks_statement)).all()

    assigned_in_progress_task_id = None
    assigned_inbox_task_ids: list[str] = []
    review_tasks_count = 0

    for task in tasks:
        if task.status == "in_progress" and assigned_in_progress_task_id is None:
            assigned_in_progress_task_id = str(task.id)
        elif task.status == "inbox":
            assigned_inbox_task_ids.append(str(task.id))
        elif task.status == "review":
            review_tasks_count += 1

    # -- Pending approvals for this board --
    approvals_statement = (
        select(Approval)
        .where(
            col(Approval.board_id) == board_id,
            col(Approval.status) == "pending",
        )
    )
    pending_approvals = (await session.exec(approvals_statement)).all()
    pending_approvals_count = len(pending_approvals)

    # -- Wake decision --
    should_wake, reason = _decide_wake(
        board_paused=board_paused,
        assigned_in_progress_task_id=assigned_in_progress_task_id,
        assigned_inbox_task_ids=assigned_inbox_task_ids,
        pending_approvals_count=pending_approvals_count,
        review_tasks_count=review_tasks_count,
    )

    return {
        "board_id": str(board_id),
        "board_paused": board_paused,
        "assigned_in_progress_task_id": assigned_in_progress_task_id,
        "assigned_inbox_task_ids": assigned_inbox_task_ids,
        "pending_approvals_count": pending_approvals_count,
        "review_tasks_count": review_tasks_count,
        "active_run_id": None,
        "should_wake": should_wake,
        "reason": reason,
    }


def _decide_wake(
    *,
    board_paused: bool,
    assigned_in_progress_task_id: str | None,
    assigned_inbox_task_ids: list[str],
    pending_approvals_count: int,
    review_tasks_count: int,
) -> tuple[bool, str]:
    """Decide whether an agent should wake based on work snapshot data."""
    if board_paused:
        return False, "board_paused"
    if assigned_in_progress_task_id:
        return True, "assigned_in_progress_task"
    if assigned_inbox_task_ids:
        return True, "assigned_inbox_task"
    if pending_approvals_count > 0:
        return True, "pending_approval"
    if review_tasks_count > 0:
        return True, "review_queue"
    return False, "idle_no_work"


def _empty_snapshot(agent_id: UUID) -> dict:
    return {
        "board_id": None,
        "board_paused": False,
        "assigned_in_progress_task_id": None,
        "assigned_inbox_task_ids": [],
        "pending_approvals_count": 0,
        "review_tasks_count": 0,
        "active_run_id": None,
        "should_wake": False,
        "reason": "idle_no_work",
    }
