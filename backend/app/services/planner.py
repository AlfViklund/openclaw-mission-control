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

from app.core.time import utcnow
from app.models.artifacts import Artifact
from app.models.boards import Board
from app.models.planner_outputs import PlannerOutput
from app.services.artifact_storage import read_artifact_file
from app.services.artifacts import get_artifact_by_id
from app.services.planner_dag import compute_parallelism_groups, validate_dag

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

PLANNER_SYSTEM_PROMPT = """You are a project planner. Your job is to analyze a project specification document and break it down into a structured backlog.

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
- Be thorough but practical - aim for actionable tasks
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
) -> PlannerOutput:
    """Generate a backlog from raw spec text.

    This is the core generation logic. The caller is responsible for
    obtaining the spec text (from artifact storage, Telegram, etc.).
    """
    board = await Board.objects.by_id(board_id).first(session)
    if not board:
        raise ValueError(f"Board {board_id} not found")

    existing = await session.exec(
        select(PlannerOutput).where(
            col(PlannerOutput.artifact_id) == artifact_id,
            col(PlannerOutput.status) == "draft",
        )
    ).first()
    if existing:
        return existing

    planner_output = PlannerOutput(
        board_id=board_id,
        artifact_id=artifact_id,
        status="draft",
        created_by=created_by,
    )

    prompt = (
        f"Analyze the following project specification and break it down into a structured backlog. "
        f"Maximum {max_tasks} tasks.\n\n"
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
        planner_output.error_message = f"LLM generation failed: {exc}"
        planner_output.epics = []
        planner_output.tasks = []
        session.add(planner_output)
        await session.commit()
        await session.refresh(planner_output)
        return planner_output

    parsed = _extract_json_from_response(response_text)
    if not parsed:
        planner_output.error_message = "Failed to parse LLM response as JSON"
        planner_output.epics = []
        planner_output.tasks = []
        session.add(planner_output)
        await session.commit()
        await session.refresh(planner_output)
        return planner_output

    epics = parsed.get("epics", [])
    tasks = parsed.get("tasks", [])

    if not tasks:
        planner_output.error_message = "No tasks generated from specification"
        planner_output.epics = epics
        planner_output.tasks = tasks
        session.add(planner_output)
        await session.commit()
        await session.refresh(planner_output)
        return planner_output

    dag_error = validate_dag(tasks)
    if dag_error:
        planner_output.error_message = f"DAG validation failed: {dag_error}"
        planner_output.epics = epics
        planner_output.tasks = tasks
        session.add(planner_output)
        await session.commit()
        await session.refresh(planner_output)
        return planner_output

    parallelism_groups = compute_parallelism_groups(tasks)

    planner_output.epics = epics
    planner_output.tasks = tasks
    planner_output.parallelism_groups = parallelism_groups
    planner_output.status = "draft"
    planner_output.error_message = None

    session.add(planner_output)
    await session.commit()
    await session.refresh(planner_output)
    return planner_output


async def generate_backlog(
    session: AsyncSession,
    *,
    artifact_id: UUID,
    board_id: UUID,
    max_tasks: int = 50,
    created_by: UUID | None = None,
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
    )


async def _call_llm_via_gateway(
    session: AsyncSession,
    board: Board,
    system_prompt: str,
    user_prompt: str,
) -> str:
    """Send a planning request through the OpenClaw Gateway to a board lead agent.

    Uses the gateway WebSocket RPC to send a message to the board lead agent
    and waits for a response by polling chat history.
    """
    import asyncio
    import time

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

    full_message = f"{system_prompt}\n\n{user_prompt}"

    history_before = await _get_history_length(lead.openclaw_session_id, config)

    await dispatch.send_agent_message(
        session_key=lead.openclaw_session_id,
        config=config,
        agent_name=lead.name,
        message=full_message,
        deliver=True,
    )

    response_text = await _wait_for_agent_response(
        session_key=lead.openclaw_session_id,
        config=config,
        history_cursor=history_before,
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
    timeout: int = 300,
) -> str:
    """Poll gateway chat history until the agent responds.

    Args:
        session_key: ACP session key.
        config: Gateway config.
        history_cursor: Message count before the request was sent.
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
                for msg in new_messages:
                    if isinstance(msg, dict):
                        content = msg.get("content", "")
                        role = msg.get("role", "")
                        if role in ("assistant", "agent", "model") and content:
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

    id_map: dict[str, UUID] = {}

    for task_data in tasks:
        task = Task(
            board_id=planner_output.board_id,
            title=task_data.get("title", "Untitled"),
            description=task_data.get("description"),
            status="inbox",
            priority="medium",
        )
        session.add(task)
        id_map[task_data["id"]] = task.id

    await session.flush()

    for task_data in tasks:
        new_id = id_map[task_data["id"]]
        for dep_id in task_data.get("depends_on", []):
            if dep_id in id_map:
                dep = TaskDependency(
                    task_id=new_id,
                    depends_on_task_id=id_map[dep_id],
                )
                session.add(dep)

    planner_output.status = "applied"
    planner_output.applied_at = utcnow()
    planner_output.epics = epics
    planner_output.tasks = tasks

    session.add(planner_output)
    await session.commit()
    await session.refresh(planner_output)
    return planner_output
