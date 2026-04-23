"""Concurrent request test server on localhost:8080.
Use with bitbangproxy to verify /fast doesn't wait for /slow."""

from flask import Flask
import time

app = Flask(__name__)

@app.route('/')
def index():
    return '''<!DOCTYPE html>
<html><body>
<h1>Concurrent Request Test</h1>
<div id="results"></div>
<script>
async function test() {
    const el = document.getElementById('results');
    el.innerHTML = 'Testing...';

    const t0 = Date.now();

    // Fire both requests concurrently
    const [fast, slow] = await Promise.all([
        fetch('fast').then(r => r.text()),
        fetch('slow').then(r => r.text()),
    ]);

    const elapsed = Date.now() - t0;
    el.innerHTML = `
        <p>Fast: ${fast}</p>
        <p>Slow: ${slow}</p>
        <p>Total time: ${elapsed}ms</p>
        <p>${elapsed < 1500 ? 'PASS - requests were concurrent' : 'FAIL - requests were serialized'}</p>
    `;
}
test();
</script>
</body></html>'''

@app.route('/fast')
def fast():
    return "fast response"

@app.route('/slow')
def slow():
    time.sleep(1)
    return "slow response"


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, threaded=True)
