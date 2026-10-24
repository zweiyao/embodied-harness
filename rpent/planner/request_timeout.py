# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Opt-in response limits and an SDK wait clock that excludes native tools."""

from __future__ import annotations

import asyncio
import math
import threading
import time
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any


class ModelRequestTimeout(RuntimeError):
    """The configured model-response waiting budget expired."""


def request_timeout(toolkit: Any) -> float | None:
    """Read an explicit toolkit limit without changing other environments."""
    value = getattr(toolkit, "model_request_timeout_s", None)
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError("model_request_timeout_s must be finite and positive")
    return float(value)


class ModelWaitClock:
    """Bound SDK wait segments, not unobservable provider HTTP requests."""

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self._lock = threading.Lock()
        self._tools = 0
        self._started = time.monotonic()

    def reset(self) -> None:
        """Start a fresh wait segment after a response or the last native tool."""
        with self._lock:
            self._started = time.monotonic()

    def remaining(self) -> float | None:
        """Return seconds left, or None while native tools are executing."""
        with self._lock:
            if self._tools:
                return None
            return max(0.0, self.seconds - (time.monotonic() - self._started))

    def tool_started(self) -> None:
        with self._lock:
            self._tools += 1

    def tool_finished(self) -> None:
        with self._lock:
            self._tools -= 1
            if not self._tools:
                self._started = time.monotonic()

    def error(self) -> ModelRequestTimeout:
        return ModelRequestTimeout(
            f"Codex SDK model-wait interval timed out after {self.seconds:g}s "
            "(excludes RPent tool execution; provider request boundaries unavailable)"
        )

    async def watch(self) -> None:
        while True:
            remaining = self.remaining()
            if remaining == 0:
                raise self.error()
            await asyncio.sleep(0.05 if remaining is None else min(0.05, remaining))


class TimedToolkit:
    """Delegate MCP operations, pausing only during actual toolkit execution."""

    def __init__(self, toolkit: Any, clock: ModelWaitClock) -> None:
        self._toolkit, self._clock = toolkit, clock

    def __getattr__(self, name: str) -> Any:
        return getattr(self._toolkit, name)

    def execute_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self._clock.tool_started()
        try:
            return self._toolkit.execute_tool(name, arguments)
        finally:
            self._clock.tool_finished()


async def timed_sdk_events(
    events: AsyncIterator[Any], clock: ModelWaitClock | None
) -> AsyncIterator[Any]:
    """Consume an SDK stream while an independent wait watchdog runs."""
    if clock is None:
        async for event in events:
            yield event
        return
    watchdog = asyncio.create_task(clock.watch())
    pending = None
    iterator = events.__aiter__()
    try:
        while True:
            pending = asyncio.create_task(anext(iterator))
            done, _ = await asyncio.wait(
                (pending, watchdog), return_when=asyncio.FIRST_COMPLETED
            )
            if watchdog in done:
                await watchdog
            try:
                yield pending.result()
            except StopAsyncIteration:
                return
    finally:
        for task in (pending, watchdog):
            if task is not None:
                task.cancel()
                with suppress(
                    asyncio.CancelledError, ModelRequestTimeout, StopAsyncIteration
                ):
                    await task
        close = getattr(iterator, "aclose", None)
        if close is not None:
            await close()
