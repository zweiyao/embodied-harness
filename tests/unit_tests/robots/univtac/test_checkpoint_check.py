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


def checkpoint(tmp_path):
    files = {}
    for name in ("state.json", "scene.json", "baseline.json"):
        (tmp_path / name).write_text("{}")
        files[name] = hashlib.sha256(b"{}").hexdigest()
    manifest = {"schema_version": 1, "files": files}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    return manifest


def test_checkpoint_integrity_and_paths_before_restore(tmp_path):
    manifest = checkpoint(tmp_path)
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


def test_restore_supplies_explicit_physx_environment_indices(tmp_path, monkeypatch):
    import torch

    class ReachedPhysX(Exception):
        pass

    def reset_to(state, env_ids=None):
        # The pinned TacEx default is slice(None), incompatible with the pinned
        # PhysX frontend's tensor.to(int32). Exercise that actual boundary.
        assert state == {}
        assert env_ids.to(torch.int32).tolist() == [0, 1]
        assert env_ids.device.type == "cpu"
        raise ReachedPhysX

    monkeypatch.setitem(
        sys.modules,
        "uipc.core",
        SimpleNamespace(SceneFactory=None, SceneIO=None, SceneSnapshot=None),
    )
    (tmp_path / "state.json").write_text(json.dumps({"physx": {}}))
    monkeypatch.setattr(
        "debug.univtac_checkpoint_check.read_verified",
        lambda root: {"task": "insert_hole", "seed": 2},
    )
    backend = SimpleNamespace(
        task_name="insert_hole",
        seed=2,
        task=SimpleNamespace(
            scene=SimpleNamespace(reset_to=reset_to), num_envs=2, device="cpu"
        ),
    )
    with pytest.raises(ReachedPhysX):
        restore(backend, tmp_path)


def test_only_matching_precharged_infrastructure_reservation(tmp_path):
    cell = {
        "id": "infra-01",
        "stage": "infrastructure",
        "model": "script",
        "condition": "C",
        "task": "insert_hole",
        "seed": 2,
    }
    attempt = {"cell": "infra-01", "session_id": str(tmp_path)}
    finished = {}
    pilot = SimpleNamespace(
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


def test_failed_initialization_is_charged_and_written_before_close(
    tmp_path, monkeypatch
):
    import robots.univtac.backend
    import robots.univtac.pilot

    cell = {
        "id": "infra-01",
        "stage": "infrastructure",
        "model": "script",
        "condition": "C",
        "task": "insert_hole",
        "seed": 2,
    }
    finished = []
    pilot = SimpleNamespace(
        _attempt=lambda events, attempt_id: {
            "cell": "infra-01",
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
def test_measurement_preserves_reset_gel_archive_and_restores_run_dir(tmp_path, fail):
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
        ),
        scene=SimpleNamespace(get_state=lambda: {}),
        _get_observations=lambda: {},
    )
    backend = SimpleNamespace(task=task, output_dir=tmp_path, run_dir=original)

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
        assert measure(backend)["scene"] == {"measured": True}
    assert backend.run_dir == original
    assert (original / "evaluator-initial-gel.npz").read_bytes() == b"initial"
    archived = list(
        (tmp_path / "checkpoint-measurements").glob("*/evaluator-initial-gel.npz")
    )
    assert len(archived) == 1
    assert archived[0].read_bytes() == b"measurement"
