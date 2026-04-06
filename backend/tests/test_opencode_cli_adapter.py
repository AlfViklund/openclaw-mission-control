from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.services.pipeline_runtime_state import extract_retry_after_seconds
from app.services.runtime_adapters.opencode_cli_adapter import OpenCodeCLIAdapter


def test_extract_error_prefers_structured_event_message() -> None:
    adapter = OpenCodeCLIAdapter()
    events = [
        {"type": "message", "content": "working"},
        {
            "type": "error",
            "error": {
                "name": "UnknownError",
                "data": {"message": "Model not found: opencode/qwen3.6-plus-free/high."},
            },
        },
    ]

    assert adapter._extract_error(events) == "Model not found: opencode/qwen3.6-plus-free/high."


def test_extract_output_falls_back_to_last_event_json() -> None:
    adapter = OpenCodeCLIAdapter()
    events = [{"type": "error", "error": {"message": "boom"}}]

    assert adapter._extract_output(events) == json.dumps(events[-1])


def test_normalize_model_and_variant_splits_legacy_reasoning_suffix() -> None:
    adapter = OpenCodeCLIAdapter()

    model, variant = adapter._normalize_model_and_variant("opencode/qwen3.6-plus-free/high")

    assert model == "opencode/qwen3.6-plus-free"
    assert variant == "high"


def test_normalize_model_and_variant_leaves_standard_model_unchanged() -> None:
    adapter = OpenCodeCLIAdapter()

    model, variant = adapter._normalize_model_and_variant("opencode/qwen3.6-plus-free")

    assert model == "opencode/qwen3.6-plus-free"
    assert variant is None


def test_extract_retry_after_seconds_from_provider_error() -> None:
    message = 'Rate limit exceeded. retry-after":"14524"'

    assert extract_retry_after_seconds(message) == 14524


@pytest.mark.asyncio
async def test_spawn_aborts_long_retry_after_and_kills_process(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    log_dir = tmp_path / "log"
    log_dir.mkdir(parents=True)
    log_path = log_dir / "2026-04-06T195754.log"

    class _FakeWriter:
        def __init__(self) -> None:
            self.buffer = bytearray()

        def write(self, data: bytes) -> None:
            self.buffer.extend(data)

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            return None

        async def wait_closed(self) -> None:
            return None

    class _FakeProc:
        def __init__(self) -> None:
            self.stdin = _FakeWriter()
            self.stdout = asyncio.StreamReader()
            self.stdout.feed_eof()
            self.stderr = asyncio.StreamReader()
            self.stderr.feed_eof()
            self.returncode: int | None = None
            self.killed = False
            self._done = asyncio.Event()

        async def wait(self) -> int:
            await self._done.wait()
            return int(self.returncode or 0)

        def kill(self) -> None:
            self.killed = True
            self.returncode = -9
            self._done.set()

    proc = _FakeProc()

    async def _fake_create_subprocess_exec(*_args, **_kwargs):
        log_path.write_text(
            'ERROR ... FreeUsageLimitError ... "message":"Rate limit exceeded. Please try again later." ... retry-after":"14524"',
            encoding="utf-8",
        )
        return proc

    monkeypatch.setattr(
        "app.services.runtime_adapters.opencode_cli_adapter.OPENCODE_LOG_DIR",
        log_dir,
    )
    monkeypatch.setattr(
        "app.services.runtime_adapters.opencode_cli_adapter.asyncio.create_subprocess_exec",
        _fake_create_subprocess_exec,
    )
    monkeypatch.setattr(
        "app.services.runtime_adapters.opencode_cli_adapter.settings.opencode_retry_after_abort_seconds",
        300,
    )

    adapter = OpenCodeCLIAdapter(workdir=str(tmp_path))
    result = await adapter.spawn("Plan the task", agent="plan")

    assert result.success is False
    assert "aborted early" in (result.error or "").lower()
    assert result.metadata["retry_after_seconds"] == 14524
    assert proc.killed is True
