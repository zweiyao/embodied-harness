# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Specific, predeclared comparator for the two GSmini checkpoint diagnostics."""

from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path

import numpy as np

PROTOCOL_FILE = Path(__file__).with_name("univtac_checkpoint_protocol_v1.json")
RGB_KEYS = (
    "observation/head/rgb",
    "observation/wrist/rgb",
    "tactile/left_tactile/rgb",
    "tactile/right_tactile/rgb",
    "tactile/left_tactile/rgb_marker",
    "tactile/right_tactile/rgb_marker",
)
DEPTH_KEYS = (
    "observation/head/depth",
    "observation/wrist/depth",
    "tactile/left_tactile/depth",
    "tactile/right_tactile/depth",
)
MARKER_KEYS = ("tactile/left_tactile/marker", "tactile/right_tactile/marker")


def protocol():
    return json.loads(PROTOCOL_FILE.read_text())


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def add(checks, name, passed, **metrics):
    checks.append({"name": name, "passed": bool(passed), **metrics})


def exact(checks, name, a, b):
    from robots.univtac.pilot import digest

    add(checks, name, digest(a) == digest(b))


def numeric(value):
    if isinstance(value, dict) and value.get("_kind") in ("tensor", "array"):
        value = value["data"]
    result = np.asarray(value, dtype=float)
    if not np.isfinite(result).all():
        raise ValueError("Nonfinite state value")
    return result


def bounded(checks, name, a, b, limit, *, vectors=False):
    a, b = numeric(a), numeric(b)
    if a.shape != b.shape or not a.size:
        raise ValueError(f"Missing/incompatible state shape: {name}")
    error = np.linalg.norm(a - b, axis=-1) if vectors else np.abs(a - b)
    maximum = float(np.max(error))
    add(checks, name, maximum <= limit, maximum=maximum, limit=float(limit))


def pose(checks, name, a, b, p, initial):
    a, b = numeric(a), numeric(b)
    if a.shape != (7,) or b.shape != (7,):
        raise ValueError(f"Pose must contain xyz+wxyz: {name}")
    epsilon = p["initial_float32_epsilon_multiplier"] * np.finfo(np.float32).eps
    position_limit = (
        epsilon * max(1.0, float(np.linalg.norm(a[:3])))
        if initial
        else p["position_limit_m"]
    )
    bounded(checks, name + "/position", a[:3], b[:3], position_limit, vectors=True)
    q, r = a[3:], b[3:]
    if min(np.linalg.norm(q), np.linalg.norm(r)) < 1e-12:
        raise ValueError("Zero quaternion")
    q, r = q / np.linalg.norm(q), r / np.linalg.norm(r)
    if np.dot(q, r) < 0:
        r = -r
    angle = float(4 * np.arctan2(np.linalg.norm(q - r), np.linalg.norm(q + r)))
    add(
        checks,
        name + "/rotation",
        True,
        maximum_rad=angle,
        enforced=False,
        basis="Actual world surface displacement is checked separately",
    )


def _tiles(a, b, size):
    values = [float(np.sqrt(np.mean((a - b) ** 2)))]
    for row in range(0, a.shape[0], size):
        for col in range(0, a.shape[1], size):
            d = (
                a[row : row + size, col : col + size]
                - b[row : row + size, col : col + size]
            )
            values.append(float(np.sqrt(np.mean(d**2))))
    return np.asarray(values)


def rgb_check(checks, name, a, b, static, p):
    a, b = a.astype(float), b.astype(float)
    if not all(
        np.isfinite(x).all() and x.min() >= 0 and x.max() <= 255 for x in (a, b)
    ):
        raise ValueError(f"Invalid RGB encoding/range: {name}")
    size = p["rgb_tile_size_px"]
    envelope = np.max(
        [
            _tiles(x.astype(float), y.astype(float), size)
            for x, y in itertools.combinations(static, 2)
        ],
        axis=0,
    )
    limits = np.minimum(
        p["rgb_full_scale"] * p["rgb_rmse_fraction_cap"],
        envelope + p["rgb_static_envelope_margin_lsb"],
    )
    error = _tiles(a, b, size)
    add(
        checks,
        name,
        np.all(error <= limits),
        global_rmse=float(error[0]),
        max_tile_rmse=float(error[1:].max()),
        rejected_tiles=int(np.sum(error[1:] > limits[1:])),
        stationary_max_rmse=float(envelope.max()),
        maximum_allowed=float(limits.max()),
    )


