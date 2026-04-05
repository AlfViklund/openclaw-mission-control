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
from app.models.planner_expansion_runs import PlannerExpansionRun
from app.models.planner_outputs import PlannerOutput
from app.services.artifact_storage import read_artifact_file
from app.services.artifact_storage import save_artifact_file
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
PLANNER_PHASE_LABELS = {
    "digest": "Specification Digest",
    "dossier": "Project Dossier",
    "epics": "Epic Synthesis",
    "tasks": "Seed Task Package",
    "ready": "Board Package Ready",
}
PLANNER_PHASE_ORDER = tuple(PLANNER_PHASE_LABELS.keys())
PLANNER_EXPANSION_RUNNING_STATUSES = frozenset({"running"})
PLANNER_EXPANSION_AUTO_TRIGGERS = frozenset({"backlog_low", "dependency_unblocked", "task_done"})
DEFAULT_EXPANSION_MODE = "buffered_auto"
DEFAULT_MAX_ACTIVE_EPICS = 3
PLANNER_DOCUMENT_BLUEPRINTS = (
    {
        "key": "spec_digest",
        "title": "Specification Digest",
        "preferred_role": "lead",
        "instructions": (
            "Summarize the specification into the essential product goals, "
            "user flows, constraints, integrations, edge cases, delivery risks, "
            "and open questions needed for downstream planning."
        ),
    },
    {
        "key": "product_brief",
        "title": "Product Brief",
        "preferred_role": "lead",
        "instructions": (
            "Turn the digest into a concise product brief with target users, "
            "core outcomes, success signals, scope boundaries, and release intent."
        ),
    },
    {
        "key": "architecture_brief",
        "title": "Architecture Brief",
        "preferred_role": "dev",
        "instructions": (
            "Describe the technical architecture, key components, data flows, "
            "interfaces, implementation constraints, and major engineering decisions."
        ),
    },
    {
        "key": "qa_strategy",
        "title": "QA Strategy",
        "preferred_role": "qa",
        "instructions": (
            "Define the test strategy, acceptance validation plan, major failure modes, "
            "regression focus areas, and evidence needed to sign off delivery."
        ),
    },
    {
        "key": "documentation_plan",
        "title": "Documentation Plan",
        "preferred_role": "docs",
        "instructions": (
            "List the user-facing and engineering-facing documents required to ship, "
            "who they serve, when they should be produced, and what each must contain."
        ),
    },
    {
        "key": "release_ops_runbook",
        "title": "Release and Ops Runbook",
        "preferred_role": "ops",
        "instructions": (
            "Outline deployment, observability, security, migration, rollback, "
            "support readiness, and runtime safeguards needed for launch."
        ),
    },
)

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
PLANNER_MARKDOWN_SYSTEM_PROMPT = """You are preparing a planning document for a software delivery board.

Output only Markdown.
Write for humans reviewing the plan in a project UI.
Be concrete, structured, and concise.
"""
PLANNER_EPICS_SYSTEM_PROMPT = """You are creating an epic map from a project dossier.

Output ONLY valid JSON with this exact structure:
{
  "epics": [
    {
      "id": "epic_1",
      "title": "...",
      "description": "...",
      "primary_role": "dev"
    }
  ]
}

Rules:
- Keep epics delivery-oriented and mutually understandable by a human lead
- Cover implementation, verification, documentation, and release readiness when needed
- primary_role should be one of: dev, qa, docs, ops
- Return 3 to 8 epics unless the scope is obviously smaller
"""
PLANNER_TASK_PACK_SYSTEM_PROMPT = """You are generating the initial seed task pack for one epic in a software delivery plan.

Output ONLY valid JSON with this exact structure:
{
  "coverage_summary": "...",
  "remaining_work_summary": "...",
  "open_acceptance_items": ["..."],
  "next_focus_roles": ["dev", "qa"],
  "tasks": [
    {
      "id": "task_1",
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
- Return tasks only for the provided epic
- This is the initial work package, not the full backlog
- Generate only the highest-leverage seed tasks that should appear on the board first
- Use open_acceptance_items to capture notable scope that remains after the seed tasks
- coverage_summary should explain what part of the epic is now covered by the seed tasks
- remaining_work_summary should explain what still needs materialization later
- next_focus_roles should contain only dev, qa, docs, ops and reflect who should likely own the next batch
- Dependencies must reference only task IDs from this response
- suggested_agent_role should be one of: dev, qa, docs, ops
- estimate should be one of: small, medium, large, xlarge
- Include the docs, QA, and ops tasks that belong to this epic, not just coding work
"""
PLANNER_EXPANSION_SYSTEM_PROMPT = """You are materializing the next small task batch for already-approved scope.

Output ONLY valid JSON with this exact structure:
{
  "coverage_summary": "...",
  "remaining_work_summary": "...",
  "open_acceptance_items": ["..."],
  "next_focus_roles": ["dev", "qa"],
  "scope_suggestions": ["..."],
  "tasks": [
    {
      "id": "task_1",
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
- Only create tasks that are clearly inside the already-approved epic and dossier scope
- Do NOT recreate, restate, or rename work that already exists on the board
- Generate only the next small batch that should be materialized now
- Prefer 1 to 2 tasks per epic unless the request explicitly allows more
- Leave new product scope in scope_suggestions instead of creating tasks for it
- Keep dependencies minimal and only reference task IDs from this response
- suggested_agent_role should be one of: dev, qa, docs, ops
- estimate should be one of: small, medium, large, xlarge
"""
PLANNER_DEPENDENCY_SYSTEM_PROMPT = """You are normalizing dependencies for an existing task graph.

Output ONLY valid JSON with this exact structure:
{
  "dependencies": [
    {"task_id": "task_a", "depends_on": ["task_b", "task_c"]}
  ]
}

Rules:
- Only use the provided task IDs
- Keep dependencies minimal and necessary
- Do not introduce cycles
- Prefer sequencing by true prerequisite, not by habit
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


def _default_phase_statuses() -> list[dict[str, str | None]]:
    return [
        {
            "key": key,
            "label": label,
            "status": "pending",
            "detail": None,
        }
        for key, label in PLANNER_PHASE_LABELS.items()
    ]


def _phase_status_map(
    planner_output: PlannerOutput,
) -> dict[str, dict[str, str | None]]:
    statuses = planner_output.phase_statuses or _default_phase_statuses()
    return {
        str(item.get("key")): {
            "key": str(item.get("key")),
            "label": str(item.get("label") or PLANNER_PHASE_LABELS.get(str(item.get("key")), "")),
            "status": str(item.get("status") or "pending"),
            "detail": item.get("detail") if isinstance(item.get("detail"), str) else None,
        }
        for item in statuses
    }


def _set_phase_status(
    planner_output: PlannerOutput,
    *,
    phase_key: str,
    status: str,
    detail: str | None = None,
) -> None:
    status_map = _phase_status_map(planner_output)
    current = status_map.get(
        phase_key,
        {
            "key": phase_key,
            "label": PLANNER_PHASE_LABELS.get(phase_key, phase_key.title()),
            "status": "pending",
            "detail": None,
        },
    )
    current["status"] = status
    current["detail"] = detail
    status_map[phase_key] = current
    ordered: list[dict[str, str | None]] = []
    for key in PLANNER_PHASE_ORDER:
        ordered.append(status_map.get(key, current if key == phase_key else {
            "key": key,
            "label": PLANNER_PHASE_LABELS[key],
            "status": "pending",
            "detail": None,
        }))
    for key, value in status_map.items():
        if key not in PLANNER_PHASE_ORDER:
            ordered.append(value)
    planner_output.phase_statuses = ordered


def _set_pipeline_phase(
    planner_output: PlannerOutput,
    *,
    phase_key: str,
    detail: str | None = None,
) -> None:
    planner_output.pipeline_phase = phase_key
    _set_phase_status(
        planner_output,
        phase_key=phase_key,
        status="running",
        detail=detail,
    )


def _complete_pipeline_phase(
    planner_output: PlannerOutput,
    *,
    phase_key: str,
    detail: str | None = None,
) -> None:
    _set_phase_status(
        planner_output,
        phase_key=phase_key,
        status="completed",
        detail=detail,
    )


def _clip_text(value: str, *, max_chars: int) -> str:
    trimmed = value.strip()
    if len(trimmed) <= max_chars:
        return trimmed
    return trimmed[: max_chars - 20].rstrip() + "\n\n[truncated]"


def _split_spec_into_chunks(spec_text: str, *, max_chars: int = 12000) -> list[str]:
    paragraphs = [part.strip() for part in spec_text.split("\n\n") if part.strip()]
    if not paragraphs:
        return [spec_text.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(paragraph) <= max_chars:
            current = paragraph
            continue
        for start in range(0, len(paragraph), max_chars):
            part = paragraph[start : start + max_chars].strip()
            if part:
                chunks.append(part)
        current = ""
    if current:
        chunks.append(current)
    return chunks or [spec_text.strip()]


def _document_context_for_prompt(documents: list[dict], *, max_chars: int = 14000) -> str:
    blocks: list[str] = []
    remaining = max_chars
    for document in documents:
        title = str(document.get("title") or document.get("key") or "Document")
        content = str(document.get("content") or "").strip()
        if not content:
            continue
        block = f"## {title}\n\n{content}\n"
        if len(block) > remaining and blocks:
            break
        if len(block) > remaining:
            block = _clip_text(block, max_chars=remaining)
        blocks.append(block)
        remaining -= len(block)
        if remaining <= 0:
            break
    return "\n".join(blocks).strip()


def _compact_task_outline(tasks: list[dict], *, max_chars: int = 12000) -> str:
    lines: list[str] = []
    for task in tasks:
        task_id = task.get("id", "task")
        title = task.get("title", "Untitled")
        epic_id = task.get("epic_id", "epic")
        lines.append(f"- {task_id} [{epic_id}] {title}")
    return _clip_text("\n".join(lines), max_chars=max_chars)


def _normalize_dependency_patch(
    tasks: list[dict],
    payload: dict,
) -> list[dict]:
    known_ids = {str(task.get("id")) for task in tasks if task.get("id")}
    dependency_map = {
        str(task.get("id")): list(task.get("depends_on") or [])
        for task in tasks
        if task.get("id")
    }
    for row in payload.get("dependencies", []):
        task_id = str(row.get("task_id") or "")
        if task_id not in known_ids:
            continue
        depends_on = [
            dep_id
            for dep_id in row.get("depends_on", [])
            if isinstance(dep_id, str) and dep_id in known_ids and dep_id != task_id
        ]
        dependency_map[task_id] = depends_on
    normalized: list[dict] = []
    for task in tasks:
        task_id = str(task.get("id"))
        updated = dict(task)
        updated["depends_on"] = dependency_map.get(task_id, [])
        normalized.append(updated)
    return normalized


def _normalize_epic_tasks(epic: dict, payload: dict) -> list[dict]:
    epic_id = str(epic.get("id") or "epic")
    normalized: list[dict] = []
    id_map: dict[str, str] = {}
    raw_tasks = payload.get("tasks", [])
    for index, task in enumerate(raw_tasks, start=1):
        raw_id = str(task.get("id") or f"task_{index}")
        task_id = f"{epic_id}_{raw_id}"
        id_map[raw_id] = task_id
    for index, task in enumerate(raw_tasks, start=1):
        raw_id = str(task.get("id") or f"task_{index}")
        normalized_task = {
            "id": id_map[raw_id],
            "epic_id": epic_id,
            "title": str(task.get("title") or "Untitled"),
            "description": task.get("description"),
            "acceptance_criteria": list(task.get("acceptance_criteria") or []),
            "depends_on": [
                id_map.get(dep_id, dep_id)
                for dep_id in task.get("depends_on", [])
                if isinstance(dep_id, str) and dep_id in id_map and dep_id != raw_id
            ],
            "tags": list(task.get("tags") or []),
            "estimate": task.get("estimate"),
            "suggested_agent_role": task.get("suggested_agent_role"),
        }
        normalized.append(normalized_task)
    return normalized


def _count_assignable_planner_agents(
    role_agents: dict[str, list[Agent]],
    lead_agent: Agent | None,
) -> int:
    specialist_count = sum(len(agents) for agents in role_agents.values())
    if lead_agent is not None and _agent_is_assignable(lead_agent):
        return specialist_count + 1
    return max(specialist_count, 1)


def _default_initial_task_budget(*, online_assignable_agents: int) -> int:
    return max(8, min(16, 4 * max(1, online_assignable_agents)))


def _default_expansion_policy(
    *,
    online_assignable_agents: int,
    initial_task_budget: int,
) -> dict[str, object]:
    low_backlog_threshold = max(4, max(1, online_assignable_agents))
    max_new_tasks_per_round = min(8, 2 * max(1, online_assignable_agents))
    return {
        "mode": DEFAULT_EXPANSION_MODE,
        "auto_expand_enabled": True,
        "initial_task_budget": initial_task_budget,
        "low_backlog_threshold": low_backlog_threshold,
        "max_new_tasks_per_round": max_new_tasks_per_round,
        "max_new_tasks_per_epic": 2,
        "max_active_epics": DEFAULT_MAX_ACTIVE_EPICS,
        "allow_scope_growth": False,
    }


def _normalize_expansion_policy(
    policy: dict[str, object] | None,
    *,
    online_assignable_agents: int,
    initial_task_budget: int,
) -> dict[str, object]:
    normalized = _default_expansion_policy(
        online_assignable_agents=online_assignable_agents,
        initial_task_budget=initial_task_budget,
    )
    if isinstance(policy, dict):
        normalized.update(policy)
    normalized["mode"] = str(normalized.get("mode") or DEFAULT_EXPANSION_MODE)
    normalized["auto_expand_enabled"] = bool(normalized.get("auto_expand_enabled", True))
    normalized["initial_task_budget"] = int(
        normalized.get("initial_task_budget") or initial_task_budget
    )
    normalized["low_backlog_threshold"] = max(
        1,
        int(normalized.get("low_backlog_threshold") or 1),
    )
    normalized["max_new_tasks_per_round"] = max(
        1,
        int(normalized.get("max_new_tasks_per_round") or 1),
    )
    normalized["max_new_tasks_per_epic"] = max(
        1,
        int(normalized.get("max_new_tasks_per_epic") or 1),
    )
    normalized["max_active_epics"] = max(
        1,
        int(normalized.get("max_active_epics") or DEFAULT_MAX_ACTIVE_EPICS),
    )
    normalized["allow_scope_growth"] = bool(normalized.get("allow_scope_growth", False))
    return normalized


def _estimate_remaining_scope_count(epic_states: list[dict]) -> int | None:
    if not epic_states:
        return None
    return sum(len(list(state.get("open_acceptance_items") or [])) for state in epic_states)


def _build_epic_state(
    *,
    epic: dict,
    payload: dict,
    materialized_tasks: int,
    done_tasks: int = 0,
) -> dict[str, Any]:
    open_acceptance_items = [
        str(item).strip()
        for item in payload.get("open_acceptance_items", [])
        if isinstance(item, str) and str(item).strip()
    ]
    next_focus_roles = [
        str(item).strip()
        for item in payload.get("next_focus_roles", [])
        if isinstance(item, str) and str(item).strip()
    ]
    status = "planned"
    if materialized_tasks > 0:
        status = "active"
    if materialized_tasks > 0 and done_tasks >= materialized_tasks and not open_acceptance_items:
        status = "completed"
    return {
        "epic_id": str(epic.get("id") or "epic"),
        "status": status,
        "coverage_summary": payload.get("coverage_summary"),
        "remaining_work_summary": payload.get("remaining_work_summary"),
        "materialized_tasks": materialized_tasks,
        "done_tasks": done_tasks,
        "open_acceptance_items": open_acceptance_items,
        "next_focus_roles": next_focus_roles,
    }


def _normalize_task_title(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _compact_existing_epic_tasks(tasks: list[dict[str, Any]], *, max_chars: int = 6000) -> str:
    lines: list[str] = []
    for task in tasks:
        task_id = str(task.get("planner_task_id") or task.get("id") or "task")
        status = str(task.get("status") or "unknown")
        title = str(task.get("title") or "Untitled")
        role = str(task.get("suggested_agent_role") or "lead")
        lines.append(f"- {task_id} [{status}] ({role}) {title}")
    return _clip_text("\n".join(lines) or "- None yet", max_chars=max_chars)


async def _persist_planner_document(
    session: AsyncSession,
    *,
    planner_output: PlannerOutput,
    key: str,
    title: str,
    preferred_role: str,
    resolved_agent: Agent,
    content: str,
) -> dict[str, Any]:
    filename = f"planner-{planner_output.id.hex[:8]}-{key.replace('_', '-')}.md"
    storage_path, size_bytes, checksum = save_artifact_file(
        board_id=str(planner_output.board_id),
        filename=filename,
        content=content.encode("utf-8"),
    )
    artifact = Artifact(
        board_id=planner_output.board_id,
        task_id=None,
        type="plan",
        source="generated",
        filename=filename,
        mime_type="text/markdown",
        size_bytes=size_bytes,
        storage_path=storage_path,
        checksum=checksum,
        version=1,
        created_by=planner_output.created_by,
    )
    session.add(artifact)
    await session.flush()
    return {
        "key": key,
        "title": title,
        "preferred_role": preferred_role,
        "resolved_agent_id": str(resolved_agent.id),
        "resolved_agent_name": resolved_agent.name,
        "resolved_agent_role": (
            resolved_agent.identity_profile.get("role")
            if isinstance(resolved_agent.identity_profile, dict)
            else None
        ),
        "status": "completed",
        "artifact_id": str(artifact.id),
        "filename": filename,
        "content": content,
    }


async def generate_backlog_from_text(
    session: AsyncSession,
    *,
    artifact_id: UUID,
    board_id: UUID,
    spec_text: str,
    max_tasks: int | None = None,
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
        if force:
            for output in existing_outputs:
                await session.delete(output)
            await session.commit()
        else:
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
        pipeline_phase="queued",
        created_by=created_by,
        epics=[],
        tasks=[],
        documents=[],
        phase_statuses=_default_phase_statuses(),
        epic_states=[],
        expansion_policy={},
        parallelism_groups=[],
        materialized_task_count=0,
        remaining_scope_count=None,
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
    max_tasks: int | None,
) -> None:
    """Spawn background planner generation without blocking the request."""

    task = asyncio.create_task(
        _run_planner_generation(
            planner_output_id=planner_output_id,
            board_id=board_id,
            spec_text=spec_text,
            initial_task_budget=max_tasks,
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
    initial_task_budget: int | None,
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
                failed_phase=planner_output.pipeline_phase or "digest",
                error_message=f"Board {board_id} not found",
            )
            return
        try:
            role_agents, lead_agent = await _resolve_board_agents_for_planner(
                session,
                board_id=board.id,
            )
            if lead_agent is None:
                raise ValueError(
                    "No board lead agent available for planning. "
                    "Provision an agent with is_board_lead=True first."
                )

            online_assignable_agents = _count_assignable_planner_agents(
                role_agents,
                lead_agent,
            )
            seed_task_budget = (
                initial_task_budget
                if initial_task_budget is not None
                else _default_initial_task_budget(
                    online_assignable_agents=online_assignable_agents,
                )
            )
            planner_output.expansion_policy = _normalize_expansion_policy(
                planner_output.expansion_policy,
                online_assignable_agents=online_assignable_agents,
                initial_task_budget=seed_task_budget,
            )

            _set_pipeline_phase(
                planner_output,
                phase_key="digest",
                detail="Condensing the specification into a digest.",
            )
            session.add(planner_output)
            await session.commit()

            documents = await _generate_planner_documents(
                session=session,
                planner_output=planner_output,
                board=board,
                spec_text=spec_text,
                role_agents=role_agents,
                lead_agent=lead_agent,
            )
            planner_output.documents = documents
            _set_pipeline_phase(
                planner_output,
                phase_key="epics",
                detail="Synthesizing delivery epics from the dossier.",
            )
            session.add(planner_output)
            await session.commit()

            epics = await _generate_epics_from_documents(
                session=session,
                board=board,
                documents=documents,
                role_agents=role_agents,
                lead_agent=lead_agent,
            )
            planner_output.epics = epics
            _complete_pipeline_phase(
                planner_output,
                phase_key="epics",
                detail=f"Generated {len(epics)} epics.",
            )
            _set_pipeline_phase(
                planner_output,
                phase_key="tasks",
                detail="Expanding epics into board-ready task packs.",
            )
            session.add(planner_output)
            await session.commit()

            tasks, epic_states, warning = await _generate_tasks_from_epics(
                session=session,
                board=board,
                documents=documents,
                epics=epics,
                role_agents=role_agents,
                lead_agent=lead_agent,
                max_tasks=seed_task_budget,
            )
        except Exception as exc:
            await _mark_planner_output_failed(
                session,
                planner_output,
                failed_phase=planner_output.pipeline_phase or "digest",
                error_message=f"Planner pipeline failed: {exc}",
                epics=planner_output.epics,
                tasks=planner_output.tasks,
                documents=planner_output.documents,
            )
            return

        if not tasks:
            await _mark_planner_output_failed(
                session,
                planner_output,
                failed_phase="tasks",
                error_message="No tasks generated from specification",
                epics=epics,
                tasks=tasks,
                documents=documents,
            )
            return

        dag_error = validate_dag(tasks)
        if dag_error:
            await _mark_planner_output_failed(
                session,
                planner_output,
                failed_phase="tasks",
                error_message=f"DAG validation failed: {dag_error}",
                epics=epics,
                tasks=tasks,
                documents=documents,
            )
            return

        planner_output.tasks = tasks
        planner_output.epic_states = epic_states
        planner_output.parallelism_groups = compute_parallelism_groups(tasks)
        planner_output.materialized_task_count = 0
        planner_output.remaining_scope_count = _estimate_remaining_scope_count(epic_states)
        planner_output.status = "draft"
        planner_output.pipeline_phase = "ready"
        planner_output.error_message = warning
        _complete_pipeline_phase(
            planner_output,
            phase_key="tasks",
            detail=f"Generated {len(tasks)} board-ready tasks.",
        )
        _set_phase_status(
            planner_output,
            phase_key="ready",
            status="completed",
            detail="Planner package is ready for review and apply.",
        )
        session.add(planner_output)
        await session.commit()


async def _mark_planner_output_failed(
    session: AsyncSession,
    planner_output: PlannerOutput,
    *,
    failed_phase: str,
    error_message: str,
    epics: list[dict] | None = None,
    tasks: list[dict] | None = None,
    documents: list[dict] | None = None,
) -> None:
    """Persist planner failure state for UI polling and operator review."""

    planner_output.status = "failed"
    planner_output.pipeline_phase = "failed"
    planner_output.error_message = error_message
    planner_output.epics = epics or []
    planner_output.tasks = tasks or []
    planner_output.documents = documents or planner_output.documents or []
    planner_output.parallelism_groups = (
        compute_parallelism_groups(tasks or [])
        if tasks
        else []
    )
    _set_phase_status(
        planner_output,
        phase_key=failed_phase,
        status="failed",
        detail=error_message,
    )

    session.add(planner_output)
    await session.commit()


async def _generate_planner_documents(
    session: AsyncSession,
    *,
    planner_output: PlannerOutput,
    board: Board,
    spec_text: str,
    role_agents: dict[str, list[Agent]],
    lead_agent: Agent,
) -> list[dict]:
    spec_chunks = _split_spec_into_chunks(spec_text)
    chunk_notes: list[str] = []
    for index, chunk in enumerate(spec_chunks, start=1):
        chunk_note = await _call_llm_via_gateway(
            session=session,
            board=board,
            system_prompt=PLANNER_MARKDOWN_SYSTEM_PROMPT,
            user_prompt=(
                f"Summarize specification chunk {index} of {len(spec_chunks)} into concise Markdown "
                "covering product goals, key requirements, constraints, risky assumptions, and "
                "open questions.\n\n"
                f"--- SPEC CHUNK ---\n\n{chunk}"
            ),
            preferred_role="lead",
            role_agents=role_agents,
            lead_agent=lead_agent,
        )
        chunk_notes.append(chunk_note.strip())

    digest_content = await _call_llm_via_gateway(
        session=session,
        board=board,
        system_prompt=PLANNER_MARKDOWN_SYSTEM_PROMPT,
        user_prompt=(
            "Combine the chunk summaries into a single readable specification digest.\n\n"
            "Use sections:\n"
            "- Product Goal\n"
            "- Primary Users and Scenarios\n"
            "- Core Requirements\n"
            "- Constraints and Integrations\n"
            "- Risks and Open Questions\n\n"
            f"--- CHUNK SUMMARIES ---\n\n{_clip_text(chr(10).join(chunk_notes), max_chars=18000)}"
        ),
        preferred_role="lead",
        role_agents=role_agents,
        lead_agent=lead_agent,
    )

    digest_agent = _select_planning_agent(
        preferred_role="lead",
        role_agents=role_agents,
        lead_agent=lead_agent,
    )
    documents = [
        await _persist_planner_document(
            session,
            planner_output=planner_output,
            key="spec_digest",
            title="Specification Digest",
            preferred_role="lead",
            resolved_agent=digest_agent,
            content=digest_content.strip(),
        )
    ]
    planner_output.documents = list(documents)
    _complete_pipeline_phase(
        planner_output,
        phase_key="digest",
        detail="Specification digest is ready for downstream planning.",
    )
    session.add(planner_output)
    await session.commit()

    _set_phase_status(
        planner_output,
        phase_key="dossier",
        status="running",
        detail="Generating delivery documents for product, engineering, QA, docs, and ops.",
    )
    planner_output.pipeline_phase = "dossier"
    session.add(planner_output)
    await session.commit()

    digest_context = digest_content.strip()
    for blueprint in PLANNER_DOCUMENT_BLUEPRINTS[1:]:
        resolved_agent = _select_planning_agent(
            preferred_role=str(blueprint["preferred_role"]),
            role_agents=role_agents,
            lead_agent=lead_agent,
        )
        content = await _call_llm_via_gateway(
            session=session,
            board=board,
            system_prompt=PLANNER_MARKDOWN_SYSTEM_PROMPT,
            user_prompt=(
                f"Create the planner document titled '{blueprint['title']}'.\n\n"
                f"Document goal: {blueprint['instructions']}\n\n"
                "Output a Markdown document with a short summary, key sections, and concrete "
                "recommendations that a human owner can review quickly in the UI.\n\n"
                f"--- SPECIFICATION DIGEST ---\n\n{digest_context}"
            ),
            preferred_role=str(blueprint["preferred_role"]),
            role_agents=role_agents,
            lead_agent=lead_agent,
        )
        document = await _persist_planner_document(
            session,
            planner_output=planner_output,
            key=str(blueprint["key"]),
            title=str(blueprint["title"]),
            preferred_role=str(blueprint["preferred_role"]),
            resolved_agent=resolved_agent,
            content=content.strip(),
        )
        documents.append(document)
        planner_output.documents = list(documents)
        session.add(planner_output)
        await session.commit()

    _complete_pipeline_phase(
        planner_output,
        phase_key="dossier",
        detail=f"Generated {len(documents)} readable planner documents.",
    )
    session.add(planner_output)
    await session.commit()
    return documents


async def _generate_epics_from_documents(
    session: AsyncSession,
    *,
    board: Board,
    documents: list[dict],
    role_agents: dict[str, list[Agent]],
    lead_agent: Agent,
) -> list[dict]:
    response_text = await _call_llm_via_gateway(
        session=session,
        board=board,
        system_prompt=PLANNER_EPICS_SYSTEM_PROMPT,
        user_prompt=(
            "Create the delivery epic map for this project based on the planner dossier.\n\n"
            f"--- DOSSIER ---\n\n{_document_context_for_prompt(documents)}"
        ),
        preferred_role="lead",
        role_agents=role_agents,
        lead_agent=lead_agent,
    )
    parsed = _extract_json_from_response(response_text)
    if not parsed:
        raise ValueError("Failed to parse epic synthesis response as JSON")
    epics = list(parsed.get("epics", []))
    if not epics:
        raise ValueError("Epic synthesis returned no epics")
    return epics


async def _generate_tasks_from_epics(
    session: AsyncSession,
    *,
    board: Board,
    documents: list[dict],
    epics: list[dict],
    role_agents: dict[str, list[Agent]],
    lead_agent: Agent,
    max_tasks: int,
) -> tuple[list[dict], list[dict], str | None]:
    if not epics:
        return [], [], None

    document_context = _document_context_for_prompt(documents)
    per_epic_limit = max(1, min(3, max_tasks // max(1, len(epics)) or 1))
    tasks: list[dict] = []
    epic_states: list[dict] = []

    for epic in epics:
        response_text = await _call_llm_via_gateway(
            session=session,
            board=board,
            system_prompt=PLANNER_TASK_PACK_SYSTEM_PROMPT,
            user_prompt=(
                f"Create the initial seed task pack for the epic '{epic.get('title', 'Untitled Epic')}'.\n\n"
                f"Epic description: {epic.get('description', '')}\n"
                f"Target task budget: up to {per_epic_limit} tasks.\n\n"
                "Generate only the initial tasks for this epic. Include implementation, QA, docs, "
                "and ops work that belongs inside this epic, but leave later scope in the "
                "remaining_work_summary and open_acceptance_items fields.\n\n"
                f"--- DOSSIER ---\n\n{document_context}"
            ),
            preferred_role="lead",
            role_agents=role_agents,
            lead_agent=lead_agent,
        )
        parsed = _extract_json_from_response(response_text)
        if not parsed:
            raise ValueError(
                f"Failed to parse task pack JSON for epic {epic.get('title', 'unknown')}"
            )
        epic_tasks = _normalize_epic_tasks(epic, parsed)
        if not epic_tasks:
            raise ValueError(f"Task expansion returned no tasks for epic {epic.get('title', 'unknown')}")
        tasks.extend(epic_tasks)
        epic_states.append(
            _build_epic_state(
                epic=epic,
                payload=parsed,
                materialized_tasks=len(epic_tasks),
            )
        )

    warning: str | None = None
    try:
        dependency_response = await _call_llm_via_gateway(
            session=session,
            board=board,
            system_prompt=PLANNER_DEPENDENCY_SYSTEM_PROMPT,
            user_prompt=(
                "Normalize the task dependencies for this existing task list.\n\n"
                "Return only required dependencies between the provided tasks.\n\n"
                f"--- TASK OUTLINE ---\n\n{_compact_task_outline(tasks)}"
            ),
            preferred_role="lead",
            role_agents=role_agents,
            lead_agent=lead_agent,
        )
        parsed = _extract_json_from_response(dependency_response)
        if parsed:
            normalized = _normalize_dependency_patch(tasks, parsed)
            dag_error = validate_dag(normalized)
            if dag_error is None:
                tasks = normalized
            else:
                warning = f"Dependency normalization skipped: {dag_error}"
        else:
            warning = "Dependency normalization skipped: invalid JSON response"
    except Exception as exc:
        warning = f"Dependency normalization skipped: {exc}"

    if len(tasks) > max_tasks:
        tasks = tasks[:max_tasks]
        kept_ids = {str(task.get("id")) for task in tasks if task.get("id")}
        tasks = [
            {
                **task,
                "depends_on": [
                    dep_id
                    for dep_id in task.get("depends_on", [])
                    if dep_id in kept_ids
                ],
            }
            for task in tasks
        ]
        materialized_by_epic: dict[str, int] = {}
        for task in tasks:
            epic_id = str(task.get("epic_id") or "")
            if epic_id:
                materialized_by_epic[epic_id] = materialized_by_epic.get(epic_id, 0) + 1
        for state in epic_states:
            epic_id = str(state.get("epic_id") or "")
            state["materialized_tasks"] = materialized_by_epic.get(epic_id, 0)
            state["status"] = "active" if state["materialized_tasks"] else "planned"
        warning = (
            f"{warning}; seed task list trimmed to {max_tasks}"
            if warning
            else f"Seed task list trimmed to {max_tasks}"
        )
    return tasks, epic_states, warning


async def generate_backlog(
    session: AsyncSession,
    *,
    artifact_id: UUID,
    board_id: UUID,
    max_tasks: int | None = None,
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
    preferred_role: str = "lead",
    role_agents: dict[str, list[Agent]] | None = None,
    lead_agent: Agent | None = None,
) -> str:
    """Send a planning request through the OpenClaw Gateway to a planner agent.

    Uses the gateway WebSocket RPC to send a message to the selected planner agent
    and waits for a response by polling chat history with request correlation.
    """
    from uuid import uuid4

    from app.services.openclaw.gateway_dispatch import GatewayDispatchService

    dispatch = GatewayDispatchService(session)
    _gateway, config = await dispatch.require_gateway_config_for_board(board)

    if role_agents is None or lead_agent is None:
        role_agents, lead_agent = await _resolve_board_agents_for_planner(
            session,
            board_id=board.id,
        )
    if lead_agent is None:
        raise ValueError(
            "No board lead agent available for planning. "
            "Provision an agent with is_board_lead=True first."
        )

    target_agent = _select_planning_agent(
        preferred_role=preferred_role,
        role_agents=role_agents,
        lead_agent=lead_agent,
    )
    if not target_agent.openclaw_session_id:
        raise ValueError(
            f"Planner agent '{target_agent.name}' has no active session. "
            "Run template sync to provision the agent."
        )

    request_id = uuid4().hex[:12]
    request_marker = f"\n\n[PLANNER_REQUEST:{request_id}]"
    isolated_session_key = f"{target_agent.openclaw_session_id}:planner:{request_id}"
    role_label = (
        str(target_agent.identity_profile.get("role") or "").strip()
        if isinstance(target_agent.identity_profile, dict)
        else ""
    )
    role_context = (
        f"You are acting as the board's {role_label or target_agent.name}. "
        "This is an isolated planning session, not the agent's live heartbeat thread."
    )
    full_message = f"{role_context}\n\n{system_prompt}\n\n{user_prompt}{request_marker}"

    await dispatch.send_agent_message(
        session_key=isolated_session_key,
        config=config,
        agent_name=f"{target_agent.name} Planner",
        message=full_message,
        deliver=True,
    )

    try:
        return await _wait_for_agent_response(
            session_key=isolated_session_key,
            config=config,
            history_cursor=0,
            request_marker=f"[PLANNER_RESPONSE:{request_id}]",
            timeout=300,
        )
    finally:
        from app.services.openclaw.gateway_rpc import delete_session

        try:
            await delete_session(isolated_session_key, config=config)
        except Exception:
            logger.warning(
                "planner.gateway.session_cleanup_failed",
                extra={"session_key": isolated_session_key},
            )


async def _get_history_length(session_key: str, config: Any) -> int:
    """Get current chat history length before sending a request."""
    from app.services.openclaw.gateway_rpc import openclaw_call

    try:
        history = await openclaw_call(
            "chat.history",
            {"sessionKey": session_key, "limit": 1},
            config=config,
        )
        messages, total = _extract_gateway_history(history)
        return total or len(messages)
    except Exception:
        return 0


def _extract_gateway_history(history: Any) -> tuple[list[dict[str, Any]], int]:
    """Normalize gateway history payloads returned by different layers."""
    if isinstance(history, dict):
        for key in ("messages", "history"):
            value = history.get(key)
            if isinstance(value, list):
                normalized = [item for item in value if isinstance(item, dict)]
                total = history.get("total")
                if isinstance(total, int):
                    return normalized, total
                return normalized, len(normalized)
    if isinstance(history, list):
        normalized = [item for item in history if isinstance(item, dict)]
        return normalized, len(normalized)
    return [], 0


def _extract_message_text(content: Any) -> str:
    """Flatten structured gateway content into plain text for correlation."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [_extract_message_text(item) for item in content]
        return "\n".join(part for part in parts if part).strip()
    if isinstance(content, dict):
        block_type = str(content.get("type", "")).lower()
        if block_type in {"thinking", "toolcall", "toolresult"}:
            return ""
        for key in ("text", "markdown", "content"):
            value = content.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        if "items" in content:
            return _extract_message_text(content.get("items"))
    return ""


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
                {"sessionKey": session_key, "limit": 20},
                config=config,
            )
            messages, total = _extract_gateway_history(history)
            total = total or len(messages)

            if total > history_cursor:
                message_delta = max(total - history_cursor, 0)
                if message_delta <= 0:
                    new_messages = []
                else:
                    new_messages = messages[-min(len(messages), message_delta) :]
                fallback_response: str | None = None
                for msg in reversed(new_messages):
                    role = msg.get("role", "")
                    content = _extract_message_text(msg.get("content"))
                    if role in ("assistant", "agent", "model") and content:
                        if request_marker and request_marker in content:
                            return content.replace(request_marker, "").strip()
                        if not request_marker:
                            return content
                        if fallback_response is None:
                            fallback_response = content
                if fallback_response:
                    return fallback_response
        except Exception:
            pass
        await asyncio.sleep(2)

    raise RuntimeError("Timeout waiting for agent response")


