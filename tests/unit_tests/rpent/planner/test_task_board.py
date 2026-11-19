# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Exercise subtask boundaries and episode-level SDK counters."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from rpent.planner.codex import _CodexDashboardSession, _Recorder
from rpent.planner.task_board import TaskBoard


@pytest.mark.parametrize("mode", ["same", "fresh"])
def test_handoff_retains_one_budget_and_rejects_duplicate(tmp_path, mode):
    async def run():
        recorder = _Recorder(max_turns=6, dashboard_events=Mock())
        usage = {"input_tokens": 12, "cached_input_tokens": 7, "output_tokens": 2}
        assert recorder._set_usage(usage)
        session = _CodexDashboardSession(
            config=None,
            thread_options={},
            turn_options={},
            recorder=recorder,
            emit_event=Mock(),
            control=Mock(),
        )
        session._codex = AsyncMock()
        session._submit_text = AsyncMock()
        session.board = TaskBoard(tmp_path / "TASK_BOARD.md", mode)
        await session._handoff()
        session._codex.thread_start.assert_not_awaited()
        session.board.path.write_text("Goal and evidence from observation 3.")
        await session._handoff()
        await session._handoff()
        assert session._codex.thread_start.await_count == int(mode == "fresh")
        assert session._submit_text.await_count == 3
        assert recorder._set_usage(usage) == (mode == "fresh")
        assert not recorder._set_usage(usage)
        n = 2 if mode == "fresh" else 1
        assert recorder.turns == n
        assert recorder.usage["total_cached_input_tokens"] == n * 7
        assert recorder.usage["total_input_tokens"] == n * 12
        assert recorder.usage["total_output_tokens"] == n * 2

    asyncio.run(run())


@pytest.mark.parametrize(
    ("text", "status", "budget", "handoffs"),
    [
        ("BOARD_READY", "completed", 2, 1),
        ("BOARD_READY", "interrupted", 2, 0),
        ("BOARD_READY", "failed", 2, 0),
        ("BOARD_READY", "completed", 1, 0),
        ("Episode complete", "completed", 2, 0),
    ],
)
def test_board_boundary_requires_normal_signal_and_remaining_budget(
    tmp_path, text, status, budget, handoffs
):
    async def run():
        recorder = _Recorder(max_turns=budget, dashboard_events=Mock())
        control = Mock()
        control.complete = AsyncMock()
        session = _CodexDashboardSession(
            config=None,
            thread_options={},
            turn_options={},
            recorder=recorder,
            emit_event=recorder.observe,
            control=control,
        )
        session.board = TaskBoard(tmp_path / "TASK_BOARD.md", "fresh")
        session._handoff = AsyncMock()

        async def stream():
            yield {
                "method": "item/completed",
                "payload": {"item": {"type": "agentMessage", "text": text}},
            }
            yield {
                "method": "thread/tokenUsage/updated",
                "payload": {"token_usage": {"input_tokens": 8}},
            }
            yield {"method": "turn/completed", "payload": {"turn": {"status": status}}}

        turn = Mock(stream=stream, interrupt=AsyncMock())
        await session._consume_turn(turn, asyncio.Event())
        assert session._handoff.await_count == handoffs
        assert control.end.called == (budget == 1 or status == "failed")

    asyncio.run(run())
