# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Flexiv tool browsing reflects declarations without opening robot resources."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from robots.flexiv.catalog import catalog, generated_availability
from robots.flexiv.toolkit import FlexivToolkit
from robots.libero.research.library import Library
from rpent.tools import ToolResult


def test_rdk_catalog_uses_current_declarations_without_constructing_toolkit(
    monkeypatch,
):
    def forbidden(*args, **kwargs):
        pytest.fail("Browsing tools must not construct or observe a robot")

    monkeypatch.setattr(FlexivToolkit, "__init__", forbidden)
    tools = {item["name"]: item for item in catalog(control_mode="rdk")}
    assert set(tools) == {
        "observe",
        "tactile_compare",
        "view_perception_setup",
        "localize_target",
        "move_tcp",
        "move_eef_delta",
        "set_gripper",
        "stop_motion",
        "read_text_file",
        "write_text_file",
        "list_dir",
        "finish",
    }
    assert {item["availability"] for item in tools.values()} == {"conditional"}
    assert set(tools["move_eef_delta"]["parameters"]["properties"]) == {
        "translation_m",
        "rotation_vector_rad",
    }
    assert tools["move_tcp"]["description"] == FlexivToolkit.rdk_move_tcp.description
    assert (
        tools["set_gripper"]["description"] == FlexivToolkit.rdk_set_gripper.description
    )
    assert tools["finish"]["required"] is True
    assert "original image pixels" in tools["tactile_compare"]["description"]
    assert "not calibrated force" in tools["tactile_compare"]["description"]

    # A generic quaternion contract must not override the delta schema.
    delta = tools["move_eef_delta"]
    assert "rotation_vector_rad=[rx,ry,rz]" in delta["input_contract"]
    assert "wxyz" not in delta["input_contract"]
    assert (
        "unit axis * angle"
        in delta["parameters"]["properties"]["rotation_vector_rad"]["description"]
    )
    assert "arrival or the command deadline" in delta["description"]
    assert "quaternion_wxyz=[w,x,y,z]" in tools["move_tcp"]["input_contract"]
    assert "四元数" not in tools["set_gripper"]["input_contract"]


def test_live_declarations_supply_exact_description_schema_and_registration():
    actual = replace(
        FlexivToolkit.observe,
        description="This run's exact observation declaration.",
        _input_schema={"type": "object", "properties": {"tick": {"type": "integer"}}},
    )
    tools = {
        item["name"]: item
        for item in catalog(control_mode="rdk", declarations=(actual,))
    }
    assert tools["observe"]["availability"] == "registered"
    assert tools["observe"]["description"] == actual.description
    assert tools["observe"]["parameters"] == actual.input_schema
    assert tools["move_tcp"]["availability"] == "not_registered"
    assert tools["finish"]["availability"] == "not_registered"


@pytest.mark.parametrize(
    "mode,metadata",
    [
        ("rdk", {"control_backend": "rdk", "motion_enabled": True}),
        ("rdk", {"control_backend": "rdk", "motion_enabled": False}),
        (
            "rdk",
            {
                "control_backend": "rdk",
                "motion_enabled": True,
                "calibrated_readonly": True,
            },
        ),
        ("native", {"motion_enabled": False, "calibrated_readonly": True}),
        ("native", {"motion_enabled": True}),
        (
            "native",
            {
                "motion_enabled": True,
                "supervised_control": True,
                "eef_chunk_control": True,
                "home_available": True,
            },
        ),
        (
            "eef_delta",
            {
                "motion_enabled": True,
                "supervised_control": True,
                "eef_chunk_control": True,
            },
        ),
    ],
)
def test_catalog_matches_actual_toolkit_registration(
    tmp_path, monkeypatch, mode, metadata
):
    monkeypatch.setattr("rpent.tools.toolkit.substitute", lambda value: value)
    monkeypatch.setattr(FlexivToolkit, "_capture", lambda self: ToolResult(data={}))
    toolkit = FlexivToolkit(
        env=SimpleNamespace(meta=metadata, close=lambda: None),
        output_dir=tmp_path,
        dashboard_events=SimpleNamespace(enabled=False, emit=lambda event: None),
        memory=SimpleNamespace(check_layout=lambda: None, file_tool_description=""),
        control_mode=mode,
    )
    try:
        declarations = toolkit.list_tools()
        tools = catalog(control_mode=mode, declarations=declarations)
        registered = {
            item["name"]: item for item in tools if item["availability"] == "registered"
        }
        assert set(registered) == {item.name for item in declarations}
        for declaration in declarations:
            assert (
                registered[declaration.name]["description"] == declaration.description
            )
            assert (
                registered[declaration.name]["parameters"] == declaration.input_schema
            )
    finally:
        toolkit.close()


def test_candidate_is_displayed_but_never_imported_or_registered(tmp_path):
    definition = {
        "name": "sensor_contact_candidate",
        "description": "Candidate contact measurement.",
        "parameters": {"type": "object", "properties": {}},
        "source": "raise RuntimeError('must never import')\ndef run(frames, params):\n    return {}\n",
    }
    version = Library(tmp_path).save([definition])
    metadata = {
        "validation": "replay_passed",
        "source_run": "development-run",
        "reason": "Explain motion and contact together.",
    }
    (tmp_path / f"{version}.meta.json").write_text(json.dumps(metadata))
    tools = catalog(control_mode="rdk", declarations=(), library_root=tmp_path)
    candidate = next(item for item in tools if item["name"] == definition["name"])
    assert candidate["id"] == f"generated:{version}"
    assert candidate["origin"] == "generated"
    assert candidate["availability"] == "candidate"
    assert candidate["validation"] == "replay_passed"
    assert candidate["source"] == definition["source"]
    assert candidate["parameters"] == definition["parameters"]
    assert candidate["source_run"] == metadata["source_run"]
    assert candidate["required"] is False


def test_wired_generated_tool_is_selectable_without_loading_program(tmp_path):
    from examples.flexiv.alignment_contact_replay import candidate

    definition = candidate()
    definition["source"] = (
        "raise RuntimeError('must never import')\ndef run(frames, params):\n    return {}\n"
    )
    version = Library(tmp_path).save([definition])
    (tmp_path / f"{version}.meta.json").write_text(
        json.dumps({"validation": "replay_passed"})
    )
    tools = catalog(control_mode="rdk", library_root=tmp_path)
    generated = next(item for item in tools if item["name"] == definition["name"])
    assert generated["availability"] == "conditional"
    assert generated["validation"] == "replay_passed"
    tools = catalog(control_mode="rdk", declarations=(), library_root=tmp_path)
    generated = next(item for item in tools if item["name"] == definition["name"])
    assert generated["availability"] == "not_registered"


def test_generated_adapter_contract_can_be_reused_by_another_tool():
    from examples.flexiv.alignment_contact_replay import candidate

    definition = {**candidate(), "name": "sensor_other_alignment"}
    assert generated_availability(definition)[0] is False
    definition["input_adapter"] = "flexiv.alignment.v1"
    assert generated_availability(definition) == (True, None)
    definition["parameters"]["required"].remove("anchor_step")
    assert generated_availability(definition)[0] is False


def test_missing_library_is_not_created_while_browsing(tmp_path):
    root = tmp_path / "absent-library"
    with pytest.raises(ValueError, match="library does not exist"):
        catalog(control_mode="rdk", library_root=root)
    assert not root.exists()


def test_invalid_control_mode_is_not_advertised():
    with pytest.raises(ValueError, match="control mode"):
        catalog(control_mode="unknown")
