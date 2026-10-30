# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Test saved-record selection without importing or executing candidate code."""

import json

import pytest
from jsonschema import ValidationError

from examples.flexiv.alignment_contact_replay import recorded_frames


@pytest.fixture
def saved_run(tmp_path):
    def observation(step, command=None):
        return {
            "step_idx": step,
            "artifacts": ["perception.json", "side.png", "evaluator.json"],
            "state": {
                "tcp_pose": [0.5, 0.1, -0.4, 1, 0, 0, 0],
                "coordinate_frame": "robot_base",
                "quaternion_order": "wxyz",
                "gripper_width_m": 0.004,
                "ext_wrench_in_world": [0, 0, 2, 0, 0, 0],
                "hidden_object_pose": [99, 99, 99],
                "task_success": True,
            },
            "command": command,
            "result": {
                "reached": True,
                "position_error_m": 0.0004,
                "environment_success": True,
                "target_pose_truth": [99, 99, 99],
            },
            "extras": {"native_success": True},
        }

    def localization(step, source):
        data = {
            "step": source,
            "camera": "wrist",
            "pixel": [100, 200],
            "box": [90, 190, 110, 210],
            "target": "visible surface",
            "coordinate_frame": "robot_base",
            "point_base_m": [0.51 + step * 0.001, 0.1, -0.45],
            "depth_m": 0.3,
            "depth_patch_spread_m": 0.001,
            "valid_patch_pixels": 25,
            "source": "color_aligned_realsense_depth",
            "captured_at": "2026-10-30T14:34:00",
            "calibration_validation": {"operator_confirmed": True},
            "hidden_hole_center": [99, 99, 99],
        }
        (tmp_path / "localization.json" / f"{step}.json").write_text(json.dumps(data))
        return {
            "step_idx": step,
            "artifacts": ["localization.json", "wrist_selected.png"],
            "state": observation(source)["state"],
            "command": {"tool": "localize_target", "source_step": source},
            "result": data,
        }

    (tmp_path / "localization.json").mkdir()
    motion = {
        "action": "move_eef_delta",
        "translation_m": [0, 0, -0.002],
        "rotation_vector_rad": [0, 0, 0],
        "hidden_policy_hint": "discard this",
    }
    records = [
        observation(0),
        localization(1, 0),
        localization(2, 0),
        localization(3, 0),
        observation(4, motion),
        localization(5, 4),
        observation(6, motion),
    ]
    (tmp_path / "states.json").write_text(json.dumps({"steps": records}))
    params = {
        "anchor_step": 0,
        "feature_record": 1,
        "reference_records": [2, 3],
        "compare_steps": [4, 6],
        "track_with_tcp": True,
    }
    return tmp_path, params


def test_localizations_are_grouped_under_source_observation(saved_run):
    root, params = saved_run
    frames = recorded_frames(root, params)

    assert [frame["step"] for frame in frames] == [0, 4, 6]
    assert [m["record_step"] for m in frames[0]["localizations"]] == [1, 2, 3]
    assert {m["step"] for m in frames[0]["localizations"]} == {0}
    assert frames[1]["localizations"] == frames[2]["localizations"] == []


def test_adjacency_skips_queries_but_preserves_omitted_observations(saved_run):
    root, params = saved_run
    frames = recorded_frames(root, params)
    assert [frame["previous_observation_step"] for frame in frames] == [None, 0, 4]

    frames = recorded_frames(root, {**params, "compare_steps": [6]})
    assert frames[1]["previous_observation_step"] == 4
    assert frames[1]["previous_observation_step"] != frames[0]["step"]


def test_input_bundle_excludes_hidden_state_evaluator_and_unrelated_fields(saved_run):
    root, params = saved_run
    frames = recorded_frames(root, params)
    serialized = json.dumps(frames)

    for hidden in (
        "hidden_object_pose",
        "task_success",
        "environment_success",
        "target_pose_truth",
        "native_success",
        "evaluator.json",
        "hidden_hole_center",
        "hidden_policy_hint",
    ):
        assert hidden not in serialized
    assert frames[1]["command"] == {
        "action": "move_eef_delta",
        "translation_m": [0, 0, -0.002],
        "rotation_vector_rad": [0, 0, 0],
    }
    assert frames[1]["action_result"] == {
        "reached": True,
        "position_error_m": 0.0004,
    }
    assert "ext_wrench_in_world" in frames[0]["state"]