def _sync_epic_states_with_materialized_tasks(
    planner_output: PlannerOutput,
    *,
    materialized_tasks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    task_counts: dict[str, dict[str, int]] = {}
    for task in materialized_tasks:
        epic_id = str(task.get("planner_epic_id") or task.get("epic_id") or "")
        if not epic_id:
            continue
        state = task_counts.setdefault(
            epic_id,
            {"materialized": 0, "done": 0, "blocked_open": 0, "open": 0},
        )
        state["materialized"] += 1
        if str(task.get("status") or "") == "done":
            state["done"] += 1
        else:
            state["open"] += 1
            if bool(task.get("is_blocked")):
                state["blocked_open"] += 1

    updated: list[dict[str, Any]] = []
    for state in planner_output.epic_states or []:
        epic_id = str(state.get("epic_id") or "")
        counts = task_counts.get(
            epic_id,
            {"materialized": 0, "done": 0, "blocked_open": 0, "open": 0},
        )
        next_state = dict(state)
        next_state["materialized_tasks"] = counts["materialized"]
        next_state["done_tasks"] = counts["done"]
        open_acceptance_items = list(next_state.get("open_acceptance_items") or [])
        if counts["materialized"] == 0:
            next_state["status"] = "planned"
        elif counts["open"] == 0 and not open_acceptance_items:
            next_state["status"] = "completed"
        elif counts["open"] > 0 and counts["blocked_open"] == counts["open"]:
            next_state["status"] = "blocked"
        else:
            next_state["status"] = "active"
        updated.append(next_state)
    return updated


async def _create_board_tasks_from_planner_tasks(
    session: AsyncSession,
    *,
    planner_output: PlannerOutput,
    board: Board,
    tasks: list[dict],
    role_agents: dict[str, list[Agent]],
    lead_agent: Agent | None,
    materialized_from: str,
    expansion_round: int,
) -> list[UUID]:
    from app.models.tag_assignments import TagAssignment
    from app.models.tags import Tag
    from app.models.task_dependencies import TaskDependency
    from app.models.tasks import Task
    from app.services.tags import slugify_tag

    id_map: dict[str, UUID] = {}
    created_ids: list[UUID] = []

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
            planner_output_id=planner_output.id,
            planner_epic_id=task_data.get("epic_id"),
            materialized_from=materialized_from,
            expansion_round=expansion_round,
            assigned_agent_id=assignee.id if assignee is not None else None,
            auto_created=True,
            auto_reason=f"planner_output:{planner_output.id}",
        )
        session.add(task)
        id_map[str(task_data["id"])] = task.id
        created_ids.append(task.id)

    await session.flush()

    for task_data in tasks:
        new_id = id_map[str(task_data["id"])]
        for dep_id in task_data.get("depends_on", []):
            if dep_id in id_map:
                session.add(
                    TaskDependency(
                        board_id=planner_output.board_id,
                        task_id=new_id,
                        depends_on_task_id=id_map[dep_id],
                    )
                )

        tags = task_data.get("tags", [])
        for tag_name in tags:
            tag_slug = slugify_tag(str(tag_name))
            tag = await Tag.objects.filter_by(
                organization_id=board.organization_id,
                slug=tag_slug,
            ).first(session)
            if not tag:
                tag = Tag(
                    organization_id=board.organization_id,
                    name=str(tag_name),
                    slug=tag_slug,
                    color="blue",
                )
                session.add(tag)
                await session.flush()
            session.add(TagAssignment(task_id=new_id, tag_id=tag.id))

    return created_ids


