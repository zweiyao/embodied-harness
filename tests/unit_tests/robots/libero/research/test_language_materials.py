# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Language-only guidance stays isolated from original memory and active runs."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from robots.libero.prompt_bundle import system_prompt, user_prompt
from robots.libero.research.language_materials import freeze_materials
from rpent.memory import MemoryManager
from rpent.prompt.utils import format_prompt
from rpent.tools.common import CommonTools


def builder():
    root = Path(__file__).resolve().parents[5]
    spec = importlib.util.spec_from_file_location(
        "language_builder",
        root / "examples/manual-workbench/build_language_materials.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_preserves_evidence_and_freezes_prompt(tmp_path):
    source = tmp_path / "source"
    (source / "global").mkdir(parents=True)
    (source / "task-family").mkdir()
    (source / "task-specific").mkdir()
    original = source / "global/basket.md"
    original.write_text(
        "---\ntitle: Basket\nconfidence: single-shot\n---\nCarry with `gripper:+1`; `step_clip=0.008-0.012`. Never copy old coordinates.\n"
    )
    audit = {
        "task_language": "Put milk in basket",
        "terminated": True,
        "perception_table": [[1, 2], [3, 4]],
        "strategy_notes": "Use pi0_pick('pick up the milk', max_chunks=12).",
    }
    (source / "task-specific/a.json").write_text(json.dumps(audit))
    (source / "task-specific/a_recipe.jsonl").write_text(
        json.dumps({"action": "move_to", "xyz": [1, 2, 3], "gripper": 1}) + "\n"
    )
    before = hashlib.sha256(original.read_bytes()).hexdigest()
    package = tmp_path / "package"
    builder().build(source, package)
    narrative = (package / "memory/task-specific/a.md").read_text()
    assert "pi0_pick" not in narrative and "move_to" not in narrative
    assert "Put milk in basket" in narrative and "completion: yes" in narrative
    assert "(1, 2)" in narrative and "(3, 4)" in narrative
    assert "(1, 2, 3)" in narrative and "keep the gripper closed" in narrative
    assert not list((package / "memory").rglob("*.json*"))
    assert hashlib.sha256(original.read_bytes()).hexdigest() == before
    variables = {
        "suite": "libero_object",
        "task": 0,
        "seed": 0,
        "output_dir": str(tmp_path / "run"),
    }
    freeze_materials(package, tmp_path / "run", variables)
    system = format_prompt(system_prompt(variables), variables=variables)
    user = format_prompt(user_prompt(variables), variables=variables)
    assert str(tmp_path / "run/language-materials/memory") in system
    assert "libero_object" in user and "{{" not in system + user
    assert "back_project" not in system + user
    # Edits to a future package cannot change an already frozen experiment.
    (package / "system.md").write_text("changed")
    assert format_prompt(system_prompt(variables), variables=variables) == system
    with pytest.raises(ValueError, match="Changed language material"):
        freeze_materials(package, tmp_path / "next", {})


def test_legacy_prompt_is_unchanged_without_package():
    assert isinstance(system_prompt({"memory_profile": "hf"}), dict)
    assert "BEGIN" in user_prompt({})


def test_frozen_package_does_not_copy_adjacent_raw_recipes(tmp_path):
    source = tmp_path / "package"
    (source / "memory").mkdir(parents=True)
    names = ["system.md", "user.md", "guide.md", "memory/MEMORY.md"]
    for name in names:
        (source / name).write_text("prose")
    (source / "old_recipe.jsonl").write_text('{"action":"move_to"}')
    manifest = {
        "version": "test",
        "files": {n: hashlib.sha256(b"prose").hexdigest() for n in names},
    }
    (source / "manifest.json").write_text(json.dumps(manifest))
    variables = {}
    freeze_materials(source, tmp_path / "run", variables)
    assert not (Path(variables["language_materials"]) / "old_recipe.jsonl").exists()


def test_frozen_root_notes_are_readable_through_actual_file_tool(tmp_path):
    source = tmp_path / "package"
    (source / "memory/libero").mkdir(parents=True)
    contents = {
        "system.md": "system",
        "user.md": "user",
        "guide.md": "guide",
        "memory/MEMORY.md": "[note](note.md)",
        "memory/note.md": "conditional evidence",
        "memory/libero/note.md": "unsupported nested layout",
    }
    for name, text in contents.items():
        (source / name).write_text(text)
    (source / "manifest.json").write_text(
        json.dumps(
            {
                "version": "read-policy-test",
                "files": {
                    name: hashlib.sha256(text.encode()).hexdigest()
                    for name, text in contents.items()
                },
            }
        )
    )
    variables = {}
    freeze_materials(source, tmp_path / "run", variables)
    root = Path(variables["memory_dir"])
    file_tools = CommonTools(memory=MemoryManager(root))
    assert (
        file_tools.read_text_file(path=str(root / "note.md")).data["content"]
        == "conditional evidence"
    )
    with pytest.raises(PermissionError, match="reading this memory path is denied"):
        file_tools.read_text_file(path=str(root / "libero/note.md"))
    with pytest.raises(PermissionError, match="writing to memory is denied"):
        file_tools.write_text_file(path=str(root / "note.md"), content="changed")
