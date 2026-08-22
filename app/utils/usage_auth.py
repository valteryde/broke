"""Site-key authentication for the usage beacon (no session, no CSRF)."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time

from .models import UsageToken


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def verify_usage_token(raw: str | None) -> UsageToken | None:
    """Return the matching token row, touching last_used, or None."""
    offered = (raw or "").strip()
    if not offered:
        return None
    token_hash = hash_token(offered)
    try:
        row = UsageToken.get_or_none(UsageToken.token_hash == token_hash)
    except Exception:
        return None
    if not row:
        return None
    stored = str(row.token_hash or "")
    if not stored or not hmac.compare_digest(stored, token_hash):
        return None

    now = int(time.time())
    if not row.last_used or now - int(row.last_used) > 60:
        try:
            row.last_used = now
            row.save()
        except Exception:
            pass
    return row
