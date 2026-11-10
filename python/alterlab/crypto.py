"""Client-side cookie encryption for zero-knowledge session storage.

Encrypts cookies locally before sending to the AlterLab API. The server
never sees plaintext cookie values — only encrypted blobs.

Requires the `cryptography` package (already an AlterLab SDK dependency).

Usage:
    from alterlab.crypto import encrypt_cookies

    encrypted = encrypt_cookies(
        cookies={"session_id": "abc123", "token": "xyz789"},
        server_public_key_pem=public_key_pem,
    )
    # encrypted.encrypted_cookies, encrypted.wrapped_key, encrypted.cookie_names
"""

import base64
import json
import os
from dataclasses import dataclass
from typing import Dict, List

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


@dataclass
class EncryptedCookiePayload:
    """Result of client-side cookie encryption."""

    encrypted_cookies: str
    """Base64(IV) + '.' + Base64(ciphertext) — AES-256-GCM encrypted."""

    wrapped_key: str
    """Base64 RSA-OAEP wrapped AES-256 session key."""

    cookie_names: List[str]
    """Plaintext cookie names (no values) for server-side UI display."""


def encrypt_cookies(
    cookies: Dict[str, str],
    server_public_key_pem: str,
) -> EncryptedCookiePayload:
    """Encrypt cookies client-side for zero-knowledge storage.

    Generates an ephemeral AES-256-GCM key, encrypts the cookie dict,
    then wraps the AES key with the server's RSA-OAEP public key.

    Args:
        cookies: Cookie name-value mapping to encrypt.
        server_public_key_pem: PEM-encoded RSA public key from the server
            (obtained via GET /api/v1/sessions/public-key).

    Returns:
        EncryptedCookiePayload ready to pass to the sessions API.

    Raises:
        ValueError: If cookies is empty or public key is invalid.
        cryptography exceptions: If encryption fails.
    """
    if not cookies:
        raise ValueError("cookies must be a non-empty dict")

    # Generate ephemeral AES-256-GCM key (32 bytes = 256 bits)
    session_key = AESGCM.generate_key(bit_length=256)

    # Encrypt cookie JSON with AES-256-GCM
    nonce = os.urandom(12)  # 96-bit nonce for GCM
    plaintext = json.dumps(cookies, separators=(",", ":")).encode("utf-8")
    ciphertext = AESGCM(session_key).encrypt(nonce, plaintext, None)

    # Load the server's RSA public key
    public_key = serialization.load_pem_public_key(
        server_public_key_pem.encode("utf-8")
    )

    # Wrap the AES session key with RSA-OAEP (SHA-256)
    wrapped_key = public_key.encrypt(
        session_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )

    # Format: base64(nonce).base64(ciphertext)
    encrypted_cookies = (
        base64.b64encode(nonce).decode("ascii")
        + "."
        + base64.b64encode(ciphertext).decode("ascii")
    )

    return EncryptedCookiePayload(
        encrypted_cookies=encrypted_cookies,
        wrapped_key=base64.b64encode(wrapped_key).decode("ascii"),
        cookie_names=list(cookies.keys()),
    )