async def apply_planner_output(
    session: AsyncSession,
    planner_output: PlannerOutput,
    *,
    tasks_override: list[dict] | None = None,
    epics_override: list[dict] | None = None,
) -> PlannerOutput:
    """Apply a planner output by creating the initial materialized task batch on the board."""

    tasks = tasks_override or planner_output.tasks
    epics = epics_override or planner_output.epics

    dag_error = validate_dag(tasks)
    if dag_error:
        raise ValueError(f"Cannot apply: {dag_error}")

    if planner_output.status == "applied":
        raise ValueError("Planner output has already been applied")

    board = await Board.objects.by_id(planner_output.board_id).first(session)
    if board is None:
        raise ValueError(f"Board {planner_output.board_id} not found")

    role_agents, lead_agent = await _resolve_board_agents_for_planner(
        session,
        board_id=planner_output.board_id,
    )
    await _create_board_tasks_from_planner_tasks(
        session,
        planner_output=planner_output,
        board=board,
        tasks=tasks,
        role_agents=role_agents,
        lead_agent=lead_agent,
        materialized_from="initial",
        expansion_round=0,
    )

    planner_output.status = "applied"
    planner_output.applied_at = utcnow()
    planner_output.epics = epics
    planner_output.tasks = tasks
    planner_output.materialized_task_count = len(tasks)
    planner_output.epic_states = _sync_epic_states_with_materialized_tasks(
        planner_output,
        materialized_tasks=[
            {
                "epic_id": task.get("epic_id"),
                "planner_epic_id": task.get("epic_id"),
                "status": "inbox",
                "is_blocked": False,
            }
            for task in tasks
        ],
    )
    planner_output.remaining_scope_count = _estimate_remaining_scope_count(
        planner_output.epic_states,
    )

    session.add(planner_output)
    await session.commit()
    await _notify_lead_of_planner_package(
        session,
        planner_output=planner_output,
        lead_agent=lead_agent,
        task_count=len(tasks),
    )
    await session.refresh(planner_output)
    return planner_output


