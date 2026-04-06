"""OpenCode CLI runtime adapter for local agent execution."""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.config import BACKEND_ROOT
from app.services.runtime_adapters.base import RunResult, RuntimeAdapter, RuntimeAdapterError

EVIDENCE_DIR = BACKEND_ROOT / "storage" / "evidence"
KNOWN_MODEL_VARIANTS = frozenset({"low", "medium", "high"})


class OpenCodeCLIAdapter(RuntimeAdapter):
    """Execute agent runs via OpenCode CLI (`opencode run`).

    Runs OpenCode in non-interactive mode with `--format json` for
    machine-readable event streams.
    """

    def __init__(self, workdir: str | None = None) -> None:
        self._workdir = workdir
        self._active_processes: dict[str, asyncio.subprocess.Process] = {}
        self._active_runs: dict[str, dict[str, Any]] = {}

    @property
    def runtime_name(self) -> str:
        return "opencode_cli"

    async def spawn(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float | None = None,
        permissions_profile: str | None = None,
        agent: str = "build",
        **kwargs: Any,
    ) -> RunResult:
        run_id = str(uuid4())
        evidence_dir = EVIDENCE_DIR / run_id
        evidence_dir.mkdir(parents=True, exist_ok=True)
        normalized_model, variant = self._normalize_model_and_variant(model)

        cmd = [
            "opencode", "run",
            "--agent", agent,
            "--format", "json",
        ]
        if normalized_model:
            cmd.extend(["--model", normalized_model])
        if variant:
            cmd.extend(["--variant", variant])

        self._active_runs[run_id] = {
            "started_at": time.time(),
            "model": normalized_model,
            "variant": variant,
            "status": "running",
            "agent": agent,
        }

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._workdir,
                env={**os.environ, "OPENCODE_TEMPERATURE": str(temperature)} if temperature else None,
            )
            self._active_processes[run_id] = proc

            stdout_data, stderr_data = await proc.communicate(input=prompt.encode())

            events = self._parse_json_events(stdout_data)
            error_output = stderr_data.decode("utf-8", errors="replace") if stderr_data else ""
            event_error = self._extract_error(events)

            evidence = self._save_evidence(
                run_id, evidence_dir, prompt, events, error_output,
            )

            if proc.returncode == 0 and event_error is None:
                self._active_runs[run_id]["status"] = "succeeded"
                output = self._extract_output(events)
                return RunResult(
                    success=True,
                    output=output,
                    evidence_paths=evidence,
                    metadata={
                        "model": normalized_model,
                        "variant": variant,
                        "agent": agent,
                        "run_id": run_id,
                        "events": len(events),
                    },
                )

            self._active_runs[run_id]["status"] = "failed"
            output = self._extract_output(events)
            if event_error:
                return RunResult(
                    success=False,
                    output=output,
                    error=event_error,
                    evidence_paths=evidence,
                    metadata={
                        "model": normalized_model,
                        "variant": variant,
                        "agent": agent,
                        "run_id": run_id,
                        "events": len(events),
                    },
                )
            return RunResult(
                success=False,
                output=output,
                error=f"OpenCode CLI exited with code {proc.returncode}: {error_output}",
                evidence_paths=evidence,
                metadata={
                    "model": normalized_model,
                    "variant": variant,
                    "agent": agent,
                    "run_id": run_id,
                    "events": len(events),
                },
            )

        except FileNotFoundError:
            raise RuntimeAdapterError(
                "opencode CLI not found. Install OpenCode or use ACP runtime instead."
            )
        except Exception as exc:
            self._active_runs[run_id]["status"] = "failed"
            raise RuntimeAdapterError(f"OpenCode CLI run failed: {exc}") from exc

    async def cancel(self, run_id: str) -> bool:
        proc = self._active_processes.get(run_id)
        if proc and proc.returncode is None:
            try:
                proc.kill()
                await proc.wait()
                self._active_runs[run_id]["status"] = "canceled"
                return True
            except Exception:
                return False
        return False

    async def status(self, run_id: str) -> str:
        run_info = self._active_runs.get(run_id)
        if not run_info:
            return "unknown"
        proc = self._active_processes.get(run_id)
        if proc and proc.returncode is None:
            return "running"
        return run_info.get("status", "unknown")

    def _parse_json_events(self, stdout_data: bytes) -> list[dict]:
        """Parse newline-delimited JSON events from OpenCode stdout."""
        events = []
        for line in stdout_data.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                events.append(event)
            except json.JSONDecodeError:
                events.append({"type": "raw", "content": line})
        return events

    def _save_evidence(
        self,
        run_id: str,
        evidence_dir: Path,
        prompt: str,
        events: list[dict],
        error_output: str,
    ) -> list[dict]:
        """Save run evidence to disk and return evidence paths."""
        evidence = []

        prompt_path = evidence_dir / "prompt.txt"
        prompt_path.write_text(prompt)
        evidence.append({
            "type": "prompt",
            "path": str(prompt_path.relative_to(EVIDENCE_DIR.parent)),
            "size_bytes": len(prompt),
        })

        events_path = evidence_dir / "events.jsonl"
        events_path.write_text(
            "\n".join(json.dumps(e) for e in events)
        )
        evidence.append({
            "type": "events",
            "path": str(events_path.relative_to(EVIDENCE_DIR.parent)),
            "size_bytes": events_path.stat().st_size,
        })

        if error_output:
            error_path = evidence_dir / "stderr.txt"
            error_path.write_text(error_output)
            evidence.append({
                "type": "error",
                "path": str(error_path.relative_to(EVIDENCE_DIR.parent)),
                "size_bytes": len(error_output),
            })

        file_edits = [e for e in events if e.get("type") == "file_edit"]
        if file_edits:
            diff_path = evidence_dir / "diffs.json"
            diff_path.write_text(json.dumps(file_edits, indent=2))
            evidence.append({
                "type": "diff",
                "path": str(diff_path.relative_to(EVIDENCE_DIR.parent)),
                "size_bytes": diff_path.stat().st_size,
            })

        return evidence

    def _extract_output(self, events: list[dict]) -> str:
        """Extract the final output from OpenCode events."""
        for event in reversed(events):
            if event.get("type") in ("response", "message", "output"):
                content = event.get("content", "")
                if content:
                    return content
        return json.dumps(events[-1]) if events else ""

    def _extract_error(self, events: list[dict]) -> str | None:
        """Extract a terminal error message from OpenCode events."""
        for event in reversed(events):
            if event.get("type") != "error":
                continue
            error = event.get("error")
            if isinstance(error, dict):
                data = error.get("data")
                if isinstance(data, dict) and isinstance(data.get("message"), str) and data["message"].strip():
                    return data["message"].strip()
                if isinstance(error.get("message"), str) and error["message"].strip():
                    return error["message"].strip()
            if isinstance(event.get("content"), str) and event["content"].strip():
                return event["content"].strip()
            return json.dumps(event)
        return None

    def _normalize_model_and_variant(self, model: str | None) -> tuple[str | None, str | None]:
        """Split legacy `provider/model/variant` strings into model + variant flags."""
        if not model:
            return None, None
        base_model, _, suffix = model.rpartition("/")
        if base_model and suffix in KNOWN_MODEL_VARIANTS and "/" in base_model:
            return base_model, suffix
        return model, None
