# Copyright 2026 The RPent Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tool-free model access for saved-trajectory decision review."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from rpent.evaluation.decision_summary import PROMPT, DecisionSummary, summary_schema
from rpent.utils.logging import get_logger

logger = get_logger("decision_summary")


def review_action(
    run_dir: Path, packet: dict[str, Any], model: str, timeout_s: int
) -> tuple[DecisionSummary, dict]:
    """Supply only pre-action evidence, in an isolated home with tools disabled."""
    import openai_codex

    from rpent.planner.codex import build_probe_config
    from rpent.robots.components.grounding_agent import (
        _check_codex_mcp_isolation,
        _isolated_codex_environment,
    )

    inputs = [
        openai_codex.TextInput(
            PROMPT
            + "\n"
            + json.dumps(
                {
                    **{k: packet[k] for k in ("action", "before", "images")},
                    "attached_image_count": len(packet["images"]),
                },
                ensure_ascii=False,
            )
        )
    ]
    for image in packet["images"]:
        path = (run_dir / image["artifact"]).resolve()
        if not path.is_relative_to(run_dir.resolve() / "inputs"):
            raise ValueError("Image reference outside the journal input directory")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != path.stem:
            raise ValueError("Journal image hash mismatch")
        inputs.append(
            openai_codex.TextInput(
                f"Image evidence: {image['id']} / {image['artifact']}"
            )
        )
        inputs.append(
            openai_codex.ImageInput(
                "data:image/png;base64," + base64.b64encode(data).decode()
            )
        )

    with tempfile.TemporaryDirectory(prefix="rpent-decision-review-") as directory:
        root = Path(directory)
        work, home = root / "work", root / "codex"
        work.mkdir()
        home.mkdir()
        config = build_probe_config()
        env, overrides = _isolated_codex_environment(
            config.env, home, config.config_overrides
        )
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
            cwd=str(work),
            env=env,
            config_overrides=overrides
            + config.config_overrides
            + tuple(f"features.{name}=false" for name in disabled)
            + (
                "tools.update_plan.enabled=false",
                "tools.experimental_request_user_input.enabled=false",
                'web_search="disabled"',
                "apps._default.enabled=false",
            ),
        )
        _check_codex_mcp_isolation(config)
        started = time.monotonic()
        answer, usage = asyncio.run(
            asyncio.wait_for(
                _review(config, inputs, model, summary_schema(packet)),
                timeout=timeout_s,
            )
        )
    usage["elapsed_s"] = round(time.monotonic() - started, 3)
    usage["input_image_count"] = len(packet["images"])
    return DecisionSummary.model_validate_json(answer), usage


async def _review(
    config: Any, inputs: list, model: str, schema: dict
) -> tuple[str, dict]:
    import openai_codex

    client = openai_codex.AsyncCodex(config)
    answer = ""
    usage: dict[str, Any] = {"input_tokens": None, "output_tokens": None}
    completed = False
    try:
        options = {
            "model": model,
            "cwd": config.cwd,
            "approval_mode": openai_codex.ApprovalMode.deny_all,
            "sandbox": openai_codex.Sandbox.read_only,
        }
        thread = await client.thread_start(**options)
        turn = await thread.turn(inputs, **options, effort="low", output_schema=schema)
        async for event in turn.stream():
            payload = event.payload.model_dump(mode="json")
            if event.method in {"error", "fatal"}:
                logger.warning("Reviewer model event: %s", payload)
                if not payload.get("will_retry", False):
                    raise RuntimeError(f"Reviewer model error: {payload}")
            if event.method == "item/completed":
                item = payload["item"]
                if item["type"] in {
                    "mcpToolCall",
                    "dynamicToolCall",
                    "commandExecution",
                    "fileChange",
                }:
                    raise RuntimeError("Review attempted to use a tool")
                if item["type"] == "agentMessage":
                    answer = item["text"]
            elif event.method == "thread/tokenUsage/updated":
                total = payload["token_usage"]["total"]
                usage = {
                    "input_tokens": total["input_tokens"],
                    "output_tokens": total["output_tokens"],
                    "cached_input_tokens": total.get("cached_input_tokens"),
                }
            elif event.method == "turn/completed":
                if payload["turn"]["status"] != "completed":
                    raise RuntimeError(f"Review ended: {payload['turn']['status']}")
                completed = True
    finally:
        await asyncio.wait_for(client.close(), timeout=15)
    if not completed:
        raise RuntimeError("Review stream ended without completion")
    return answer, usage
