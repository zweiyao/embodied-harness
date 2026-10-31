# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Frozen Flexiv selection and recorded perception execution without hardware."""

import base64
import copy
import io
import json
from types import SimpleNamespace

import pytest
from PIL import Image

from examples.flexiv.alignment_contact_replay import candidate
from robots.flexiv.catalog import catalog
from robots.flexiv.manual import ManualToolkit
from robots.libero.research.library import digest


def selection(*names, generated=False):
    chosen = [item for item in catalog(control_mode="rdk") if item["name"] in names]
    if generated:
        definition = candidate()
        chosen.append(
            {
                **definition,
                "origin": "generated",
                "version": digest([definition]),
                "dependencies": ["localize_target"],
            }
        )
    return chosen


@pytest.fixture
def factory(tmp_path, monkeypatch):
    monkeypatch.setattr("rpent.tools.toolkit.substitute", lambda text: text)
    calls = []
    buffer = io.BytesIO()
    Image.new("RGB", (8, 6), "white").save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode()
    state = {
        "tcp_pose": [0.4, 0.0, 0.2, 1, 0, 0, 0],
        "coordinate_frame": "robot_base",
        "quaternion_order": "wxyz",
        "gripper_width_m": 0.004,
        "ext_wrench_in_world": [0, 0, 2, 0, 0, 0],
    }

    def observe():
        calls.append(("observe",))
        return {
            "state": dict(state),
            "camera_calibration": {
                "state": dict(state),
                "cameras": {"side": {"intrinsics": {"width": 8, "height": 6}}},
            },
            "images_png": {"side": encoded},
            "depths": {"side": [[0.3] * 8] * 6},
        }

    def delta(translation, rotation):
        calls.append(("move_eef_delta", translation, rotation))
        state["tcp_pose"] = [
            *[state["tcp_pose"][axis] + translation[axis] for axis in range(3)],
            *state["tcp_pose"][3:],
        ]
        return {"reached": True, "position_error_m": 0.0001}

    env = SimpleNamespace(
        meta={
            "control_backend": "rdk",
            "motion_enabled": True,
            "calibrated_readonly": True,
        },
        get_observation=observe,
        move_eef_delta=delta,
        close=lambda: None,
    )

    def create(selected):
        return ManualToolkit(
            selected=selected,
            env=env,
            output_dir=tmp_path / "run",
            control_mode="rdk",
            dashboard_events=SimpleNamespace(enabled=False, emit=lambda event: None),
            memory=SimpleNamespace(check_layout=lambda: None, file_tool_description=""),
        )

    return create, env, calls


def test_selected_tools_alone_are_declared_and_dispatched_with_native_feedback(factory):
    create, _, calls = factory
    selected = selection("move_eef_delta", "finish")
    kit = create(selected)
    try:
        assert kit.planner_tools_only is True
        assert {tool.name for tool in kit.list_tools()} == {"move_eef_delta", "finish"}
        assert calls == [("observe",)]  # Startup observation survives deselection.
        assert kit.execute_tool("observe", {}).is_error
        assert kit.execute_tool("set_gripper", {"width_m": 0.05}).is_error
        assert calls == [("observe",)]
        result = kit.execute_tool(
            "move_eef_delta",
            {"translation_m": [0.01, 0, 0], "rotation_vector_rad": [0, 0, 0]},
        )
        assert not result.is_error
        assert calls[1] == ("move_eef_delta", [0.01, 0, 0], [0, 0, 0])
        assert calls[2] == ("observe",)
        assert result.images and result.data["action_result"]["reached"]
        assert len(kit.state.records()) == 2
        selected[0]["name"] = "changed_after_start"
        assert {tool.name for tool in kit.list_tools()} == {"move_eef_delta", "finish"}
    finally:
        kit.close()


@pytest.mark.parametrize(
    "case",
    [
        "missing_finish",
        "duplicate",
        "stale_native",
        "unavailable",
        "dependency",
        "changed_generated",
        "unsupported",
    ],
)
def test_invalid_selection_fails_before_observation_or_docker(
    factory, monkeypatch, case
):
    create, env, calls = factory
    selected = selection("finish", "localize_target", generated=True)
    if case == "missing_finish":
        selected = selection("observe")
    elif case == "duplicate":
        selected += [copy.deepcopy(selected[-1])]
    elif case == "stale_native":
        selected[0]["source"] += "\n# stale\n"
    elif case == "unavailable":
        env.meta["motion_enabled"] = False
        selected = selection("move_eef_delta", "finish")
    elif case == "dependency":
        selected = selection("finish", generated=True)
    elif case == "changed_generated":
        selected[-1]["source"] += "\n# changed\n"
    else:
        definition = candidate()
        definition["name"] = "sensor_unknown"
        selected[-1].update(definition, version=digest([definition]))
    monkeypatch.setattr(
        "robots.flexiv.manual.Sandbox",
        lambda *args: pytest.fail("Invalid selection must not start Docker"),
    )
    with pytest.raises(ValueError):
        create(selected)
    assert not calls


