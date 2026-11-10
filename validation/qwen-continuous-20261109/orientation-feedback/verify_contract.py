# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Compare frozen parent declarations, defaults and prompts without a simulator."""

import json
import os
import subprocess
import sys
from pathlib import Path

code = """import json
from robots.libero.research.manual import availability_prompt
from rpent.dashboard.workbench import Workbench, native_catalog
catalog=native_catalog();wb=Workbench.__new__(Workbench);wb.robot="libero";wb.catalog=lambda:[dict(t,selectable=True) for t in catalog]
output=[]
for ids in [None,["native:finish"],["native:move_eef","native:finish"],["native:translate_to","native:finish"],["native:preview_placement","native:align_placement","native:finish"],["native:rotate_pitch","native:rotate_wrist","native:finish"]]:
 selected=wb.selection(ids); output.append({"ids":[t["id"] for t in selected],"prompt":availability_prompt(selected)})
print(json.dumps({"catalog":catalog,"cases":output}))
"""
values = []
for root in sys.argv[1:3]:
    env = {**os.environ, "PYTHONPATH": root, "RPENT_REPO_ROOT": root}
    values.append(
        json.loads(
            subprocess.check_output(
                [sys.executable, "-c", code], cwd=root, env=env, text=True
            )
        )
    )
old, new = values
assert old["cases"] == new["cases"]
new_catalog = {item["name"]: item for item in new["catalog"]}
assert all(item == new_catalog[item["name"]] for item in old["catalog"])
assert set(new_catalog) - {item["name"] for item in old["catalog"]} == {"rotate_axis"}
assert new_catalog["translate_to"]["version"] == "6711255f161f2c32649b31f6c2ff8055f5c8544bfbdca507ce66fa4daac280af"
report = {
    "passed": True,
    "old_native_declarations_unchanged": len(old["catalog"]),
    "default_selection_and_old_prompt_cases_unchanged": len(old["cases"]),
    "orientation_tool_version": new_catalog["rotate_axis"]["version"],
    "placement_tool_versions": {
        name: new_catalog[name]["version"]
        for name in ("preview_placement", "align_placement")
    },
    "native_motion_version": new_catalog["translate_to"]["version"],
    "model_requests": 0,
    "simulator_actions": 0,
}
Path(sys.argv[3]).write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report))
