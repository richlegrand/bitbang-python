"""BitBang cryptographic identity management.

Devices get a persistent RSA-2048 keypair and a 64-bit access code. The UID
in the URL is derived from the public key hash (first 128 bits of
SHA-256(DER pubkey), base64url-encoded). The access code is independent
and travels in the URL fragment, never sent to the signaling server.
Both are stored in the same identity file.

Encoding: base64url without padding. UID is 22 chars, code is 11 chars.
The alphabet is ``[A-Za-z0-9_-]`` — URL-safe, stdlib in Python/Go/JS, and
roughly 35% shorter than the equivalent hex.

Key storage: ~/.bitbang/<program_name>/identity.pem (mode 600)
The file contains two PEM blocks:
  - ``PRIVATE KEY``           — PKCS8 RSA private key
  - ``BITBANG ACCESS CODE``   — base64-wrapped raw 8 random bytes; the
                                URL-facing string form is the same bytes
                                encoded as 11 base64url chars

Legacy identity files (single PEM block, no access code) are rejected on
load and the user is told to ``--regenerate``; the v3 signaling server
won't accept the legacy UID anyway.

Usage:
    from bitbang.identity import load_or_create_identity

    private_key, uid, code = load_or_create_identity()
    # uid:  22-char base64url string derived from the public key
    # code: 11-char base64url string (random, persisted alongside the key)
"""

import os
import sys
import hashlib
import base64
import secrets
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes, serialization

# Domain separation tag prepended to the challenge nonce before signing.
# Must match the signaling server's AUTH_DOMAIN.
#
# Prevents cross-protocol attacks: without this prefix, a malicious server
# could send nonce = SHA256(arbitrary_payload) and reuse the device's
# signature in another context (e.g. firmware verification) that uses the
# same RSA key. Binding every signature to its purpose makes a signature
# from one context structurally invalid in any other.
#
# Bumped only if the signing scheme itself changes (padding/hash/structure),
# not when the surrounding protocol version changes.
AUTH_DOMAIN = b"bitbang-auth-v1:"

# PEM block name for the access code stored alongside the private key.
ACCESS_CODE_PEM_TYPE = "BITBANG ACCESS CODE"

# Access code length in bytes — 8 bytes = 64 bits, displayed as 11
# base64url chars (no padding).
ACCESS_CODE_BYTES = 8


def generate_identity():
    """Generate new RSA-2048 identity plus a fresh access code.

    Returns:
        tuple: (private_key, uid, code) where uid is 22-char base64url
        and code is 11-char base64url.
    """
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    uid = uid_from_public_key(private_key.public_key())
    code = generate_access_code()
    return private_key, uid, code


def generate_access_code() -> str:
    """Generate a fresh 64-bit access code as an 11-char base64url string."""
    # secrets.token_urlsafe(nbytes) emits base64url without padding —
    # exactly the format we want for URL fragments and JSON payloads.
    return secrets.token_urlsafe(ACCESS_CODE_BYTES)


def uid_from_public_key(public_key) -> str:
    """Derive 128-bit UID from public key (22 base64url chars).

    Uses SHA-256 hash of DER-encoded public key, truncated to 128 bits and
    encoded as base64url without padding. The access code (separate, not
    derived from the key) provides an independent rotatable secret.

    Args:
        public_key: RSA public key object

    Returns:
        str: 22-character base64url string (alphabet [A-Za-z0-9_-])
    """
    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    digest = hashlib.sha256(public_bytes).digest()[:16]
    return base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')


def public_key_to_base64(public_key) -> str:
    """Encode public key as base64 DER for transmission."""
    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return base64.b64encode(public_bytes).decode('ascii')


def public_key_from_base64(b64_str: str):
    """Decode base64 DER public key."""
    public_bytes = base64.b64decode(b64_str)
    return serialization.load_der_public_key(public_bytes)


def sign_challenge(private_key, nonce: bytes) -> bytes:
    """Sign challenge nonce with private key.

    Uses RSASSA-PKCS1v1_5 padding with SHA-256 hash. The signed payload is
    AUTH_DOMAIN + nonce; see AUTH_DOMAIN comment.
    """
    return private_key.sign(
        AUTH_DOMAIN + nonce,
        padding.PKCS1v15(),
        hashes.SHA256()
    )


def decrypt_oaep(private_key, ciphertext: bytes) -> bytes:
    """Decrypt a payload that the browser encrypted with RSA-OAEP/SHA-256.

    The browser uses SubtleCrypto with `{name: 'RSA-OAEP', hash: 'SHA-256'}`
    and no label; this is the matching decrypt. Used to unwrap the
    bidirectional-verify payload ({fingerprint, nonce, code}) that the
    browser delivers on the WebRTC answer.
    """
    return private_key.decrypt(
        ciphertext,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )


