# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Compare old declarations and installed gripper math without an environment."""

import hashlib
import inspect
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from robosuite.models.grippers.panda_gripper import PandaGripper
from robosuite.models.grippers.robotiq_85_gripper import Robotiq85Gripper

snapshot_code = """
import json
from robots.libero.research.manual import availability_prompt
from rpent.dashboard.workbench import Workbench, native_catalog
wb = Workbench.__new__(Workbench)
wb.robot = "libero"
wb.catalog = lambda: [dict(t, selectable=True) for t in native_catalog()]
output = []
for ids in [None, ["native:move_eef", "native:finish"], ["native:finish"]]:
    selected = wb.selection(ids)
    output.append({"ids": [t["id"] for t in selected],
                   "prompt": availability_prompt(selected)})
print(json.dumps(output))
"""

snapshots = [
    json.loads(
        subprocess.check_output(
            [sys.executable, "-c", snapshot_code], cwd=Path(root), text=True
        )
    )
    for root in sys.argv[1:3]
]
assert len(snapshots) == 2 and snapshots[0] == snapshots[1]
grippers = {}
for cls in (PandaGripper, Robotiq85Gripper):
    cases = []
    for initial in ([0.0, 0.0], [-0.6, 0.4], [0.6, -0.4]):
        gripper = cls.__new__(cls)  # No XML load, simulator construction or reset.
        gripper.current_action = np.array(initial)
        for _ in range(3):
            np.testing.assert_array_equal(
                gripper.format_action(np.array([0.0])), initial
            )
        opened = gripper.format_action(np.array([-1.0]))
        assert not np.array_equal(opened, initial)
        cases.append(
            {"initial_target": initial, "zero_preserved": True, "open_changed": True}
        )
    source = Path(inspect.getfile(cls))
    grippers[cls.__name__] = {
        "source": str(source),
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "cases": cases,
    }
print(
    json.dumps(
        {
            "default_selection_and_old_prompts_unchanged": True,
            "comparison_cases": len(snapshots[0]),
            "default_tool_ids": snapshots[0][0]["ids"],
            "installed_gripper_math": grippers,
            "simulator_instances": 0,
            "simulator_actions": 0,
            "model_requests": 0,
            "limitations": "Command-target math only; no measured-gap, grasp, clearance or task-success claim.",
        }
    )
)
