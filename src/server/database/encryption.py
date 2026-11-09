"""
Shared encryption key helper for pgcrypto-based encryption at rest.

Used by api_keys.py and oauth_tokens.py for pgp_sym_encrypt/decrypt.

The app-side helpers below encrypt values that must be decrypted
synchronously (provider construction, which cannot await a database round
trip), so they cannot use pgcrypto's database-side functions.
"""

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def get_encryption_key() -> str:
    """Return the symmetric encryption key for data stored at rest."""
    key = os.getenv("BYOK_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError(
            "BYOK_ENCRYPTION_KEY environment variable is not set. "
            "Required for encrypting sensitive data at rest."
        )
    return key


def encryption_configured() -> bool:
    """True when the at-rest encryption key is set — i.e. encrypted stores
    (vault secrets, BYOK keys, OAuth tokens) can hold data at all."""
    return bool(os.getenv("BYOK_ENCRYPTION_KEY"))


def _aead() -> AESGCM:
    # A stable 256-bit key derived from the deployment's at-rest key, so a
    # rotated BYOK_ENCRYPTION_KEY invalidates every app-encrypted token at
    # once instead of silently decrypting some with an old key.
    digest = hashlib.sha256(get_encryption_key().encode("utf-8")).digest()
    return AESGCM(digest)


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a short secret into a self-contained, URL-safe token.

    Format: base64url(nonce || AES-GCM ciphertext+tag). Used for values that
    are decrypted synchronously (a user's sandbox provider key at provider
    construction), where pgcrypto's database-side decryption cannot reach.
    """
    nonce = os.urandom(12)
    sealed = _aead().encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.urlsafe_b64encode(nonce + sealed).decode("ascii")


def decrypt_secret(token: str) -> str:
    """Decrypt a token produced by :func:`encrypt_secret`.

    Raises:
        ValueError: If the token is malformed or the key no longer matches
            (a rotated BYOK_ENCRYPTION_KEY).
    """
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii"))
    except Exception as exc:  # noqa: BLE001 - surfaced as a uniform error
        raise ValueError("invalid encrypted secret") from exc
    if len(raw) < 13:
        raise ValueError("invalid encrypted secret")
    try:
        plaintext = _aead().decrypt(raw[:12], raw[12:], None)
    except Exception as exc:  # noqa: BLE001 - InvalidTag and friends
        raise ValueError("cannot decrypt secret with the current key") from exc
    return plaintext.decode("utf-8")
