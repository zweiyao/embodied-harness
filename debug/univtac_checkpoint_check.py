# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Development-only checkpoint qualification; never changes the live adapter.

Requires an already charged infrastructure reservation. Run capture and restore
in separate processes, with the same development task/seed. All evidence is
private evaluator data, not maker input. No recorded image replaces a live image.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
import sys
import time
import traceback
import uuid
from pathlib import Path

import numpy as np

from debug.univtac_checkpoint_compare import (
    compare_branches,
    file_hash,
    protocol,
)

TASK_FIELDS = (
    "step_count",
    "take_action_cnt",
    "eval_success",
    "plan_success",
    "in_pre_move",
    "last_qpos",
    "keep_still_times",
    "last_render",
    "atom_tag",
    "atom_id",
    "episode_length_buf",
)
ACTOR_FIELDS = ("next_status", "next_pts", "next_mat")
JOINT_TARGET_FIELDS = ("joint_pos_target", "joint_vel_target", "joint_effort_target")
MARKER_FIELDS = (
    "init_surface_vertices",
    "init_surface_vertices_camera",
    "reference_surface_vertices_camera",
    "marker_grid",
    "marker_surf_idx",
    "marker_weight",
    "constrain_pts",
)


def pack(value):
    """Encode only explicit scalar/container/numeric state, without pickle."""
    if hasattr(value, "detach"):
        return {
            "_kind": "tensor",
            "dtype": str(value.dtype).split(".")[-1],
            "device": str(value.device),
            "data": value.detach().cpu().tolist(),
        }
    if isinstance(value, np.ndarray):
        return {"_kind": "array", "dtype": str(value.dtype), "data": value.tolist()}
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, tuple):
        return {"_kind": "tuple", "data": [pack(v) for v in value]}
    if isinstance(value, list):
        return [pack(v) for v in value]
    if isinstance(value, dict):
        return {str(k): pack(v) for k, v in value.items()}
    if value is None or type(value) in (bool, int, float, str):
        return value
    raise TypeError(f"Unsupported checkpoint state: {type(value).__name__}")


def unpack(value):
    if isinstance(value, list):
        return [unpack(v) for v in value]
    if not isinstance(value, dict):
        return value
    kind = value.get("_kind")
    if kind == "array":
        return np.asarray(value["data"], dtype=value["dtype"])
    if kind == "tensor":
        import torch

        return torch.tensor(
            value["data"], dtype=getattr(torch, value["dtype"]), device=value["device"]
        )
    if kind == "tuple":
        return tuple(unpack(v) for v in value["data"])
    return {k: unpack(v) for k, v in value.items()}


def write_json(path, value):
    from rpent.evaluation.result import write_json_atomic

    write_json_atomic(path, value)


def read_verified(root):
    """Reject missing, changed or escaping files before touching simulator state."""
    root = Path(root).resolve()
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest.get("schema_version") not in (1, 2):
        raise ValueError("Unsupported checkpoint schema")
    if not {"state.json", "scene.json", "baseline.json"} <= manifest["files"].keys():
        raise ValueError("Incomplete checkpoint manifest")
    for relative, expected in manifest["files"].items():
        path = (root / relative).resolve()
        if path == root or root not in path.parents:
            raise ValueError("Checkpoint path escapes its directory")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Checkpoint file changed: {relative}")
    return manifest


def differences(expected, actual, prefix=""):
    """Report strict differences; numeric deltas are diagnostic, not tolerances."""
    from robots.univtac.pilot import digest

    if digest(expected) == digest(actual):
        return []
    if isinstance(expected, dict) and isinstance(actual, dict):
        result = []
        for key in sorted(expected.keys() | actual.keys()):
            path = f"{prefix}/{key}"
            if key not in expected or key not in actual:
                result.append({"path": path, "missing": True})
            else:
                result.extend(differences(expected[key], actual[key], path))
        return result
    item = {"path": prefix, "exact_match": False}
    if isinstance(expected, list) and isinstance(actual, list):
        try:
            a, b = np.asarray(expected, dtype=float), np.asarray(actual, dtype=float)
            if a.shape == b.shape and a.size:
                item["max_abs_difference"] = float(np.max(np.abs(a - b)))
        except (TypeError, ValueError):
            pass
    return [item]


def fields(obj, names):
    return {name: getattr(obj, name) for name in names if hasattr(obj, name)}


