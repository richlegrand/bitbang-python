"""BitBang adapters for WebRTC DataChannel.

This module provides adapters that bridge web apps to WebRTC DataChannels
via the BitBang signaling server. Subclass to add media tracks.

Classes:
    BitBangBase: Abstract base class with shared WebRTC/signaling functionality
    BitBangWSGI: Adapter for WSGI apps (Flask, Django)
    BitBangASGI: Adapter for ASGI apps (FastAPI, Starlette)

Example usage (Flask):
    from flask import Flask
    from bitbang import BitBangWSGI

    app = Flask(__name__)

    @app.route('/')
    def index():
        return 'Hello from BitBang!'

    adapter = BitBangWSGI(app)  # UID auto-generated from identity
    adapter.run()

Example usage (FastAPI):
    from fastapi import FastAPI
    from bitbang import BitBangASGI

    app = FastAPI()

    @app.get('/')
    async def index():
        return 'Hello from BitBang!'

    adapter = BitBangASGI(app)  # UID auto-generated from identity
    adapter.run()
"""

import asyncio
import base64
import io
import json
import os
import re
import socket
import ssl
import struct
import sys
import tempfile
import threading
import time
import traceback
import urllib.parse
from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
from aiortc.sdp import candidate_from_sdp
import websockets

# SWSP (Simple WebRTC Streaming Protocol) constants
FLAG_SYN = 0x0001
FLAG_FIN = 0x0004
FLAG_DAT = 0x0000
SWSP_CHUNK_SIZE = 16384  # 16KB chunks

BANNER = r"""   ___  _ __  ___
  / _ )(_) /_/ _ )___ ____  ___ _
 / _  / / __/ _  / _ `/ _ \/ _ `/
/____/_/\__/____/\_,_/_//_/\_, /
                          /___/ """


def add_bitbang_args(parser):
    """Add common BitBang CLI arguments to an argparse parser."""
    import argparse
    group = parser.add_argument_group('BitBang options')
    group.add_argument('--ephemeral', action='store_true',
                       help='Use a temporary identity (not saved to disk)')
    group.add_argument('--identity', metavar='PATH',
                       help='Use a specific identity file')
    group.add_argument('--regenerate', action='store_true',
                       help='Delete and regenerate identity')
    group.add_argument('--server', default=None,
                       help='Signaling server hostname (default: bitba.ng)')
    group.add_argument('--debug', action='store_true',
                       help='Enable verbose logging')
    group.add_argument('--turn-url', metavar='URL',
                       help='TURN server URL (e.g. turn:myserver.com:3478)')
    group.add_argument('--turn-user', metavar='USER',
                       help='TURN server username')
    group.add_argument('--turn-credential', metavar='PASS',
                       help='TURN server credential')
    group.add_argument('--pin', metavar='PIN',
                       help='PIN to protect access')
    return group


def bitbang_kwargs(args, program_name=None):
    """Convert parsed args to BitBang adapter constructor kwargs."""
    kwargs = {
        'program_name': program_name,
        'ephemeral': args.ephemeral,
        'identity_path': args.identity,
        'regenerate': args.regenerate,
        'server': args.server,
        'debug': args.debug,
        'pin': getattr(args, 'pin', None),
    }
    if args.turn_url:
        ice_server = {'urls': [args.turn_url]}
        if args.turn_user:
            ice_server['username'] = args.turn_user
        if args.turn_credential:
            ice_server['credential'] = args.turn_credential
        kwargs['ice_servers'] = [ice_server]
    return kwargs


