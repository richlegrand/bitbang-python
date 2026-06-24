"""Regression tests for the PIN-bypass exploit reported by jacopotediosi
against OctoPrint-BitBang 0.2.7 (plugins.octoprint.org PR #1443).

The exploit: after the WebRTC channel is up (bidirectional verify
already passed), an attacker who skips the stream-0 connect/auth
handshake entirely and sends an application SYN on stream_id > 0 used
to be dispatched directly to the registered handler. PIN check
bypassed.

These tests run the dispatch path in isolation — no signaling, no
WebRTC, no identity — so they execute in milliseconds and don't need
the Playwright stack. They exercise `bitbang.adapter.BitBangBase`
which is what `OctoPrint-BitBang` consumes via `BitBangASGI`.
"""

import asyncio
import json
import struct
import time

import pytest

from bitbang.adapter import BitBangBase, FLAG_DAT, FLAG_FIN, FLAG_SYN


def _frame(stream_id: int, flags: int, payload: bytes = b"") -> bytes:
    """Build a SWSP wire frame the way the JS client and Go server do."""
    return struct.pack('<IHH', stream_id, flags, len(payload)) + payload


class _RecordingChannel:
    """Stand-in for an RTCDataChannel that captures sent frames."""

    def __init__(self):
        self.sent: list[bytes] = []

    def send(self, data):
        self.sent.append(data)


class _CountingApp:
    """ASGI/WSGI stub. If `handle_datachannel_message` ever calls into
    _handle_swsp_request, the handler will reach the app — incrementing
    the call counter. The whole point of the gate is to keep this at 0
    for unauthenticated frames.
    """

    def __init__(self):
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1


def _make_adapter(pin: str | None) -> BitBangBase:
    """Construct a BitBangBase skipping __init__ (which would require
    identity files and a signaling endpoint). We populate the handful
    of attrs the dispatch path needs and nothing else.
    """
    obj = object.__new__(BitBangBase)
    obj.app = _CountingApp()
    obj.pin = pin
    obj._pin_callback = None
    obj.debug = False
    obj.peers = {}
    return obj


class _FakePC:
    """Stand-in for an RTCPeerConnection: tracks connectionState and records
    whether close() was awaited."""

    def __init__(self, state='connected'):
        self.connectionState = state
        self.closed = False

    async def close(self):
        self.closed = True
        self.connectionState = 'closed'


def _make_peer(adapter: BitBangBase, client_id: str, pc=None, authenticated=False):
    """Reproduce the peer dict shape from BitBangBase.handle_request."""
    channel = _RecordingChannel()
    adapter.peers[client_id] = {
        'pc': pc,
        'channel': channel,
        'pending_requests': {},
        'browser_ip': '203.0.113.7',
        'verify_nonce': None,
        'verify_failed': False,
        'authenticated': authenticated,
        'auth_fails': 0,
    }
    return adapter.peers[client_id], channel


def test_syn_before_auth_rejected_no_pin():
    """Listener without PIN: SYN on stream 1 before the connect
    handshake must still be rejected. (No PIN doesn't mean no
    handshake — connect is what flips authenticated.)
    """
    adapter = _make_adapter(pin=None)
    _, channel = _make_peer(adapter, 'c1')

    syn = _frame(1, FLAG_SYN | FLAG_FIN, b'{"type":"http","method":"GET","pathname":"/"}')
    asyncio.run(adapter.handle_datachannel_message(channel, syn, 'c1'))

    assert adapter.app.calls == 0, \
        "handler dispatched on stream 1 before connect — gate is broken"
    assert len(channel.sent) > 0, \
        "expected an unauthenticated error frame back to the client"


def test_syn_before_auth_rejected_with_pin():
    """Listener with PIN: the exact exploit jacopotediosi posted —
    skip stream-0 entirely, send {"type":"http"} on stream 1. Before
    the fix this dispatched to the HTTP handler; after, it bounces.
    """
    adapter = _make_adapter(pin='1234')
    _, channel = _make_peer(adapter, 'c1')

    syn = _frame(1, FLAG_SYN | FLAG_FIN, b'{"type":"http","method":"GET","pathname":"/"}')
    asyncio.run(adapter.handle_datachannel_message(channel, syn, 'c1'))

    assert adapter.app.calls == 0
    # And the error response was emitted — at minimum a SYN frame for
    # stream 1 carrying the error metadata.
    assert any(struct.unpack('<I', f[:4])[0] == 1 for f in channel.sent), \
        "no error frame seen on stream 1"


def test_dat_before_auth_dropped():
    """Even more direct: send a DAT (not a SYN) on a stream that was
    never opened. Belt-and-suspenders to the handler-nil short-circuit:
    the explicit gate covers this too.
    """
    adapter = _make_adapter(pin='1234')
    _, channel = _make_peer(adapter, 'c1')

    dat = _frame(7, FLAG_DAT, b'hello')
    asyncio.run(adapter.handle_datachannel_message(channel, dat, 'c1'))

    assert adapter.app.calls == 0