def commanded_joint_targets(task):
    return {
        name: getattr(task._robot_manager.robot.data, name).clone()
        for name in JOINT_TARGET_FIELDS
    }


def runtime_state(backend):
    import torch

    task = backend.task
    return {
        "physx": task.scene.get_state(),
        "joint_targets": commanded_joint_targets(task),
        "task": fields(task, TASK_FIELDS),
        "actors": {
            name: fields(actor, ACTOR_FIELDS)
            for name, actor in task._actor_manager.actors.items()
        },
        "markers": {
            name: fields(
                sensor.sensor.marker_motion_simulator.marker_motion_sim, MARKER_FIELDS
            )
            for name, sensor in task._tactile_manager.tactiles.items()
        },
        "references": backend.references,
        "physics_start": backend.physics_start,
        "rng": {
            "task": task.rng.bit_generator.state,
            "numpy": np.random.get_state(),
            "python": random.getstate(),
            "torch": torch.get_rng_state(),
            "cuda": torch.cuda.get_rng_state_all(),
        },
    }


def measure(backend, *, refresh=False, archive_root=None):
    from robots.univtac.backend import save_native_frame
    from robots.univtac.pilot import digest

    if refresh:
        backend.observation()
    task = backend.task
    if not task.uipc_sim.world.dump():
        raise RuntimeError("Official UIPC world.dump returned false during comparison")
    frame = task.uipc_sim.world.frame()
    source = Path(task.uipc_sim.cfg.workspace) / "dump"
    archive = (
        archive_root or backend.output_dir / "checkpoint-measurements"
    ) / uuid.uuid4().hex
    archive.mkdir(parents=True, exist_ok=False)
    dump_hashes = {}
    for path in source.rglob("*"):
        if path.is_file() and (
            path.name.endswith(f".{frame}") or path.name.endswith(f".{frame}.json")
        ):
            relative = path.relative_to(source)
            target = archive / "dump" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            dump_hashes[str(relative)] = hashlib.sha256(path.read_bytes()).hexdigest()
    if len(dump_hashes) != 9:
        raise RuntimeError("Missing pinned UIPC state during live comparison")
    native = task._get_observations()
    save_native_frame(archive / "native.npz", native)
    original_run_dir = backend.run_dir
    try:
        # _scene_components writes gel evidence: retain the reset artifact and
        # give every diagnostic measurement its own immutable copy.
        backend.run_dir = archive
        scene = backend._scene_components(native)
    finally:
        backend.run_dir = original_run_dir
    result = {
        # Recompute from live state, never use the cached scene fingerprint.
        "scene": scene,
        "physx": pack(task.scene.get_state()),
        "joint_targets": pack(commanded_joint_targets(task)),
        "uipc_dump_sha256": dump_hashes,
        "uipc_frame": frame,
        "native": {
            "path": str(archive / "native.npz"),
            "sha256": file_hash(archive / "native.npz"),
        },
        "surface_vertices_w": np.array(
            task.uipc_sim.sio.simplicial_surface(2).positions().view(), copy=True
        )
        .reshape(-1, 3)
        .tolist(),
        "runtime_exact": {
            key: digest(pack(value))
            for key, value in runtime_state(backend).items()
            if key not in ("physx", "joint_targets")
        },
    }
    write_json(archive / "measurements.json", result)
    return result


def stationary_samples(backend, archive_root=None):
    """Identical live render calls on capture and restored branches; no stepping."""
    p = protocol()
    for _ in range(p["render_warmup_calls"]):
        backend.observation()
    return [
        measure(backend, refresh=True, archive_root=archive_root)
        for _ in range(p["stationary_samples"])
    ]


def short_branch(backend, actions, archive_root=None):
    records = []
    for action in actions:
        _, _, ended, _, receipt = backend.step(action)
        records.append(
            {"receipt": receipt, "scene": measure(backend, archive_root=archive_root)}
        )
        if ended or not receipt["exec_success"]:
            raise RuntimeError("Short checkpoint branch stopped before all commands")
    return records