class BitBangBase:
    """Base class for BitBang adapters.

    Handles WebRTC signaling, peer connections, and SWSP protocol.
    Subclasses implement app-specific request handling (WSGI or ASGI).

    Subclass and override setup_peer_connection() to add media tracks.
    """

    DEFAULT_SERVER = "bitba.ng"

    def __init__(self, app, server=None, debug=False,
                 ephemeral=False, identity_path=None, regenerate=False,
                 ice_servers=None, program_name=None,
                 pin=None, pin_callback=None):
        """Initialize the adapter.

        Args:
            app: Web application (WSGI or ASGI)
            server: Signaling server hostname (default: bitba.ng)
            debug: Enable verbose logging (ICE candidates, SDP, etc.)
            ephemeral: Use temporary identity (not saved to disk)
            identity_path: Path to specific identity file
            regenerate: Delete and regenerate identity
            ice_servers: Custom ICE server config (browser-native format)
            program_name: Program name for identity (e.g. 'fileshare', 'webcam')
            pin: Simple PIN string for access protection
            pin_callback: Function(path, pin) -> bool for custom auth logic.
                          Receives the connect path and PIN, returns True if valid.
                          Takes precedence over pin if both are set.
        """
        from .identity import load_or_create_identity, public_key_to_base64

        self.private_key, self.uid = load_or_create_identity(
            program_name=program_name,
            ephemeral=ephemeral,
            identity_path=identity_path,
            regenerate=regenerate
        )
        self.public_key_b64 = public_key_to_base64(self.private_key.public_key())

        self.app = app
        self.program_name = program_name
        self.server = server or self.DEFAULT_SERVER
        self.debug = debug
        self.ice_servers = ice_servers  # custom TURN config (browser-native format)
        self.pin = pin
        self.pin_callback = pin_callback
        self.ws_target = None  # Set to "host:port" to enable WebSocket bridging
        self.peers = {}  # client_id -> {'pc': RTCPeerConnection, 'channel': DataChannel}

    def setup_peer_connection(self, pc, client_id):
        """Hook for subclasses to add media tracks.

        Called after RTCPeerConnection is created but before offer is generated.
        Override this method to add video/audio tracks.

        Args:
            pc: RTCPeerConnection instance
            client_id: Unique identifier for this client connection
        """
        pass

    def get_stream_metadata(self):
        """Return stream metadata mapping mid -> name.

        Override this to provide stream names for media tracks.
        The bootstrap page uses this to wire <video>/<audio> elements.

        Returns:
            dict: Mapping of media line index to stream name
                  e.g., {"0": "webcam", "1": "microphone"}
        """
        return {}

    def _resolve_turn_ips(self, ice_servers):
        """Resolve TURN server hostnames to IPs for relay detection."""
        ips = set()
        for server in ice_servers:
            urls = server.get('urls', [])
            if isinstance(urls, str):
                urls = [urls]
            for url in urls:
                if url.startswith('turn'):
                    host = url.split(':')[1] if ':' in url else None
                    if host:
                        try:
                            ips.add(socket.gethostbyname(host))
                        except socket.gaierror:
                            pass
        return ips

    def _build_rtc_config(self, ice_servers):
        """Convert browser-native iceServers list to aiortc RTCConfiguration."""
        if not ice_servers:
            return RTCConfiguration([])
        rtc_servers = []
        for server in ice_servers:
            urls = server.get('urls', [])
            username = server.get('username')
            credential = server.get('credential')
            if username and credential:
                rtc_servers.append(RTCIceServer(
                    urls=urls, username=username, credential=credential
                ))
            else:
                rtc_servers.append(RTCIceServer(urls=urls))
        return RTCConfiguration(rtc_servers)

    async def connect(self):
        """Main signaling loop - connect to server and handle messages."""
        self._loop = asyncio.get_event_loop()
        uri = f"wss://{self.server}/ws/device/{self.uid}"
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        while True:
            try:
                print(f"Connecting to {self.server}...")
                async with websockets.connect(uri, ssl=ssl_context, ping_interval=60, ping_timeout=60) as ws:
                    if not await self._register(ws):
                        return
                    await self._message_loop(ws)

            except (OSError, websockets.exceptions.ConnectionClosed) as e:
                print(f"Connection lost: {e}, retrying in 3s...")
                await asyncio.sleep(3)
            except Exception as e:
                print(f"Unexpected error: {e}")
                await asyncio.sleep(3)

    async def _register(self, ws):
        """Send registration and handle challenge-response. Returns True on success."""
        from .identity import sign_challenge, print_qr_code

        from . import PROTOCOL_VERSION

        # Send registration with public key and protocol version
        reg = {
            'type': 'register',
            'uid': self.uid,
            'public_key': self.public_key_b64,
            'protocol': PROTOCOL_VERSION,
        }
        if self.ice_servers:
            reg['ice_servers'] = self.ice_servers
        await ws.send(json.dumps(reg))

        # Wait for challenge or registered
        while True:
            data = json.loads(await ws.recv())

            if data['type'] == 'challenge':
                # Sign the nonce and respond
                nonce = base64.b64decode(data['nonce'])
                signature = sign_challenge(self.private_key, nonce)
                await ws.send(json.dumps({
                    'type': 'challenge_response',
                    'signature': base64.b64encode(signature).decode('ascii')
                }))

            elif data['type'] == 'registered':
                url = f"https://{self.server}/{self.uid}"
                if self.debug:
                    url += "?debug"
                print(BANNER)
                from bitbang import __version__
                print(f"v{__version__}")
                if self.debug:
                    import aiortc
                    print(f"  aiortc {aiortc.__version__}, websockets {websockets.__version__}, Python {sys.version.split()[0]}")
                print()
                print_qr_code(url)
                print(f"\nReady: {url}\n")
                return True

            elif data['type'] == 'error':
                if data.get('message') == 'protocol_too_old':
                    print("\nPlease upgrade bitbang:")
                    print("  pip install --upgrade bitbang\n")
                else:
                    print(f"Registration failed: {data.get('message')}")
                return False

    async def _message_loop(self, ws):
        """Dispatch incoming signaling messages."""
        while True:
            data = json.loads(await ws.recv())
            msg_type = data.get('type')

            if msg_type == 'request':
                if self.debug:
                    print("Received connection request", data)
                await self.handle_request(ws, data)

            elif msg_type == 'answer':
                if self.debug:
                    print("Received answer", data)
                await self.handle_answer(ws, data)

            elif msg_type == 'candidate':
                if self.debug:
                    print("Received candidate", data)
                self._add_ice_candidate(data)

            elif msg_type == 'error':
                print(f"Signaling error: {data.get('message')}")

    def _add_ice_candidate(self, data):
        """Parse and add a remote ICE candidate to the peer connection."""
        client_id = data.get('client_id')
        if client_id not in self.peers:
            if self.debug:
                print(f"Unknown client_id in candidate: {client_id}")
            return

        pc = self.peers[client_id]['pc']
        candidate_info = data['candidate']
        cand_str = candidate_info['candidate']
        if cand_str.startswith('candidate:'):
            cand_str = cand_str[10:]

        candidate = candidate_from_sdp(cand_str)
        candidate.sdpMid = candidate_info['sdpMid']
        candidate.sdpMLineIndex = candidate_info['sdpMLineIndex']

        asyncio.ensure_future(pc.addIceCandidate(candidate))
        if self.debug:
            print(f"Added remote candidate for {client_id}")

    async def handle_request(self, ws, message):
        """Handle connection request from browser - create offer and send it."""
        try:
            client_id = message.get('client_id')

            # Clean up previous connection for this client if any
            if client_id in self.peers:
                await self.peers[client_id]['pc'].close()
                del self.peers[client_id]
                if self.debug:
                    print(f"Cleaned up previous connection for {client_id}")

            # Create peer connection with ICE servers from signaling server
            ice_servers = message.get('ice_servers') or []
            turn_ips = self._resolve_turn_ips(ice_servers)
            pc = RTCPeerConnection(self._build_rtc_config(ice_servers))

            # Allow subclasses to add media tracks
            self.setup_peer_connection(pc, client_id)

            # Create DataChannel (we are the offerer, so we create it)
            channel = pc.createDataChannel("http")
            if self.debug:
                print(f"Created datachannel: {channel.label} for {client_id}")

            # Store peer info
            self.peers[client_id] = {
                'pc': pc,
                'channel': channel,
                'pending_requests': {}  # stream_id -> {'meta': {...}, ...}
            }

            @channel.on("open")
            def on_open():
                self._log_connection_type(pc, turn_ips)

            @channel.on("message")
            async def on_message(msg, cid=client_id):
                await self.handle_datachannel_message(channel, msg, cid)

            # Create and send offer
            await self._create_and_send_offer(ws, pc, client_id)

        except Exception as e:
            print(f"Error handling request: {e}")
            traceback.print_exc()

    async def _create_and_send_offer(self, ws, pc, client_id):
        """Gather ICE candidates and send the offer to the browser."""
        # Create Offer
        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)

        # Wait for ICE gathering to complete (aiortc bundles candidates in SDP)
        while pc.iceGatheringState != "complete":
            await asyncio.sleep(0.1)
        if self.debug:
            print(f"ICE gathering complete for {client_id}")

        # Get the SDP with all candidates included
        local = pc.localDescription

        # Build stream metadata map (mid -> name)
        streams = self._build_stream_metadata(pc)

        # Send Offer to browser via signaling server
        response = {
            "type": "offer",
            "sdp": local.sdp,
            "client_id": client_id,
            "streams": streams,
        }
        if self.program_name:
            response["device_name"] = self.program_name
        await ws.send(json.dumps(response))
        if self.debug:
            print(f"Sent offer with ICE candidates for {client_id}, streams: {streams}")

    def _log_connection_type(self, pc, turn_ips):
        """Check if connection is using TURN relay and log the result.

        Path: pc.sctp (SCTP) -> .transport (DTLS) -> .transport (ICE) -> ._connection
        """
        try:
            ice = pc.sctp.transport.transport
            pair = ice._connection._nominated.get(1)
            if pair:
                local_type = pair.local_candidate.type
                remote_type = pair.remote_candidate.type
                # "relay" type means this side allocated a TURN relay.
                # But when the *remote* side relays through TURN, we
                # discover the relay address via connectivity checks and
                # it shows as "prflx" -- so also check the IP directly.
                is_relay = (local_type == "relay" or remote_type == "relay" or
                            pair.remote_candidate.host in turn_ips or
                            pair.local_candidate.host in turn_ips)
                if is_relay:
                    print("Client connected (via TURN relay)")
                else:
                    print(f"Client connected (direct: {local_type}/{remote_type})")
            else:
                print("Client connected")
        except Exception as e:
            print(f"Client connected (could not check ICE type: {e})")

    def _build_stream_metadata(self, pc):
        """Build stream metadata from peer connection transceivers."""
        custom_streams = self.get_stream_metadata()
        streams = {}

        for transceiver in pc.getTransceivers():
            if transceiver.sender and transceiver.sender.track:
                mid = transceiver.mid
                if mid is not None:
                    mid_str = str(mid)
                    if mid_str in custom_streams:
                        streams[mid_str] = custom_streams[mid_str]
                    else:
                        track_kind = transceiver.sender.track.kind
                        if track_kind == 'video':
                            streams[mid_str] = 'video'
                        elif track_kind == 'audio':
                            streams[mid_str] = 'audio'

        return streams

    async def handle_answer(self, websocket, message):
        """Handle answer from browser - set remote description."""
        try:
            client_id = message.get('client_id')
            if client_id not in self.peers:
                if self.debug:
                    print(f"Unknown client_id in answer: {client_id}")
                return

            pc = self.peers[client_id]['pc']

            sdp_source = message['sdp']
            if isinstance(sdp_source, str) and sdp_source.strip().startswith('{'):
                try:
                    sdp_json = json.loads(sdp_source)
                    sdp_val = sdp_json.get('sdp', sdp_source)
                except json.JSONDecodeError:
                    sdp_val = sdp_source
            else:
                sdp_val = sdp_source

            obj = RTCSessionDescription(sdp=sdp_val, type="answer")
            await pc.setRemoteDescription(obj)
            if self.debug:
                print(f"Set remote description with answer for {client_id}")

        except Exception as e:
            print(f"Error handling answer: {e}")
            traceback.print_exc()

    # -- WebSocket bridging --------------------------------------------------

    async def _handle_ws_open(self, channel, stream_id, request, peer):
        """Handle a WebSocket open request (SYN with type 'websocket')."""
        if not self.ws_target:
            # No target configured, send FIN to reject
            channel.send(struct.pack('<IHH', stream_id, FLAG_FIN, 0))
            return

        pathname = request.get('pathname', '/')
        uri = f"ws://{self.ws_target}{pathname}"

        if self.debug:
            print(f"WS open: {pathname} (stream={stream_id})")

        # Track this stream as a WebSocket connection
        if 'ws_conns' not in peer:
            peer['ws_conns'] = {}

        try:
            ws = await websockets.connect(uri, ping_interval=None)
        except Exception as e:
            print(f"WS connect failed: {pathname} -> {e}")
            channel.send(struct.pack('<IHH', stream_id, FLAG_FIN, 0))
            return

        peer['ws_conns'][stream_id] = ws

        # Send SYN ack to browser (tells ws-shim the connection is open)
        channel.send(struct.pack('<IHH', stream_id, FLAG_SYN, 0))

        if self.debug:
            print(f"WS opened: {pathname} (stream={stream_id})")

        # Read from local WS, forward to browser as DAT frames
        async def ws_reader():
            try:
                async for msg in ws:
                    if isinstance(msg, str):
                        data = b'\x00' + msg.encode('utf-8')  # 0 = text
                    else:
                        data = b'\x01' + msg  # 1 = binary
                    channel.send(struct.pack('<IHH', stream_id, FLAG_DAT, len(data)) + data)
            except websockets.exceptions.ConnectionClosed:
                pass
            except Exception as e:
                if self.debug:
                    print(f"WS reader error (stream={stream_id}): {e}")
            finally:
                # Send FIN to browser
                channel.send(struct.pack('<IHH', stream_id, FLAG_FIN, 0))
                peer['ws_conns'].pop(stream_id, None)
                if self.debug:
                    print(f"WS closed: {pathname} (stream={stream_id})")

        asyncio.ensure_future(ws_reader())

    async def _handle_ws_frame(self, channel, stream_id, flags, payload, peer):
        """Handle a DAT or FIN frame for an active WebSocket stream."""
        ws = peer.get('ws_conns', {}).get(stream_id)
        if not ws:
            return

        if flags & FLAG_FIN:
            # Browser closed the WebSocket
            await ws.close()
            peer['ws_conns'].pop(stream_id, None)
            return

        if len(payload) < 1:
            return

        # Parse type byte + message
        type_byte = payload[0]
        data = payload[1:]

        try:
            if type_byte == 0:
                await ws.send(data.decode('utf-8'))
            else:
                await ws.send(data)
        except Exception as e:
            if self.debug:
                print(f"WS write failed (stream={stream_id}): {e}")
            await ws.close()

    def _send_control(self, channel, msg, fin=False):
        """Send a control message on streamId 0."""
        payload = json.dumps(msg).encode('utf-8')
        flags = FLAG_SYN | FLAG_FIN if fin else FLAG_SYN
        channel.send(struct.pack('<IHH', 0, flags, len(payload)) + payload)

    def _handle_control_message(self, channel, payload, client_id=None):
        """Handle control messages on streamId 0 (connect/auth handshake)."""
        try:
            msg = json.loads(payload.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return

        if msg.get('type') == 'connect':
            path = msg.get('path', '/')
            if self.debug:
                print(f"Connect handshake: path={path}")

            # Store the connect path for PIN callback
            if client_id and client_id in self.peers:
                self.peers[client_id]['connect_path'] = path

            if self._pin_required(path):
                self._send_control(channel, {"type": "auth_required"})
            else:
                self._send_control(channel, {"type": "ready"}, fin=True)

        elif msg.get('type') == 'auth':
            pin = msg.get('pin', '')
            path = '/'
            if client_id and client_id in self.peers:
                path = self.peers[client_id].get('connect_path', '/')

            if self._verify_pin(path, pin):
                print("PIN auth succeeded")
                self._send_control(channel, {"type": "auth_result", "success": True}, fin=True)
            else:
                print("PIN auth failed")
                self._send_control(channel, {"type": "auth_result", "success": False}, fin=True)

    def _pin_required(self, path='/'):
        """Check if PIN auth is required for this path."""
        if self.pin_callback:
            return not self.pin_callback(path, '')
        return self.pin is not None

    def _verify_pin(self, path, pin):
        """Verify PIN. Returns True if valid."""
        if self.pin_callback:
            return self.pin_callback(path, pin)
        return self.pin is not None and pin == self.pin

    async def handle_datachannel_message(self, channel, message, client_id):
        """Handle SWSP binary request from browser and send SWSP response."""
        if not isinstance(message, bytes):
            print("Received non-binary message on http channel (unexpected)")
            return

        try:
            # Parse 8-byte SWSP header
            stream_id = int.from_bytes(message[0:4], 'little')
            flags = int.from_bytes(message[4:6], 'little')
            length = int.from_bytes(message[6:8], 'little')
            payload = message[8:8+length]

            # StreamId 0 is reserved for control messages (connect/ready/auth)
            if stream_id == 0:
                if flags & FLAG_SYN:
                    self._handle_control_message(channel, payload, client_id)
                return

            peer = self.peers.get(client_id)
            if not peer:
                return
            pending = peer['pending_requests']

            # Check if this is a WebSocket stream (DAT/FIN for active WS)
            ws_conns = peer.get('ws_conns', {})
            if stream_id in ws_conns and not (flags & FLAG_SYN):
                await self._handle_ws_frame(channel, stream_id, flags, payload, peer)
                return

            # SYN flag indicates new request
            if flags & FLAG_SYN:
                request = json.loads(payload.decode('utf-8'))

                # WebSocket open request
                if request.get('type') == 'websocket':
                    await self._handle_ws_open(channel, stream_id, request, peer)
                    return

                if flags & FLAG_FIN:
                    # SYN|FIN: complete request in one frame (no body)
                    await self._handle_swsp_request(channel, stream_id, request, None, client_id=client_id)
                else:
                    # SYN only: expect body frames to follow
                    content_len = request.get('contentLength', 0)
                    temp_file = tempfile.NamedTemporaryFile(delete=False)
                    pending[stream_id] = {
                        'meta': request,
                        'temp_file': temp_file,
                        'temp_path': temp_file.name,
                        'bytes': 0,
                        'start': time.time(),
                        'content_len': content_len,
                        'filename': None
                    }

            elif stream_id in pending:
                req_data = pending[stream_id]

                # Write body chunks to temp file
                if length > 0:
                    req_data['temp_file'].write(payload)
                    req_data['bytes'] += length

                    # Extract filename from first chunk (multipart header)
                    if req_data['filename'] is None and req_data['bytes'] == length:
                        filename = self._extract_multipart_filename(payload)
                        req_data['filename'] = filename or 'unknown'
                        size_str = self._format_size(req_data['content_len'])
                        print(f"Upload started: {req_data['filename']} ({size_str})")

                    # Update progress bar
                    total = req_data['content_len']
                    if total > 1024 * 1024:
                        elapsed = time.time() - req_data['start']
                        self._print_upload_progress(req_data['bytes'], total, elapsed)

                if flags & FLAG_FIN:
                    # Request complete - process it
                    req_data = pending.pop(stream_id)
                    elapsed = time.time() - req_data['start']
                    speed = req_data['bytes'] / elapsed / (1024 * 1024) if elapsed > 0 else 0
                    filename = req_data.get('filename', 'unknown')

                    # Clear progress bar and print completion
                    if req_data['content_len'] > 1024 * 1024:
                        sys.stdout.write('\r' + ' ' * 80 + '\r')
                    print(f"Upload complete: {filename} ({self._format_size(req_data['bytes'])}) in {elapsed:.1f}s @ {speed:.1f} MB/s")

                    # Seek to beginning for reading
                    req_data['temp_file'].seek(0)

                    # Update content length with actual bytes received
                    meta = req_data['meta']
                    if req_data['bytes'] > 0:
                        meta['contentLength'] = req_data['bytes']

                    try:
                        await self._handle_swsp_request(channel, stream_id, meta, req_data['temp_file'], client_id=client_id)
                    finally:
                        req_data['temp_file'].close()
                        try:
                            os.unlink(req_data['temp_path'])
                        except OSError:
                            pass

        except Exception as e:
            print(f"Error handling datachannel message: {e}")
            traceback.print_exc()

    async def _handle_swsp_request(self, channel, stream_id, request, body=None, client_id=None):
        """Process SWSP request - subclasses must implement."""
        raise NotImplementedError("Subclasses must implement _handle_swsp_request")

    def _send_error_response(self, channel, stream_id, error_msg):
        """Send a 500 error response."""
        error_json = json.dumps({
            "status": 500,
            "headers": {"Content-Type": "text/plain"}
        }).encode('utf-8')
        channel.send(struct.pack('<IHH', stream_id, FLAG_SYN, len(error_json)) + error_json)
        error_body = f"Internal Server Error: {error_msg}".encode('utf-8')
        channel.send(struct.pack('<IHH', stream_id, FLAG_DAT, len(error_body)) + error_body)
        channel.send(struct.pack('<IHH', stream_id, FLAG_FIN, 0))

    def _log_download(self, pathname):
        """Log download requests."""
        if '/download' in pathname:
            if 'path=' in pathname:
                query = pathname.split('?', 1)[1] if '?' in pathname else ''
                params = urllib.parse.parse_qs(query)
                if 'path' in params:
                    filename = params['path'][0].split('/')[-1]
                    print(f"Download of {filename} requested")
                    return
            print("Download requested")

    def _get_backpressure_params(self, client_id):
        """Get the backpressure high-water mark and SCTP transport for a peer.

        On Windows, aiortc's pure-Python SCTP floods the shared UDP socket,
        causing ICE consent checks (RFC 7675) to fail after ~30s. Limit the
        total backlog (app buffer + SCTP in-flight) to keep consent alive.
        On other platforms this isn't an issue so we use a larger buffer.
        """
        pc = self.peers.get(client_id, {}).get('pc') if client_id else None
        sctp = pc.sctp if pc and hasattr(pc, 'sctp') and pc.sctp else None

        if sys.platform == 'win32' and sctp:
            limit = 128 * 1024
        else:
            limit = 4 * 1024 * 1024

        return limit, sctp

    async def _send_with_backpressure(self, channel, frame, limit, sctp):
        """Send a frame, waiting if the buffer is too full."""
        while True:
            flight = sctp._flight_size if sctp else 0
            total_backlog = channel.bufferedAmount + flight
            if total_backlog <= limit:
                break
            await asyncio.sleep(0.01)
        channel.send(frame)

    def _extract_multipart_filename(self, data):
        """Extract filename from multipart form data header."""
        try:
            header = data[:500].decode('utf-8', errors='ignore')
            match = re.search(r'filename="([^"]+)"', header)
            if match:
                return match.group(1)
        except Exception:
            pass
        return None

    def _format_size(self, size):
        """Format file size for display."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:.1f} {unit}" if unit != 'B' else f"{size} {unit}"
            size /= 1024
        return f"{size:.1f} PB"

    def _print_upload_progress(self, received, total, elapsed):
        """Print upload progress bar that updates in place."""
        speed = received / elapsed if elapsed > 0 else 0
        speed_mb = speed / (1024 * 1024)
        received_mb = received / (1024 * 1024)
        total_mb = total / (1024 * 1024)
        pct = received / total if total > 0 else 0
        bar_width = 30
        filled = int(bar_width * pct)
        bar = '=' * filled + '>' + ' ' * (bar_width - filled - 1) if filled < bar_width else '=' * bar_width
        line = f"\rUpload: [{bar}] {received_mb:.1f}/{total_mb:.1f} MB ({pct*100:.0f}%) @ {speed_mb:.1f} MB/s"
        sys.stdout.write(line)
        sys.stdout.flush()

    def _print_progress(self, sent, total, start_time, done=False):
        """Print a progress bar that updates in place."""
        elapsed = time.time() - start_time
        speed = sent / elapsed if elapsed > 0 else 0
        speed_mb = speed / (1024 * 1024)
        sent_mb = sent / (1024 * 1024)
        total_mb = total / (1024 * 1024)

        if total > 0:
            pct = sent / total
            bar_width = 30
            filled = int(bar_width * pct)
            bar = '=' * filled + '>' + ' ' * (bar_width - filled - 1)
            line = f"\r[{bar}] {sent_mb:.1f}/{total_mb:.1f} MB ({pct*100:.0f}%) @ {speed_mb:.1f} MB/s"
        else:
            line = f"\r{sent_mb:.1f} MB @ {speed_mb:.1f} MB/s"

        if done:
            sys.stdout.write('\r' + ' ' * 80 + '\r')
            print(f"Sent {sent_mb:.1f} MB in {elapsed:.1f}s ({speed_mb:.1f} MB/s)")
        else:
            sys.stdout.write(line)
            sys.stdout.flush()

    async def close(self):
        """Close all peer connections and cleanup resources."""
        for client_id, peer_info in list(self.peers.items()):
            await peer_info['pc'].close()
        self.peers.clear()

    def run(self):
        """Run the signaling loop (blocking)."""
        try:
            asyncio.run(self.connect())
        except KeyboardInterrupt:
            # Suppress noisy shutdown warnings from asyncio and aiortc threads
            import logging
            logging.getLogger('asyncio').setLevel(logging.CRITICAL)
            threading.excepthook = lambda args: None
            print("\nShutting down...")


class BitBangWSGI(BitBangBase):
    """BitBang adapter for WSGI apps (Flask, Django)."""

    async def _handle_swsp_request(self, channel, stream_id, request, body=None, client_id=None):
        """Process SWSP request through WSGI app.

        The WSGI app runs in a thread so that blocking generators (e.g. SSE
        with time.sleep) don't stall the asyncio event loop. Frames are passed
        back via an asyncio queue.
        """
        method = request.get('method', 'GET')
        pathname = request.get('pathname', '/')
        content_type = request.get('contentType', '')
        content_length = request.get('contentLength', 0)
        headers = request.get('headers', {})

        if self.debug:
            print(f"SWSP request: {method} {pathname} (stream={stream_id})")

        self._log_download(pathname)

        limit, sctp = self._get_backpressure_params(client_id)

        # Thread-to-asyncio bridge: the WSGI thread produces frames into a
        # bounded queue.Queue (thread-safe). The thread blocks on put() when
        # full, providing natural backpressure. The event loop reads with
        # run_in_executor wrapping the blocking get().
        import queue as queue_mod
        frame_queue = queue_mod.Queue(maxsize=64)
        _DONE = object()

        def produce_frames():
            """Run the WSGI app in a thread, push frames onto the queue."""
            try:
                for frame in self._stream_wsgi_response(stream_id, method, pathname, body, content_type, content_length, headers):
                    frame_queue.put(frame)  # blocks when queue is full
            except Exception as e:
                frame_queue.put(e)
            finally:
                frame_queue.put(_DONE)

        thread = threading.Thread(target=produce_frames, daemon=True)
        thread.start()

        loop = asyncio.get_event_loop()

        try:
            while True:
                # Blocking get() runs in executor so it doesn't stall the event loop
                item = await loop.run_in_executor(None, frame_queue.get)
                if item is _DONE:
                    break
                if isinstance(item, Exception):
                    raise item
                if channel.readyState != "open":
                    break
                await self._send_with_backpressure(channel, item, limit, sctp)

        except Exception as e:
            print(f"Error handling SWSP request: {e}")
            traceback.print_exc()
            self._send_error_response(channel, stream_id, str(e))

    def _stream_wsgi_response(self, stream_id, method, pathname, body=None, content_type='', content_length=0, headers=None):
        """Generator that yields SWSP frames from WSGI response."""
        headers_set = []

        def start_response(status, response_headers, exc_info=None):
            headers_set[:] = [status, response_headers]
            return lambda s: None

        # Parse path and query string
        if '?' in pathname:
            path_info, query_string = pathname.split('?', 1)
        else:
            path_info = pathname
            query_string = ''

        if not path_info.startswith('/'):
            path_info = '/' + path_info

        # Handle different body types for wsgi.input
        if body is None:
            wsgi_input = io.BytesIO(b'')
        elif hasattr(body, 'read'):
            wsgi_input = body
        else:
            wsgi_input = io.BytesIO(body)

        environ = {
            'REQUEST_METHOD': method,
            'PATH_INFO': path_info,
            'QUERY_STRING': query_string,
            'SERVER_NAME': self.server,
            'SERVER_PORT': '443',
            'HTTP_HOST': self.server,
            'wsgi.url_scheme': 'https',
            'wsgi.input': wsgi_input,
            'wsgi.errors': sys.stderr,
            'CONTENT_TYPE': content_type,
            'CONTENT_LENGTH': str(content_length) if content_length else '',
        }

        # Inject request headers into WSGI environ (HTTP_* keys per WSGI spec).
        # This forwards cookies, authorization, and other headers from the SW.
        if headers:
            for key, value in headers.items():
                wsgi_key = 'HTTP_' + key.upper().replace('-', '_')
                if wsgi_key == 'HTTP_CONTENT_TYPE':
                    environ['CONTENT_TYPE'] = value
                elif wsgi_key == 'HTTP_CONTENT_LENGTH':
                    environ['CONTENT_LENGTH'] = value
                else:
                    environ[wsgi_key] = value

        result = self.app(environ, start_response)

        try:
            status_str, headers_list = headers_set
            status_code = int(status_str.split()[0]) if isinstance(status_str, str) else int(status_str)

            # Build headers dict, preserving multiple Set-Cookie values as
            # an array (the SW cookie jar handles both string and array).
            resp_headers = {}
            set_cookies = []
            for key, value in headers_list:
                if key.lower() == 'set-cookie':
                    set_cookies.append(value)
                else:
                    resp_headers[key] = value
            if len(set_cookies) == 1:
                resp_headers['Set-Cookie'] = set_cookies[0]
            elif len(set_cookies) > 1:
                resp_headers['Set-Cookie'] = set_cookies

            total_bytes = int(resp_headers.get('Content-Length', 0))

            # SYN frame with headers
            header_json = json.dumps({"status": status_code, "headers": resp_headers}).encode('utf-8')
            yield struct.pack('<IHH', stream_id, FLAG_SYN, len(header_json)) + header_json

            # DAT frames with body chunks
            bytes_sent = 0
            start_time = time.time()
            last_update = 0
            show_progress = total_bytes > 1024 * 1024

            for data in result:
                if isinstance(data, str):
                    data = data.encode('utf-8')
                for i in range(0, len(data), SWSP_CHUNK_SIZE):
                    chunk = data[i:i+SWSP_CHUNK_SIZE]
                    yield struct.pack('<IHH', stream_id, FLAG_DAT, len(chunk)) + chunk
                    bytes_sent += len(chunk)

                    now = time.time()
                    if show_progress and now - last_update >= 0.1:
                        last_update = now
                        self._print_progress(bytes_sent, total_bytes, start_time)

            # FIN frame
            yield struct.pack('<IHH', stream_id, FLAG_FIN, 0)

            if show_progress:
                self._print_progress(bytes_sent, total_bytes, start_time, done=True)

        finally:
            if hasattr(result, 'close'):
                result.close()


class BitBangASGI(BitBangBase):
    """BitBang adapter for ASGI apps (FastAPI, Starlette)."""

    async def _handle_swsp_request(self, channel, stream_id, request, body=None, client_id=None):
        """Process SWSP request through ASGI app."""
        method = request.get('method', 'GET')
        pathname = request.get('pathname', '/')
        content_type = request.get('contentType', '')
        content_length = request.get('contentLength', 0)
        req_headers = request.get('headers', {})

        if self.debug:
            print(f"SWSP request: {method} {pathname} (stream={stream_id})")

        self._log_download(pathname)

        limit, sctp = self._get_backpressure_params(client_id)

        try:
            async for frame in self._stream_asgi_response(stream_id, method, pathname, body, content_type, content_length, req_headers):
                if channel.readyState != "open":
                    break
                await self._send_with_backpressure(channel, frame, limit, sctp)

        except Exception as e:
            print(f"Error handling SWSP request: {e}")
            traceback.print_exc()
            self._send_error_response(channel, stream_id, str(e))

    async def _stream_asgi_response(self, stream_id, method, pathname, body=None, content_type='', content_length=0, req_headers=None):
        """Async generator that yields SWSP frames from ASGI response.

        Frames are yielded as the ASGI app produces them, so streaming
        responses (SSE, chunked transfer) work correctly.
        """

        # Parse path and query string
        if '?' in pathname:
            path_info, query_string = pathname.split('?', 1)
        else:
            path_info = pathname
            query_string = ''

        if not path_info.startswith('/'):
            path_info = '/' + path_info

        # Read body data
        if body is None:
            body_data = b''
        elif hasattr(body, 'read'):
            body_data = body.read()
        else:
            body_data = body

        # Build ASGI scope headers from forwarded request headers
        headers = []
        if req_headers:
            for key, value in req_headers.items():
                headers.append((key.lower().encode(), value.encode()))
        # Override content-type and content-length from SWSP metadata
        if content_type:
            headers = [(k, v) for k, v in headers if k != b'content-type']
            headers.append((b'content-type', content_type.encode()))
        if content_length:
            headers = [(k, v) for k, v in headers if k != b'content-length']
            headers.append((b'content-length', str(content_length).encode()))

        scope = {
            'type': 'http',
            'asgi': {'version': '3.0'},
            'http_version': '1.1',
            'method': method,
            'path': path_info,
            'query_string': query_string.encode(),
            'headers': headers,
            'server': (self.server, 443),
        }

        # Create receive callable
        body_sent = False
        async def receive():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {'type': 'http.request', 'body': body_data, 'more_body': False}
            return {'type': 'http.request', 'body': b'', 'more_body': False}

        # Queue for frames produced by the ASGI send() callback.
        # The ASGI app pushes frames as it produces body chunks;
        # the outer async generator yields them to the caller.
        frame_queue = asyncio.Queue(maxsize=64)
        _DONE = object()

        bytes_sent = 0
        start_time = time.time()
        last_update = 0
        total_bytes = 0
        show_progress = False

        async def send(message):
            nonlocal total_bytes, show_progress, bytes_sent, last_update
            if message['type'] == 'http.response.start':
                resp_headers = {}
                set_cookies = []
                for k, v in message.get('headers', []):
                    name, value = k.decode(), v.decode()
                    if name.lower() == 'set-cookie':
                        set_cookies.append(value)
                    else:
                        resp_headers[name] = value
                if len(set_cookies) == 1:
                    resp_headers['Set-Cookie'] = set_cookies[0]
                elif len(set_cookies) > 1:
                    resp_headers['Set-Cookie'] = set_cookies

                total_bytes = int(resp_headers.get('content-length', 0))
                show_progress = total_bytes > 1024 * 1024

                # SYN frame with headers
                status_code = message['status']
                header_json = json.dumps({"status": status_code, "headers": resp_headers}).encode('utf-8')
                await frame_queue.put(struct.pack('<IHH', stream_id, FLAG_SYN, len(header_json)) + header_json)

            elif message['type'] == 'http.response.body':
                chunk = message.get('body', b'')
                if chunk:
                    for i in range(0, len(chunk), SWSP_CHUNK_SIZE):
                        part = chunk[i:i+SWSP_CHUNK_SIZE]
                        await frame_queue.put(struct.pack('<IHH', stream_id, FLAG_DAT, len(part)) + part)
                        bytes_sent += len(part)

                        now = time.time()
                        if show_progress and now - last_update >= 0.1:
                            last_update = now
                            self._print_progress(bytes_sent, total_bytes, start_time)

                # If more_body is False (or absent), this is the last chunk
                if not message.get('more_body', False):
                    await frame_queue.put(_DONE)

        # Run the ASGI app as a task so we can yield frames as they arrive
        async def run_app():
            try:
                await self.app(scope, receive, send)
            except Exception as e:
                await frame_queue.put(e)
            finally:
                # Ensure _DONE is sent even if the app didn't signal end-of-body
                try:
                    frame_queue.put_nowait(_DONE)
                except asyncio.QueueFull:
                    pass

        app_task = asyncio.create_task(run_app())

        try:
            while True:
                item = await frame_queue.get()
                if item is _DONE:
                    break
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            app_task.cancel()
            try:
                await app_task
            except asyncio.CancelledError:
                pass

        # FIN frame
        yield struct.pack('<IHH', stream_id, FLAG_FIN, 0)

        if show_progress:
            self._print_progress(bytes_sent, total_bytes, start_time, done=True)


