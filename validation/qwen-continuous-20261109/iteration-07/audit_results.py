# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Audit four fresh R18/W2 cells; public workflow labels remain observational."""

import hashlib
import json
from pathlib import Path

from metrics import analyze
from model_argument_failure import argument_failure_evidence

from robots.libero.research.manual import availability_prompt
from robots.libero.robot_spec import get_robot_spec

ROOT = Path(__file__).resolve().parent
plan = json.loads((ROOT / "plan.json").read_text())
rows = json.loads((ROOT / "results.json").read_text())
reference_r = json.loads((ROOT.parent / "iteration-06/results.json").read_text())
reference_c = [
    row
    for row in json.loads((ROOT.parent / "iteration-01/results.json").read_text())
    if row["condition"] == "C"
]
handoff = json.loads((ROOT / "material-handoff.json").read_text())
assert json.loads((ROOT / "status.json").read_text())["phase"] == "completed"
expected_cells = {
    (lane, condition, task, 0)
    for lane, condition in (("a", "R18-reference"), ("b", "R18+W2"))
    for task in (4, 0)
}
assert len(rows) == 4
assert {
    (r["lane"], r["condition"], r["task"], r["seed"]) for r in rows
} == expected_cells
assert len({str(Path(r["path"]).resolve()) for r in rows}) == 4
assert len({str(Path(r["runtime_audit"]["path"]).resolve()) for r in rows}) == 4
assert all(r["cell_id"] == r["path"] for r in rows)

material_manifests = {}
for lane, settings in plan["lanes"].items():
    package = Path(settings["materials"])
    manifest = json.loads((package / "manifest.json").read_text())
    assert manifest["version"] == settings["material_version"]
    assert settings["workflow_requested"] is (lane == "b")
    assert all(
        hashlib.sha256((package / name).read_bytes()).hexdigest() == expected
        for name, expected in manifest["files"].items()
    )
    material_manifests[lane] = manifest
assert set(material_manifests["a"]["files"]) == set(material_manifests["b"]["files"])
assert [
    name
    for name in material_manifests["a"]["files"]
    if material_manifests["a"]["files"][name] != material_manifests["b"]["files"][name]
] == ["user.md"]
assert material_manifests["b"]["files"] == handoff["material_files_sha256"]
assert material_manifests["a"]["version"] == handoff["parent_package_version"]
assert material_manifests["b"]["version"] == handoff["package_version"]
assert {
    **material_manifests["b"],
    "version": material_manifests["a"]["version"],
    "files": material_manifests["a"]["files"],
} == material_manifests["a"]
assert handoff["source_root"] == plan["runtime_source"]