def capture(backend, root, attempt_id):
    from uipc.core import SceneFactory, SceneSnapshot

    root.mkdir(parents=True, exist_ok=False)
    task = backend.task
    archive = root / "measurements"
    anchor = measure(backend, archive_root=archive)
    state = runtime_state(backend)
    if not task.uipc_sim.world.dump():
        raise RuntimeError("Official UIPC world.dump returned false")
    frame = task.uipc_sim.world.frame()
    source = Path(task.uipc_sim.cfg.workspace) / "dump"
    files = [
        path
        for path in source.rglob("*")
        if path.is_file()
        and (path.name.endswith(f".{frame}") or path.name.endswith(f".{frame}.json"))
    ]
    if len(files) != 9:
        raise RuntimeError(f"Expected 9 pinned UIPC dump files, found {len(files)}")
    for path in files:
        destination = root / "dump" / path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    write_json(root / "state.json", pack(state))
    write_json(
        root / "scene.json", SceneFactory().to_json(SceneSnapshot(task.uipc_sim.scene))
    )
    stationary = stationary_samples(backend, archive)
    from robots.univtac.observations import sensor_observation

    # Actual observed hand pose, followed by a fixed 0.2 mm out-and-back and hold.
    observed = sensor_observation(
        task._get_observations(),
        backend.controller.observer.observe_state(task),
        backend.references,
        control_step=task.take_action_cnt,
        physics_step=task.step_count - backend.physics_start,
    )["state"]
    start = np.r_[observed["eef_pose_wxyz"], observed["gripper"]]
    lifted = start.copy()
    lifted[2] += protocol()["branch_offset_m"]
    actions = [lifted.tolist(), start.tolist(), start.tolist()]
    task._rpent_archive = root / "baseline-native-frames"
    baseline = {
        "anchor": anchor,
        "stationary": stationary,
        "actions": actions,
        "steps": short_branch(backend, actions, archive),
    }
    write_json(root / "baseline.json", baseline)
    write_json(root / "protocol.json", protocol())
    manifest = {
        "schema_version": 2,
        "task": backend.task_name,
        "seed": backend.seed,
        "frame": frame,
        "capture_attempt_id": attempt_id,
        "source_sha256": {
            name: file_hash(Path(__file__).with_name(name))
            for name in ("univtac_checkpoint_check.py", "univtac_checkpoint_compare.py")
        },
        "files": {
            str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*"))
            if p.is_file()
        },
    }
    write_json(root / "manifest.json", manifest)
    return baseline


def restore_physx(task, state):
    """Restore measured state and the independently commanded joint targets."""
    import torch

    robot = task._robot_manager.robot
    targets = state.get("joint_targets")
    if not isinstance(targets, dict) or set(targets) != set(JOINT_TARGET_FIELDS):
        raise ValueError("Checkpoint lacks complete commanded joint targets")
    if any(
        not torch.is_tensor(value) or value.shape != robot.data.joint_pos.shape
        for value in targets.values()
    ):
        raise ValueError("Checkpoint joint target tensors have incompatible shapes")
    # TacEx's None default becomes slice(None), which the pinned PhysX tensor
    # frontend cannot convert to indices. Supply all environment IDs explicitly.
    env_ids = torch.arange(task.num_envs, device=task.device)
    task.scene.reset_to(state["physx"], env_ids=env_ids)
    # reset_to substitutes measured positions/velocities as targets. Restore the
    # original commands instead; Isaac's setters only fill buffers until flushed.
    robot.set_joint_position_target(targets["joint_pos_target"], env_ids=env_ids)
    robot.set_joint_velocity_target(targets["joint_vel_target"], env_ids=env_ids)
    robot.set_joint_effort_target(targets["joint_effort_target"], env_ids=env_ids)
    robot.write_data_to_sim()


