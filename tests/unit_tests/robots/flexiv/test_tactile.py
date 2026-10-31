# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Recorded tactile evidence remains distinct from force and motion control."""

import json
from types import SimpleNamespace

import numpy as np
import pytest

from robots.flexiv.tactile import compare
from robots.flexiv.tactile_camera import attach_snapshot, read_snapshot
from robots.flexiv.toolkit import FlexivToolkit, tool_methods

cv2 = pytest.importorskip("cv2")


def frame_pair():
    before = np.full((360, 640, 3), 200, np.uint8)
    for x in range(40, 610, 30):
        for y in range(40, 330, 30):
            cv2.circle(before, (x, y), 4, (30, 30, 30), -1)
    after = cv2.warpAffine(before, np.float32([[1, 0, 2], [0, 1, -1]]), (640, 360))
    metadata = {
        "status": "available",
        "serial": "sensor",
        "side": "left",
        "capture_session": "session",
        "resolution_wh": [640, 360],
        "received_at_s": 10,
        "sequence": 1,
    }
    return before, after, metadata, {**metadata, "received_at_s": 11, "sequence": 2}


def test_known_image_translation_and_empty_image_quality():
    before, after, first, second = frame_pair()
    result = compare(before, after, first, second)
    assert result["status"] == "measured"
    assert result["median_displacement_xy_px"] == pytest.approx([2, -1], abs=0.1)
    assert "force" not in result
    blank = np.zeros_like(before)
    result = compare(blank, blank, first, second)
    assert result["status"] == "insufficient_evidence"
    assert "median_displacement_xy_px" not in result
    assert compare(before, blank, first, second)["status"] == "insufficient_evidence"


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "stale"),
        ("serial", "other"),
        ("capture_session", "restart"),
        ("sequence", 1),
    ],
)
def test_reject_mismatched_or_unavailable_recordings(field, value):
    before, after, first, second = frame_pair()
    with pytest.raises(ValueError):
        compare(before, after, first, {**second, field: value})


def test_atomic_snapshot_missing_and_stale_never_reused_as_current(tmp_path):
    assert read_snapshot(tmp_path)[0]["status"] == "unavailable"
    before, _, metadata, _ = frame_pair()
    ok, jpeg = cv2.imencode(".jpg", before)
    assert ok
    np.savez(tmp_path / "left.npz", metadata=json.dumps(metadata), jpeg=jpeg)
    assert read_snapshot(tmp_path, now=11)[1] == jpeg.tobytes()
    stale, image = read_snapshot(tmp_path, now=13)
    assert stale["status"] == "stale"
    assert image is None
    observed = {"images_png": {}}
    attach_snapshot(observed, tmp_path)
    assert observed["tactile"]["left"]["status"] == "stale"
    assert not observed["images_png"]


def test_record_images_metadata_and_compare_without_robot_actions(
    tmp_path, monkeypatch
):
    import base64

    before, after, first, second = frame_pair()
    observations = iter([(before, first), (after, second)])

    def observe():
        frame, metadata = next(observations)
        _, png = cv2.imencode(".png", frame)
        return {
            "state": {},
            "images_png": {"tactile_left": base64.b64encode(png).decode()},
            "tactile": {"left": metadata},
        }

    monkeypatch.setattr("rpent.tools.toolkit.substitute", lambda value: value)
    monkeypatch.setattr(FlexivToolkit, "_register_common_tools", lambda self: None)
    env = SimpleNamespace(
        meta={
            "control_backend": "rdk",
            "motion_enabled": False,
            "tactile_configured": True,
        },
        get_observation=observe,
        close=lambda: None,
    )
    toolkit = FlexivToolkit(
        env=env,
        output_dir=tmp_path,
        control_mode="rdk",
        dashboard_events=SimpleNamespace(enabled=False, emit=lambda e: None),
        memory=SimpleNamespace(),
    )
    try:
        result = toolkit.execute_tool("observe", {})
        after_step = result.data["step"]
        assert len(result.images) == 1
        assert (
            toolkit.state.load("tactile.json", step=after_step)["left"]["side"]
            == "left"
        )
        result = toolkit.execute_tool(
            "tactile_compare", {"before_step": after_step - 1, "after_step": after_step}
        )
        assert not result.is_error
        assert result.data["median_displacement_xy_px"] == pytest.approx(
            [2, -1], abs=0.1
        )
        assert "tactile_compare" not in tool_methods(
            {"tactile_configured": False}, "rdk"
        )
        assert "tactile_compare" not in tool_methods(None, "native")
    finally:
        toolkit.close()
