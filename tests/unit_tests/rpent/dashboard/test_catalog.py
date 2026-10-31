# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Cross-environment browsing does not grant incompatible execution access."""

import json

import pytest

from rpent.dashboard.catalog import load_sources
from rpent.dashboard.workbench import Workbench, publish


@pytest.fixture
def workbenches(tmp_path, monkeypatch):
    sources = []
    for robot in ("libero", "univtac", "flexiv"):
        library = tmp_path / robot / "library"
        library.mkdir(parents=True)
        sources.append(
            {"robot": robot, "library_root": str(library), "control_mode": "rdk"}
        )
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(sources))
    monkeypatch.setenv("RPENT_TOOL_CATALOG", str(path))
    return {
        source["robot"]: Workbench(
            {
                "robot": source["robot"],
                "control_mode": "rdk",
                "library_root": source["library_root"],
                "runs_root": str(tmp_path / source["robot"] / "runs"),
                "models": [{"id": "sdk", "planner": "codex", "model": "fixture"}],
            },
            robot=source["robot"],
        )
        for source in sources
    }


def definition(name="sensor_fixture", *, changed=False):
    return {
        "name": name,
        "description": "Count recorded sensor frames.",
        "parameters": {"type": "object", "properties": {}},
        "source": f"def run(frames, params): return {{'changed': {changed!r}}}\n",
    }


def test_all_sources_visible_without_constructing_hardware(workbenches, monkeypatch):
    from robots.flexiv.toolkit import FlexivToolkit

    def forbidden(*args, **kwargs):
        pytest.fail("Catalog browsing must not construct a robot toolkit")

    monkeypatch.setattr(FlexivToolkit, "__init__", forbidden)
    bench = workbenches["flexiv"]
    items = bench.catalog()
    assert {env for item in items for env in item["supported_environments"]} == {
        "libero",
        "univtac",
        "flexiv",
    }
    by_id = {item["id"]: item for item in items}
    assert by_id["native:move_eef_delta"]["selectable"] is True
    assert by_id["foreign:libero:native:pi0_pick"]["selectable"] is False
    assert by_id["foreign:univtac:native:move_eef"]["incompatibility_reason"]
    finish = [item for item in items if item["name"] == "finish"]
    assert len(finish) == 1
    assert finish[0]["id"] == "native:finish"
    assert finish[0]["source_robot"] == "shared"
    assert set(finish[0]["supported_environments"]) == {"libero", "univtac", "flexiv"}
    assert {item["id"] for item in bench.selection()} == {
        item["id"]
        for item in items
        if item["origin"] == "native" and item["selectable"]
    }


def test_shared_file_tools_are_not_made_available_to_univtac(workbenches):
    bench = workbenches["univtac"]
    read = [item for item in bench.catalog() if item["name"] == "read_text_file"]
    assert len(read) == 1
    assert read[0]["source_robot"] == "shared"
    assert set(read[0]["supported_environments"]) == {"libero", "flexiv"}
    assert read[0]["selectable"] is False
    with pytest.raises(ValueError, match="尚未适配"):
        bench.selection(["native:finish", read[0]["id"]])


def test_foreign_control_and_program_ids_are_rejected(workbenches):
    version = publish(workbenches["univtac"].library, definition(), {})
    bench = workbenches["flexiv"]
    foreign = f"foreign:univtac:generated:{version}"
    tool = next(item for item in bench.catalog() if item["id"] == foreign)
    assert tool["source"] == definition()["source"]
    assert tool["source_robot"] == "univtac"
    assert tool["selectable"] is False
    for tool_id in (foreign, "foreign:libero:native:pi0_pick"):
        with pytest.raises(ValueError, match="当前环境|尚未适配"):
            bench.selection(["native:finish", tool_id])


def test_current_dependencies_versions_and_frozen_source_survive_global_catalog(
    workbenches,
):
    bench = workbenches["libero"]
    first = publish(bench.library, definition(), {"dependencies": ["back_project"]})
    tool_id = "generated:" + first
    with pytest.raises(ValueError, match="requires"):
        bench.selection(["native:finish", tool_id])
    bench.checks["sdk"] = {"ok": True}
    prepared = bench.prepare(
        {"tools": ["native:finish", "native:back_project", tool_id]}
    )
    new = publish(bench.library, definition(changed=True), {"previous_version": first})
    assert prepared["frozen_tools"][-1]["source"] == definition()["source"]
    assert prepared["frozen_tools"][-1]["version"] == first
    with pytest.raises(ValueError, match="Unknown"):
        bench.selection(["native:finish", tool_id])
    for observer in workbenches.values():
        versions = {
            item["version"]
            for item in observer.catalog()
            if item["origin"] == "generated"
        }
        assert versions == {new}


def test_generated_code_is_loaded_as_data_only(workbenches, tmp_path):
    marker = tmp_path / "must-not-exist"
    tool = definition()
    tool["source"] = (
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n" + tool["source"]
    )
    publish(workbenches["libero"].library, tool, {})
    workbenches["flexiv"].catalog()
    assert not marker.exists()


def test_missing_global_config_keeps_current_ids_only(tmp_path, monkeypatch):
    monkeypatch.delenv("RPENT_TOOL_CATALOG", raising=False)
    bench = Workbench(
        {
            "runs_root": str(tmp_path),
            "library_root": str(tmp_path / "library"),
            "models": [],
        }
    )
    assert all(
        item["selectable"] and item["id"].startswith("native:")
        for item in bench.catalog()
    )
    assert not bench.library.exists()


@pytest.mark.parametrize(
    "sources",
    [
        {},
        [{"robot": "unknown"}],
        [{"robot": "libero"}, {"robot": "libero"}],
        [{"robot": "libero", "library_root": 42}],
        [{"robot": "flexiv", "control_mode": "invented"}],
    ],
)
def test_invalid_server_sources_fail_explicitly(tmp_path, sources):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(sources))
    with pytest.raises(ValueError):
        load_sources(str(path))


def test_missing_foreign_library_is_not_created(workbenches, tmp_path):
    bench = workbenches["flexiv"]
    missing = tmp_path / "missing"
    bench.catalog_sources = [{"robot": "libero", "library_root": str(missing)}]
    with pytest.raises(ValueError, match="does not exist"):
        bench.catalog()
    assert not missing.exists()
