# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""CPU counterexamples for the preregistered checkpoint qualification."""

import copy
import json
from types import SimpleNamespace

import numpy as np
import pytest

from debug.univtac_checkpoint_check import qualification_report, stationary_samples
from debug.univtac_checkpoint_compare import (
    DEPTH_KEYS,
    MARKER_KEYS,
    RGB_KEYS,
    compare_branches,
    depth_check,
    file_hash,
    protocol,
    rgb_check,
)


def encoded(values):
    return {"_kind": "tensor", "dtype": "float32", "device": "cpu", "data": values}


@pytest.fixture
def branch(tmp_path):
    arrays = {}
    for key in RGB_KEYS + DEPTH_KEYS + MARKER_KEYS:
        tactile = key.startswith("tactile/")
        height, width = (240, 320) if tactile else (270, 480)
        if key in RGB_KEYS:
            arrays[key] = np.full(
                (height, width, 3),
                100,
                dtype=np.float32 if tactile and key.endswith("/rgb") else np.uint8,
            )
        elif key in DEPTH_KEYS:
            arrays[key] = np.full(
                (height, width), 5 if tactile else 1, dtype=np.float32
            )
        else:
            xy = np.stack([np.arange(64), np.arange(64)], axis=-1).astype(np.float32)
            arrays[key] = np.stack([xy, xy])
    path = tmp_path / "native.npz"
    np.savez_compressed(path, **arrays)
    p = protocol()
    pose = [0, 0, 0, 1, 0, 0, 0]
    state = {
        "scene": {
            "model": {
                "benchmark_commit": p["basis"]["native_commit"],
                "task": "insert_hole",
                "sensor": "gsmini",
            },
            "physics": {"dt": 1 / 120},
            "assets": {"robot.usd": "hash"},
            "rng": {"seed": 2},
            "sensors": {
                "camera_calibration": {
                    side: {
                        "intrinsics": np.eye(3).tolist(),
                        "position_w": pose[:3],
                        "quaternion_wxyz": pose[3:],
                        "width": 480,
                        "height": 270,
                        "camera_convention": "ros_optical",
                        "depth_units": "m",
                    }
                    for side in ("head", "wrist")
                }
            },
            "state": {
                "actors": {"prism": pose},
                "robot": {
                    key: {"position": pose[:3], "quaternion_wxyz": pose[3:]}
                    for key in ("hand_pose", "tcp_pose", "root_pose_w")
                },
                "gel_vertices_w": {
                    side: [[0, 0, 0], [0.01, 0.01, 0]]
                    for side in ("left_tactile", "right_tactile")
                },
            },
        },
        "physx": {
            "articulation": {
                "robot": {
                    "joint_position": encoded([[0.0] * 9]),
                    "joint_velocity": encoded([[0.0] * 9]),
                    "root_velocity": encoded([[0.0] * 6]),
                    "root_pose": encoded([pose]),
                }
            }
        },
        "joint_targets": {
            key: encoded([[0.0] * 9])
            for key in ("joint_pos_target", "joint_vel_target", "joint_effort_target")
        },
        "uipc_dump_sha256": {f"buffer{i}": "same" for i in range(9)},
        "uipc_frame": 100,
        "surface_vertices_w": [[0, 0, 0], [0.01, 0.01, 0]],
        "runtime_exact": dict.fromkeys(
            ("task", "actors", "markers", "references", "physics_start", "rng"), "same"
        ),
        "native": {"path": str(path), "sha256": file_hash(path)},
    }
    stationary = [copy.deepcopy(state) for _ in range(4)]
    steps = []
    for i in range(3):
        measured = copy.deepcopy(state)
        measured["uipc_frame"] += 2 * (i + 1)
        steps.append(
            {
                "scene": measured,
                "receipt": {
                    "exec_success": True,
                    "native_action_delta": 1,
                    "physics_step_delta": 2,
                    "attempted_commands": i + 1,
                },
            }
        )
    actions = [
        [0, 0, p["branch_offset_m"], 1, 0, 0, 0, 0.1],
        [0, 0, 0, 1, 0, 0, 0, 0.1],
        [0, 0, 0, 1, 0, 0, 0, 0.1],
    ]
    return {
        "anchor": state,
        "stationary": stationary,
        "steps": steps,
        "actions": actions,
    }


