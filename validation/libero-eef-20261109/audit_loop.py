# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Retain bounded counters and image-delivery evidence, never raw observations."""

import json
from datetime import datetime
from pathlib import Path

ROOT = Path("/home/zwy/work/embodied_harness/validation/libero-eef-20261109")
run = ROOT / "vlm-loop-01"
events = [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()]
summary = json.loads((run / "summary.json").read_text())
requests = [e for e in events if e["kind"] == "model_request"]
responses = [e for e in events if e["kind"] == "model_response"]
deliveries = []
for index, event in enumerate(events):
    if event["kind"] != "tool_response" or event["payload"]["name"] != "move_eef":
        continue
    response = event["payload"]
    following = next(e for e in events[index + 1 :] if e["kind"] == "model_request")
    parts = following["payload"]["messages"][-1]["parts"]
    returned = next(p for p in parts if p.get("tool_name") == "move_eef")
    images = [c["data"] for c in returned["content"] if isinstance(c, dict)]
    assert images == response["images"]
    deliveries.append(
        {
            "step": response["result"]["step"],
            "images": len(images),
            "delivered_to_next_request": True,
        }
    )
assert summary["passed"] and len(deliveries) == 2
assert all(
    r["payload"]["model_settings"]["extra_body"]["enable_thinking"] for r in requests
)
report = {
    "passed": True,
    "purpose": summary["purpose"],
    "model": "qwen3.8-max",
    "enable_thinking": True,
    "request_budget": 6,
    "wall_time_budget_s": 300,
    "output_token_limit": 4096,
    "stats": summary["stats"],
    "native_success": summary["native_success"],
    "environment_closed": summary["environment_closed"],
    "actions": [
        {
            "step": a["step"],
            "images": a["images"],
            **{
                k: a["receipt"][k]
                for k in ["steps_used", "position_error_m", "orientation_error_rad"]
            },
        }
        for a in summary["actions"]
    ],
    "feedback_delivery": deliveries,
    "returned_model_wait_s": [
        (
            datetime.fromisoformat(b["time"]) - datetime.fromisoformat(a["time"])
        ).total_seconds()
        for a, b in zip(requests, responses, strict=True)
    ],
    "thinking_response_count": sum(
        any(
            p.get("part_kind") == "thinking" and p.get("content")
            for p in e["payload"]["parts"]
        )
        for e in responses
    ),
    "limitation": "This fixture forces two free-space movements and omits experience reads; it validates the interface, not task policy or success-rate gains.",
}
task = next((ROOT / "smoke/runs").glob("*/tasks/*"))
outcome = json.loads((task / "outcome.json").read_text())
report["task_smoke"] = {
    k: outcome[k]
    for k in ["status", "stats", "elapsed_s", "actions", "environment_success", "error"]
}
(ROOT / "loop-evidence.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report))
