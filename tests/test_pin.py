"""Test PIN authentication."""


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
    """Entering the wrong PIN shows spinner then re-prompts."""
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    page.goto(pin_device_url, wait_until='networkidle')

    # Enter wrong PIN
    page.wait_for_selector('#pin-input', timeout=15000)
    page.fill('#pin-input', '0000')
    page.click('#pin-submit')

    # PIN input should disappear (spinner shown)
    page.wait_for_selector('#pin-input', state='hidden', timeout=5000)

    # After delay, PIN prompt should reappear
    page.wait_for_selector('#pin-input', timeout=10000)
    assert page.locator('#pin-input').is_visible()

    # Now enter correct PIN
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

    # Navigate directly to a protected path
    page.goto(pin_callback_device_url + '/protected', wait_until='networkidle')

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
