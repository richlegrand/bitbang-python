"""Test app with WebSocket echo endpoint.

The Flask app serves the HTML page. A separate websockets server
handles the WebSocket echo on a different port. The BitBang adapter's
ws_target bridges them together.
"""

import asyncio
import threading
import websockets
from flask import Flask, Response

app = Flask(__name__)

# Port for the standalone WebSocket echo server
WS_PORT = 18765


@app.route('/')
def index():
    return '''<!DOCTYPE html>
<html>
<head><title>WebSocket Test</title></head>
<body>
<h1 id="heading">WebSocket Echo Test</h1>
<div id="result"></div>
<script>
function runTest() {
    return new Promise(function(resolve, reject) {
        var ws = new WebSocket('ws://' + location.host + '/echo');
        var received = [];

        ws.onopen = function() {
            ws.send('hello');
            ws.send('world');
            ws.send('bitbang');
        };

        ws.onmessage = function(e) {
            received.push(e.data);
            if (received.length >= 3) {
                ws.close();
                document.getElementById('result').textContent = received.join(',');
                resolve(received);
            }
        };

        ws.onerror = function() {
            reject('WebSocket error');
        };

        setTimeout(function() {
            ws.close();
            resolve(received);
        }, 10000);
    });
}
</script>
</body>
</html>'''


async def ws_echo_handler(websocket):
    """Echo messages back with 'echo:' prefix."""
    async for message in websocket:
        await websocket.send(f"echo:{message}")


def start_ws_echo_server():
    """Run the WebSocket echo server in a background thread."""
    loop = asyncio.new_event_loop()

    async def serve():
        async with websockets.serve(ws_echo_handler, "localhost", WS_PORT):
            await asyncio.Future()  # run forever

    def run():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(serve())

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t
