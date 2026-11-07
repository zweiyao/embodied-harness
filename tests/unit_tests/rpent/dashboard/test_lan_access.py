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

import asyncio
from functools import partial

from rpent.dashboard.lan_access import relay


def test_allowed_peer_streams_both_directions_and_half_close():
    async def check():
        async def respond(reader, writer):
            data = await reader.read()
            writer.write(b"response:" + data)
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        async with await asyncio.start_server(respond, "127.0.0.1", 0) as upstream:
            port = upstream.sockets[0].getsockname()[1]
            handler = partial(relay, allowed_peer="127.0.0.1", upstream_port=port)
            async with await asyncio.start_server(handler, "127.0.0.1", 0) as gateway:
                reader, writer = await asyncio.open_connection(
                    "127.0.0.1", gateway.sockets[0].getsockname()[1]
                )
                payload = b"observation\x00" * 20000
                writer.write(payload)
                await writer.drain()
                writer.write_eof()
                assert (
                    await asyncio.wait_for(reader.read(), 3) == b"response:" + payload
                )
                writer.close()
                await writer.wait_closed()

    asyncio.run(check())


def test_disallowed_peer_cannot_reach_upstream_even_with_forwarded_header():
    async def check():
        connections = []

        async def record(reader, writer):
            connections.append(True)
            writer.close()
            await writer.wait_closed()

        async with await asyncio.start_server(record, "127.0.0.1", 0) as upstream:
            port = upstream.sockets[0].getsockname()[1]
            handler = partial(relay, allowed_peer="127.0.0.2", upstream_port=port)
            async with await asyncio.start_server(handler, "127.0.0.1", 0) as gateway:
                reader, writer = await asyncio.open_connection(
                    "127.0.0.1", gateway.sockets[0].getsockname()[1]
                )
                writer.write(b"GET / HTTP/1.1\r\nX-Forwarded-For: 127.0.0.2\r\n\r\n")
                try:
                    assert await asyncio.wait_for(reader.read(), 3) == b""
                except ConnectionResetError:
                    pass
                writer.close()
                try:
                    await writer.wait_closed()
                except ConnectionResetError:
                    pass
                assert not connections

    asyncio.run(check())