async def _notify_lead_of_planner_package(
    session: AsyncSession,
    *,
    planner_output: PlannerOutput,
    lead_agent: Agent | None,
    task_count: int,
) -> None:
    if lead_agent is None or not lead_agent.openclaw_session_id:
        return

    board = await Board.objects.by_id(planner_output.board_id).first(session)
    if board is None:
        return

    documents = planner_output.documents or []
    document_lines_list: list[str] = []
    for doc in documents:
        line = f"- {doc.get('title', doc.get('key', 'Document'))}"
        artifact_id = doc.get("artifact_id")
        if artifact_id:
            line += f" (artifact {artifact_id})"
        document_lines_list.append(line)
    document_lines = "\n".join(document_lines_list)
    epic_lines = "\n".join(
        f"- {epic.get('title', epic.get('id', 'Epic'))}"
        for epic in planner_output.epics[:8]
    )
    message = (
        "Approved planner package is ready for execution.\n\n"
        f"Board: {board.name}\n"
        f"Planner output: {planner_output.id}\n"
        f"Tasks created: {task_count}\n\n"
        "Planner dossier documents:\n"
        f"{document_lines or '- None'}\n\n"
        "Epics:\n"
        f"{epic_lines or '- None'}\n\n"
        "Start orchestration from this approved planner package. "
        "Use the generated dossier and epic/task structure as the source of truth for coordination."
    )

    try:
        from app.services.openclaw.gateway_dispatch import GatewayDispatchService

        await GatewayDispatchService(session).send_to_agent(
            agent=lead_agent,
            message=message,
            deliver=True,
        )
    except Exception:
        logger.warning(
            "Failed to notify lead after planner apply",
            extra={
                "planner_output_id": str(planner_output.id),
                "lead_agent_id": str(lead_agent.id),
            },
        )


