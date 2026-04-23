# bitbang/__init__.py
from .adapter import BitBangBase, BitBangWSGI, BitBangASGI
from .proxy import ReverseProxyWSGI, ReverseProxyASGI
from .identity import (
    generate_identity,
    load_or_create_identity,
    uid_from_public_key,
    sign_challenge,
    verify_challenge,
)

__version__ = "0.1.47"

# SWSP protocol version sent in the register message. The signaling server
# rejects devices below its minimum. Bump only for breaking wire changes.
PROTOCOL_VERSION = 1
