"""Helpers for assembling denormalized board snapshot response payloads."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError
from sqlalchemy import func
from sqlmodel import col, select

from app.models.activity_events import ActivityEvent
from app.models.agents import Agent
from app.models.approvals import Approval
from app.models.board_onboarding import BoardOnboardingSession
from app.models.board_memory import BoardMemory
from app.models.runs import Run
from app.models.tasks import Task
from app.schemas.activity_events import ActivityEventRead
from app.schemas.approvals import ApprovalRead
from app.schemas.board_memory import BoardMemoryRead
from app.schemas.board_onboarding import BoardOnboardingTeamPlan
from app.schemas.boards import BoardRead
from app.schemas.view_models import (
    BoardRuntimeAgentState,
    BoardRuntimeIntegrity,
    BoardSnapshot,
    TaskCardRead,
)
from app.services.approval_task_links import load_task_ids_by_approval, task_counts_for_board
from app.services.agent_presets import AGENT_ROLE_PRESETS
from app.services.agent_work import get_board_wake_reasons
from app.services.openclaw.internal.agent_key import agent_key, slugify
from app.services.openclaw.provisioning_db import AgentLifecycleService
from app.services.tags import TagState, load_tag_state
from app.services.task_dependencies import (
    blocked_by_dependency_ids,
    dependency_ids_by_task_id,
    dependency_status_by_id,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.models.boards import Board


def _memory_to_read(memory: BoardMemory) -> BoardMemoryRead:
    return BoardMemoryRead.model_validate(memory, from_attributes=True)


def _activity_to_read(event: ActivityEvent) -> ActivityEventRead:
    payload = ActivityEventRead.model_validate(event, from_attributes=True)
    payload.board_id = event.board_id
    return payload


def _approval_to_read(
    approval: Approval,
    *,
    task_ids: list[UUID],
    task_titles: list[str],
) -> ApprovalRead:
    model = ApprovalRead.model_validate(approval, from_attributes=True)
    primary_task_id = task_ids[0] if task_ids else None
    return model.model_copy(
        update={
            "task_id": primary_task_id,
            "task_ids": task_ids,
            "task_titles": task_titles,
        },
    )


def _task_to_card(
    task: Task,
    *,
    agent_name_by_id: dict[UUID, str],
    counts_by_task_id: dict[UUID, tuple[int, int]],
    deps_by_task_id: dict[UUID, list[UUID]],
    dependency_status_by_id_map: dict[UUID, str],
    tag_state_by_task_id: dict[UUID, TagState],
) -> TaskCardRead:
    card = TaskCardRead.model_validate(task, from_attributes=True)
    approvals_count, approvals_pending_count = counts_by_task_id.get(task.id, (0, 0))
    assignee = agent_name_by_id.get(task.assigned_agent_id) if task.assigned_agent_id else None
    depends_on_task_ids = deps_by_task_id.get(task.id, [])
    tag_state = tag_state_by_task_id.get(task.id, TagState())
    blocked_by_task_ids = blocked_by_dependency_ids(
        dependency_ids=depends_on_task_ids,
        status_by_id=dependency_status_by_id_map,
    )
    if task.status == "done":
        blocked_by_task_ids = []
    return card.model_copy(
        update={
            "assignee": assignee,
            "approvals_count": approvals_count,
            "approvals_pending_count": approvals_pending_count,
            "depends_on_task_ids": depends_on_task_ids,
            "tag_ids": tag_state.tag_ids,
            "tags": tag_state.tags,
            "blocked_by_task_ids": blocked_by_task_ids,
            "is_blocked": bool(blocked_by_task_ids),
        },
    )


_RUNTIME_MEMORY_TAGS = frozenset(
    {
        "auth",
        "blocked",
        "platform",
        "provision",
        "provisioning",
        "reconcile",
        "runtime",
        "template",
        "wake",
    }
)
_RUNTIME_EVENT_PREFIXES = ("agent.", "gateway.")
_RUNTIME_EVENT_TYPES = frozenset(
    {
        "approval.lead_notify_failed",
        "approval.pipeline_blocked",
        "board.lead_notify_failed",
        "task.assignee_notify_failed",
        "task.assignee_wake_failed",
        "task.lead_notify_failed",
        "task.lead_unassigned_notify_failed",
        "task.rework_notify_failed",
    }
)
_HEALTHY_AGENT_STATUSES = frozenset({"online", "idle", "dormant"})


def _is_runtime_memory(memory: BoardMemory) -> bool:
    tags = {str(tag).strip().lower() for tag in memory.tags or [] if str(tag).strip()}
    return bool(tags & _RUNTIME_MEMORY_TAGS)


def _is_runtime_event(event: ActivityEvent) -> bool:
    if event.event_type in _RUNTIME_EVENT_TYPES:
        return True
    return any(event.event_type.startswith(prefix) for prefix in _RUNTIME_EVENT_PREFIXES)


def _agent_role_key(agent: Agent) -> str:
    if agent.is_board_lead:
        return "board_lead"
    profile = agent.identity_profile if isinstance(agent.identity_profile, dict) else {}
    raw_role = profile.get("role")
    if isinstance(raw_role, str):
        normalized = raw_role.strip().lower()
        for role_key, preset in AGENT_ROLE_PRESETS.items():
            preset_role = str((preset.get("identity_profile") or {}).get("role", "")).strip().lower()
            if normalized and normalized == preset_role:
                return role_key
        for role_key in AGENT_ROLE_PRESETS:
            if normalized == role_key:
                return role_key
    return "worker"


def _agent_role_label(agent: Agent, role_key: str) -> str:
    if role_key in AGENT_ROLE_PRESETS:
        return str(AGENT_ROLE_PRESETS[role_key].get("label") or role_key.replace("_", " ").title())
    profile = agent.identity_profile if isinstance(agent.identity_profile, dict) else {}
    raw_role = profile.get("role")
    if isinstance(raw_role, str) and raw_role.strip():
        return raw_role.strip()
    return "Worker"


def _parse_team_plan(onboarding: BoardOnboardingSession | None) -> BoardOnboardingTeamPlan | None:
    if onboarding is None or onboarding.draft_goal is None:
        return None
    try:
        raw = onboarding.draft_goal.get("team_plan") if isinstance(onboarding.draft_goal, dict) else None
        if raw is None:
            return None
        return BoardOnboardingTeamPlan.model_validate(raw)
    except ValidationError:
        return None


def _expected_role_keys(team_plan: BoardOnboardingTeamPlan | None) -> list[str]:
    worker_roles: list[str]
    if team_plan is None:
        worker_roles = []
    elif team_plan.provision_mode == "full_team":
        worker_roles = [
            role_key
            for role_key, preset in AGENT_ROLE_PRESETS.items()
            if not bool(preset.get("is_board_lead"))
        ]
    elif team_plan.provision_mode == "selected_roles":
        worker_roles = [
            role_key
            for role_key in team_plan.roles or []
            if role_key in AGENT_ROLE_PRESETS and not bool(AGENT_ROLE_PRESETS[role_key].get("is_board_lead"))
        ]
    else:
        worker_roles = []
    return ["board_lead", *worker_roles]


def _workspace_template_sync_state(workspace_path: Path | None) -> tuple[str, bool]:
    if workspace_path is None or not workspace_path.exists():
        return "missing", False

    for file_name in ("HEARTBEAT.md", "AGENTS.md", "TOOLS.md"):
        candidate = workspace_path / file_name
        if not candidate.exists():
            continue
        try:
            content = candidate.read_text(encoding="utf-8")
        except OSError:
            continue
        if "Authorization: Bearer" in content:
            return "drifted", True
    return "ok", True


def _runtime_blocker(
    *,
    status: str,
    wake_reason: str | None,
    last_provision_error: str | None,
    agent_auth_last_error: str | None,
    workspace_exists: bool,
    template_sync_state: str,
) -> str | None:
    if agent_auth_last_error:
        return "PlatformBlocked(Auth)"
    if last_provision_error:
        return "PlatformBlocked(Provisioning)"
    if template_sync_state == "drifted":
        return "PlatformBlocked(Template)"
    if not workspace_exists:
        return "PlatformBlocked(Workspace)"
    if wake_reason in {"assigned_in_progress_task", "assigned_inbox_task", "pending_approval", "review_queue"}:
        if status not in _HEALTHY_AGENT_STATUSES:
            return "PlatformBlocked(Check-in)"
    return None


async def _build_runtime_integrity(
    session: AsyncSession,
    *,
    board: Board,
    agents: list[Agent],
    tasks: list[Task],
    wake_reason_by_agent_id: dict[str, str],
) -> BoardRuntimeIntegrity:
    onboarding = (
        await BoardOnboardingSession.objects.filter_by(board_id=board.id)
        .order_by(col(BoardOnboardingSession.updated_at).desc())
        .first(session)
    )
    team_plan = _parse_team_plan(onboarding)
    expected_roles = _expected_role_keys(team_plan)

    runs = (
        await Run.objects.filter(col(Run.agent_id).in_([agent.id for agent in agents]))
        .filter(col(Run.status) == "running")
        .all(session)
        if agents
        else []
    )
    running_agent_ids = {run.agent_id for run in runs if run.agent_id is not None}

    task_counts_by_agent_id: dict[UUID, int] = {}
    for task in tasks:
        if task.assigned_agent_id is None or task.status == "done":
            continue
        task_counts_by_agent_id[task.assigned_agent_id] = (
            task_counts_by_agent_id.get(task.assigned_agent_id, 0) + 1
        )

    gateway = None
    if board.gateway_id is not None:
        from app.models.gateways import Gateway

        gateway = await Gateway.objects.by_id(board.gateway_id).first(session)
    workspace_root = (gateway.workspace_root or "").rstrip("/") if gateway is not None else ""

    agent_states: list[BoardRuntimeAgentState] = []
    actual_roles: list[str] = []
    healthy_roles: list[str] = []
    stale_roles: list[str] = []
    auth_drift_agent_ids: list[UUID] = []
    template_drift_agent_ids: list[UUID] = []
    missing_first_heartbeat_agent_ids: list[UUID] = []
    platform_blocked_agent_ids: list[UUID] = []
    workspace_missing_agent_ids: list[UUID] = []

    for agent in agents:
        computed = AgentLifecycleService.with_computed_status(agent)
        role_key = _agent_role_key(computed)
        role_label = _agent_role_label(computed, role_key)
        actual_roles.append(role_key)
        workspace_path = (
            Path(f"{workspace_root}/workspace-{slugify(agent_key(computed))}").expanduser()
            if workspace_root
            else None
        )
        template_sync_state, workspace_exists = _workspace_template_sync_state(workspace_path)
        wake_reason = wake_reason_by_agent_id.get(str(computed.id))
        runtime_blocker = _runtime_blocker(
            status=computed.status,
            wake_reason=wake_reason,
            last_provision_error=computed.last_provision_error,
            agent_auth_last_error=computed.agent_auth_last_error,
            workspace_exists=workspace_exists,
            template_sync_state=template_sync_state,
        )
        state = BoardRuntimeAgentState(
            agent_id=computed.id,
            name=computed.name,
            role_key=role_key,
            role_label=role_label,
            status=computed.status,
            agent_auth_mode=computed.agent_auth_mode,
            pending_agent_token_version=computed.pending_agent_token_version,
            wake_reason=wake_reason,
            last_seen_at=computed.last_seen_at,
            last_provision_error=computed.last_provision_error,
            agent_auth_last_error=computed.agent_auth_last_error,
            agent_auth_last_synced_at=computed.agent_auth_last_synced_at,
            assigned_task_count=task_counts_by_agent_id.get(computed.id, 0),
            has_active_run=computed.id in running_agent_ids,
            workspace_path=str(workspace_path) if workspace_path is not None else None,
            workspace_exists=workspace_exists,
            template_sync_state=template_sync_state,
            runtime_blocker=runtime_blocker,
        )
        agent_states.append(state)

        if computed.last_seen_at is None:
            missing_first_heartbeat_agent_ids.append(computed.id)
        if computed.agent_auth_last_error:
            auth_drift_agent_ids.append(computed.id)
        if template_sync_state == "drifted":
            template_drift_agent_ids.append(computed.id)
        if not workspace_exists:
            workspace_missing_agent_ids.append(computed.id)
        if runtime_blocker is not None:
            platform_blocked_agent_ids.append(computed.id)
            if role_key not in stale_roles:
                stale_roles.append(role_key)
        elif computed.status in _HEALTHY_AGENT_STATUSES:
            if role_key not in healthy_roles:
                healthy_roles.append(role_key)
        else:
            if role_key not in stale_roles:
                stale_roles.append(role_key)

    missing_roles = [role for role in expected_roles if role not in actual_roles]
    actual_worker_count = sum(1 for agent in agents if not agent.is_board_lead)
    healthy_worker_count = sum(
        1
        for state in agent_states
        if state.role_key != "board_lead"
        and state.status in _HEALTHY_AGENT_STATUSES
        and state.runtime_blocker is None
    )

    return BoardRuntimeIntegrity(
        provision_mode=team_plan.provision_mode if team_plan is not None else None,
        expected_roles=expected_roles,
        actual_roles=actual_roles,
        healthy_roles=healthy_roles,
        missing_roles=missing_roles,
        stale_roles=stale_roles,
        auth_drift_agent_ids=auth_drift_agent_ids,
        template_drift_agent_ids=template_drift_agent_ids,
        missing_first_heartbeat_agent_ids=missing_first_heartbeat_agent_ids,
        platform_blocked_agent_ids=platform_blocked_agent_ids,
        workspace_missing_agent_ids=workspace_missing_agent_ids,
        worker_capacity=board.max_agents,
        actual_worker_count=actual_worker_count,
        healthy_worker_count=healthy_worker_count,
        board_max_agents_counts_workers_only=True,
        agents=agent_states,
    )


async def build_board_snapshot(session: AsyncSession, board: Board) -> BoardSnapshot:
    """Build a board snapshot with tasks, agents, approvals, and chat history."""
    board_read = BoardRead.model_validate(board, from_attributes=True)

    tasks = list(
        await Task.objects.filter_by(board_id=board.id)
        .order_by(col(Task.created_at).desc())
        .all(session),
    )
    task_ids = [task.id for task in tasks]
    tag_state_by_task_id = await load_tag_state(
        session,
        task_ids=task_ids,
    )

    deps_by_task_id = await dependency_ids_by_task_id(
        session,
        board_id=board.id,
        task_ids=task_ids,
    )
    all_dependency_ids: list[UUID] = []
    for values in deps_by_task_id.values():
        all_dependency_ids.extend(values)
    dependency_status_by_id_map = await dependency_status_by_id(
        session,
        board_id=board.id,
        dependency_ids=list({*all_dependency_ids}),
    )

    agents = (
        await Agent.objects.filter_by(board_id=board.id)
        .order_by(col(Agent.created_at).desc())
        .all(session)
    )
    wake_reason_by_agent_id = await get_board_wake_reasons(session, board.id, agents)
    agent_reads = [
        AgentLifecycleService.to_agent_read(
            AgentLifecycleService.with_computed_status(agent),
            wake_reason=wake_reason_by_agent_id.get(str(agent.id)),
        )
        for agent in agents
    ]
    agent_name_by_id = {agent.id: agent.name for agent in agents}

    pending_approvals_count = int(
        (
            await session.exec(
                select(func.count(col(Approval.id)))
                .where(col(Approval.board_id) == board.id)
                .where(col(Approval.status) == "pending"),
            )
        ).one(),
    )

    approvals = (
        await Approval.objects.filter_by(board_id=board.id)
        .order_by(col(Approval.created_at).desc())
        .limit(200)
        .all(session)
    )
    approval_ids = [approval.id for approval in approvals]
    task_ids_by_approval = await load_task_ids_by_approval(
        session,
        approval_ids=approval_ids,
    )
    task_title_by_id = {task.id: task.title for task in tasks}
    # Hydrate each approval with linked task metadata, falling back to legacy
    # single-task fields so older rows still render complete approval cards.
    approval_reads = [
        _approval_to_read(
            approval,
            task_ids=(
                linked_task_ids := task_ids_by_approval.get(
                    approval.id,
                    [approval.task_id] if approval.task_id is not None else [],
                )
            ),
            task_titles=[
                task_title_by_id[task_id]
                for task_id in linked_task_ids
                if task_id in task_title_by_id
            ],
        )
        for approval in approvals
    ]

    counts_by_task_id = await task_counts_for_board(session, board_id=board.id)

    task_cards = [
        _task_to_card(
            task,
            agent_name_by_id=agent_name_by_id,
            counts_by_task_id=counts_by_task_id,
            deps_by_task_id=deps_by_task_id,
            dependency_status_by_id_map=dependency_status_by_id_map,
            tag_state_by_task_id=tag_state_by_task_id,
        )
        for task in tasks
    ]

    chat_messages = (
        await BoardMemory.objects.filter_by(board_id=board.id)
        .filter(col(BoardMemory.is_chat).is_(True))
        # Old/invalid rows (empty/whitespace-only content) can exist; exclude them to
        # satisfy the NonEmptyStr response schema.
        .filter(func.length(func.trim(col(BoardMemory.content))) > 0)
        .order_by(col(BoardMemory.created_at).desc())
        .limit(200)
        .all(session)
    )
    chat_messages.sort(key=lambda item: item.created_at)
    chat_reads = [_memory_to_read(memory) for memory in chat_messages]

    coordination_messages = (
        await BoardMemory.objects.filter_by(board_id=board.id)
        .filter(col(BoardMemory.is_chat).is_(False))
        .filter(func.length(func.trim(col(BoardMemory.content))) > 0)
        .order_by(col(BoardMemory.created_at).desc())
        .limit(200)
        .all(session)
    )
    coordination_messages.sort(key=lambda item: item.created_at)
    coordination_reads = [_memory_to_read(memory) for memory in coordination_messages if not _is_runtime_memory(memory)]
    runtime_memory_reads = [_memory_to_read(memory) for memory in coordination_messages if _is_runtime_memory(memory)]

    runtime_events = (
        await ActivityEvent.objects.filter_by(board_id=board.id)
        .order_by(col(ActivityEvent.created_at).desc())
        .limit(200)
        .all(session)
    )
    runtime_event_reads = [_activity_to_read(event) for event in runtime_events if _is_runtime_event(event)]
    runtime_event_reads.sort(key=lambda event: event.created_at, reverse=True)

    runtime_integrity = await _build_runtime_integrity(
        session,
        board=board,
        agents=agents,
        tasks=tasks,
        wake_reason_by_agent_id=wake_reason_by_agent_id,
    )

    return BoardSnapshot(
        board=board_read,
        tasks=task_cards,
        agents=agent_reads,
        approvals=approval_reads,
        chat_messages=chat_reads,
        coordination_messages=coordination_reads,
        runtime_messages=runtime_memory_reads,
        runtime_events=runtime_event_reads[:100],
        runtime_integrity=runtime_integrity,
        pending_approvals_count=pending_approvals_count,
    )
