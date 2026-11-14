# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Explicit dev-only unlimited actions preserve ordinary evaluation budgets."""

import json
from types import SimpleNamespace

import numpy as np
import pytest

from robots.robodojo import env_server, robot_spec, tasks, tools
from rpent.evaluation import RunFinalizationContext
from rpent.session import EnvState


@pytest.mark.parametrize("limit", [-1, 0])
def test_eval_fair_rejects_nonpositive_action_limits(limit):
    args = env_server.build_parser().parse_args(
        ["--mode", "eval-fair", "--max-episode-steps", str(limit)]
    )
    with pytest.raises(ValueError):
        env_server.build_config(args)


def test_explicit_zero_is_preserved_in_dev_config():
    args = env_server.build_parser().parse_args(["--max-episode-steps", "0"])
    cfg = env_server.build_config(args)
    assert cfg.max_episode_steps == cfg.task_config.max_episode_steps == 0


def test_unlimited_is_rejected_before_eval_fair_allocates(agent_module):
    with pytest.raises(ValueError, match="dev diagnostics"):
        agent_module.RoboDojoAgentEnv(
            None, meta={"mode": "eval-fair", "max_episode_steps": 0}
        )


def test_unlimited_rpc_continues_past_task_cap_and_reports_json_null(
    monkeypatch, agent_module, make_agent
):
    native = SimpleNamespace(
        take_action_cnt=[199], step_lim=200, is_success=lambda env_idx: False
    )

    def apply(action, action_type, *, eval_fair):
        native.take_action_cnt[0] += 1

    agent = make_agent(
        native,
        meta={"max_episode_steps": 0},
        slot=SimpleNamespace(env=native, apply_action=apply),
    )
    agent._configure_action_limit()
    agent._configure_action_limit()  # Repeated/reset setup must not int(infinity).
    monkeypatch.setattr(agent_module, "_obs_dict", lambda *a: {"state": {}})
    monkeypatch.setattr(agent_module, "_reward_details", lambda *a: {"reward": 0})
    for _ in range(3):
        _, _, done, info = agent.step_native(np.zeros(14))
        assert not done and info["status"]["step_limit"] is None
        json.dumps(info, allow_nan=False)
    assert native.take_action_cnt == [202]
    assert agent.get_env_meta() == {"max_episode_steps": 0}
    assert agent.get_reward_details()["step_limit"] is None


def test_unlimited_configuration_is_tagged_and_flash_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(tasks, "validate_task", lambda *a: None)
    monkeypatch.setattr(tasks, "task_summary", lambda *a: {})
    args = SimpleNamespace(
        task="align_blocks",
        layout=0,
        max_episode_steps=0,
        planner="codex",
        memory_dir=str(tmp_path / "memory"),
        output_dir=tmp_path,
        source_root=None,
        env_cfg_type="arx_x5",
        action_type="joint",
        random=False,
    )
    config = robot_spec._parse_config(args)
    assert config.task_desc["diagnostic_unlimited_actions"] is True
    args.planner = "flash"
    with pytest.raises(ValueError, match="dev diagnostics"):
        robot_spec._parse_config(args)


def _obs():
    return {
        "vision": {},
        "state": {
            "left_ee_pose": [0, 0, 0.9, 1, 0, 0, 0],
            "right_ee_pose": [0, 0, 0.9, 1, 0, 0, 0],
            "left_ee_joint_state": [1.0],
            "right_ee_joint_state": [1.0],
        },
    }


def test_policy_chunk_and_state_record_handle_unlimited_budget(tmp_path):
    count = [199]

    def step(action):
        count[0] += 1
        return _obs(), 0, False, {"status": {"step": count[0], "step_limit": None}}

    env = SimpleNamespace(
        get_obs=_obs,
        step=step,
        get_status=lambda: {"step": count[0], "step_limit": None},
        get_task_language=lambda: "Align the blocks.",
    )
    primitives = SimpleNamespace(
        env=env,
        vla_client=SimpleNamespace(predict=lambda obs: np.zeros((2, 14))),
        _check_cancelled=lambda: None,
    )
    result = tools.pi0_pick(primitives, None, max_chunks=2).data
    assert result["simulator_steps"] == 4 and result["chunks_used"] == 2
    assert not result["terminated"] and count[0] == 203
    state = EnvState(tmp_path)
    record = tools.dump_state(primitives, state)
    assert not record.truncated


def test_unlimited_result_is_not_labelled_benchmark_comparable(tmp_path):
    context = RunFinalizationContext(
        output_dir=tmp_path,
        robot_name="robodojo",
        task_desc={
            "task": "align_blocks",
            "layout": 0,
            "diagnostic_unlimited_actions": True,
        },
        environment_success=False,
        agent_error=None,
        elapsed_s=1,
        planner="codex",
        model="gpt-6-astra",
        reasoning_effort="low",
        max_turns=120,
        planner_timeout_s=600,
        finish_result=None,
        stats={},
    )
    result = json.loads(robot_spec.finalize_run(context).read_text())
    assert result["diagnostic_unlimited_actions"] is True
    assert result["benchmark_comparable"] is False
    assert result["success"] is False
