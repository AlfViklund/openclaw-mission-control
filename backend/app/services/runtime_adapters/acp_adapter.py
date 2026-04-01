"""ACP runtime adapter using OpenClaw Gateway WebSocket RPC."""

from __future__ import annotations

import hashlib
import time
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from app.services.runtime_adapters.base import RunResult, RuntimeAdapter, RuntimeAdapterError

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.services.openclaw.gateway_dispatch import GatewayDispatchService
    from app.services.openclaw.gateway_rpc import GatewayConfig


class ACPAdapter(RuntimeAdapter):
    """Execute agent runs via OpenClaw Gateway ACP sessions.

    Uses the existing GatewayDispatchService to send messages to agent
    sessions and retrieve responses through chat history.
    """

    def __init__(
        self,
        session: AsyncSession,
        dispatch: GatewayDispatchService,
        gateway_config: GatewayConfig,
        session_key: str,
        agent_name: str,
    ) -> None:
        self._session = session
        self._dispatch = dispatch
        self._gateway_config = gateway_config
        self._session_key = session_key
        self._agent_name = agent_name
        self._active_runs: dict[str, dict[str, Any]] = {}

    @property
    def runtime_name(self) -> str:
        return "acp"

    async def spawn(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float | None = None,
        permissions_profile: str | None = None,
        **kwargs: Any,
    ) -> RunResult:
        run_id = str(uuid4())
        self._active_runs[run_id] = {
            "started_at": time.time(),
            "model": model,
            "status": "running",
        }

        try:
            await self._dispatch.send_agent_message(
                session_key=self._session_key,
                config=self._gateway_config,
                agent_name=self._agent_name,
                message=prompt,
                deliver=True,
            )

            response_text = await self._wait_for_response()

            evidence = self._build_evidence(prompt, response_text, model)

            self._active_runs[run_id]["status"] = "succeeded"
            self._active_runs[run_id]["finished_at"] = time.time()

            return RunResult(
                success=True,
                output=response_text,
                evidence_paths=evidence,
                metadata={"model": model, "run_id": run_id},
            )

        except Exception as exc:
            self._active_runs[run_id]["status"] = "failed"
            self._active_runs[run_id]["error"] = str(exc)
            raise RuntimeAdapterError(f"ACP run failed: {exc}") from exc

    async def cancel(self, run_id: str) -> bool:
        if run_id not in self._active_runs:
            return False
        try:
            from app.services.openclaw.gateway_rpc import openclaw_call
            await openclaw_call(
                "chat.abort",
                {"session_key": self._session_key},
                config=self._gateway_config,
            )
            self._active_runs[run_id]["status"] = "canceled"
            return True
        except Exception:
            return False

    async def status(self, run_id: str) -> str:
        run_info = self._active_runs.get(run_id)
        if not run_info:
            return "unknown"
        return run_info.get("status", "unknown")

    async def _wait_for_response(self, timeout: int = 300) -> str:
        """Wait for the agent to respond by polling chat history."""
        from app.services.openclaw.gateway_rpc import openclaw_call

        start = time.time()
        last_count = 0

        while time.time() - start < timeout:
            try:
                history = await openclaw_call(
                    "chat.history",
                    {"session_key": self._session_key, "limit": 20},
                    config=self._gateway_config,
                )
                messages = history.get("messages", []) if isinstance(history, dict) else []
                if len(messages) > last_count:
                    last_msg = messages[-1]
                    if isinstance(last_msg, dict):
                        content = last_msg.get("content", "")
                        role = last_msg.get("role", "")
                        if role in ("assistant", "agent", "model"):
                            return content
                    last_count = len(messages)
            except Exception:
                pass
            import asyncio
            await asyncio.sleep(2)

        raise RuntimeAdapterError("Timeout waiting for agent response")

    def _build_evidence(
        self,
        prompt: str,
        response: str,
        model: str | None,
    ) -> list[dict]:
        """Build evidence records from the run."""
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()[:16]
        return [
            {
                "type": "prompt",
                "path": f"evidence/acp/{prompt_hash}_prompt.txt",
                "size_bytes": len(prompt),
            },
            {
                "type": "response",
                "path": f"evidence/acp/{prompt_hash}_response.txt",
                "size_bytes": len(response),
            },
        ]
