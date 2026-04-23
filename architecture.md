# BitBang Browser Architecture Specification

## Overview

BitBang connects browsers to remote devices/apps ("bangs") via WebRTC. The browser-side architecture has three layers:

1. **Bootstrap page** — served by the signaling server, manages the WebRTC connection
2. **Service worker** — intercepts HTTP requests from the iframe and routes them through the WebRTC data channel
3. **Iframe** — renders the device/app's HTML as a full page, isolated from bootstrap code

The goal is that the device/app author writes a normal web app (HTML, CSS, JS) as if they're running a standard web server. They should not need to understand WebRTC, signaling, or data channels. The only BitBang-specific feature exposed to them is media stream injection via a `data-bitbang-stream` attribute.

## Connection Flow

```
Step 1: Browser navigates to https://bitba.ng/<uid>
        Signaling server serves bootstrap.html

Step 2: Bootstrap page:
        a. Registers service worker (SW) for this scope
        b. Opens WebSocket to signaling server
        c. Receives SDP offer from device (relayed through signaling server)
           - Offer includes stream metadata:
             {
               "type": "offer",
               "sdp": "v=0\r\n...",
               "streams": {
                 "0": "camera-front",
                 "1": "camera-rear"
               }
             }
           - The keys are "mid" values (media line indices in SDP)
           - The values are human-friendly stream names chosen by the device author
        d. Creates and sends SDP answer
        e. ICE candidate exchange (trickle or gathered)
        f. WebRTC peer connection established
        g. Media streams received via pc.ontrack
        h. Data channel opened

Step 3: Bootstrap page creates full-viewport iframe
        iframe.src = "/app" (or "/")
        Service worker intercepts this fetch

Step 4: Service worker routes "/app" request through data channel
        Device responds with its HTML page
        Service worker returns it as a Response to the iframe

Step 5: Iframe renders device HTML as a complete, isolated page
        All subsequent fetches (CSS, JS, images, API calls) from
        the iframe are intercepted by the service worker and routed
        through the data channel to the device

Step 6: Bootstrap page reaches into iframe DOM and wires up media streams
```

## Component Details

### Bootstrap Page (bootstrap.html)

Served by the signaling server. This page is always present but hidden behind the iframe. It holds the WebRTC connection for the lifetime of the session.

Responsibilities:
- Display connection progress UI during setup
- Manage WebSocket connection to signaling server
- Handle SDP offer/answer exchange
- Manage RTCPeerConnection
- Collect media streams and map them to friendly names
- Register the service worker
- Bridge between service worker and data channel (via postMessage)
- Create the iframe once connection is established
- Reach into iframe DOM after load to wire up media streams