def restore(backend, root):
    import torch
    from uipc.core import SceneFactory, SceneIO, SceneSnapshot

    manifest = read_verified(root)
    if manifest["schema_version"] != 2:
        raise ValueError(
            "Schema 1 checkpoint is audit-only: commanded joint targets were not saved"
        )
    if (
        "protocol.json" not in manifest["files"]
        or json.loads((root / "protocol.json").read_text()) != protocol()
    ):
        raise ValueError(
            "Checkpoint lacks the exact preregistered qualification protocol"
        )
    if manifest.get("source_sha256") != {
        name: file_hash(Path(__file__).with_name(name))
        for name in ("univtac_checkpoint_check.py", "univtac_checkpoint_compare.py")
    }:
        raise ValueError("Qualification source changed since capture")
    if (manifest["task"], manifest["seed"]) != (backend.task_name, backend.seed):
        raise ValueError("Checkpoint task/seed differs from reservation")
    state = unpack(json.loads((root / "state.json").read_text()))
    task = backend.task
    restore_physx(task, state)
    # PhysX GPU setters require this before reading updated link transforms.
    # This refreshes kinematics without advancing a physics step.
    task._robot_manager.robot._physics_sim_view.update_articulations_kinematic()
    factory = SceneFactory()
    saved = factory.from_json(json.loads((root / "scene.json").read_text()))
    commit = factory.commit_to_json(saved - SceneSnapshot(task.uipc_sim.scene))
    SceneIO(task.uipc_sim.scene).update_from_json(commit)
    for relative in manifest["files"]:
        if relative.startswith("dump/"):
            destination = Path(task.uipc_sim.cfg.workspace) / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / relative, destination)
    if not task.uipc_sim.world.recover(manifest["frame"]):
        raise RuntimeError("Official UIPC world.recover returned false")
    task.uipc_sim.world.retrieve()
    for name, value in state["task"].items():
        setattr(task, name, value)
    for name, values in state["actors"].items():
        for key, value in values.items():
            setattr(task._actor_manager.actors[name], key, value)
    for name, values in state["markers"].items():
        marker = task._tactile_manager.tactiles[
            name
        ].sensor.marker_motion_simulator.marker_motion_sim
        for key, value in values.items():
            setattr(marker, key, value)
    backend.references, backend.physics_start = (
        state["references"],
        state["physics_start"],
    )
    backend.attempted_commands, backend.last_receipt = 0, {}
    task.rng.bit_generator.state = state["rng"]["task"]
    np.random.set_state(state["rng"]["numpy"])
    random.setstate(state["rng"]["python"])
    torch.set_rng_state(state["rng"]["torch"])
    torch.cuda.set_rng_state_all(state["rng"]["cuda"])


def validate_reservation(pilot, attempt_id, phase, output):
    """Accept only an unfinished, precharged development infrastructure cell."""
    from robots.univtac.pilot import digest

    def read(events):
        p = protocol()
        if pilot.manifest.get("checkpoint_qualification") != {
            "protocol_sha256": digest(p),
            "cells": p["cells"],
        }:
            raise ValueError(
                "Reservation requires the exact registered qualification protocol"
            )
        attempt = pilot._attempt(events, attempt_id)
        cell = pilot._cell(attempt["cell"])
        expected = p["cells"][0 if phase == "capture" else 1]
        if (
            cell["id"] != expected
            or cell["stage"] != "infrastructure"
            or cell["model"] != "script"
            or cell["condition"] != "C"
            or cell["task"] != "insert_hole"
            or cell["seed"] != 2
            or attempt_id in pilot._finished(events)
            or Path(attempt["session_id"]).resolve() != output
        ):
            raise ValueError("Not the required unfinished infrastructure reservation")
        return cell, None

    return pilot._transaction(read)


def qualification_report(
    output, snapshot, attempt_id, phase, checks, capture_evidence=None
):
    from robots.univtac.pilot import digest

    manifest = read_verified(snapshot)
    branch = (
        snapshot / "baseline.json"
        if phase == "capture"
        else output / "restored-measurements.json"
    )
    report = {
        "passed": checks["passed"],
        "protocol_sha256": digest(protocol()),
        "snapshot_sha256": digest(manifest),
        "attempt_id": attempt_id,
        "role": phase,
        "cell_id": protocol()["cells"][0 if phase == "capture" else 1],
        "checks": checks["checks"],
        "capture_evidence": capture_evidence,
        "capture_report_sha256": capture_evidence["sha256"]
        if capture_evidence
        else None,
        "snapshot_manifest": {
            "path": str(snapshot / "manifest.json"),
            "sha256": file_hash(snapshot / "manifest.json"),
        },
        "branch_evidence": {"path": str(branch), "sha256": file_hash(branch)},
    }
    path = output / "report.json"
    if path.exists():
        raise FileExistsError("Qualification report is immutable")
    write_json(path, report)
    return {"path": str(path), "sha256": file_hash(path)}


