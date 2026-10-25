# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Replay uses the actual exported sensor contract without running candidate code."""

import json
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np
import pytest
from jsonschema import ValidationError

from robots.univtac.pilot import replay as module
from robots.univtac.pilot.evidence import export_development
from robots.univtac.toolkit import UniVTACToolkit
from rpent.dashboard.events import NullDashboardEventSink
from rpent.memory import MemoryManager
from tests.unit_tests.robots.univtac.test_toolkit import POSE, FakeEnv


@pytest.fixture
def sensors(tmp_path):
    root = tmp_path / "run"
    api = UniVTACToolkit(
        env=FakeEnv(),
        output_dir=root,
        dashboard_events=NullDashboardEventSink(),
        memory=MemoryManager(tmp_path / "memory", memory_access="read_only"),
    )
    try:
        api.execute_tool("move_eef", {"poses": [POSE] * 5})
        return Path(export_development(root)["sensors"])
    finally:
        api.close()


@pytest.fixture
def candidate():
    return {
        "name": "sensor_replay_test",
        "description": "Replay test",
        "parameters": {
            "type": "object",
            "properties": {"radius": {"type": "integer", "minimum": 1}},
            "required": ["radius"],
            "additionalProperties": False,
        },
        "source": "raise RuntimeError('candidate must never run on the host')\ndef run(frames, params): return {}",
    }


def rewrite_archive(source, target, change):
    with ZipFile(source) as original, ZipFile(target, "w", ZIP_DEFLATED) as edited:
        for name in original.namelist():
            data = original.read(name)
            if name == "frames/0005/sensor_frame.json":
                frame = json.loads(data)
                change(frame)
                data = json.dumps(frame).encode()
            edited.writestr(name, data)


def test_sensor_window_round_trips_real_export_and_excludes_private_fields(sensors):
    frames = module.load_frames(sensors)
    assert [frame["step"] for frame in frames] == [2, 3, 4, 5]
    assert [frame["step"] for frame in module.load_frames(sensors, step=1)] == [0, 1]
    np.testing.assert_array_equal(frames[-1]["cameras"]["head"]["depth"], 5.5)
    assert frames[-1]["tactile"]["left"]["rgb"].dtype == np.uint8
    assert frames[-1]["tactile"]["left"]["marker_coordinate_order"] == "x,y"
    assert "actor" not in frames[-1] and "evaluator" not in frames[-1]


def test_unknown_fields_do_not_follow_private_or_external_artifacts(sensors, tmp_path):
    target = tmp_path / "extra.zip"

    def change(frame):
        frame["evaluator"] = {"artifact": "../../private.json"}
        frame["tactile"]["left"]["hidden_force"] = {"artifact": "private.npz"}

    rewrite_archive(sensors, target, change)
    frame = module.load_frames(target)[-1]
    assert "evaluator" not in frame and "hidden_force" not in frame["tactile"]["left"]


@pytest.mark.parametrize(
    "reference",
    ["../../private.npz", "sensor_cameras_head_depth.png/01.png", "evaluator.npz"],
)
def test_sensor_references_cannot_escape_or_read_non_sensor_entries(
    sensors, tmp_path, reference
):
    target = tmp_path / "invalid.zip"
    rewrite_archive(
        sensors,
        target,
        lambda frame: frame["cameras"]["head"].update(depth={"artifact": reference}),
    )
    with pytest.raises(ValueError, match="artifact reference"):
        module.load_frames(target)


@pytest.mark.parametrize("step", [-1, 6, True])
def test_unknown_step_is_not_silently_replaced(sensors, step):
    with pytest.raises(ValueError, match="Unknown recorded step"):
        module.load_frames(sensors, step=step)


def test_replay_checks_parameters_before_loading_or_starting_docker(
    candidate, monkeypatch
):
    monkeypatch.setattr(
        module, "Sandbox", lambda *_: pytest.fail("must not start Docker")
    )
    with pytest.raises(ValidationError):
        module.replay(candidate, {"radius": 0}, "/nonexistent/sensors.zip")


@pytest.mark.parametrize(
    "result,validation",
    [({"value": 2}, "replay_passed"), ({"error": "missing sensor"}, "replay_failed")],
)
def test_replay_records_real_input_and_sandbox_identity(
    sensors, candidate, monkeypatch, result, validation
):
    class Sandbox:
        def __init__(self, image):
            self.image = "sha256:resolved"

        def run(self, tool, params, frames):
            assert tool == candidate and params == {"radius": 2}
            assert [frame["step"] for frame in frames] == [2, 3, 4, 5]
            return result

    monkeypatch.setattr(module, "Sandbox", Sandbox)
    report = module.replay(candidate, {"radius": 2}, sensors)
    assert report["validation"] == validation
    assert report["sandbox_image"] == "sha256:resolved"
    assert report["result"] == result and len(report["input_sha256"]) == 64
    assert report["tool_version"] == module.digest([candidate])


def test_cli_error_report_is_saved_without_publishing(tmp_path, candidate, monkeypatch):
    tool = tmp_path / "candidate.json"
    tool.write_text(json.dumps(candidate))
    metadata = tmp_path / "metadata.json"
    metadata.write_text(
        json.dumps({"source_run": "dev", "reason": "test", "input_contract": "sensors"})
    )
    output, library = tmp_path / "report.json", tmp_path / "library"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "replay",
            "--sensors",
            "unused.zip",
            "--candidate",
            str(tool),
            "--output",
            str(output),
            "--library",
            str(library),
            "--metadata",
            str(metadata),
        ],
    )
    monkeypatch.setattr(
        module,
        "replay",
        lambda *a, **k: {
            "validation": "replay_failed",
            "result": {"error": "missing sensor"},
        },
    )
    with pytest.raises(SystemExit, match="not published"):
        module.main()
    assert json.loads(output.read_text())["validation"] == "replay_failed"
    assert not library.exists()
