"""
Symmetric encryption helpers for protecting integration secrets stored in system_settings.

Uses Fernet (AES-128-CBC + HMAC-SHA256) with a deterministic 32-byte key derived
via SHA-256 from ``settings.APP_SECRET_KEY``. Encrypted payloads are prefixed with
``enc:v1:`` so legacy plaintext rows remain readable and can be migrated seamlessly.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from backend.app.config import settings

logger = logging.getLogger(__name__)

ENC_PREFIX = "enc:v1:"
SECRET_MASK = "********"


def _get_fernet() -> Fernet:
    """Build a Fernet instance bound to the active APP_SECRET_KEY."""
    secret_material = (settings.APP_SECRET_KEY or "").encode("utf-8")
    digest = hashlib.sha256(b"sdgen-secret-v1:" + secret_material).digest()
    fernet_key = base64.urlsafe_b64encode(digest)
    return Fernet(fernet_key)


def is_encrypted_secret(value: Optional[str]) -> bool:
    """Return True if value already carries the encrypted payload prefix."""
    return isinstance(value, str) and value.startswith(ENC_PREFIX)


def encrypt_secret(plaintext: Optional[str]) -> str:
    """
    Encrypt a plaintext secret for database storage.

    Empty strings return ``""``. Already encrypted ``enc:v1:`` values are
    returned unchanged to avoid double encryption.
    """
    if not plaintext:
        return ""
    raw = str(plaintext)
    if not raw.strip():
        return ""
    if is_encrypted_secret(raw):
        return raw
    token = _get_fernet().encrypt(raw.encode("utf-8")).decode("ascii")
    return f"{ENC_PREFIX}{token}"


def decrypt_secret(stored_value: Optional[str]) -> str:
    """
    Decrypt a stored database secret value.

    Values without the ``enc:v1:`` prefix are treated as legacy plaintext and
    returned directly. Invalid/corrupted tokens log a warning and return ``""``.
    """
    if not stored_value:
        return ""
    raw = str(stored_value)
    if not is_encrypted_secret(raw):
        return raw
    token = raw[len(ENC_PREFIX):].encode("ascii")
    try:
        return _get_fernet().decrypt(token).decode("utf-8")
    except (InvalidToken, ValueError, Exception) as exc:
        logger.warning("Failed to decrypt stored secret (%s); falling back to empty", type(exc).__name__)
        return ""


def mask_secret(value: Optional[str]) -> str:
    """Return masked placeholder for UI/API responses without leaking characters."""
    if value is None:
        return ""
    raw = str(value).strip()
    if not raw:
        return ""
    if is_encrypted_secret(raw):
        raw = decrypt_secret(raw).strip()
    return SECRET_MASK if raw else ""
