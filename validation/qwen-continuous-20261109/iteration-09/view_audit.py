# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Observe actual planner image bindings; never classify or execute a task."""

import copy
import hashlib
from pathlib import Path

from PIL import Image

from robots.libero.research.manual import planner_view_description

ACTIONS = {
    "pi0_doubled",
    "pi0_pick",
    "release",
    "set_gripper",
    "translate_to",
    "align_placement",
    "rotate_axis",
}


def expected_api_views(prior_tools):
    expected = copy.deepcopy(prior_tools)
    for name in ("view_env_state", "read_image"):
        matching = [t for t in expected if t["name"] == name]
        assert len(matching) == 1
        matching[0]["description"] = planner_view_description(name)
    return expected


def audit_view_returns(path, events):
    root = Path(path)
    report = {
        "checked_bundles": 0,
        "explicit_policy_reads": 0,
        "error_returns": 0,
        "bindings": [],
    }
    for event in events:
        if event["kind"] != "tool_response":
            continue
        payload = event["payload"]
        name, result = payload.get("name"), payload.get("result", {})
        if name not in ACTIONS | {"view_env_state", "read_image"}:
            continue
        if payload.get("error") or result.get("error") or result.get("errors"):
            report["error_returns"] += 1
            continue
        assert isinstance(result.get("step"), int)
        step = result["step"]
        views, images = result["image_views"], payload["images"]
        if name == "read_image":
            expected_names = [result["artifact"]]
            report["explicit_policy_reads"] += int(
                result["artifact"] == "agentview_policy.png"
            )
        else:
            assert result["planner_view_mode"] == "calibrated-pair-v1"
            expected_names = ["agentview_high.png", "wrist_high.png"]
        assert len(views) == len(images) == len(expected_names)
        for index, (view, encoded, artifact) in enumerate(
            zip(views, images, expected_names, strict=True)
        ):
            assert Path(artifact).name == artifact
            original = root / artifact / f"{step:02d}{Path(artifact).suffix}"
            attached = (root / encoded["artifact"]).resolve()
            assert attached.is_relative_to(root.resolve() / "inputs")
            data = original.read_bytes()
            assert attached.read_bytes() == data and encoded["bytes"] == len(data)
            with Image.open(original) as image:
                width, height = image.size
            calibrated = artifact in {
                "agentview.png",
                "agentview_high.png",
                "wrist.png",
                "wrist_high.png",
            }
            policy = artifact == "agentview_policy.png"
            frame = (
                "calibrated" if calibrated else "policy" if policy else "unclassified"
            )
            camera = (
                ("agentview" if artifact.startswith("agentview") else "wrist")
                if calibrated or policy
                else None
            )
            assert view == {
                "index": index,
                "artifact": artifact,
                "camera": camera,
                "step": step,
                "width": width,
                "height": height,
                "coordinate_frame": frame,
            }
            report["bindings"].append(
                {"tool": name, **view, "sha256": hashlib.sha256(data).hexdigest()}
            )
        report["checked_bundles"] += 1
    report["passed"] = True
    report["limit"] = (
        "Byte/frame provenance only; no target identity, holding, official success or outcome classification inference. Errors remain observable, not silently excluded."
    )
    return report