async def list_planner_expansion_runs(
    session: AsyncSession,
    *,
    planner_output_id: UUID,
    limit: int = 20,
) -> list[PlannerExpansionRun]:
    return list(
        await PlannerExpansionRun.objects.filter_by(planner_output_id=planner_output_id)
        .order_by(col(PlannerExpansionRun.created_at).desc())
        .limit(limit)
        .all(session)
    )


async def _latest_planner_expansion_run(
    session: AsyncSession,
    *,
    planner_output_id: UUID,
) -> PlannerExpansionRun | None:
    return (
        await PlannerExpansionRun.objects.filter_by(planner_output_id=planner_output_id)
        .order_by(col(PlannerExpansionRun.created_at).desc())
        .first(session)
    )


async def _active_planner_expansion_run(
    session: AsyncSession,
    *,
    planner_output_id: UUID,
) -> PlannerExpansionRun | None:
    return (
        await PlannerExpansionRun.objects.filter_by(planner_output_id=planner_output_id)
        .filter(col(PlannerExpansionRun.status).in_(tuple(PLANNER_EXPANSION_RUNNING_STATUSES)))
        .first(session)
    )


async def _latest_applied_planner_output_for_board(
    session: AsyncSession,
    *,
    board_id: UUID,
) -> PlannerOutput | None:
    return (
        await PlannerOutput.objects.filter_by(board_id=board_id, status="applied")
        .order_by(col(PlannerOutput.applied_at).desc(), col(PlannerOutput.created_at).desc())
        .first(session)
    )


