"""Pytest fixtures for BitBang E2E tests.

Starts BitBang devices (test Flask apps) connected to test.bitba.ng,
provides their URLs to tests, and tears them down after the session.
"""

import pytest
import subprocess
import time
import sys
import os
import re

TEST_SERVER = os.environ.get('BITBANG_TEST_SERVER', 'test.bitba.ng')

collect_ignore = ['test_app_runner.py', 'test_app.py', 'test_pin_app_runner.py',
                  'test_ws_app_runner.py', 'test_ws_app.py']
DEVICE_STARTUP_TIMEOUT = 15  # seconds to wait for device to register


def _start_device(script, *extra_args):
    """Start a BitBang device subprocess and return (process, url)."""
    tests_dir = os.path.dirname(__file__)
    repo_dir = os.path.dirname(tests_dir)

    proc = subprocess.Popen(
        [sys.executable, '-u', os.path.join(tests_dir, script),
         '--server', TEST_SERVER, *extra_args],
        cwd=repo_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    url = None
    deadline = time.time() + DEVICE_STARTUP_TIMEOUT
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            continue
        print(f'[device] {line.rstrip()}')
        match = re.search(r'Ready: (https://\S+)', line)
        if match:
            url = match.group(1)
            break

    if url is None:
        proc.kill()
        output = proc.stdout.read()
        raise RuntimeError(f'Device failed to start. Output:\n{output}')

    print(f'[device] URL: {url}')
    return proc, url


def _stop_device(proc):
    """Stop a device subprocess."""
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope='session')
def device_url():
    """Start a BitBang test device (no PIN) and return its URL."""
    proc, url = _start_device('test_app_runner.py')
    yield url
    _stop_device(proc)


@pytest.fixture(scope='session')
def pin_device_url():
    """Start a BitBang test device with simple PIN '1234' and return its URL."""
    proc, url = _start_device('test_pin_app_runner.py', '--mode', 'simple')
    yield url
    _stop_device(proc)


@pytest.fixture(scope='session')
def pin_callback_device_url():
    """Start a BitBang test device with PIN callback and return its URL."""
    proc, url = _start_device('test_pin_app_runner.py', '--mode', 'callback')
    yield url
    _stop_device(proc)


@pytest.fixture(scope='session')
def ws_device_url():
    """Start a BitBang test device with WebSocket echo and return its URL."""
    proc, url = _start_device('test_ws_app_runner.py')
    yield url
    _stop_device(proc)


@pytest.fixture(scope='session')
def browser_context(playwright, device_url):
    """Create a persistent browser context for the test session."""
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    yield context
    context.close()
    browser.close()
