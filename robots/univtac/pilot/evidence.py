# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Export self-contained, model-visible development evidence for tool makers."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from rpent.dashboard.workbench import clean

STATE = dict.fromkeys(
    (
        "eef_pose_wxyz",
        "gripper",
        "joint_positions",
        "pose_frame",
        "eef_frame",
        "position_units",
        "gripper_units",
    )
)
CALIBRATION = dict.fromkeys(
    (
        "intrinsics",
        "position_w",
        "quaternion_wxyz",
        "camera_convention",
        "depth_units",
        "height",
        "width",
    )
)
CAMERA = {"rgb": None, "depth": None, "calibration": CALIBRATION}
TACTILE = dict.fromkeys(
    (
        "rgb",
        "depth",
        "reference_rgb",
        "reference_kind",
        "tracking_quality",
        "image_size",
        "depth_image_size",
        "depth_units",
        "depth_semantics",
        "marker_units",
        "marker_coordinate_order",
        "marker_origin",
        "marker_axes",
        "marker_reference",
        "marker_current",
        "marker_displacement",
    )
)
FRAME = {
    "cameras": {"head": CAMERA, "wrist": CAMERA},
    "tactile": {"left": TACTILE, "right": TACTILE},
    "state": STATE,
    **dict.fromkeys(
        (
            "step",
            "timestamp",
            "simulation_time_s",
            "physics_dt",
            "control_step",
            "physics_step",
            "pose_frame",
            "eef_frame",
            "gripper_units",
        )
    ),
}
RECEIPT = {
    "exec_success",
    "reason",
    "native_action_delta",
    "physics_step_delta",
    "position_error_m",
    "orientation_error_rad",
    "max_joint_increment_rad",
    "executed_commands",
}
TACTILE_METRICS = {
    "reference_kind",
    "mean_rgb_change",
    "changed_pixel_fraction",
    "change_threshold",
    "change_centroid_rc",
    "image_size",
    "image_change",
    "marker_count",
    "valid_markers",
    "mean_marker_displacement_xy",
    "median_marker_displacement_magnitude",
    "p95_marker_displacement_magnitude",
    "marker_displacement",
    "tracking_quality",
}
PRIVATE = re.compile(
    r"(^|_)(actor|actors|evaluator)(_|$)|official_success|native_success|environment_success|ground.?truth|hidden|"
    r"api.?key|authorization|access_token|refresh_token|id_token|password|traceback|^reward$|^atom$|"
    r"^done$|^terminated$|^truncated$|^eval_success$|^success$|^early_stop$|^plan_failed$|^budget_exhausted$",
    re.I,
)


def _scrub(value):
    if isinstance(value, dict):
        return {
            key: _scrub(item) for key, item in value.items() if not PRIVATE.search(key)
        }
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    return clean(value)


def _pick(value, fields):
    return {key: _scrub(value[key]) for key in fields if key in value}


def _safe_file(root, relative):
    path = root / relative
    if path.resolve() != path or not path.is_file():
        raise ValueError(f"Missing or redirected evidence file: {relative}")
    return path


def _receipt(value):
    result = _pick(value, RECEIPT | {"error"})
    if "commands" in value:
        result["commands"] = [_pick(command, RECEIPT) for command in value["commands"]]
    return result


def _feedback(root):
    if not (root / "events.jsonl").exists():
        return {"schema_version": 1, "calls": []}
    path = _safe_file(root, Path("events.jsonl"))
    calls = {}
    for line in path.read_text().splitlines():
        event = json.loads(line)
        payload = event.get("payload", {})
        if event.get("kind") == "tool_request":
            calls[payload["call_id"]] = {
                "call_id": payload["call_id"],
                "name": payload["name"],
                "arguments": _scrub(payload.get("arguments", {})),
            }
        elif event.get("kind") == "tool_response" and payload.get("call_id") in calls:
            call = calls[payload["call_id"]]
            value = payload.get("result", {})
            result = _pick(value, {"error", "errors", "step"})
            if call["name"].startswith("sensor_"):
                result = _scrub(value)
            elif call["name"] == "move_eef":
                result.update(_receipt(value.get("control_result", value)))
            elif call["name"] == "observe":
                result["state"] = _pick(value.get("state", {}), STATE)
            elif call["name"] == "depth_points":
                result.update(
                    _pick(value, {"camera", "image_size", "pixels_rc", "depth_m"})
                )
                if isinstance(value.get("calibration"), dict):
                    result["calibration"] = _pick(value["calibration"], CALIBRATION)
            elif call["name"] == "tactile_stats":
                result.update(_pick(value, {"units"}))
                result["fingers"] = {
                    side: _pick(metrics, TACTILE_METRICS)
                    for side, metrics in value.get("fingers", {}).items()
                    if side in {"left", "right"}
                }
            call.update(result=result, elapsed_s=payload.get("elapsed_s"))
    return {"schema_version": 1, "calls": list(calls.values())}


