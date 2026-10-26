# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""CPU checks for the isolated qualification script, without simulator imports."""

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from debug.univtac_checkpoint_check import (
    differences,
    main,
    measure,
    pack,
    read_verified,
    restore,
    restore_physx,
    runtime_state,
    unpack,
    validate_reservation,
)


def test_numeric_and_rng_state_roundtrip_without_pickle():
    state = {
        "positions": np.array([[0.1, -0.2]], dtype=np.float32),
        "rng": ("MT19937", np.array([0, 2**32 - 1], dtype=np.uint32), 624, 0, 0.0),
        "pending": None,
    }
    restored = unpack(json.loads(json.dumps(pack(state), allow_nan=False)))
    assert restored["positions"].dtype == np.float32
    assert np.array_equal(restored["positions"], state["positions"])
    assert type(restored["rng"]) is tuple
    assert restored["rng"][1].dtype == np.uint32
    assert np.array_equal(restored["rng"][1], state["rng"][1])
    with pytest.raises(TypeError, match="Unsupported checkpoint state"):
        pack(object())


def checkpoint(tmp_path, version=1):
    files = {}
    for name in ("state.json", "scene.json", "baseline.json"):
        (tmp_path / name).write_text("{}")
        files[name] = hashlib.sha256(b"{}").hexdigest()
    manifest = {"schema_version": version, "files": files}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    return manifest


@pytest.mark.parametrize("version", [1, 2])
def test_checkpoint_integrity_and_paths_before_restore(tmp_path, version):
    manifest = checkpoint(tmp_path, version)
    assert read_verified(tmp_path) == manifest
    (tmp_path / "scene.json").write_text("changed")
    with pytest.raises(ValueError, match="Checkpoint file changed"):
        read_verified(tmp_path)
    checkpoint(tmp_path)
    manifest["files"]["../outside.json"] = "irrelevant"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="escapes"):
        read_verified(tmp_path)


def test_strict_check_does_not_hide_small_physics_or_renderer_differences():
    expected = {"physics": [0.0, 1.0], "sensors": {"rgb_sha256": "a"}}
    actual = {"physics": [1e-12, 1.0], "sensors": {"rgb_sha256": "b"}}
    changed = differences(expected, actual)
    assert {x["path"] for x in changed} == {"/physics", "/sensors/rgb_sha256"}
    assert (
        next(x for x in changed if x["path"] == "/physics")["max_abs_difference"]
        == 1e-12
    )
    assert differences(expected, expected) == []


def test_capture_and_restore_preserve_commands_distinct_from_actual_state(monkeypatch):
    import torch

    actual_position = torch.tensor([[0.1], [0.2]])
    actual_velocity = torch.tensor([[0.01], [0.02]])
    commands = {
        "joint_pos_target": torch.tensor([[0.3], [0.4]]),
        "joint_vel_target": torch.tensor([[0.0], [0.0]]),
        "joint_effort_target": torch.tensor([[0.5], [0.6]]),
    }
    data = SimpleNamespace(
        joint_pos=actual_position.clone(),
        joint_vel=actual_velocity.clone(),
        **{name: value.clone() for name, value in commands.items()},
    )
    flushed = []

    def set_target(name, target, env_ids):
        assert env_ids.to(torch.int32).tolist() == [0, 1]
        assert env_ids.device.type == "cpu"
        getattr(data, name)[env_ids] = target

    robot = SimpleNamespace(
        data=data,
        set_joint_position_target=lambda target, env_ids: set_target(
            "joint_pos_target", target, env_ids
        ),
        set_joint_velocity_target=lambda target, env_ids: set_target(
            "joint_vel_target", target, env_ids
        ),
        set_joint_effort_target=lambda target, env_ids: set_target(
            "joint_effort_target", target, env_ids
        ),
        write_data_to_sim=lambda: flushed.append(
            {name: getattr(data, name).clone() for name in commands}
        ),
    )
    physical = {"position": actual_position, "velocity": actual_velocity}

    def reset_to(state, env_ids=None):
        assert env_ids.to(torch.int32).tolist() == [0, 1]
        # The pinned reset_to overwrites command buffers with measured state.
        data.joint_pos = state["position"].clone()
        data.joint_vel = state["velocity"].clone()
        data.joint_pos_target = data.joint_pos.clone()
        data.joint_vel_target = data.joint_vel.clone()

    task = SimpleNamespace(
        scene=SimpleNamespace(get_state=lambda: physical, reset_to=reset_to),
        _robot_manager=SimpleNamespace(robot=robot),
        _actor_manager=SimpleNamespace(actors={}),
        _tactile_manager=SimpleNamespace(tactiles={}),
        rng=np.random.default_rng(2),
        num_envs=2,
        device="cpu",
    )
    monkeypatch.setattr(torch.cuda, "get_rng_state_all", lambda: [])
    state = runtime_state(SimpleNamespace(task=task, references={}, physics_start=0))
    for name in commands:
        getattr(data, name).fill_(99)
        assert torch.equal(state["joint_targets"][name], commands[name])
    state = unpack(json.loads(json.dumps(pack(state))))
    restore_physx(task, state)
    assert torch.equal(data.joint_pos, actual_position)
    assert torch.equal(data.joint_vel, actual_velocity)
    assert len(flushed) == 1
    for name, expected in commands.items():
        assert torch.equal(flushed[0][name], expected)
        assert flushed[0][name].dtype == expected.dtype


