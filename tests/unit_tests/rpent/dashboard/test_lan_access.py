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

import pytest

from rpent.dashboard.lan_access import relay


@pytest.mark.parametrize(
    "allowed_peer",
    ["127.0.0.1", ("127.0.0.1", "127.0.0.2"), ("127.0.0.2", "127.0.0.1")],
)
def test_allowed_peer_streams_both_directions_and_half_close(allowed_peer):
    async def check():
        async def respond(reader, writer):
            data = await reader.read()
            writer.write(b"response:" + data)
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        async with await asyncio.start_server(respond, "127.0.0.1", 0) as upstream:
            port = upstream.sockets[0].getsockname()[1]
            handler = partial(relay, allowed_peer=allowed_peer, upstream_port=port)
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


@pytest.mark.parametrize(
    "allowed_peer", ["127.0.0.2", "127.0.0.10", ("127.0.0.2", "127.0.0.10")]
)
def test_disallowed_peer_cannot_reach_upstream_even_with_forwarded_header(allowed_peer):
    async def check():
        connections = []

        async def record(reader, writer):
            connections.append(True)
            writer.close()
            await writer.wait_closed()

        async with await asyncio.start_server(record, "127.0.0.1", 0) as upstream:
            port = upstream.sockets[0].getsockname()[1]
            handler = partial(relay, allowed_peer=allowed_peer, upstream_port=port)
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


def test_repeated_allow_keeps_both_addresses(monkeypatch):
    from rpent.dashboard import lan_access

    calls = []

    async def serve(bind, allowed_peer, ports):
        calls.append((bind, allowed_peer, ports))

    monkeypatch.setattr(lan_access, "serve", serve)
    monkeypatch.setattr(
        "sys.argv",
        [
            "lan_access",
            "--bind",
            "192.0.2.1",
            "--allow",
            "192.0.2.2",
            "--allow",
            "192.0.2.3",
            "--ports",
            "8094",
        ],
    )
    lan_access.main()
    assert calls == [("192.0.2.1", ("192.0.2.2", "192.0.2.3"), [8094])]
