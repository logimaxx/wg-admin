from __future__ import annotations

import base64
import secrets

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _raw(key: str) -> bytes:
    data = base64.b64decode(key)
    if len(data) != 32:
        raise ValueError("WireGuard keys must decode to 32 bytes")
    return data


def genkey() -> str:
    private = X25519PrivateKey.generate()
    raw = private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    return _b64(raw)


def pubkey(private_key: str) -> str:
    private = X25519PrivateKey.from_private_bytes(_raw(private_key))
    raw = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return _b64(raw)


def genpsk() -> str:
    return _b64(secrets.token_bytes(32))