async def _load_materialized_task_snapshots(
    session: AsyncSession,
    *,
    board_id: UUID,
    planner_output_id: UUID,
) -> list[dict[str, Any]]:
    from app.models.tasks import Task
    from app.services.task_dependencies import (
        blocked_by_dependency_ids,
        dependency_ids_by_task_id,
        dependency_status_by_id,
    )

    tasks = list(
        await Task.objects.filter_by(board_id=board_id, planner_output_id=planner_output_id)
        .order_by(col(Task.created_at).asc())
        .all(session)
    )
    task_ids = [task.id for task in tasks]
    deps_by_task_id = await dependency_ids_by_task_id(
        session,
        board_id=board_id,
        task_ids=task_ids,
    )
    all_dependency_ids = list({dep_id for values in deps_by_task_id.values() for dep_id in values})
    dependency_statuses = await dependency_status_by_id(
        session,
        board_id=board_id,
        dependency_ids=all_dependency_ids,
    )

    snapshots: list[dict[str, Any]] = []
    for task in tasks:
        dep_ids = deps_by_task_id.get(task.id, [])
        blocked_by = blocked_by_dependency_ids(
            dependency_ids=dep_ids,
            status_by_id=dependency_statuses,
        )
        snapshots.append(
            {
                "id": str(task.id),
                "title": task.title,
                "status": task.status,
                "planner_task_id": task.planner_task_id,
                "epic_id": task.epic_id,
                "planner_epic_id": task.planner_epic_id,
                "suggested_agent_role": task.suggested_agent_role,
                "materialized_from": task.materialized_from,
                "expansion_round": task.expansion_round,
                "is_blocked": bool(blocked_by) if task.status != "done" else False,
            }
        )
    return snapshots


