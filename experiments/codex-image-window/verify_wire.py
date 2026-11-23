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

"""Exercise the native Codex client against a loopback Responses server with synthetic PNGs."""

import argparse
import asyncio
import base64
import io
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from aiohttp import web
from openai_codex import (
    ApprovalMode,
    AsyncCodex,
    CodexConfig,
    ImageInput,
    Sandbox,
    TextInput,
)
from PIL import Image

PLACEHOLDER = "[Earlier image omitted]"


def image_url(index):
    stream = io.BytesIO()
    Image.new("RGB", (640, 480), (index, 0, 0)).save(stream, format="PNG")
    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode()


def image_number(url):
    data = base64.b64decode(url.split(",", 1)[1])
    with Image.open(io.BytesIO(data)) as image:
        return image.convert("RGB").getpixel((0, 0))[0]


def summarize(items):
    images, omitted = [], 0
    for item in items:
        blocks = item.get("content", item.get("output", []))
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if block.get("type") == "input_image":
                images.append(image_number(block["image_url"]))
            if block.get("type") == "input_text" and block.get("text") == PLACEHOLDER:
                omitted += 1
    return images, omitted


class CameraFixture:
    def list_tools(self):
        return [
            SimpleNamespace(
                name="view_env_state",
                description="Read synthetic camera frames.",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            )
        ]

    def __init__(self):
        self.calls = 0

    def execute_tool(self, name, arguments):
        from rpent.tools import ToolResult

        assert name == "view_env_state" and not arguments
        self.calls += 1
        return ToolResult(
            data={"observation_step": self.calls},
            images=[
                base64.b64decode(image_url(i).split(",", 1)[1])
                for i in range(self.calls * 3 - 2, self.calls * 3 + 1)
            ],
        )


