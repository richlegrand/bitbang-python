"""Standalone script to run the test Flask app with PIN protection.
Launched by conftest.py as a subprocess."""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from tests.test_app import app
from bitbang import BitBangWSGI

def check_pin(path, pin):
    """/ is open, /admin requires PIN '9999', everything else requires '1234'."""
    if path == '/':
        return True
    if path.startswith('/admin'):
        return pin == '9999'
    return pin == '1234'

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--server', default='test.bitba.ng')
    parser.add_argument('--mode', choices=['simple', 'callback'], default='simple')
    args = parser.parse_args()

    if args.mode == 'callback':
        adapter = BitBangWSGI(app, server=args.server, ephemeral=True,
                              program_name='test_pin_cb', pin_callback=check_pin)
    else:
        adapter = BitBangWSGI(app, server=args.server, ephemeral=True,
                              program_name='test_pin', pin='1234')
    adapter.run()
