# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Read current BDDL/init arrays and archived calibration; never start an environment."""

import hashlib
import json
import runpy
from pathlib import Path

import numpy as np
import torch

SITE = Path("/home/zwy/work/harnessvla/.venv/lib/python3.11/site-packages")
CORE = SITE / "liberopro/liberopro"
RUN = Path(
    "/home/zwy/work/embodied_harness/experiments/qwen-flash-eef-screen3-20261109/a/runs/session/tasks/0002_libero_10_task_t8_s0"
)
parser = runpy.run_path(str(CORE / "envs/bddl_utils.py"))[
    "_core_robosuite_parse_problem"
]
names = runpy.run_path(str(CORE / "benchmark/libero_suite_task_map.py"))[
    "libero_task_map"
]["libero_10_task"]
out = {
    "environment_started": False,
    "model_requests": 0,
    "runtime_changes": 0,
    "tasks": [],
}
for task, name in enumerate(names):
    path = CORE / "bddl_files/libero_10_task" / (name + ".bddl")
    parsed = parser(str(path))
    out["tasks"].append(
        {
            "task": task,
            "bddl": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "language": " ".join(parsed["language_instruction"]),
            "goal": parsed["goal_state"],
            "objects": parsed["objects"],
            "static_language_goal_review": "conflict: requested left pot but goal selects right-region object"
            if task == 8
            else "no apparent mismatch in object/goal semantics; not full physical predicate validation",
        }
    )
path = CORE / "init_files/libero_10_task" / (names[8] + ".pruned_init")
states = torch.load(path, weights_only=False)
assert states.shape == (50, 47)
p1, p2 = states[:, 10:13], states[:, 17:20]


def within(xyz, bounds):
    return (
        (xyz[:, 0] >= bounds[0])
        & (xyz[:, 0] <= bounds[2])
        & (xyz[:, 1] >= bounds[1])
        & (xyz[:, 1] <= bounds[3])
    )


parsed = parser(out["tasks"][8]["bddl"])
r = next(
    v for k, v in parsed["regions"].items() if k.endswith("moka_pot_right_init_region")
)["ranges"][0]
l = next(
    v for k, v in parsed["regions"].items() if k.endswith("moka_pot_left_init_region")
)["ranges"][0]
meta = json.loads((RUN / "agentview_metadata_high.json/00.json").read_text())
transform = np.asarray(meta["extrinsic_cam2world"])
k = np.asarray(meta["intrinsic_K"])


def project(xyz):
    camera = transform[:3, :3].T @ (np.asarray(xyz) - transform[:3, 3])
    pixel = k @ camera
    return (pixel[:2] / pixel[2])[::-1].tolist()


with np.load(RUN / "agentview_world_high.npz/00.npz") as file:
    world = file[file.files[0]]
out["task8_init"] = {
    "path": str(path),
    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    "shape": list(states.shape),
    "flattened_layout": {
        "time": [0, 1],
        "robot_qpos": [1, 10],
        "moka_pot_1_free_qpos": [10, 17],
        "moka_pot_2_free_qpos": [17, 24],
        "stove_button_qpos": [24, 25],
        "qvel": [25, 47],
        "index_convention": "Python zero-based half-open slices",
    },
    "layout_basis": "7 Panda joints + 2 finger joints; two free objects in parsed declaration/merge order; fixed stove hinge; nq=24,nv=22",
    "first_moka1_xyz": p1[0].tolist(),
    "first_moka2_xyz": p2[0].tolist(),
    "moka1_in_right_region_count": int(within(p1, r).sum()),
    "moka2_in_left_region_count": int(within(p2, l).sum()),
    "right_region_xy_bounds": r,
    "left_region_xy_bounds": l,
    "moka1_y_larger_all": bool(np.all(p1[:, 1] > p2[:, 1])),
    "first_center_projected_rc": {
        "moka_pot_1": project(p1[0]),
        "moka_pot_2": project(p2[0]),
    },
    "world_map_projection_check": {
        "source_pixel_rc": [630, 840],
        "reprojected_rc": project(world[630, 840, :3]),
    },
    "calibration_source": str(RUN / "agentview_metadata_high.json/00.json"),
    "scope": "Offline source-order and saved-array decoding; no live joint-name query or environment start.",
}
sources = {
    "liberopro/liberopro/__init__.py": ["libero_config_path =", "def get_libero_path"],
    "liberopro/liberopro/envs/bddl_utils.py": [
        'elif t == ":objects"',
        "object_list.append(group.pop(0))",
    ],
    "liberopro/liberopro/envs/bddl_base_domain.py": [
        "self.objects = list(self.objects_dict.values())",
        "mujoco_objects=self.objects + self.fixtures",
    ],
    "liberopro/liberopro/envs/problems/libero_kitchen_tabletop_manipulation.py": [
        "def _load_objects_in_arena",
        "def _load_fixtures_in_arena",
        "def _check_success",
    ],
    "liberopro/liberopro/envs/objects/turbosquid_objects.py": ["class MokaPot("],
    "liberopro/liberopro/envs/env_wrapper.py": [
        "def set_init_state",
        "problem_info = BDDLUtils.get_problem_info(bddl_file_name)",
        "self.env = TASK_MAPPING",
    ],
    "robosuite/utils/binding_utils.py": [
        "def from_flattened",
        "def set_state_from_flattened",
    ],
    "robosuite/models/tasks/task.py": [
        "def merge_objects",
        "self.worldbody.append(mujoco_obj.get_obj())",
    ],
    "rlinf/envs/sim/libero/libero_env.py": [
        "def _repoint_libero_config",
        "if configured_root != installed_root:",
        'bddl_root = l_pro.get_libero_path("bddl_files")',
        "original_path = os.path.join(bddl_root, folder_name, file_name)",
        '"bddl_file_name": final_path',
        "WorkerEnv(**param)",
        'init_root = l_pro.get_libero_path("init_states")',
    ],
    "liberopro/liberopro/benchmark/__init__.py": [
        "def _make_benchmark",
        "def get_task_init_states",
    ],
}
out["source_locations"] = []
for rel, needles in sources.items():
    path = SITE / rel
    lines = path.read_text().splitlines()
    out["source_locations"].append(
        {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "lines": {
                needle: [i + 1 for i, line in enumerate(lines) if needle in line]
                for needle in needles
            },
        }
    )
print(json.dumps(out, indent=2))
