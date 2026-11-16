# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Shared CLI/Dashboard prompt context and provenance recording."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def prepare_prompt_context(args, config) -> None:
    """Supply real runtime values without embedding experience bodies."""
    enabled = bool(getattr(args, "codex_analysis", False) and args.planner == "codex")
    values = config.prompt_vars
    values["output_dir"] = str(config.output_dir)
    values["analysis_enabled"] = enabled
    if enabled:
        values["analysis_workspace"] = str(config.output_dir / "agent")
    for key in ("max_turns", "planner_timeout_s"):
        value = getattr(args, key, None)
        if value is not None:
            values[key] = value


def render_prompt(
    bundle, variant: str, variables, output_dir: Path
) -> tuple[str, dict]:
    """Render and archive exactly the files and text used for this variant."""
    text, info = bundle.render_with_sources(variant, variables=variables)
    path = Path(output_dir) / "prompt-sources.json"
    data = json.loads(path.read_text()) if path.exists() else {"version": 1}
    data[variant] = info
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return text, info


def record_prompts(output_dir: Path, system: str, user: str, *, planner: str) -> None:
    """Keep the saved input and its declared backend roles consistent."""
    root = Path(output_dir)
    (root / "prompts.json").write_text(
        json.dumps({"system": system, "user": user}, ensure_ascii=False, indent=2)
        + "\n"
    )
    path = root / "prompt-sources.json"
    data = json.loads(path.read_text()) if path.exists() else {"version": 1}
    data["roles"] = {
        "system": "developer_instructions" if planner == "codex" else "system_prompt",
        "user": "user_input",
    }
    data["submitted_hashes"] = {
        name: hashlib.sha256(text.encode()).hexdigest()
        for name, text in (("system", system), ("user", user))
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
