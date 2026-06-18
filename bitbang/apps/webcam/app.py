import sys

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

    # CLI override of the library-default on_preempted. The library
    # default just logs; for an interactive CLI, the right response is
    # to print a clear line and exit with a distinct code. Library users
    # who embed bitbang in a larger app inherit the polite default.
    @adapter.on_preempted
    def _on_preempt():
        print("BitBang: another instance with the same UID has taken over. Exiting.")
        sys.exit(2)

    adapter.run()


if __name__ == '__main__':
    main()
