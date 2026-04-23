# BitBang

![Tests](https://github.com/richlegrand/bitbang/actions/workflows/tests.yml/badge.svg)
![PyPI](https://img.shields.io/pypi/v/bitbang)
![Python](https://img.shields.io/pypi/pyversions/bitbang)
![License](https://img.shields.io/github/license/richlegrand/bitbang)

Access your local web server from anywhere -- no account, no subscription, no cloud in the middle. BitBang uses WebRTC to connect browsers directly to your device, peer-to-peer.

## Quick demo

Install:
```
pip install bitbang              # Linux / macOS
python -m pip install bitbang    # Windows (or any platform) 
```

Quick test:
```bash
bitbang-fileshare ~/Downloads            # Linux / macOS
python -m bitbang fileshare ~/Downloads  # Windows (or any platform)
```

This prints a URL and QR code. Anyone with the link can browse and download files directly from your machine, or they can upload files to the specified directory. Note, you can verify it works outside your local network, by scanning the QR code from a phone on cellular (turn off WiFi).

## Flask / FastAPI integration (or any WSGI / ASGI web framework)

Take an existing Flask or FastAPI app and add remote access. 


```python
# Flask 
from bitbang import BitBangWSGI
...
app = Flask(__name__)
adapter = BitBangWSGI(app)
adapter.run()  # Prints QR code and public URL
```

```python
# FastAPI 
from bitbang import BitBangASGI
...
app = FastAPI()
adapter = BitBangASGI(app)
adapter.run() # Prints QR code and public URL
```

## Comparison

| | ngrok | Cloudflare Tunnel | Tailscale | BitBang |
|---|---|---|---|---|
| Account required | Yes | Yes | Yes | No |
| Free tunnels | 1 | Unlimited | Unlimited | Unlimited |
| Data path | Their servers | Their servers | P2P | P2P |
| Viewer needs install | No | No | Yes | No |
| Configuration | CLI flags | Config file + DNS | Dashboard | None |

BitBang's data path is direct between peers. The signaling server brokers the initial connection, then steps aside.

---

## Fileshare

Fileshare allows you to easily/quickly share local files without uploading them to a third-party service. It's intended to be an example of a simple (yet useful!) BitBang application. It's just a straightforward Flask app.

```bash
bitbang-fileshare big_sourcetree.tar.gz       # Share a single file
bitbang-fileshare ~/Documents/project         # Share a directory (uploads enabled)
python -m bitbang fileshare c:\ide\files      # Windows
```

Files transfer directly from your machine to the recipient. The recipient can also upload files to your machine.

## Webcam

The Webcam app streams video from your webcam to a browser using WebRTC media channels and BitBang. It can be used as an easy-to-setup monitoring/security camera using your laptop, for example.

```bash
bitbang-webcam                  # Linux / macOS
python -m bitbang webcam        # Windows (or any platform)
```

## Examples

The `examples/` directory contains two simple examples which show how to integrate BitBang into your current Python web frameworks:

```bash
cd examples/simple_fastapi && python3 app.py
cd examples/simple_flask && python3 app.py
```

---

## Python API

These options are available from the BitBang constructor (same options for BitBangASGI):

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

If your app uses argparse, `add_bitbang_args` and `bitbang_kwargs` can wire up the standard CLI flags for you:

```python
from bitbang.adapter import BitBangWSGI, add_bitbang_args, bitbang_kwargs

parser = argparse.ArgumentParser()
parser.add_argument('path')
add_bitbang_args(parser)
args = parser.parse_args()

adapter = BitBangWSGI(app, **bitbang_kwargs(args, program_name='myapp'))
```

These options appear like this on the command line:

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

When `--debug` is enabled, the printed URL includes `?debug`, which activates a browser-side debug UI showing connection steps (connecting to server, waiting for device, establishing peer connection). Without it, the browser shows a simple "Loading..." while connecting.

Each app gets its own persistent RSA keypair and URL, stored in `~/.bitbang/<program_name>/identity.pem`. This means the URL for each BitBang program stays the same across restarts. Use `--regenerate` to get a new URL, or `--ephemeral` for a one-time session.

`bitba.ng` provides a TURN server when a peer-to-peer connection isn't possible, but you can provide your own TURN server if you prefer via the command-line options or through the constructor by specifying `ice_servers` in browser-native WebRTC format. The defaults should work fine though, so you shouldn't need to provide these.  

---

## Background

The Internet is often thought of as a fully connected network -- every machine is accessible from every other machine. But there are rules governing accessibility on the Internet... 

### Rules of Internet Accessibility

1. Machines on the Internet are accessible by other machines on the Internet -- and by machines on your local network.
2. Machines on your local network are only accessible by other machines on your local network.

Because of rule 2, machines on your local network aren't reachable from outside -- nor are the resources they hold: files, cameras, sensors, compute, or the web app you're currently developing. Cloud services exist to fill this gap: Dropbox for files, AWS IoT for sensors, Tailscale for compute, and ngrok for web apps -- among others. These services apply rule 1, but each comes with the friction of account creation, fees, and your data living on someone else's server.

BitBang connects a browser directly to any machine on your local network, from anywhere on the Internet. No cloud intermediary, no account, no third party in the middle. It uses a novel application of the peer-to-peer technology WebRTC. 

### WebRTC

WebRTC is the behind-the-scenes technology that makes Zoom and Google Meet video conferencing possible. WebRTC offers the highest bandwidth and lowest latency possible, which is good when you're streaming live video, or practically anything else. It's mature, well-tested, and has ubiquitous support across all browsers. In addition to delivering low-latency media, it can also deliver raw data over "data channels", which is what BitBang uses.


## How it works

Browsers normally connect to web servers over a TCP socket. BitBang replaces this with a WebRTC data channel:

![BitBang Python Block Diagram](https://raw.githubusercontent.com/richlegrand/bitbang/refs/heads/main/assets/bitbang_python.png)

The signaling server (`bitba.ng`) brokers the WebRTC handshake, then has no further involvement and never sees application data.

## Signaling server

The signaling server source is available [here](https://github.com/richlegrand/bitbang-server). It:

1. Serves the BitBang browser runtime
2. Validates connecting devices via RSA challenge
3. Maintains WebSocket connections to active devices
4. Brokers ICE candidate and SDP exchange between browsers and devices

After the P2P connection is established, the signaling server is not involved. We are providing a signaling server for testing, etc. at https://bitba.ng. It mostly brokers connections, so it doesn't need many resources. 

## Security

WebRTC mandates encryption:

- **Data channels**: DTLS 1.2+
- **Media streams**: SRTP 
- **Signaling**: HTTPS and WSS

Furthermore, each BitBang "device" generates an RSA keypair. The public key hash becomes its unique 128-bit ID, which is used in its BitBang public URL. The signaling server challenge-verifies key ownership (and hence ID) before accepting connections.

## Related

[BitBangProxy](https://github.com/richlegrand/bitbangproxy) is a standalone Go binary that proxies any local web serve (NAS, router, media server, etc.) through a WebRTC data channel. You simply run it on a local machine -- Windows, macOS, and Linux are supported. The target is specified in the URL at browse-time:

```
https://bitba.ng/<proxy-id>/192.168.1.10
https://bitba.ng/<proxy-id>/nas.local
https://bitba.ng/<proxy-id>/octopi.local:5000
```

## Roadmap

**ESP32 support** -- Native BitBang for microcontrollers, including video streaming and OTA updates. It's an IoT network with no account set-up, subscription, etc. Espressif has released a closed-source WebRTC library. Ours is a port of [libdatachannel](https://github.com/paullouisageneau/libdatachannel), and it's open of course.

---

## License

MIT

## Contributing

Issues and pull requests are welcome.
