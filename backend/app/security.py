"""Password hashing, signed session tokens and encryption of LinkedIn cookies.

Uses only the standard library plus `cryptography`, so there is nothing to
compile on Railway and no password-hashing backend to go stale.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1


# --------------------------------------------------------------------------
# passwords
# --------------------------------------------------------------------------
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32
    )
    return "scrypt${}${}".format(salt.hex(), digest.hex())


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, salt_hex, digest_hex = stored.split("$")
    except (ValueError, AttributeError):
        return False
    if algorithm != "scrypt":
        return False
    digest = hashlib.scrypt(
        password.encode(),
        salt=bytes.fromhex(salt_hex),
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=32,
    )
    return hmac.compare_digest(digest.hex(), digest_hex)


# --------------------------------------------------------------------------
# session tokens (HMAC signed, no external JWT dependency)
# --------------------------------------------------------------------------
def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _secret() -> bytes:
    return get_settings().app_secret.encode()


def create_session_token(user_id: int, expires_in_seconds: int) -> str:
    payload = {"uid": user_id, "exp": int(time.time()) + expires_in_seconds}
    body = _b64encode(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(_secret(), body.encode(), hashlib.sha256).digest()
    return body + "." + _b64encode(signature)


def read_session_token(token: str) -> int | None:
    """Returns the user id, or None when the token is invalid or expired."""
    try:
        body, signature = token.split(".")
    except (ValueError, AttributeError):
        return None
    expected = hmac.new(_secret(), body.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(_b64decode(signature), expected):
        return None
    try:
        payload = json.loads(_b64decode(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if int(payload.get("exp", 0)) < time.time():
        return None
    return int(payload["uid"])


# --------------------------------------------------------------------------
# encryption at rest for the LinkedIn cookies
# --------------------------------------------------------------------------
def _fernet() -> Fernet:
    key = hashlib.sha256(get_settings().app_secret.encode() + b"cookie-encryption").digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_json(data: dict) -> str:
    return _fernet().encrypt(json.dumps(data).encode()).decode()


def decrypt_json(blob: str) -> dict:
    try:
        return json.loads(_fernet().decrypt(blob.encode()).decode())
    except (InvalidToken, ValueError):
        # Happens when APP_SECRET changed after the tokens were saved.
        return {}