def depth_check(checks, name, a, b, p):
    """Keep all interior pixels and require two-way matching on 1px edges."""
    scale = 0.001 if name.startswith("tactile/") else 1.0
    a, b = np.squeeze(a).astype(float) * scale, np.squeeze(b).astype(float) * scale
    if a.ndim != 2 or a.shape != b.shape:
        raise ValueError("Depth must be matching 2D frames")
    if any((x[np.isfinite(x)] < 0).any() for x in (a, b)):
        raise ValueError("Negative finite depth")
    va, vb = np.isfinite(a), np.isfinite(b)
    if not va.any() or not vb.any():
        raise ValueError("No finite depth")
    edge = np.zeros(a.shape, dtype=bool)
    for axis in (0, 1):
        first, second = [slice(None)] * 2, [slice(None)] * 2
        first[axis], second[axis] = slice(None, -1), slice(1, None)
        first, second = tuple(first), tuple(second)
        x, y = a[first], a[second]
        finite = va[first] & va[second]
        delta = np.zeros(x.shape)
        np.subtract(x, y, out=delta, where=finite)
        jump = np.maximum(
            p["depth_edge_absolute_jump_m"],
            p["depth_edge_relative_jump"]
            * np.minimum(
                np.where(np.isfinite(x), x, np.inf), np.where(np.isfinite(y), y, np.inf)
            ),
        )
        boundary = (va[first] != va[second]) | (finite & (np.abs(delta) > jump))
        edge[first] |= boundary
        edge[second] |= boundary
    padded = np.pad(edge, 1)
    edge = np.logical_or.reduce(
        [
            padded[i : i + a.shape[0], j : j + a.shape[1]]
            for i in range(3)
            for j in range(3)
        ]
    )
    interior = va & vb & ~edge
    if not interior.any():
        raise ValueError("Depth has no comparable interior")
    interior_error = float(np.max(np.abs(a[interior] - b[interior])))
    limit = p["position_limit_m"]
    unmatched = []
    for source, target, valid in ((a, b, va), (b, a, vb)):
        padded = np.pad(target, 1, constant_values=np.inf)
        nearest = np.full(a.shape, np.inf)
        for i in range(3):
            for j in range(3):
                neighbor = padded[i : i + a.shape[0], j : j + a.shape[1]]
                pair = valid & np.isfinite(neighbor)
                delta = np.full(a.shape, np.inf)
                np.subtract(source, neighbor, out=delta, where=pair)
                nearest = np.minimum(nearest, np.abs(delta))
        unmatched.append(int(np.sum(valid & edge & (nearest > limit))))
    invalid_interior = int(np.sum((va != vb) & ~edge))
    add(
        checks,
        name,
        interior_error <= limit and not any(unmatched) and not invalid_interior,
        interior_max_m=interior_error,
        limit_m=limit,
        edge_pixels=int(edge.sum()),
        interior_pixels=int(interior.sum()),
        unmatched_edge_forward=unmatched[0],
        unmatched_edge_reverse=unmatched[1],
        changed_validity_outside_edge=invalid_interior,
    )


def native(record, root, p):
    ref = record["native"]
    path, root = Path(ref["path"]).resolve(), Path(root).resolve()
    if root not in path.parents or file_hash(path) != ref["sha256"]:
        raise ValueError(
            "Native frame missing, changed or outside its evidence directory"
        )
    with np.load(path, allow_pickle=False) as archive:
        arrays = {key: archive[key] for key in RGB_KEYS + DEPTH_KEYS + MARKER_KEYS}
    for key, value in arrays.items():
        width, height = (
            p["tactile_resolution_wh"]
            if key.startswith("tactile/")
            else p["rgbd_resolution_wh"]
        )
        shape = (
            (2, 64, 2)
            if key in MARKER_KEYS
            else (height, width, 3)
            if key in RGB_KEYS
            else (height, width)
        )
        if value.squeeze().shape != shape:
            raise ValueError(f"Unexpected sensor resolution: {key}")
        dtype = (
            np.uint8
            if key in RGB_KEYS
            and (not key.startswith("tactile/") or key.endswith("rgb_marker"))
            else np.float32
        )
        if value.dtype != dtype:
            raise ValueError(f"Unexpected sensor dtype: {key}")
    return arrays


