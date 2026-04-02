"""Mission Control API client for the Telegram bot."""

from __future__ import annotations

from typing import Any

import httpx

from bot.config import settings


class MissionControlClient:
    """Async HTTP client for the Mission Control backend API."""

    def __init__(self) -> None:
        self._base = settings.api_base_url.rstrip("/")
        self._headers = settings.api_headers

    async def _get(self, path: str, params: dict | None = None) -> Any:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._base}{path}",
                headers=self._headers,
                params=params,
                timeout=30.0,
            )
            resp.raise_for_status()
            return resp.json()

    async def _patch(self, path: str, json: dict | None = None) -> Any:
        async with httpx.AsyncClient() as client:
            resp = await client.patch(
                f"{self._base}{path}",
                headers=self._headers,
                json=json,
                timeout=60.0,
            )
            resp.raise_for_status()
            return resp.json()

    async def _post(self, path: str, json: dict | None = None, params: dict | None = None) -> Any:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._base}{path}",
                headers=self._headers,
                json=json,
                params=params,
                timeout=60.0,
            )
            resp.raise_for_status()
            return resp.json()

    async def _delete(self, path: str) -> Any:
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{self._base}{path}",
                headers=self._headers,
                timeout=30.0,
            )
            resp.raise_for_status()
            return resp.json()

    # -- Boards --

    async def list_boards(self) -> list[dict]:
        data = await self._get("/api/v1/boards")
        return data.get("items", [])

    async def panic_board(self, board_id: str, reason: str | None = None) -> dict:
        params = {"reason": reason} if reason else None
        return await self._post(f"/api/v1/boards/{board_id}/panic", params=params)

    async def resume_board(self, board_id: str) -> dict:
        return await self._post(f"/api/v1/boards/{board_id}/resume")

    # -- Tasks --

    async def list_tasks(self, board_id: str, params: dict | None = None) -> list[dict]:
        data = await self._get(f"/api/v1/boards/{board_id}/tasks", params=params or {})
        return data.get("items", [])

    async def get_task(self, board_id: str, task_id: str) -> dict:
        return await self._get(f"/api/v1/boards/{board_id}/tasks/{task_id}")

    async def update_task_status(self, board_id: str, task_id: str, status: str) -> dict:
        return await self._patch(
            f"/api/v1/boards/{board_id}/tasks/{task_id}",
            json={"status": status},
        )

    # -- Runs --

    async def list_runs(self, task_id: str) -> list[dict]:
        data = await self._get(f"/api/v1/runs/by-task/{task_id}")
        return data.get("items", [])

    async def list_runs_for_notifications(self, status: str | None = None, since: str | None = None) -> list[dict]:
        params: dict = {}
        if status:
            params["status"] = status
        if since:
            params["since"] = since
        data = await self._get("/api/v1/runs", params=params)
        return data.get("items", [])

    async def list_failed_build_runs(self, since: str | None = None) -> list[dict]:
        params: dict = {"status": "failed", "stage": "build"}
        if since:
            params["since"] = since
        data = await self._get("/api/v1/runs", params=params)
        return data.get("items", [])

    # -- Pipeline --

    async def validate_pipeline(self, task_id: str, stage: str) -> dict:
        return await self._get(
            f"/api/v1/pipeline/tasks/{task_id}/validate",
            params={"stage": stage},
        )

    async def execute_stage(self, task_id: str, stage: str) -> dict:
        return await self._post(
            f"/api/v1/pipeline/tasks/{task_id}/execute",
            params={"stage": stage},
        )

    # -- Approvals --

    async def list_approvals(self, board_id: str | None = None, since: str | None = None) -> list[dict]:
        if not board_id:
            return []
        params: dict = {"status": "pending"}
        if since:
            params["since"] = since
        data = await self._get(f"/api/v1/boards/{board_id}/approvals", params=params)
        return data.get("items", [])

    async def resolve_approval(self, board_id: str, approval_id: str, decision: str) -> dict:
        return await self._patch(
            f"/api/v1/boards/{board_id}/approvals/{approval_id}",
            json={"status": decision},
        )

    # -- Artifacts --

    async def list_artifacts(self, board_id: str | None = None) -> list[dict]:
        params = {}
        if board_id:
            params["board_id"] = board_id
        data = await self._get("/api/v1/artifacts", params=params)
        return data.get("items", [])

    async def list_unblocked_tasks(self, since: str | None = None) -> list[dict]:
        boards = await self.list_boards()
        tasks: list[dict] = []
        for board in boards:
            params: dict = {}
            if since:
                params["since"] = since
            board_tasks = await self.list_tasks(board["id"], params=params)
            tasks.extend(task for task in board_tasks if not task.get("is_blocked"))
        return tasks

    # -- Planner --

    async def generate_backlog(self, artifact_id: str, board_id: str) -> dict:
        return await self._post(
            "/api/v1/planner/generate",
            json={"artifact_id": artifact_id},
        )

    # -- Agents --

    async def list_agents(self) -> list[dict]:
        data = await self._get("/api/v1/agents")
        return data.get("items", [])

    async def wake_agent(self, agent_id: str) -> dict:
        return await self._post(f"/api/v1/watchdog/agents/{agent_id}/wake")

    async def get_escalations(self) -> dict:
        return await self._get("/api/v1/watchdog/escalations")

    # -- QA --

    async def run_tests(self, task_id: str, browsers: str | None = None) -> dict:
        params = {"task_id": task_id}
        if browsers:
            params["browsers"] = browsers
        return await self._post("/api/v1/qa/test", params=params)


api = MissionControlClient()
