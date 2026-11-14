# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Resume only six missing IPv4 cells after an operator-requested stop."""

import ast
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path("/home/zwy/work/embodied_harness")
ORIGINAL = BASE / "experiments/libero-object-t-qwenflash-original-50-20261112"
PARENT = BASE / "experiments/libero-object-t-qwenflash-original-50-ipv4-resume-20261113"
RETEST = BASE / "experiments/libero-object-t-qwenflash-pre-ipv4-retest-5-20261113"
ROOT = BASE / "experiments/libero-object-t-qwenflash-ipv4-final6-20261113"
ARCHIVE = BASE / "validation/libero-object-t-qwenflash-original-50-20261112"
OUT = Path(__file__).resolve().parent


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def replace(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)


assert not ROOT.exists()
settled = [
    r
    for r in json.loads((PARENT / "results.json").read_text())
    if r["network_segment"] == "ipv4-direct"
] + json.loads((RETEST / "results.json").read_text())
keys = {(r["task"], r["seed"]) for r in settled}
assert len(settled) == len(keys) == 44
missing = sorted({(t, s) for t in range(10) for s in range(5)} - keys)
assert missing == [(1, 3), (8, 1), (8, 3), (9, 0), (9, 2), (9, 4)]
prepare = (ARCHIVE / "prepare_batch.py").read_text()
prepare = replace(prepare, str(ORIGINAL.relative_to(BASE)), str(ROOT.relative_to(BASE)))
prepare = replace(
    prepare, "rpent-object-t-qwenflash-'", "rpent-qwenflash-ipv4-final6-'"
)
prepare = replace(prepare, "-20261112.service", "-20261113.service")
prepare = replace(
    prepare,
    "research-runs/libero-object-t-qwenflash-original-50-20261112-",
    "research-runs/libero-object-t-qwenflash-ipv4-final6-20261113-",
)
ast.parse(prepare)
snapshot = OUT / "prepare_batch.snapshot.py"
snapshot.write_text(prepare)
subprocess.run([sys.executable, str(snapshot)], check=True)
plan = json.loads((ROOT / "plan.json").read_text())
parent_plan = json.loads((PARENT / "plan.json").read_text())
for key in [
    "configuration",
    "suite",
    "materials",
    "material_version",
    "source",
    "base_revision",
    "time_policy",
    "incident_policy",
]:
    assert plan[key] == parent_plan[key], key
inv = json.loads((ROOT / "invariants.json").read_text())
assert (
    inv["source_hashes"]
    == json.loads((PARENT / "invariants.json").read_text())["source_hashes"]
)
ports = {}
for p in Path("/proc").iterdir():
    if not p.name.isdigit():
        continue
    try:
        args = (p / "cmdline").read_bytes().split(b"\0")
        cgroup = (p / "cgroup").read_text()
    except (PermissionError, FileNotFoundError):
        continue
    if "harnessvla-dashboard.service" not in cgroup or b"--port" not in args:
        continue
    if b"libero" in args and any(b"pi05_vla_server" in a for a in args):
        ports["vla"] = args[args.index(b"--port") + 1].decode()
    elif any(b"sam3_server.py" in a for a in args):
        ports["sam3"] = args[args.index(b"--port") + 1].decode()
assert set(ports) == {"vla", "sam3"}
for index, (name, lane) in enumerate(plan["lanes"].items()):
    lane["trials"] = [{"task": t, "seed": s} for t, s in missing[index::2]]
    path = ROOT / name / "start.sh"
    text = (
        path.read_text()
        .replace("http://127.0.0.1:49337", "http://127.0.0.1:" + ports["vla"])
        .replace("http://127.0.0.1:37867", "http://127.0.0.1:" + ports["sam3"])
    )
    path.write_text(text)
    save(ROOT / name / "results.json", [])
plan.update(
    total=6,
    tasks=[1, 8, 9],
    network_segment="ipv4-direct",
    approved_user_request="先把libero测完吧；按提前结束失败结算，继续后续任务",
    retained_valid_ipv4_cells=44,
    backend_ports=ports,
)
plan["early_stop_policy"] = (
    "Only running+idle, complete stop response, no pending model/tool calls, no finish call and terminated=false. Save derived failure separately and abort only to release the completed planner. Never append prompts or overwrite the raw outcome."
)
save(ROOT / "plan.json", plan)
driver = (RETEST / "run_batch.py").read_text()
driver = replace(
    driver,
    "import hashlib\n",
    "import hashlib\n\nfrom idle_settlement import early_stop_evidence\n",
)
driver = replace(
    driver,
    '        for trial in lane["trials"]:\n',
    '        for trial in lane["trials"]:\n            adjudication = None\n',
)
driver = replace(
    driver,
    '                if run and run["outcome"] and state["session_state"] == "ready":\n',
    """                if run and adjudication is None and state["session_state"] == "running" and state.get("interaction", {}).get("planner_activity") == "idle":
                    event_path = Path(run["path"]) / "events.jsonl"
                    if event_path.exists():
                        events = [json.loads(line) for line in event_path.read_text().splitlines()]
                        adjudication = early_stop_evidence(state, events)
                        if adjudication is not None:
                            save(Path(run["path"]) / "batch-adjudication.json", adjudication)
                            api(port, "/api/session/abort", {})
                if run and run["outcome"] and state["session_state"] == "ready":
""",
)
driver = replace(
    driver,
    '            outcome = run["outcome"]\n',
    """            outcome = run["outcome"]
            raw_status = outcome["status"]
            if adjudication is not None:
                assert raw_status == "aborted", outcome
                outcome = {**outcome, "status": "model_stopped_without_finish", "environment_success": False, "error": None}
""",
)
driver = replace(
    driver,
    '                "budget_exhausted",\n',
    '                "budget_exhausted",\n                "model_stopped_without_finish",\n',
)
driver = replace(
    driver,
    '                "status": outcome["status"],\n',
    '                "status": outcome["status"],\n                "raw_harness_status": raw_status,\n                "batch_adjudication": adjudication,\n',
)
driver = replace(
    driver,
    '        for lane in PLAN["lanes"].values():\n',
    '        import sys\n\n        subprocess.run([sys.executable, str(ROOT / "summarize_final50.py")], check=True)\n        for lane in PLAN["lanes"].values():\n',
)
ast.parse(driver)
(ROOT / "run_batch.py").write_text(driver)
shutil.copyfile(OUT / "idle_settlement.py", ROOT / "idle_settlement.py")
shutil.copyfile(OUT / "summarize_final50.py", ROOT / "summarize_final50.py")
shutil.copyfile(PARENT / "trace_workbench.py", ROOT / "trace_workbench.py")
launch = replace((PARENT / "launch_preflight.py").read_text(), str(PARENT), str(ROOT))
(ROOT / "launch_preflight.py").write_text(launch)
spec = importlib.util.spec_from_file_location("final6", ROOT / "run_batch.py")
sys.path.insert(0, str(ROOT))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.aggregate()
save(ROOT / "status.json", {"phase": "prepared", "planned": 6, "completed": 0})
save(
    OUT / "preparation.json",
    {
        "root": str(ROOT),
        "remaining": missing,
        "retained_unique": 44,
        "source_hashes_preserved": len(inv["source_hashes"]),
        "backend_ports": ports,
        "configuration_unchanged": True,
        "early_stop_rule_approved": True,
    },
)
print(
    json.dumps({"root": str(ROOT), "missing": missing, "lanes": plan["lanes"]}),
    flush=True,
)
