"""Planner service: generates backlog from spec artifacts.

Supports multiple backends:
- Direct LLM call (via configured provider)
- OpenClaw Gateway ACP session (preferred when gateway is available)
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlmodel import col, select

from app.core.logging import get_logger
from app.core.time import utcnow
from app.db.session import async_session_maker
from app.models.agents import Agent
from app.models.artifacts import Artifact
from app.models.boards import Board
from app.models.planner_outputs import PlannerOutput
from app.services.artifact_storage import read_artifact_file
from app.services.artifacts import get_artifact_by_id
from app.services.planner_dag import compute_parallelism_groups, validate_dag

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

logger = get_logger(__name__)

PLANNER_ACTIVE_STATUSES = frozenset({"generating", "draft"})
PLANNER_ROLE_TO_AGENT_ROLE = {
    "dev": "developer",
    "qa": "qa",
    "docs": "docs",
    "ops": "ops",
}

PLANNER_SYSTEM_PROMPT = """You are a staff-level product planning lead. Analyze the specification and produce an execution-ready backlog for a multi-agent software delivery team.

Output ONLY valid JSON with this exact structure:
{
  "epics": [
    {"id": "epic_1", "title": "...", "description": "..."}
  ],
  "tasks": [
    {
      "id": "task_1",
      "epic_id": "epic_1",
      "title": "...",
      "description": "...",
      "acceptance_criteria": ["criterion 1", "criterion 2"],
      "depends_on": ["task_2"],
      "tags": ["backend", "api"],
      "estimate": "medium",
      "suggested_agent_role": "dev"
    }
  ]
}

Rules:
- Task IDs must be unique strings (use format: task_N)
- Epic IDs must be unique strings (use format: epic_N)
- depends_on must reference other task IDs from the same output
- NO self-dependencies (a task cannot depend on itself)
- NO circular dependencies
- Tasks with no dependencies can run in parallel
- suggested_agent_role should be one of: dev, qa, docs, ops
- estimate should be one of: small, medium, large, xlarge
- Break the spec into epics, then tasks within each epic
- Include acceptance criteria for each task
- Produce a backlog that is immediately useful for delivery, not just analysis
- Cover the full execution path needed to ship:
  - planning/architecture decisions
  - implementation work
  - quality validation and test coverage
  - documentation and handoff material
  - release/operations readiness when relevant
- Always include at least one documentation or handoff task unless the spec is clearly a docs-only request
- Use suggested_agent_role intentionally:
  - dev for product/backend/frontend/integration work and technical design
  - qa for test strategy, acceptance validation, regressions, e2e, and verification
  - docs for README, ADR, changelog, runbook, API docs, onboarding, support docs
  - ops for deployment, observability, security, infrastructure, migration, rollback, and runtime safeguards
