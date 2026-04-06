from __future__ import annotations

import json

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