async def probe(binary, transport, window, source, compact=False):
    histories, rows = {}, []

    fixture = CameraFixture()
    compacted = asyncio.Event()
    compaction_rows = []
    upgrades = 0
    retried_input = None
    mcp = None
    if source in ("mcp", "code"):
        from rpent.planner.utils.http_mcp_server import HttpMcpServer

        mcp = HttpMcpServer(fixture)
    requested_groups = set()

    def respond(payload, wire):
        previous = payload.get("previous_response_id")
        inputs = histories[previous].copy() if previous else []
        inputs.extend(payload["input"])
        rid = f"resp_{len(histories) + 1}"
        item = {
            "type": "message",
            "role": "assistant",
            "id": f"msg_{rid}",
            "content": [{"type": "output_text", "text": "ok"}],
        }
        warmup = payload.get("generate") is False
        if any(item.get("type") == "compaction_trigger" for item in inputs):
            images, omitted = summarize(inputs)
            compaction_rows.append({"images": images, "omitted": omitted})
            compacted.set()
            return [
                {
                    "type": "response.output_item.done",
                    "item": {
                        "type": "compaction",
                        "encrypted_content": "synthetic-only",
                    },
                },
                {"type": "response.completed", "response": {"id": rid}},
            ]
        group = sum(
            item.get("role") == "user"
            and any(
                b.get("text", "").startswith("Group ") for b in item.get("content", [])
            )
            for item in inputs
        )
        tool_call = source != "user" and group not in requested_groups and not warmup
        if tool_call:
            requested_groups.add(group)
            name = "view_env_state" if mcp else "view_image"
            args = {} if mcp else {"path": str(Path(tmp) / f"group-{group}.png")}
            item = {
                "type": "function_call",
                "call_id": f"call_{group}",
                "name": name,
                "arguments": json.dumps(args),
            }
            if source in ("mcp", "code"):
                item["namespace"] = "mcp__rpent"
            if source == "code":
                calculation = ""
                if group == 1:
                    calculation = (
                        """const t = await tools.exec_command({cmd: "python3 -c 'print(6*7)'"}); """
                        """if (t.exit_code !== 0 || t.output.trim() !== "42") """
                        """throw Error("Python computation failed: " + t.output); """
                    )
                item = {
                    "type": "custom_tool_call",
                    "namespace": "functions",
                    "name": "exec",
                    "call_id": f"call_{group}",
                    "input": calculation
                    + "const r = await tools.mcp__rpent__view_env_state({}); "
                    "for (const b of r.content) { if (b.type === 'image') image(b); "
                    "else if (b.type === 'text') text(b.text); }",
                }
        histories[rid] = inputs if warmup else [*inputs, item]
        if not warmup and not tool_call:
            images, omitted = summarize(inputs)
            rows.append(
                {
                    "wire": wire,
                    "previous": previous,
                    "images": images,
                    "omitted": omitted,
                }
            )
        events = [{"type": "response.created", "response": {"id": rid}}]
        if not warmup:
            events.append({"type": "response.output_item.done", "item": item})
        events.append({"type": "response.completed", "response": {"id": rid}})
        return events

    async def endpoint(request):
        nonlocal upgrades, retried_input
        if request.method == "GET":
            upgrades += 1
            if transport == "fallback":
                raise web.HTTPUpgradeRequired()
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            async for message in ws:
                for event in respond(json.loads(message.data), "ws"):
                    await ws.send_json(event)
            return ws
        payload = await request.json()
        if transport == "retry" and len(rows) == 3:
            if retried_input is None:
                retried_input = payload["input"]
                raise web.HTTPServiceUnavailable()
            assert retried_input == payload["input"]
        events = respond(payload, "http")
        return web.Response(
            content_type="text/event-stream",
            text="".join(f"data: {json.dumps(e)}\n\n" for e in events),
        )

    app = web.Application(client_max_size=16 * 1024**2)
    app.router.add_route("*", "/v1/responses", endpoint)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    base_url = f"http://127.0.0.1:{runner.addresses[0][1]}/v1"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            if mcp:
                from rpent.utils.logging import init_output_dir

                init_output_dir(Path(tmp, "logs"))
                mcp.start()
            home = Path(tmp, "codex")
            home.mkdir()
            provider_name = "OpenAI" if compact else "fixture"
            provider = f'{{name="{provider_name}", base_url="{base_url}", wire_api="responses", supports_websockets={str(transport in ("ws", "fallback")).lower()}}}'
            overrides = ["features.code_mode=false", "features.view_image=true"]
            if mcp:
                overrides.extend(
                    [
                        "mcp_servers.rpent.required=true",
                        f'mcp_servers.rpent.url="{mcp.url}"',
                        'mcp_servers.rpent.default_tools_approval_mode="approve"',
                    ]
                )
            config = CodexConfig(
                codex_bin=binary,
                cwd=tmp,
                env={"CODEX_HOME": str(home)},
                config_overrides=(
                    *overrides,
                    f"model_providers.fixture={provider}",
                    'model_provider="fixture"',
                ),
            )
            async with AsyncCodex(config) as client:
                thread = await client.thread_start(
                    cwd=tmp,
                    model="gpt-6-astra",
                    model_provider="fixture",
                    ephemeral=False,
                    approval_mode=ApprovalMode.deny_all,
                    sandbox=Sandbox.read_only,
                )
                for turn in range(4):
                    inputs = [TextInput(f"Group {turn + 1}")]
                    if source == "view":
                        Path(tmp, f"group-{turn + 1}.png").write_bytes(
                            base64.b64decode(image_url(turn * 3 + 3).split(",", 1)[1])
                        )
                    if not mcp:
                        stop = turn * 3 + (3 if source == "view" else 4)
                        inputs.extend(
                            ImageInput(image_url(i)) for i in range(turn * 3 + 1, stop)
                        )
                    result = await asyncio.wait_for(
                        thread.run(inputs, effort="high"), 45
                    )
                    if result.error or result.final_response != "ok":
                        raise ValueError(
                            f"unexpected turn result: {result.status} {result.error}"
                        )
                if source == "user":
                    saved = (await thread.read(include_turns=True)).model_dump(
                        mode="json"
                    )
                    saved_images = [
                        image_number(block["url"])
                        for turn_data in saved["thread"]["turns"]
                        for item_data in turn_data["items"]
                        for block in item_data.get("content", [])
                        if isinstance(block, dict) and block.get("type") == "image"
                    ]
                    assert saved_images == list(range(1, 13)), saved_images
                if compact:
                    await thread.compact()
                    await asyncio.wait_for(compacted.wait(), 20)
    finally:
        await runner.cleanup()
        if mcp:
            mcp.stop()
    if mcp:
        assert fixture.calls == 4, fixture.calls
    print(
        json.dumps(
            {
                "source": source,
                "transport": transport,
                "rows": rows,
                "upgrades": upgrades,
                "retry": retried_input is not None,
                "compact": compaction_rows,
            }
        ),
        flush=True,
    )
    if transport == "fallback":
        assert upgrades > 0
    if transport == "retry":
        assert retried_input is not None
    if compact:
        assert compaction_rows == [
            {"images": rows[-1]["images"], "omitted": rows[-1]["omitted"]}
        ]
    assert len(rows) == 4
    for index, row in enumerate(rows, 1):
        count = 3 * index
        omitted = max(0, count - window)
        assert row["images"] == list(range(omitted + 1, count + 1))
        assert row["omitted"] == omitted
        assert row["wire"] == ("ws" if transport == "ws" else "http")
    if transport == "ws" and window == 10:
        assert rows[-1]["previous"] is None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary")
    parser.add_argument("transport", choices=("http", "ws", "fallback", "retry"))
    parser.add_argument("mode", choices=("stock", "window"))
    parser.add_argument(
        "--source", choices=("user", "mcp", "view", "code"), default="user"
    )
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    if args.transport == "retry" and args.source != "user":
        parser.error("retry uses user image inputs")
    asyncio.run(
        probe(
            args.binary,
            args.transport,
            10 if args.mode == "window" else 12,
            args.source,
            args.compact,
        )
    )
