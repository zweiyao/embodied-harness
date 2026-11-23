# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Physical Flexiv contracts remain separate for each existing control mode."""

from pathlib import Path

from rpent.prompt.composition import (
    COMMON_DIR,
    memory_available,
    read_sections,
    system_sections,
    task_file,
    user_sections,
)
from rpent.utils.config import get_memory_dir

ROOT = Path(__file__).parent / "prompts"


def system_prompt(variables=None):
    values = variables or {}
    control = {
        "native": "control_native.md",
        "eef_absolute": "control_absolute.md",
        "rdk": "control_rdk.md",
        "eef_delta": "control_eef.md",
    }[values.get("action_mode") or values.get("control_mode", "native")]
    result = system_sections(
        COMMON_DIR,
        ROOT / control,
        analysis=values.get("analysis_enabled", False),
        variables=values,
    )
    physical = read_sections({"PHYSICAL OPERATION": ROOT / "physical_operation.md"})
    result.update(physical)
    result.sources += physical.sources
    return result


def inspection_task(key, instruction):
    from robots.flexiv.robot_spec import INSPECTION

    return (
        task_file(ROOT / "tasks", key).stem in {"default", "inspection"}
        or instruction == INSPECTION
    )


def user_prompt(variables=None):
    values = {"memory_dir": str(get_memory_dir("flexiv")), **(variables or {})}
    result = user_sections(
        COMMON_DIR,
        task_file(ROOT / "tasks", values.get("task_key", "default")),
        memory_available=memory_available(values),
        variables=values,
    )
    result["OFFICIAL INSTRUCTION"] = "{{instruction}}"
    result.variables.setdefault("memory_dir", values["memory_dir"])
    if "output_dir" in values and "RUN CONTEXT" not in result:
        result["OUTPUT"] = "Save records under {{output_dir}}."
    return result