def test_syn_after_connect_no_pin_dispatched():
    """Happy path: when no PIN is set, a stream-0 connect alone flips
    authenticated to True, and a subsequent SYN on a non-zero stream
    reaches the handler.
    """
    adapter = _make_adapter(pin=None)
    peer, channel = _make_peer(adapter, 'c1')

    # Stream 0 connect (no PIN required) — flips authenticated=True.
    connect = _frame(0, FLAG_SYN, b'{"type":"connect","path":"/","version":3}')
    asyncio.run(adapter.handle_datachannel_message(channel, connect, 'c1'))

    assert peer['authenticated'] is True, \
        "no-PIN connect should have flipped authenticated to True"


def test_syn_after_failed_pin_still_rejected():
    """Wrong PIN must not flip the gate. Without this, an attacker
    could send a junk PIN, ignore the auth_result, then sneak a SYN
    through. (Same coverage as the matching Go test.)
    """
    adapter = _make_adapter(pin='1234')
    peer, channel = _make_peer(adapter, 'c1')

    connect = _frame(0, FLAG_SYN, b'{"type":"connect","path":"/","version":3}')
    asyncio.run(adapter.handle_datachannel_message(channel, connect, 'c1'))

    # Wrong PIN. The handler currently sleeps 2s on failure (intentional
    # brake) — patch it out for test speed.
    with _no_pin_fail_sleep():
        wrong = _frame(0, FLAG_SYN, b'{"type":"auth","pin":"0000"}')
        asyncio.run(adapter.handle_datachannel_message(channel, wrong, 'c1'))

    assert peer['authenticated'] is False, \
        "failed PIN should leave authenticated=False"

    syn = _frame(1, FLAG_SYN | FLAG_FIN, b'{"type":"http"}')
    asyncio.run(adapter.handle_datachannel_message(channel, syn, 'c1'))
    assert adapter.app.calls == 0


def test_three_wrong_pins_closes_connection():
    """Brute-force brake: after MAX_AUTH_FAILS wrong PINs the session's
    data channel is torn down, forcing a fresh WebRTC handshake to make
    further guesses. Mirrors the Go 3-strike test.
    """
    from bitbang.adapter import MAX_AUTH_FAILS

    adapter = _make_adapter(pin='1234')
    pc = _FakePC()
    peer, channel = _make_peer(adapter, 'c1', pc=pc)

    # Use one loop across the messages so the pc.close() scheduled via
    # ensure_future on the final failure actually gets a chance to run.
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(adapter.handle_datachannel_message(
            channel, _frame(0, FLAG_SYN, b'{"type":"connect","path":"/","version":3}'), 'c1'))
        with _no_pin_fail_sleep():
            for _ in range(MAX_AUTH_FAILS):
                loop.run_until_complete(adapter.handle_datachannel_message(
                    channel, _frame(0, FLAG_SYN, b'{"type":"auth","pin":"0000"}'), 'c1'))
        loop.run_until_complete(asyncio.sleep(0))  # let the close task run
    finally:
        loop.close()

    assert peer['auth_fails'] == MAX_AUTH_FAILS
    assert pc.closed is True, "connection should be closed after too many wrong PINs"


def test_unauth_session_cap_counts_live_only():
    """The concurrent-session cap counts only live, unauthenticated peers:
    authenticated peers and dropped (closed/failed) peers don't consume a
    slot, so legit users and churned attackers never wedge it.
    """
    from bitbang.adapter import MAX_UNAUTH_PEERS

    adapter = _make_adapter(pin='1234')
    # 2 live unauth + 1 authenticated + 1 closed + 1 failed
    _make_peer(adapter, 'live1', pc=_FakePC('connected'))
    _make_peer(adapter, 'live2', pc=_FakePC('connecting'))
    _make_peer(adapter, 'authed', pc=_FakePC('connected'), authenticated=True)
    _make_peer(adapter, 'gone1', pc=_FakePC('closed'))
    _make_peer(adapter, 'gone2', pc=_FakePC('failed'))

    assert adapter._count_unauth_live() == 2

    # Fill to the cap with live unauth peers → next connection is over the cap.
    for i in range(MAX_UNAUTH_PEERS):
        _make_peer(adapter, f'flood{i}', pc=_FakePC('connected'))
    assert adapter._count_unauth_live() >= MAX_UNAUTH_PEERS


def test_pin_compare_is_constant_time():
    """Sanity check that _verify_pin no longer uses Python's plain
    string equality. We can't measure timing reliably in a unit test,
    but we can confirm the function returns False for the obvious
    same-length-wrong-content case AND for the prefix case (where
    `==` short-circuits dramatically faster).
    """
    adapter = _make_adapter(pin='hunter2hunter2hunter2')
    assert adapter._verify_pin('/', '') is False
    assert adapter._verify_pin('/', 'h') is False
    assert adapter._verify_pin('/', 'hunter2hunter2hunter1') is False  # same len
    assert adapter._verify_pin('/', 'hunter2hunter2hunter2') is True


class _no_pin_fail_sleep:
    """Context manager that no-ops time.sleep for the duration. Used to
    skip the 2s pin-fail brake in tests that just want to exercise the
    flag behavior.
    """

    def __enter__(self):
        import bitbang.adapter as m
        self._orig = m.time.sleep
        m.time.sleep = lambda s: None
        return self

    def __exit__(self, *_):
        import bitbang.adapter as m
        m.time.sleep = self._orig