def test_unchanged_complete_branch_passes(branch, tmp_path):
    result = compare_branches(branch, copy.deepcopy(branch), tmp_path, tmp_path)
    assert result["passed"], [c for c in result["checks"] if not c["passed"]]


@pytest.mark.parametrize(
    "changed",
    [
        "joint",
        "target",
        "rng",
        "uipc_missing",
        "geometry",
        "missing_frame",
        "stationary_physics",
    ],
)
def test_small_state_corruption_and_missing_evidence_reject(branch, tmp_path, changed):
    other = copy.deepcopy(branch)
    if changed == "joint":
        other["anchor"]["physx"]["articulation"]["robot"]["joint_velocity"]["data"][0][
            0
        ] = 1e-12
    elif changed == "target":
        other["anchor"]["joint_targets"]["joint_effort_target"]["data"][0][0] = 1e-12
    elif changed == "rng":
        other["anchor"]["runtime_exact"]["rng"] = "different"
    elif changed == "uipc_missing":
        del other["anchor"]["uipc_dump_sha256"]["buffer0"]
    elif changed == "geometry":
        other["steps"][0]["scene"]["surface_vertices_w"][0][0] = (
            protocol()["position_limit_m"] * 1.01
        )
    elif changed == "missing_frame":
        del other["stationary"][0]["native"]
    else:
        other["stationary"][2]["uipc_frame"] += 1
    assert not compare_branches(branch, other, tmp_path, tmp_path)["passed"]


def test_depth_background_and_fixed_one_pixel_contour():
    p = protocol()
    base = np.ones((20, 20))
    base[:, :4] = np.nan
    checks = []
    other = base.copy()
    other[:, :4] = np.inf
    depth_check(checks, "observation/head/depth", base, other, p)
    assert checks[-1]["passed"]
    other[10, 10] = np.nan
    depth_check(checks, "observation/head/depth", base, other, p)
    assert not checks[-1]["passed"]
    assert checks[-1]["changed_validity_outside_edge"] == 1
    base = np.ones((20, 20))
    base[:, 10:] = 2
    shifted = np.ones_like(base)
    shifted[:, 11:] = 2
    depth_check(checks, "observation/head/depth", base, shifted, p)
    assert checks[-1]["passed"]
    shifted[:, 11:13] = 1
    depth_check(checks, "observation/head/depth", base, shifted, p)
    assert not checks[-1]["passed"]
    shifted = base.copy()
    shifted[5, 5] += p["position_limit_m"] * 1.01
    depth_check(checks, "observation/head/depth", base, shifted, p)
    assert not checks[-1]["passed"]


def test_local_rgb_error_cannot_hide_in_global_average():
    base = np.full((270, 480, 3), 100, dtype=np.uint8)
    other = base.copy()
    other[:32, :32] += 10
    checks = []
    rgb_check(checks, "rgb", base, other, [base] * 4, protocol())
    assert checks[-1]["global_rmse"] < 2.55
    assert checks[-1]["rejected_tiles"] == 1
    assert not checks[-1]["passed"]


def test_marker_limit_and_npz_integrity(branch, tmp_path):
    path = tmp_path / "changed.npz"
    with np.load(tmp_path / "native.npz") as data:
        arrays = {key: data[key] for key in data.files}
    arrays[MARKER_KEYS[0]][1, 0, 0] += 0.26
    np.savez_compressed(path, **arrays)
    other = copy.deepcopy(branch)
    other["steps"][0]["scene"]["native"] = {
        "path": str(path),
        "sha256": file_hash(path),
    }
    result = compare_branches(branch, other, tmp_path, tmp_path)
    assert not result["passed"]
    assert any(
        "/marker/current" in c["name"] and not c["passed"] for c in result["checks"]
    )
    other["steps"][0]["scene"]["native"]["sha256"] = "wrong"
    assert not compare_branches(branch, other, tmp_path, tmp_path)["passed"]


