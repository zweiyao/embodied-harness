# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Scripted CLI validation preserves the caller's environment."""

import json
import os
from contextlib import contextmanager
from types import SimpleNamespace

from tests.e2e_tests import common
from tests.e2e_tests.offline_planner_server import ScriptedToolCall


def test_scripted_chain_inherits_environment(tmp_path, monkeypatch):
    executable = tmp_path / "bin/python"
    executable.parent.mkdir()
    executable.with_name("rpent").touch()
    monkeypatch.setattr(common.sys, "executable", str(executable))
    output = tmp_path / "run"
    before = dict(os.environ)

    @contextmanager
    def server(script):
        yield SimpleNamespace(
            base_url="http://127.0.0.1:1", assert_complete=lambda: None
        )

    def run(command, *, cwd, env, check):
        assert env == {**before, "OPENAI_API_KEY": common.OFFLINE_MODEL_NAME}
        output.mkdir()
        (output / "transcript_fixture.json").write_text(
            json.dumps({"finish": {"_finish": True, "status": "stuck"}})
        )
        (output / "states.json").write_text(
            json.dumps(
                {
                    "steps": [
                        {
                            "command": {"action": "pi0_pick"},
                            "result": {"simulator_steps": 2},
                        }
                    ]
                }
            )
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(common, "OfflinePlannerServer", server)
    monkeypatch.setattr(common.subprocess, "run", run)
    result = common.run_scripted_policy_chain(
        robot="robodojo",
        robot_argv=[],
        output_dir=output,
        action=ScriptedToolCall("pi0_pick", {"max_chunks": 1}),
        action_count_field="simulator_steps",
    )
    assert result["simulator_action_count"] == 2
    assert dict(os.environ) == before
