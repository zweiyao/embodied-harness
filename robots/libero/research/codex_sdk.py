# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Tool-free inference through RPent's Codex SDK on the experiment host."""

from __future__ import annotations

import asyncio
import base64
import json
import tempfile
from dataclasses import replace
from pathlib import Path


async def _complete(config, model: str, prompt: str, images: list[bytes]):
    import openai_codex

    async with openai_codex.AsyncCodex(config) as codex:
        thread = await codex.thread_start(
            model=model,
            approval_mode=openai_codex.ApprovalMode.deny_all,
            sandbox=openai_codex.Sandbox.read_only,
            ephemeral=True,
        )
        inputs = [openai_codex.TextInput(prompt)] + [
            openai_codex.ImageInput(
                "data:image/png;base64," + base64.b64encode(image).decode("ascii")
            )
            for image in images
        ]
        turn = await thread.turn(inputs)
        result = await turn.run()
    if result.status.value != "completed":
        raise RuntimeError(f"Codex turn {result.status.value}: {result.error}")
    for item in result.items:
        item = getattr(item, "root", item)
        if item.type not in {"userMessage", "agentMessage", "reasoning"}:
            raise RuntimeError(f"Codex attempted an unprovided tool: {item.type}")
    usage = result.usage.model_dump(mode="json") if result.usage else {}
    return result.final_response or "", usage


def complete(
    model: str, system: str, payload: dict, images: list[bytes]
) -> tuple[str, dict]:
    """Reuse RPent's configuration and credential isolation, without any MCP."""
    from rpent.planner.codex import build_codex_config
    from rpent.robots.components.grounding_agent import (
        _check_codex_mcp_isolation,
        _isolated_codex_environment,
    )

    with tempfile.TemporaryDirectory(prefix="sensor-teacher-") as directory:
        root = Path(directory)
        cwd, home = root / "work", root / "codex"
        cwd.mkdir()
        home.mkdir()
        config = build_codex_config(
            mcp_url=None, base_url=None, api_key=None, cwd=str(cwd)
        )
        env, overrides = _isolated_codex_environment(
            config.env, home, config.config_overrides
        )
        # The fresh home excludes user MCP, skills and instructions; only normal
        # remote credentials are shared, so refresh remains on the same host.
        disabled = (
            "shell_tool",
            "unified_exec",
            "view_image",
            "view_image_tool",
            "js_repl",
            "code_mode",
            "multi_agent",
            "multi_agent_v2",
            "image_generation",
            "goals",
            "hooks",
            "browser_use",
            "computer_use",
        )
        config = replace(
            config,
            env=env,
            config_overrides=overrides
            + config.config_overrides
            + tuple(f"features.{name}=false" for name in disabled)
            + (
                "tools.update_plan.enabled=false",
                "tools.experimental_request_user_input.enabled=false",
                'web_search="disabled"',
                "apps._default.enabled=false",
                'model_reasoning_effort="low"',
            ),
        )
        _check_codex_mcp_isolation(config)
        prompt = (
            system
            + "\nUse only the supplied input. Do not call any tools.\n"
            + json.dumps(payload, allow_nan=False)
        )

        async def bounded():
            async with asyncio.timeout(540):
                return await _complete(config, model, prompt, images)

        return asyncio.run(bounded())
