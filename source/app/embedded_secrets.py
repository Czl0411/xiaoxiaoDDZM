from __future__ import annotations

import base64
import hashlib
import hmac
import os

try:
    from app._embedded_secret_payload import DEEPSEEK_SECRET_BLOB
except (ImportError, AttributeError):
    DEEPSEEK_SECRET_BLOB = ""


_KEY_PARTS = (
    b"DZMMBot::paid-interaction::",
    b"portable-read-only-secret::",
    b"2026-07",
)


def _key() -> bytes:
    return hashlib.sha256(b"".join(_KEY_PARTS)).digest()


def _xor_with_stream(value: bytes, nonce: bytes) -> bytes:
    output = bytearray()
    counter = 0
    while len(output) < len(value):
        output.extend(
            hashlib.sha256(_key() + nonce + counter.to_bytes(4, "big")).digest()
        )
        counter += 1
    return bytes(left ^ right for left, right in zip(value, output))


def encode_secret_for_embedding(value: str, *, nonce: bytes | None = None) -> str:
    raw = value.strip().encode("utf-8")
    if not raw:
        return ""
    nonce = nonce or os.urandom(16)
    encrypted = _xor_with_stream(raw, nonce)
    signature = hmac.new(_key(), nonce + encrypted, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(nonce + signature + encrypted).decode("ascii")


def decode_embedded_secret(blob: str) -> str:
    if not blob:
        return ""
    try:
        packed = base64.urlsafe_b64decode(blob.encode("ascii"))
        nonce, signature, encrypted = packed[:16], packed[16:48], packed[48:]
        expected = hmac.new(_key(), nonce + encrypted, hashlib.sha256).digest()
        if len(nonce) != 16 or not encrypted or not hmac.compare_digest(signature, expected):
            return ""
        return _xor_with_stream(encrypted, nonce).decode("utf-8").strip()
    except (ValueError, UnicodeDecodeError):
        return ""


def get_embedded_secret(name: str) -> str:
    if name != "deepseek_api_key":
        return ""
    return decode_embedded_secret(DEEPSEEK_SECRET_BLOB)


def embedded_secret_is_locked(name: str) -> bool:
    return bool(get_embedded_secret(name))
