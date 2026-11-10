# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Read archived observations through the actual presentation code, without actions."""

import hashlib
import json
import sys
import threading
from pathlib import Path


def main():
    source = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(source))
    from robots.libero.research.manual import ManualToolkit, availability_prompt
    from robots.libero.tools import view_env_state
    from rpent.dashboard.workbench import native_catalog
    from rpent.session import EnvState
    from rpent.session.base import StepRecord

    root = Path(
        "/home/zwy/work/embodied_harness/experiments/qwen-continuous-20261109/iteration-08"
    )
    assert Path(sys.modules[ManualToolkit.__module__].__file__).is_relative_to(source)

    def hash_bytes(data):
        return hashlib.sha256(data).hexdigest()

    summary = {
        "source": str(source),
        "frames": [],
        "native_catalog_sha256": hash_bytes(
            json.dumps(native_catalog(), sort_keys=True).encode()
        ),
    }
    selected_names = json.loads((root / "plan.json").read_text())["tool_names"]
    selected = [t for t in native_catalog() if t["name"] in selected_names]
    summary["native_availability_sha256"] = hash_bytes(
        availability_prompt(selected).encode()
    )
    candidate = hasattr(ManualToolkit, "_present_state")
    for result in json.loads((root / "results.json").read_text()):
        path = Path(result["path"])
        manifest = path / "states.json"
        before = hash_bytes(manifest.read_bytes())
        data = json.loads(manifest.read_text())
        # Rehydrate only the in-memory reader; never reset, record, save or initialize runtime.
        state = EnvState.__new__(EnvState)
        state._output_dir = path
        state._artifact_lock = threading.Lock()
        state._steps = [
            StepRecord(**{**r, "artifacts": set(r["artifacts"])}) for r in data["steps"]
        ]
        t = ManualToolkit.__new__(ManualToolkit)
        t._state = state
        for record in state.records():
            original = view_env_state(step=record.step_idx, state=state)
            row = {
                "task_path": str(path),
                "step": record.step_idx,
                "native_data_sha256": hash_bytes(
                    json.dumps(original.data, sort_keys=True).encode()
                ),
                "native_image_sha256": [hash_bytes(b) for b in original.images],
            }
            if candidate:
                t.planner_view_mode = "native"
                assert t._present_state(original) is original
                t.planner_view_mode = "calibrated-pair-v1"
                shown = t._present_state(original)
                assert not shown.is_error
                names = ["agentview_high.png", "wrist_high.png"]
                assert shown.images == [
                    state.load_bytes(name, step=record.step_idx) for name in names
                ]
                assert [v["artifact"] for v in shown.data["image_views"]] == names
                assert all(
                    v["step"] == record.step_idx
                    and v["coordinate_frame"] == "calibrated"
                    for v in shown.data["image_views"]
                )
                assert {k: shown.data[k] for k in original.data} == original.data
                row["candidate_image_sha256"] = [hash_bytes(b) for b in shown.images]
                row["image_views"] = shown.data["image_views"]
                for name in names + ["agentview_policy.png"]:
                    read = t.read_image(name=name, step=record.step_idx)
                    assert read.images == [state.load_bytes(name, step=record.step_idx)]
                assert (
                    t.read_image(
                        name="agentview_policy.png", step=record.step_idx
                    ).data["image_views"][0]["coordinate_frame"]
                    == "policy"
                )
            summary["frames"].append(row)
        assert hash_bytes(manifest.read_bytes()) == before
    summary["passed"] = True
    summary["policy_requests"] = 0
    summary["simulator_actions"] = 0
    summary["limit"] = (
        "Checks stored bytes/frame bindings, not semantic identity, holding or task success. Does not instantiate runtime."
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
