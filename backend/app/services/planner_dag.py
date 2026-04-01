"""Dependency graph validation for planner outputs.

Detects cycles, self-dependencies, and computes parallelism groups
via topological sorting.
"""

from __future__ import annotations

from collections import defaultdict, deque


class DagValidationError(Exception):
    """Raised when the dependency graph is invalid."""


def validate_dag(tasks: list[dict]) -> list[str] | None:
    """Validate task dependency graph and return error message or None.

    Checks:
    - No self-dependencies
    - No circular dependencies
    - All depends_on references exist within the task list

    Returns:
        Error message string if invalid, None if valid.
    """
    task_ids = {t["id"] for t in tasks}

    for task in tasks:
        task_id = task["id"]
        deps = task.get("depends_on", [])

        for dep_id in deps:
            if dep_id == task_id:
                return f"Task '{task_id}' depends on itself"
            if dep_id not in task_ids:
                return f"Task '{task_id}' depends on unknown task '{dep_id}'"

    cycle = _find_cycle(tasks)
    if cycle:
        return f"Circular dependency detected: {' -> '.join(cycle)}"

    return None


def _find_cycle(tasks: list[dict]) -> list[str] | None:
    """Find a cycle in the dependency graph using DFS.

    Returns:
        List of task IDs forming the cycle, or None if no cycle exists.
    """
    adj: dict[str, list[str]] = defaultdict(list)
    for task in tasks:
        for dep in task.get("depends_on", []):
            adj[dep].append(task["id"])

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {t["id"]: WHITE for t in tasks}
    parent: dict[str, str | None] = {t["id"]: None for t in tasks}

    def dfs(node: str) -> list[str] | None:
        color[node] = GRAY
        for neighbor in adj.get(node, []):
            if color[neighbor] == GRAY:
                cycle = [neighbor, node]
                current = node
                while current != neighbor:
                    current = parent[current]  # type: ignore[assignment]
                    if current is None:
                        break
                    cycle.append(current)
                cycle.reverse()
                return cycle
            if color[neighbor] == WHITE:
                parent[neighbor] = node
                result = dfs(neighbor)
                if result:
                    return result
        color[node] = BLACK
        return None

    for task in tasks:
        if color[task["id"]] == WHITE:
            result = dfs(task["id"])
            if result:
                return result

    return None


def compute_parallelism_groups(tasks: list[dict]) -> list[dict]:
    """Compute which tasks can run in parallel based on dependencies.

    Uses Kahn's algorithm for topological sort to assign levels.
    Tasks at the same level have no dependencies on each other and
    can be executed simultaneously.

    Returns:
        List of dicts with 'level' (int) and 'task_ids' (list[str]).
    """
    if not tasks:
        return []

    task_ids = {t["id"] for t in tasks}
    in_degree: dict[str, int] = {t["id"]: 0 for t in tasks}
    adj: dict[str, list[str]] = defaultdict(list)

    for task in tasks:
        for dep in task.get("depends_on", []):
            if dep in task_ids:
                adj[dep].append(task["id"])
                in_degree[task["id"]] += 1

    queue: deque[str] = deque(
        tid for tid, deg in in_degree.items() if deg == 0
    )

    levels: list[dict] = []
    while queue:
        level_size = len(queue)
        level_task_ids: list[str] = []
        for _ in range(level_size):
            node = queue.popleft()
            level_task_ids.append(node)
            for neighbor in adj[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        levels.append({
            "level": len(levels),
            "task_ids": level_task_ids,
        })

    return levels
