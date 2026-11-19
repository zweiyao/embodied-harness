# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Episode-local handoffs for the optional RoboDojo dashboard experiment."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

INSTRUCTIONS = (
    "For short or tightly coupled work, continue directly. At a verified subgoal "
    "boundary, update TASK_BOARD.md with the native instruction, completed subgoals "
    "and evidence steps, facts needed later, and the next goal or uncertainty. "
    "Then end this turn with BOARD_READY. After handoff, read the board and "
    "observe the current state before moving."
)


@dataclass
class TaskBoard:
    path: Path
    mode: str
    last_digest: str | None = None

    def accept_revision(self) -> bool:
        """Accept only a new, readable, nonempty episode-local board."""
        if self.path.is_symlink() or not self.path.is_file():
            return False
        try:
            content = self.path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            return False
        digest = hashlib.sha256(content.encode()).hexdigest()
        if not content or digest == self.last_digest:
            return False
        self.last_digest = digest
        return True
