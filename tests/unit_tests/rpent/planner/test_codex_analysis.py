# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Native analysis stays separate from robot actions and host evidence."""

from pathlib import Path

import openai_codex
import pytest

from rpent.memory import MemoryManager
from rpent.planner.codex import CodexPlanner
from rpent.planner.codex_workspace import prepare_workspace
from tests.unit_tests.rpent.planner.test_codex_contracts import (
    FakeCodex,
    FakeToolkit,
    RecordingSink,
    install_fake_backend,
)


def test_analysis_profile_enables_native_tools_without_legacy_full_access(
    tmp_path, monkeypatch
):
    config_type = openai_codex.CodexConfig
    install_fake_backend(monkeypatch)
    monkeypatch.setattr(openai_codex, "CodexConfig", config_type)
    toolkit = FakeToolkit()
    toolkit.memory = MemoryManager(tmp_path / "memory")
    planner = CodexPlanner(
        output_dir=str(tmp_path / "run"),
        repo_root=tmp_path / "source",
        dashboard_events=RecordingSink(),
        model="gpt-6-astra",
        reasoning_effort="high",
        analysis_enabled=True,
    )
    result = planner.solve(
        system_prompt="fixed", user_message="current task", toolkit=toolkit, max_turns=3
    )
    assert result.error is None
    codex = FakeCodex.instances[0]
    assert codex.thread_options["developer_instructions"] == "fixed"
    assert codex.thread_options["config"]["model_reasoning_effort"] == "high"
    assert "sandbox" not in codex.thread_options
    text, turn_options = codex.thread.turn_prompts[0]
    assert text == "current task" and "sandbox" not in turn_options
    assert "developer_instructions" not in turn_options
    overrides = codex.config.config_overrides
    assert 'default_permissions="rpent_analysis"' in overrides
    assert overrides.index("features.shell_tool=true") > overrides.index(
        "features.shell_tool=false"
    )
    assert "features.view_image=true" in overrides
    assert 'web_search="disabled"' in overrides
    assert "features.multi_agent=false" in overrides
    root = tmp_path / "run" / "agent"
    assert Path(codex.thread_options["cwd"]) == root
    assert toolkit.memory.authorize_write("scratch/test.py") == root / "scratch/test.py"
    for forbidden in (
        tmp_path / "run" / "observation.json",
        tmp_path / "source" / "source.py",
        toolkit.memory.root / "MEMORY.md",
    ):
        with pytest.raises(PermissionError):
            toolkit.memory.authorize_write(forbidden)
    (root / "escape").symlink_to(tmp_path)
    with pytest.raises(PermissionError):
        toolkit.memory.authorize_write("escape/observation.json")
    assert planner._analysis_workspace is None


@pytest.mark.parametrize("name", ["NOTES.md", "scratch", "workspace.json"])
def test_workspace_rejects_symlinked_outputs(tmp_path, name):
    workspace = tmp_path / "agent"
    workspace.mkdir()
    (workspace / name).symlink_to(tmp_path / "evidence")
    with pytest.raises(ValueError):
        prepare_workspace(tmp_path, None)


def test_dashboard_sdk_separates_fixed_instructions_and_steering(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from rpent.planner.codex import _CodexDashboardSession, _Recorder

    seen = {}

    class Turn:
        async def steer(self, text):
            seen["steer"] = text

        async def stream(self):
            yield {
                "method": "turn/completed",
                "payload": {"turn": {"status": "completed"}},
            }

        async def interrupt(self):
            pass

    class Client:
        def __init__(self, config):
            pass

        async def thread_start(self, **options):
            seen["thread"] = options
            return self

        async def turn(self, text, **options):
            seen["turn"] = (text, options)
            return Turn()

        async def close(self):
            pass

    class Control:
        async def start(self):
            pass

        async def run(self, session):
            await session.submit(SimpleNamespace(text="follow-up"))

        async def complete(self, session):
            pass

    monkeypatch.setattr(openai_codex, "AsyncCodex", Client)

    async def run():
        session = _CodexDashboardSession(
            config=None,
            thread_options={"developer_instructions": "fixed", "model": "gpt-6-astra"},
            turn_options={"effort": "high"},
            recorder=_Recorder(max_turns=5, dashboard_events=RecordingSink()),
            emit_event=lambda event: None,
            control=Control(),
        )
        await session.run("task only")
        await session.close()

    asyncio.run(run())
    assert seen["thread"]["developer_instructions"] == "fixed"
    assert seen["turn"] == ("task only", {"effort": "high"})
    assert seen["steer"] == "follow-up"
