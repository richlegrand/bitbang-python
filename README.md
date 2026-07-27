# bitbang-python

[![Tests](https://github.com/richlegrand/bitbang-python/actions/workflows/tests.yml/badge.svg)](https://github.com/richlegrand/bitbang-python/actions/workflows/tests.yml)
[![PyPI](https://img.shields.io/pypi/v/bitbang)](https://pypi.org/project/bitbang/)
[![Python](https://img.shields.io/pypi/pyversions/bitbang)](https://pypi.org/project/bitbang/)
![License](https://img.shields.io/github/license/richlegrand/bitbang-python)

**Turns your local Python web app into a URL you can open from anywhere.**

`bitbang` wraps a WSGI or ASGI app (Flask, FastAPI, Quart) and prints a URL and QR code. Open the URL in any browser and you're connected to the app -- peer-to-peer, end-to-end encrypted, with no account, no port forwarding. 

This is the Python implementation of [BitBang](https://github.com/richlegrand/bitbang). For remote access to a whole machine (shell, files, proxy) without writing code, see [bitbang-cli](https://github.com/richlegrand/bitbang-cli).


## Install

```
pip install bitbang              # Linux / macOS
python -m pip install bitbang    # Windows (or any platform)
```

## Quick test

```
bitbang-fileshare ~/Downloads            # Linux / macOS
python -m bitbang fileshare ~/Downloads  # Windows (or any platform)
```

This prints a URL and QR code. Anyone with the link can browse and download files directly from your machine, or upload files to the shared directory. To verify it works outside your local network, scan the QR code from a phone on cellular (turn off WiFi).

## Flask / FastAPI integration (or any WSGI / ASGI framework)

Take an existing app and give it a URL:

```python
# Flask
from bitbang import BitBangWSGI

app = Flask(__name__)
adapter = BitBangWSGI(app)
adapter.run()  # Prints QR code and public URL
```

```python
# FastAPI
from bitbang import BitBangASGI

app = FastAPI()
adapter = BitBangASGI(app)
adapter.run()  # Prints QR code and public URL
```

The `examples/` directory contains a minimal version of each:

```
cd examples/simple_fastapi && python3 app.py
cd examples/simple_flask && python3 app.py
```

## Bundled apps

**Fileshare** shares local files without uploading them to a third-party service. Files transfer directly from your machine to the recipient, and the recipient can upload files back. It's also intended as an example of a simple BitBang application -- it's a straightforward Flask app.

```
bitbang-fileshare big_sourcetree.tar.gz       # Share a single file
bitbang-fileshare ~/Documents/project         # Share a directory (uploads enabled)
python -m bitbang fileshare c:\ide\files      # Windows
```

**Webcam** streams video from your webcam to a browser over WebRTC media channels -- an easy-to-set-up monitoring camera using a laptop, for example.

```
bitbang-webcam                  # Linux / macOS
python -m bitbang webcam        # Windows (or any platform)
```

## Python API

These options are available from the `BitBangWSGI` constructor (same options for `BitBangASGI`):

```python
adapter = BitBangWSGI(app,
    program_name='BitBang',    # Identity name, shows in browser title
    server='bitba.ng',         # Signaling server (default: bitba.ng)
    ephemeral=False,           # Use a temporary identity (not saved to disk)
    identity_path=None,        # Use a specific identity file
    regenerate=False,          # Delete and regenerate identity
    debug=False,               # Verbose logging + browser debug UI (?debug)
    pin=None,                  # PIN string to protect access
    pin_callback=None,         # Function(path, pin) -> bool for custom auth
    ice_servers=None,          # Custom TURN server config
)
```

If your app uses argparse, `add_bitbang_args` and `bitbang_kwargs` wire up the standard CLI flags:

```python
from bitbang.adapter import BitBangWSGI, add_bitbang_args, bitbang_kwargs

parser = argparse.ArgumentParser()
parser.add_argument('path')
add_bitbang_args(parser)
args = parser.parse_args()

adapter = BitBangWSGI(app, **bitbang_kwargs(args, program_name='myapp'))
```

These options appear on the command line as:

```
--ephemeral              Use a temporary identity
--identity PATH          Use a specific identity file
--regenerate             Delete and regenerate identity
--server HOST            Signaling server hostname
--turn-url URL           TURN server URL (e.g. turn:myserver.com:3478)
--turn-user USER         TURN server username
--turn-credential PASS   TURN server credential
--pin PIN                PIN to protect access
--debug                  Enable verbose logging and browser debug UI
```

With `--debug`, the printed URL includes `?debug`, which activates a browser-side debug UI showing connection steps. Without it, the browser shows a simple "Loading..." while connecting.

### Identity and URLs

Each app gets its own persistent RSA keypair, stored at `~/.bitbang/<program_name>/identity.pem`. The public key hash becomes the app's 128-bit ID, used in its URL -- so the URL stays the same across restarts. Use `--regenerate` for a new URL, or `--ephemeral` for a one-time session.

### TURN

When a direct peer-to-peer connection isn't possible, `bitba.ng` provides a TURN relay, which carries only ciphertext. You can supply your own TURN server via the command-line options or the `ice_servers` constructor argument (browser-native WebRTC format). The defaults work fine for most setups.

## How it works

Browsers normally connect to web servers over a TCP socket. BitBang replaces this with a WebRTC data channel:

![BitBang Python block diagram](https://raw.githubusercontent.com/richlegrand/bitbang-python/refs/heads/main/assets/bitbang_python.png)

The signaling server brokers the WebRTC handshake, then has no further involvement and never sees application data. The full story -- architecture, trust model, and origin -- is in the [BitBang project README](https://github.com/richlegrand/bitbang), the [whitepaper](https://github.com/richlegrand/bitbang/blob/main/whitepaper.md), and [Trustless Signaling](https://github.com/richlegrand/bitbang/blob/main/trustless-signaling.md) document.

## License

MIT

## Contributing

Issues and pull requests are welcome.