# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""CPU preflight checks never construct a native task or consume an episode."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from robots.univtac import probe


@pytest.fixture
def configured_assets(tmp_path):
    root = tmp_path / "checkout"
    assets = root / "custom-assets"
    assets.mkdir(parents=True)
    robot = assets / "configured-robot.usd"
    plate = assets / "configured-plate.usda"
    gelpad = assets / "nested-gelpad.usdc"
    for path in (robot, plate, gelpad):
        path.write_bytes(b"USD fixture")
    calibration = assets / "calibration"
    calibration.mkdir()
    for name in (
        "params.json",
        "polycalib.npz",
        "gelmap.npy",
        "dataPack.npz",
        "shadowTable.npz",
    ):
        (calibration / name).write_bytes(b"calibration fixture")
    renderer = tmp_path / "renderer-mdl"
    (renderer / "gltf").mkdir(parents=True)
    (renderer / "gltf" / "pbr.mdl").write_bytes(b"MDL fixture")
    (renderer / "OmniPBR.mdl").write_bytes(b"MDL fixture")

    class Task:
        def __init__(self, *args, **kwargs):
            raise AssertionError("probe must not construct Task")

        def reset(self):
            raise AssertionError("probe must not reset Task")

        def load_robot_and_sensors(self, cfg):
            assert self is None
            assert cfg.tactile_sensor_type == "gsmini"
            cfg.robot = SimpleNamespace(
                robot=SimpleNamespace(spawn=SimpleNamespace(usd_path=str(robot))),
                tactiles=[
                    SimpleNamespace(
                        name=side,
                        sensor_cfg=SimpleNamespace(
                            optical_sim_cfg=SimpleNamespace(
                                calib_folder_path=str(calibration)
                            )
                        ),
                    )
                    for side in ("left_tactile", "right_tactile")
                ],
            )
            return cfg

    def importer(name):
        return SimpleNamespace(
            __file__=root / "envs" / f"{name.split('.')[-1]}.py",
            Task=Task,
            TaskCfg=lambda: SimpleNamespace(
                tactile_sensor_type="another-sensor",
                plate=SimpleNamespace(spawn=SimpleNamespace(usd_path=str(plate))),
            ),
        )

    references = {
        robot: [gelpad.name, "https://example.invalid/remote-scene.usd"],
        gelpad: [robot.name, "OmniPBR.mdl", "gltf/pbr.mdl"],
        plate: [],
    }
    return root, robot, gelpad, calibration, importer, references, renderer


def test_probe_reads_actual_configs_and_checks_nested_usd_once(configured_assets):
    root, robot, gelpad, calibration, importer, references, renderer = configured_assets
    opened = []

    def read_refs(path):
        opened.append(path)
        return references[path]

    report = probe.check_local_assets(
        root, importer=importer, usd_references=read_refs, mdl_search_paths=[renderer]
    )
    assert report["passed"] is True
    assert [item["task"] for item in report["tasks"]] == list(probe.TASKS)
    assert all(item["robot_usd"] == str(robot) for item in report["tasks"])
    assert all(item["sensor"] == "gsmini" for item in report["tasks"])
    assert opened.count(robot) == opened.count(gelpad) == 1
    assert report["remote_references_unchecked"] == [
        "https://example.invalid/remote-scene.usd"
    ]
    assert {item["asset"] for item in report["renderer_resolutions"]} == {
        "OmniPBR.mdl",
        "gltf/pbr.mdl",
    }
    assert all(Path(item["path"]).is_file() for item in report["renderer_resolutions"])
    assert len(report["files"]) == 10


@pytest.mark.parametrize(
    "failure",
    [
        "robot-pointer",
        "nested-pointer",
        "missing-calibration",
        "invalid-usd",
        "missing-mdl",
        "renderer-pointer",
        "local-mdl-pointer",
    ],
)
def test_missing_or_pointer_assets_fail_before_any_task(configured_assets, failure):
    root, robot, gelpad, calibration, importer, references, renderer = configured_assets
    pointer = b"version https://git-lfs.github.com/spec/v1\noid sha256:placeholder\nsize 123\n"
    if failure == "robot-pointer":
        robot.write_bytes(pointer)
    elif failure == "nested-pointer":
        gelpad.write_bytes(pointer)
    elif failure == "missing-calibration":
        (calibration / "shadowTable.npz").unlink()
    elif failure == "missing-mdl":
        (renderer / "gltf" / "pbr.mdl").unlink()
    elif failure == "renderer-pointer":
        (renderer / "OmniPBR.mdl").write_bytes(pointer)
    elif failure == "local-mdl-pointer":
        (gelpad.parent / "OmniPBR.mdl").write_bytes(pointer)

    def read_refs(path):
        if failure == "invalid-usd" and path == robot:
            raise ValueError("USD layer cannot be opened")
        return references[path]

    report = probe.check_local_assets(
        root, importer=importer, usd_references=read_refs, mdl_search_paths=[renderer]
    )
    assert report["passed"] is False
    assert report["errors"]
    expected = (
        "LFS pointer"
        if "pointer" in failure
        else "missing"
        if "missing" in failure
        else "cannot be opened"
    )
    assert any(expected in item["error"] for item in report["errors"])


@pytest.mark.parametrize("failure", ["startup", "assets"])
def test_probe_persists_failure_and_traceback_before_kit_exits_zero(
    tmp_path, monkeypatch, capsys, failure
):
    monkeypatch.setattr(probe.importlib, "import_module", lambda name: None)
    monkeypatch.setattr(probe, "_mdl_search_paths", lambda: [])
    monkeypatch.setattr(
        probe,
        "check_local_assets",
        lambda root, **kwargs: {"passed": False, "errors": ["LFS pointer"]},
    )

    class Backend:
        def __init__(self, **kwargs):
            pass

        def start_app(self):
            if failure == "startup":
                raise RuntimeError("startup failed")

        def close(self):
            saved = json.loads((tmp_path / "probe-result.json").read_text())
            assert saved["probe_passed"] is False
            assert saved["status"] == "failed"
            assert saved["episode_started"] is False
            assert (tmp_path / "probe-error.txt").read_text().startswith("Traceback")
            raise SystemExit(0)

    with pytest.raises(SystemExit) as stopped:
        probe.run_probe(root="unused", output_dir=tmp_path, backend_factory=Backend)
    assert stopped.value.code == 0
    assert "Traceback" in capsys.readouterr().err


def test_probe_success_is_written_before_close_without_reset(tmp_path, monkeypatch):
    monkeypatch.setattr(probe.importlib, "import_module", lambda name: None)
    monkeypatch.setattr(probe, "_mdl_search_paths", lambda: [])
    monkeypatch.setattr(
        probe.importlib.metadata, "version", lambda name: "test-version"
    )
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True)),
    )
    monkeypatch.setattr(
        probe,
        "check_local_assets",
        lambda root, **kwargs: {"passed": True, "errors": []},
    )

    class Backend:
        def __init__(self, **kwargs):
            pass

        def start_app(self):
            saved = json.loads((tmp_path / "probe-result.json").read_text())
            assert saved["probe_passed"] is False
            assert saved["status"] == "running"

        def close(self):
            saved = json.loads((tmp_path / "probe-result.json").read_text())
            assert saved["probe_passed"] is True

        def reset(self):
            raise AssertionError("probe must never reset")

    result = probe.run_probe(
        root="unused", output_dir=tmp_path, backend_factory=Backend
    )
    assert result["probe_passed"] is True
    assert result["local_assets_passed"] is True
    assert result["episode_started"] is False
