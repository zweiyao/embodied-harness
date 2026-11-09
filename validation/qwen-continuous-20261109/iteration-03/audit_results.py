# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Audit C+M against preserved C cells without replacing failures."""

import hashlib
import json
from pathlib import Path

from metrics import analyze

ROOT = Path(__file__).resolve().parent
OLD = ROOT.parent / "iteration-01"
plan = json.loads((ROOT / "plan.json").read_text())
rows = json.loads((ROOT / "results.json").read_text())
reference = [
    r for r in json.loads((OLD / "results.json").read_text()) if r["condition"] == "C"
]
assert json.loads((ROOT / "status.json").read_text())["phase"] == "completed"
assert len(rows) == 2
assert {(r["task"], r["seed"], r["condition"]) for r in rows} == {
    (4, 0, "C+M"),
    (0, 0, "C+M"),
}
summary = {"passed": False, "conditions": {}, "paired_initial_images": []}
for row in rows:
    p = Path(row["path"])
    assert all(row["metrics"][k] == v for k, v in analyze(p).items())
    declarations = json.loads((p / "manifest.json").read_text())["tools"]
    assert (
        next(t["version"] for t in declarations if t["name"] == "translate_to")
        == plan["native_motion_version"]
    )

    events = [
        json.loads(line) for line in (p / "events.jsonl").read_text().splitlines()
    ]
    requests = [x["payload"] for x in events if x["kind"] == "model_request"]
    responses = [x["payload"] for x in events if x["kind"] == "model_response"]
    assert len(requests) <= 30
    assert all(
        x["model_settings"]["extra_body"]["enable_thinking"] is False for x in requests
    )
    assert all(x["model_name"] == "qwen3.8-flash" for x in responses)
    for request in requests:
        parameters = request["model_request_parameters"]
        tools = parameters["function_tools"] + parameters["output_tools"]
        assert len(tools) == len(plan["tool_names"])
        assert {t["name"] for t in tools} == set(plan["tool_names"])
        patch = next(t for t in tools if t["name"] == "sensor_patch_batch")
        assert "alignment_pair" not in patch["parameters_json_schema"]["properties"]
        motion = next(t for t in tools if t["name"] == "translate_to")
        assert set(motion["parameters_json_schema"]["properties"]) == {"xyz"}
    assert plan["benchmark"]["private_bddl"] in (p / "env_server.log").read_text()
for condition, group in [("C_reference", reference), ("C+M", rows)]:
    summary["conditions"][condition] = {
        "valid": len(group),
        "successes": sum(r["evaluation_success"] for r in group),
        "success_rate_percent": 100
        * sum(r["evaluation_success"] for r in group)
        / len(group),
        "before_action_calls": [r["metrics"]["before_action_calls"] for r in group],
    }
for task in [4, 0]:
    pair = [r for r in rows + reference if r["task"] == task]
    assert len(pair) == 2
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
    "Development only, two tasks and one initial state; prior C reference retained. Temporal and lane confounding remain; no overall ten-task success-rate or causal generalization claim."
)
(ROOT / "final-verification.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary))
