"""Test PIN authentication."""

from urllib.parse import urlparse, urlunparse


def _with_path(url: str, path: str) -> str:
    """Append `path` to `url`, preserving the fragment.

    `url` is the device URL with a `#code` fragment. Naive string
    concatenation (``url + '/x'``) would push the path inside the
    fragment, breaking bidirectional verify. This splices the path in
    before the fragment.
    """
    p = urlparse(url)
    return urlunparse(p._replace(path=p.path + path))


def test_pin_prompt_appears(pin_device_url, playwright):
    """Device with PIN shows the PIN prompt before loading content."""
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    page.goto(pin_device_url, wait_until='networkidle')

    # The PIN prompt should be visible (not the device content)
    page.wait_for_selector('#pin-input', timeout=15000)
    assert page.locator('#pin-input').is_visible()

    page.close()
    context.close()
    browser.close()


def test_pin_correct_proceeds(pin_device_url, playwright):
    """Entering the correct PIN loads the device content."""
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    page.goto(pin_device_url, wait_until='networkidle')

    # Enter correct PIN
    page.wait_for_selector('#pin-input', timeout=15000)
    page.fill('#pin-input', '1234')
    page.click('#pin-submit')

    # Wait for device content to load in the iframe
    frame = page.frame_locator('#device-frame')
    heading = frame.locator('#heading')
    heading.wait_for(timeout=15000)

    assert heading.text_content() == 'Hello from BitBang'

    page.close()
    context.close()
    browser.close()


def test_pin_wrong_retries(pin_device_url, playwright):
    """Entering the wrong PIN re-prompts after a delay."""
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    page.goto(pin_device_url, wait_until='networkidle')

    # Enter wrong PIN
    page.wait_for_selector('#pin-input', timeout=15000)
    page.fill('#pin-input', '0000')
    page.click('#pin-submit')

    # After delay, PIN prompt should still be visible (ready for retry)
    page.wait_for_timeout(4000)
    assert page.locator('#pin-input').is_visible()

    # Clear and enter correct PIN
    page.locator('#pin-input').clear()
    page.fill('#pin-input', '1234')
    page.click('#pin-submit')

    frame = page.frame_locator('#device-frame')
    heading = frame.locator('#heading')
    heading.wait_for(timeout=15000)
    assert heading.text_content() == 'Hello from BitBang'

    page.close()
    context.close()
    browser.close()


def test_pin_callback_open_path(pin_callback_device_url, playwright):
    """PIN callback: root path doesn't require PIN."""
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    page.goto(pin_callback_device_url, wait_until='networkidle')

    # Should load directly without PIN prompt
    frame = page.frame_locator('#device-frame')
    heading = frame.locator('#heading')
    heading.wait_for(timeout=15000)
    assert heading.text_content() == 'Hello from BitBang'

    page.close()
    context.close()
    browser.close()


def test_pin_callback_protected_path(pin_callback_device_url, playwright):
    """PIN callback: /protected path requires PIN '1234'."""
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    # Navigate directly to a protected path. Use _with_path to splice
    # '/protected' in before the URL fragment — naive concatenation would
    # corrupt the access code.
    page.goto(_with_path(pin_callback_device_url, '/protected'), wait_until='networkidle')

    # Should see PIN prompt
    page.wait_for_selector('#pin-input', timeout=15000)
    page.fill('#pin-input', '1234')
    page.click('#pin-submit')

    # Should load the protected content
    frame = page.frame_locator('#device-frame')
    frame.locator('body').wait_for(timeout=15000)

    page.close()
    context.close()
    browser.close()
