# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Audit the complete four-cell C/E development screen."""

import hashlib
import json
from pathlib import Path

from metrics import analyze

ROOT = Path(__file__).resolve().parent
plan = json.loads((ROOT / "plan.json").read_text())
rows = json.loads((ROOT / "results.json").read_text())
assert json.loads((ROOT / "status.json").read_text())["phase"] == "completed"
assert len(rows) == 4
summary = {
    "passed": False,
    "conditions": {},
    "paired_initial_images": [],
    "runtime_incidents": 0,
}
for condition in ["C", "E"]:
    group = [r for r in rows if r["condition"] == condition]
    assert {(r["task"], r["seed"]) for r in group} == {(4, 0), (0, 0)}
    for row in group:
        p = Path(row["path"])
        actual = analyze(p)
        assert all(row["metrics"][k] == v for k, v in actual.items())
        requests = []
        responses = []
        for line in (p / "events.jsonl").read_text().splitlines():
            event = json.loads(line)
            if event["kind"] == "model_request":
                requests.append(event["payload"])
            if event["kind"] == "model_response":
                responses.append(event["payload"])
        assert len(requests) <= 30
        assert all(
            x["model_settings"]["extra_body"]["enable_thinking"] is False
            for x in requests
        )
        assert all(x["model_name"] == "qwen3.8-flash" for x in responses)
        assert all(
            "move_eef"
            in {t["name"] for t in x["model_request_parameters"]["function_tools"]}
            for x in requests
        )
        assert (
            plan["benchmark"]["private_bddl"] in (p / "env_server.log").read_text()
        ), "Private BDDL route not used"
    summary["conditions"][condition] = {
        "valid": len(group),
        "successes": sum(r["evaluation_success"] for r in group),
        "success_rate_percent": 100
        * sum(r["evaluation_success"] for r in group)
        / len(group),
        "before_action_calls": [r["metrics"]["before_action_calls"] for r in group],
        "new_tool_calls": sum(
            r["metrics"]["tool_calls"].get("move_eef", 0) for r in group
        ),
    }
for task in [4, 0]:
    pair = [r for r in rows if r["task"] == task]
    cameras = {}
    for camera in ["agentview_high.png", "wrist_high.png"]:
        hashes = {
            r["condition"]: hashlib.sha256(
                (Path(r["path"]) / camera / "00.png").read_bytes()
            ).hexdigest()
            for r in pair
        }
        cameras[camera] = {
            "hashes": hashes,
            "identical": len(set(hashes.values())) == 1,
        }
    summary["paired_initial_images"].append(
        {
            "task": task,
            "seed": 0,
            "cameras": cameras,
            "eligible_for_strict_pair": all(v["identical"] for v in cameras.values()),
        }
    )
for name, expected in json.loads((ROOT / "invariants.json").read_text())[
    "source_hashes"
].items():
    assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == expected, name
summary["runtime_incidents"] = sum(
    len(json.loads(p.read_text())) for p in ROOT.glob("*/incidents.json")
)
assert json.loads((ROOT / "cleanup.json").read_text())["passed"]
summary["passed"] = True
summary["limitation"] = (
    "Development only, two tasks and one initial state; lane is confounded with condition. No overall ten-task success-rate or causal generalization claim."
)
(ROOT / "final-verification.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary))