def export_development(output_dir: str | Path) -> dict[str, str]:
    """Freeze sensor bytes, measured actions and visible call feedback once.

    Only the persisted state manifest, its whitelisted sensor artifacts and
    tool journal are read. Evaluator/native/outcome files are never inputs.
    The ZIP contains the actual referenced bytes, not mutable external paths.
    """
    root = Path(output_dir).resolve()
    destination = root / "maker-inputs"
    if destination.exists():
        raise FileExistsError(
            "Development evidence already exported; never overwrite maker inputs"
        )
    records = json.loads(_safe_file(root, Path("states.json")).read_text()).get(
        "steps", []
    )
    if not records:
        raise ValueError("No recorded sensor frames to export")
    if [record["step_idx"] for record in records] != list(range(len(records))):
        raise ValueError("Expected the complete ordered EnvState trace")
    feedback = _feedback(root)
    actions, command_step = [], None
    with tempfile.TemporaryDirectory(prefix=".maker-inputs-", dir=root) as temporary:
        temporary = Path(temporary)
        with ZipFile(temporary / "sensors.zip", "w") as archive:

            def add(name, data):
                info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                archive.writestr(info, data)

            for record in records:
                step = record["step_idx"]
                artifacts = set(record["artifacts"])
                if "sensor_frame.json" not in artifacts:
                    raise ValueError(f"Step {step} has no sensor frame manifest")
                frame_path = Path("sensor_frame.json") / f"{step:02d}.json"
                frame = json.loads(_safe_file(root, frame_path).read_text())
                if frame.get("step") != step:
                    raise ValueError("Sensor frame does not match its recorded step")

                def select(value, schema, prefix):
                    output = {}
                    for key, child_schema in schema.items():
                        if key not in value:
                            continue
                        child, field = value[key], f"{prefix}_{key}"
                        if child_schema is not None:
                            output[key] = select(child, child_schema, field)
                        elif isinstance(child, dict):
                            name = child.get("artifact")
                            if (
                                set(child) != {"artifact"}
                                or name not in artifacts
                                or name not in (field + ".png", field + ".npz")
                            ):
                                raise ValueError(
                                    f"Invalid sensor artifact reference: {field}"
                                )
                            path = _safe_file(
                                root, Path(name) / f"{step:02d}{Path(name).suffix}"
                            )
                            add(f"frames/{step:04d}/{name}", path.read_bytes())
                            output[key] = {"artifact": name}
                        else:
                            output[key] = _scrub(child)
                    return output

                filtered = select(frame, FRAME, "sensor")
                add(
                    f"frames/{step:04d}/sensor_frame.json",
                    json.dumps(filtered, allow_nan=False).encode(),
                )
                command = record.get("command")
                if command is not None:
                    command_step = step if command.get("action") == "move_eef" else None
                if command_step is not None:
                    action = {
                        "step": step,
                        "command_step": command_step,
                        "state": _pick(record["state"], STATE),
                        "receipt": _receipt(record.get("result") or {}),
                    }
                    if command is not None:
                        action["command"] = _pick(command, {"action", "poses"})
                    actions.append(action)
            add(
                "manifest.json",
                json.dumps(
                    {"schema_version": 1, "steps": list(range(len(records)))}
                ).encode(),
            )
        (temporary / "actions.json").write_text(
            json.dumps(
                {"schema_version": 1, "steps": actions}, allow_nan=False, indent=2
            )
        )
        (temporary / "feedback.json").write_text(
            json.dumps(feedback, allow_nan=False, indent=2)
        )
        temporary.rename(destination)
    return {
        "sensors": str(destination / "sensors.zip"),
        "actions": str(destination / "actions.json"),
        "feedback": str(destination / "feedback.json"),
    }
