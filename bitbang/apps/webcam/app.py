try:
    from .webcam_adapter import WebcamBitBang
except ImportError:
    from webcam_adapter import WebcamBitBang
from flask import Flask, render_template, send_file


app = Flask(__name__, template_folder=".")

@app.route('/favicon.ico')
def favicon():
    return send_file('static/favicon.png', mimetype='image/png')


@app.route('/')
def index():
    return render_template('index.html')


def main():
    import argparse
    from bitbang.adapter import add_bitbang_args, bitbang_kwargs

    parser = argparse.ArgumentParser(description='Stream webcam via BitBang')
    add_bitbang_args(parser)
    args = parser.parse_args()

    adapter = WebcamBitBang(app, **bitbang_kwargs(args, program_name='webcam'))
    adapter.run()


if __name__ == '__main__':
    main()
