"""License key generation and validation for the Self-Hosted plan.

Key format: VSCR-{base64url_payload}-{hmac24}

The payload is a JSON object signed with HMAC-SHA256. Validation is fully
offline — no database round-trip required. The DB check (max activations,
revocation) happens separately in the routes layer.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Optional

from app.config import LICENSE_SIGNING_KEY


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _sign(payload_b64: str) -> str:
    return hmac.new(
        LICENSE_SIGNING_KEY.encode(),
        payload_b64.encode(),
        hashlib.sha256,
    ).hexdigest()[:24]


def generate_license_key(
    issued_to: str,
    payment_type: str = "one_time",  # one_time | monthly
    expires_at: Optional[int] = None,  # Unix timestamp or None = lifetime
) -> str:
    """Generate a signed license key. Call server-side only."""
    payload = {
        "iss": issued_to,
        "ed": "self_hosted",
        "pt": payment_type,
        "iat": int(time.time()),
        "exp": expires_at,
        "nonce": secrets.token_hex(8),
    }
    payload_b64 = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _sign(payload_b64)
    return f"VSCR-{payload_b64}-{sig}"


def validate_license_key(raw_key: str) -> dict:
    """Verify signature and expiry. Returns decoded payload or raises ValueError."""
    raw_key = raw_key.strip()
    parts = raw_key.split("-", 2)
    if len(parts) != 3 or parts[0] != "VSCR":
        raise ValueError("Invalid key format")

    _, payload_b64, provided_sig = parts
    expected_sig = _sign(payload_b64)

    if not hmac.compare_digest(provided_sig, expected_sig):
        raise ValueError("Invalid key signature")

    try:
        padding = "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + padding))
    except Exception:
        raise ValueError("Corrupted key payload")

    if payload.get("exp") and payload["exp"] < time.time():
        raise ValueError("License key has expired")

    return payload


def key_hash(raw_key: str) -> str:
    """SHA-256 hash of the raw key — used as the DB lookup identifier."""
    return hashlib.sha256(raw_key.strip().encode()).hexdigest()
