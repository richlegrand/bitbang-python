"""Test cookie handling through the SW cookie jar."""

import json
import pytest



def test_login_sets_cookie(device_url, browser_context):
    """POST /login sets a session cookie, subsequent requests include it."""
    page = browser_context.new_page()
    page.goto(device_url, wait_until='networkidle')

    frame = page.frame_locator('#device-frame')
    frame.locator('#heading').wait_for(timeout=15000)

    # POST to /login — should set a cookie
    login_result = frame.locator('body').evaluate('''() => {
        return fetch("/login", { method: "POST" }).then(r => r.json());
    }''')
    assert login_result['status'] == 'ok'

    # Small delay for SW cookie jar to process the Set-Cookie header
    page.wait_for_timeout(200)

    # GET /protected — should include the cookie
    protected_result = frame.locator('body').evaluate('''() => {
        return fetch("/protected").then(r => r.json());
    }''')
    assert protected_result['status'] == 'ok'
    assert protected_result['session'] == 'test-session-123'

    page.close()



def test_logout_clears_cookie(device_url, browser_context):
    """GET /logout clears the session cookie."""
    page = browser_context.new_page()
    page.goto(device_url, wait_until='networkidle')

    frame = page.frame_locator('#device-frame')
    frame.locator('#heading').wait_for(timeout=15000)

    # Login first
    frame.locator('body').evaluate('''() => {
        return fetch("/login", { method: "POST" }).then(r => r.json());
    }''')

    # Logout
    frame.locator('body').evaluate('''() => {
        return fetch("/logout").then(r => r.json());
    }''')

    # Protected should now fail
    protected_result = frame.locator('body').evaluate('''() => {
        return fetch("/protected").then(r => r.json());
    }''')
    assert protected_result['status'] == 'unauthorized'

    page.close()
