# SWSP Cookie and Request Header Support

## Problem

SWSP request frames only carry `method`, `pathname`, `contentType`, and `contentLength`. No request headers are forwarded. This means:

1. Server-set cookies never reach the client on subsequent requests
2. Authorization headers, custom headers, etc. are dropped
3. Any web app that uses sessions/login is broken

Additionally, service worker synthetic responses strip `Set-Cookie` headers (browser security constraint), so the browser's cookie jar is never populated.

## Solution

Two changes:

1. **SWSP request header forwarding** -- add a `headers` field to the SYN frame payload
2. **Device-side cookie jar** -- the adapter/proxy manages cookies per client connection

### SWSP Request Header Forwarding

Current SYN payload:
```json
{ "method": "GET", "pathname": "/dashboard" }
```

New SYN payload:
```json
{ "method": "GET", "pathname": "/dashboard", "headers": { "Accept": "text/html", "X-Custom": "value" } }
```

The `headers` field is a flat object of header name -> value. The SW already captures request headers (`Object.fromEntries(event.request.headers)`). The bootstrap just needs to include them in the SWSP frame.

This is useful beyond cookies -- Authorization, Accept, custom headers all flow through.

### Device-Side Cookie Jar

Each client connection gets its own cookie jar on the device/proxy. The jar intercepts cookies from responses and injects them into subsequent requests. The browser's cookie jar is bypassed entirely.

**Response flow (server -> browser):**
1. App/server includes `Set-Cookie` in response headers
2. Adapter/proxy extracts all `Set-Cookie` headers, stores in per-client jar
3. Response is sent to browser via SWSP (Set-Cookie can be stripped or left -- browser ignores it either way)

**Request flow (browser -> server):**
1. SWSP request arrives with headers (may include browser-set cookies from `document.cookie`)
2. Adapter/proxy merges browser cookies with jar cookies (jar takes precedence for same-name cookies)
3. Combined `Cookie` header is injected into the request
4. App/server sees cookies as normal

### Why Device-Side?

- `Set-Cookie` from SW synthetic responses is stripped by the browser (security constraint)
- `HttpOnly` cookies can't be set via `document.cookie` (JS shim won't work)
- The device-side jar avoids both limitations -- the browser is not involved
- Cookies don't persist across connections (matches WebRTC session lifecycle)

## Changes Required

### bootstrap.js (bitbang-server)

In `handleProxyRequest`, include headers in the SWSP SYN frame:

```javascript
const requestMeta = { method, pathname: fullPath, headers };
if (hasBody) {
    requestMeta.contentLength = contentLength;
    // contentType is already in headers
}
```

Note: `contentType` and `contentLength` become redundant since they're in `headers`, but keep them for backward compatibility with older devices.

### sw.js (bitbang-server)

No changes needed. Already captures and forwards all request headers to the bootstrap.

### Python adapter (bitbang/adapter.py)

**SWSP request parsing:**
- Read `headers` field from SYN payload
- Inject into WSGI environ as `HTTP_*` keys (per WSGI spec)
- Inject into ASGI scope as header tuples

**Cookie jar (per client):**
- Store: after WSGI/ASGI response, extract `Set-Cookie` headers, parse and store in jar
- Inject: before calling app, merge jar cookies into the request's Cookie header
- Storage: simple `{name: value}` dict per client_id (no domain/path scoping needed -- it's all one server)

**Multiple Set-Cookie headers:**
- Current code collapses headers into a dict, losing duplicates
- Fix: collect all Set-Cookie values before collapsing, process each into the jar

### Go proxy (bitbangproxy)

**SWSP request parsing:**
- Read `headers` field from SYN payload
- Forward as HTTP request headers to the local server

**Cookie jar:**
- Use Go's `net/http/cookiejar` per Handler instance
- Use a persistent `http.Client` with the jar (not `http.DefaultClient`)
- Jar handles domain/path scoping, multiple cookies, expiry automatically

**Multiple Set-Cookie headers:**
- Go's `resp.Header["Set-Cookie"]` is already a `[]string`
- The jar processes them via the `http.Client` automatically
- For SWSP response to browser: join or pick first (browser ignores them anyway)

## What This Enables

- Flask/FastAPI/Django session login
- NAS web interfaces via bitbangproxy
- Any app that uses cookies, Authorization headers, or custom headers
- CSRF tokens (which rely on cookies)

## Limitations

- Cookies don't persist across WebRTC connections (page refresh = new session)
- Cookie jar is per-connection, not per-user (no way to identify returning users)
- Browser-side `document.cookie` reads won't see server-set HttpOnly cookies (by design)
