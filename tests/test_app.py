"""Minimal Flask app used by tests. Exercises the core features:
page load, static assets, cookies, POST forms, and SSE streaming."""

from flask import Flask, request, make_response, Response
import json
import time

app = Flask(__name__)

@app.route('/')
def index():
    return '''<!DOCTYPE html>
<html>
<head><title>BitBang Test</title>
<link rel="stylesheet" href="/style.css">
<script src="/app.js"></script>
</head>
<body>
<h1 id="heading">Hello from BitBang</h1>
<div id="cookie-value"></div>
</body>
</html>'''

@app.route('/style.css')
def style():
    return Response('body { background: white; }', mimetype='text/css')

@app.route('/app.js')
def script():
    return Response('document.addEventListener("DOMContentLoaded", function() { '
                    'document.getElementById("heading").dataset.loaded = "true"; });',
                    mimetype='application/javascript')

@app.route('/api/echo', methods=['POST'])
def echo():
    """Echo the POST body back as JSON."""
    data = request.get_data(as_text=True)
    return json.dumps({'echo': data, 'content_type': request.content_type})

@app.route('/api/headers')
def headers():
    """Return selected request headers as JSON."""
    return json.dumps({
        'host': request.headers.get('Host', ''),
        'referer': request.headers.get('Referer', ''),
    })

@app.route('/login', methods=['POST'])
def login():
    resp = make_response(json.dumps({'status': 'ok'}))
    resp.set_cookie('session', 'test-session-123', path='/')
    return resp

@app.route('/logout')
def logout():
    resp = make_response(json.dumps({'status': 'logged_out'}))
    resp.delete_cookie('session', path='/')
    return resp

@app.route('/protected')
def protected():
    session = request.cookies.get('session')
    if session:
        return json.dumps({'status': 'ok', 'session': session})
    return json.dumps({'status': 'unauthorized'}), 401

@app.route('/sse')
def sse():
    def generate():
        for i in range(3):
            yield f'data: message {i}\n\n'
            time.sleep(0.1)
    return Response(generate(), mimetype='text/event-stream')

@app.route('/download')
def download():
    """Serve a test file for download (100KB of repeated bytes)."""
    data = b'BitBang test data. ' * 5263  # ~100KB
    return Response(data, mimetype='application/octet-stream',
                    headers={'Content-Length': str(len(data)),
                             'Content-Disposition': 'attachment; filename="test.bin"'})

@app.route('/upload', methods=['POST'])
def upload():
    """Accept a file upload and return its size."""
    data = request.get_data()
    return json.dumps({'size': len(data), 'content_type': request.content_type})
