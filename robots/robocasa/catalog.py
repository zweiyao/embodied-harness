# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Read-only native robocasa workbench metadata."""

import json
from pathlib import Path

from rpent.dashboard.native_tools import build_catalog, validate_native_selection
from rpent.tools import iter_tools
from rpent.tools.common import CommonTools


def native_catalog() -> list[dict]:
    from robots.robocasa import tools
    from robots.robocasa.primitives import RoboCasaPrimitives

    common = list(iter_tools(CommonTools))
    return build_catalog(
        [*common, *iter_tools(RoboCasaPrimitives), *iter_tools(tools)],
        {t.name for t in common},
    )


def validate_selection(selected: list[dict]) -> None:
    validate_native_selection(selected, native_catalog())


def task_fields() -> list[dict]:
    protocol = json.loads((Path(__file__).parent / "eval/target50.json").read_text())
    seeds = {
        task: [[n, str(n)] for n in group["seeds"]]
        for group in protocol["splits"].values()
        for task in group["tasks"]
    }
    return [
        {"name": "task_name", "label": "原生任务", "options": [[t, t] for t in seeds]},
        {
            "name": "split",
            "label": "环境任务集",
            "options": [[protocol["environment_split"], protocol["environment_split"]]],
        },
        {
            "name": "seed",
            "label": "场景 seed",
            "depends_on": "task_name",
            "options_by": seeds,
        },
    ]