```javascript
// === Connection Progress UI ===

const STATUS = {
    CONNECTING_SERVER: "Connecting to BitBang...",
    SERVER_CONNECTED: "Server connected",
    FINDING_DEVICE: "Looking for device...",
    DEVICE_FOUND: "Device online!",
    WAITING_OFFER: "Requesting connection...",
    OFFER_RECEIVED: "Connection offer received",
    SENDING_ANSWER: "Establishing connection...",
    ICE_CHECKING: "Finding best path...",
    CONNECTED: "Connected!"
};

// === Media Stream Collection ===

// Stream name mapping received with the offer
// Keys are mid values, values are device-author-chosen names
let streamNameMap = {};  // { "0": "camera-front", "1": "camera-rear" }

// Resolved streams: friendly name -> MediaStream
const resolvedStreams = {};

function handleOffer(msg) {
    streamNameMap = msg.streams || {};
    // ... set remote description, create answer, etc.
}

pc.ontrack = (event) => {
    const mid = event.transceiver.mid;
    const name = streamNameMap[mid] || mid;  // fallback to mid if no name
    resolvedStreams[name] = event.streams[0];
};

// === Service Worker Bridge ===
// The service worker cannot hold the data channel directly.
// Communication between SW and bootstrap happens via postMessage.

// SW -> Bootstrap: "please fetch this URL via data channel"
navigator.serviceWorker.addEventListener('message', async (event) => {
    const { requestId, url, method, headers, body } = event.data;

    // Serialize as HTTP-like request over data channel
    dataChannel.send(JSON.stringify({
        requestId,
        method,
        url,
        headers,
        body
    }));
});

// Device -> Bootstrap (via data channel) -> SW
dataChannel.onmessage = (event) => {
    const response = JSON.parse(event.data);

    // Forward to service worker
    navigator.serviceWorker.controller.postMessage({
        requestId: response.requestId,
        status: response.status,
        headers: response.headers,
        body: response.body
    });
};

// === Iframe Creation ===
// Only after: data channel is open AND service worker is ready

async function launchApp() {
    await navigator.serviceWorker.ready;

    const iframe = document.createElement('iframe');
    iframe.style.cssText = `
        position: fixed;
        top: 0; left: 0;
        width: 100%; height: 100%;
        border: none;
        z-index: 9999;
    `;

    iframe.onload = () => {
        wireUpMediaStreams(iframe);
    };

    iframe.src = '/';  // Service worker intercepts, fetches from device
    document.body.appendChild(iframe);

    // Hide connection progress UI
    document.getElementById('connection-ui').style.display = 'none';
}

// === Media Stream Injection ===
// After iframe loads, scan its DOM for data-bitbang-stream attributes
// and attach the corresponding MediaStream objects.

function wireUpMediaStreams(iframe) {
    const doc = iframe.contentDocument;

    const elements = doc.querySelectorAll('[data-bitbang-stream]');
    elements.forEach(el => {
        const name = el.getAttribute('data-bitbang-stream');

        if (name === '') {
            // <video data-bitbang-stream> with no value = use default stream
            // Default is the first stream in resolvedStreams
            const firstKey = Object.keys(resolvedStreams)[0];
            if (firstKey) {
                el.srcObject = resolvedStreams[firstKey];
            }
        } else {
            // <video data-bitbang-stream="camera-front"> = use named stream
            if (resolvedStreams[name]) {
                el.srcObject = resolvedStreams[name];
            } else {
                console.warn(`BitBang: no stream found with name "${name}"`);
            }
        }
    });

    // Also expose streams for device JS that needs programmatic access
    iframe.contentWindow.__bitbang = {
        streams: resolvedStreams,
        getStream: (name) => resolvedStreams[name],
        getDefaultStream: () => resolvedStreams[Object.keys(resolvedStreams)[0]]
    };
}
```

### Service Worker (sw.js)

Registered by the bootstrap page. Intercepts all fetch requests from the iframe and routes them through the bootstrap page (which forwards them through the data channel to the device).

The service worker cannot directly access the data channel. All communication with the data channel goes through the bootstrap page via postMessage.

#### Routing Strategy: frameType-based

The service worker needs to distinguish between:
- Requests from the **bootstrap page** (should go to the server normally)
- Requests from the **iframe** (should be proxied through the data channel)

**Why not use path prefixes?** Initially we considered reserving a path prefix like `/_bb/` for bootstrap assets. However, CDN providers like Cloudflare may inject their own scripts (Rocket Loader, analytics, challenge scripts) at unpredictable paths. We can't maintain an allowlist of paths we don't control.

**Solution: Route based on who's asking, not what they're asking for.**

The service worker can inspect `client.frameType` to determine if a request originated from:
- `'top-level'` — the bootstrap page (parent window)
- `'nested'` — the iframe (device content)

This is robust because the architecture itself defines the routing — bootstrap is always top-level, device content is always in the iframe.