def state_checks(checks, label, expected, actual, p, *, initial, anchor=False):
    a, b = expected["scene"], actual["scene"]
    for name in ("model", "physics", "assets", "rng"):
        exact(checks, label + "/" + name, a[name], b[name])
    for key in ("task", "actors", "markers", "references", "physics_start", "rng"):
        if initial:
            exact(
                checks,
                label + "/runtime/" + key,
                expected["runtime_exact"][key],
                actual["runtime_exact"][key],
            )
    exact(checks, label + "/frame", expected["uipc_frame"], actual["uipc_frame"])
    for side in () if anchor else ("head", "wrist"):
        x, y = (
            a["sensors"]["camera_calibration"][side],
            b["sensors"]["camera_calibration"][side],
        )
        exact(
            checks,
            label + "/calibration/" + side,
            {
                k: x[k]
                for k in (
                    "intrinsics",
                    "width",
                    "height",
                    "camera_convention",
                    "depth_units",
                )
            },
            {
                k: y[k]
                for k in (
                    "intrinsics",
                    "width",
                    "height",
                    "camera_convention",
                    "depth_units",
                )
            },
        )
        pose(
            checks,
            label + "/camera/" + side,
            x["position_w"] + x["quaternion_wxyz"],
            y["position_w"] + y["quaternion_wxyz"],
            p,
            initial,
        )
    x, y = (
        expected["physx"]["articulation"]["robot"],
        actual["physx"]["articulation"]["robot"],
    )
    for field in ("joint_position", "joint_velocity", "root_velocity"):
        if initial or field == "root_velocity":
            exact(checks, label + "/physx/" + field, x[field], y[field])
        else:
            add(
                checks,
                label + "/physx/" + field,
                True,
                enforced=False,
                maximum=float(np.max(np.abs(numeric(x[field]) - numeric(y[field])))),
            )
    pose(
        checks,
        label + "/physx/root",
        numeric(x["root_pose"])[0],
        numeric(y["root_pose"])[0],
        p,
        True,
    )
    for field in ("joint_pos_target", "joint_vel_target", "joint_effort_target"):
        if initial or field != "joint_pos_target":
            exact(
                checks,
                label + "/" + field,
                expected["joint_targets"][field],
                actual["joint_targets"][field],
            )
        else:
            add(
                checks,
                label + "/" + field,
                True,
                enforced=False,
                maximum=float(
                    np.max(
                        np.abs(
                            numeric(expected["joint_targets"][field])
                            - numeric(actual["joint_targets"][field])
                        )
                    )
                ),
            )
    if initial:
        if (
            len(expected["uipc_dump_sha256"]) != 9
            or len(actual["uipc_dump_sha256"]) != 9
        ):
            raise ValueError("Required nine UIPC buffers missing")
        exact(
            checks,
            label + "/uipc_dumps",
            expected["uipc_dump_sha256"],
            actual["uipc_dump_sha256"],
        )
    else:
        keys = expected["uipc_dump_sha256"].keys()
        add(
            checks,
            label + "/uipc_dump_inventory",
            len(keys) == 9 and keys == actual["uipc_dump_sha256"].keys(),
            exact_files=sum(
                expected["uipc_dump_sha256"][k] == actual["uipc_dump_sha256"].get(k)
                for k in keys
            ),
        )
    bounded(
        checks,
        label + "/actual_world_surfaces",
        expected["surface_vertices_w"],
        actual["surface_vertices_w"],
        p["position_limit_m"],
        vectors=True,
    )
    if anchor:
        return
    if (
        a["state"]["actors"].keys() != b["state"]["actors"].keys()
        or not a["state"]["actors"]
    ):
        raise ValueError("Actor inventory changed/missing")
    for name in a["state"]["actors"]:
        pose(
            checks,
            label + "/actor/" + name,
            a["state"]["actors"][name],
            b["state"]["actors"][name],
            p,
            initial,
        )
    for name in ("hand_pose", "tcp_pose", "root_pose_w"):
        x, y = a["state"]["robot"][name], b["state"]["robot"][name]
        pose(
            checks,
            label + "/robot/" + name,
            x["position"] + x["quaternion_wxyz"],
            y["position"] + y["quaternion_wxyz"],
            p,
            initial,
        )
    for side in ("left_tactile", "right_tactile"):
        bounded(
            checks,
            label + "/gel/" + side,
            a["state"]["gel_vertices_w"][side],
            b["state"]["gel_vertices_w"][side],
            p["position_limit_m"],
            vectors=True,
        )


