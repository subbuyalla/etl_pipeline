"""
Encrypt / decrypt connector secrets for storage in MySQL.

Ciphertext lives in `obs_secrets`. The Fernet master key stays outside the DB
(`SECRETS_MASTER_KEY` env) — never store the master key in MySQL.
"""

from __future__ import annotations

import base64
import hashlib
import os
from functools import lru_cache


class SecretsCryptoError(RuntimeError):
    pass


def _derive_fernet_key(raw: str) -> bytes:
    """Accept a Fernet key, or any passphrase (hashed into a url-safe 32-byte key)."""
    text = (raw or "").strip()
    if not text:
        raise SecretsCryptoError(
            "Missing SECRETS_MASTER_KEY. Generate one with: "
            'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )
    try:
        from cryptography.fernet import Fernet

        key_bytes = text.encode("utf-8")
        Fernet(key_bytes)
        return key_bytes
    except Exception:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest)


@lru_cache(maxsize=1)
def _fernet():
    from cryptography.fernet import Fernet

    return Fernet(_derive_fernet_key(os.getenv("SECRETS_MASTER_KEY") or ""))


def encrypt_secret(plaintext: str) -> str:
    """Return url-safe encrypted token (str) for DB storage."""
    if plaintext is None or str(plaintext) == "":
        raise SecretsCryptoError("Cannot encrypt empty secret")
    token = _fernet().encrypt(str(plaintext).encode("utf-8"))
    return token.decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt a token previously produced by encrypt_secret."""
    if not ciphertext:
        raise SecretsCryptoError("Cannot decrypt empty ciphertext")
    try:
        return _fernet().decrypt(str(ciphertext).encode("utf-8")).decode("utf-8")
    except Exception as exc:
        raise SecretsCryptoError(
            "Failed to decrypt secret (wrong SECRETS_MASTER_KEY or corrupt ciphertext)"
        ) from exc


def clear_crypto_cache() -> None:
    _fernet.cache_clear()
