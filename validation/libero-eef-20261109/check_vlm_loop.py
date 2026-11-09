# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Real Max/VLM interface fixture, explicitly not a benchmark evaluation."""

import json
import os
import shutil
import sys
from pathlib import Path

from robots.libero.env_client import LiberoEnvClient
from robots.libero.env_server import LiberoEnvFacade, make_env
from robots.libero.research.manual import ManualToolkit, availability_prompt
from rpent.dashboard.events import NullDashboardEventSink
from rpent.dashboard.workbench import RunJournal, Workbench, native_catalog
from rpent.memory import MemoryManager
from rpent.planner.api_loop import ApiAgentLoop
from rpent.planner.base import build_api_model
from rpent.utils.logging import init_output_dir


def main():
    root = Path(sys.argv[1]).resolve()
    root.mkdir(parents=True, exist_ok=False)
    shutil.copytree(os.environ["LIBERO_CONFIG_PATH"], root / "libero-config")
    os.environ["LIBERO_CONFIG_PATH"] = str(root / "libero-config")
    init_output_dir(root)
    facade = LiberoEnvFacade(
        make_env(0, 0, "libero_10_task", enable_eef_control=True), meta={}
    )

    class LocalRpc:
        def call(self, name, args=(), kwargs=None, **ignored):
            return facade._rpc[name](*args, **(kwargs or {}))

    toolkit = None
    report = {
        "passed": False,
        "purpose": "two-move interface fixture, not benchmark",
        "max_turns": 6,
        "timeout_s": 300,
    }
    try:
        selected = [
            t
            for t in native_catalog()
            if t["name"] in {"view_env_state", "move_eef", "finish"}
        ]
        toolkit = ManualToolkit(
            selected=selected,
            journal=RunJournal(root),
            runtime_kwargs={
                "env": LiberoEnvClient(LocalRpc(), expected_meta={}),
                "model": None,
                "sam3_client": None,
            },
            dashboard_events=NullDashboardEventSink(),
            memory=MemoryManager(root / "memory"),
            state_output_dir=root,
        )
        profile_path = Path(
            "/home/zwy/work/embodied_harness/experiments/qwen-max-v3-screen3-20261107/a/workbench.json"
        )
        wb = Workbench(json.loads(profile_path.read_text()))
        with wb.environment("qwen3.8-max") as profile:
            planner = ApiAgentLoop(
                model=build_api_model(profile["model"], profile["base_url"]),
                dashboard_events=NullDashboardEventSink(),
                reasoning_effort="medium",
                max_tokens=4096,
                timeout_s=300,
            )
            result = planner.solve(
                system_prompt=availability_prompt(selected)
                + "Use only the supplied tools and observed images/robot state.",
                user_message=(
                    "This is an interface check, not a benchmark task. First view the current scene. "
                    "Choose and execute one small free-space EEF movement from the images and measured pose. "
                    "Inspect the returned images and actual pose, then choose and execute a second small movement. "
                    "Inspect that feedback and call finish with your assessment of the control feedback. "
                    "Keep the gripper open and do not attempt the full object task."
                ),
                toolkit=toolkit,
                max_turns=6,
            )
        events = [
            json.loads(l) for l in (root / "events.jsonl").read_text().splitlines()
        ]
        responses = [
            e["payload"]
            for e in events
            if e["kind"] == "tool_response" and e["payload"]["name"] == "move_eef"
        ]
        report.update(
            stats=result.stats,
            error=result.error,
            finish=result.finish_result,
            native_success=toolkit.solved(),
            actions=[
                {
                    "step": r["result"].get("step"),
                    "images": len(r.get("images", [])),
                    "error": r["result"].get("error"),
                    "receipt": r["result"].get("log", {}).get("result"),
                }
                for r in responses
            ],
        )
        report["passed"] = bool(
            len(responses) == 2
            and not result.error
            and result.finish_result
            and all(
                not r["result"].get("error") and len(r.get("images", [])) >= 2
                for r in responses
            )
        )
        assert report["passed"], (
            "Inspect summary and raw logs; never classify this fixture as benchmark success"
        )
    finally:
        if toolkit is not None:
            toolkit.close()
        facade.close()
        report["environment_closed"] = True
        (root / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
