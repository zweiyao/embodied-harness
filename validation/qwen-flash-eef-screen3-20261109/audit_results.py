# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Audit the completed screen and compare bounded metrics with its reference."""

import hashlib
import json
from pathlib import Path

from metrics import analyze

ROOT = Path(__file__).resolve().parent
plan = json.loads((ROOT / "plan.json").read_text())
rows = json.loads((ROOT / "results.json").read_text())
assert json.loads((ROOT / "status.json").read_text())["phase"] == "completed"
assert len(rows) == plan["total"] == 3
reference = json.loads((Path(plan["reference_root"]) / "results.json").read_text())
parity = json.loads((ROOT / "initial-scene-parity.json").read_text())
assert parity["complete"]
comparisons = []
for row in sorted(rows, key=lambda r: r["task"]):
    path = Path(row["path"])
    metrics = analyze(path)
    assert metrics == {k: row["metrics"][k] for k in metrics}
    events = [
        json.loads(line) for line in (path / "events.jsonl").read_text().splitlines()
    ]
    requests = [e["payload"] for e in events if e["kind"] == "model_request"]
    responses = [e["payload"] for e in events if e["kind"] == "model_response"]
    assert all(
        r["model_settings"]["extra_body"]["enable_thinking"] is False for r in requests
    )
    assert all(r["model_name"] == "qwen3.8-flash" for r in responses)
    assert len(requests) <= plan["config"]["max_turns"]
    assert all(
        "move_eef"
        in {t["name"] for t in r["model_request_parameters"]["function_tools"]}
        for r in requests
    )
    eef_responses = [
        e["payload"]
        for e in events
        if e["kind"] == "tool_response" and e["payload"]["name"] == "move_eef"
    ]
    old = next(r for r in reference if r["task"] == row["task"])
    scene = next(r for r in parity["rows"] if r["task"] == row["task"])
    comparisons.append(
        {
            "task": row["task"],
            "seed": row["seed"],
            "matched_initial_images": scene["matched_initial_images"],
            "current_success": row["evaluation_success"],
            "reference_success": old["evaluation_success"],
            "termination": row["status"],
            "elapsed_s": row["elapsed_s"],
            "model_requests": len(requests),
            "model_responses": len(responses),
            "unfinished_model_requests": len(requests) - len(responses),
            "actions": metrics["action_calls"],
            "reference_actions": old["metrics"]["action_calls"],
            "before_action_calls": metrics["before_action_calls"],
            "reference_before_action_calls": old["metrics"]["before_action_calls"],
            "mean_completed_model_wait_s": metrics["completed_model_wait_mean_s"],
            "reference_mean_completed_model_wait_s": old["metrics"][
                "completed_model_wait_mean_s"
            ],
            "move_eef_calls": metrics["tool_calls"].get("move_eef", 0),
            "move_eef_returned_steps": sum(
                r["result"].get("log", {}).get("result", {}).get("steps_used", 0)
                for r in eef_responses
            ),
            "move_eef_errors": sum(
                bool(r["result"].get("error")) for r in eef_responses
            ),
            "tool_errors": metrics["tool_error_responses"],
            "memory_reads": row["metrics"]["new_experience_reads"],
        }
    )
protected = json.loads((ROOT / "invariants.json").read_text())["source_hashes"]
assert all(
    hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p, h in protected.items()
)
cleanup = json.loads((ROOT / "cleanup.json").read_text())
assert cleanup["passed"]
report = {
    "passed": True,
    "completed": 3,
    "protected_files": len(protected),
    "successes": sum(r["current_success"] for r in comparisons),
    "success_rate_percent": 100 * sum(r["current_success"] for r in comparisons) / 3,
    "move_eef_calls": sum(r["move_eef_calls"] for r in comparisons),
    "move_eef_offered_every_request": True,
    "comparison": comparisons,
    "runtime_incidents": sum(
        len(json.loads(p.read_text())) for p in ROOT.glob("*/incidents.json")
    ),
    "limitations": [
        "Three development cells, one attempt each, no fresh randomized baseline.",
        "Adding the tool also enables its approved conditional guidance.",
        "Mean model waits exclude unfinished requests and are not pure network time.",
        "Any initial-image mismatch is excluded from a strict paired-scene comparison.",
    ],
}
(ROOT / "final-verification.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, ensure_ascii=False))
