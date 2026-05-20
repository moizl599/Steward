"""Symmetric encryption for stored Kubecost auth tokens.

Uses Fernet (AES-128-CBC + HMAC) keyed by SECRET_KEY.

Generate a key with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

import base64
import hashlib

from cryptography.fernet import Fernet

from app.config import get_settings


def _get_cipher() -> Fernet:
    """Derive a Fernet key from SECRET_KEY.

    If SECRET_KEY is already a 32-byte urlsafe-base64 value, use it directly.
    Otherwise hash it to 32 bytes and base64-encode (lets users set any string).
    """
    raw = get_settings().secret_key.encode()
    try:
        # Validate as a real Fernet key
        Fernet(raw)
        return Fernet(raw)
    except Exception:
        digest = hashlib.sha256(raw).digest()
        derived = base64.urlsafe_b64encode(digest)
        return Fernet(derived)


def encrypt(plaintext: str) -> str:
    return _get_cipher().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _get_cipher().decrypt(ciphertext.encode()).decode()