```javascript
// Pending requests awaiting response
const pendingRequests = new Map();

self.addEventListener('fetch', async (event) => {
    const url = new URL(event.request.url);

    // Only intercept requests to our origin
    // Let external CDN requests (fonts, libraries) pass through normally
    if (url.origin !== self.location.origin) {
        return;
    }

    // Get the client that made this request
    const client = await self.clients.get(event.clientId);

    // No client, or top-level window — serve from server normally
    // This includes bootstrap page AND any CDN-injected scripts (e.g., Cloudflare)
    if (!client || client.frameType === 'top-level') {
        return;
    }

    // Nested frame (iframe) — proxy through data channel
    if (client.frameType === 'nested') {
        event.respondWith(fetchViaDataChannel(event));
    }
});

async function fetchViaDataChannel(event) {
    const requestId = crypto.randomUUID();

    // Find the bootstrap page (it holds the data channel)
    // Bootstrap is always the top-level window
    const allClients = await self.clients.matchAll({ type: 'window' });
    const bootstrap = allClients.find(c => c.frameType === 'top-level');

    if (!bootstrap) {
        return new Response('BitBang: no connection', { status: 503 });
    }

    // Ask bootstrap to fetch via data channel
    bootstrap.postMessage({
        requestId,
        url: event.request.url,
        method: event.request.method,
        headers: Object.fromEntries(event.request.headers),
        body: await event.request.text()
    });

    // Wait for response from bootstrap
    return new Promise((resolve, reject) => {
        const timeout = setTimeout(() => {
            pendingRequests.delete(requestId);
            resolve(new Response('BitBang: request timeout', { status: 504 }));
        }, 30000);

        pendingRequests.set(requestId, { resolve, timeout });
    });
}

// Receive responses forwarded from bootstrap page
self.addEventListener('message', (event) => {
    const { requestId, status, headers, body } = event.data;
    const pending = pendingRequests.get(requestId);

    if (pending) {
        clearTimeout(pending.timeout);
        pending.resolve(new Response(body, {
            status: status || 200,
            headers: headers || {}
        }));
        pendingRequests.delete(requestId);
    }
});
```

### Iframe (device content)

The iframe renders whatever HTML the device/app serves. The device author writes a normal web page. They do NOT need to understand WebRTC, signaling, or data channels.

#### Simple case: one video stream

The device author just adds the `data-bitbang-stream` attribute to a video element. The bootstrap page automatically attaches the stream after load.

```html
<!DOCTYPE html>
<html>
<head>
    <title>My Webcam</title>
    <style>
        video { width: 100%; max-width: 640px; }
    </style>
</head>
<body>
    <h1>Live Camera</h1>
    <video data-bitbang-stream autoplay muted playsinline></video>
    <p>Streaming via BitBang</p>
</body>
</html>
```

No JavaScript required. The bootstrap page finds the `data-bitbang-stream` attribute and wires up the default (first) media stream.

#### Multiple named streams

```html
<video data-bitbang-stream="camera-front" autoplay muted playsinline></video>
<video data-bitbang-stream="camera-rear" autoplay muted playsinline></video>
<audio data-bitbang-stream="microphone" autoplay></audio>
```

Stream names correspond to names declared by the device when adding tracks.

#### Advanced: programmatic stream access

For device authors who need direct access to streams (e.g., drawing to canvas, applying filters, WebAudio processing):

```html
<script>
    // __bitbang is injected by the bootstrap page after iframe loads
    // It may not be available immediately, so check or wait
    function onBitBangReady() {
        const stream = window.__bitbang.getStream('camera-front');
        const video = document.getElementById('source');
        video.srcObject = stream;

        // Now draw to canvas with effects, etc.
    }

    // Simple polling check (or use MutationObserver on window.__bitbang)
    const check = setInterval(() => {
        if (window.__bitbang) {
            clearInterval(check);
            onBitBangReady();
        }
    }, 50);
</script>
```

#### Normal HTTP — no BitBang awareness needed

For non-media apps (file browser, print server), the device author writes completely standard HTML/JS with no BitBang-specific code at all:

```html
<!DOCTYPE html>
<html>
<body>
    <h1>Shared Files</h1>
    <div id="files"></div>
    <script>
        // This is a normal fetch. The service worker transparently
        // routes it through the data channel to the device.
        fetch('/api/files')
            .then(r => r.json())
            .then(files => {
                document.getElementById('files').innerHTML =
                    files.map(f => `<a href="/download/${f}">${f}</a>`).join('<br>');
            });
    </script>
</body>
</html>
```

