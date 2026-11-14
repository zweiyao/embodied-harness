# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Read-only native robotwin workbench metadata."""

import json
from pathlib import Path

from rpent.dashboard.native_tools import build_catalog, validate_native_selection
from rpent.tools import iter_tools
from rpent.tools.common import CommonTools


def native_catalog() -> list[dict]:
    from robots.robotwin import tools
    from robots.robotwin.primitives import RoboTwinPrimitives
    from robots.robotwin.toolkit import RoboTwinToolkit

    common = list(iter_tools(CommonTools))
    return build_catalog(
        [
            *common,
            *iter_tools(tools),
            *iter_tools(RoboTwinPrimitives),
            RoboTwinToolkit.render,
        ],
        {t.name for t in common},
    )


def validate_selection(selected: list[dict]) -> None:
    validate_native_selection(selected, native_catalog())


def task_fields() -> list[dict]:
    protocol = json.loads(
        (Path(__file__).parent / "eval/demo_randomized.json").read_text()
    )
    tasks = protocol["tasks"]
    return [
        {"name": "task_name", "label": "原生任务", "options": [[t, t] for t in tasks]},
        {
            "name": "task_config",
            "label": "环境任务集",
            "options": [[protocol["task_config"], protocol["task_config"]]],
        },
        {
            "name": "seed",
            "label": "场景 seed 与指令",
            "depends_on": "task_name",
            "options_by": {
                t: [
                    [row["seed"], f"{row['seed']} · {row['task_language']}"]
                    for row in rows
                ]
                for t, rows in tasks.items()
            },
        },
    ]
