"""Bearer authentication for the Telegraf metrics ingest (no session, no CSRF)."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time

from flask import request

from .models import MetricsToken

# Telegraf's outputs.influxdb_v2 sends "Authorization: Token <t>". Curl users and the
# v1 output reach for "Bearer", so both prefixes are honoured.
_PREFIXES = ("token ", "bearer ")


def query_token_allowed() -> bool:
    """Whether a token may arrive as the InfluxDB v1 ``?p=`` query parameter.

    Off by default: a query string lands in access logs on every proxy it passes, which
    turns each write into a leak of a long-lived credential. Telegraf never needs it —
    the v2 output sends a header and the v1 output sends basic auth — so this exists only
    for legacy clients that cannot do either.
    """
    return os.environ.get("METRICS_ALLOW_QUERY_TOKEN", "0").lower() in ("1", "true", "yes")


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def extract_token() -> str | None:
    """Pull the raw token out of the Authorization header or the v1 query parameters."""
    header = (request.headers.get("Authorization") or "").strip()
    lowered = header.lower()
    for prefix in _PREFIXES:
        if lowered.startswith(prefix):
            candidate = header[len(prefix) :].strip()
            return candidate or None

    # InfluxDB v1 clients authenticate with u/p query params or basic auth instead.
    if query_token_allowed():
        param = (request.args.get("p") or "").strip()
        if param:
            return param
    if request.authorization and request.authorization.password:
        return request.authorization.password.strip() or None
    return None


def verify_metrics_token() -> MetricsToken | None:
    """Return the matching token row, touching last_used, or None when unauthenticated."""
    raw = extract_token()
    if not raw:
        return None

    token_hash = hash_token(raw)
    try:
        row = MetricsToken.get_or_none(MetricsToken.token_hash == token_hash)
    except Exception:
        return None
    if not row:
        return None
    if not hmac.compare_digest(str(row.token_hash), token_hash):
        return None

    now = int(time.time())
    # last_used only drives a "last seen" column, so a coarse update keeps writes off
    # the hot path of an agent reporting every few seconds.
    if not row.last_used or now - int(row.last_used) > 60:
        try:
            row.last_used = now
            row.save()
        except Exception:
            pass
    return row
