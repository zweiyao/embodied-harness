# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Tool-free inference through RPent's Codex SDK on the experiment host."""

from __future__ import annotations

import asyncio
import base64
import json
import tempfile
from contextlib import suppress
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace


async def _complete(
    config,
    model: str,
    prompt: str,
    images: list[bytes],
    *,
    output_schema=None,
    on_event=None,
):
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
        options = {"output_schema": output_schema} if output_schema is not None else {}
        turn = await thread.turn(inputs, **options)
        if on_event is None:
            result = await turn.run()
        else:
            items, usage, completed = [], None, None
            stream = turn.stream()
            try:
                async for event in stream:
                    on_event(
                        {
                            "method": event.method,
                            "payload": event.payload.model_dump(
                                mode="json", by_alias=True
                            ),
                        }
                    )
                    payload = event.payload
                    if event.method in {"item/started", "item/completed"}:
                        item = getattr(payload.item, "root", payload.item)
                        if item.type not in {
                            "userMessage",
                            "agentMessage",
                            "reasoning",
                        }:
                            raise RuntimeError(
                                f"Codex attempted an unprovided tool: {item.type}"
                            )
                        if event.method == "item/completed":
                            items.append(item)
                    elif event.method == "thread/tokenUsage/updated":
                        usage = payload.token_usage
                    elif event.method == "turn/completed":
                        completed = payload.turn
            finally:
                if completed is None:
                    with suppress(Exception):
                        await asyncio.wait_for(turn.interrupt(), timeout=5)
                await stream.aclose()
            if completed is None:
                raise RuntimeError("Codex stream ended without turn/completed")
            messages = [item for item in items if item.type == "agentMessage"]
            result = SimpleNamespace(
                status=completed.status,
                error=completed.error,
                items=items,
                usage=usage,
                final_response=messages[-1].text if messages else "",
            )
    if result.status.value != "completed":
        raise RuntimeError(f"Codex turn {result.status.value}: {result.error}")
    for item in result.items:
        item = getattr(item, "root", item)
        if item.type not in {"userMessage", "agentMessage", "reasoning"}:
            raise RuntimeError(f"Codex attempted an unprovided tool: {item.type}")
    usage = result.usage.model_dump(mode="json") if result.usage else {}
    return result.final_response or "", usage


def complete(
    model: str,
    system: str,
    payload: dict,
    images: list[bytes],
    *,
    timeout_s=540,
    output_schema=None,
    on_event=None,
    reasoning_effort="low",
) -> tuple[str, dict]:
    """Reuse RPent's configuration and credential isolation, without any MCP."""
    from rpent.planner.codex import build_codex_config
    from rpent.robots.components.grounding_agent import (
        _check_codex_mcp_isolation,
        _isolated_codex_environment,
    )

    if reasoning_effort not in {"minimal", "low", "medium", "high", "xhigh"}:
        raise ValueError("Unsupported maker reasoning effort")

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
                f'model_reasoning_effort="{reasoning_effort}"',
            ),
        )
        _check_codex_mcp_isolation(config)
        prompt = request_prompt(system, payload)

        async def bounded():
            return await asyncio.wait_for(
                _complete(
                    config,
                    model,
                    prompt,
                    images,
                    output_schema=output_schema,
                    on_event=on_event,
                ),
                timeout=timeout_s,
            )

        return asyncio.run(bounded())


def request_prompt(system: str, payload: dict) -> str:
    """Return the exact user text supplied to the isolated SDK turn."""
    return (
        system
        + "\nUse only the supplied input. Do not call any tools.\n"
        + json.dumps(payload, allow_nan=False)
    )


def complete_recorded(
    model, system, payload, images, *, output_schema, on_event, timeout_s=180
):
    """One fresh, tool-free SDK turn with returned events; no hard token cap.

    Timeout covers SDK initialization and the turn, plus bounded interruption
    cleanup. The SDK does not expose individual provider retry boundaries.
    """
    return complete(
        model,
        system,
        payload,
        images,
        timeout_s=timeout_s,
        output_schema=output_schema,
        on_event=on_event,
    )
