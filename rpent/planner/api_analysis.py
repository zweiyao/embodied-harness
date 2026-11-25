# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Episode-local analysis and image history for the RoboDojo API profiles."""

import asyncio
import os
import signal
from dataclasses import replace
from pathlib import Path

from pydantic_ai import BinaryContent
from pydantic_ai.messages import ImageUrl, ToolReturnPart, UserPromptPart

OMITTED = "[Earlier image omitted; original retained in episode evidence.]"


def recent_images(messages, limit=10):
    """Copy only the request parts that contain expired images, newest first."""
    remaining = limit

    def visit(value):
        nonlocal remaining
        if isinstance(value, ImageUrl) or (
            isinstance(value, BinaryContent) and value.media_type.startswith("image/")
        ):
            if remaining:
                remaining -= 1
                return value
            return OMITTED
        if isinstance(value, (list, tuple)):
            return list(reversed([visit(item) for item in reversed(value)]))
        return value

    result = []
    for message in reversed(messages):
        parts = []
        for part in reversed(message.parts):
            if isinstance(part, (ToolReturnPart, UserPromptPart)):
                part = replace(part, content=visit(part.content))
            parts.append(part)
        result.append(replace(message, parts=list(reversed(parts))))
    return list(reversed(result))


async def execute_command(workspace: Path, cmd: str) -> dict:
    """Execute in a separate process group so cancelling also stops child tools."""
    process = await asyncio.create_subprocess_shell(
        cmd,
        cwd=workspace,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
    )
    output = bytearray()
    truncated = False
    try:
        while chunk := await process.stdout.read(8192):
            room = 32768 - len(output)
            truncated |= len(chunk) > room
            output.extend(chunk[:room])
        await process.wait()
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.communicate()
        raise
    return {
        "exit_status": process.returncode,
        "output": output.decode(errors="replace"),
        "truncated": truncated,
    }


def local_image(workspace: Path, path: str) -> BinaryContent:
    """Read a PNG or JPEG without changing the original encoding."""
    data = (workspace / path).read_bytes()
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return BinaryContent(data=data, media_type="image/png")
    if data.startswith(b"\xff\xd8\xff"):
        return BinaryContent(data=data, media_type="image/jpeg")
    raise ValueError("Expected PNG or JPEG")
