"""Test file download and upload through the data channel."""

import json


def test_file_download(device_url, browser_context):
    """Download a ~100KB file through the WebRTC data channel."""
    page = browser_context.new_page()
    page.goto(device_url, wait_until='networkidle')

    frame = page.frame_locator('#device-frame')
    frame.locator('#heading').wait_for(timeout=15000)

    # Fetch the file and check its size
    result = frame.locator('body').evaluate('''() => {
        return fetch("/download").then(r => {
            const len = r.headers.get("content-length");
            return r.arrayBuffer().then(buf => ({
                status: r.status,
                content_length: len,
                actual_size: buf.byteLength,
            }));
        });
    }''')

    assert result['status'] == 200
    assert result['actual_size'] > 90000  # ~100KB
    assert result['actual_size'] == int(result['content_length'])

    page.close()


def test_file_upload(device_url, browser_context):
    """Upload data to the device via POST."""
    page = browser_context.new_page()
    page.goto(device_url, wait_until='networkidle')

    frame = page.frame_locator('#device-frame')
    frame.locator('#heading').wait_for(timeout=15000)

    # Upload 10KB of data
    result = frame.locator('body').evaluate('''() => {
        const data = new Uint8Array(10240);
        for (let i = 0; i < data.length; i++) data[i] = i % 256;
        return fetch("/upload", {
            method: "POST",
            headers: { "Content-Type": "application/octet-stream" },
            body: data,
        }).then(r => r.json());
    }''')

    assert result['size'] == 10240
    assert 'octet-stream' in result['content_type']

    page.close()