def verify_challenge(public_key, nonce: bytes, signature: bytes) -> bool:
    """Verify challenge signature.

    Mirrors sign_challenge — RSASSA-PKCS1v1_5 + SHA-256 over AUTH_DOMAIN + nonce.
    """
    try:
        public_key.verify(
            signature,
            AUTH_DOMAIN + nonce,
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        return True
    except Exception:
        return False


def _encode_pem_block(pem_type: str, body: bytes) -> bytes:
    """Encode a single PEM block (header + base64 body in 64-char lines + footer)."""
    b64 = base64.b64encode(body).decode('ascii')
    lines = [b64[i:i + 64] for i in range(0, len(b64), 64)] or ['']
    return (
        f"-----BEGIN {pem_type}-----\n"
        + "\n".join(lines)
        + f"\n-----END {pem_type}-----\n"
    ).encode('ascii')


def _extract_pem_block(data: bytes, pem_type: str) -> bytes | None:
    """Return the body bytes of the named PEM block, or None if absent.

    Tolerates extra surrounding content (other PEM blocks, whitespace).
    """
    begin = f"-----BEGIN {pem_type}-----".encode('ascii')
    end = f"-----END {pem_type}-----".encode('ascii')
    start = data.find(begin)
    if start < 0:
        return None
    body_start = start + len(begin)
    stop = data.find(end, body_start)
    if stop < 0:
        return None
    body_b64 = data[body_start:stop].strip()
    try:
        return base64.b64decode(body_b64)
    except Exception:
        return None


def save_identity(path: str, private_key, code: str):
    """Save private key + access code to a multi-block PEM file (mode 600).

    The file contains the PKCS8 ``PRIVATE KEY`` block followed by a
    ``BITBANG ACCESS CODE`` block. The block body is standard PEM base64
    of the raw 8 code bytes — the URL-facing string form (`code`) is the
    same bytes encoded as 11 base64url-no-padding chars; we decode it
    back to raw here.
    """
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
    # base64.urlsafe_b64decode is strict about padding, so add what we stripped.
    code_bytes = base64.urlsafe_b64decode(code + '=' * (-len(code) % 4))
    code_block = _encode_pem_block(ACCESS_CODE_PEM_TYPE, code_bytes)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(pem)
        f.write(code_block)


def load_identity(path: str):
    """Load private key + access code from a PEM file.

    Returns:
        tuple: (private_key, code) where code is an 11-char base64url
        string, or None if the file lacks the ``BITBANG ACCESS CODE``
        block (legacy identity).
    """
    with open(path, 'rb') as f:
        data = f.read()
    private_key = serialization.load_pem_private_key(data, password=None)
    code_bytes = _extract_pem_block(data, ACCESS_CODE_PEM_TYPE)
    if code_bytes is None or len(code_bytes) != ACCESS_CODE_BYTES:
        return private_key, None
    return private_key, base64.urlsafe_b64encode(code_bytes).rstrip(b'=').decode('ascii')


def load_or_create_identity(program_name: str = None, ephemeral: bool = False,
                            identity_path: str = None, regenerate: bool = False):
    """Load existing identity or create new one.

    Identity is stored in ~/.bitbang/<program_name>/identity.pem.
    Each program gets its own persistent identity by default.
    On first run, generates a new keypair and saves it.

    A legacy (single-block, no access code) identity file is treated as
    such: the function prints a message and exits with status 1, since
    the v3 signaling server rejects the legacy UID it would derive.

    Returns:
        tuple: (private_key, uid, code)
    """
    if ephemeral:
        return generate_identity()

    if identity_path:
        private_key, code = load_identity(identity_path)
        if code is None:
            _exit_legacy_identity(identity_path)
        uid = uid_from_public_key(private_key.public_key())
        return private_key, uid, code

    home = os.path.expanduser('~')
    if program_name:
        bitbang_dir = os.path.join(home, '.bitbang', program_name)
    else:
        bitbang_dir = os.path.join(home, '.bitbang')
    default_path = os.path.join(bitbang_dir, 'identity.pem')

    if regenerate and os.path.exists(default_path):
        os.remove(default_path)

    if os.path.exists(default_path):
        private_key, code = load_identity(default_path)
        if code is None:
            _exit_legacy_identity(default_path)
        uid = uid_from_public_key(private_key.public_key())
        return private_key, uid, code

    # Create new identity
    os.makedirs(bitbang_dir, exist_ok=True)
    private_key, uid, code = generate_identity()
    save_identity(default_path, private_key, code)
    print(f"Created new identity: {uid}")
    return private_key, uid, code


def _exit_legacy_identity(path: str):
    """Print a clear message and exit when a legacy identity file is found."""
    print(
        f"Identity file at {path} is in a legacy format with no access\n"
        f"code block. The current signaling server (bitba.ng) requires the\n"
        f"split-identity (UID + code) format. Run with --regenerate to\n"
        f"create a new identity (your old URL will stop working).",
        file=sys.stderr,
    )
    sys.exit(1)


def print_qr_code(url: str):
    """Print QR code to terminal.

    Requires qrcode package (optional dependency).
    Silently skips if not installed.
    """
    try:
        import qrcode
        qr = qrcode.QRCode(
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=1,
            border=1,
        )
        qr.add_data(url)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
    except ImportError:
        pass  # qrcode not installed, skip
