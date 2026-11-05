"""Authentication, Password Hashing, and Signed Token Management for NUDHUJ AutoDeal OS SaaS."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from typing import Any, Dict, Optional

SECRET_KEY = os.getenv("AUTODEAL_SECRET_KEY", "nudhuj-autodeal-os-enterprise-secret-key-2026")


def hash_password(password: str, salt: Optional[str] = None) -> str:
    """Hash a password using PBKDF2-HMAC-SHA256 with a random salt."""
    if not salt:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        120_000,
    )
    return f"{salt}${dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a plaintext password against a stored salt$hash string."""
    if not stored_hash or "$" not in stored_hash:
        return False
    salt, _ = stored_hash.split("$", 1)
    expected = hash_password(password, salt=salt)
    return hmac.compare_digest(expected, stored_hash)


def create_access_token(
    user_id: int,
    org_id: int,
    email: str,
    role: str = "owner",
    expires_in_seconds: int = 86400 * 14,
) -> str:
    """Create an HMAC-SHA256 signed session token (JWT-compatible structure)."""
    payload = {
        "sub": user_id,
        "org_id": org_id,
        "email": email,
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time()) + expires_in_seconds,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    b64_payload = base64.urlsafe_b64encode(payload_bytes).decode("ascii").rstrip("=")
    sig = hmac.new(
        SECRET_KEY.encode("utf-8"),
        b64_payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    b64_sig = base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")
    return f"{b64_payload}.{b64_sig}"


def verify_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify signature and expiration of an access token, returning payload or None."""
    if not token or "." not in token:
        return None
    try:
        b64_payload, b64_sig = token.split(".", 1)
        expected_sig = hmac.new(
            SECRET_KEY.encode("utf-8"),
            b64_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        expected_b64_sig = base64.urlsafe_b64encode(expected_sig).decode("ascii").rstrip("=")
        if not hmac.compare_digest(b64_sig, expected_b64_sig):
            return None

        padding = "=" * (-len(b64_payload) % 4)
        payload_bytes = base64.urlsafe_b64decode(b64_payload + padding)
        payload = json.loads(payload_bytes.decode("utf-8"))
        if payload.get("exp", 0) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def slugify_org(name: str) -> str:
    """Create a URL-safe slug for an organization or proposal."""
    cleaned = re.sub(r"[^a-zA-Z0-9\u0600-\u06FF\s-]", "", name).strip().lower()
    cleaned = re.sub(r"[\s_]+", "-", cleaned)
    if not cleaned or not re.search(r"[a-z0-9]", cleaned):
        cleaned = f"org-{secrets.token_hex(3)}"
    return f"{cleaned[:32]}-{secrets.token_hex(2)}"
