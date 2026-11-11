# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Read archived sensor artifacts without constructing or resetting EnvState."""

import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image
from robots.libero.research.placement import PlacementTools

parser = argparse.ArgumentParser()
parser.add_argument("annotations", type=Path)
parser.add_argument("output", type=Path)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
annotations = json.loads(args.annotations.read_text())
cases = {}
results = []
for child in annotations["cases"]:
    case = {**cases.get(child.get("inherits"), {}), **child}
    cases[case["id"]] = case
    root, step, camera = Path(case["run"]), case["step"], case["camera"]

    def artifact(name):
        return root / name / f"{step:02d}{Path(name).suffix}"

    paths = {
        "rgb": artifact(camera + "_high.png"),
        "world": artifact(camera + "_world_high.npz"),
        "calibration": artifact(camera + "_metadata_high.json"),
        "state": root / "states.json",
    }
    states = json.loads(paths["state"].read_text())["steps"]
    raw = next(row["state"] for row in states if row["step_idx"] == step)
    with np.load(paths["world"]) as archive:
        world = archive["array"]
    high = {
        "rgb": np.asarray(Image.open(paths["rgb"])),
        "world": world,
        "calibration": json.loads(paths["calibration"].read_text()),
    }
    proprio = {
        k: raw[k] for k in ("robot0_eef_pos", "robot0_eef_quat", "robot0_gripper_qpos")
    }
    frame = {"step": step, "proprio": proprio, "cameras": {camera: {"high": high}}}
    tool = PlacementTools(SimpleNamespace(frames=lambda: [frame]), None)
    result = tool.preview_placement(
        **{
            k: case[k]
            for k in (
                "step",
                "camera",
                "held_feature",
                "target_region",
                "plane_samples",
            )
        }
    )
    # Images remain diagnostic artifacts outside Git; only numeric provenance is copied.
    for index, content in enumerate(result.images):
        (args.output / f"{case['id']}-{index}.png").write_bytes(content)
    data = dict(result.data)
    data.pop("preview_id", None)
    if "selected_region_center_xyz" in data:
        other = "wrist" if camera == "agentview" else "agentview"
        meta = json.loads(artifact(other + "_metadata_high.json").read_text())
        c2w = np.asarray(meta["extrinsic_cam2world"])
        target = np.asarray(data["selected_region_center_xyz"])
        p = np.asarray(meta["intrinsic_K"]) @ (c2w[:3, :3].T @ (target - c2w[:3, 3]))
        data["second_camera_target_pixel_rc"] = (p[:2] / p[2])[::-1].tolist()
        data["second_camera_projection_limit"] = (
            "Projection for independent image review, not a semantic or accuracy verdict"
        )
    results.append(
        {
            "id": case["id"],
            "roles": case["visual_roles"],
            "result": data,
            "source_sha256": {
                k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in paths.items()
            },
            "images": [
                str(args.output / f"{case['id']}-{i}.png")
                for i in range(len(result.images))
            ],
        }
    )
summary = {
    "cases": results,
    "simulator_actions": 0,
    "model_calls": 0,
    "limitation": "Independent manual annotations; no target policy evaluated, no action or semantic verification performed",
}
(args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
print(
    json.dumps(
        {
            "status_counts": {item["id"]: item["result"]["status"] for item in results},
            "output": str(args.output),
        }
    )
)
