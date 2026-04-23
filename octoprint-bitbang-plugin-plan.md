# OctoPrint BitBang Plugin — Implementation Plan

## Overview

A single OctoPrint plugin that provides:

1. **Remote UI access** — Full OctoPrint web interface via BitBang P2P tunnel
2. **Low-latency video** — H.264 passthrough to WebRTC (no transcode)
3. **Extensible frame hook** — Entry point for community-built failure detection

No account. No subscription. No port forwarding. One shareable link.

## Value Proposition

| Feature | OctoEverywhere | Obico | BitBang Plugin |
|---------|----------------|-------|----------------|
| Remote access | ✓ | ✓ | ✓ |
| Video streaming | ✓ | ✓ | ✓ (WebRTC) |
| Failure detection | ✗ | ✓ ($) | Hook for community |
| Account required | Yes | Yes | No |
| Subscription | $2.49/mo+ | $4/mo+ | Free |
| Data routing | Their servers | Their servers | P2P |
| Open source | No | Partial | Yes |

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Raspberry Pi                                 │
│                                                                  │
│  ┌──────────────┐     ┌─────────────────────────────────────┐   │
│  │ USB Camera   │     │         BitBang Plugin              │   │
│  └──────┬───────┘     │                                     │   │
│         │             │  ┌─────────────┐  ┌──────────────┐  │   │
│         ▼             │  │ HTTP/WS     │  │ Video        │  │   │
│  ┌──────────────┐     │  │ Tunnel      │  │ Stream       │  │   │
│  │ camera-      │     │  │             │  │              │  │   │
│  │ streamer     │     │  │ OctoPrint   │  │ RTSP H.264   │  │   │
│  │              │     │  │ localhost   │  │ passthrough  │  │   │
│  │ • MJPEG      │     │  │ :5000       │  │ via aiortc   │  │   │
│  │ • H.264      │     │  └──────┬──────┘  └──────┬───────┘  │   │
│  │ • RTSP       │─────│─────────┼────────────────┤          │   │
│  └──────────────┘     │         └────────┬───────┘          │   │
│                       │                  │                  │   │
│                       │           WebRTC Connection         │   │
│                       │           (data + media)            │   │
│                       └──────────────────┼──────────────────┘   │
│                                          │                      │
└──────────────────────────────────────────┼──────────────────────┘
                                           │ P2P (or TURN relay)
                                           ▼
                                    ┌──────────────┐
                                    │   Browser    │
                                    │              │
                                    │ • OctoPrint  │
                                    │   UI         │
                                    │ • Video      │
                                    │   <video>    │
                                    └──────────────┘
```

## Camera Stack Compatibility

| Stack | Input | Method |
|-------|-------|--------|
| camera-streamer (new) | `rtsp://localhost:8554/stream.h264` | Passthrough (`decode=False`) |
| mjpg-streamer (old) | `http://localhost:8080/?action=stream` | Transcode (`decode=True`) |

The plugin auto-detects which stack is running and chooses the optimal path.

## Implementation

### Plugin Structure

```
OctoPrint-BitBang/
├── octoprint_bitbang/
│   ├── __init__.py           # Plugin entry point
│   ├── bitbang_service.py    # Core BitBang + video service
│   ├── video_track.py        # aiortc video handling
│   ├── frame_hook.py         # Extensible frame processing
│   └── static/
│       └── js/
│           └── bitbang.js    # Settings UI
├── setup.py
├── requirements.txt
└── README.md
```

### Core Plugin Class

