# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Read-only workbench metadata for RoboDojo's native tools and layouts."""

from __future__ import annotations

import hashlib
import inspect
import re
from pathlib import Path

from rpent.tools import iter_tools
from rpent.tools.common import CommonTools


def native_catalog() -> list[dict]:
    from robots.robodojo import tools

    common = list(iter_tools(CommonTools))
    common_names = {t.name for t in common}
    result = []
    for declaration in [*iter_tools(tools), *common]:
        source = inspect.getsource(declaration.handler)
        auxiliary = declaration.name in common_names
        result.append(
            {
                "id": f"native:{declaration.name}",
                "name": declaration.name,
                "origin": "native",
                "category": "auxiliary"
                if auxiliary
                else "perception"
                if declaration.readonly
                else "control",
                "description": declaration.description,
                "parameters": declaration.input_schema,
                "version": hashlib.sha256(source.encode()).hexdigest(),
                "source": source,
                "required": declaration.name == "finish",
                "dependencies": [],
                "validation": "native",
                "input_contract": declaration.description,
                "example": None,
            }
        )
    return result


def validate_selection(selected: list[dict]) -> None:
    """Reject unsupported execution and stale declarations before ENV startup."""
    catalog = {item["id"]: item for item in native_catalog()}
    names = [item["name"] for item in selected]
    if "finish" not in names or len(names) != len(set(names)):
        raise ValueError("Select finish and at most one version per tool")
    for item in selected:
        current = catalog.get(item["id"])
        if item.get("origin") != "native" or current is None:
            raise ValueError("RoboDojo workbench supports native tools only")
        if any(
            item.get(key) != current[key]
            for key in ("name", "version", "source", "parameters", "description")
        ):
            raise ValueError(f"Native tool changed since selection: {item['name']}")


def task_fields(
    source_root: str | Path, assets_root: str | Path, env_cfg_type: str = "arx_x5"
) -> list[dict]:
    """Enumerate fixed layouts using the installed SeedManager's ID semantics.

    The current native bridge uses the environment config's seed (default 0)
    for the layout directory. A layout ID is its numeric-suffix-sorted position,
    not the suffix itself. No simulator or description manager is constructed.
    """
    import yaml

    from robots.robodojo.tasks import list_tasks

    source_root, assets_root = Path(source_root), Path(assets_root)
    cfg = yaml.safe_load((source_root / "env_cfg" / f"{env_cfg_type}.yml").read_text())
    directory = (
        assets_root
        / "Assets/Eval_Layout/RoboDojo"
        / cfg["config_name"]
        / str(cfg.get("seed", 0))
    )
    tasks = list_tasks(source_root)
    if not tasks:
        raise ValueError("RoboDojo task inventory is empty")
    layouts = {}
    for task in tasks:
        pattern = re.compile(rf"{re.escape(task)}_\d+\.json")
        paths = sorted(
            (p for p in directory.iterdir() if pattern.fullmatch(p.name)),
            key=lambda p: int(p.stem.rsplit("_", 1)[-1]),
        )
        if not paths:
            raise ValueError(f"No fixed layouts for RoboDojo task: {task}")
        layouts[task] = [[i, str(i)] for i in range(len(paths))]
    return [
        {"name": "task", "label": "原生任务", "options": [[t, t] for t in tasks]},
        {
            "name": "layout",
            "label": "场景布局（layout）",
            "depends_on": "task",
            "options_by": layouts,
        },
    ]
