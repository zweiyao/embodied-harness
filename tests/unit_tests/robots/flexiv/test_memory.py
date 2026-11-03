# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Flexiv experience is discoverable without injecting it into policy prompts."""

from pathlib import Path

import pytest

from robots.flexiv.robot_spec import get_robot_spec
from rpent.memory import MemoryManager
from rpent.tools.common import CommonTools


def test_insertion_experience_is_indexed_and_loaded_only_by_file_tool(monkeypatch):
    repo = Path(__file__).resolve().parents[4]
    monkeypatch.setenv("RPENT_REPO_ROOT", str(repo))
    root = repo / "memory" / "flexiv"
    memory = MemoryManager(root, memory_access="read_only")
    assert memory.validate() == []
    tools = CommonTools(memory=memory)
    index = tools.read_text_file(path=str(root / "MEMORY.md")).data["content"]
    leaf = "global/insertion_grasp_revalidation.md"
    assert f"]({leaf})" in index
    experience = tools.read_text_file(path=str(root / leaf)).data["content"]
    assert "confidence: single-shot" in experience
    assert "35a7fbd1bfabd254f93c" in experience
    with pytest.raises(PermissionError):
        memory.authorize_write(root / leaf)

    spec = get_robot_spec()
    variables = {
        "control_mode": "rdk",
        "memory_dir": root,
        "instruction": "Insert the USB plug",
        "output_dir": "/tmp/run",
    }
    system = spec.prompts.render("system", variables=variables)
    user = spec.prompts.render("user", variables=variables)
    assert "INSERTION" not in system
    assert "MEMORY.md" not in system
    assert str(root / "MEMORY.md") in user
    assert "read_text_file is enabled" in user
    for prompt in (system, user):
        assert "35a7fbd1bfabd254f93c" not in prompt
        assert "11.95" not in prompt
        assert "TCP—物体关系" not in prompt

    default_variables = {k: v for k, v in variables.items() if k != "memory_dir"}
    assert str(root / "MEMORY.md") in spec.prompts.render(
        "user", variables=default_variables
    )
