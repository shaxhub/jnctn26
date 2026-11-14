"""Signed, fixed-price quotes.

A quote freezes prices and quantities until `expires_at = min(price validTo, earliest order cutoff)`.
It is signed as a compact JWS (RFC 7515) with Ed25519 (alg "EdDSA", RFC 8037), so anyone with the
public key (served at /.well-known/jwks.json) can verify it and the gateway can detect tampering when
the quote comes back in place_order.

TODO(A): key rotation (kid per key), store the private key in a KMS, add `aud`/`iss` claims.
"""
from __future__ import annotations

import base64
import json
import re
import threading
from datetime import datetime
from functools import lru_cache

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .config import TZ, settings

KID = "gateway-quote-key-1"
_B64URL_RE = re.compile(r"[A-Za-z0-9_-]+")
_key_lock = threading.Lock()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    if not s or len(s) % 4 == 1 or not _B64URL_RE.fullmatch(s):
        raise ValueError("invalid base64url")
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


@lru_cache(maxsize=1)
def private_key() -> Ed25519PrivateKey:
    path = settings.signing_key_path
    with _key_lock:
        if path.exists():
            return serialization.load_pem_private_key(path.read_bytes(), password=None)
        key = Ed25519PrivateKey.generate()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
        path.chmod(0o600)
        return key


def public_key() -> Ed25519PublicKey:
    return private_key().public_key()


def jwks() -> dict:
    raw = public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return {"keys": [{"kty": "OKP", "crv": "Ed25519", "x": _b64(raw), "kid": KID, "alg": "EdDSA", "use": "sig"}]}


def sign(payload: dict) -> str:
    header = {"alg": "EdDSA", "typ": "JWT", "kid": KID}
    signing_input = _b64(json.dumps(header, separators=(",", ":")).encode()) + "." + \
        _b64(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode())
    return signing_input + "." + _b64(private_key().sign(signing_input.encode()))


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=TZ)


def verify(jws: str, key: Ed25519PublicKey | None = None) -> dict:
    """Return the payload if the signature is valid; raise ValueError otherwise."""
    try:
        parts = jws.split(".")
        if len(parts) != 3:
            raise ValueError("malformed JWS")
        h, p, s = parts
        hdr = json.loads(_unb64(h))
        if not isinstance(hdr, dict) or hdr.get("alg") != "EdDSA" or hdr.get("kid") != KID:
            raise ValueError("unsupported or mismatched JWS header")
        (key or public_key()).verify(_unb64(s), f"{h}.{p}".encode())
        payload = json.loads(_unb64(p))
        if not isinstance(payload, dict):
            raise ValueError("JWS payload must be a JSON object")
        return payload
    except Exception as e:  # cryptography raises InvalidSignature; malformed input raises others
        raise ValueError(f"invalid quote signature: {e.__class__.__name__}") from e


def expiry(price_valid_to: list[datetime | None], cutoffs: list[datetime | None], fallback: datetime) -> datetime:
    valid_prices = [_aware(t) for t in price_valid_to if t is not None]
    valid_cutoffs = [_aware(t) for t in cutoffs if t is not None]
    fb = _aware(fallback)
    if valid_cutoffs:
        return min(valid_prices + valid_cutoffs)
    return min(valid_prices + [fb])
