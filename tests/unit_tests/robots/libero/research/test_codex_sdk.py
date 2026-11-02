# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Direct SDK inference keeps image input and excludes environment tools."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import openai_codex
import pytest
from openai_codex.generated.v2_all import TurnStatus

from robots.libero.research import codex_sdk
from robots.libero.research.models import Model


@pytest.mark.parametrize(
    ("status", "item_type", "error"),
    [
        ("completed", "agentMessage", None),
        ("failed", "agentMessage", "Codex turn failed"),
        ("interrupted", "agentMessage", "Codex turn interrupted"),
        ("completed", "commandExecution", "unprovided tool"),
    ],
)
def test_sdk_direct_inference_boundary(tmp_path, monkeypatch, status, item_type, error):
    home = tmp_path / "existing-codex"
    home.mkdir()
    (home / "config.toml").write_text(
        '[mcp_servers.forbidden]\nurl="http://127.0.0.1:1/mcp"\n'
    )
    (home / "auth.json").write_text("{}")
    monkeypatch.setenv("CODEX_HOME", str(home))
    seen = {}

    class FakeCodex:
        def __init__(self, config):
            seen["config"] = config
            isolated = Path(config.env["CODEX_HOME"])
            assert isolated != home
            assert not (isolated / "config.toml").exists()
            assert (isolated / "auth.json").resolve() == home / "auth.json"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            seen["closed"] = True

        async def thread_start(self, **kwargs):
            seen["thread"] = kwargs
            return self

        async def turn(self, inputs):
            seen["inputs"] = inputs
            return self

        async def run(self):
            return SimpleNamespace(
                status=TurnStatus(status),
                error="test failure" if status != "completed" else None,
                items=[SimpleNamespace(type=item_type)],
                usage=SimpleNamespace(
                    model_dump=lambda **_: {"total": {"total_tokens": 17}}
                ),
                final_response='{"tool":"finish","arguments":{}}',
            )

    monkeypatch.setattr(openai_codex, "AsyncCodex", FakeCodex)
    monkeypatch.setattr(
        "rpent.robots.components.grounding_agent._check_codex_mcp_isolation",
        lambda config: None,
    )
    model = Model({"kind": "codex_sdk", "model": "gpt-6-astra"})
    if error:
        with pytest.raises(RuntimeError, match=error):
            model.complete("test prompt", {"step": 1}, [b"first", b"second"])
    else:
        answer, request = model.complete(
            "test prompt", {"step": 1}, [b"first", b"second"]
        )
        assert answer == {"tool": "finish", "arguments": {}}
        assert request["usage"]["total"]["total_tokens"] == 17
    assert seen["closed"]
    assert seen["thread"]["ephemeral"] is True
    assert seen["thread"]["sandbox"] == openai_codex.Sandbox.read_only
    assert seen["thread"]["approval_mode"] == openai_codex.ApprovalMode.deny_all
    assert len(seen["inputs"]) == 3
    overrides = seen["config"].config_overrides
    assert "features.shell_tool=false" in overrides
    assert not any("mcp_servers" in value for value in overrides)
    assert not Path(seen["config"].cwd).exists()


@pytest.mark.parametrize("cancelled", [False, True])
def test_sdk_completion_timeout_waits_for_cleanup(tmp_path, monkeypatch, cancelled):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "existing-codex"))
    monkeypatch.setattr(
        "rpent.robots.components.grounding_agent._check_codex_mcp_isolation",
        lambda config: None,
    )
    seen = {}

    async def pending(config, *args, **kwargs):
        seen["cwd"] = Path(config.cwd)
        try:
            if cancelled:
                raise asyncio.CancelledError()
            await asyncio.sleep(10)
        finally:
            await asyncio.sleep(0)
            seen["cleaned"] = True

    monkeypatch.setattr(codex_sdk, "_complete", pending)
    expected_error = asyncio.CancelledError if cancelled else asyncio.TimeoutError
    with pytest.raises(expected_error):
        codex_sdk.complete("gpt-6-astra", "test", {}, [], timeout_s=0.01)
    assert seen["cleaned"]
    assert not seen["cwd"].exists()


def test_tool_maker_can_explicitly_select_high_reasoning(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "existing-codex"))
    monkeypatch.setattr(
        "rpent.robots.components.grounding_agent._check_codex_mcp_isolation",
        lambda config: None,
    )
    seen = {}

    async def complete(config, *args, **kwargs):
        seen["overrides"] = config.config_overrides
        return "{}", {}

    monkeypatch.setattr(codex_sdk, "_complete", complete)
    assert codex_sdk.complete(
        "gpt-6-astra", "test", {}, [], reasoning_effort="high"
    ) == ("{}", {})
    assert 'model_reasoning_effort="high"' in seen["overrides"]
    assert 'model_reasoning_effort="low"' not in seen["overrides"]
