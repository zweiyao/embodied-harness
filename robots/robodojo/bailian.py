# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Shared model and EEF tool selection for the opt-in RoboDojo API workbench."""

import os

MODELS = ("qwen3.8-flash", "deepseek-v4.1-flash")
C_TOOLS = (
    "move_eef",
    "view_env_state",
    "back_project",
    "segment",
    "query_geometry",
    "read_text_file",
    "write_text_file",
    "list_dir",
    "finish",
)


def model_profile(name):
    if name not in MODELS:
        raise ValueError(f"Unsupported RoboDojo Bailian profile: {name}")
    return {
        "id": f"robodojo-{name}-api",
        "label": f"{name} · API",
        "planner": "api",
        "model": f"openai-chat:{name}",
        "reasoning_effort": "high",
        "bailian_profile": name,
        "fixed_tools": ["native:" + tool for tool in C_TOOLS],
    }


def selected_tools():
    from robots.robodojo.catalog import native_catalog

    if os.environ.get("RPENT_ROBODOJO_GEOMETRY") != "fit":
        raise ValueError(
            "RoboDojo Bailian profiles require RPENT_ROBODOJO_GEOMETRY=fit"
        )
    catalog = {row["name"]: row for row in native_catalog()}
    return [catalog[name] for name in C_TOOLS]
