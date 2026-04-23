"""Test PIN callback with per-path protection.

The PIN is checked via the connect handshake on stream 0. Protected links
send a 'bb-navigate' message to the bootstrap, which re-runs the connect
flow for the new path without dropping the WebRTC connection.

Entry points:
  /            -> no PIN required
  /admin       -> PIN '9999' required
  /settings    -> PIN '1234' required
"""

from bitbang import BitBangWSGI
from flask import Flask, send_file

app = Flask(__name__, static_folder="static")

@app.route('/favicon.ico')
def favicon():
    return send_file('static/favicon.png', mimetype='image/png')

@app.route('/')
def index():
    return '''<!DOCTYPE html>
<html><body style="font-family: sans-serif; max-width: 500px; margin: 40px auto;">
<h1>PIN Callback Test</h1>
<p>This page was accessed without a PIN.</p>
<h3>Protected pages:</h3>
<ul>
    <li><a href="#" onclick="navigate('/admin')">Admin</a> (PIN: 9999)</li>
    <li><a href="#" onclick="navigate('/settings')">Settings</a> (PIN: 1234)</li>
</ul>
<script>
function navigate(path) {
    window.parent.postMessage({ type: 'bb-navigate', path }, '*');
}
</script>
</body></html>'''

@app.route('/admin')
def admin():
    return '''<!DOCTYPE html>
<html><body style="font-family: sans-serif; max-width: 500px; margin: 40px auto;">
<h1>Admin</h1>
<p>You authenticated with the admin PIN (9999).</p>
<p><a href="#" onclick="window.parent.postMessage({type:'bb-navigate',path:'/'},'*')">Home</a></p>
</body></html>'''

@app.route('/settings')
def settings():
    return '''<!DOCTYPE html>
<html><body style="font-family: sans-serif; max-width: 500px; margin: 40px auto;">
<h1>Settings</h1>
<p>You authenticated with the settings PIN (1234).</p>
<p><a href="#" onclick="window.parent.postMessage({type:'bb-navigate',path:'/'},'*')">Home</a></p>
</body></html>'''


def check_pin(path, pin):
    """Per-path PIN logic. Called on each connect/navigate."""
    if path == '/' or path.startswith('/public'):
        return True
    if path.startswith('/admin'):
        return pin == '9999'
    return pin == '1234'


if __name__ == '__main__':
    adapter = BitBangWSGI(app, program_name='pin_callback_test', pin_callback=check_pin)
    adapter.run()
