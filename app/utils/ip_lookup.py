"""Look up visitor country/region/city via the broke-ip sidecar. Never persist the IP."""

from __future__ import annotations

import ipaddress
import logging
import os
from collections import OrderedDict
from typing import Any

import requests

logger = logging.getLogger(__name__)

CACHE_SIZE = 2048
TIMEOUT_SECONDS = 0.1
_cache: OrderedDict[str, dict[str, str | None]] = OrderedDict()


def ip_url() -> str:
    return (os.environ.get("IP_URL") or "").strip().rstrip("/")


def ip_token() -> str:
    return (os.environ.get("IP_TOKEN") or "").strip()


def trust_proxy() -> bool:
    return os.environ.get("BROKE_TRUST_PROXY", "0").lower() in ("1", "true", "yes")


def visitor_ip(headers: Any, remote_addr: str | None) -> str | None:
    """Best-effort client IP. Header spoofing is ignored unless BROKE_TRUST_PROXY=1."""
    cf = (headers.get("CF-Connecting-IP") or "").strip()
    if cf:
        return cf.split(",")[0].strip() or None
    if trust_proxy():
        forwarded = (headers.get("X-Forwarded-For") or "").strip()
        if forwarded:
            return forwarded.split(",")[0].strip() or None
        real_ip = (headers.get("X-Real-IP") or "").strip()
        if real_ip:
            return real_ip
    addr = (remote_addr or "").strip()
    return addr or None


def header_country(headers: Any) -> str | None:
    for name in ("CF-IPCountry", "CloudFront-Viewer-Country", "X-Country-Code"):
        value = (headers.get(name) or "").strip().upper()
        if value and value != "XX" and len(value) <= 8:
            return value
    return None


def _cache_get(ip: str) -> dict[str, str | None] | None:
    place = _cache.get(ip)
    if place is None:
        return None
    _cache.move_to_end(ip)
    return place


def _cache_put(ip: str, place: dict[str, str | None]) -> None:
    if ip in _cache:
        _cache.move_to_end(ip)
        _cache[ip] = place
        return
    _cache[ip] = place
    if len(_cache) > CACHE_SIZE:
        _cache.popitem(last=False)


def _skip_lookup(ip: str) -> bool:
    """Sidecar also rejects these; skip the hop so a docker NAT burst stays quiet."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return bool(
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def lookup_place(ip: str | None) -> dict[str, str | None]:
    """Call the sidecar. Failures become nulls — ingest must not depend on geo."""
    empty = {"country": None, "region": None, "city": None}
    if not ip or not ip_url() or _skip_lookup(ip):
        return empty
    cached = _cache_get(ip)
    if cached is not None:
        return cached

    headers = {}
    token = ip_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = requests.get(
            f"{ip_url()}/lookup",
            params={"ip": ip},
            headers=headers,
            timeout=TIMEOUT_SECONDS,
        )
        if response.status_code != 200:
            return empty
        payload = response.json()
        place = {
            "country": payload.get("country") or None,
            "region": payload.get("region") or None,
            "city": payload.get("city") or None,
        }
        _cache_put(ip, place)
        return place
    except Exception:
        logger.debug("IP lookup failed", exc_info=True)
        return empty


def sidecar_status() -> dict[str, Any] | None:
    """Used by settings. Never raises."""
    if not ip_url():
        return None
    headers = {}
    token = ip_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = requests.get(f"{ip_url()}/status", headers=headers, timeout=1.0)
        if response.status_code != 200:
            return {"ok": False, "error": f"HTTP {response.status_code}"}
        data = response.json()
        if isinstance(data, dict):
            return data
        return {"ok": False}
    except Exception as exc:
        return {"ok": False, "error": str(exc.__class__.__name__)}


def resolve_geo(headers: Any, remote_addr: str | None) -> dict[str, str | None]:
    """Country from a trusted CDN header when present; city from the sidecar."""
    country = header_country(headers)
    ip = visitor_ip(headers, remote_addr)
    place = lookup_place(ip)
    if country and not place.get("country"):
        place = {**place, "country": country}
    elif country:
        place = {**place, "country": country}
    return place