def compare_branches(expected, actual, expected_root, actual_root):
    """Missing evidence fails closed; keep each metric, not a pooled score."""
    p, checks = protocol(), []
    try:
        count = p["stationary_samples"]
        if len(expected["stationary"]) != count or len(actual["stationary"]) != count:
            raise ValueError("Four stationary samples required on both branches")
        if (
            len(expected["steps"]) != p["branch_commands"]
            or len(actual["steps"]) != p["branch_commands"]
        ):
            raise ValueError("Three complete branch commands required")
        exact(checks, "command_inputs", expected["actions"], actual["actions"])
        commands = numeric(expected["actions"])
        if commands.shape != (3, 8) or not np.array_equal(commands[1], commands[2]):
            raise ValueError("Expected fixed out/back/hold command recipe")
        delta = np.zeros(8)
        delta[2] = p["branch_offset_m"]
        if not np.allclose(
            commands[0] - commands[1], delta, rtol=0, atol=4 * np.finfo(float).eps
        ):
            raise ValueError("Command recipe changed")
        state_checks(
            checks,
            "anchor",
            expected["anchor"],
            actual["anchor"],
            p,
            initial=True,
            anchor=True,
        )
        static = [native(r, expected_root, p) for r in expected["stationary"]]
        cap = p["rgb_full_scale"] * p["rgb_rmse_fraction_cap"]
        for key in RGB_KEYS:
            maximum = max(
                float(
                    _tiles(
                        a[key].astype(float),
                        b[key].astype(float),
                        p["rgb_tile_size_px"],
                    ).max()
                )
                for a, b in itertools.combinations(static, 2)
            )
            add(
                checks,
                "capture/static_noise/" + key,
                maximum <= cap,
                maximum_tile_rmse=maximum,
                limit=cap,
            )
        for branch_name, branch in (("capture", expected), ("restored", actual)):
            for index, record in enumerate(branch["stationary"]):
                for field in (
                    "uipc_frame",
                    "uipc_dump_sha256",
                    "physx",
                    "joint_targets",
                ):
                    exact(
                        checks,
                        f"{branch_name}/stationary{index}/unchanged/{field}",
                        branch["anchor"][field],
                        record[field],
                    )
        pairs = list(zip(expected["stationary"], actual["stationary"])) + [
            (a["scene"], b["scene"]) for a, b in zip(expected["steps"], actual["steps"])
        ]
        for index, (a, b) in enumerate(pairs):
            label = (
                f"stationary{index}" if index < count else f"command{index - count + 1}"
            )
            state_checks(checks, label, a, b, p, initial=index < count)
            aa, bb = native(a, expected_root, p), native(b, actual_root, p)
            for key in aa:
                if aa[key].dtype != bb[key].dtype or aa[key].shape != bb[key].shape:
                    raise ValueError(f"Sensor dtype/shape changed: {key}")
            for key in RGB_KEYS:
                rgb_check(
                    checks,
                    label + "/" + key,
                    aa[key],
                    bb[key],
                    [s[key] for s in static],
                    p,
                )
            for key in DEPTH_KEYS:
                start = len(checks)
                depth_check(checks, key, aa[key], bb[key], p)
                checks[start]["name"] = label + "/" + key
            for key in MARKER_KEYS:
                # Restored RNG and reference rows must preserve exact correspondence;
                # unlike runtime tools this qualification must not hide lost markers.
                exact(
                    checks,
                    label + "/" + key + "/reference",
                    aa[key][0].tolist(),
                    bb[key][0].tolist(),
                )
                bounded(
                    checks,
                    label + "/" + key + "/current",
                    aa[key][1],
                    bb[key][1],
                    p["marker_limit_px"],
                    vectors=True,
                )
        for index, (a, b) in enumerate(zip(expected["steps"], actual["steps"]), 1):
            fields = (
                "exec_success",
                "native_action_delta",
                "physics_step_delta",
                "attempted_commands",
            )
            exact(
                checks,
                f"command{index}/receipt",
                {k: a["receipt"][k] for k in fields},
                {k: b["receipt"][k] for k in fields},
            )
    except (KeyError, ValueError, OSError, TypeError) as exc:
        add(checks, "required_evidence", False, error=f"{type(exc).__name__}: {exc}")
    return {
        "protocol_id": p["id"],
        "passed": bool(checks) and all(c["passed"] for c in checks),
        "checks": checks,
    }
