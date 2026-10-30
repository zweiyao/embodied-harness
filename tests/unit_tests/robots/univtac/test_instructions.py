# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Task prompts preserve upstream wording and detect backend/planner drift."""

import json

import pytest

from robots.univtac import robot_spec
from robots.univtac.instructions import load_official_seen
from tests.unit_tests.robots.univtac.test_registration import arguments

# Upstream instructions/* .json, seen split, commit 0dafa10262e22f486f160a55d6f11aeab12d8e7b.
OFFICIAL = [
    "Explore the inclined hole through contact to determine its orientation, then insert the test tube into the hole.",
    "Insert the 2.0 cm diameter test tube into the 2.05 cm narrow hole on the inclined surface from the near-center starting position.",
    "Rotate the key in the slot until mechanical resistance is sensed, then pull the key straight out.",
]


@pytest.mark.parametrize("task_index,expected", list(enumerate(OFFICIAL)))
def test_planner_task_matches_official_reset_text(tmp_path, task_index, expected):
    name = robot_spec.TASKS[task_index]
    folder = tmp_path / "instructions"
    folder.mkdir()
    path = folder / f"{name}.json"
    path.write_text(json.dumps({"seen": [expected], "unseen": ["Other wording"]}))
    config = robot_spec._parse_config(arguments(tmp_path, "--task", str(task_index)))
    text = config.prompt_vars["instruction"]
    assert text == load_official_seen(tmp_path, name)[0] == expected
    prompt = robot_spec.get_robot_spec().prompts.render(
        "user", variables=config.prompt_vars
    )
    assert prompt.strip().endswith(expected)
    assert "GUIDANCE" not in prompt


@pytest.mark.parametrize(
    "seen",
    [["Extract the held key from its slot."], [], [OFFICIAL[2], "Extra instruction"]],
)
def test_changed_upstream_instruction_is_not_silently_accepted(tmp_path, seen):
    folder = tmp_path / "instructions"
    folder.mkdir()
    (folder / "pull_out_key.json").write_text(json.dumps({"seen": seen}))
    with pytest.raises(ValueError, match="differ from the planner snapshot"):
        load_official_seen(tmp_path, "pull_out_key")