@pytest.mark.parametrize("targets", [None, {}, {"joint_pos_target": [0.0]}])
def test_missing_command_targets_reject_before_touching_physics(targets):
    import torch

    def forbidden_reset(*args, **kwargs):
        pytest.fail("Invalid checkpoint must not change physical state")

    task = SimpleNamespace(
        scene=SimpleNamespace(reset_to=forbidden_reset),
        _robot_manager=SimpleNamespace(
            robot=SimpleNamespace(data=SimpleNamespace(joint_pos=torch.zeros(1, 1)))
        ),
    )
    with pytest.raises(ValueError, match="complete commanded joint targets"):
        restore_physx(task, {"joint_targets": targets})


def test_old_snapshot_remains_auditable_but_cannot_restore(tmp_path, monkeypatch):
    manifest = checkpoint(tmp_path)
    assert read_verified(tmp_path) == manifest
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}

    monkeypatch.setitem(
        sys.modules,
        "uipc.core",
        SimpleNamespace(SceneFactory=None, SceneIO=None, SceneSnapshot=None),
    )
    with pytest.raises(ValueError, match="Schema 1 checkpoint is audit-only"):
        restore(SimpleNamespace(), tmp_path)
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


def test_only_matching_precharged_infrastructure_reservation(tmp_path):
    from debug.univtac_checkpoint_compare import protocol
    from robots.univtac.pilot import digest

    cell = {
        "id": "infra-03",
        "stage": "infrastructure",
        "model": "script",
        "condition": "C",
        "task": "insert_hole",
        "seed": 2,
    }
    attempt = {"cell": "infra-03", "session_id": str(tmp_path)}
    finished = {}
    pilot = SimpleNamespace(
        manifest={
            "checkpoint_qualification": {
                "protocol_sha256": digest(protocol()),
                "cells": protocol()["cells"],
            }
        },
        _attempt=lambda events, attempt_id: attempt,
        _cell=lambda name: cell,
        _finished=lambda events: finished,
        _transaction=lambda operation: operation([])[0],
    )
    assert validate_reservation(pilot, "reserved", "capture", tmp_path) == cell
    with pytest.raises(ValueError, match="reservation"):
        validate_reservation(pilot, "reserved", "restore", tmp_path)
    with pytest.raises(ValueError, match="reservation"):
        validate_reservation(pilot, "reserved", "capture", Path("/wrong-output"))
    finished["reserved"] = {}
    with pytest.raises(ValueError, match="reservation"):
        validate_reservation(pilot, "reserved", "capture", tmp_path)
    finished.clear()
    for changed in ({}, {"protocol_sha256": "wrong", "cells": protocol()["cells"]}):
        pilot.manifest = {"checkpoint_qualification": changed}
        with pytest.raises(ValueError, match="registered qualification protocol"):
            validate_reservation(pilot, "reserved", "capture", tmp_path)


