"""Same as app.py but runs as a normal Flask server on localhost:8080.
Use this with bitbangproxy to test proxying a local web server."""

from flask import Flask, render_template, send_file

app = Flask(__name__, template_folder=".", static_folder="static")

@app.route('/favicon.ico')
def favicon():
    return send_file('static/favicon.png', mimetype='image/png')

@app.route('/')
def index():
    return render_template('index.html')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
