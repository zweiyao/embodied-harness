# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Browse configured tool libraries without connecting to their environments."""

from __future__ import annotations

import copy
import json
from pathlib import Path

_ENVIRONMENTS = {"libero", "univtac", "flexiv"}


def load_sources(path: str | None) -> list[dict]:
    """Read server-owned environment/library paths from a JSON list."""
    if not path:
        return []
    sources = json.loads(Path(path).read_text())
    if not isinstance(sources, list):
        raise ValueError("RPENT_TOOL_CATALOG must contain a list of sources")
    seen = set()
    for source in sources:
        if not isinstance(source, dict) or set(source) - {
            "robot",
            "library_root",
            "runs_root",
            "control_mode",
        }:
            raise ValueError("Invalid tool catalog source")
        robot = source.get("robot")
        if not isinstance(robot, str) or robot not in _ENVIRONMENTS or robot in seen:
            raise ValueError("Tool catalog sources need unique supported robot names")
        seen.add(robot)
        for key in ("library_root", "runs_root"):
            if key in source and not isinstance(source[key], str):
                raise ValueError(f"Catalog {key} must be a filesystem path")
        if source.get("control_mode", "native") not in ("native", "eef_delta", "rdk"):
            raise ValueError("Unknown catalog control mode")
    return sources


def generated_catalog(
    library_root: Path, *, runs_root: Path | None = None
) -> list[dict]:
    """Read published metadata and hash-checked code; never execute tool source."""
    from robots.libero.research.library import Library

    invoked = set()
    if runs_root is not None:
        for run in runs_root.glob("*/tasks/*/tool-invocations.json"):
            try:
                invoked.update(json.loads(run.read_text()))
            except (OSError, ValueError):
                pass
    result = []
    for path in sorted(library_root.glob("*.meta.json")):
        metadata = json.loads(path.read_text())
        version = path.name.removesuffix(".meta.json")
        (tool,) = Library(library_root).load(version)
        result.append(
            {
                **metadata,
                **tool,
                "id": "generated:" + version,
                "origin": "generated",
                "category": "perception",
                "version": version,
                "invoked": version in invoked,
                "required": False,
            }
        )
    return result


def combined_catalog(
    current: list[dict], *, robot: str, sources: list[dict]
) -> list[dict]:
    """Keep current IDs selectable and show foreign components with adapter gaps."""
    from rpent.dashboard.workbench import native_catalog

    groups = [(robot, current)]
    for source in sources:
        other = source["robot"]
        if other == robot:
            continue
        items = native_catalog(other, control_mode=source.get("control_mode", "native"))
        if source.get("library_root"):
            library = Path(source["library_root"])
            if not library.is_dir():
                raise ValueError(
                    f"Configured {other} tool library does not exist: {library}"
                )
            runs = Path(source["runs_root"]) if source.get("runs_root") else None
            items += generated_catalog(library, runs_root=runs)
        groups.append((other, items))

    result = []
    shared = {}
    for source_robot, items in groups:
        for original in items:
            item = copy.deepcopy(original)
            is_current = source_robot == robot
            item.update(
                source_robot=source_robot,
                supported_environments=[source_robot],
                selectable=is_current,
                incompatibility_reason=None,
            )
            if not is_current:
                item["id"] = f"foreign:{source_robot}:{item['id']}"
                item["required"] = False
                item["availability"] = "incompatible"
                item["incompatibility_reason"] = (
                    f"该控制接口调用 {source_robot} 的执行器；当前环境为 {robot}。"
                    if item.get("category") == "control"
                    else f"该工具使用 {source_robot} 的观测或文件接口；尚未适配 {robot}。"
                )
                item["availability_note"] = item["incompatibility_reason"]
            elif source_robot == "flexiv" and item["origin"] == "generated":
                from robots.flexiv.catalog import generated_availability

                supported, reason = generated_availability(item)
                item["selectable"] = supported
                item["incompatibility_reason"] = reason
                item["availability"] = "available" if supported else "candidate"
                item["availability_note"] = (
                    "已接入记录帧执行器；选择后本轮可调用，回放通过不代表任务效果提升。"
                    if supported
                    else reason
                )
            if item["origin"] == "native" and item.get("category") == "auxiliary":
                key = (
                    item["name"],
                    item["version"],
                    json.dumps(item["parameters"], sort_keys=True),
                )
                if key in shared:
                    existing = shared[key]
                    existing["source_robot"] = "shared"
                    existing["supported_environments"].append(source_robot)
                    continue
                shared[key] = item
            result.append(item)
    return result
