# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Provider usage is cumulative; unreported fields must remain unknown."""

import json

from examples.univtac.raw_depth_baseline import summarize


def test_summary_uses_final_cumulative_usage_and_official_success(tmp_path):
    events = [
        {
            "kind": "sdk_event",
            "payload": {
                "method": "thread/tokenUsage/updated",
                "payload": {
                    "token_usage": {"total": {"input_tokens": n, "output_tokens": 20}}
                },
            },
        }
        for n in (100, 250)
    ]
    events.append(
        {"kind": "tool_response", "payload": {"name": "move_eef", "elapsed_s": 1.25}}
    )
    (tmp_path / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    result = summarize(
        {
            "id": "test",
            "path": str(tmp_path),
            "outcome": {
                "environment_success": False,
                "finish": {"status": "success"},
                "stats": {"total_reasoning_output_tokens": 0},
            },
        }
    )
    assert result["official_success"] is False
    assert result["input_tokens"] == 250
    assert result["reasoning_output_tokens"] is None
    assert result["tool_execution_s"] == 1.25


def test_summary_keeps_missing_usage_unknown(tmp_path):
    (tmp_path / "events.jsonl").write_text("")
    result = summarize({"id": "test", "path": str(tmp_path), "outcome": {}})
    assert result["input_tokens"] is None
    assert result["official_success"] is None
