"""Standalone script to run the test Flask app as a BitBang device.
Launched by conftest.py as a subprocess."""

import argparse
import sys
import os

# Ensure the repo root is on the path so bitbang can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from tests.test_app import app
from bitbang import BitBangWSGI

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--server', default='test.bitba.ng')
    args = parser.parse_args()

    adapter = BitBangWSGI(app, server=args.server, ephemeral=True, program_name='test')
    adapter.run()
