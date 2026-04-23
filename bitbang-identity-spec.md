# BitBang Identity Specification

## Overview

Every bang has a cryptographic identity based on an RSA key pair. The identity serves three purposes:

1. **Unique identifier (UID)** — Derived from public key hash, used in URLs
2. **Ownership proof** — Device proves identity by signing challenges
3. **Spoofing prevention** — Cannot claim a UID without possessing the private key

## Key Generation

### RSA Parameters

- **Algorithm:** RSA
- **Key size:** 2048 bits
- **Public exponent:** 65537 (0x10001)

2048 bits is the standard minimum for RSA today. Fast to generate (~50ms), sufficient security, wide library support.

### UID Derivation

```
UID = first 128 bits of SHA-256(public_key_der)
```

Where `public_key_der` is the public key encoded in DER format (SubjectPublicKeyInfo).

- **128 bits = 32 hex characters**
- Standard UUID length
- Collision probability: effectively zero
- Example: `a8f3c2b1e9d4f6a7b2c8e1d3f5a9b0c4`

Manual typing is rare — QR codes and copy/paste handle the length.

### Encoding

**Canonical format: lowercase hexadecimal**

```
a8f3c2b1e9d4
```

12 characters, always lowercase, no prefix.

**Why hex over base58/base64:**

- Trivial to implement on any platform including ESP32
- No ambiguous characters (hex has no O/0 or I/1/l confusion anyway)
- URL-safe without encoding
- Easy to debug and log
- Consistent everywhere — no translation between internal/external formats

### Implementation

Python:

```python
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
import hashlib

def generate_identity():
    """Generate new RSA identity, return (private_key, uid)."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    
    uid = uid_from_public_key(private_key.public_key())
    
    return private_key, uid

def uid_from_public_key(public_key) -> str:
    """Derive 128-bit UID from public key."""
    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    
    # 128 bits = 16 bytes = 32 hex chars
    return hashlib.sha256(public_bytes).hexdigest()[:32]
```

C (ESP32):

```c
#include <mbedtls/rsa.h>
#include <mbedtls/sha256.h>
#include <mbedtls/pk.h>

void derive_uid(mbedtls_pk_context *pk, char *uid_out) {
    unsigned char der_buf[512];
    unsigned char hash[32];
    int der_len;
    
    // Export public key as DER
    der_len = mbedtls_pk_write_pubkey_der(pk, der_buf, sizeof(der_buf));
    // Note: mbedtls writes from end of buffer
    unsigned char *der_start = der_buf + sizeof(der_buf) - der_len;
    
    // SHA-256 hash
    mbedtls_sha256(der_start, der_len, hash, 0);
    
    // First 16 bytes (128 bits) as hex
    for (int i = 0; i < 16; i++) {
        sprintf(uid_out + (i * 2), "%02x", hash[i]);
    }
    uid_out[32] = '\0';
}
```

## Storage

### Location

Identity files are stored in `.bitbang/` directory relative to the application:

```
my-project/
├── app.py
├── .bitbang/
│   ├── identity.pem      # Private key (PEM format)
│   └── config.toml       # Optional configuration (TURN, etc.)
```

### File Format

