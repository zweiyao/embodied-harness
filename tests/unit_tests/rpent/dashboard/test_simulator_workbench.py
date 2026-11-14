# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Five simulator workbenches preserve native tool and task identities."""

import json

import pytest

from rpent.dashboard.catalog import load_sources
from rpent.dashboard.state import _parse_task
from rpent.dashboard.workbench import Workbench
from rpent.robots.base import get_robot_spec


@pytest.mark.parametrize(
    ("robot", "observation_tool"),
    [
        ("libero", "view_env_state"),
        ("univtac", "observe"),
        ("robodojo", "view_env_state"),
        ("robocasa", "view_env_state"),
        ("robotwin", "view_env_state"),
    ],
)
def test_simulator_catalog_and_selection_without_environment(
    robot, observation_tool, tmp_path, monkeypatch
):
    monkeypatch.delenv("RPENT_TOOL_CATALOG", raising=False)
    bench = Workbench(
        {
            "robot": robot,
            "runs_root": str(tmp_path),
            "library_root": str(tmp_path / "library"),
            "models": [{"id": "fixture", "planner": "api", "model": "fixture"}],
        },
        robot=robot,
    )
    tools = bench.catalog()
    assert any(t["name"] == "finish" for t in tools)
    assert any(t["name"] == observation_tool for t in tools)
    chosen = bench.selection(["native:finish", f"native:{observation_tool}"])
    assert {t["name"] for t in chosen} == {"finish", observation_tool}
    assert not (tmp_path / "states.json").exists()


def test_capabilities_replace_central_catalog_name_list(tmp_path):
    path = tmp_path / "sources.json"
    robots = ["libero", "univtac", "robodojo", "robocasa", "robotwin", "flexiv"]
    path.write_text(json.dumps([{"robot": r} for r in robots]))
    assert [s["robot"] for s in load_sources(str(path))] == robots


@pytest.mark.parametrize("robot", ["robocasa", "robotwin"])
def test_native_protocol_fields_roundtrip_and_unknown_seed_rejected(
    robot, tmp_path, monkeypatch
):
    import importlib

    fields = importlib.import_module(f"robots.{robot}.catalog").task_fields()
    spec = get_robot_spec(robot).dashboard["task"]
    assert [f["name"] for f in fields] == [f["name"] for f in spec["fields"]]
    values = {}
    for f in fields:
        options = (
            f["options_by"][str(values[f["depends_on"]])]
            if "depends_on" in f
            else f["options"]
        )
        values[f["name"]] = options[0][0]
    text = spec["command"] + " " + " ".join(str(values[f["name"]]) for f in fields)
    assert _parse_task(spec, text) == values
    monkeypatch.delenv("RPENT_TOOL_CATALOG", raising=False)
    bench = Workbench(
        {
            "robot": robot,
            "runs_root": str(tmp_path),
            "library_root": str(tmp_path / "library"),
            "models": [{"id": "fixture", "planner": "api", "model": "fixture"}],
            "setup": {"profiles": [{"robot": robot, "task_fields": fields}]},
        },
        robot=robot,
    )
    bench.checks["fixture"] = {"ok": True}
    assert (
        bench.prepare({**values, "tools": ["native:finish"]})["task_name"]
        == values["task_name"]
    )
    with pytest.raises(ValueError, match="Unsupported task field seed"):
        bench.prepare({**values, "seed": -1, "tools": ["native:finish"]})
