# BitBang Cookie Handling Specification

## Overview

BitBang proxies HTTP through WebRTC data channels. Because responses are constructed by the service worker (not received from a real HTTP connection), the browser's native cookie handling doesn't apply. `Set-Cookie` is a forbidden response header and cannot be processed from constructed Response objects.

This specification describes a browser-side cookie jar implementation that handles cookies transparently, making proxied applications with login/session functionality work correctly.

## Architecture

```
Local Server                    BitBangProxy/Device              Browser
     │                                  │                           │
     │◀─── HTTP request ────────────────│◀─── SWSP request ─────────│
     │     (with Cookie header          │     (with cookie header   │
     │      injected by proxy)          │      from cookie jar)     │
     │                                  │                           │
     │─── HTTP response ───────────────▶│─── SWSP response ────────▶│
     │    (with Set-Cookie)             │    (Set-Cookie in headers)│
     │                                  │                           │
     │                                  │     Cookie jar updated    │
     │                                  │     in sw.js/bootstrap.js │
```

## Cookie Jar Location

The cookie jar lives in the **service worker** (`sw.js`). This ensures:
- All requests pass through (already intercepted)
- All responses pass through (already constructed here)
- Persistence across iframe reloads (service worker lifetime)
- Shared across all requests in the session

## Data Structures

### Cookie Object

```javascript
/**
 * @typedef {Object} Cookie
 * @property {string} name - Cookie name
 * @property {string} value - Cookie value
 * @property {string} path - Path scope (default: "/")
 * @property {number|null} expires - Expiration timestamp (ms since epoch), null = session
 * @property {boolean} secure - Secure flag (we ignore this since DTLS is always secure)
 * @property {boolean} httpOnly - HttpOnly flag (we ignore this, no real DOM access)
 */
```

### Cookie Jar

```javascript
/**
 * Cookie jar keyed by uid:target
 * 
 * Keying by uid:target (not just target) prevents cross-device leakage.
 * Service workers are shared across all tabs on the same origin (bitba.ng).
 * Without uid in the key, two tabs connecting to different devices that 
 * happen to use the same private IP (e.g., 192.168.1.50) would share cookies.
 * 
 * @type {Map<string, Cookie[]>}
 */
const cookieJar = new Map();

/**
 * Generate cookie jar key
 * @param {string} uid - Device UID
 * @param {string} target - Target host:port
 * @returns {string}
 */
function getCookieKey(uid, target) {
    return `${uid}:${target}`;
}
```

## Parsing Set-Cookie Headers

### Input Format

SWSP response headers are JSON. `Set-Cookie` may be:
- A single string: `"session=abc; Path=/; Max-Age=3600"`
- An array of strings: `["session=abc; Path=/", "csrf=xyz; Path=/api"]`

### Parser Implementation

```javascript
/**
 * Parse a Set-Cookie header string into a Cookie object
 * @param {string} setCookieString - e.g., "session=abc; Path=/admin; Max-Age=3600"
 * @returns {Cookie}
 */
function parseSetCookie(setCookieString) {
    const parts = setCookieString.split(';').map(p => p.trim());
    
    // First part is always name=value
    const [nameValue, ...attributes] = parts;
    const eqIndex = nameValue.indexOf('=');
    const name = nameValue.substring(0, eqIndex);
    const value = nameValue.substring(eqIndex + 1);
    
    // Defaults
    const cookie = {
        name,
        value,
        path: '/',
        expires: null,  // null = session cookie
        secure: false,
        httpOnly: false
    };
    
    // Parse attributes
    for (const attr of attributes) {
        const [attrName, attrValue] = attr.split('=').map(s => s.trim());
        const attrLower = attrName.toLowerCase();
        
        if (attrLower === 'path') {
            cookie.path = attrValue || '/';
        } else if (attrLower === 'max-age') {
            const seconds = parseInt(attrValue, 10);
            if (!isNaN(seconds)) {
                cookie.expires = Date.now() + (seconds * 1000);
            }
        } else if (attrLower === 'expires') {
            const date = new Date(attrValue);
            if (!isNaN(date.getTime())) {
                // Only use Expires if Max-Age wasn't set
                if (cookie.expires === null) {
                    cookie.expires = date.getTime();
                }
            }
        } else if (attrLower === 'secure') {
            cookie.secure = true;
        } else if (attrLower === 'httponly') {
            cookie.httpOnly = true;
        }
        // Ignore: Domain (we key by target anyway), SameSite (not applicable)
    }
    
    return cookie;
}

/**
 * Parse Set-Cookie header(s) from SWSP response
 * @param {string|string[]} header - Set-Cookie header value(s)
 * @returns {Cookie[]}
 */
function parseSetCookieHeader(header) {
    if (!header) return [];
    
    const headers = Array.isArray(header) ? header : [header];
    return headers.map(parseSetCookie);
}
```

## Storing Cookies