```python
# octoprint_bitbang/__init__.py

import octoprint.plugin
from .bitbang_service import BitBangService

class BitBangPlugin(
    octoprint.plugin.StartupPlugin,
    octoprint.plugin.ShutdownPlugin,
    octoprint.plugin.SettingsPlugin,
    octoprint.plugin.TemplatePlugin,
    octoprint.plugin.AssetPlugin,
):
    def __init__(self):
        self._service = None

    def on_after_startup(self):
        self._service = BitBangService(
            proxy_target="localhost:5000",
            video_source=self._detect_video_source(),
            on_frame=self.on_frame,
            logger=self._logger,
        )
        self._service.start()
        
        self._logger.info(f"BitBang remote access: {self._service.public_url}")

    def on_shutdown(self):
        if self._service:
            self._service.stop()

    def _detect_video_source(self):
        """Auto-detect camera-streamer (RTSP) or mjpg-streamer (MJPEG)."""
        import socket
        
        # Try RTSP first (new stack)
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('localhost', 8554))
            sock.close()
            if result == 0:
                return {
                    "url": "rtsp://localhost:8554/stream.h264",
                    "format": "rtsp",
                    "passthrough": True
                }
        except:
            pass
        
        # Fall back to MJPEG (old stack)
        return {
            "url": "http://localhost:8080/?action=stream",
            "format": None,
            "passthrough": False
        }

    def on_frame(self, frame):
        """
        Override point for frame processing.
        
        Called every N frames (configurable). Frame is a numpy array (H, W, 3).
        Return a dict to trigger an alert, or None to continue.
        
        Example:
            def on_frame(self, frame):
                result = my_model.predict(frame)
                if result["spaghetti"] > 0.8:
                    return {"type": "spaghetti", "confidence": result["spaghetti"]}
                return None
        """
        pass

    def get_settings_defaults(self):
        return {
            "enabled": True,
            "frame_interval": 30,  # Process every Nth frame
            "auto_pause_on_failure": False,
        }

__plugin_name__ = "BitBang"
__plugin_pythoncompat__ = ">=3.7,<4"
__plugin_implementation__ = BitBangPlugin()
```

### Video Service with aiortc

```python
# octoprint_bitbang/bitbang_service.py

import asyncio
import threading
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaPlayer

class BitBangService:
    def __init__(self, proxy_target, video_source, on_frame=None, logger=None):
        self.proxy_target = proxy_target
        self.video_source = video_source
        self.on_frame = on_frame
        self.logger = logger
        
        self._thread = None
        self._loop = None
        self._pc = None
        self.public_url = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        if self._loop:
            self._loop.call_soon_threadsafe(self._shutdown)

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._main())

    async def _main(self):
        # Connect to BitBang signaling
        proxy_id = await self._register_with_bitbang()
        self.public_url = f"https://bitba.ng/{proxy_id}"
        
        # Wait for incoming connections
        while True:
            offer = await self._wait_for_offer()
            await self._handle_connection(offer)

    async def _handle_connection(self, offer):
        self._pc = RTCPeerConnection()
        
        # Add video track
        player = MediaPlayer(
            self.video_source["url"],
            format=self.video_source.get("format"),
            decode=not self.video_source.get("passthrough", False)
        )
        
        if player.video:
            if self.on_frame and not self.video_source.get("passthrough"):
                # Wrap track with frame hook (only if decoding)
                track = FrameHookTrack(player.video, self.on_frame)
                self._pc.addTrack(track)
            else:
                self._pc.addTrack(player.video)
        
        # Set up data channel for HTTP/WS tunnel
        # ... (existing BitBang proxy logic)
        
        # Complete WebRTC handshake
        await self._pc.setRemoteDescription(offer)
        answer = await self._pc.createAnswer()
        await self._pc.setLocalDescription(answer)
        
        await self._send_answer(answer)
```

### Frame Hook for Extensibility

```python
# octoprint_bitbang/frame_hook.py

from aiortc import MediaStreamTrack
import numpy as np

class FrameHookTrack(MediaStreamTrack):
    """
    Wraps a video track to tap frames for processing.
    
    Note: Only works when decode=True (not passthrough mode).
    For passthrough, frames must be tapped separately from the RTSP stream.
    """
    
    kind = "video"
    
    def __init__(self, track, callback, interval=30):
        super().__init__()
        self.track = track
        self.callback = callback
        self.interval = interval
        self._count = 0

    async def recv(self):
        frame = await self.track.recv()
        
        self._count += 1
        if self._count % self.interval == 0 and self.callback:
            # Convert to numpy for processing
            img = frame.to_ndarray(format="rgb24")
            result = self.callback(img)
            
            if result:
                # Trigger alert (pause print, notification, etc.)
                self._handle_alert(result)
        
        return frame

    def _handle_alert(self, result):
        # Hook for pause/notify logic
        pass
```

### Passthrough + Separate Frame Tap

For H.264 passthrough mode, we can't tap frames from aiortc (no decode). Instead, tap directly from RTSP:

