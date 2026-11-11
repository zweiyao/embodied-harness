# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""One real alignment through the selected toolkit; no learned policy calls."""

import hashlib
import json
import os
import signal
import sys
from pathlib import Path
from types import SimpleNamespace


def main():
    root = Path(sys.argv[1]).resolve()
    source = Path(os.environ["RPENT_REPO_ROOT"]).resolve()
    config = root / "libero-config/config.yaml"
    assert Path(os.environ["LIBERO_CONFIG_PATH"]).resolve() == config.parent
    before_config = hashlib.sha256(config.read_bytes()).hexdigest()
    assert not any(
        os.environ.get(name)
        for name in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
        )
    )

    import numpy as np

    from robots.libero.env_client import LiberoEnvClient
    from robots.libero.env_server import LiberoEnvFacade, make_env
    from robots.libero.research import placement
    from robots.libero.research.manual import ManualToolkit
    from rpent.dashboard.workbench import RunJournal, native_catalog
    from rpent.memory import MemoryManager
    from rpent.utils.config import get_repo_root
    from rpent.utils.logging import init_output_dir

    assert get_repo_root().resolve() == source
    assert Path(placement.__file__).resolve().is_relative_to(source)
    owned = {}

    def remember_children():
        pending = [os.getpid()]
        while pending:
            pid = pending.pop()
            children = Path(f"/proc/{pid}/task/{pid}/children")
            if children.exists():
                for child in map(int, children.read_text().split()):
                    stat = Path(f"/proc/{child}/stat")
                    if stat.exists():
                        owned[str(child)] = stat.read_text().split()[21]
                        pending.append(child)

    def stop(signum, frame):
        raise TimeoutError("P probe watchdog expired")

    signal.signal(signal.SIGALRM, stop)
    signal.signal(signal.SIGTERM, stop)
    signal.alarm(300)
    report = {
        "passed": False,
        "source_root": str(source),
        "pid": os.getpid(),
        "model_requests": 0,
        "vla_predictions": 0,
        "enable_eef_control": False,
        "purpose": "Interface only; O is a diagnostic visible surface, not a verified held object",
    }
    env = facade = toolkit = None
    trace = []
    try:
        init_output_dir(root)
        env = make_env(
            0, 0, "libero_10_task", max_episode_steps=200, enable_eef_control=False
        )
        facade = LiberoEnvFacade(env, meta={})

        class LocalRpc:
            def call(self, name, args=(), kwargs=None, **ignored):
                return facade._rpc[name](*args, **(kwargs or {}))

        client = LiberoEnvClient(LocalRpc(), expected_meta={})
        selected = [
            item
            for item in native_catalog()
            if item["name"] in {"finish", "preview_placement", "align_placement"}
        ]
        toolkit = ManualToolkit(
            selected=selected,
            journal=RunJournal(root / "journal"),
            runtime_kwargs={"env": client, "model": None, "sam3_client": None},
            dashboard_events=SimpleNamespace(enabled=False, emit=lambda *args: None),
            memory=MemoryManager(root / "empty-memory"),
            state_output_dir=root / "state",
        )
        remember_children()
        report["selected_names"] = [tool.name for tool in toolkit.list_tools()]
        p = toolkit.primitives
        inner_step = p._step_env

        def traced_step(action):
            inner_step(action)
            trace.append(
                {
                    "action": np.asarray(action).tolist(),
                    "eef": client.raw_obs()["robot0_eef_pos"].tolist(),
                }
            )

        p._step_env = traced_step
        initial = np.asarray(client.raw_obs()["robot0_eef_pos"]).copy()
        previews = []
        chosen = None
        for row, col in [
            (850, 450),
            (850, 550),
            (900, 450),
            (800, 600),
            (900, 600),
            (800, 450),
        ]:
            params = {
                "step": toolkit.state.get().step_idx,
                "camera": "agentview",
                "held_feature": [row, col],
                "plane_samples": [
                    [row - 35, col - 35],
                    [row - 35, col + 70],
                    [row + 35, col + 70],
                    [row + 35, col - 35],
                ],
                "target_region": [
                    [row - 12, col + 25],
                    [row - 12, col + 45],
                    [row + 12, col + 45],
                    [row + 12, col + 25],
                ],
            }
            preview = toolkit.execute_tool("preview_placement", params)
            previews.append({"params": params, "result": preview.data})
            if (
                preview.data.get("status") == "review_required"
                and 0.015 < preview.data["xy_correction_m"] < 0.06
            ):
                chosen = preview
                break
        (root / "previews.json").write_text(json.dumps(previews, indent=2) + "\n")
        assert chosen is not None, (
            "No eligible bounded diagnostic preview; no action executed"
        )
        for i, content in enumerate(chosen.images):
            (root / f"preview-{i}.png").write_bytes(content)
        result = toolkit.execute_tool(
            "align_placement", {"preview_id": chosen.data["preview_id"]}
        )
        record = toolkit.state.get()
        assert not result.is_error, result.data
        assert record.command["action"] == "align_placement"
        assert record.result["preview_id"] == chosen.data["preview_id"]
        assert len(result.images) >= 2 and 0 < len(trace) <= 80
        assert all(np.array_equal(item["action"][3:], [0, 0, 0, 0]) for item in trace)
        final = np.asarray(client.raw_obs()["robot0_eef_pos"])
        assert np.linalg.norm(final[:2] - initial[:2]) > 0.001
        executed = len(trace)
        rejected = toolkit.execute_tool(
            "align_placement", {"preview_id": chosen.data["preview_id"]}
        )
        assert rejected.is_error and len(trace) == executed
        report.update(
            passed=True,
            consumed_preview_rejected=True,
            actual_control_steps=len(trace),
            recorded_step=record.step_idx,
            motion_result=record.result,
            initial_eef_xyz=initial.tolist(),
            final_eef_xyz=final.tolist(),
            actual_xy_displacement_m=float(np.linalg.norm(final[:2] - initial[:2])),
            returned_images=len(result.images),
            zero_rotation_and_gripper_commands=True,
            gripper_limit="Command checked; target retention relies on unchanged M and its prior installed-controller probe",
        )
    except BaseException as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        remember_children()
        if toolkit is not None:
            toolkit.close()
        if facade is not None:
            facade.close()
        elif env is not None:
            env.env.close()
        signal.alarm(0)
        report["owned_children_start_ticks"] = owned
        report["facade_closed"] = facade is not None and facade._closed
        report["private_config_unchanged"] = (
            hashlib.sha256(config.read_bytes()).hexdigest() == before_config
        )
        (root / "trace.json").write_text(json.dumps(trace, indent=2) + "\n")
        (root / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
