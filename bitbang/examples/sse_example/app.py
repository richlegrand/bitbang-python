"""SSE (Server-Sent Events) example for BitBang.

Tests that streaming HTTP responses work correctly over the WebRTC data channel.
The server pushes a timestamp event every second; the browser displays them live.
"""

from bitbang import BitBangWSGI
from flask import Flask, render_template, Response
import time


app = Flask(__name__, template_folder=".")


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/events')
def events():
    def generate():
        count = 0
        while True:
            count += 1
            ts = time.strftime('%H:%M:%S')
            yield f"data: #{count} at {ts}\n\n"
            time.sleep(1)

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache'})


if __name__ == '__main__':
    adapter = BitBangWSGI(app, program_name='sse_example')
    adapter.run()
