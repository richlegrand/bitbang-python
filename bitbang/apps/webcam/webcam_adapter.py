"""BitBang Webcam adapter - extends PsiWSGI with webcam video track.

This module provides WebcamPsiWSGI which adds a webcam video track
to the base PsiWSGI adapter. It uses MediaRelay to share a single
webcam source across multiple clients.

Usage:
    from flask import Flask
    from webcam_adapter import WebcamBitBang

    app = Flask(__name__)

    @app.route('/')
    def index():
        return open('index.html').read()

    adapter = WebcamBitBang(app)
    adapter.run()
"""

import sys
from bitbang import BitBangWSGI
from aiortc.contrib.media import MediaPlayer, MediaRelay


def _find_windows_camera():
    """Discover the first available camera on Windows via PowerShell."""
    import subprocess
    try:
        result = subprocess.run(
            ['powershell', '-Command',
             'Get-PnpDevice -Class Camera -Status OK | Select-Object -ExpandProperty FriendlyName'],
            capture_output=True, text=True, timeout=5
        )
        name = result.stdout.strip().split('\n')[0].strip()
        if name:
            return name
    except Exception:
        pass
    return None


def _default_webcam():
    """Return (device, format, options) for the current platform."""
    if sys.platform == 'darwin':
        return '0:none', 'avfoundation', {'framerate': '30', 'video_size': '640x480'}
    elif sys.platform == 'win32':
        camera = _find_windows_camera()
        if camera:
            print(f"Found camera: {camera}")
            return f'video={camera}', 'dshow', {'framerate': '30', 'video_size': '640x480'}
        else:
            print("No camera found, trying default")
            return 'video=0', 'dshow', {'framerate': '30', 'video_size': '640x480'}
    else:
        return '/dev/video0', 'v4l2', {'framerate': '30', 'video_size': '640x480'}


class WebcamBitBang(BitBangWSGI):
    """BitBang Webcam adapter - adds webcam video track to connections.

    Extends BitBangWSGI to capture video from /dev/video0 and share it
    with all connected clients using MediaRelay.
    """

    def __init__(self, app, **kwargs):
        super().__init__(app, **kwargs)
        self.relay = MediaRelay()

        # Open webcam at startup so we fail fast with a clear message
        device, fmt, options = _default_webcam()
        try:
            self.player = MediaPlayer(device, format=fmt, options=options)
            print(f"Opened webcam: {device}")
        except Exception as e:
            print(f"Error: Could not open webcam '{device}': {e}")
            sys.exit(1)

    def setup_peer_connection(self, pc, client_id):
        """Add webcam video track to peer connection."""

        if self.player.video:
            pc.addTrack(self.relay.subscribe(self.player.video))
            print(f"Added relayed webcam video track for {client_id}")

    def get_stream_metadata(self):
        """Return stream name for video track."""
        if self.player and self.player.video:
            return {"0": "webcam"}
        return {}

    async def close(self):
        """Close peer connections and media player."""
        await super().close()

        if self.player:
            if self.player.video:
                self.player.video.stop()
            self.player = None