def test_disarmed_readonly_selection_is_valid(factory):
    create, env, calls = factory
    env.meta["motion_enabled"] = False
    kit = create(selection("observe", "finish"))
    try:
        assert {tool.name for tool in kit.list_tools()} == {"observe", "finish"}
        assert calls == [("observe",)]
    finally:
        kit.close()


@pytest.mark.parametrize("sandbox_failure", [False, True])
def test_generated_tool_uses_recorded_ids_frozen_source_and_journals_errors(
    factory, monkeypatch, sandbox_failure
):
    create, _, calls = factory
    captured = []

    class FakeSandbox:
        def __init__(self, image):
            self.image = "sha256:frozen-sandbox-image"

        def run(self, definition, params, frames):
            captured.append((copy.deepcopy(definition), params, frames))
            if sandbox_failure:
                raise TimeoutError("sensor tool exceeded 15 seconds")
            return {"status": "evidence_computed", "steps": [f["step"] for f in frames]}

    monkeypatch.setattr("robots.flexiv.manual.Sandbox", FakeSandbox)
    monkeypatch.setattr(
        "robots.flexiv.perception.back_project",
        lambda meta, depth, camera, pixel, box: {
            "camera": camera,
            "coordinate_frame": "robot_base",
            "point_base_m": [0.4 + pixel[0] * 0.001, 0, 0.2],
            "depth_m": 0.3,
            "depth_patch_spread_m": 0.001,
            "valid_patch_pixels": 25,
            "source": "color_aligned_realsense_depth",
            "captured_at": "2026-10-30T00:00:00Z",
            "calibration_validation": {"operator_confirmed": True},
        },
    )
    selected = selection("localize_target", "move_eef_delta", "finish", generated=True)
    frozen_source = selected[-1]["source"]
    kit = create(selected)
    selected[-1]["source"] = "raise RuntimeError('not the frozen program')"
    try:
        record_ids = []
        for target, pixel in (("held feature", [2.0, 2.0]), ("reference", [4.0, 2.0])):
            result = kit.execute_tool(
                "localize_target",
                {
                    "step": 0,
                    "target": target,
                    "camera": "side",
                    "pixel": pixel,
                    "box": [1.0, 1.0, 6.0, 4.0],
                },
            )
            assert not result.is_error
            assert result.data["step"] == 0
            record_ids.append(result.data["record_step"])
        assert record_ids == [1, 2]
        moved = kit.execute_tool(
            "move_eef_delta",
            {
                "translation_m": [0.001, 0, 0],
                "rotation_vector_rad": [0, 0, 0],
            },
        )
        assert moved.data["step"] == 3
        params = {
            "anchor_step": 0,
            "feature_record": 1,
            "reference_records": [2],
            "compare_steps": [3],
            "track_with_tcp": True,
        }
        before = list(calls)
        result = kit.execute_tool("sensor_alignment_contact", params)
        assert result.is_error is sandbox_failure
        assert calls == before
        assert len(captured) == 1 and captured[0][0]["source"] == frozen_source
        frames = captured[0][2]
        assert [frame["step"] for frame in frames] == [0, 3]
        assert [item["record_step"] for item in frames[0]["localizations"]] == [1, 2]
        assert frames[1]["previous_observation_step"] == 0
        assert frames[1]["command"]["translation_m"] == [0.001, 0, 0]
        assert not kit.execute_tool(
            "sensor_alignment_contact", {**params, "compare_steps": [1]}
        ).data.get("status")
        assert len(captured) == 1
        events = [
            json.loads(line)
            for line in (kit.journal.root / "events.jsonl").read_text().splitlines()
        ]
        generated_input = next(
            event for event in events if event["kind"] == "generated_input"
        )
        assert generated_input["payload"]["steps"] == [0, 3]
        assert (
            generated_input["payload"]["sandbox_image"] == "sha256:frozen-sandbox-image"
        )
        assert events[-1]["payload"]["result"].get("error")
        assert json.loads((kit.journal.root / "tool-invocations.json").read_text()) == [
            selected[-1]["version"]
        ]
    finally:
        kit.close()