def test_render_cadence(monkeypatch):
    import debug.univtac_checkpoint_check as check

    calls = []
    backend = SimpleNamespace(observation=lambda: calls.append("warmup"))
    monkeypatch.setattr(
        check, "measure", lambda backend, **kwargs: calls.append("sample") or kwargs
    )
    stationary_samples(backend)
    assert calls == ["warmup"] * 2 + ["sample"] * 4


def test_produced_reports_pass_freeze_gate_and_reject_changed_native(branch, tmp_path):
    from robots.univtac.pilot import digest
    from robots.univtac.pilot.checkpoint_protocol import verify_qualification

    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    native = snapshot / "native.npz"
    native.write_bytes((tmp_path / "native.npz").read_bytes())
    for measurement in [branch["anchor"], *branch["stationary"]] + [
        step["scene"] for step in branch["steps"]
    ]:
        measurement["native"] = {"path": str(native), "sha256": file_hash(native)}
    for name in ("state.json", "scene.json", "baseline.json", "protocol.json"):
        (snapshot / name).write_text(
            json.dumps(
                protocol()
                if name == "protocol.json"
                else branch
                if name == "baseline.json"
                else {}
            )
        )
    (snapshot / "dump").mkdir()
    for index in range(9):
        (snapshot / "dump" / str(index)).write_bytes(b"fixture UIPC buffer")
    manifest = {
        "schema_version": 2,
        "capture_attempt_id": "reserved",
        "files": {
            str(path.relative_to(snapshot)): file_hash(path)
            for path in snapshot.rglob("*")
            if path.is_file()
        },
    }
    (snapshot / "manifest.json").write_text(json.dumps(manifest))
    checks = compare_branches(branch, branch, snapshot, snapshot)
    assert checks["passed"]
    ref = qualification_report(tmp_path, snapshot, "reserved", "capture", checks)
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["role"] == "capture" and report["cell_id"] == "infra-03"
    assert ref["sha256"] == file_hash(ref["path"])
    assert report["snapshot_manifest"]["sha256"] == file_hash(
        snapshot / "manifest.json"
    )
    assert report["branch_evidence"]["sha256"] == file_hash(snapshot / "baseline.json")
    restored = tmp_path / "restore"
    restored.mkdir()
    (restored / "restored-measurements.json").write_text(json.dumps(branch))
    second = qualification_report(restored, snapshot, "other", "restore", checks, ref)
    restored_report = json.loads((restored / "report.json").read_text())
    assert restored_report["capture_report_sha256"] == ref["sha256"]
    assert restored_report["snapshot_sha256"] == report["snapshot_sha256"]
    assert second["sha256"] == file_hash(second["path"])
    events = [
        {"kind": "reserved", "id": attempt, "cell": cell}
        for attempt, cell in (("reserved", "infra-03"), ("other", "infra-04"))
    ] + [
        {
            "kind": "finished",
            "id": attempt,
            "outcome": {
                "termination_reason": "completed",
                "checkpoint_validation_passed": True,
                "checkpoint_evidence": evidence,
            },
        }
        for attempt, evidence in (("reserved", ref), ("other", second))
    ]
    frozen = {"checkpoint_qualification": {"protocol_sha256": digest(protocol())}}
    verify_qualification(frozen, events)
    with pytest.raises(FileExistsError):
        qualification_report(
            tmp_path, snapshot, "reserved", "capture", {"passed": False, "checks": []}
        )
    native.write_bytes(b"changed after qualification")
    with pytest.raises(ValueError, match="changed|differs"):
        verify_qualification(frozen, events)