The device author does not know or care that `/api/files` was routed through WebRTC. It's just a fetch.

## Data Channel Protocol

HTTP requests and responses are serialized as JSON over the WebRTC data channel.

### Request (browser -> device)

```json
{
    "requestId": "uuid-string",
    "method": "GET",
    "url": "/api/files",
    "headers": {
        "Accept": "application/json"
    },
    "body": ""
}
```

### Response (device -> browser)

```json
{
    "requestId": "uuid-string",
    "status": 200,
    "headers": {
        "Content-Type": "application/json"
    },
    "body": "[\"file1.txt\", \"file2.jpg\"]"
}
```

Note: Binary data (images, file downloads) will need base64 encoding or a separate binary data channel. This is an implementation detail to resolve — consider using a binary data channel with a header prefix for the requestId, or chunked transfer for large payloads.

## Stream Declaration Protocol

When the device creates the SDP offer, it includes a `streams` metadata object alongside the SDP. This maps `mid` values (media line indices in the SDP) to friendly stream names.

### Device side (when adding tracks)

```python
# The device author writes:
bang.add_video("camera-front", front_camera_track)
bang.add_video("camera-rear", rear_camera_track)
bang.add_audio("microphone", mic_track)

# Internally, BitBang library tracks the mid -> name mapping
# and includes it in the signaling message with the offer
```

### Signaling message format

```json
{
    "type": "offer",
    "sdp": "v=0\r\n...",
    "streams": {
        "0": "camera-front",
        "1": "camera-rear",
        "2": "microphone"
    }
}
```

### Browser side (bootstrap)

```javascript
// Parse stream map from offer message
const streamNameMap = offerMsg.streams || {};

// As ontrack fires, map mid -> friendly name -> MediaStream
pc.ontrack = (event) => {
    const mid = event.transceiver.mid;
    const name = streamNameMap[mid] || mid;
    resolvedStreams[name] = event.streams[0];
};
```

## Key Design Principles

1. **Device author writes normal HTML/JS.** No BitBang SDK required for non-media apps. Standard fetch, standard DOM, standard everything.

2. **Media streams are the one exception.** Video/audio requires the `data-bitbang-stream` attribute or programmatic access via `window.__bitbang`. This is the only BitBang-specific API surface exposed to device authors.

3. **Iframe provides isolation.** Device CSS cannot affect bootstrap UI. Device JS cannot stomp bootstrap globals. Device code cannot access the WebRTC connection directly.

4. **Bootstrap page is the hidden orchestrator.** It holds the WebRTC connection, bridges the service worker to the data channel, and wires up media streams. It exists for the lifetime of the session but is invisible to the user after connection.

5. **Service worker is the invisible transport.** It makes the data channel look like normal HTTP. The iframe doesn't know its fetches are going through WebRTC.

## Open Implementation Questions

- **Binary data over data channel:** JSON with base64 is simple but doubles file sizes. A binary channel with length-prefixed requestId headers would be more efficient for file transfers. Needs design decision.

- **Large file chunking:** Data channel messages have size limits (~256KB typically, configurable). Large responses (firmware uploads, big file downloads) need chunking and reassembly. The service worker should handle streaming responses.

- **Service worker lifecycle:** Browsers can terminate idle service workers. Need to ensure the SW stays alive during active sessions, or handle restart gracefully.

- **iframe.onload timing:** If the device's HTML includes async scripts that create `data-bitbang-stream` elements dynamically after page load, `iframe.onload` will fire before those elements exist. May need a MutationObserver fallback or a `BitBang.ready()` signal from the device.

- **Multiple simultaneous viewers:** Each browser connection is a separate WebRTC peer connection from the device. The device needs to handle multiple data channels and potentially multiple media encodings. This is a device-side concern, not a browser architecture concern.
