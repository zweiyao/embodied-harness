# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Verbatim seen instructions from pinned UniVTAC 0dafa10262e22f486f160a55d6f11aeab12d8e7b.

The planner can run without the Isaac checkout. The backend checks this snapshot
against instructions/<task>.json before passing the official text to reset.
"""

import json
from pathlib import Path

SEEN_INSTRUCTIONS = {
    "insert_hole": "Explore the inclined hole through contact to determine its orientation, then insert the test tube into the hole.",
    "insert_tube": "Insert the 2.0 cm diameter test tube into the 2.05 cm narrow hole on the inclined surface from the near-center starting position.",
    "pull_out_key": "Rotate the key in the slot until mechanical resistance is sensed, then pull the key straight out.",
}


def load_official_seen(root: Path, task_name: str) -> list[str]:
    """Read official instructions and reject drift from the planner's snapshot."""
    path = root / "instructions" / f"{task_name}.json"
    instructions = json.loads(path.read_text())["seen"]
    if instructions != [SEEN_INSTRUCTIONS[task_name]]:
        raise ValueError(
            f"Official seen instructions differ from the planner snapshot: {path}"
        )
    return instructions
