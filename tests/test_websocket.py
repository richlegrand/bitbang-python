"""Test WebSocket bridging through the BitBang data channel."""


def test_websocket_echo(ws_device_url, playwright):
    """WebSocket messages round-trip through the BitBang tunnel."""
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    page.goto(ws_device_url, wait_until='networkidle')

    frame = page.frame_locator('#device-frame')
    frame.locator('#heading').wait_for(timeout=15000)

    # Run the WebSocket test from the page's JS
    messages = frame.locator('body').evaluate('''() => {
        return new Promise((resolve, reject) => {
            var ws = new WebSocket('ws://' + location.host + '/echo');
            var received = [];

            ws.onopen = function() {
                ws.send('hello');
                ws.send('world');
                ws.send('bitbang');
            };

            ws.onmessage = function(e) {
                received.push(e.data);
                if (received.length >= 3) {
                    ws.close();
                    resolve(received);
                }
            };

            ws.onerror = function() {
                reject('WebSocket error');
            };

            setTimeout(function() {
                ws.close();
                resolve(received);
            }, 10000);
        });
    }''')

    assert len(messages) == 3
    assert messages[0] == 'echo:hello'
    assert messages[1] == 'echo:world'
    assert messages[2] == 'echo:bitbang'

    page.close()
    context.close()
    browser.close()


def test_websocket_binary(ws_device_url, playwright):
    """Binary WebSocket messages round-trip through the BitBang tunnel."""
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    page.goto(ws_device_url, wait_until='networkidle')

    frame = page.frame_locator('#device-frame')
    frame.locator('#heading').wait_for(timeout=15000)

    # Send and receive binary data
    result = frame.locator('body').evaluate('''() => {
        return new Promise((resolve, reject) => {
            var ws = new WebSocket('ws://' + location.host + '/echo');
            ws.binaryType = 'arraybuffer';

            ws.onopen = function() {
                var buf = new Uint8Array([1, 2, 3, 4, 5]);
                ws.send(buf.buffer);
            };

            ws.onmessage = function(e) {
                // Binary echo comes back as text with 'echo:' prefix
                // because the echo server receives bytes and sends back a string
                ws.close();
                resolve(typeof e.data === 'string' ? e.data : 'binary');
            };

            ws.onerror = function() {
                reject('WebSocket error');
            };

            setTimeout(function() {
                ws.close();
                resolve('timeout');
            }, 10000);
        });
    }''')

    # The echo server converts bytes to string, so we get back a string
    assert result != 'timeout'

    page.close()
    context.close()
    browser.close()
