"""WebSocket echo test server on localhost:8080.
Use with bitbangproxy to test WebSocket bridging."""

from flask import Flask
from flask_sock import Sock

app = Flask(__name__)
sock = Sock(app)

@app.route('/')
def index():
    return '''<!DOCTYPE html>
<html><body>
<h1>WebSocket Echo Test</h1>
<div>
    <input type="text" id="msg" value="hello" style="width:200px">
    <button onclick="send()">Send</button>
</div>
<div id="log" style="margin-top:1em; font-family:monospace; white-space:pre"></div>
<script>
const log = document.getElementById('log');
function addLog(text) {
    log.textContent += text + '\\n';
}

let ws;
function connect() {
    addLog('Connecting...');
    ws = new WebSocket('echo');
    ws.onopen = () => addLog('Connected');
    ws.onmessage = (e) => addLog('Received: ' + e.data);
    ws.onclose = () => addLog('Disconnected');
    ws.onerror = () => addLog('Error');
}

function send() {
    const msg = document.getElementById('msg').value;
    addLog('Sent: ' + msg);
    ws.send(msg);
}

connect();
</script>
</body></html>'''

@sock.route('/echo')
def echo(ws):
    while True:
        data = ws.receive()
        ws.send(f"echo: {data}")


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
