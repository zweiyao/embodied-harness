# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Replay a published sensor tool on archived observations; no simulator calls."""

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path("/home/zwy/work/embodied_harness")
RUN = (
    ROOT
    / "experiments/libero10-task-no-memory-dual-20-20261107/qwen/runs/session/tasks/0005_libero_10_task_t4_s0"
)
VERSION = "cca2f3c424d195fe3e55896ec0fe4c54b08b9f6929fdf794cfc98595458155c3"
library_file = ROOT / f"tool-library/manual/{VERSION}.json"
assert (
    hashlib.sha256(library_file.read_bytes()).hexdigest()
    == "ae4d062e8810352fa3c36e78326d1e6e40faac77917fdb68ec2356f311fd18a9"
)
tool = json.loads(library_file.read_text())[0]
assert tool["name"] == "sensor_patch_batch"
namespace = {}
# Execute only the hash-pinned published numerical helper on archived arrays.
exec(compile(tool["source"], str(library_file), "exec"), namespace)  # noqa: S102


def array(name):
    with np.load(RUN / name / "00.npz") as data:
        assert len(data.files) == 1
        return data[data.files[0]]


world = array("agentview_world_high.npz")
depth = array("agentview_depth_high.npz")
rgb = np.asarray(Image.open(RUN / "agentview_high.png/00.png"))
state = json.loads((RUN / "states.json").read_text())["steps"][0]["state"]
frames = [
    {
        "step": 0,
        "proprio": {"robot0_eef_pos": state["robot0_eef_pos"]},
        "cameras": {
            "agentview": {"high": {"rgb": rgb, "world": world, "depth": depth}}
        },
    }
]
events = [json.loads(line) for line in (RUN / "events.jsonl").read_text().splitlines()]
queries = [
    e["payload"]["arguments"]
    for e in events
    if e["kind"] == "tool_request" and e["payload"]["name"] == "back_project"
][:4]
h, w = world.shape[:2]
points = [[q["row"] / (h - 1), q["col"] / (w - 1)] for q in queries]
result = namespace["run"](frames, {"points": points})
assert len(result["patches"]) == len(points)
assert all(
    p["pixel_rc"] == [q["row"], q["col"]] for p, q in zip(result["patches"], queries)
)
checks = []
for patch, q in zip(result["patches"], queries):
    r, c = q["row"], q["col"]
    xyz = world[r - 2 : r + 3, c - 2 : c + 3, :3].reshape(-1, 3)
    z = depth[r - 2 : r + 3, c - 2 : c + 3].reshape(-1)
    good = (
        np.isfinite(xyz).all(axis=1)
        & (np.abs(xyz).sum(axis=1) > 1e-6)
        & np.isfinite(z)
        & (z > 0)
    )
    reference = np.quantile(xyz[good], [0.1, 0.5, 0.9], axis=0)
    np.testing.assert_allclose(patch["world_median_xyz"], reference[1])
    np.testing.assert_allclose(
        patch["eef_to_patch_xyz"], reference[1] - np.asarray(state["robot0_eef_pos"])
    )
    checks.append(
        {
            "pixel_rc": [r, c],
            "valid_count": patch["valid_count"],
            "patch_spread_m": float(np.linalg.norm(reference[2] - reference[0])),
        }
    )
missing = namespace["run"](
    [{"step": 0, "cameras": {"agentview": {}}}], {"points": points}
)
assert "error" in missing
declarations = json.loads((RUN / "tool-declarations.json").read_text())
assert not any(t["name"].startswith("sensor_") for t in declarations)
artifact = RUN / "segment_01.json"
assert (
    artifact.is_dir()
    and (artifact / "00.json").is_file()
    and not (artifact / "01.json").exists()
)
summary = {
    "run_path": str(RUN),
    "published_version": VERSION,
    "library_file_sha256": hashlib.sha256(library_file.read_bytes()).hexdigest(),
    "checks": checks,
    "patch_median_and_eef_offsets_match": True,
    "missing_high_resolution_rejected": True,
    "selected_native_tools": len(declarations),
    "sensor_tools_selected": False,
    "segment_artifact_is_directory": True,
    "segment_index_is_not_frame_step": True,
    "new_environment_actions": 0,
    "runtime_source_changes": 0,
    "demonstrates_task_gain": False,
    "scope": "One archived frame; direct published function replay, not Docker/integration/semantic validation.",
}
output = ROOT / "debug/qwen-root-cause-20261107/replay.json"
output.write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))
