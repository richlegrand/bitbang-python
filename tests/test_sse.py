"""Test Server-Sent Events streaming through the data channel."""

from .frames import device_frame

def test_sse_messages_arrive(device_url, browser_context):
    """SSE stream delivers messages incrementally through WebRTC."""
    page = browser_context.new_page()
    page.goto(device_url, wait_until='networkidle')

    frame = device_frame(page)
    frame.locator('#heading').wait_for(timeout=15000)

    # Open an EventSource and collect messages
    messages = frame.locator('body').evaluate('''() => {
        return new Promise((resolve) => {
            const msgs = [];
            const es = new EventSource("/sse");
            es.onmessage = (e) => {
                msgs.push(e.data);
                if (msgs.length >= 3) {
                    es.close();
                    resolve(msgs);
                }
            };
            es.onerror = () => {
                es.close();
                resolve(msgs);
            };
            // Timeout after 10s
            setTimeout(() => { es.close(); resolve(msgs); }, 10000);
        });
    }''')

    assert len(messages) == 3
    assert messages[0] == 'message 0'
    assert messages[1] == 'message 1'
    assert messages[2] == 'message 2'

    page.close()
