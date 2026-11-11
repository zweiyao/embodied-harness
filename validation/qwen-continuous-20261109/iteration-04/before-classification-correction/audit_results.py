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
reference_m = json.loads((ROOT.parent / "iteration-03/results.json").read_text())
assert json.loads((ROOT / "status.json").read_text())["phase"] == "completed"
assert len(rows) == 2
assert {(r["task"], r["seed"], r["condition"]) for r in rows} == {
    (4, 0, "C+M-restricted18"),
    (0, 0, "C+M-restricted18"),
}
summary = {
    "passed": False,
    "conditions": {},
    "paired_initial_images": [],
    "motion_returns": [],
}
for row in rows:
    p = Path(row["path"])
    assert all(row["metrics"][k] == v for k, v in analyze(p).items())
    declarations = json.loads((p / "manifest.json").read_text())["tools"]
    prior_row = next(r for r in reference_m if r["task"] == row["task"])
    prior_tools = {
        t["name"]: t
        for t in json.loads((Path(prior_row["path"]) / "manifest.json").read_text())[
            "tools"
        ]
    }
    assert len(declarations) == 18
    assert all(
        all(
            t[key] == prior_tools[t["name"]][key]
            for key in ["version", "description", "parameters"]
        )
        for t in declarations
    )
    assert (
        next(t["version"] for t in declarations if t["name"] == "translate_to")
        == plan["native_motion_version"]
    )

    events = [
        json.loads(line) for line in (p / "events.jsonl").read_text().splitlines()
    ]
    motion_returns = [
        x["payload"]
        for x in events
        if x["kind"] == "tool_response" and x["payload"].get("name") == "translate_to"
    ]
    summary["motion_returns"].append(
        {
            "task": row["task"],
            "requests": row["metrics"]["tool_calls"].get("translate_to", 0),
            "responses": len(motion_returns),
            "responses_without_error": sum(
                isinstance(x.get("result"), dict)
                and not (
                    x.get("error")
                    or x["result"].get("error")
                    or x["result"].get("errors")
                )
                for x in motion_returns
            ),
            "actual_movement": "Requires pose/frame review; not inferred from response count or steps_used.",
        }
    )
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
for condition, group in [
    ("C_reference", reference),
    ("C+M_21_reference", reference_m),
    ("C+M-restricted18", rows),
]:
    summary["conditions"][condition] = {
        "valid": len(group),
        "successes": sum(r["evaluation_success"] for r in group),
        "success_rate_percent": 100
        * sum(r["evaluation_success"] for r in group)
        / len(group),
        "before_action_calls": [r["metrics"]["before_action_calls"] for r in group],
        "translate_to_calls": sum(
            r["metrics"]["tool_calls"].get("translate_to", 0) for r in group
        ),
    }
for task in [4, 0]:
    pair = [r for r in rows + reference + reference_m if r["task"] == task]
    assert len(pair) == 3
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
live = json.loads((ROOT / "live-audit.json").read_text())
assert (
    live["all_no_eef_control_wrapper"]
    and live["all_source_roots_match"]
    and live["all_proxy_variables_absent"]
)
summary["passed"] = True
summary["limitation"] = (
    "Development only, two tasks and one initial state; prior C and 21-tool C+M references retained; selection restriction and absence of the EEF feedback wrapper are interventions. Temporal and lane confounding remain; no overall ten-task success-rate or causal generalization claim."
)
(ROOT / "final-verification.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary))
