# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Reject plausible but wrong provenance while retaining tool errors as observations."""

import copy

import pytest
from PIL import Image
from view_audit import audit_view_returns, expected_api_views


@pytest.fixture
def bundle(tmp_path):
    views, images = [], []
    (tmp_path / "inputs").mkdir()
    for index, camera in enumerate(["agentview", "wrist"]):
        name = camera + "_high.png"
        path = tmp_path / name / "00.png"
        path.parent.mkdir()
        Image.new("RGB", (16 + index, 20 + index), color=(30 * index, 70, 100)).save(
            path
        )
        target = tmp_path / "inputs" / f"{index}.bin"
        target.write_bytes(path.read_bytes())
        images.append(
            {
                "artifact": str(target.relative_to(tmp_path)),
                "bytes": target.stat().st_size,
            }
        )
        views.append(
            {
                "index": index,
                "artifact": name,
                "camera": camera,
                "step": 0,
                "width": 16 + index,
                "height": 20 + index,
                "coordinate_frame": "calibrated",
            }
        )
    event = {
        "kind": "tool_response",
        "payload": {
            "name": "view_env_state",
            "result": {
                "step": 0,
                "planner_view_mode": "calibrated-pair-v1",
                "image_views": views,
            },
            "images": images,
        },
    }
    return tmp_path, event


def test_valid_bundle_and_error_are_observed_without_outcome_rewrite(bundle):
    path, event = bundle
    error = {
        "kind": "tool_response",
        "payload": {
            "name": "align_placement",
            "result": {"error": "stale preview"},
            "images": [],
        },
    }
    result = audit_view_returns(path, [event, error])
    assert result["checked_bundles"] == 1 and result["error_returns"] == 1
    assert "official_success" not in result and "classification" not in result


@pytest.mark.parametrize(
    "bad", ["order", "step", "dimensions", "frame", "bytes", "count"]
)
def test_wrong_bundle_is_rejected(bundle, bad):
    path, event = bundle
    payload = copy.deepcopy(event["payload"])
    if bad == "order":
        payload["images"].reverse()
    elif bad == "step":
        payload["result"]["image_views"][0]["step"] = 2
    elif bad == "dimensions":
        payload["result"]["image_views"][0]["width"] = 1024
    elif bad == "frame":
        payload["result"]["image_views"][0]["coordinate_frame"] = "policy"
    elif bad == "bytes":
        (path / payload["images"][0]["artifact"]).write_bytes(b"wrong")
    else:
        payload["images"].pop()
    with pytest.raises(AssertionError):
        audit_view_returns(path, [{"kind": "tool_response", "payload": payload}])


def test_only_two_api_descriptions_change():
    tools = [
        {"name": n, "description": "prior", "parameters_json_schema": {"fixture": n}}
        for n in ["view_env_state", "read_image", "pi0_pick"]
    ]
    frozen = copy.deepcopy(tools)
    expected = expected_api_views(tools)
    assert tools == frozen
    assert expected[2] == tools[2]
    assert all(
        expected[i]["parameters_json_schema"] == tools[i]["parameters_json_schema"]
        for i in [0, 1]
    )
    assert all("image_views" in expected[i]["description"] for i in [0, 1])
    with pytest.raises(AssertionError):
        expected_api_views(tools[1:])


def test_explicit_policy_read_is_reported_and_labeled(bundle):
    path, event = bundle
    source = path / "agentview_high.png/00.png"
    policy = path / "agentview_policy.png/00.png"
    policy.parent.mkdir()
    policy.write_bytes(source.read_bytes())
    payload = event["payload"]
    payload["name"] = "read_image"
    payload["images"] = payload["images"][:1]
    view = payload["result"]["image_views"][0]
    view.update(artifact="agentview_policy.png", coordinate_frame="policy")
    payload["result"] = {
        "artifact": "agentview_policy.png",
        "step": 0,
        "image_views": [view],
    }
    assert audit_view_returns(path, [event])["explicit_policy_reads"] == 1
