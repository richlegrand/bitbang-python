"""Test page refresh re-establishes the connection."""


def test_refresh_reloads_page(device_url, browser_context):
    """Page refresh re-establishes the WebRTC connection and loads content."""
    page = browser_context.new_page()
    page.goto(device_url, wait_until='networkidle')

    frame = page.frame_locator('#device-frame')
    frame.locator('#heading').wait_for(timeout=15000)
    assert frame.locator('#heading').text_content() == 'Hello from BitBang'

    # Refresh
    page.reload(wait_until='networkidle')

    frame = page.frame_locator('#device-frame')
    frame.locator('#heading').wait_for(timeout=15000)
    assert frame.locator('#heading').text_content() == 'Hello from BitBang'

    page.close()


def test_hard_refresh(device_url, browser_context):
    """Hard refresh (Ctrl+Shift+R) re-establishes connection."""
    page = browser_context.new_page()
    page.goto(device_url, wait_until='networkidle')

    frame = page.frame_locator('#device-frame')
    frame.locator('#heading').wait_for(timeout=15000)
    assert frame.locator('#heading').text_content() == 'Hello from BitBang'

    # Hard refresh (bypass cache)
    page.keyboard.down('Shift')
    page.reload(wait_until='networkidle')
    page.keyboard.up('Shift')

    frame = page.frame_locator('#device-frame')
    frame.locator('#heading').wait_for(timeout=15000)
    assert frame.locator('#heading').text_content() == 'Hello from BitBang'

    page.close()


def test_multiple_pages(device_url, browser_context):
    """Two browser tabs can connect to the same device simultaneously."""
    page1 = browser_context.new_page()
    page1.goto(device_url, wait_until='networkidle')
    frame1 = page1.frame_locator('#device-frame')
    frame1.locator('#heading').wait_for(timeout=15000)

    page2 = browser_context.new_page()
    page2.goto(device_url, wait_until='networkidle')
    frame2 = page2.frame_locator('#device-frame')
    frame2.locator('#heading').wait_for(timeout=15000)

    # Both pages should be serving content
    assert frame1.locator('#heading').text_content() == 'Hello from BitBang'
    assert frame2.locator('#heading').text_content() == 'Hello from BitBang'

    page1.close()
    page2.close()
