"""Simple upload test server on localhost:8080.
Use with bitbangproxy to test POST/PUT request body proxying."""

from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/')
def index():
    return '''<!DOCTYPE html>
<html><body>
<h1>Upload Test</h1>
<form action="upload" method="POST" enctype="multipart/form-data">
    <input type="file" name="file">
    <button type="submit">Upload</button>
</form>
</body></html>'''

@app.route('/upload', methods=['POST'])
def upload():
    data = request.get_data()
    return f"Received {len(data)} bytes"


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
