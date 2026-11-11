# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Opt-in Qwen idle retry, buffering each response before exposing tool calls."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from openai import APIConnectionError
from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.models.openai import OpenAIChatModel


class IncompleteModelStream(RuntimeError):
    """The provider closed its stream without a terminal choice."""


class ModelRetryExhausted(RuntimeError):
    """Both transport attempts failed; this is an infrastructure incident."""


class _BufferedChunks:
    def __init__(self, chunks):
        self.chunks = chunks

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def close(self):
        # The real HTTP stream is already closed before this object is returned.
        pass

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk


def _has_progress(chunk) -> bool:
    for choice in chunk.choices or []:
        delta = choice.delta
        if delta is None:
            continue
        if any(
            getattr(delta, key, None)
            for key in ("content", "reasoning_content", "reasoning", "refusal")
        ):
            return True
        if any(
            call.function and (call.function.name or call.function.arguments)
            for call in delta.tool_calls or []
        ):
            return True
    return False


class IdleRetryChatModel(OpenAIChatModel):
    """Retry one stalled Qwen request without publishing a partial response."""

    def __init__(
        self,
        model: OpenAIChatModel,
        *,
        record: Callable[[str, Any], None] | None = None,
        idle_s: float = 60,
        retry_delay_s: float = 2,
    ) -> None:
        if not isinstance(
            model, OpenAIChatModel
        ) or not model.model_name.lower().startswith("qwen"):
            raise ValueError("Idle retry supports only Qwen OpenAI Chat models")
        if idle_s <= 0 or retry_delay_s < 0:
            raise ValueError("Invalid idle timeout or retry delay")
        # The copy shares the existing transport and its owner. No proxy, address
        # family, pool or TLS setting changes. Avoid multiplying SDK retries.
        self._retry_client = model.client.with_options(max_retries=0)
        super().__init__(
            model.model_name,
            provider=model.provider,
            profile=model.profile,
            settings=model.settings,
        )
        self.record = record
        self.idle_s = idle_s
        self.retry_delay_s = retry_delay_s

    @property
    def client(self):
        return self._retry_client

    def _get_tool_choice(self, model_settings, model_request_parameters):
        tools, choice = super()._get_tool_choice(
            model_settings, model_request_parameters
        )
        if tools and model_settings.get("extra_body", {}).get("enable_thinking"):
            # Qwen thinking rejects required/forced tool choice. The SDK's
            # original output validator still requires a successful finish call.
            choice = "auto"
        return tools, choice

    def _record(self, request_id, attempt, phase, **fields):
        if self.record is not None:
            self.record(
                "api_transport_attempt",
                {
                    "request_id": request_id,
                    "attempt": attempt,
                    "phase": phase,
                    **fields,
                },
            )

    async def _completions_create(
        self, messages, stream, model_settings, model_request_parameters
    ):
        request_id = uuid4().hex
        loop = asyncio.get_running_loop()
        for attempt in (1, 2):
            started = loop.time()
            self._record(request_id, attempt, "started", idle_timeout_s=self.idle_s)
            try:
                response = await asyncio.wait_for(
                    super()._completions_create(
                        messages, stream, model_settings, model_request_parameters
                    ),
                    timeout=self.idle_s,
                )
                if not stream:
                    self._record(
                        request_id,
                        attempt,
                        "completed",
                        elapsed_s=loop.time() - started,
                    )
                    return response
                chunks = []
                terminal = False
                last_progress = started
                progress_count = 0
                async with response:
                    iterator = response.__aiter__()
                    while True:
                        remaining = max(0, last_progress + self.idle_s - loop.time())
                        try:
                            chunk = await asyncio.wait_for(
                                anext(iterator), timeout=remaining
                            )
                        except StopAsyncIteration:
                            break
                        chunks.append(chunk)
                        terminal = terminal or any(
                            c.finish_reason is not None for c in chunk.choices or []
                        )
                        if _has_progress(chunk):
                            last_progress = loop.time()
                            progress_count += 1
                            # Only metadata is journaled, never reasoning content.
                            if progress_count == 1 or progress_count % 100 == 0:
                                self._record(
                                    request_id,
                                    attempt,
                                    "progress",
                                    chunks=progress_count,
                                    elapsed_s=loop.time() - started,
                                )
                if not terminal:
                    raise IncompleteModelStream("Stream ended before a terminal choice")
                self._record(
                    request_id,
                    attempt,
                    "completed",
                    elapsed_s=loop.time() - started,
                    progress_chunks=progress_count,
                )
                return _BufferedChunks(chunks)
            except (
                asyncio.TimeoutError,
                APIConnectionError,
                ModelAPIError,
                IncompleteModelStream,
            ) as exc:
                retryable = isinstance(
                    exc,
                    (asyncio.TimeoutError, APIConnectionError, IncompleteModelStream),
                ) or isinstance(exc.__cause__, APIConnectionError)
                if not retryable:
                    raise
                self._record(
                    request_id,
                    attempt,
                    "failed",
                    error_type=type(exc).__name__,
                    elapsed_s=loop.time() - started,
                )
                if attempt == 2:
                    raise ModelRetryExhausted(
                        "Two model transport attempts failed; task result is an infrastructure incident"
                    ) from exc
                await asyncio.sleep(self.retry_delay_s)
