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


def measure(backend, *, refresh=False):
    from robots.univtac.backend import save_native_frame

    if refresh:
        backend.observation()
    task = backend.task
    if not task.uipc_sim.world.dump():
        raise RuntimeError("Official UIPC world.dump returned false during comparison")
    frame = task.uipc_sim.world.frame()
    source = Path(task.uipc_sim.cfg.workspace) / "dump"
    archive = backend.output_dir / "checkpoint-measurements" / uuid.uuid4().hex
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
    }
    write_json(archive / "measurements.json", result)
    return result


def short_branch(backend, actions):
    records = []
    for action in actions:
        _, _, ended, _, receipt = backend.step(action)
        records.append({"receipt": receipt, "scene": measure(backend)})
        if ended or not receipt["exec_success"]:
            raise RuntimeError("Short checkpoint branch stopped before all commands")
    return records


def capture(backend, root):
    from uipc.core import SceneFactory, SceneSnapshot

    root.mkdir(parents=True, exist_ok=False)
    task = backend.task
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
    initial = measure(backend, refresh=True)
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
    lifted[2] += 0.0002
    actions = [lifted.tolist(), start.tolist(), start.tolist()]
    task._rpent_archive = root / "baseline-native-frames"
    baseline = {
        "initial": initial,
        "actions": actions,
        "steps": short_branch(backend, actions),
    }
    write_json(root / "baseline.json", baseline)
    manifest = {
        "schema_version": 2,
        "task": backend.task_name,
        "seed": backend.seed,
        "frame": frame,
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

    def read(events):
        attempt = pilot._attempt(events, attempt_id)
        cell = pilot._cell(attempt["cell"])
        expected = "infra-01" if phase == "capture" else "infra-02"
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
            baseline = capture(backend, snapshot)
        else:
            read_verified(snapshot)
            baseline = json.loads((snapshot / "baseline.json").read_text())
        restore(backend, snapshot)
        backend.task._rpent_archive = output / "restored-native-frames"
        initial = measure(backend, refresh=True)
        actual = {
            "initial": initial,
            "steps": short_branch(backend, baseline["actions"]),
        }
        write_json(output / "restored-measurements.json", actual)
        result["differences"] = differences(
            {"initial": baseline["initial"], "steps": baseline["steps"]}, actual
        )
        result["checkpoint_validation_passed"] = not result["differences"]
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
