# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Audit the recorded Qwen thinking switch without exposing thought text."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
rows = json.loads((ROOT / "results.json").read_text())
assert len(rows) == 3
checks = []
for row in rows:
    path = Path(row["path"])
    events = [
        json.loads(line) for line in (path / "events.jsonl").read_text().splitlines()
    ]
    requests = [e["payload"] for e in events if e["kind"] == "model_request"]
    responses = [e["payload"] for e in events if e["kind"] == "model_response"]
    assert requests and responses
    assert all(r["model"]["_model_name"] == "qwen3.8-max" for r in requests)
    assert all(
        r["model_settings"]["extra_body"]["enable_thinking"] is True for r in requests
    )
    assert all(r["model_name"] == "qwen3.8-max" for r in responses)
    thinking = [
        part
        for r in responses
        for part in r["parts"]
        if part.get("part_kind") == "thinking"
    ]
    nonempty = sum(bool(part.get("content")) for part in thinking)
    assert nonempty > 0
    checks.append(
        {
            "task": row["task"],
            "seed": row["seed"],
            "path": str(path),
            "requests_checked": len(requests),
            "responses_checked": len(responses),
            "enable_thinking_true_on_every_request": True,
            "provider_model": "qwen3.8-max",
            "nonempty_thinking_parts": nonempty,
        }
    )
result = {
    "passed": True,
    "completed": 3,
    "details": checks,
    "scope": "Actual recorded model settings and returned provider part types; no thought text included. The setting is a Qwen boolean switch, not a graded intensity.",
}
(ROOT / "final-thinking-audit.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result))
