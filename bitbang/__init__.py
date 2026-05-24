# bitbang/__init__.py
from .adapter import BitBangBase, BitBangWSGI, BitBangASGI
from .proxy import ReverseProxyWSGI, ReverseProxyASGI
from .identity import (
    generate_identity,
    generate_access_code,
    load_or_create_identity,
    uid_from_public_key,
    sign_challenge,
    verify_challenge,
)

__version__ = "0.1.52"

# SWSP protocol version sent in the register message. The signaling server
# rejects devices below its minimum. Bump only for breaking wire changes.
#
# v3: split-identity URLs — 80-bit UID + 40-bit access code in fragment.
# Browsers/devices on this version must use the new identity format
# (multi-block PEM); the v3 signaling server rejects legacy 32-hex UIDs.
PROTOCOL_VERSION = 3
