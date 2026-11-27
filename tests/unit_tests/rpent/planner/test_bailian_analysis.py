# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Check the isolated analysis tools and ten-image window on serialized requests."""

import asyncio
import base64
import json

import pytest
from pydantic_ai import (
    BinaryContent,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from rpent.planner.api_analysis import (
    OMITTED,
    execute_command,
    local_image,
    recent_images,
)


def test_image_window_keeps_last_ten_across_tools_and_crops():
    images = [BinaryContent(data=bytes([i]), media_type="image/png") for i in range(15)]
    history = [ModelRequest(parts=[UserPromptPart(["cameras", *images[:3]])])]
    for step in range(4):
        call_id = f"c{step}"
        history.append(ModelResponse(parts=[ToolCallPart("get", {}, call_id)]))
        history.append(
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        "get",
                        [str(step), *images[3 + 3 * step : 6 + 3 * step]],
                        call_id,
                    )
                ]
            )
        )
    original = repr(history)
    window = recent_images(history)
    model = OpenAIChatModel("qwen3.8-flash", provider=OpenAIProvider(api_key="offline"))
    wire = asyncio.run(model._map_messages(window, ModelRequestParameters()))
    parts = [
        part
        for message in wire
        if isinstance(message.get("content"), list)
        for part in message["content"]
    ]
    blobs = [
        base64.b64decode(part["image_url"]["url"].split(",")[1])
        for part in parts
        if part["type"] == "image_url"
    ]
    assert blobs == [i.data for i in images[-10:]]
    assert json.dumps(wire).count(OMITTED) == 5
    assert [m["tool_call_id"] for m in wire if m["role"] == "tool"] == [
        f"c{i}" for i in range(4)
    ]
    assert repr(history) == original


def test_analysis_workspace_reports_output_and_reads_original_image(tmp_path):
    from PIL import Image

    result = asyncio.run(execute_command(tmp_path, "pwd; exit 3"))
    assert result["exit_status"] == 3
    assert result["output"].strip() == str(tmp_path)
    Image.new("RGB", (3, 4)).save(tmp_path / "crop.png")
    assert (
        local_image(tmp_path, "crop.png").data == (tmp_path / "crop.png").read_bytes()
    )
    (tmp_path / "bogus.png").write_text("not an image")
    with pytest.raises(ValueError, match="PNG or JPEG"):
        local_image(tmp_path, "bogus.png")


def test_command_cancellation_terminates_child_process(tmp_path):
    async def wait_for_child():
        while not (tmp_path / "ready").exists():
            await asyncio.sleep(0.01)

    async def run():
        task = asyncio.create_task(
            execute_command(tmp_path, "(sleep 0.5; touch escaped) & touch ready; wait")
        )
        await asyncio.wait_for(wait_for_child(), timeout=3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0.6)
        assert not (tmp_path / "escaped").exists()

    asyncio.run(run())
