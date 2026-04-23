# BitBangProxy Design Document

## Overview

BitBangProxy is a Go binary using Pion WebRTC that acts as a gateway from the public internet to any machine on the local network. It extends the existing BitBang ecosystem with a standalone proxy that requires no Python on the target machine.

## Current State

**Existing and working:**
- Python library (`bitbang` package) with Flask/FastAPI integration
- Working apps: fileshare, webcam
- Signaling server deployed at `bitba.ng`
- Browser runtime in [bitbang-server](https://github.com/richlegrand/bitbang-server) repo:
  - `bootstrap.js` — WebRTC connection management, SWSP protocol
  - `sw.js` — Service worker intercepting `/__device__/*` requests
- RSA identity system with challenge-response authentication
- SWSP (Simple WebRTC Streaming Protocol) for HTTP over data channels

**What BitBangProxy adds:**
- Go binary that proxies any local server without Python
- Dynamic target from URL (future milestone)

**Current limitation:**
The existing `bootstrap.js` ignores any path after the UID. Given URL `https://bitba.ng/<uid>/hello/there`, it extracts the UID but then loads `/__device__/` in the iframe — the `/hello/there` portion is discarded. This needs to be fixed to support path-based routing and per-path PIN protection.

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                      REMOTE BROWSER                          │
│                                                              │
│  Existing browser runtime (bootstrap.js, sw.js)              │
│  connects to BitBangProxy exactly like a Python device       │
│                                                              │
└─────────────────────────┬────────────────────────────────────┘
                          │ WebRTC
                          │
┌─────────────────────────┼────────────────────────────────────┐
│              SIGNALING SERVER (bitba.ng)                     │
│              (existing, no changes needed)                   │
└─────────────────────────┬────────────────────────────────────┘
                          │ WebRTC
                          │
┌─────────────────────────┼────────────────────────────────────┐
│                    LOCAL NETWORK                             │
│                                                              │
│  ┌─────────────────┐                                         │
│  │  BITBANGPROXY   │        ┌─────────────┐                  │
│  │  (Go binary)    │───────▶│ Web Server  │                  │
│  │                 │        │ (any local) │                  │
│  └─────────────────┘        └─────────────┘                  │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

## Connection Handshake with Path

When the data channel opens, the browser must send the requested path to the device. This enables path-based access control and per-path PIN protection.

### URL Format

```
https://bitba.ng/<uid>/<path>
```

Examples:
```
https://bitba.ng/a3f8c2e9.../              → path: /
https://bitba.ng/a3f8c2e9.../admin         → path: /admin
https://bitba.ng/a3f8c2e9.../hello/there   → path: /hello/there
```

For BitBangProxy with dynamic target:
```
https://bitba.ng/<proxy-id>/<target>/<path>
```

Examples:
```
https://bitba.ng/a3f8c2e9.../nas.local:8080/           → target: nas.local:8080, path: /
https://bitba.ng/a3f8c2e9.../192.168.1.10/admin        → target: 192.168.1.10, path: /admin
```

### Handshake Flow (SWSP on streamId 0)

```
Browser                              Device/Proxy
   │                                       │
   │◀────── data channel opens ────────────│
   │                                       │
   │  SYN streamId=0                       │
   │── { "type": "connect",  ─────────────▶│
   │     "path": "/hello/there" }          │
   │                                       │
   │            (device evaluates path)    │
   │                                       │
   │  SYN streamId=0                       │
   │◀── { "type": "ready" } ───────────────│  (no PIN needed)
   │                                       │
   │  OR                                   │
   │                                       │
   │  SYN streamId=0                       │
   │◀── { "type": "auth_required" } ───────│  (PIN needed)
   │                                       │
   │  OR                                   │
   │                                       │
   │  SYN|FIN streamId=0                   │
   │◀── { "type": "error",  ───────────────│  (path rejected)
   │      "message": "Access denied" }     │
   │                                       │
```

After `ready` (or successful PIN auth), `bootstrap.js` loads `/__device__<path>` in the iframe.

### Browser Changes Required (bitbang-server repo)

Current `bootstrap.js` behavior:
```javascript
// Current code (simplified)
const pathParts = window.location.pathname.split('/').filter(Boolean);
const uid = pathParts[0];
// pathParts[1], pathParts[2], etc. are IGNORED
// ...
iframe.src = '/__device__/';  // Always loads /
```

Required changes:
```javascript
// New behavior
const pathParts = window.location.pathname.split('/').filter(Boolean);
const uid = pathParts[0];
const devicePath = '/' + pathParts.slice(1).join('/');  // e.g., "/hello/there"

// On data channel open, send connect message
const connectMsg = { type: 'connect', path: devicePath };
dataChannel.send(createFrame(0, FLAG_SYN, JSON.stringify(connectMsg)));

// Wait for response before creating iframe
// ...

// Load the actual path, not just /
iframe.src = '/__device__' + devicePath;
```

---

## BitBang PIN Mechanism

BitBang supports optional PIN protection for devices and proxies. PIN authentication happens over the DTLS-encrypted data channel, so the signaling server never sees the PIN.

### Why Data Channel?

The WebRTC data channel is encrypted end-to-end with DTLS. The signaling server cannot see the contents. This means:
- No hashing needed — PIN can be sent plaintext over the encrypted channel
- No nonce needed — DTLS prevents replay attacks
- No URL fragments — URL is just `https://bitba.ng/<uid>`
- No signaling server changes — it remains a dumb relay

### Per-Path PIN Protection

Devices can require PIN for specific paths:

| Path | PIN Required |
|------|--------------|
| `/` | No |
| `/public/*` | No |
| `/admin/*` | Yes |
| `/settings` | Yes |

The device evaluates the path from the `connect` message and responds with either `ready` or `auth_required`.

### Full Handshake with PIN

```
Browser                              Device/Proxy
   │                                       │
   │◀────── data channel opens ────────────│
   │                                       │
   │  SYN streamId=0                       │
   │── { "type": "connect",  ─────────────▶│
   │     "path": "/admin" }                │
   │                                       │
   │         (device: /admin requires PIN) │
   │                                       │
   │  SYN streamId=0                       │
   │◀── { "type": "auth_required" } ───────│
   │                                       │
   │  (bootstrap.js shows PIN prompt)      │
   │                                       │
   │  SYN streamId=0                       │
   │── { "type": "auth",  ────────────────▶│
   │     "pin": "1234" }                   │
   │                                       │
   │                   (device verifies PIN)
   │                                       │
   │  SYN|FIN streamId=0                   │
   │◀── { "type": "auth_result",  ─────────│
   │      "success": true }                │
   │                                       │
   │  (bootstrap.js creates iframe,        │
   │   loads /__device__/admin)            │
   │                                       │
```

### Failure Case

```json
{
  "type": "auth_result",
  "success": false,
  "message": "Invalid PIN",
  "remaining": 2
}
```

- `bootstrap.js` shows error screen with message
- User can retry (if `remaining` > 0)
- Device tracks failed attempts for rate limiting

### Rate Limiting

Device enforces:
- 3 attempts, then 30 second backoff
- Configurable lockout after N total failures
- Rate limit tracked per connection (close connection after too many failures)

### Security Properties

| Threat | Mitigation |
|--------|------------|
| Signaling server eavesdropping | DTLS encryption — server sees nothing |
| Replay attack | DTLS session is unique per connection |
| Online brute force | Device rate limits attempts |
| Offline brute force | Not possible — attacker never sees PIN |

### BitBangProxy PIN Integration

```bash
# Start proxy with PIN protection for all paths
bitbangproxy --pin 1234

# Or configure per-path protection (future)
bitbangproxy --pin-path "/admin/*:1234" --pin-path "/settings:5678"
```

Output:
```
BitBangProxy v0.1.0
Identity: a3f8c2e91b4d7f08...
URL: https://bitba.ng/a3f8c2e91b4d7f08

PIN protection enabled.

Proxying: localhost:8080
Connected to signaling server.
```

The proxy:
1. Stores PIN(s) in identity file
2. On data channel open, waits for `connect` message with path
3. Evaluates path against PIN rules
4. Sends `ready` or `auth_required`
5. If auth required, waits for `auth`, verifies, sends `auth_result`
6. If success, proceeds with normal SWSP proxying

---

## SWSP Protocol (Existing)

BitBang uses **SWSP (Simple WebRTC Streaming Protocol)** for HTTP over data channels. This is implemented in `bootstrap.js` and must be matched exactly.

### Frame Format

```
┌──────────────┬──────────────┬──────────────┬─────────────────┐
│ Stream ID    │ Flags        │ Length       │ Payload         │
│ (4 bytes LE) │ (2 bytes LE) │ (2 bytes LE) │ (variable)      │
└──────────────┴──────────────┴──────────────┴─────────────────┘
```

### Flags

```go
const (
    FLAG_SYN = 0x0001  // Start of stream, payload is JSON metadata
    FLAG_FIN = 0x0004  // End of stream
    FLAG_DAT = 0x0000  // Data chunk (implicit, no flags set)
)
```

### Control Messages (streamId 0)

StreamId 0 is reserved for control messages:

| Message | Direction | Purpose |
|---------|-----------|---------|
| `connect` | Browser → Device | Initial handshake with path |
| `ready` | Device → Browser | No auth needed, proceed |
| `auth_required` | Device → Browser | PIN required |
| `auth` | Browser → Device | PIN submission |
| `auth_result` | Device → Browser | Auth success/failure |
| `error` | Device → Browser | Connection rejected |

### Request (Browser → Proxy)

**SYN frame payload (JSON):**
```json
{
  "method": "GET",
  "pathname": "/api/status"
}
```

For POST/PUT:
```json
{
  "method": "POST",
  "pathname": "/upload",
  "contentLength": 1048576,
  "contentType": "application/octet-stream"
}
```

Followed by DAT frames (body chunks, max ~16KB each), then FIN.

### Response (Proxy → Browser)

**SYN frame payload (JSON):**
```json
{
  "status": 200,
  "headers": {
    "Content-Type": "text/html",
    "Content-Length": "1234"
  }
}
```

Followed by DAT frames (body chunks), then FIN.

### Go Implementation

```go
const (
    FlagSYN = 0x0001
    FlagFIN = 0x0004
)

type Frame struct {
    StreamID uint32
    Flags    uint16
    Payload  []byte
}

func ParseFrame(data []byte) Frame {
    return Frame{
        StreamID: binary.LittleEndian.Uint32(data[0:4]),
        Flags:    binary.LittleEndian.Uint16(data[4:6]),
        Payload:  data[8 : 8+binary.LittleEndian.Uint16(data[6:8])],
    }
}

func BuildFrame(streamID uint32, flags uint16, payload []byte) []byte {
    buf := make([]byte, 8+len(payload))
    binary.LittleEndian.PutUint32(buf[0:4], streamID)
    binary.LittleEndian.PutUint16(buf[4:6], flags)
    binary.LittleEndian.PutUint16(buf[6:8], uint16(len(payload)))
    copy(buf[8:], payload)
    return buf
}
```

## Signaling Protocol (Existing)

Same as Python BitBang — see `signaling.py` in bitbang-server.

### Device Registration

```
Device → Server:  { "type": "register", "public_key": "<base64 DER>" }
Server → Device:  { "type": "challenge", "nonce": "<base64>" }
Device → Server:  { "type": "challenge_response", "signature": "<base64>" }
Server → Device:  { "type": "registered" }
```

### Connection Flow

```
Browser connects via /ws/client/<uid>
Server → Device:  { "type": "request", "client_id": "..." }
Device → Server:  { "type": "offer", "client_id": "...", "sdp": "..." }
Server → Browser: { "type": "offer", "sdp": "...", "ice_servers": [...] }
Browser → Server: { "type": "answer", "sdp": "..." }
Server → Device:  { "type": "answer", "client_id": "...", "sdp": "..." }

ICE candidates (trickle ICE, relayed in both directions):
Device → Server:  { "type": "candidate", "client_id": "...", "candidate": {...} }
Server → Browser: { "type": "candidate", "candidate": {...} }
Browser → Server: { "type": "candidate", "candidate": {...} }
Server → Device:  { "type": "candidate", "client_id": "...", "candidate": {...} }
```

No PIN-related signaling messages — all PIN auth happens over the data channel after WebRTC connection is established.

## Identity

Same as existing BitBang:
- RSA 2048-bit key pair
- UID = `sha256(publicKeyDER)[:16]` → 32 hex characters
- Stored in `~/.bitbang/bitbangproxy/identity.pem`
- `--ephemeral` for throwaway identity
- When PIN enabled: PIN stored alongside identity

## Test Environment

The signaling server is protocol-agnostic -- it just relays JSON messages and doesn't care whether the device is Python or Go. Test directly against `bitba.ng` using `--ephemeral` identities. No separate instance needed.

For offline development, run the signaling server locally: `cd signaling && ./run.sh` (listens on port 8081).

---

# Versioned Implementation Plan

## Phase 1: Core HTTP Proxy (Hardcoded Target)

Uses existing browser runtime unchanged. Proxy forwards all requests to `localhost:8080`.

---

### Version 0.1: Identity & Signaling

**Goal:** Connect to signaling server, authenticate, receive connection requests.

**Functionality:**
- RSA key pair generation and persistence
- WebSocket connection to signaling server
- Challenge-response authentication
- Receive `request` messages from server
- Log connection attempts

**Files:**
```
cmd/bitbangproxy/main.go
internal/identity/identity.go
internal/signaling/client.go
```

**Test:**
1. Start proxy: `bitbangproxy`
2. Open browser to `https://bitba.ng/<uid>`
3. Proxy logs: "Received connection request from client_id: ..."

**Success:** Proxy authenticates and receives connection requests.

---

### Version 0.2: Peer Connection

**Goal:** Establish WebRTC peer connection with browser.

**Functionality:**
- Create Pion PeerConnection with ICE servers from `request` message
- Generate SDP offer with data channel
- Exchange offer/answer via signaling
- Relay trickle ICE candidates bidirectionally
- Data channel opens

**Files:**
```
internal/peer/connection.go
```

**Test:**
1. Start proxy
2. Browser connects
3. Proxy logs: "Data channel opened"
4. Browser console shows: "DataChannel opened"

**Success:** Data channel established between browser and proxy.

---

### Version 0.3: SWSP Frames

**Goal:** Parse and generate SWSP frames correctly.

**Functionality:**
- Parse incoming frames (streamId, flags, payload)
- Generate outgoing frames
- Echo test: receive frame, send it back

**Files:**
```
internal/protocol/swsp.go
internal/protocol/swsp_test.go
```

**Test:**
1. Unit tests for frame parsing/building
2. Integration: modify browser to send test frame, verify echo

**Success:** Frames round-trip correctly.

---

### Version 0.4: Single HTTP GET

**Goal:** Proxy a single HTTP GET request to localhost:8080.

**Functionality:**
- Receive SYN frame with request metadata
- Make HTTP GET to `http://localhost:8080/<pathname>`
- Send SYN response frame with status/headers
- Send response body as DAT frames
- Send FIN frame

**Files:**
```
internal/proxy/http.go
```

**Test:**
1. Start local server: `python3 -m http.server 8080`
2. Create `index.html`: `<h1>Hello from local server</h1>`
3. Start proxy
4. Browser navigates to `https://bitba.ng/<uid>`
5. Page shows "Hello from local server"

**Success:** Browser displays content from local server.

---

### Version 0.5: Streaming Responses

**Goal:** Handle responses that stream over time (SSE, chunked).

**Functionality:**
- Send DAT frames incrementally as data arrives
- Don't buffer entire response before sending
- FIN only when local server closes connection
- Backpressure: if the data channel can't keep up with the local server, pause reading from the HTTP response (Go channels make this natural)

**Test server (`test_sse.py`):**
```python
from flask import Flask, Response
import time

app = Flask(__name__)

@app.route('/events')
def events():
    def generate():
        for i in range(5):
            yield f"data: event {i}\n\n"
            time.sleep(0.5)
    return Response(generate(), mimetype='text/event-stream')

app.run(port=8080)
```

**Test:**
1. Start SSE server
2. Browser requests `/events`
3. Events appear incrementally (not all at once after 2.5s)

**Success:** Streaming responses work correctly.

---

### Version 0.6: Request Bodies (POST/PUT)

**Goal:** Handle uploads and POST requests.

**Functionality:**
- Receive DAT frames after SYN (request body chunks)
- Stream body to local server
- Handle FIN to complete request
- Backpressure: pause reading if local server is slow

**Test server (`test_upload.py`):**
```python
from flask import Flask, request

app = Flask(__name__)

@app.route('/upload', methods=['POST'])
def upload():
    data = request.get_data()
    return f"Received {len(data)} bytes"

app.run(port=8080)
```

**Test:**
1. Start upload server
2. Browser POSTs 1MB of data
3. Server confirms receipt of 1MB

**Success:** Uploads work correctly.

---

### Version 0.7: Concurrent Requests

**Goal:** Multiple simultaneous requests on same data channel.

**Functionality:**
- Track multiple in-flight streams by streamId
- Interleave response frames correctly
- Independent timeouts per stream

**Test server:**
```python
from flask import Flask
import time

app = Flask(__name__)

@app.route('/fast')
def fast():
    return "fast response"

@app.route('/slow')
def slow():
    time.sleep(1)
    return "slow response"

app.run(port=8080)
```

**Test:**
1. Browser fires both requests concurrently
2. `/fast` returns in ~50ms
3. `/slow` returns in ~1000ms
4. `/fast` doesn't wait for `/slow`

**Success:** Concurrent requests handled independently.

---

## Phase 2: Connection Handshake & Path Support

Requires browser-side changes in bitbang-server repo.

---

### Version 0.8: Connect Handshake with Path

**Goal:** Browser sends path on connection; device acknowledges before proxying begins.

**Note:** Current `bootstrap.js` ignores the URL path after the UID. This version fixes that.

**Browser changes (bitbang-server repo):**
- Extract full path from URL: `/hello/there` from `https://bitba.ng/<uid>/hello/there`
- On data channel open, send `connect` message with path
- Wait for `ready` response before creating iframe
- Load `/__device__<path>` instead of just `/__device__/`

**Proxy functionality:**
- Wait for `connect` message on streamId 0
- For now, always respond with `ready`
- Store path for logging

**SWSP messages:**

Browser → Device:
```json
SYN streamId=0: { "type": "connect", "path": "/hello/there" }
```

Device → Browser:
```json
SYN|FIN streamId=0: { "type": "ready" }
```

**Test:**
1. Start proxy
2. Browser navigates to `https://bitba.ng/<uid>/subdir/page.html`
3. Proxy logs: "Connect: path=/subdir/page.html"
4. Iframe loads `/subdir/page.html`, not `/`

**Success:** URL path is respected.

---

## Phase 3: WebSocket Support

---

### Version 0.9: WebSocket Bridging

**Goal:** Proxy WebSocket connections over the existing data channel using SWSP.

WebSocket connections are multiplexed over the same data channel as HTTP, using
SWSP stream IDs. No additional data channels are created. This is consistent
with how HTTP requests work and avoids the overhead of negotiating new channels.

**Browser changes (bitbang-server repo):**
- Add `ws-shim.js`: monkey-patches `window.WebSocket` in the iframe
- Each `new WebSocket(url)` allocates a SWSP stream ID and sends a SYN frame
- `bootstrap.js` loads shim before iframe

**SWSP framing for WebSocket streams:**

Open (browser -> proxy):
```json
SYN frame: { "type": "websocket", "pathname": "/echo" }
```

Messages (bidirectional):
```
DAT frame payload:
┌──────────────┬─────────────────┐
│ Type (1 byte)│ Message         │
│ 0=text, 1=bin│                 │
└──────────────┴─────────────────┘
```

The type byte distinguishes text vs binary WebSocket messages, since WebSocket
has that distinction and SWSP doesn't.

Close (either direction):
```
FIN frame (no payload, or optional close code/reason)
```

**Proxy functionality:**
- SYN with `"type": "websocket"` opens a WebSocket to `ws://localhost:8080/<pathname>`
- DAT frames are forwarded bidirectionally (proxy <-> local server)
- FIN from either side closes both ends
- Each WebSocket stream has its own stream ID, interleaved with HTTP traffic

**Files:**
```
internal/proxy/websocket.go
```

**Test server (`test_ws.py`):**
```python
from flask import Flask
from flask_sock import Sock

app = Flask(__name__)
sock = Sock(app)

@sock.route('/echo')
def echo(ws):
    while True:
        data = ws.receive()
        ws.send(f"echo: {data}")

app.run(port=8080)
```

**Test:**
1. Start WebSocket echo server
2. Browser connects WebSocket to `/echo`
3. Send "hello", receive "echo: hello"

**Success:** WebSocket messages round-trip correctly.

---

## Phase 4: Dynamic Target Routing

---

### Version 0.10: URL-Based Target

**Goal:** Target specified in URL, not hardcoded.

**URL format:**
```
https://bitba.ng/<proxy-id>/<target>
https://bitba.ng/<proxy-id>/<target>/<path>
```

**Browser changes (bitbang-server repo):**
- `bootstrap.js` detects proxy mode (TBD: how? special UID prefix? signaling flag?)
- Parses URL: extracts `<target>` and `<path>`
- Includes `target` in connect message:
  ```json
  { "type": "connect", "target": "nas.local:8080", "path": "/admin" }
  ```

**Proxy functionality:**
- Extract `target` from connect message
- Store per-connection
- Route all subsequent requests to that target

**Test:**
1. Run two local servers on ports 8080 and 9090
2. Browser → `/<proxy-id>/localhost:8080` → sees server A
3. Browser → `/<proxy-id>/localhost:9090` → sees server B

**Success:** Different URLs reach different local servers.

---

## Phase 5: PIN Protection

---

### Version 0.11: PIN Authentication

**Goal:** Optional PIN protection for proxy access.

**Functionality:**
- `--pin <value>` CLI flag
- Store PIN alongside identity
- On `connect` message, evaluate path against PIN rules
- Send `auth_required` if PIN needed
- Wait for `auth` message with PIN
- Verify PIN, send `auth_result`
- Rate limit failed attempts (3 tries, then 30s backoff)
- Close connection after too many failures

**Browser changes (bitbang-server repo):**
- `bootstrap.js` handles `auth_required` response to connect
- Shows PIN prompt UI (before iframe is created)
- Sends `auth` message with user-entered PIN
- Handles `auth_result` — proceed on success, show error on failure

**SWSP auth flow (all on streamId 0):**

Browser → Device:
```json
SYN: { "type": "connect", "path": "/admin" }
```

Device → Browser:
```json
SYN: { "type": "auth_required" }
```

Browser → Device:
```json
SYN: { "type": "auth", "pin": "1234" }
```

Device → Browser (success):
```json
SYN|FIN: { "type": "auth_result", "success": true }
```

Device → Browser (failure):
```json
SYN|FIN: { "type": "auth_result", "success": false, "message": "Invalid PIN", "remaining": 2 }
```

**Files:**
```
internal/auth/pin.go
```

**Test:**
1. Start proxy: `bitbangproxy --pin 1234`
2. Browser connects, sees PIN prompt
3. Wrong PIN → error message, can retry
4. Correct PIN → proceeds to connection

**Success:** PIN protects access; signaling server never sees PIN.

---

## Phase 6: Production Ready

---

### Version 1.0: Polish

**Functionality:**
- Reconnection on signaling disconnect (exponential backoff)
- Graceful shutdown
- Comprehensive logging
- Timeout handling for all operations
- Error responses for unreachable targets

**Tests:**
- Stress: 50 concurrent connections
- Chaos: kill signaling server mid-transfer, verify reconnection
- Long-running: 24-hour uptime
- Error handling: target refuses connection, target times out

**Success:** Stable under load, recovers from failures.

---

# CLI Interface

```bash
# Start proxy (hardcoded target for v0.1-0.7)
bitbangproxy

# With options
bitbangproxy --target localhost:8080    # Explicit target (pre-v0.10)
bitbangproxy --pin 1234                 # Enable PIN protection
bitbangproxy --ephemeral                # Throwaway identity
bitbangproxy --signaling wss://...      # Custom signaling server
bitbangproxy -v                         # Verbose logging

# Identity management
bitbangproxy identity                   # Show UID and URL
bitbangproxy identity --new             # Generate new identity
```

**Output (without PIN):**
```
BitBangProxy v0.1.0
Identity: a3f8c2e91b4d7f08...
URL: https://bitba.ng/a3f8c2e91b4d7f08

Proxying: localhost:8080
Connected to signaling server.

[12:34:56] Browser connected, path=/
[12:34:56] GET / → 200 (12ms)
[12:34:57] GET /style.css → 200 (8ms)
```

**Output (with PIN):**
```
BitBangProxy v0.1.0
Identity: a3f8c2e91b4d7f08...
URL: https://bitba.ng/a3f8c2e91b4d7f08

PIN protection enabled.

Proxying: localhost:8080
Connected to signaling server.

[12:34:56] Browser connected, path=/admin
[12:34:56] PIN auth failed (1/3)
[12:34:58] PIN auth succeeded
[12:34:58] GET /admin → 200 (12ms)
```

---

# File Structure

```
bitbangproxy/
├── cmd/
│   └── bitbangproxy/
│       └── main.go
├── internal/
│   ├── identity/
│   │   └── identity.go       # RSA keys, PIN storage
│   ├── signaling/
│   │   └── client.go
│   ├── peer/
│   │   └── connection.go
│   ├── proxy/
│   │   ├── http.go
│   │   └── websocket.go
│   ├── auth/
│   │   └── pin.go            # PIN verification, rate limiting
│   └── protocol/
│       ├── swsp.go
│       └── swsp_test.go
├── go.mod
├── go.sum
└── README.md
```

# Dependencies

```go
require (
    github.com/pion/webrtc/v3 v3.2.0
    github.com/gorilla/websocket v1.5.0
    github.com/spf13/cobra v1.8.0
)
```

---

# Summary

| Version | Milestone | Changes Required | Test |
|---------|-----------|------------------|------|
| 0.1 | Identity & signaling | Proxy only | Auth succeeds |
| 0.2 | Peer connection | Proxy only | Data channel opens |
| 0.3 | SWSP frames | Proxy only | Frames round-trip |
| 0.4 | Single HTTP GET | Proxy only | Page loads |
| 0.5 | Streaming responses | Proxy only | SSE works |
| 0.6 | Request bodies | Proxy only | Upload works |
| 0.7 | Concurrent requests | Proxy only | Fast doesn't wait for slow |
| 0.8 | Connect handshake | Proxy + bitbang-server | Path in URL works |
| 0.9 | WebSocket bridging | Proxy + bitbang-server | WS echo works |
| 0.10 | Dynamic target | Proxy + bitbang-server | URL routes to target |
| 0.11 | PIN protection | Proxy + bitbang-server | PIN auth works |
| 1.0 | Production ready | Proxy only | Stress/chaos tests pass |

Phase 1 (v0.1-0.7) requires no changes to bitbang-server and can test against the existing browser runtime with a hardcoded target.