# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Prompt selection, source provenance and backend-aware capabilities."""

import hashlib
import json
from types import SimpleNamespace

import pytest

from robots.robodojo import prompt_bundle
from rpent.cli.prompts import prepare_prompt_context, record_prompts, render_prompt
from rpent.prompt.composition import task_file
from rpent.robots.prompt_bundle import PromptBundle


def variables(tmp_path, **extra):
    return dict(
        task="arrange_largest_number",
        layout=0,
        env_cfg_type="arx_x5",
        task_summary="scene",
        output_dir=tmp_path,
        mode="dev",
        max_turns=120,
        planner_timeout_s=600,
        **extra,
    )


def test_selected_files_roles_and_memory_are_recoverable(tmp_path):
    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "MEMORY.md").write_text("SENSITIVE_LESSON_BODY")
    bundle = PromptBundle(prompt_bundle.system_prompt, prompt_bundle.user_prompt)
    values = variables(
        tmp_path,
        memory_dir=memory,
        analysis_enabled=True,
        analysis_workspace=tmp_path / "agent",
        manual_tools=[{"name": "move_eef"}],
    )
    system, info = render_prompt(bundle, "system", values, tmp_path)
    user, user_info = render_prompt(bundle, "user", values, tmp_path)
    record_prompts(tmp_path, system, user, planner="codex")
    assert "wxyz" in system and "link6" in system
    assert "eef_absolute" in user and "action_type: joint" not in user
    assert str(memory / "MEMORY.md") in user
    assert "SENSITIVE_LESSON_BODY" not in system + user
    assert "arrange_largest_number.md" in str(user_info)
    assert "put_bottles_into_dustbin.md" not in str(user_info)
    from pathlib import Path

    for item in info["files"] + user_info["files"]:
        assert (
            hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest()
            == item["sha256"]
        )
    saved = json.loads((tmp_path / "prompt-sources.json").read_text())
    assert saved["roles"]["system"] == "developer_instructions"
    assert (
        saved["submitted_hashes"]["user"] == hashlib.sha256(user.encode()).hexdigest()
    )
    assert "control_mode" not in values


def test_memory_requires_real_index_and_reader(tmp_path):
    bundle = PromptBundle(prompt_bundle.system_prompt, prompt_bundle.user_prompt)
    values = variables(tmp_path, memory_dir=tmp_path, manual_tools=[{"name": "finish"}])
    assert "MEMORY.md" not in bundle.render("user", variables=values)
    (tmp_path / "MEMORY.md").write_text("INDEX")
    assert "MEMORY.md" not in bundle.render("user", variables=values)
    values["manual_tools"].append({"name": "read_text_file"})
    assert str(tmp_path / "MEMORY.md") in bundle.render("user", variables=values)


def test_task_selection_rejects_paths_and_symlinks(tmp_path):
    (tmp_path / "default.md").write_text("DEFAULT")
    assert task_file(tmp_path, "missing").name == "default.md"
    with pytest.raises(ValueError):
        task_file(tmp_path, "../secret")
    (tmp_path / "escape.md").symlink_to(tmp_path.parent / "secret.md")
    with pytest.raises(ValueError):
        task_file(tmp_path, "escape")


def test_legacy_factories_and_api_capabilities(tmp_path):
    bundle = PromptBundle(lambda _: {"LEGACY": "Hello {{name}}"}, lambda _: "Task")
    assert bundle.render("system", variables={"name": "robot"}).endswith(
        "Hello robot\n"
    )
    config = SimpleNamespace(output_dir=tmp_path, prompt_vars={})
    args = SimpleNamespace(
        planner="api",
        codex_analysis=True,
        codex_full_access=True,
        max_turns=5,
        planner_timeout_s=60,
    )
    prepare_prompt_context(args, config)
    assert config.prompt_vars["analysis_enabled"] is False
    assert config.prompt_vars["analysis_full_access"] is False
    assert "analysis_workspace" not in config.prompt_vars
    args.planner = "codex"
    prepare_prompt_context(args, config)
    assert config.prompt_vars["analysis_enabled"] is True
    assert config.prompt_vars["analysis_full_access"] is True
    assert config.prompt_vars["analysis_workspace"] == str(tmp_path / "agent")


@pytest.mark.parametrize("eef", [False, True])
def test_robodojo_reobserves_and_replans_after_range_rejection(eef):
    selected = (
        [{"name": "move_eef"}, {"name": "view_env_state"}, {"name": "finish"}]
        if eef
        else []
    )
    bundle = PromptBundle(prompt_bundle.system_prompt, prompt_bundle.user_prompt)
    text, info = bundle.render_with_sources(
        "system", variables={"manual_tools": selected}
    )
    assert "Stop on safety/authorization faults or uncertain execution" not in text
    assert "Do not finish solely for this rejection" in text
    assert "it does not end the episode" in text
    assert "blindly replay the old command" in text and "not reset the scene" in text
    assert any(
        item["path"].endswith("robots/robodojo/prompts/execution_recovery.md")
        for item in info["files"]
    )


@pytest.mark.parametrize("robot", ["flexiv", "univtac", "libero"])
def test_other_robots_keep_default_uncertain_execution_stop(robot):
    from rpent.robots.base import get_robot_spec

    text = get_robot_spec(robot).prompts.render("system", variables={})
    assert "Stop on safety/authorization faults or uncertain execution" in text
    assert "Do not finish solely for this rejection" not in text
