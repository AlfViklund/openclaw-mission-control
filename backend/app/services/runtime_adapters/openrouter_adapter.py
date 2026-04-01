"""OpenRouter API runtime adapter (stub/feature-flagged)."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.services.runtime_adapters.base import RunResult, RuntimeAdapter, RuntimeAdapterError

EVIDENCE_DIR = Path(__file__).resolve().parents[4] / "storage" / "evidence"


class OpenRouterAdapter(RuntimeAdapter):
    """Execute agent runs via OpenRouter unified API.

    Feature-flagged: requires ENABLE_OPENROUTER=true in settings.
    Uses BYOK (Bring Your Own Key) pattern for provider routing.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or getattr(settings, "openrouter_api_key", "")
        self._enabled = bool(getattr(settings, "enable_openrouter", False))
        self._active_runs: dict[str, dict[str, Any]] = {}

    @property
    def runtime_name(self) -> str:
        return "openrouter"

    async def spawn(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float | None = None,
        permissions_profile: str | None = None,
        **kwargs: Any,
    ) -> RunResult:
        if not self._enabled:
            raise RuntimeAdapterError(
                "OpenRouter adapter is disabled. Set ENABLE_OPENROUTER=true to enable."
            )
        if not self._api_key:
            raise RuntimeAdapterError(
                "OpenRouter API key not configured. Set OPENROUTER_API_KEY."
            )

        run_id = str(uuid4())
        self._active_runs[run_id] = {
            "started_at": time.time(),
            "model": model or "anthropic/claude-sonnet-4-20260325",
            "status": "running",
        }

        try:
            import httpx

            model_name = model or "anthropic/claude-sonnet-4-20260325"
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://clawdev.local",
                        "X-Title": "ClawDev Mission Control",
                    },
                    json={
                        "model": model_name,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": temperature or 0.7,
                    },
                    timeout=120.0,
                )
                response.raise_for_status()
                data = response.json()

            content = ""
            if "choices" in data and data["choices"]:
                content = data["choices"][0].get("message", {}).get("content", "")

            evidence = self._build_evidence(run_id, prompt, content, model_name)

            self._active_runs[run_id]["status"] = "succeeded"
            self._active_runs[run_id]["finished_at"] = time.time()

            return RunResult(
                success=True,
                output=content,
                evidence_paths=evidence,
                metadata={
                    "model": model_name,
                    "run_id": run_id,
                    "usage": data.get("usage", {}),
                },
            )

        except Exception as exc:
            self._active_runs[run_id]["status"] = "failed"
            raise RuntimeAdapterError(f"OpenRouter API call failed: {exc}") from exc

    async def cancel(self, run_id: str) -> bool:
        if run_id in self._active_runs:
            self._active_runs[run_id]["status"] = "canceled"
            return True
        return False

    async def status(self, run_id: str) -> str:
        run_info = self._active_runs.get(run_id)
        if not run_info:
            return "unknown"
        return run_info.get("status", "unknown")

    def _build_evidence(
        self,
        run_id: str,
        prompt: str,
        response: str,
        model: str,
    ) -> list[dict]:
        evidence_dir = EVIDENCE_DIR / "openrouter" / run_id
        evidence_dir.mkdir(parents=True, exist_ok=True)

        prompt_path = evidence_dir / "prompt.txt"
        prompt_path.write_text(prompt)
        response_path = evidence_dir / "response.txt"
        response_path.write_text(response)

        return [
            {
                "type": "prompt",
                "path": str(prompt_path.relative_to(EVIDENCE_DIR.parent)),
                "size_bytes": len(prompt),
            },
            {
                "type": "response",
                "path": str(response_path.relative_to(EVIDENCE_DIR.parent)),
                "size_bytes": len(response),
            },
        ]
