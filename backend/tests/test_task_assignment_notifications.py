from __future__ import annotations

from uuid import uuid4

from app.api import tasks as tasks_api
from app.core.config import settings
from app.models.agents import Agent
from app.models.boards import Board
from app.models.tasks import Task


def test_assignment_notification_message_uses_agent_safe_task_endpoints() -> None:
    board = Board(
        id=uuid4(),
        organization_id=uuid4(),
        gateway_id=uuid4(),
        name="CardFlow",
        slug="cardflow",
    )
    task = Task(
        id=uuid4(),
        board_id=board.id,
        title="Publish compliance runbook",
        status="inbox",
        description="Document rollout controls",
    )
    agent = Agent(
        id=uuid4(),
        board_id=board.id,
        gateway_id=board.gateway_id,
        name="Technical Writer",
    )

    message = tasks_api._assignment_notification_message(
        board=board,
        task=task,
        agent=agent,
    )

    task_path = f"{settings.base_url}/api/v1/agent/boards/{board.id}/tasks/{task.id}"
    assert f"GET {task_path}" in message
    assert f"GET {settings.base_url}/api/v1/pipeline/tasks/{task.id}/summary" in message
    assert f"POST {settings.base_url}/api/v1/pipeline/tasks/{task.id}/start-work" in message
    assert f"POST {settings.base_url}/api/v1/pipeline/tasks/{task.id}/execute-next" in message
    assert f"POST {task_path}/comments" in message
    assert "kind=completion_report" in message
    assert "Do not use /api/v1/boards/{board_id}/tasks/{task_id}" in message