```python
# octoprint_bitbang/frame_tap.py

import av
import threading
import time

class FrameTap:
    """
    Separate thread that taps frames from RTSP for processing,
    independent of the passthrough video stream.
    """
    
    def __init__(self, rtsp_url, callback, interval=30, fps=30):
        self.rtsp_url = rtsp_url
        self.callback = callback
        self.interval = interval
        self.fps = fps
        
        self._running = False
        self._thread = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _run(self):
        container = av.open(self.rtsp_url)
        frame_count = 0
        
        for frame in container.decode(video=0):
            if not self._running:
                break
                
            frame_count += 1
            if frame_count % self.interval == 0:
                img = frame.to_ndarray(format="rgb24")
                result = self.callback(img)
                
                if result:
                    self._handle_alert(result)
            
            # Don't spin faster than source FPS
            time.sleep(1 / self.fps)

        container.close()
```

## Phases

### Phase 1: Core Plugin (Week 1)
- [ ] Plugin skeleton with OctoPrint lifecycle hooks
- [ ] Auto-detect camera stack (RTSP vs MJPEG)
- [ ] Basic settings UI (enable/disable, show link)
- [ ] Integrate existing BitBang Python client for HTTP/WS tunnel

### Phase 2: Video Streaming (Week 2)
- [ ] aiortc integration with MediaPlayer
- [ ] H.264 passthrough mode (`decode=False`)
- [ ] MJPEG fallback with transcode
- [ ] Browser-side video element integration

### Phase 3: Frame Hook (Week 3)
- [ ] FrameTap for passthrough mode
- [ ] Callback interface for frame processing
- [ ] Alert mechanism (pause print via OctoPrint API)
- [ ] Basic notification support (webhook)

### Phase 4: Polish & Release (Week 4)
- [ ] Settings UI refinement
- [ ] Documentation
- [ ] Example failure detection model (TFLite)
- [ ] Submit to plugins.octoprint.org

## Community Extension Points

The plugin exposes clean hooks for community contributions:

### 1. Failure Detection Models

```python
# Example: Community spaghetti detector

import tflite_runtime.interpreter as tflite

class SpaghettiDetector:
    def __init__(self):
        self.interpreter = tflite.Interpreter(model_path="spaghetti.tflite")
        self.interpreter.allocate_tensors()
    
    def __call__(self, frame):
        # Preprocess
        input_data = self.preprocess(frame)
        
        # Inference
        self.interpreter.set_tensor(self.input_idx, input_data)
        self.interpreter.invoke()
        output = self.interpreter.get_tensor(self.output_idx)
        
        if output[0] > 0.8:
            return {"type": "spaghetti", "confidence": float(output[0])}
        return None
```

### 2. Notification Integrations

```python
# Example: Discord webhook

class DiscordNotifier:
    def __init__(self, webhook_url):
        self.webhook_url = webhook_url
    
    def notify(self, alert, snapshot):
        requests.post(self.webhook_url, json={
            "content": f"🚨 Print failure detected: {alert['type']}",
            "embeds": [{"image": {"url": snapshot}}]
        })
```

### 3. Custom Frame Processors

```python
# Example: Timelapse generator

class TimelapseCapture:
    def __init__(self, output_dir):
        self.output_dir = output_dir
        self.frame_num = 0
    
    def __call__(self, frame):
        path = f"{self.output_dir}/frame_{self.frame_num:06d}.jpg"
        cv2.imwrite(path, cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
        self.frame_num += 1
        return None  # No alert
```

## Dependencies

```
# requirements.txt

aiortc>=1.4.0
aiohttp>=3.8.0
av>=10.0.0
numpy>=1.20.0

# Optional for failure detection
tflite-runtime>=2.10.0  # or tensorflow-lite
opencv-python-headless>=4.5.0
```

## Resources

- [OctoPrint Plugin Tutorial](https://docs.octoprint.org/en/master/plugins/gettingstarted.html)
- [aiortc Documentation](https://aiortc.readthedocs.io/)
- [camera-streamer GitHub](https://github.com/ayufan/camera-streamer)
- [Print Nanny Dataset](https://github.com/print-nanny/print-nanny-client) — Training data for failure detection
- [Obico ML Models](https://github.com/TheSpaghettiDetective/obico-server) — Reference implementations

## Open Questions

1. **QR code for mobile?** Display QR in OctoPrint UI for easy phone access
2. **Multiple cameras?** Some setups have 2+ cameras
3. **Audio?** Useful for detecting stepper skips, grinding sounds
4. **Bandwidth adaptation?** Dynamic bitrate based on connection quality
