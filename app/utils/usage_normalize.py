"""Turn a raw browser path into page / route / sector grains."""

from __future__ import annotations

import re
from urllib.parse import unquote, urlparse

MAX_PATH = 512

_TICKET_ID = re.compile(r"^[A-Za-z]{2,10}-\d+$")
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_HEX = re.compile(r"^[0-9a-fA-F]{8,}$")
_NUMERIC = re.compile(r"^\d+$")
_HASH_PREFIX = re.compile(r"^[0-9a-fA-F]{6,}$")


def _collapse_segment(segment: str) -> str:
    if not segment:
        return segment
    if _TICKET_ID.match(segment) or _UUID.match(segment) or _NUMERIC.match(segment):
        return ":id"
    if _HEX.match(segment) and len(segment) >= 8:
        return ":id"
    if _HASH_PREFIX.match(segment) and len(segment) >= 16:
        return ":id"
    return segment


def normalize_path(raw: str | None) -> dict[str, str]:
    """Return page, route, and sector for a URL or path the beacon sent.

    Query strings and fragments are dropped. Trailing slashes are stripped except
    for the site root. Id-like segments become ``:id`` on the route only.
    """
    text = unquote(str(raw or "")).strip()
    if not text:
        return {"path": "/", "route": "/", "sector": "(root)"}

    if "://" in text:
        parsed = urlparse(text)
        text = parsed.path or "/"
    else:
        if "?" in text:
            text = text.split("?", 1)[0]
        if "#" in text:
            text = text.split("#", 1)[0]

    if not text.startswith("/"):
        text = "/" + text
    if len(text) > 1:
        text = text.rstrip("/")
    if len(text) > MAX_PATH:
        text = text[:MAX_PATH]

    segments = [part for part in text.split("/") if part]
    if not segments:
        return {"path": "/", "route": "/", "sector": "(root)"}

    collapsed = [_collapse_segment(part) for part in segments]
    route = "/" + "/".join(collapsed)
    page = text
    sector = segments[0]
    return {"path": page, "route": route, "sector": sector}


def normalize_referrer(raw: str | None, *, page_host: str | None = None) -> str | None:
    """Keep an in-app referrer path; drop off-site URLs down to path-only if same host."""
    text = str(raw or "").strip()
    if not text:
        return None
    if "://" in text:
        parsed = urlparse(text)
        host = (parsed.netloc or "").split(":")[0].lower()
        if page_host and host and host != page_host.lower():
            return None
        text = parsed.path or "/"
    grains = normalize_path(text)
    return grains["path"]