summary = {
    "passed": False,
    "conditions": {},
    "paired_initial_images": [],
    "tool_returns": [],
    "workflow_observations": [],
    "invocation_metadata": [],
    "audit_correction": {
        "reason": "Catalog invoked is per-session usage metadata, not the tool contract",
        "excluded_contract_fields": ["invoked"],
        "original_failure_preserved": "initial-final-audit-error.txt",
        "plan": "postrun-audit-correction.md",
        "policy_retries": 0,
        "outcomes_unchanged": True,
    },
}
runtime = []
spec = get_robot_spec()
for row in rows:
    p = Path(row["path"]).resolve()
    lane = row["lane"]
    settings = plan["lanes"][lane]
    assert p.is_relative_to(ROOT / lane / "runs")
    assert row["condition"] == settings["condition"]
    assert row["material_version"] == settings["material_version"]
    outcome = json.loads((p / "outcome.json").read_text())
    assert row["official_success"] == outcome.get("environment_success")
    assert row["classification"] in {
        "task_result",
        "budget_timeout",
        "model_argument_error",
    }
    if row["classification"] == "task_result":
        assert type(row["official_success"]) is bool
        assert row["evaluation_success"] is row["official_success"]
    else:
        assert row["evaluation_success"] is False
    if row["classification"] == "budget_timeout":
        timeout = plan["config"]["planner_timeout_s"]
        assert outcome.get("status") == "timeout"
        assert outcome.get("error") == f"planner timed out after {timeout:g}s"
        assert (outcome.get("elapsed_s") or 0) >= timeout
    if row["classification"] == "model_argument_error":
        assert argument_failure_evidence(p, outcome)
        assert row["evaluation_success"] is False
    assert all(row["metrics"][key] == value for key, value in analyze(p).items())

    manifest = json.loads((p / "manifest.json").read_text())
    declarations = manifest["tools"]
    prior_row = next(
        r for r in reference_r if (r["task"], r["seed"]) == (row["task"], row["seed"])
    )
    prior_path = Path(prior_row["path"])
    prior_tools = json.loads((prior_path / "manifest.json").read_text())["tools"]
    assert len(declarations) == 18
    assert [
        {k: v for k, v in tool.items() if k != "invoked"} for tool in declarations
    ] == [{k: v for k, v in tool.items() if k != "invoked"} for tool in prior_tools]
    for tool, old_tool in zip(declarations, prior_tools, strict=True):
        earlier = [
            r
            for r in rows
            if r["lane"] == lane
            and Path(r["path"]).name < p.name
            and r["metrics"]["tool_calls"].get(tool["name"], 0)
        ]
        summary["invocation_metadata"].append(
            {
                "cell_id": str(p),
                "tool": tool["name"],
                "current_invoked": tool.get("invoked"),
                "historical06_invoked": old_tool.get("invoked"),
                "prior_same_lane_cells_with_toolkit_entry": [
                    r["path"] for r in earlier
                ],
                "interpretation": "Usage metadata recorded separately; no other manifest field excluded.",
            }
        )
    assert [t["id"] for t in declarations] == plan["config"]["tools"]
    assert [t["name"] for t in declarations] == plan["tool_names"]
    for key in ("max_turns", "max_tokens", "planner_timeout_s"):
        assert manifest["task"][key] == plan["config"][key]

    frozen = p / "language-materials"
    frozen_manifest = json.loads((frozen / "manifest.json").read_text())
    assert frozen_manifest == material_manifests[lane]
    assert all(
        hashlib.sha256((frozen / name).read_bytes()).hexdigest() == expected
        for name, expected in frozen_manifest["files"].items()
    )
    values = {
        "suite": plan["suite"],
        "task": row["task"],
        "seed": row["seed"],
        "output_dir": str(p),
        "language_materials": str(frozen),
        "memory_dir": str(frozen / "memory"),
        "memory_version": frozen_manifest["version"],
    }
    actual_prompts = json.loads((p / "prompts.json").read_text())
    assert actual_prompts["user"] == spec.prompts.render("user", variables=values)
    assert actual_prompts["system"] == availability_prompt(
        declarations
    ) + spec.prompts.render("system", variables=values)

    workflow = row["metrics"].get("workflow")
    if isinstance(workflow, dict) and not workflow.get("metric_error"):
        assert workflow["workflow_requested"] is settings["workflow_requested"]
    summary["workflow_observations"].append(
        {
            "cell_id": str(p),
            "condition": row["condition"],
            "task": row["task"],
            "workflow_requested": settings["workflow_requested"],
            "metrics": workflow,
            "outcome_interpretation": "Observational only; no success/classification override.",
        }
    )
    events = [
        json.loads(line) for line in (p / "events.jsonl").read_text().splitlines()
    ]
    prior_events = [
        json.loads(line)
        for line in (prior_path / "events.jsonl").read_text().splitlines()
    ]
    prior_request = next(
        x["payload"] for x in prior_events if x["kind"] == "model_request"
    )
    prior_parameters = prior_request["model_request_parameters"]
    prior_api_tools = (
        prior_parameters["function_tools"] + prior_parameters["output_tools"]
    )
    # list_dir's description/default include the exact run directory. Normalize
    # only that observed variable; preserve every other declaration field.
    expected_api_tools = json.loads(
        json.dumps(prior_api_tools).replace(str(prior_path), str(p))
    )
    requests = [x["payload"] for x in events if x["kind"] == "model_request"]
    responses = [x["payload"] for x in events if x["kind"] == "model_response"]
    assert 1 <= len(requests) <= 30
    assert all(x["model_name"] == "qwen3.8-flash" for x in responses)
    for request in requests:
        assert request["model"]["_model_name"] == "qwen3.8-flash"
        assert request["model_settings"]["extra_body"]["enable_thinking"] is False
        parameters = request["model_request_parameters"]
        actual_tools = parameters["function_tools"] + parameters["output_tools"]
        assert actual_tools == expected_api_tools
    assert plan["benchmark"]["private_bddl"] in (p / "env_server.log").read_text()
    for name in ("translate_to", "rotate_axis", "preview_placement", "align_placement"):
        returned = [
            x["payload"]
            for x in events
            if x["kind"] == "tool_response" and x["payload"].get("name") == name
        ]
        summary["tool_returns"].append(
            {
                "cell_id": str(p),
                "name": name,
                "requests": row["metrics"]["tool_calls"].get(name, 0),
                "responses": len(returned),
                "responses_without_error": sum(
                    isinstance(x.get("result"), dict)
                    and not (
                        x.get("error")
                        or x["result"].get("error")
                        or x["result"].get("errors")
                    )
                    for x in returned
                ),
                "limit": "Counts do not establish handler entry, movement, holding or task benefit.",
            }
        )
    audit_path = Path(row["runtime_audit"]["path"]).resolve()
    assert audit_path.is_relative_to(ROOT / lane)
    report = json.loads(audit_path.read_text())
    assert report["task_path"] == str(p)
    assert report["run_id"] == row["run_id"]
    assert (report["lane"], report["condition"], report["task"], report["seed"]) == (
        lane,
        row["condition"],
        row["task"],
        row["seed"],
    )
    assert report["observer_stopped"] and not report["guard_violations"]
    assert report["environment_eef_control_expected"] is True
    assert report["coverage_complete"] == row["runtime_audit"]["coverage_complete"]
    runtime.append({"path": str(audit_path), "report": report})

