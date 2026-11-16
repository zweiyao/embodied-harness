# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Physical Flexiv contracts remain separate for each existing control mode."""

from pathlib import Path

from rpent.prompt.composition import (
    COMMON_DIR,
    memory_available,
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
        "rdk": "control_rdk.md",
        "eef_delta": "control_eef.md",
    }[values.get("control_mode", "native")]
    return system_sections(
        COMMON_DIR,
        ROOT / control,
        analysis=values.get("analysis_enabled", False),
        variables=values,
    )


def user_prompt(variables=None):
    values = {"memory_dir": str(get_memory_dir("flexiv")), **(variables or {})}
    result = user_sections(
        COMMON_DIR,
        task_file(ROOT / "tasks", "default"),
        memory_available=memory_available(values),
        variables=values,
    )
    result.variables.setdefault("memory_dir", values["memory_dir"])
    if "output_dir" in values and "RUN CONTEXT" not in result:
        result["OUTPUT"] = "Save records under {{output_dir}}."
    return result
