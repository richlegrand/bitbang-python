"""Same as app.py but runs as a normal Flask server on localhost:8080.
Use this with bitbangproxy to test proxying SSE streaming."""

from flask import Flask, Response, render_template
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
    app.run(host='0.0.0.0', port=8080)
