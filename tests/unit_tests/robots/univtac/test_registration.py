# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Lightweight discovery, RPC connection and outcome provenance checks."""

import argparse
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from robots.univtac import env_client, robot_spec
from rpent.dashboard.events import NullDashboardEventSink


def arguments(tmp_path, *extra):
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(tmp_path / "run"))
    parser.set_defaults(
        model="gpt-6-astra",
        planner="codex_sdk",
        base_url=None,
        reasoning_effort="high",
        max_tokens=4096,
    )
    robot_spec._add_cli_args(parser, use_dashboard=True)
    return parser.parse_args(list(extra))


def test_fresh_discovery_and_native_catalog_do_not_import_isaac():
    script = """
import sys
from rpent.robots import enumerate_robots, get_robot_spec
from robots.univtac import native_catalog
assert 'univtac' in enumerate_robots()
assert get_robot_spec('univtac').name == 'univtac'
catalog = native_catalog()
names = [t['name'] for t in catalog]
assert len(names) == len(set(names))
assert {'move_eef', 'observe', 'depth_points', 'tactile_stats', 'finish'} <= set(names)
assert all(not any(n == p or n.startswith(p + '.') for n in sys.modules)
           for p in ['isaaclab', 'isaacsim', 'omni', 'tacex'])
"""
    result = subprocess.run(
        [sys.executable, "-c", script], text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr


def test_task_parser_and_runtime_requirements_fail_before_start(tmp_path):
    args = arguments(
        tmp_path,
        "--task",
        "2",
        "--seed",
        "7",
        "--env-endpoint",
        "http://127.0.0.1:1234",
    )
    robot_spec._validate_args(args)
    config = robot_spec._parse_config(args)
    assert config.task_desc == {
        "suite": "univtac",
        "task": 2,
        "task_name": "pull_out_key",
        "seed": 7,
    }
    assert "Extract" in config.prompt_vars["instruction"]
    with pytest.raises(ValueError, match="seed"):
        robot_spec._parse_config(arguments(tmp_path, "--seed", "-1"))
    with pytest.raises(ValueError):
        robot_spec._validate_args(arguments(tmp_path))
    with pytest.raises(SystemExit):
        arguments(tmp_path, "--task", "3")


def test_factory_keeps_memory_readonly_and_selection_explicit(tmp_path, monkeypatch):
    from robots.univtac import toolkit
    from rpent.tools.common import CommonTools

    captured = {}
    selected = [tool for tool in toolkit.native_catalog() if tool["name"] == "finish"]

    def fake_toolkit(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(**kwargs, list_tools=lambda: (CommonTools.finish,))

    monkeypatch.setattr(toolkit, "UniVTACToolkit", fake_toolkit)
    monkeypatch.setattr(
        "rpent.dashboard.workbench.source_snapshot",
        lambda *a: {"revision": "test", "files": {}},
    )
    args = arguments(tmp_path)
    config = robot_spec._parse_config(args)
    config.prompt_vars["manual_tools"] = selected
    robot_spec._prepare_memory(args, config)
    config.prompt_vars["run_journal"] = object()
    api = robot_spec.get_toolkit(
        runtime_kwargs={"env": object()},
        dashboard_events=NullDashboardEventSink(),
        config=config,
    )
    assert captured["selected"] is selected
    assert captured["journal"] is config.prompt_vars["run_journal"]
    assert api.memory.root == (config.output_dir / "empty-memory").resolve()
    with pytest.raises(PermissionError):
        api.memory.authorize_write(api.memory.root / "MEMORY.md")


class FakeRpc:
    def __init__(self, *, robot="univtac", task_name="insert_hole"):
        self.meta = {"robot": robot, "task_name": task_name, "seed": 0}
        self.calls = []
        self.observations = [{"control_step": i} for i in range(3)]

    def call(self, name, **kwargs):
        self.calls.append((name, kwargs))
        if name == "env.get_env_meta":
            return self.meta
        if name == "env.reset":
            return self.observations[0], {"control_step": 0}
        if name == "env.chunk_step":
            return self.observations[1:], 0.0, False, False, {"executed_commands": 2}
        if name == "env.raw_obs":
            return self.observations[-1]
        if name == "env.evaluator_state":
            return {"official_success": False}
        if name == "env.close":
            return None
        raise AssertionError(name)


def test_client_resets_requested_task_and_caches_final_chunk_frame():
    rpc = FakeRpc()
    client = env_client.UniVTACEnvClient(rpc, task_name="insert_hole", seed=7)
    assert rpc.calls[1][1]["kwargs"] == {"task_name": "insert_hole", "seed": 7}
    assert client.last_obs == {"control_step": 0}
    client.chunk_step([[0] * 8] * 2, return_all_frames=True)
    assert client.last_obs == {"control_step": 2}
    assert client.get_observation() == client.last_obs
    assert client.evaluator_state() == {"official_success": False}
    client.close()
    assert rpc.calls[-1][0] == "env.close"


@pytest.mark.parametrize("meta", [{"robot": "libero"}, {"task_name": "pull_out_key"}])
def test_client_rejects_wrong_borrowed_server_before_reset(meta):
    rpc = FakeRpc(**meta)
    with pytest.raises((ValueError, RuntimeError), match="meta|task|robot|server"):
        env_client.UniVTACEnvClient(rpc, task_name="insert_hole", seed=0)
    assert not any(name == "env.reset" for name, _ in rpc.calls)


@pytest.mark.parametrize("borrowed", [True, False])
def test_runtime_tracks_owned_daemon_and_keeps_borrowed_server_unowned(
    tmp_path, monkeypatch, borrowed
):
    created = []

    class FakeDaemon:
        def __init__(self, **kwargs):
            self.settings = kwargs
            self.started = False
            created.append(self)

        def start(self):
            self.started = True

    monkeypatch.setattr(robot_spec, "ProcessDaemon", FakeDaemon)
    monkeypatch.setattr(robot_spec, "pick_free_port", lambda: 18760)
    monkeypatch.setattr(robot_spec, "HttpRpcClient", lambda endpoint: endpoint)
    monkeypatch.setattr(
        robot_spec, "try_wait_server", lambda *a, post_fn, **kw: post_fn()
    )
    monkeypatch.setattr(
        env_client,
        "UniVTACEnvClient",
        lambda rpc, **kwargs: {"endpoint": rpc, **kwargs},
    )
    extra = (
        ["--env-endpoint", "http://127.0.0.1:3456"]
        if borrowed
        else ["--univtac-root", "/bench", "--univtac-python", "/sim/python"]
    )
    args = arguments(tmp_path, *extra)
    owned, runtime = robot_spec._init_runtime(args, tmp_path, NullDashboardEventSink())
    assert runtime["env"]["task_name"] == "insert_hole"
    if borrowed:
        assert not created and not owned
        assert runtime["env"]["endpoint"] == "http://127.0.0.1:3456"
    else:
        assert owned == created and created[0].started
        cmd = created[0].settings["cmd"]
        assert cmd[:3] == ["/sim/python", "-m", "robots.univtac.env_server"]
        assert cmd[cmd.index("--root") + 1] == "/bench"
        assert runtime["env"]["endpoint"] == "http://127.0.0.1:18760"


def test_finalizer_uses_official_success_without_libero_release_requirement(tmp_path):
    (tmp_path / "outcome.json").write_text(
        json.dumps(
            {
                "finish": {"status": "success"},
                "stable_placement": "unverified",
                "release_count": 0,
            }
        )
    )
    robot_spec._finalize_run(
        SimpleNamespace(output_dir=tmp_path, environment_success=False)
    )
    result = json.loads((tmp_path / "outcome.json").read_text())
    assert result["environment_success"] is False
    assert result["finish"]["status"] == "success"
    assert result["release_required"] is False
    assert "stable_placement" not in result and "release_count" not in result
