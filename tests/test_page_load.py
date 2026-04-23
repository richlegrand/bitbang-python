"""Test basic page load through WebRTC data channel."""

import pytest


def test_page_loads(device_url, browser_context):
    """Device serves HTML through WebRTC — page title and heading visible."""
    page = browser_context.new_page()
    page.goto(device_url, wait_until='networkidle')

    # Wait for the iframe to load the device content
    # The bootstrap creates an iframe with id="device-frame"
    frame = page.frame_locator('#device-frame')
    heading = frame.locator('#heading')
    heading.wait_for(timeout=15000)

    assert heading.text_content() == 'Hello from BitBang'
    page.close()


def test_page_title(device_url, browser_context):
    """Page title propagates from device to browser tab."""
    page = browser_context.new_page()
    page.goto(device_url, wait_until='networkidle')

    frame = page.frame_locator('#device-frame')
    frame.locator('#heading').wait_for(timeout=15000)

    # Bootstrap copies iframe title to document.title
    assert 'BitBang Test' in page.title()
    page.close()


def test_static_css_loads(device_url, browser_context):
    """CSS file loads through the data channel."""
    page = browser_context.new_page()
    page.goto(device_url, wait_until='networkidle')

    frame = page.frame_locator('#device-frame')
    frame.locator('#heading').wait_for(timeout=15000)

    # Verify the CSS was applied (background should be white from style.css)
    bg = frame.locator('body').evaluate('el => getComputedStyle(el).backgroundColor')
    # white can be rgb(255, 255, 255) or rgba(255, 255, 255, 1)
    assert '255, 255, 255' in bg
    page.close()


def test_static_js_loads(device_url, browser_context):
    """JavaScript file loads and executes through the data channel."""
    page = browser_context.new_page()
    page.goto(device_url, wait_until='networkidle')

    frame = page.frame_locator('#device-frame')
    heading = frame.locator('#heading')
    heading.wait_for(timeout=15000)

    # app.js sets data-loaded="true" on DOMContentLoaded
    assert heading.get_attribute('data-loaded') == 'true'
    page.close()
