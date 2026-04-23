"""Reverse proxy implementations for BitBang.

ReverseProxyWSGI -- WSGI reverse proxy for use with BitBangWSGI.
ReverseProxyASGI -- ASGI reverse proxy for use with BitBangASGI.

Both forward requests to a local HTTP server and stream responses
back through the BitBang WebRTC tunnel.
"""

import urllib.request
import urllib.error

CHUNK_SIZE = 32768


# -- WSGI reverse proxy ------------------------------------------------------

class ReverseProxyWSGI:
    """WSGI app that proxies requests to a local HTTP server.

    Usage:
        proxy = ReverseProxy("localhost:8080")
        adapter = BitBangWSGI(proxy)
        adapter.run()
    """

    def __init__(self, target="localhost:5000"):
        if not target.startswith("http"):
            target = f"http://{target}"
        self.target = target.rstrip("/")

    def __call__(self, environ, start_response):
        method = environ["REQUEST_METHOD"]
        path = environ.get("PATH_INFO", "/")
        query = environ.get("QUERY_STRING", "")

        url = f"{self.target}{path}"
        if query:
            url += f"?{query}"

        headers = self._build_headers(environ)
        body = self._read_body(environ)

        req = urllib.request.Request(url, data=body, headers=headers, method=method)

        try:
            resp = urllib.request.urlopen(req, timeout=30)
            status = f"{resp.status} {resp.reason}"
            resp_headers = list(resp.getheaders())
            start_response(status, resp_headers)
            return _iter_response(resp)
        except urllib.error.HTTPError as e:
            status = f"{e.code} {e.reason}"
            resp_headers = list(e.headers.items())
            body_bytes = e.read()
            start_response(status, resp_headers)
            return [body_bytes]
        except Exception as e:
            start_response("502 Bad Gateway", [("Content-Type", "text/plain")])
            return [f"Proxy error: {e}".encode()]

    def _build_headers(self, environ):
        headers = {}
        original_host = None
        for key, value in environ.items():
            if key.startswith("HTTP_"):
                name = key[5:].replace("_", "-").title()
                if name.lower() == "host":
                    original_host = value
                    continue
                headers[name] = value
        if environ.get("CONTENT_TYPE"):
            headers["Content-Type"] = environ["CONTENT_TYPE"]

        # Forward proxy headers so the target app generates correct URLs.
        # Host is a forbidden header in browsers so it may not be in the
        # request. Fall back to WSGI SERVER_NAME.
        if not original_host:
            original_host = environ.get("SERVER_NAME")
            port = environ.get("SERVER_PORT", "443")
            if port not in ("443", "80") and original_host:
                original_host += f":{port}"
        if original_host:
            headers["X-Forwarded-Host"] = original_host
            headers["X-Forwarded-Proto"] = environ.get("wsgi.url_scheme", "https")
        return headers

    def _read_body(self, environ):
        content_length = environ.get("CONTENT_LENGTH")
        if content_length and int(content_length) > 0:
            return environ["wsgi.input"].read(int(content_length))
        return None


def _iter_response(resp):
    """Yield response body in chunks."""
    try:
        while True:
            chunk = resp.read(CHUNK_SIZE)
            if not chunk:
                break
            yield chunk
    except Exception:
        pass
    finally:
        resp.close()


# -- ASGI reverse proxy ------------------------------------------------------

class ReverseProxyASGI:
    """ASGI app that proxies requests to a local HTTP server.

    Uses aiohttp for async HTTP. Runs entirely in the event loop --
    no threads, no queue bridging.

    Usage:
        proxy = ReverseProxyASGI("localhost:8080")
        adapter = BitBangASGI(proxy)
        adapter.run()
    """

    def __init__(self, target="localhost:5000"):
        if not target.startswith("http"):
            target = f"http://{target}"
        self.target = target.rstrip("/")
        self._session = None

    async def _get_session(self):
        if self._session is None or self._session.closed:
            import aiohttp
            self._session = aiohttp.ClientSession()
        return self._session

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return

        method = scope["method"]
        path = scope.get("path", "/")
        query = scope.get("query_string", b"").decode()

        url = f"{self.target}{path}"
        if query:
            url += f"?{query}"

        # Build headers from ASGI scope
        headers = {}
        original_host = None
        for k, v in scope.get("headers", []):
            name = k.decode()
            if name.lower() == "host":
                original_host = v.decode()
                continue
            headers[name] = v.decode()

        # Forward proxy headers so the target app generates correct URLs.
        # Host is a forbidden header in browsers so it won't be in the
        # SWSP request. Use the ASGI scope's server tuple instead.
        if not original_host:
            server = scope.get("server")
            if server:
                original_host = server[0]
                if server[1] != 443 and server[1] != 80:
                    original_host += f":{server[1]}"
        if original_host:
            headers["X-Forwarded-Host"] = original_host
            headers["X-Forwarded-Proto"] = scope.get("scheme", "https")

        # Read request body
        body = b""
        while True:
            msg = await receive()
            body += msg.get("body", b"")
            if not msg.get("more_body", False):
                break

        # Forward to target
        session = await self._get_session()
        try:
            async with session.request(
                method, url, headers=headers, data=body or None,
                timeout=__import__('aiohttp').ClientTimeout(total=30)
            ) as resp:
                # Send response start
                resp_headers = []
                for k, v in resp.headers.items():
                    resp_headers.append((k.lower().encode(), v.encode()))

                await send({
                    "type": "http.response.start",
                    "status": resp.status,
                    "headers": resp_headers,
                })

                # Stream response body
                async for chunk in resp.content.iter_chunked(CHUNK_SIZE):
                    await send({
                        "type": "http.response.body",
                        "body": chunk,
                        "more_body": True,
                    })

                await send({
                    "type": "http.response.body",
                    "body": b"",
                    "more_body": False,
                })

        except Exception as e:
            await send({
                "type": "http.response.start",
                "status": 502,
                "headers": [(b"content-type", b"text/plain")],
            })
            await send({
                "type": "http.response.body",
                "body": f"Proxy error: {e}".encode(),
                "more_body": False,
            })
