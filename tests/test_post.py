"""Test POST requests with body through the data channel."""

import json


def test_post_echo(device_url, browser_context):
    """POST body arrives at the device and response is returned."""
    page = browser_context.new_page()
    page.goto(device_url, wait_until='networkidle')

    frame = page.frame_locator('#device-frame')
    frame.locator('#heading').wait_for(timeout=30000)

    result = frame.locator('body').evaluate('''() => {
        return fetch("/api/echo", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ hello: "world" })
        }).then(r => r.json());
    }''')

    body = json.loads(result['echo'])
    assert body == {'hello': 'world'}
    assert 'application/json' in result['content_type']

    page.close()


def test_post_form_urlencoded(device_url, browser_context):
    """URL-encoded form POST body arrives correctly."""
    page = browser_context.new_page()
    page.goto(device_url, wait_until='networkidle')

    frame = page.frame_locator('#device-frame')
    frame.locator('#heading').wait_for(timeout=15000)

    result = frame.locator('body').evaluate('''() => {
        return fetch("/api/echo", {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded" },
            body: "operation=read&key=value"
        }).then(r => r.json());
    }''')

    assert result['echo'] == 'operation=read&key=value'

    page.close()