def test_failed_initialization_is_charged_and_written_before_close(
    tmp_path, monkeypatch
):
    import robots.univtac.backend
    import robots.univtac.pilot
    from debug.univtac_checkpoint_compare import protocol

    cell = {
        "id": "infra-03",
        "stage": "infrastructure",
        "model": "script",
        "condition": "C",
        "task": "insert_hole",
        "seed": 2,
    }
    finished = []
    pilot = SimpleNamespace(
        manifest={
            "checkpoint_qualification": {
                "protocol_sha256": robots.univtac.pilot.digest(protocol()),
                "cells": protocol()["cells"],
            }
        },
        _attempt=lambda events, attempt_id: {
            "cell": "infra-03",
            "session_id": str(tmp_path),
        },
        _cell=lambda name: cell,
        _finished=lambda events: {},
        _transaction=lambda operation: operation([])[0],
        finish_episode=lambda attempt_id, result: finished.append(result.copy()),
    )
    closed = []

    class FailedBackend:
        def __init__(self, **kwargs):
            self.task = None

        def reset(self):
            raise RuntimeError("test reset failed")

        def close(self):
            assert finished and (tmp_path / "checkpoint-result.json").is_file()
            closed.append(True)

    monkeypatch.setattr(robots.univtac.pilot, "Pilot", lambda root: pilot)
    monkeypatch.setattr(robots.univtac.backend, "UniVTACBackend", FailedBackend)
    args = [
        "--root",
        "unused",
        "--pilot-root",
        "unused",
        "--attempt-id",
        "reserved",
        "--phase",
        "capture",
        "--snapshot-root",
        str(tmp_path / "snapshot"),
        "--output-dir",
        str(tmp_path),
    ]
    assert main(args) == 1
    result = json.loads((tmp_path / "checkpoint-result.json").read_text())
    assert result["initializations"] == 1
    assert result["termination_reason"] == "setup_failure"
    assert result["checkpoint_validation_passed"] is False
    assert result["official_success"] is None
    assert closed == [True]
    with pytest.raises(FileExistsError):
        main(args)
    assert len(finished) == 1


@pytest.mark.parametrize("fail", [False, True])
def test_measurement_preserves_reset_gel_archive_and_restores_run_dir(
    tmp_path, fail, monkeypatch
):
    import torch

    original = tmp_path / "reset"
    original.mkdir()
    (original / "evaluator-initial-gel.npz").write_bytes(b"initial")
    workspace = tmp_path / "world"
    (workspace / "dump").mkdir(parents=True)
    for i in range(9):
        (workspace / "dump" / f"buffer{i}.7").write_bytes(b"state")
    task = SimpleNamespace(
        uipc_sim=SimpleNamespace(
            world=SimpleNamespace(dump=lambda: True, frame=lambda: 7),
            cfg=SimpleNamespace(workspace=str(workspace)),
            sio=SimpleNamespace(
                simplicial_surface=lambda dim: SimpleNamespace(
                    positions=lambda: SimpleNamespace(view=lambda: np.zeros((1, 3)))
                )
            ),
        ),
        scene=SimpleNamespace(get_state=lambda: {}),
        _get_observations=lambda: {},
        _robot_manager=SimpleNamespace(
            robot=SimpleNamespace(
                data=SimpleNamespace(
                    joint_pos_target=torch.tensor([[0.3]]),
                    joint_vel_target=torch.tensor([[0.0]]),
                    joint_effort_target=torch.tensor([[0.5]]),
                )
            )
        ),
    )
    backend = SimpleNamespace(task=task, output_dir=tmp_path, run_dir=original)
    monkeypatch.setattr(
        "debug.univtac_checkpoint_check.runtime_state", lambda backend: {}
    )

    def components(native):
        (backend.run_dir / "evaluator-initial-gel.npz").write_bytes(b"measurement")
        if fail:
            raise RuntimeError("test measurement failed")
        return {"measured": True}

    backend._scene_components = components
    if fail:
        with pytest.raises(RuntimeError, match="measurement failed"):
            measure(backend)
    else:
        measured = measure(backend)
        assert measured["scene"] == {"measured": True}
        assert unpack(measured["joint_targets"])["joint_effort_target"].item() == 0.5
        altered = json.loads(json.dumps(measured))
        altered["joint_targets"]["joint_vel_target"]["data"][0][0] = 0.01
        assert (
            differences(measured, altered)[0]["path"]
            == "/joint_targets/joint_vel_target/data"
        )
    assert backend.run_dir == original
    assert (original / "evaluator-initial-gel.npz").read_bytes() == b"initial"
    archived = list(
        (tmp_path / "checkpoint-measurements").glob("*/evaluator-initial-gel.npz")
    )
    assert len(archived) == 1
    assert archived[0].read_bytes() == b"measurement"