def capture_report(pilot, snapshot):
    """Require the completed capture's immutable, ledger-bound evidence."""
    from robots.univtac.pilot import digest

    manifest = read_verified(snapshot)
    finished = pilot._transaction(
        lambda events: (
            pilot._finished(events).get(manifest["capture_attempt_id"]),
            None,
        )
    )
    if finished is None:
        raise ValueError("Capture attempt has not finished")
    ref = finished["outcome"]["checkpoint_evidence"]
    if file_hash(ref["path"]) != ref["sha256"]:
        raise ValueError("Capture report changed")
    report = json.loads(Path(ref["path"]).read_text())
    if (
        report["passed"] is not True
        or report["role"] != "capture"
        or report["attempt_id"] != manifest["capture_attempt_id"]
        or report["cell_id"] != protocol()["cells"][0]
        or report["protocol_sha256"] != digest(protocol())
        or report["snapshot_sha256"] != digest(manifest)
    ):
        raise ValueError("Capture qualification does not match this snapshot/protocol")
    return ref


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--pilot-root", required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--phase", choices=("capture", "restore"), required=True)
    parser.add_argument("--snapshot-root", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    from robots.univtac.backend import UniVTACBackend
    from robots.univtac.pilot import Pilot

    output, snapshot = (
        Path(args.output_dir).resolve(),
        Path(args.snapshot_root).resolve(),
    )
    pilot = Pilot(args.pilot_root)
    cell = validate_reservation(pilot, args.attempt_id, args.phase, output)
    output.mkdir(parents=True, exist_ok=True)
    marker = output / "checkpoint-started.json"
    with marker.open("x") as stream:
        json.dump({"attempt_id": args.attempt_id, "phase": args.phase}, stream)
    result = {
        "checkpoint_validation_passed": False,
        "official_success": None,
        "native_success": None,
        "phase": args.phase,
        "initializations": 0,
        "status": "running",
        "controller_changed": False,
        "renderer_cache_restored": False,
        "evidence": str(output / "checkpoint-result.json"),
    }
    from robots.univtac.pilot import digest

    result["protocol_sha256"] = digest(protocol())
    write_json(output / "protocol.json", protocol())
    write_json(output / "checkpoint-result.json", result)
    backend, started = None, time.monotonic()
    try:
        backend = UniVTACBackend(
            root=args.root, output_dir=output / "native", seed=cell["seed"]
        )
        result["initializations"] = (
            1  # Includes initialization failures; already charged.
        )
        write_json(output / "checkpoint-result.json", result)
        backend.reset()
        pilot.record_scene(args.attempt_id, backend.evaluator_state()["scene"])
        result["status"] = "initialized"
        write_json(output / "checkpoint-result.json", result)
        if args.phase == "capture":
            baseline = capture(backend, snapshot, args.attempt_id)
            checks = compare_branches(baseline, baseline, snapshot, snapshot)
            parent_evidence = None
        else:
            read_verified(snapshot)
            parent_evidence = capture_report(pilot, snapshot)
            baseline = json.loads((snapshot / "baseline.json").read_text())
            restore(backend, snapshot)
            backend.task._rpent_archive = output / "restored-native-frames"
            anchor = measure(backend)
            actual = {
                "anchor": anchor,
                "stationary": stationary_samples(backend),
                "actions": baseline["actions"],
                "steps": short_branch(backend, baseline["actions"]),
            }
            write_json(output / "restored-measurements.json", actual)
            checks = compare_branches(baseline, actual, snapshot, output)
        result["checkpoint_evidence"] = qualification_report(
            output, snapshot, args.attempt_id, args.phase, checks, parent_evidence
        )
        result["checkpoint_validation_passed"] = checks["passed"]
        result["status"] = (
            "passed" if result["checkpoint_validation_passed"] else "failed"
        )
        result["termination_reason"] = (
            "completed" if result["checkpoint_validation_passed"] else "failed"
        )
        result["official_success"] = backend.evaluator_state()["official_success"]
        result["native_success"] = result["official_success"]
    except BaseException as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["termination_reason"] = (
            "aborted"
            if isinstance(exc, KeyboardInterrupt)
            else ("setup_failure" if result["status"] == "running" else "failed")
        )
        result["status"] = "failed"
        details = traceback.format_exc()
        (output / "checkpoint-error.txt").write_text(details)
        sys.stderr.write(details)
        sys.stderr.flush()
        if backend is not None and backend.task is not None:
            try:
                result["official_success"] = backend.evaluator_state()[
                    "official_success"
                ]
                result["native_success"] = result["official_success"]
            except Exception as evaluator_error:
                result["evaluator_error"] = str(evaluator_error)
    finally:
        result["elapsed_s"] = time.monotonic() - started
        # Persist qualification and charge outcome before Kit.close can exit Python.
        write_json(output / "checkpoint-result.json", result)
        try:
            pilot.finish_episode(args.attempt_id, result)
            print(json.dumps(result), flush=True)
        finally:
            if backend is not None:
                backend.close()
    return 0 if result["checkpoint_validation_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