Private key in PEM format (PKCS#8):

```
-----BEGIN PRIVATE KEY-----
MIIEvgIBADANBgkqhkiG9w0BAQEFAASC...
-----END PRIVATE KEY-----
```

This format is standard, supported by OpenSSL and every crypto library.

### Permissions

On Unix systems, `identity.pem` should be mode 600 (owner read/write only):

```python
import os
import stat

def save_identity(path: str, private_key):
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
    
    # Write with restrictive permissions
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(pem)
```

### Loading

On startup:

```python
def load_or_create_identity(base_dir: str) -> tuple[PrivateKey, str]:
    """Load existing identity or create new one."""
    bitbang_dir = os.path.join(base_dir, '.bitbang')
    identity_path = os.path.join(bitbang_dir, 'identity.pem')
    
    if os.path.exists(identity_path):
        # Load existing
        with open(identity_path, 'rb') as f:
            private_key = serialization.load_pem_private_key(f.read(), password=None)
        uid = uid_from_public_key(private_key.public_key())
        return private_key, uid
    
    # Create new
    os.makedirs(bitbang_dir, exist_ok=True)
    private_key, uid = generate_identity()
    save_identity(identity_path, private_key)
    
    return private_key, uid
```

## CLI Flags

### `--ephemeral`

Generate a new identity for this session only. Do not save to disk. UID will be different on every run.

Use case: Quick demos, testing, one-off sharing where you don't want persistent identity.

```bash
bitbang send ./file.mp4 --ephemeral
```

### `--regenerate`

Delete existing identity and generate a new one. The old UID becomes permanently invalid.

Use case: You shared a link you regret, or suspect your key was compromised.

```bash
bitbang files ./shared --regenerate
```

Prompts for confirmation:

```
Warning: This will permanently invalidate your current URL.
Old UID: a8f3c2b1e9d4f6a7b2c8e1d3f5a9b0c4
Anyone with links to this UID will no longer be able to connect.
Are you sure? [y/N]: 
```

### `--identity <path>`

Use a specific identity file instead of the default `.bitbang/identity.pem`.

Use case: Running multiple bangs with different identities, or sharing identity across machines.

```bash
bitbang files ./shared --identity ~/.my-server-identity.pem
```

### Priority

If multiple flags are specified:

1. `--ephemeral` wins — always generates temporary identity
2. `--identity <path>` — uses specified file
3. `--regenerate` + default — regenerates at default location
4. Default — loads from `.bitbang/identity.pem`, creates if missing

## CLI Output: QR Code

When a bang starts, it prints the URL and a QR code to the terminal:

```
🎉 Bang is live!

https://bitba.ng/a8f3c2b1e9d4f6a7b2c8e1d3f5a9b0c4

█████████████████████████████████
█████████████████████████████████
████ ▄▄▄▄▄ █▀▄▀▄█ ▀█ █ ▄▄▄▄▄ ████
████ █   █ █ ▄▀  ▀▄▄█ █   █ ████
████ █▄▄▄█ █ ▄▀▄█▀▄▀█ █▄▄▄█ ████
████▄▄▄▄▄▄▄█ █▄█ ▀ █▄▄▄▄▄▄▄████
████ ▄▀ ▄▀▄▄▀▄   ▀▄█▄▀  ▄▀█▀████
█████▀▄▀▄ ▄ ▄▀▄▄▀▄ ▀▄▄▀  █ ████
████▄█▄██▄▄█ ▀ ▀▄█▄ ▄▄▄ ▀▄▀████
████ ▄▄▄▄▄ █▄▀█▄▀▄  █▄█ ▀█▄████
████ █   █ █ ▀▄ █▀▄ ▄▄  ▄▀ ████
████ █▄▄▄█ █ █ ▀▄▄█▀▄▀▄ ▀██████
████▄▄▄▄▄▄▄█▄▄█▄██▄█▄▄█▄██▄████
█████████████████████████████████
█████████████████████████████████

Press Ctrl+C to stop
```

### Implementation

Uses the `qrcode` library with ASCII art output:

```python
import qrcode

def print_qr_code(url: str):
    """Print QR code to terminal."""
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=1,
        border=1,
    )
    qr.add_data(url)
    qr.make(fit=True)
    
    # Print as ASCII art using Unicode block characters
    qr.print_ascii(invert=True)
```

The `qrcode` package is pure Python and has no dependencies beyond `typing_extensions`. Add to requirements:

```
qrcode>=7.0
```

### Why QR Codes Matter

- **Mobile sharing:** Point phone at screen, instantly connected
- **Physical displays:** Print server puts QR code on wall
- **No typing:** 32-character hex UIDs are impractical to type manually
- **Demo-friendly:** Shows well in screenshots and videos

## Signaling Server Authentication

### Complete Connection Flow

```
Device                          Signaling Server
   |                                   |
   |-------- WebSocket connect ------->|
   |                                   |
   |-------- register --------------->|
   |         {uid, public_key}         |
   |                                   |
   |         (server validates uid     |
   |          matches public_key hash) |
   |                                   |
   |<------- challenge ---------------|
   |         {nonce}                   |
   |                                   |
   |-------- challenge_response ------>|
   |         {signature}               |
   |                                   |
   |         (server verifies          |
   |          signature with           |
   |          public_key)              |
   |                                   |
   |<------- registered --------------|
   |         {success: true}           |
   |                                   |
   |         Device is now online      |
   |         and can receive           |
   |         connection requests       |
```

### Registration

When a device connects to the signaling server, it registers its identity:

```json
{
    "type": "register",
    "uid": "a8f3c2b1e9d4",
    "public_key": "<base64-encoded DER public key>"
}
```

The server:

1. Computes `SHA-256(base64_decode(public_key))[:12]`
2. Verifies it matches the claimed `uid`
3. Stores the mapping: `uid → public_key`
4. If UID already registered with a *different* public key, reject (spoofing attempt)
5. **Issues a challenge** (see below) — registration is not complete until challenge is passed

### Challenge-Response

The signaling server **always** issues a challenge on connection. This proves the device possesses the private key corresponding to the claimed UID:

```json
// Server → Device
{
    "type": "challenge",
    "nonce": "<32 random bytes, base64>"
}

// Device → Server
{
    "type": "challenge_response",
    "signature": "<base64-encoded RSA signature of nonce>"
}
```

Signature algorithm: RSASSA-PKCS1-v1_5 with SHA-256.

```python
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

def sign_challenge(private_key, nonce: bytes) -> bytes:
    return private_key.sign(
        nonce,
        padding.PKCS1v15(),
        hashes.SHA256()
    )

def verify_challenge(public_key, nonce: bytes, signature: bytes) -> bool:
    try:
        public_key.verify(
            signature,
            nonce,
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        return True
    except Exception:
        return False
```

### Rate Limiting

The signaling server rate limits by IP to prevent UID enumeration:

- **Invalid UID attempts:** Max 10 per minute per IP
- **Connection attempts:** Max 60 per minute per IP
- **Registration attempts:** Max 10 per minute per IP

After hitting the limit, requests are rejected with:

```json
{
    "type": "error",
    "code": "rate_limited",
    "retry_after": 60
}
```

## URL Format

```
https://bitba.ng/<uid>
```

Example:

```
https://bitba.ng/a8f3c2b1e9d4
```

The signaling server at bitba.ng:
1. Serves the bootstrap HTML/JS
2. Handles WebSocket signaling at `wss://bitba.ng/ws/<uid>`
3. Relays messages between browsers and devices

## Security Considerations

### Collision Resistance

128 bits provides 340 undecillion (3.4 × 10³⁸) possible UIDs. Collision probability is effectively zero for any practical deployment.

### Key Compromise

If a private key is compromised:

1. Attacker can impersonate the device
2. Attacker can intercept connections meant for the device
3. Owner should `--regenerate` immediately

The old UID becomes a liability. There's no revocation mechanism — the only solution is abandoning the UID.

**ESP32 with DS Peripheral:** The encrypted key blob can be read from flash, but cannot be decrypted without the eFuse HMAC key (which is hardware-protected). An attacker with physical access could use the device as a signing oracle, but cannot extract the key to clone the identity elsewhere. Regeneration is possible — generate new RSA key, encrypt with same HMAC key, store new blob.

### Forward Secrecy

WebRTC's DTLS provides forward secrecy for the data channel. Even if the RSA key is later compromised, past sessions cannot be decrypted (assuming ECDHE key exchange was used, which is the default).

### Private Key Storage

**Python (desktop/server):** The private key is stored unencrypted on disk. This is a deliberate tradeoff:

- Encrypted key would require password on every startup
- For unattended devices (IoT, servers), this is impractical
- The threat model assumes the device's filesystem is trusted

For high-security applications, users can:
- Store identity on encrypted filesystem
- Use `--ephemeral` to avoid persistent keys entirely

**ESP32:** Use the Digital Signature Peripheral (see below). The private key is hardware-protected and cannot be read by software, even with physical access to the device.

## ESP32 Considerations

### Key Storage

On ESP32, use the **Digital Signature (DS) Peripheral** for hardware-protected signing. Available on ESP32-S2, ESP32-S3, ESP32-C3, ESP32-C6, and ESP32-P4.

How it works:
1. An **HMAC key** is burned into eFuse (one-time, hardware root of trust)
2. The RSA private key is **encrypted** using this HMAC key
3. The encrypted key blob is stored in **flash** (can be updated)
4. When signing, the DS peripheral decrypts the key internally and signs
5. Decrypted key material **never leaves the peripheral**

```c
#include "esp_ds.h"

// One-time setup: burn HMAC key to eFuse (factory provisioning)
// This only needs to happen once per device

// Per-identity setup: encrypt RSA key and store in flash
void provision_identity(const uint8_t *rsa_private_key) {
    esp_ds_data_t ds_data;
    
    // Encrypt RSA key parameters with eFuse HMAC key
    esp_ds_encrypt_params(&ds_data, rsa_private_key, ...);
    
    // Store encrypted blob in flash (this CAN be updated later)
    save_ds_params_to_flash(&ds_data);
}

// Runtime: sign challenge using DS peripheral
void sign_challenge(const uint8_t *nonce, size_t nonce_len, uint8_t *signature_out) {
    esp_ds_data_t ds_data;
    load_ds_params_from_flash(&ds_data);
    
    // Hardware signing - key decrypted inside peripheral, never exposed
    esp_ds_sign(nonce, nonce_len, &ds_data, signature_out);
}
```

Benefits:
- Private key cannot be extracted (encrypted at rest, decrypted only inside hardware)
- Signing is resistant to side-channel attacks
- **Keys can be regenerated** — only the HMAC key in eFuse is permanent
- Multiple identities possible (each encrypted with same HMAC key)

Note: The eFuse HMAC key is write-once. But RSA keys themselves live in flash and can be replaced.

### Key Generation / Provisioning

RSA key generation on ESP32 is slow (~2-5 seconds) due to prime finding. Generate once on first boot, then reuse. Regeneration is possible if needed.

```c
void provision_or_load_identity() {
    if (identity_exists_in_flash()) {
        // Load existing encrypted key blob
        load_ds_params();
        derive_uid_from_public_key();
    } else {
        printf("Generating identity (this takes a few seconds)...\n");
        
        // Generate RSA key pair
        generate_rsa_key(&public_key, &private_key);
        
        // Encrypt private key with eFuse HMAC key, store in flash
        encrypt_and_save_ds_params(&private_key);
        
        // Store public key separately (needed to derive UID)
        save_public_key_to_flash(&public_key);
        
        derive_uid_from_public_key();
    }
}

void regenerate_identity() {
    // Generate new RSA key pair
    generate_rsa_key(&public_key, &private_key);
    
    // Re-encrypt with same eFuse HMAC key, overwrite flash
    encrypt_and_save_ds_params(&private_key);
    save_public_key_to_flash(&public_key);
    
    // UID changes - old URL is now invalid
}
```

For development/prototyping without DS peripheral setup, fall back to encrypted NVS storage.

### Memory Constraints

RSA-2048 operations require significant RAM. On ESP32:
- Key generation: ~30KB heap
- Sign/verify: ~10KB heap

Ensure sufficient heap is available during crypto operations.

## Signaling Server: UID Validation

The signaling server validates that UIDs are 32 lowercase hex characters:

```python
import re

UID_PATTERN = re.compile(r'^[a-f0-9]{32}$')

def validate_uid(uid: str) -> bool:
    """Validate UID format (128-bit, lowercase hex)."""
    return bool(UID_PATTERN.match(uid))
```

## Algorithm Agility

The public key is transmitted during registration, not just the UID. This means we can support different key types in the future:

```json
{
    "type": "register",
    "uid": "a8f3c2b1e9d4f6a7b2c8e1d3f5a9b0c4",
    "public_key": "<DER-encoded key>",
    "key_type": "rsa-2048"  // Future: "ed25519", "p256", etc.
}
```

Ed25519 would be attractive for ESP32 — faster, smaller keys, smaller signatures. But RSA is more widely supported today.

## Summary

| Property | Value |
|----------|-------|
| Key algorithm | RSA-2048 |
| UID derivation | SHA-256(public_key_der)[0:16] |
| UID encoding | Lowercase hex |
| UID length | 32 characters (128 bits) |
| Storage location | `.bitbang/identity.pem` |
| Storage format | PEM (PKCS#8) |
| Challenge signature | RSASSA-PKCS1-v1_5 with SHA-256 |
