"""BitBang cryptographic identity management.

Devices get a persistent RSA-2048 keypair. The UID (used in URLs) is derived
from the public key hash, ensuring globally unique and verifiable identity.

Key storage: ~/.bitbang/<program_name>/identity.pem (mode 600)

Usage:
    from bitbang.identity import load_or_create_identity

    private_key, uid = load_or_create_identity()
    # uid is a 32-char hex string derived from public key
"""

import os
import hashlib
import base64
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


def generate_identity():
    """Generate new RSA-2048 identity.

    Returns:
        tuple: (private_key, uid) where uid is 32-char hex string
    """
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    uid = uid_from_public_key(private_key.public_key())
    return private_key, uid


def uid_from_public_key(public_key) -> str:
    """Derive 128-bit UID from public key (32 hex chars).

    Uses SHA-256 hash of DER-encoded public key, truncated to 128 bits.
    This provides collision resistance while keeping URLs manageable.

    Args:
        public_key: RSA public key object

    Returns:
        str: 32-character hex string
    """
    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return hashlib.sha256(public_bytes).hexdigest()[:32]


def public_key_to_base64(public_key) -> str:
    """Encode public key as base64 DER for transmission.

    Args:
        public_key: RSA public key object

    Returns:
        str: Base64-encoded DER public key
    """
    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return base64.b64encode(public_bytes).decode('ascii')


def public_key_from_base64(b64_str: str):
    """Decode base64 DER public key.

    Args:
        b64_str: Base64-encoded DER public key

    Returns:
        RSA public key object
    """
    public_bytes = base64.b64decode(b64_str)
    return serialization.load_der_public_key(public_bytes)


def sign_challenge(private_key, nonce: bytes) -> bytes:
    """Sign challenge nonce with private key.

    Uses RSASSA-PKCS1v1_5 padding with SHA-256 hash. The signed payload is
    AUTH_DOMAIN + nonce; see AUTH_DOMAIN comment.

    Args:
        private_key: RSA private key object
        nonce: Challenge bytes to sign

    Returns:
        bytes: Signature
    """
    return private_key.sign(
        AUTH_DOMAIN + nonce,
        padding.PKCS1v15(),
        hashes.SHA256()
    )


def verify_challenge(public_key, nonce: bytes, signature: bytes) -> bool:
    """Verify challenge signature.

    Mirrors sign_challenge — RSASSA-PKCS1v1_5 + SHA-256 over AUTH_DOMAIN + nonce.

    Args:
        public_key: RSA public key object
        nonce: Original challenge bytes
        signature: Signature to verify

    Returns:
        bool: True if signature is valid
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


def save_identity(path: str, private_key):
    """Save private key to PEM file with restricted permissions.

    Creates file with mode 600 (owner read/write only).

    Args:
        path: File path to save to
        private_key: RSA private key object
    """
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(pem)


def load_identity(path: str):
    """Load private key from PEM file.

    Args:
        path: File path to load from

    Returns:
        RSA private key object
    """
    with open(path, 'rb') as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def load_or_create_identity(program_name: str = None, ephemeral: bool = False,
                            identity_path: str = None, regenerate: bool = False):
    """Load existing identity or create new one.

    Identity is stored in ~/.bitbang/<program_name>/identity.pem.
    Each program gets its own persistent identity by default.
    On first run, generates a new keypair and saves it.

    Args:
        program_name: Program name for identity directory (e.g. 'fileshare')
        ephemeral: Generate temporary identity (not saved to disk)
        identity_path: Use specific identity file instead of default
        regenerate: Delete and regenerate identity

    Returns:
        tuple: (private_key, uid)
    """
    if ephemeral:
        return generate_identity()

    if identity_path:
        private_key = load_identity(identity_path)
        uid = uid_from_public_key(private_key.public_key())
        return private_key, uid

    home = os.path.expanduser('~')
    if program_name:
        bitbang_dir = os.path.join(home, '.bitbang', program_name)
    else:
        bitbang_dir = os.path.join(home, '.bitbang')
    default_path = os.path.join(bitbang_dir, 'identity.pem')

    if regenerate and os.path.exists(default_path):
        os.remove(default_path)

    if os.path.exists(default_path):
        private_key = load_identity(default_path)
        uid = uid_from_public_key(private_key.public_key())
        return private_key, uid

    # Create new identity
    os.makedirs(bitbang_dir, exist_ok=True)
    private_key, uid = generate_identity()
    save_identity(default_path, private_key)
    print(f"Created new identity: {uid}")
    return private_key, uid


def print_qr_code(url: str):
    """Print QR code to terminal.

    Requires qrcode package (optional dependency).
    Silently skips if not installed.

    Args:
        url: URL to encode in QR code
    """
    try:
        import qrcode
        qr = qrcode.QRCode(
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=1,
            border=1,
        )
        qr.add_data(url)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
    except ImportError:
        pass  # qrcode not installed, skip