- Make tasks concrete enough that a Lead can assign them directly to Developer, QA, Technical Writer, and Ops agents
- Prefer fewer strong tasks over many vague tasks, but do not omit necessary delivery work
"""


def _extract_json_from_response(text: str) -> dict | None:
    """Extract JSON from LLM response, handling markdown code blocks."""
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    json_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
        try:
            return json.loads(text[brace_start : brace_end + 1])
        except json.JSONDecodeError:
            pass

    return None


async def generate_backlog_from_text(
    session: AsyncSession,
    *,
    artifact_id: UUID,
    board_id: UUID,
    spec_text: str,
    max_tasks: int = 50,
    created_by: UUID | None = None,
    force: bool = False,
) -> PlannerOutput:
    """Queue backlog generation from raw spec text.

    Args:
        force: If True, delete existing draft and regenerate.
    """
    board = await Board.objects.by_id(board_id).first(session)
    if not board:
        raise ValueError(f"Board {board_id} not found")

    existing_query = await session.exec(
        select(PlannerOutput).where(
            col(PlannerOutput.artifact_id) == artifact_id,
            col(PlannerOutput.status).in_(tuple(PLANNER_ACTIVE_STATUSES)),
        )
        .order_by(col(PlannerOutput.created_at).desc())
    )
    existing_outputs = list(existing_query.all())
    generating = next(
        (output for output in existing_outputs if output.status == "generating"),
        None,
    )
    if generating is not None:
        return generating

    existing_draft = next(
        (output for output in existing_outputs if output.status == "draft"),
        None,
    )
    if existing_draft is not None:
        if not force:
            return existing_draft
        for output in existing_outputs:
            if output.status == "draft":
                await session.delete(output)
        await session.commit()

    planner_output = PlannerOutput(
        board_id=board_id,
        artifact_id=artifact_id,
        status="generating",
        created_by=created_by,
        epics=[],
        tasks=[],
        parallelism_groups=[],
    )
    session.add(planner_output)
    await session.commit()
    await session.refresh(planner_output)

    _launch_planner_generation(
        planner_output_id=planner_output.id,
        board_id=board.id,
        spec_text=spec_text,
        max_tasks=max_tasks,
    )
    return planner_output


def _launch_planner_generation(
    *,
    planner_output_id: UUID,
    board_id: UUID,
    spec_text: str,
    max_tasks: int,
) -> None:
    """Spawn background planner generation without blocking the request."""

    task = asyncio.create_task(
        _run_planner_generation(
            planner_output_id=planner_output_id,
            board_id=board_id,
            spec_text=spec_text,
            max_tasks=max_tasks,
        )
    )

    def _log_task_result(done_task: asyncio.Task[None]) -> None:
        try:
            done_task.result()
        except Exception:
            logger.exception(
                "Planner background generation crashed",
                extra={"planner_output_id": str(planner_output_id)},
            )

    task.add_done_callback(_log_task_result)


async def _run_planner_generation(
    *,
    planner_output_id: UUID,
    board_id: UUID,
    spec_text: str,
    max_tasks: int,
) -> None:
    """Generate and persist planner output using a fresh DB session."""

    async with async_session_maker() as session:
        planner_output = await PlannerOutput.objects.by_id(planner_output_id).first(
            session
        )
        if planner_output is None:
            logger.warning(
                "Planner output disappeared before generation completed",
                extra={"planner_output_id": str(planner_output_id)},
            )
            return

        board = await Board.objects.by_id(board_id).first(session)
        if board is None:
            await _mark_planner_output_failed(
                session,
                planner_output,
                error_message=f"Board {board_id} not found",
            )
            return

        prompt = (
            "Analyze the following project specification and break it down into a "
            f"structured backlog. Maximum {max_tasks} tasks.\n\n"
            f"--- SPECIFICATION ---\n\n{spec_text}"
        )

        try:
            response_text = await _call_llm_via_gateway(
                session=session,
                board=board,
                system_prompt=PLANNER_SYSTEM_PROMPT,
                user_prompt=prompt,
            )
        except Exception as exc:
            await _mark_planner_output_failed(
                session,
                planner_output,
                error_message=f"LLM generation failed: {exc}",
            )
            return

        parsed = _extract_json_from_response(response_text)
        if not parsed:
            await _mark_planner_output_failed(
                session,
                planner_output,
                error_message="Failed to parse LLM response as JSON",
            )
            return

        epics = parsed.get("epics", [])
        tasks = parsed.get("tasks", [])

        if not tasks:
            await _mark_planner_output_failed(
                session,
                planner_output,
                error_message="No tasks generated from specification",
                epics=epics,
                tasks=tasks,
            )
            return

        dag_error = validate_dag(tasks)
        if dag_error:
            await _mark_planner_output_failed(
                session,
                planner_output,
                error_message=f"DAG validation failed: {dag_error}",
                epics=epics,
                tasks=tasks,
            )
            return

        planner_output.epics = epics
        planner_output.tasks = tasks
        planner_output.parallelism_groups = compute_parallelism_groups(tasks)
        planner_output.status = "draft"
        planner_output.error_message = None
        session.add(planner_output)
        await session.commit()


async def _mark_planner_output_failed(
    session: AsyncSession,
    planner_output: PlannerOutput,
    *,
    error_message: str,
    epics: list[dict] | None = None,
    tasks: list[dict] | None = None,
) -> None:
    """Persist planner failure state for UI polling and operator review."""

    planner_output.status = "failed"
    planner_output.error_message = error_message
    planner_output.epics = epics or []
    planner_output.tasks = tasks or []
    planner_output.parallelism_groups = (
        compute_parallelism_groups(tasks or [])
        if tasks
        else []
    )

    session.add(planner_output)
    await session.commit()


async def generate_backlog(
    session: AsyncSession,
    *,
    artifact_id: UUID,
    board_id: UUID,
    max_tasks: int = 50,
    created_by: UUID | None = None,
    force: bool = False,
) -> PlannerOutput:
    """Generate a backlog from a spec artifact.

    Reads the spec file content and delegates to generate_backlog_from_text.
    """
    artifact = await get_artifact_by_id(session, artifact_id)
    if not artifact:
        raise ValueError(f"Artifact {artifact_id} not found")

    try:
        spec_content = read_artifact_file(artifact.storage_path)
        spec_text = spec_content.decode("utf-8", errors="replace")
    except FileNotFoundError:
        raise ValueError(f"Spec file not found for artifact {artifact_id}")

    return await generate_backlog_from_text(
        session,
        artifact_id=artifact_id,
        board_id=board_id,
        spec_text=spec_text,
        max_tasks=max_tasks,
        created_by=created_by,
        force=force,
    )


async def _call_llm_via_gateway(
    session: AsyncSession,
    board: Board,
    system_prompt: str,
    user_prompt: str,
) -> str:
    """Send a planning request through the OpenClaw Gateway to a board lead agent.

    Uses the gateway WebSocket RPC to send a message to the board lead agent
    and waits for a response by polling chat history with request correlation.
    """
    import asyncio
    import time
    from uuid import uuid4

    from app.models.agents import Agent
    from app.services.openclaw.gateway_dispatch import GatewayDispatchService
    from app.services.openclaw.gateway_rpc import openclaw_call

    dispatch = GatewayDispatchService(session)
    gateway, config = await dispatch.require_gateway_config_for_board(board)

    agents = await Agent.objects.filter_by(board_id=board.id, is_board_lead=True).all(session)
    if not agents:
        raise ValueError(
            "No board lead agent available for planning. "
            "Provision an agent with is_board_lead=True first."
        )

    lead = agents[0]
    if not lead.openclaw_session_id:
        raise ValueError(
            f"Board lead agent '{lead.name}' has no active session. "
            "Run template sync to provision the agent."
        )

    request_id = uuid4().hex[:12]
    request_marker = f"\n\n[PLANNER_REQUEST:{request_id}]"
    full_message = f"{system_prompt}\n\n{user_prompt}{request_marker}"

    history_before = await _get_history_length(lead.openclaw_session_id, config)

    await dispatch.send_to_agent(
        agent=lead,
        message=full_message,
        deliver=True,
    )

    response_text = await _wait_for_agent_response(
        session_key=lead.openclaw_session_id,
        config=config,
        history_cursor=history_before,
        request_marker=f"[PLANNER_RESPONSE:{request_id}]",
        timeout=300,
    )
    return response_text


async def _get_history_length(session_key: str, config: Any) -> int:
    """Get current chat history length before sending a request."""
    from app.services.openclaw.gateway_rpc import openclaw_call

    try:
        history = await openclaw_call(
            "chat.history",
            {"session_key": session_key, "limit": 1},
            config=config,
        )
        messages = history.get("messages", []) if isinstance(history, dict) else []
        return history.get("total", len(messages))
    except Exception:
        return 0


async def _wait_for_agent_response(
    session_key: str,
    config: Any,
    history_cursor: int = 0,
    request_marker: str | None = None,
    timeout: int = 300,
) -> str:
    """Poll gateway chat history until the agent responds.

    Args:
        session_key: ACP session key.
        config: Gateway config.
        history_cursor: Message count before the request was sent.
        request_marker: Expected marker in the response for correlation.
        timeout: Max wait time in seconds.
    """
    from app.services.openclaw.gateway_rpc import openclaw_call

    start = time.time()

    while time.time() - start < timeout:
        try:
            history = await openclaw_call(
                "chat.history",
                {"session_key": session_key, "limit": 20},
                config=config,
            )
            messages = history.get("messages", []) if isinstance(history, dict) else []
            total = history.get("total", len(messages))

            if total > history_cursor:
                new_messages = messages[-(total - history_cursor):]
                for msg in reversed(new_messages):
                    if isinstance(msg, dict):
                        content = msg.get("content", "")
                        role = msg.get("role", "")
                        if role in ("assistant", "agent", "model") and content:
                            if request_marker and request_marker in content:
                                return content.replace(request_marker, "").strip()
                            if not request_marker:
                                return content
        except Exception:
            pass
        await asyncio.sleep(2)

    raise RuntimeError("Timeout waiting for agent response")


async def apply_planner_output(
    session: AsyncSession,
    planner_output: PlannerOutput,
    *,
    tasks_override: list[dict] | None = None,
    epics_override: list[dict] | None = None,
) -> PlannerOutput:
    """Apply a planner output by creating real tasks on the board.

    Creates Task and TaskDependency records for each planned task.
    """
    from app.models.task_dependencies import TaskDependency
    from app.models.tasks import Task

    tasks = tasks_override or planner_output.tasks
    epics = epics_override or planner_output.epics

    dag_error = validate_dag(tasks)
    if dag_error:
        raise ValueError(f"Cannot apply: {dag_error}")

    if planner_output.status == "applied":
        raise ValueError("Planner output has already been applied")

    role_agents, lead_agent = await _resolve_board_agents_for_planner(
        session,
        board_id=planner_output.board_id,
    )
    id_map: dict[str, UUID] = {}

    for task_data in tasks:
        assignee = _select_planner_task_assignee(
            task_data=task_data,
            role_agents=role_agents,
            lead_agent=lead_agent,
        )
        task = Task(
            board_id=planner_output.board_id,
            title=task_data.get("title", "Untitled"),
            description=task_data.get("description"),
            status="inbox",
            priority="medium",
            acceptance_criteria=task_data.get("acceptance_criteria", []),
            estimate=task_data.get("estimate"),
            suggested_agent_role=task_data.get("suggested_agent_role"),
            planner_task_id=task_data.get("id"),
            epic_id=task_data.get("epic_id"),
            assigned_agent_id=assignee.id if assignee is not None else None,
            auto_created=True,
            auto_reason="planner_output",
        )
        session.add(task)
        id_map[task_data["id"]] = task.id

    await session.flush()

    for task_data in tasks:
        new_id = id_map[task_data["id"]]
        for dep_id in task_data.get("depends_on", []):
            if dep_id in id_map:
                dep = TaskDependency(
                    board_id=planner_output.board_id,
                    task_id=new_id,
                    depends_on_task_id=id_map[dep_id],
                )
                session.add(dep)

        tags = task_data.get("tags", [])
        if tags and planner_output.board_id:
            from app.models.tags import Tag
            from app.models.tag_assignments import TagAssignment
            for tag_name in tags:
                tag = await Tag.objects.filter_by(
                    board_id=planner_output.board_id,
                    name=tag_name,
                ).first(session)
                if not tag:
                    tag = Tag(
                        board_id=planner_output.board_id,
                        name=tag_name,
                        color="blue",
                    )
                    session.add(tag)
                    await session.flush()
                session.add(TagAssignment(task_id=new_id, tag_id=tag.id))

    planner_output.status = "applied"
    planner_output.applied_at = utcnow()
    planner_output.epics = epics
    planner_output.tasks = tasks

    session.add(planner_output)
    await session.commit()
    await session.refresh(planner_output)
    return planner_output


def _normalize_role_name(value: str | None) -> str | None:
    if not value:
        return None
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    return normalized or None


def _planner_role_for_agent(agent: Agent) -> str | None:
    if agent.is_board_lead:
        return "lead"

    raw_role: str | None = None
    if isinstance(agent.identity_profile, dict):
        identity_role = agent.identity_profile.get("role")
        if isinstance(identity_role, str):
            raw_role = identity_role
    if raw_role is None:
        raw_role = agent.name

    normalized = _normalize_role_name(raw_role)
    if normalized is None:
        return None
    if "developer" in normalized or normalized == "dev":
        return "developer"
    if "qa" in normalized or "quality" in normalized:
        return "qa"
    if "writer" in normalized or "docs" in normalized or "documentation" in normalized:
        return "docs"
    if "ops" in normalized or "guardian" in normalized or "operations" in normalized:
        return "ops"
    return None


def _agent_is_assignable(agent: Agent) -> bool:
    return agent.status not in {"offline", "provisioning"}


def _agent_priority(agent: Agent) -> tuple[int, str]:
    status_rank = 0 if agent.status == "online" else 1
    return (status_rank, agent.name.lower())


async def _resolve_board_agents_for_planner(
    session: AsyncSession,
    *,
    board_id: UUID,
) -> tuple[dict[str, list[Agent]], Agent | None]:
    agents = await Agent.objects.filter_by(board_id=board_id).all(session)
    lead_agent = next((agent for agent in agents if agent.is_board_lead), None)

    grouped: dict[str, list[Agent]] = {
        "developer": [],
        "qa": [],
        "docs": [],
        "ops": [],
    }
    for agent in agents:
        if not _agent_is_assignable(agent):
            continue
        planner_role = _planner_role_for_agent(agent)
        if planner_role in grouped:
            grouped[planner_role].append(agent)
    for role_name in grouped:
        grouped[role_name].sort(key=_agent_priority)
    return grouped, lead_agent


def _select_planner_task_assignee(
    *,
    task_data: dict[str, Any],
    role_agents: dict[str, list[Agent]],
    lead_agent: Agent | None,
) -> Agent | None:
    planner_role = _normalize_role_name(task_data.get("suggested_agent_role"))
    mapped_role = (
        PLANNER_ROLE_TO_AGENT_ROLE.get(planner_role)
        if planner_role is not None
        else None
    )
    if mapped_role:
        candidates = role_agents.get(mapped_role, [])
        if candidates:
            return candidates[0]
    return lead_agent