```javascript
/**
 * Store cookies in the jar
 * @param {string} uid - Device UID
 * @param {string} target - Target host:port (e.g., "nas.local:8080")
 * @param {Cookie[]} cookies - Cookies to store
 */
function storeCookies(uid, target, cookies) {
    const key = getCookieKey(uid, target);
    if (!cookieJar.has(key)) {
        cookieJar.set(key, []);
    }
    
    const jar = cookieJar.get(key);
    
    for (const cookie of cookies) {
        // Remove existing cookie with same name and path
        const existingIndex = jar.findIndex(
            c => c.name === cookie.name && c.path === cookie.path
        );
        
        if (existingIndex !== -1) {
            jar.splice(existingIndex, 1);
        }
        
        // Empty value = delete cookie
        if (cookie.value === '' || cookie.value === '""') {
            continue;
        }
        
        // Expired cookie = don't store
        if (cookie.expires !== null && cookie.expires <= Date.now()) {
            continue;
        }
        
        jar.push(cookie);
    }
}
```

## Retrieving Cookies for Request

```javascript
/**
 * Check if a cookie should be sent for a given path
 * @param {Cookie} cookie
 * @param {string} requestPath - e.g., "/admin/settings"
 * @returns {boolean}
 */
function cookieMatchesPath(cookie, requestPath) {
    // Path must be a prefix
    if (!requestPath.startsWith(cookie.path)) {
        return false;
    }
    
    // If cookie path doesn't end with /, request path must either:
    // - Equal cookie path exactly, or
    // - Have / after the cookie path
    if (!cookie.path.endsWith('/')) {
        const remainder = requestPath.substring(cookie.path.length);
        if (remainder !== '' && !remainder.startsWith('/')) {
            return false;
        }
    }
    
    return true;
}

/**
 * Check if a cookie has expired
 * @param {Cookie} cookie
 * @returns {boolean}
 */
function isExpired(cookie) {
    return cookie.expires !== null && cookie.expires <= Date.now();
}

/**
 * Get Cookie header value for a request
 * @param {string} uid - Device UID
 * @param {string} target - Target host:port
 * @param {string} requestPath - Request path
 * @returns {string|null} - Cookie header value, or null if no cookies
 */
function getCookieHeader(uid, target, requestPath) {
    const key = getCookieKey(uid, target);
    const jar = cookieJar.get(key);
    if (!jar || jar.length === 0) {
        return null;
    }
    
    // Filter to matching, non-expired cookies
    const validCookies = jar.filter(cookie => 
        !isExpired(cookie) && cookieMatchesPath(cookie, requestPath)
    );
    
    // Clean up expired cookies while we're here
    const expired = jar.filter(isExpired);
    for (const cookie of expired) {
        const index = jar.indexOf(cookie);
        if (index !== -1) jar.splice(index, 1);
    }
    
    if (validCookies.length === 0) {
        return null;
    }
    
    // Sort by path length descending (more specific paths first)
    validCookies.sort((a, b) => b.path.length - a.path.length);
    
    // Serialize
    return validCookies.map(c => `${c.name}=${c.value}`).join('; ');
}
```

## Integration with SWSP

### On Sending Request (Service Worker)

```javascript
// In sw.js, when constructing SWSP request

function buildSWSPRequest(method, pathname, headers, uid, target) {
    // Inject Cookie header if we have cookies for this device/target
    const cookieHeader = getCookieHeader(uid, target, pathname);
    if (cookieHeader) {
        headers['cookie'] = cookieHeader;
    }
    
    return {
        method,
        pathname,
        headers,
        // ... other fields
    };
}
```

### On Receiving Response (Service Worker)

```javascript
// In sw.js, when processing SWSP response headers

function processSWSPResponse(metadata, uid, target) {
    const { status, headers } = metadata;
    
    // Extract and store cookies
    const setCookie = headers['set-cookie'] || headers['Set-Cookie'];
    if (setCookie) {
        const cookies = parseSetCookieHeader(setCookie);
        storeCookies(uid, target, cookies);
        
        // Remove Set-Cookie from headers before constructing Response
        // (forbidden header, and we've already processed it)
        delete headers['set-cookie'];
        delete headers['Set-Cookie'];
    }
    
    // Construct Response...
}
```

## UID and Target Determination

The cookie jar is keyed by `uid:target`. The service worker needs both values for each request.

### Initialization

When connection is established, bootstrap.js extracts uid and target from URL and passes to service worker:

```javascript
// In bootstrap.js
const url = new URL(window.location);
const pathParts = url.pathname.split('/').filter(Boolean);
const uid = pathParts[0];
const target = pathParts[1] || 'localhost:8080';  // Default for non-proxy devices

// Pass to service worker via MessageChannel or store in SW-accessible location
navigator.serviceWorker.controller.postMessage({
    type: 'setContext',
    uid: uid,
    target: target
});
```

### In Service Worker

```javascript
// In sw.js
let currentUid = null;
let currentTarget = null;

self.addEventListener('message', (event) => {
    if (event.data.type === 'setContext') {
        currentUid = event.data.uid;
        currentTarget = event.data.target;
    }
});
```