def _merge_epic_state_updates(
    *,
    current_states: list[dict[str, Any]],
    updated_states: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    updates_by_epic = {
        str(state.get("epic_id") or ""): state
        for state in updated_states
        if state.get("epic_id")
    }
    merged: list[dict[str, Any]] = []
    for state in current_states:
        epic_id = str(state.get("epic_id") or "")
        merged_state = dict(state)
        merged_state.update(updates_by_epic.get(epic_id, {}))
        merged.append(merged_state)
    return merged


def _pick_epics_for_expansion(
    *,
    planner_output: PlannerOutput,
    max_active_epics: int,
) -> list[dict[str, Any]]:
    epic_index = {
        str(epic.get("id") or ""): index for index, epic in enumerate(planner_output.epics)
    }
    states = list(planner_output.epic_states or [])
    actionable_active = [
        state
        for state in states
        if state.get("status") in {"active", "blocked"}
        and (
            state.get("remaining_work_summary")
            or list(state.get("open_acceptance_items") or [])
        )
    ]
    if actionable_active:
        actionable_active.sort(
            key=lambda state: (
                state.get("status") == "blocked",
                int(state.get("materialized_tasks") or 0),
                epic_index.get(str(state.get("epic_id") or ""), 999),
            )
        )
        return actionable_active[:max_active_epics]

    planned = [state for state in states if state.get("status") == "planned"]
    planned.sort(key=lambda state: epic_index.get(str(state.get("epic_id") or ""), 999))
    return planned[:max_active_epics]


def _normalize_expansion_tasks(
    epic: dict[str, Any],
    payload: dict[str, Any],
    *,
    round_number: int,
) -> list[dict[str, Any]]:
    epic_id = str(epic.get("id") or "epic")
    normalized: list[dict[str, Any]] = []
    raw_tasks = list(payload.get("tasks", []))
    raw_id_map: dict[str, str] = {}
    for index, task in enumerate(raw_tasks, start=1):
        raw_id = str(task.get("id") or f"task_{index}")
        raw_id_map[raw_id] = f"{epic_id}_r{round_number}_{raw_id}"
    for index, task in enumerate(raw_tasks, start=1):
        raw_id = str(task.get("id") or f"task_{index}")
        normalized.append(
            {
                "id": raw_id_map[raw_id],
                "epic_id": epic_id,
                "title": str(task.get("title") or "Untitled"),
                "description": task.get("description"),
                "acceptance_criteria": list(task.get("acceptance_criteria") or []),
                "depends_on": [
                    raw_id_map.get(dep_id, dep_id)
                    for dep_id in task.get("depends_on", [])
                    if isinstance(dep_id, str) and dep_id in raw_id_map and dep_id != raw_id
                ],
                "tags": list(task.get("tags") or []),
                "estimate": task.get("estimate"),
                "suggested_agent_role": task.get("suggested_agent_role"),
            }
        )
    return normalized


def _dedupe_expansion_tasks(
    *,
    candidate_tasks: list[dict[str, Any]],
    existing_tasks: list[dict[str, Any]],
    max_new_tasks: int,
) -> list[dict[str, Any]]:
    existing_ids = {
        str(task.get("planner_task_id") or "")
        for task in existing_tasks
        if task.get("planner_task_id")
    }
    existing_titles = {
        (
            str(task.get("planner_epic_id") or task.get("epic_id") or ""),
            _normalize_task_title(task.get("title")),
        )
        for task in existing_tasks
    }
    kept: list[dict[str, Any]] = []
    kept_ids: set[str] = set()
    kept_titles: set[tuple[str, str]] = set()
    for task in candidate_tasks:
        task_id = str(task.get("id") or "")
        epic_id = str(task.get("epic_id") or "")
        title_key = (epic_id, _normalize_task_title(task.get("title")))
        if not task_id or task_id in existing_ids or task_id in kept_ids:
            continue
        if title_key in existing_titles or title_key in kept_titles:
            continue
        kept.append(dict(task))
        kept_ids.add(task_id)
        kept_titles.add(title_key)
        if len(kept) >= max_new_tasks:
            break
    valid_ids = {str(task.get("id")) for task in kept}
    for task in kept:
        task["depends_on"] = [
            dep_id for dep_id in task.get("depends_on", []) if dep_id in valid_ids
        ]
    return kept


def _remaining_scope_summary(epic_states: list[dict[str, Any]]) -> str | None:
    lines = [
        f"- {state.get('epic_id')}: {state.get('remaining_work_summary')}"
        for state in epic_states
        if state.get("remaining_work_summary")
    ]
    if not lines:
        return None
    return "\n".join(lines[:6])


def _default_backfilled_epic_states(planner_output: PlannerOutput) -> list[dict[str, Any]]:
    seed_tasks_by_epic: dict[str, list[dict[str, Any]]] = {}
    for task in planner_output.tasks or []:
        epic_id = str(task.get("epic_id") or "")
        if not epic_id:
            continue
        seed_tasks_by_epic.setdefault(epic_id, []).append(task)

    states: list[dict[str, Any]] = []
    for epic in planner_output.epics or []:
        epic_id = str(epic.get("id") or "")
        epic_tasks = seed_tasks_by_epic.get(epic_id, [])
        next_focus_roles = [
            str(role)
            for role in {
                task.get("suggested_agent_role")
                for task in epic_tasks
                if task.get("suggested_agent_role")
            }
        ]
        states.append(
            {
                "epic_id": epic_id,
                "status": "active" if epic_tasks else "planned",
                "coverage_summary": (
                    "Initial seed task package was created for this epic."
                    if epic_tasks
                    else "Epic exists in the approved planner package but has not been materialized yet."
                ),
                "remaining_work_summary": (
                    "Use the approved dossier and current board state to materialize the next in-scope tasks for this epic."
                ),
                "materialized_tasks": len(epic_tasks),
                "done_tasks": 0,
                "open_acceptance_items": [],
                "next_focus_roles": next_focus_roles,
            }
        )
    return states


async def _backfill_existing_planner_package_state(
    session: AsyncSession,
    *,
    planner_output: PlannerOutput,
) -> None:
    from app.models.tasks import Task

    task_map = {
        str(task.get("id") or ""): task for task in planner_output.tasks or [] if task.get("id")
    }
    if not task_map:
        if not planner_output.epic_states and planner_output.epics:
            planner_output.epic_states = _default_backfilled_epic_states(planner_output)
            planner_output.remaining_scope_count = _estimate_remaining_scope_count(
                planner_output.epic_states,
            )
            session.add(planner_output)
            await session.commit()
        return

    candidates = list(
        await Task.objects.filter_by(board_id=planner_output.board_id)
        .filter(
            col(Task.planner_output_id).is_(None),
            col(Task.auto_reason) == f"planner_output:{planner_output.id}",
        )
        .all(session)
    )
    changed = False
    for task in candidates:
        planner_task_id = str(task.planner_task_id or "")
        seed_task = task_map.get(planner_task_id)
        if seed_task is None:
            continue
        task.planner_output_id = planner_output.id
        task.planner_epic_id = str(
            seed_task.get("epic_id") or task.epic_id or ""
        ) or None
        task.materialized_from = task.materialized_from or "initial"
        task.expansion_round = 0 if task.expansion_round is None else task.expansion_round
        session.add(task)
        changed = True

    if not planner_output.epic_states and planner_output.epics:
        planner_output.epic_states = _default_backfilled_epic_states(planner_output)
        planner_output.remaining_scope_count = _estimate_remaining_scope_count(
            planner_output.epic_states,
        )
        session.add(planner_output)
        changed = True

    if changed:
        await session.commit()


async def get_board_execution_coverage(
    session: AsyncSession,
    *,
    board_id: UUID,
) -> dict[str, Any]:
    board = await Board.objects.by_id(board_id).first(session)
    if board is None:
        raise ValueError(f"Board {board_id} not found")

    planner_output = await _latest_applied_planner_output_for_board(session, board_id=board_id)
    if planner_output is None:
        return {
            "board_id": board_id,
            "planner_output_id": None,
            "planner_status": None,
            "docs_count": 0,
            "epics_total": 0,
            "epics_active": 0,
            "epics_completed": 0,
            "materialized_tasks": 0,
            "done_tasks": 0,
            "in_progress_tasks": 0,
            "review_tasks": 0,
            "inbox_tasks": 0,
            "remaining_scope_count": None,
            "remaining_scope_summary": None,
            "active_epics": [],
            "next_expansion_eligible": False,
            "next_expansion_reason": "No applied planner package yet.",
            "auto_expand_enabled": False,
            "expansion_policy": {},
            "last_expansion_run": None,
        }

    await _backfill_existing_planner_package_state(
        session,
        planner_output=planner_output,
    )
    task_snapshots = await _load_materialized_task_snapshots(
        session,
        board_id=board_id,
        planner_output_id=planner_output.id,
    )
    planner_output.epic_states = _sync_epic_states_with_materialized_tasks(
        planner_output,
        materialized_tasks=task_snapshots,
    )
    role_agents, lead_agent = await _resolve_board_agents_for_planner(
        session,
        board_id=board_id,
    )
    policy = _normalize_expansion_policy(
        planner_output.expansion_policy,
        online_assignable_agents=_count_assignable_planner_agents(role_agents, lead_agent),
        initial_task_budget=int(
            (planner_output.expansion_policy or {}).get("initial_task_budget") or len(planner_output.tasks) or 8
        ),
    )
    active_run = await _active_planner_expansion_run(
        session,
        planner_output_id=planner_output.id,
    )
    unblocked_non_done = sum(
        1
        for task in task_snapshots
        if task.get("status") != "done" and not bool(task.get("is_blocked"))
    )
    threshold = int(policy.get("low_backlog_threshold") or 1)
    eligible = (
        not board.is_paused
        and bool(policy.get("auto_expand_enabled"))
        and active_run is None
        and unblocked_non_done < threshold
    )
    if board.is_paused:
        eligibility_reason = "Board is paused."
    elif not bool(policy.get("auto_expand_enabled")):
        eligibility_reason = "Auto-expand is paused."
    elif active_run is not None:
        eligibility_reason = f"Expansion round {active_run.round_number} is still running."
    elif unblocked_non_done >= threshold:
        eligibility_reason = (
            f"Ready backlog buffer is healthy ({unblocked_non_done}/{threshold})."
        )
    else:
        eligibility_reason = "Ready backlog is below the buffered threshold."

    last_run = await _latest_planner_expansion_run(
        session,
        planner_output_id=planner_output.id,
    )
    status_counts = {"done": 0, "in_progress": 0, "review": 0, "inbox": 0}
    for task in task_snapshots:
        status_key = str(task.get("status") or "")
        if status_key in status_counts:
            status_counts[status_key] += 1

    active_epics = [
        state
        for state in planner_output.epic_states
        if state.get("status") in {"active", "blocked"}
    ]
    return {
        "board_id": board_id,
        "planner_output_id": planner_output.id,
        "planner_status": planner_output.status,
        "docs_count": len(planner_output.documents or []),
        "epics_total": len(planner_output.epics or []),
        "epics_active": len([state for state in planner_output.epic_states if state.get("status") == "active"]),
        "epics_completed": len([state for state in planner_output.epic_states if state.get("status") == "completed"]),
        "materialized_tasks": len(task_snapshots),
        "done_tasks": status_counts["done"],
        "in_progress_tasks": status_counts["in_progress"],
        "review_tasks": status_counts["review"],
        "inbox_tasks": status_counts["inbox"],
        "remaining_scope_count": _estimate_remaining_scope_count(planner_output.epic_states),
        "remaining_scope_summary": _remaining_scope_summary(planner_output.epic_states),
        "active_epics": active_epics,
        "next_expansion_eligible": eligible,
        "next_expansion_reason": eligibility_reason,
        "auto_expand_enabled": bool(policy.get("auto_expand_enabled")),
        "expansion_policy": policy,
        "last_expansion_run": last_run,
    }


def _launch_planner_expansion(
    *,
    planner_output_id: UUID,
    expansion_run_id: UUID,
    max_new_tasks: int | None,
) -> None:
    task = asyncio.create_task(
        _run_planner_expansion(
            planner_output_id=planner_output_id,
            expansion_run_id=expansion_run_id,
            max_new_tasks=max_new_tasks,
        )
    )

    def _log_task_result(done_task: asyncio.Task[None]) -> None:
        try:
            done_task.result()
        except Exception:
            logger.exception(
                "Planner background expansion crashed",
                extra={
                    "planner_output_id": str(planner_output_id),
                    "expansion_run_id": str(expansion_run_id),
                },
            )

    task.add_done_callback(_log_task_result)


async def queue_planner_expansion(
    session: AsyncSession,
    *,
    planner_output: PlannerOutput,
    trigger: str = "manual",
    max_new_tasks: int | None = None,
) -> PlannerOutput:
    if planner_output.status != "applied":
        raise ValueError("Only applied planner outputs can be expanded")

    board = await Board.objects.by_id(planner_output.board_id).first(session)
    if board is None:
        raise ValueError(f"Board {planner_output.board_id} not found")
    if board.is_paused:
        raise ValueError("Board is paused")

    await _backfill_existing_planner_package_state(
        session,
        planner_output=planner_output,
    )

    active_run = await _active_planner_expansion_run(
        session,
        planner_output_id=planner_output.id,
    )
    if active_run is not None:
        return planner_output

    role_agents, lead_agent = await _resolve_board_agents_for_planner(
        session,
        board_id=planner_output.board_id,
    )
    policy = _normalize_expansion_policy(
        planner_output.expansion_policy,
        online_assignable_agents=_count_assignable_planner_agents(role_agents, lead_agent),
        initial_task_budget=int(
            (planner_output.expansion_policy or {}).get("initial_task_budget")
            or len(planner_output.tasks)
            or 8
        ),
    )
    planner_output.expansion_policy = policy
    if trigger in PLANNER_EXPANSION_AUTO_TRIGGERS and not bool(policy.get("auto_expand_enabled")):
        return planner_output

    latest_run = await _latest_planner_expansion_run(
        session,
        planner_output_id=planner_output.id,
    )
    run = PlannerExpansionRun(
        planner_output_id=planner_output.id,
        board_id=planner_output.board_id,
        round_number=(latest_run.round_number + 1) if latest_run is not None else 1,
        status="running",
        trigger=trigger,
        source_epic_ids=[],
        created_task_ids=[],
        updated_at=utcnow(),
    )
    session.add(planner_output)
    session.add(run)
    await session.commit()
    await session.refresh(planner_output)
    await session.refresh(run)
    _launch_planner_expansion(
        planner_output_id=planner_output.id,
        expansion_run_id=run.id,
        max_new_tasks=max_new_tasks,
    )
    return planner_output


async def maybe_queue_auto_expand_for_board(
    session: AsyncSession,
    *,
    board_id: UUID,
    trigger: str,
) -> PlannerOutput | None:
    planner_output = await _latest_applied_planner_output_for_board(session, board_id=board_id)
    if planner_output is None:
        return None
    board = await Board.objects.by_id(board_id).first(session)
    if board is None or board.is_paused:
        return None
    coverage = await get_board_execution_coverage(session, board_id=board_id)
    if not coverage["next_expansion_eligible"]:
        return None
    return await queue_planner_expansion(
        session,
        planner_output=planner_output,
        trigger=trigger,
        max_new_tasks=None,
    )


async def _notify_lead_of_expansion(
    session: AsyncSession,
    *,
    planner_output: PlannerOutput,
    lead_agent: Agent | None,
    expansion_run: PlannerExpansionRun,
    created_titles: list[str],
) -> None:
    if lead_agent is None or not lead_agent.openclaw_session_id:
        return
    board = await Board.objects.by_id(planner_output.board_id).first(session)
    if board is None:
        return
    created_lines = "\n".join(f"- {title}" for title in created_titles) or "- None"
    source_epics = ", ".join(expansion_run.source_epic_ids) or "n/a"
    message = (
        "Planner expanded the next execution batch.\n\n"
        f"Board: {board.name}\n"
        f"Planner output: {planner_output.id}\n"
        f"Expansion round: {expansion_run.round_number}\n"
        f"Trigger: {expansion_run.trigger}\n"
        f"Epics: {source_epics}\n\n"
        "New tasks:\n"
        f"{created_lines}\n\n"
        "Use this delta together with the approved planner package. Do not re-plan the full scope."
    )
    try:
        from app.services.openclaw.gateway_dispatch import GatewayDispatchService

        await GatewayDispatchService(session).send_to_agent(
            agent=lead_agent,
            message=message,
            deliver=True,
        )
    except Exception:
        logger.warning(
            "Failed to notify lead after planner expansion",
            extra={
                "planner_output_id": str(planner_output.id),
                "expansion_run_id": str(expansion_run.id),
            },
        )


async def _run_planner_expansion(
    *,
    planner_output_id: UUID,
    expansion_run_id: UUID,
    max_new_tasks: int | None,
) -> None:
    async with async_session_maker() as session:
        planner_output = await PlannerOutput.objects.by_id(planner_output_id).first(session)
        expansion_run = await PlannerExpansionRun.objects.by_id(expansion_run_id).first(session)
        if planner_output is None or expansion_run is None:
            return
        board = await Board.objects.by_id(planner_output.board_id).first(session)
        if board is None:
            expansion_run.status = "failed"
            expansion_run.error_message = f"Board {planner_output.board_id} not found"
            expansion_run.updated_at = utcnow()
            session.add(expansion_run)
            await session.commit()
            return

        await _backfill_existing_planner_package_state(
            session,
            planner_output=planner_output,
        )

        role_agents, lead_agent = await _resolve_board_agents_for_planner(
            session,
            board_id=planner_output.board_id,
        )
        policy = _normalize_expansion_policy(
            planner_output.expansion_policy,
            online_assignable_agents=_count_assignable_planner_agents(role_agents, lead_agent),
            initial_task_budget=int(
                (planner_output.expansion_policy or {}).get("initial_task_budget")
                or len(planner_output.tasks)
                or 8
            ),
        )
        planner_output.expansion_policy = policy
        task_snapshots = await _load_materialized_task_snapshots(
            session,
            board_id=planner_output.board_id,
            planner_output_id=planner_output.id,
        )
        planner_output.epic_states = _sync_epic_states_with_materialized_tasks(
            planner_output,
            materialized_tasks=task_snapshots,
        )
        max_total_tasks = max_new_tasks or int(policy.get("max_new_tasks_per_round") or 1)
        per_epic_limit = min(
            int(policy.get("max_new_tasks_per_epic") or 1),
            max_total_tasks,
        )
        epic_map = {str(epic.get("id") or ""): epic for epic in planner_output.epics}
        selected_states = _pick_epics_for_expansion(
            planner_output=planner_output,
            max_active_epics=int(policy.get("max_active_epics") or DEFAULT_MAX_ACTIVE_EPICS),
        )
        expansion_run.source_epic_ids = [
            str(state.get("epic_id") or "")
            for state in selected_states
            if state.get("epic_id")
        ]
        if not selected_states:
            expansion_run.status = "skipped"
            expansion_run.summary = "No eligible epics remained for expansion."
            expansion_run.updated_at = utcnow()
            session.add(expansion_run)
            await session.commit()
            return

        candidate_tasks: list[dict[str, Any]] = []
        state_updates: list[dict[str, Any]] = []
        scope_suggestions: list[str] = []
        for state in selected_states:
            epic_id = str(state.get("epic_id") or "")
            epic = epic_map.get(epic_id)
            if epic is None:
                continue
            existing_epic_tasks = [
                task for task in task_snapshots if str(task.get("planner_epic_id") or task.get("epic_id") or "") == epic_id
            ]
            response_text = await _call_llm_via_gateway(
                session=session,
                board=board,
                system_prompt=PLANNER_EXPANSION_SYSTEM_PROMPT,
                user_prompt=(
                    f"Materialize the next batch for epic '{epic.get('title', 'Untitled Epic')}'.\n\n"
                    f"Epic description: {epic.get('description', '')}\n"
                    f"Current epic status: {state.get('status', 'planned')}\n"
                    f"Remaining work summary: {state.get('remaining_work_summary') or 'Not recorded yet.'}\n"
                    f"Open acceptance items: {json.dumps(list(state.get('open_acceptance_items') or []))}\n"
                    f"Task budget: up to {per_epic_limit} tasks.\n\n"
                    "--- EXISTING MATERIALIZED TASKS ---\n\n"
                    f"{_compact_existing_epic_tasks(existing_epic_tasks)}\n\n"
                    "--- DOSSIER ---\n\n"
                    f"{_document_context_for_prompt(planner_output.documents or [])}"
                ),
                preferred_role="lead",
                role_agents=role_agents,
                lead_agent=lead_agent,
            )
            parsed = _extract_json_from_response(response_text)
            if not parsed:
                raise ValueError(f"Failed to parse expansion response for epic {epic_id}")
            scope_suggestions.extend(
                [
                    str(item).strip()
                    for item in parsed.get("scope_suggestions", [])
                    if isinstance(item, str) and str(item).strip()
                ]
            )
            normalized_tasks = _normalize_expansion_tasks(
                epic,
                parsed,
                round_number=expansion_run.round_number,
            )
            deduped = _dedupe_expansion_tasks(
                candidate_tasks=normalized_tasks,
                existing_tasks=task_snapshots + candidate_tasks,
                max_new_tasks=max_total_tasks - len(candidate_tasks),
            )
            candidate_tasks.extend(deduped)
            state_updates.append(
                _build_epic_state(
                    epic=epic,
                    payload=parsed,
                    materialized_tasks=int(state.get("materialized_tasks") or 0) + len(deduped),
                    done_tasks=int(state.get("done_tasks") or 0),
                )
            )
            if len(candidate_tasks) >= max_total_tasks:
                break

        if candidate_tasks:
            try:
                dependency_response = await _call_llm_via_gateway(
                    session=session,
                    board=board,
                    system_prompt=PLANNER_DEPENDENCY_SYSTEM_PROMPT,
                    user_prompt=(
                        "Normalize the task dependencies for this next-batch task list.\n\n"
                        f"--- TASK OUTLINE ---\n\n{_compact_task_outline(candidate_tasks)}"
                    ),
                    preferred_role="lead",
                    role_agents=role_agents,
                    lead_agent=lead_agent,
                )
                parsed = _extract_json_from_response(dependency_response)
                if parsed:
                    normalized = _normalize_dependency_patch(candidate_tasks, parsed)
                    if validate_dag(normalized) is None:
                        candidate_tasks = normalized
            except Exception:
                pass

        if not candidate_tasks:
            expansion_run.status = "skipped"
            expansion_run.summary = (
                "No new in-scope tasks were materialized."
                + (f" Suggestions: {'; '.join(scope_suggestions[:3])}" if scope_suggestions else "")
            )
            expansion_run.updated_at = utcnow()
            planner_output.epic_states = _merge_epic_state_updates(
                current_states=planner_output.epic_states or [],
                updated_states=state_updates,
            )
            session.add(planner_output)
            session.add(expansion_run)
            await session.commit()
            return

        created_ids = await _create_board_tasks_from_planner_tasks(
            session,
            planner_output=planner_output,
            board=board,
            tasks=candidate_tasks,
            role_agents=role_agents,
            lead_agent=lead_agent,
            materialized_from="expansion",
            expansion_round=expansion_run.round_number,
        )
        task_snapshots = await _load_materialized_task_snapshots(
            session,
            board_id=planner_output.board_id,
            planner_output_id=planner_output.id,
        )
        planner_output.epic_states = _merge_epic_state_updates(
            current_states=planner_output.epic_states or [],
            updated_states=state_updates,
        )
        planner_output.epic_states = _sync_epic_states_with_materialized_tasks(
            planner_output,
            materialized_tasks=task_snapshots,
        )
        planner_output.materialized_task_count = len(task_snapshots)
        planner_output.remaining_scope_count = _estimate_remaining_scope_count(
            planner_output.epic_states,
        )
        planner_output.latest_expansion_at = utcnow()
        expansion_run.status = "succeeded"
        expansion_run.created_task_ids = [str(task_id) for task_id in created_ids]
        expansion_run.summary = (
            f"Created {len(created_ids)} tasks across "
            f"{len(expansion_run.source_epic_ids)} epic(s)."
            + (f" Suggestions: {'; '.join(scope_suggestions[:3])}" if scope_suggestions else "")
        )
        expansion_run.updated_at = utcnow()
        session.add(planner_output)
        session.add(expansion_run)
        await session.commit()
        await _notify_lead_of_expansion(
            session,
            planner_output=planner_output,
            lead_agent=lead_agent,
            expansion_run=expansion_run,
            created_titles=[task.get("title", "Untitled") for task in candidate_tasks],
        )


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


def _select_planning_agent(
    *,
    preferred_role: str,
    role_agents: dict[str, list[Agent]],
    lead_agent: Agent,
) -> Agent:
    normalized = _normalize_role_name(preferred_role)
    if normalized in (None, "lead"):
        return lead_agent
    candidates = role_agents.get(PLANNER_ROLE_TO_AGENT_ROLE.get(normalized, ""), [])
    if candidates:
        return candidates[0]
    return lead_agent


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
