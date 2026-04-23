"""Standalone script to run the WebSocket test app as a BitBang device.
Launched by conftest.py as a subprocess."""

import argparse
import sys
import os

# Ensure the repo root is on the path so bitbang can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from tests.test_ws_app import app, start_ws_echo_server, WS_PORT
from bitbang import BitBangWSGI

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--server', default='test.bitba.ng')
    args = parser.parse_args()

    # Start the WebSocket echo server on a separate port
    start_ws_echo_server()
    print(f"WebSocket echo server running on localhost:{WS_PORT}")

    # Start BitBang with ws_target pointing at the echo server
    adapter = BitBangWSGI(app, server=args.server, ephemeral=True, program_name='test-ws')
    adapter.ws_target = f"localhost:{WS_PORT}"
    adapter.run()