for condition in ("R18-reference", "R18+W2"):
    group = [r for r in rows if r["condition"] == condition]
    summary["conditions"][condition] = {
        "valid": len(group),
        "successes": sum(r["evaluation_success"] for r in group),
        "success_rate_percent": 100
        * sum(r["evaluation_success"] for r in group)
        / len(group),
        "before_action_calls": [r["metrics"]["before_action_calls"] for r in group],
    }
for task in (4, 0):
    paired = {
        **{r["condition"]: r for r in rows if r["task"] == task},
        "historical_R06": next(
            r for r in reference_r if r["task"] == task and r["seed"] == 0
        ),
        "historical_C01": next(
            r for r in reference_c if r["task"] == task and r["seed"] == 0
        ),
    }
    cameras = {}
    for camera in ("agentview_high.png", "wrist_high.png"):
        hashes = {
            condition: hashlib.sha256(
                (Path(r["path"]) / camera / "00.png").read_bytes()
            ).hexdigest()
            for condition, r in paired.items()
        }
        assert len(set(hashes.values())) == 1, (task, camera, hashes)
        cameras[camera] = {"hashes": hashes, "identical": True}
    summary["paired_initial_images"].append(
        {"task": task, "seed": 0, "cameras": cameras}
    )

protected = json.loads((ROOT / "invariants.json").read_text())["source_hashes"]
for name, expected in protected.items():
    assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == expected, name
incidents = [
    row for p in ROOT.glob("*/incidents.json") for row in json.loads(p.read_text())
]
corrections_path = ROOT / "classification-corrections.json"
corrections = (
    json.loads(corrections_path.read_text()) if corrections_path.exists() else []
)
corrected = {
    r["path"] for r in corrections if r["to_classification"] == "model_argument_error"
}
assert corrected <= {
    r["path"] for r in rows if r["classification"] == "model_argument_error"
}
summary["initial_incident_entries_preserved"] = len(incidents)
summary["corrected_model_argument_failures"] = len(corrected)
summary["runtime_incidents"] = sum(r["path"] not in corrected for r in incidents)
assert json.loads((ROOT / "cleanup.json").read_text())["passed"]
summary["runtime_guard_coverage"] = (
    "complete"
    if all(r["report"]["coverage_complete"] for r in runtime)
    else "partial; see per-cell observer evidence"
)
summary["runtime_observers"] = [
    {
        "cell_id": r["report"]["task_path"],
        "path": r["path"],
        "coverage_complete": r["report"]["coverage_complete"],
        "observer_stopped": r["report"]["observer_stopped"],
        "snapshot_count": len(r["report"]["snapshots"]),
    }
    for r in runtime
]
(ROOT / "live-audit.json").write_text(
    json.dumps(
        {"audit_type": "contemporaneous_owned_process_observer", "cells": runtime},
        indent=2,
    )
    + "\n"
)
summary["task_results_valid"] = True
summary["protected_files_verified"] = len(protected)
summary["passed"] = True
summary["limitation"] = (
    "Development comparison of two tasks at seed0, fixed lane/condition and temporal ordering. "
    "Historical06 and C01 remain separate references. Official success is primary; compliant labels, "
    "fewer calls, tool acceptance and geometric arrival do not establish holding or task benefit. "
    "This screen does not establish ten-task or held-out improvement."
)
(ROOT / "final-verification.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary))