### For BitBangProxy (Dynamic Target)

Target is extracted from URL path:
```
https://bitba.ng/<uid>/<target>/<path>
```

### For Python BitBang (Fixed Target)

Target is always `localhost:<port>` or just use a fixed key like `"device"`.

## Edge Cases

### Multiple Cookies with Same Name, Different Paths

```
Set-Cookie: token=admin; Path=/admin
Set-Cookie: token=user; Path=/
```

Both are stored separately. Request to `/admin/dashboard` sends `token=admin` (more specific path wins via sorting).

### Cookie Deletion

```
Set-Cookie: session=; Max-Age=0
Set-Cookie: session=deleted; Expires=Thu, 01 Jan 1970 00:00:00 GMT
```

Empty value or past expiration = remove from jar.

### Very Long Cookie Values

Some apps use large JWT tokens. No special handling needed — just pass through.

### Unicode in Cookie Values

Cookie values should be URL-encoded by the server. Pass through as-is.

## Security Considerations

### Cross-Device Isolation

Cookies are keyed by `uid:target`. This prevents leakage between devices:

| Tab 1 | Tab 2 | Cookies Shared? |
|-------|-------|-----------------|
| `uid-alice/192.168.1.50:8080` | `uid-bob/192.168.1.50:8080` | No (different uid) |
| `uid-alice/nas.local:80` | `uid-alice/printer.local:80` | No (different target) |
| `uid-alice/nas.local:80` | `uid-alice/nas.local:80` | Yes (same uid:target) |

### Cross-Tab Behavior (Same Device)

Multiple tabs connecting to the same `uid:target` share cookies. This is correct — it matches normal browser behavior where multiple tabs to the same website share cookies. Login in one tab works in the other.

### No Cross-Target Leakage

Even within the same uid, cookies are strictly scoped. `nas.local:8080` cookies never sent to `printer.local:80`.

### Session Lifetime

Cookies persist for the service worker's lifetime (until browser tab closes or worker terminates). This matches typical session cookie behavior.

### No Real HttpOnly/Secure

These flags don't apply in our context:
- HttpOnly: No real DOM to protect from (iframe is proxied)
- Secure: DTLS provides encryption regardless

We parse them but don't enforce — they're meaningful for the local server's actual HTTP responses, not our tunnel.

## Testing

### Test Cases

1. **Basic session cookie:**
   - Server sends `Set-Cookie: session=abc123`
   - Subsequent requests include `Cookie: session=abc123`

2. **Path-scoped cookie:**
   - Server sends `Set-Cookie: admin=true; Path=/admin`
   - Request to `/admin/users` includes cookie
   - Request to `/public` does NOT include cookie

3. **Expiring cookie:**
   - Server sends `Set-Cookie: temp=xyz; Max-Age=2`
   - Immediate request includes cookie
   - Request after 3 seconds does NOT include cookie

4. **Cookie update:**
   - Server sends `Set-Cookie: token=old`
   - Server sends `Set-Cookie: token=new`
   - Request sends `Cookie: token=new`

5. **Cookie deletion:**
   - Server sends `Set-Cookie: session=abc`
   - Server sends `Set-Cookie: session=; Max-Age=0`
   - Request does NOT include cookie

6. **Multiple cookies:**
   - Server sends `Set-Cookie: a=1` and `Set-Cookie: b=2`
   - Request sends `Cookie: a=1; b=2`

### Test Server

```python
from flask import Flask, request, make_response

app = Flask(__name__)

@app.route('/login', methods=['POST'])
def login():
    resp = make_response('Logged in')
    resp.set_cookie('session', 'abc123')
    resp.set_cookie('user', 'alice')
    return resp

@app.route('/admin')
def admin():
    session = request.cookies.get('session')
    if session == 'abc123':
        return f'Welcome, session={session}'
    return 'Unauthorized', 401

@app.route('/logout', methods=['POST'])
def logout():
    resp = make_response('Logged out')
    resp.set_cookie('session', '', max_age=0)
    return resp

app.run(port=8080)
```

## Implementation Checklist

- [ ] Add `getCookieKey()` function to sw.js
- [ ] Add `parseSetCookie()` function to sw.js
- [ ] Add `parseSetCookieHeader()` function to sw.js
- [ ] Add `cookieJar` Map to sw.js
- [ ] Add `storeCookies()` function to sw.js
- [ ] Add `getCookieHeader()` function to sw.js
- [ ] Add uid/target context tracking in sw.js
- [ ] Add `setContext` message handler in sw.js
- [ ] Modify bootstrap.js to send uid/target to sw.js on connection
- [ ] Modify SWSP request building to inject Cookie header
- [ ] Modify SWSP response processing to extract and store Set-Cookie
- [ ] Test with Flask session app
- [ ] Test path scoping
- [ ] Test expiration
- [ ] Test cross-device isolation (two tabs, different uids, same target IP)
