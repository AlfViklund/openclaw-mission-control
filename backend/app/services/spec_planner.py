"""Deterministic spec-to-DAG planner helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.spec_artifacts import SpecArtifact
from app.models.tasks import Task
from app.schemas.spec_artifacts import PlannerDraftNodeRead, PlannerDraftRead
from app.services.task_dependencies import replace_task_dependencies

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
BULLET_RE = re.compile(r"^(\s*)(?:[-*+]|\d+\.)\s+(?:\[(?: |x|X)\]\s+)?(.*\S)\s*$")
CODE_FENCE_RE = re.compile(r"^(```|~~~)")


@dataclass(frozen=True, slots=True)
class _DraftNode:
    key: str
    title: str
    depth: int
    source_line: int
    parent_key: str | None

    @property
    def depends_on_keys(self) -> tuple[str, ...]:
        return (self.parent_key,) if self.parent_key else ()


def _outline_nodes(body: str) -> list[_DraftNode]:
    nodes: list[_DraftNode] = []
    stack: list[_DraftNode] = []
    current_section_depth = 0
    in_code_block = False

    for line_number, raw_line in enumerate(body.splitlines(), start=1):
        line = raw_line.rstrip()
        if CODE_FENCE_RE.match(line.lstrip()):
            in_code_block = not in_code_block
            continue
        if in_code_block or not line.strip():
            continue

        heading_match = HEADING_RE.match(line)
        bullet_match = BULLET_RE.match(line)
        title: str | None = None
        depth: int | None = None

        if heading_match:
            heading_level = len(heading_match.group(1))
            current_section_depth = heading_level * 10
            title = heading_match.group(2).strip()
            depth = current_section_depth
        elif bullet_match:
            indent = len(bullet_match.group(1))
            title = bullet_match.group(2).strip()
            depth = current_section_depth + 1 + indent // 2
        else:
            continue

        while stack and stack[-1].depth >= depth:
            stack.pop()
        parent_key = stack[-1].key if stack else None
        node = _DraftNode(
            key=f"node-{len(nodes) + 1}",
            title=title,
            depth=depth,
            source_line=line_number,
            parent_key=parent_key,
        )
        nodes.append(node)
        stack.append(node)

    return nodes


def build_planner_draft(spec_artifact: SpecArtifact) -> PlannerDraftRead:
    """Convert a spec artifact body into a stable DAG draft."""

    nodes = [
        PlannerDraftNodeRead(
            key=node.key,
            title=node.title,
            depth=node.depth,
            source_line=node.source_line,
            parent_key=node.parent_key,
            depends_on_keys=list(node.depends_on_keys),
        )
        for node in _outline_nodes(spec_artifact.body)
    ]
    return PlannerDraftRead(
        spec_artifact_id=spec_artifact.id,
        spec_title=spec_artifact.title,
        node_count=len(nodes),
        nodes=nodes,
    )


async def apply_planner_draft(
    session: AsyncSession,
    *,
    board_id: UUID,
    spec_artifact: SpecArtifact,
    draft: PlannerDraftRead,
) -> list[Task]:
    """Create board tasks from a planner draft and wire parent dependencies."""

    created: list[Task] = []
    key_to_task_id: dict[str, UUID] = {}

    for node in draft.nodes:
        task = Task(
            board_id=board_id,
            title=node.title,
            description=None,
            status="inbox",
            priority="medium",
            auto_created=True,
            auto_reason=f"spec_artifact:{spec_artifact.id}:{node.key}",
        )
        session.add(task)
        await session.flush()
        key_to_task_id[node.key] = task.id
        if node.depends_on_keys:
            dependency_ids = [
                key_to_task_id[key] for key in node.depends_on_keys if key in key_to_task_id
            ]
            if dependency_ids:
                await replace_task_dependencies(
                    session,
                    board_id=board_id,
                    task_id=task.id,
                    depends_on_task_ids=dependency_ids,
                )
        created.append(task)

    return created
