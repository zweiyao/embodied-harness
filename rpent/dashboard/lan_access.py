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

"""Expose loopback dashboards to approved IPv4 peers without restarting them.

This is a TCP source-address restriction, not user authentication. HTTP headers
cannot grant access. Keep robot RPC ports out of the configured port list.
"""

import argparse
import asyncio
import logging
from contextlib import AsyncExitStack
from functools import partial
from ipaddress import IPv4Address

log = logging.getLogger(__name__)


async def _copy(reader, writer):
    while data := await reader.read(65536):
        writer.write(data)
        await writer.drain()
    if writer.can_write_eof():
        writer.write_eof()


async def relay(reader, writer, *, allowed_peer, upstream_port):
    peer = writer.get_extra_info("peername")
    upstream = None
    pumps = []
    try:
        allowed = (allowed_peer,) if isinstance(allowed_peer, str) else allowed_peer
        if peer is None or peer[0] not in allowed:
            log.warning("Rejected peer %s on port %s", peer, upstream_port)
            return
        upstream_reader, upstream = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", upstream_port), timeout=5
        )
        pumps = [
            asyncio.create_task(_copy(reader, upstream)),
            asyncio.create_task(_copy(upstream_reader, writer)),
        ]
        await asyncio.gather(*pumps)
    except (OSError, asyncio.TimeoutError) as exc:
        log.warning("Connection on port %s ended: %s", upstream_port, exc)
    finally:
        for task in pumps:
            task.cancel()
        if pumps:
            await asyncio.gather(*pumps, return_exceptions=True)
        for stream in (upstream, writer):
            if stream is not None:
                stream.close()
                try:
                    await stream.wait_closed()
                except OSError:
                    pass


async def serve(bind, allowed_peer, ports):
    async with AsyncExitStack() as stack:
        for port in ports:
            handler = partial(relay, allowed_peer=allowed_peer, upstream_port=port)
            server = await asyncio.start_server(handler, bind, port)
            await stack.enter_async_context(server)
            log.info("Listening on %s:%s; allowed peer %s", bind, port, allowed_peer)
        await asyncio.Future()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", type=IPv4Address, required=True)
    parser.add_argument("--allow", type=IPv4Address, action="append", required=True)
    parser.add_argument("--ports", type=int, nargs="+", required=True)
    args = parser.parse_args()
    if args.bind.is_unspecified or args.bind.is_loopback or args.bind.is_multicast:
        parser.error("Bind to a specific LAN IPv4 address")
    if any(peer.is_unspecified or peer.is_multicast for peer in args.allow):
        parser.error("Allow specific client IPv4 addresses")
    if any(port < 1024 or port > 65535 for port in args.ports):
        parser.error("Dashboard ports must be in 1024..65535")
    logging.basicConfig(level=logging.INFO)
    asyncio.run(
        serve(str(args.bind), tuple(str(peer) for peer in args.allow), args.ports)
    )


if __name__ == "__main__":
    main()