@pytest.mark.parametrize("changes", [{"feature_record": 4}, {"compare_steps": [3]}])
def test_rejects_observation_ids_used_as_localizations_and_query_ids_as_frames(
    saved_run, changes
):
    root, params = saved_run
    with pytest.raises(ValueError, match="localization"):
        recorded_frames(root, {**params, **changes})


def test_rejects_localization_from_another_anchor(saved_run):
    root, params = saved_run
    with pytest.raises(ValueError, match="anchor_step"):
        recorded_frames(root, {**params, "reference_records": [2, 5]})


@pytest.mark.parametrize("field", ["feature_record", "compare_steps"])
def test_rejects_unknown_record_ids(saved_run, field):
    root, params = saved_run
    value = 999 if field == "feature_record" else [999]
    with pytest.raises(ValueError):
        recorded_frames(root, {**params, field: value})


@pytest.mark.parametrize("steps", [[4, 6, 7, 8], [4, 4]])
def test_schema_rejects_too_many_or_duplicate_comparison_frames(saved_run, steps):
    root, params = saved_run
    with pytest.raises(ValidationError):
        recorded_frames(root, {**params, "compare_steps": steps})


@pytest.mark.parametrize("steps", [[6, 4], [0, 4]])
def test_rejects_reordered_or_repeated_anchor_observations(saved_run, steps):
    root, params = saved_run
    with pytest.raises(ValueError, match="increasing"):
        recorded_frames(root, {**params, "compare_steps": steps})


def test_rejects_command_and_localization_source_disagreement(saved_run):
    root, params = saved_run
    manifest = json.loads((root / "states.json").read_text())
    manifest["steps"][2]["command"]["source_step"] = 4
    (root / "states.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="anchor_step"):
        recorded_frames(root, params)


def test_rejects_feature_reused_as_its_own_reference(saved_run):
    root, params = saved_run
    with pytest.raises(ValueError):
        recorded_frames(root, {**params, "reference_records": [1, 2]})


@pytest.mark.parametrize("change", ["width", "missing_width", "gripper_command"])
def test_omitted_gripper_change_invalidates_later_tracking(saved_run, change):
    root, params = saved_run
    manifest = json.loads((root / "states.json").read_text())
    intermediate = manifest["steps"][4]
    if change == "width":
        intermediate["state"]["gripper_width_m"] = 0.02
    elif change == "missing_width":
        del intermediate["state"]["gripper_width_m"]
    else:
        intermediate["command"] = {"action": "set_gripper", "width_m": 0.004}
    (root / "states.json").write_text(json.dumps(manifest))

    frames = recorded_frames(root, {**params, "compare_steps": [6]})
    # The final width matches the anchor, but an omitted release/regrasp must
    # not restore the previous feature-to-TCP transform.
    assert (
        frames[0]["state"]["gripper_width_m"] == frames[1]["state"]["gripper_width_m"]
    )
    assert frames[0]["tracking_break_since_anchor"] is False
    assert frames[1]["tracking_break_since_anchor"] is True


def test_missing_capture_after_a_control_breaks_action_adjacency(saved_run):
    root, params = saved_run
    manifest = json.loads((root / "states.json").read_text())
    manifest["steps"][5] = {
        "step_idx": 5,
        "artifacts": [],
        "state": {},
        "command": {
            "action": "move_eef_delta",
            "translation_m": [0.001, 0, 0],
            "rotation_vector_rad": [0, 0, 0],
        },
        "result": {"error": "capture failed after motion"},
    }
    (root / "states.json").write_text(json.dumps(manifest))

    frames = recorded_frames(root, params)
    assert frames[1]["previous_observation_step"] == 0
    assert frames[2]["previous_observation_step"] is None
