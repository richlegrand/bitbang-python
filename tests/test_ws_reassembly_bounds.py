"""Bounds on WebSocket message reassembly.

A peer that sends FLAG_MORE fragments and never a final chunk previously grew
the per-stream buffer without limit. These drive the real frame handler and
fail against that version.
"""

import asyncio
import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from bitbang.adapter import (  # noqa: E402
    FLAG_MORE,
    MAX_WS_REASSEMBLY,
    MAX_WS_REASSEMBLY_STREAMS,
    MAX_WS_REASSEMBLY_TOTAL,
)
import bitbang.adapter as adapter  # noqa: E402


class FakeWS:
    """Stands in for a websockets connection."""

    def __init__(self):
        self.closed = False
        self.sent = []

    async def close(self):
        self.closed = True

    async def send(self, data):
        self.sent.append(data)


def make_adapter():
    """A bare adapter instance; _handle_ws_frame touches only self.debug."""
    a = adapter.BitBangWSGI.__new__(adapter.BitBangWSGI)
    a.debug = False
    return a


def peer_with(streams):
    return {'ws_conns': {sid: FakeWS() for sid in streams}, 'ws_rx': {}}


def fragment(n):
    """A FLAG_MORE payload of n bytes, type byte included."""
    return b'\x00' + b'x' * (n - 1)


def run(coro):
    """Drive a coroutine on a private loop in a private thread.

    Not run_until_complete on the main thread: other tests in this suite leave
    an event loop running there, and nesting raises "Cannot run the event loop
    while another loop is running". That failure only appears when the whole
    suite runs, so a loop created here would pass in isolation and fail in CI.
    A separate thread gets a loop nothing else is using.
    """
    box = {}

    def target():
        loop = asyncio.new_event_loop()
        try:
            box['value'] = loop.run_until_complete(coro)
        except BaseException as exc:          # re-raised on the caller's thread
            box['error'] = exc
        finally:
            loop.close()

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    if 'error' in box:
        raise box['error']
    return box.get('value')


def feed(a, peer, stream_id, payload, flags=FLAG_MORE):
    return a._handle_ws_frame(None, stream_id, flags, payload, peer)


def test_per_stream_cap_closes_only_that_stream():
    a = make_adapter()
    peer = peer_with([1, 2])
    chunk = fragment(64 * 1024)

    async def drive():
        # Push stream 1 past the per-stream cap.
        for _ in range((MAX_WS_REASSEMBLY // len(chunk)) + 2):
            await feed(a, peer, 1, chunk)
        # Stream 2 is untouched and still works.
        await feed(a, peer, 2, chunk)

    run(drive())

    assert 1 not in peer['ws_rx'], "buffer for the offending stream was not released"
    assert 1 not in peer['ws_conns'], "offending stream was not closed"
    assert 2 in peer['ws_rx'], "an unrelated stream was torn down"
    assert len(peer['ws_rx'][2]) == len(chunk)


def test_buffer_never_exceeds_the_cap():
    a = make_adapter()
    peer = peer_with([1])
    chunk = fragment(64 * 1024)

    async def drive():
        for _ in range((MAX_WS_REASSEMBLY // len(chunk)) + 5):
            await feed(a, peer, 1, chunk)
            if 1 in peer['ws_rx']:
                assert len(peer['ws_rx'][1]) <= MAX_WS_REASSEMBLY

    run(drive())


def test_session_total_bounds_many_streams():
    """A per-stream cap alone would let this multiply across streams."""
    a = make_adapter()
    count = MAX_WS_REASSEMBLY_STREAMS
    peer = peer_with(range(1, count + 1))
    chunk = fragment(256 * 1024)

    async def drive():
        for _ in range(200):
            for sid in range(1, count + 1):
                if sid in peer['ws_conns']:
                    await feed(a, peer, sid, chunk)
            total = sum(len(b) for b in peer['ws_rx'].values())
            assert total <= MAX_WS_REASSEMBLY_TOTAL, f"session total reached {total}"

    run(drive())


def test_stream_count_is_bounded():
    a = make_adapter()
    over = MAX_WS_REASSEMBLY_STREAMS + 10
    peer = peer_with(range(1, over + 1))

    async def drive():
        for sid in range(1, over + 1):
            await feed(a, peer, sid, fragment(16))

    run(drive())
    assert len(peer['ws_rx']) <= MAX_WS_REASSEMBLY_STREAMS


def test_ordinary_fragmented_message_still_delivered():
    """The bound must not break the case it exists to protect."""
    a = make_adapter()
    peer = peer_with([1])
    ws = peer['ws_conns'][1]

    async def drive():
        await feed(a, peer, 1, b'\x00' + b'a' * 10)       # MORE
        await feed(a, peer, 1, b'b' * 10, flags=0)         # final
    run(drive())

    assert ws.sent == ['a' * 10 + 'b' * 10]
    assert 1 not in peer['ws_rx'], "buffer not released after the final chunk"
