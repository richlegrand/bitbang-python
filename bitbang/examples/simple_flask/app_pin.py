"""Test simple PIN protection. PIN is '1234'."""

from bitbang import BitBangWSGI
from flask import Flask, render_template, send_file

app = Flask(__name__, template_folder=".", static_folder="static")

@app.route('/favicon.ico')
def favicon():
    return send_file('static/favicon.png', mimetype='image/png')

@app.route('/')
def index():
    return render_template('index.html')


if __name__ == '__main__':
    adapter = BitBangWSGI(app, program_name='pin_test', pin='1234')
    adapter.run()
