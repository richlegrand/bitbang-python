"""Pytest fixtures for BitBang E2E tests.

Starts BitBang devices (test Flask apps) connected to test.bitba.ng,
provides their URLs to tests, and tears them down after the session.
"""

import pytest
import subprocess
import threading
import time
import sys
import os
import re

TEST_SERVER = os.environ.get('BITBANG_TEST_SERVER', 'test.bitba.ng')

collect_ignore = ['test_app_runner.py', 'test_app.py', 'test_pin_app_runner.py',
                  'test_ws_app_runner.py', 'test_ws_app.py']
DEVICE_STARTUP_TIMEOUT = 30  # seconds to wait for device to register
                             # (RSA-2048 keygen + TLS handshake + register can
                             # take >15s on slow CI runners)


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

    # Keep every line we read so we can include it in the failure message
    # — readline() consumes from the pipe, so proc.stdout.read() after a
    # kill returns only whatever was unread, which is usually nothing.
    captured = []
    url = None
    deadline = time.time() + DEVICE_STARTUP_TIMEOUT
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            continue
        captured.append(line)
        print(f'[device] {line.rstrip()}')
        match = re.search(r'Ready: (https://\S+)', line)
        if match:
            url = match.group(1)
            break

    if url is None:
        proc.kill()
        try:
            captured.append(proc.stdout.read())
        except Exception:
            pass
        full = ''.join(captured) or '(no output captured)'
        exit_code = proc.poll()
        raise RuntimeError(
            f'Device failed to start after {DEVICE_STARTUP_TIMEOUT}s '
            f'(exit={exit_code}, server={TEST_SERVER}). Output:\n{full}'
        )

    print(f'[device] URL: {url}')

    # TEMP-DEBUG (test_pin_callback_protected_path diagnosis): after
    # startup, spawn a background thread that drains the subprocess pipe
    # and echoes each line to the parent's stdout. Without this the pipe
    # buffer fills up (or debug prints simply never appear in pytest's
    # captured output), and post-startup device logs are invisible in
    # CI failure output. Remove once the underlying bug is identified.
    def _drain():
        try:
            for line in proc.stdout:
                print(f'[device] {line.rstrip()}', flush=True)
        except Exception:
            pass
    threading.Thread(target=_drain, daemon=True).start()

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
