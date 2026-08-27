"""
Product usage: browser beacon ingest plus the Usage dashboard.

The write path is deliberately not ``@protected``: the site key lives in the JSON body
because ``sendBeacon`` cannot set Authorization, and a query token would land in logs.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from flask import Blueprint, Response, abort, render_template, request, send_from_directory

from ..utils import ip_lookup, usage_store
from ..utils.app import limiter
from ..utils.features import FEATURE_USAGE, is_feature_enabled
from ..utils.models import UsageToken, User
from ..utils.path import path as app_path
from ..utils.security import protected
from ..utils.usage_auth import verify_usage_token
from ..utils.usage_normalize import normalize_path, normalize_referrer
from .metrics import ingest_base_url

usage_bp = Blueprint("usage", __name__)

MAX_BODY_BYTES = 64 * 1024
MAX_BATCH = 50
ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

RANGES: dict[str, tuple[int, int]] = {
    "24h": (24 * 3600, 900),
    "7d": (7 * 24 * 3600, 3600),
    "30d": (30 * 24 * 3600, 7200),
}
RANGE_LABELS = {
    "24h": "Last 24 hours",
    "7d": "Last 7 days",
    "30d": "Last 30 days",
}
DEFAULT_RANGE = "7d"


def _feature_guard():
    if not is_feature_enabled(FEATURE_USAGE):
        abort(404)


def _cors(response: Response) -> Response:
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Max-Age"] = "86400"
    return response


def _parse_body() -> dict[str, Any] | None:
    raw = request.get_data(cache=False) or b""
    if len(raw) > MAX_BODY_BYTES:
        return None
    if not raw.strip():
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _valid_id(value: Any) -> str | None:
    text = str(value or "").strip()
    return text if ID_RE.match(text) else None


def _ingest_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    batch = payload.get("e")
    if batch is None:
        batch = [payload]
    if not isinstance(batch, list):
        return []
    return batch[:MAX_BATCH]


def _visitor_limit_key() -> str:
    return ip_lookup.visitor_ip(request.headers, request.remote_addr) or "unknown"


def _place_for_request() -> dict[str, Any]:
    empty = {"country": None, "region": None, "city": None}
    try:
        place = ip_lookup.resolve_geo(request.headers, request.remote_addr)
    except Exception:
        return empty
    if not isinstance(place, dict):
        return empty
    return {
        "country": place.get("country"),
        "region": place.get("region"),
        "city": place.get("city"),
    }


@usage_bp.route("/ingest/usage", methods=["OPTIONS"])
def ingest_options():
    _feature_guard()
    return _cors(Response(status=204))


@usage_bp.route("/ingest/usage", methods=["POST"])
@limiter.limit("60 per minute", key_func=_visitor_limit_key)
def ingest_usage():
    _feature_guard()

    if request.args.get("k") or request.args.get("key"):
        return _cors(Response("query token not allowed", status=401))

    payload = _parse_body()
    if payload is None:
        return _cors(Response("invalid body", status=400))

    key = payload.get("k") or payload.get("key")
    if not verify_usage_token(str(key) if key is not None else None):
        return _cors(Response("unauthorized", status=401))

    visitor = _valid_id(payload.get("vid") or payload.get("visitor"))
    session = _valid_id(payload.get("sid") or payload.get("session"))
    if not visitor or not session:
        return _cors(Response("invalid ids", status=400))

    place = _place_for_request()

    rows: list[dict[str, Any]] = []
    for item in _ingest_events(payload):
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "pageview").strip().lower()
        if kind not in ("pageview", "event"):
            continue
        grains = normalize_path(item.get("path") or payload.get("path") or "/")
        name = None
        if kind == "event":
            candidate = str(item.get("name") or "").strip()
            if not NAME_RE.match(candidate):
                continue
            name = candidate
        referrer = normalize_referrer(item.get("ref") or item.get("referrer"))
        rows.append(
            {
                "ts": item.get("ts") or payload.get("t") or int(time.time() * 1000),
                "visitor": visitor,
                "session": session,
                "kind": kind,
                "path": grains["path"],
                "route": grains["route"],
                "sector": grains["sector"],
                "referrer_path": referrer,
                "name": name,
                "country": place.get("country"),
                "region": place.get("region"),
                "city": place.get("city"),
            }
        )

    if rows:
        usage_store.write_events(rows)
    return _cors(Response("ok", status=204))


@usage_bp.route("/usage.js")
def usage_script():
    _feature_guard()
    directory = str(app_path("static", "js"))
    response = send_from_directory(directory, "usage-beacon.js")
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Cache-Control"] = "public, max-age=3600"
    response.headers["Content-Type"] = "application/javascript; charset=utf-8"
    return response


def _format_duration_ms(value: int | None) -> str | None:
    if value is None:
        return None
    seconds = max(0, int(value) // 1000)
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        rem = seconds % 60
        return f"{minutes}m {rem}s" if rem else f"{minutes}m"
    hours = minutes // 60
    rem_m = minutes % 60
    return f"{hours}h {rem_m}m" if rem_m else f"{hours}h"


def _flag(iso: str) -> str:
    text = (iso or "").strip().upper()
    if len(text) != 2 or not text.isalpha():
        return ""
    return "".join(chr(0x1F1E6 + ord(c) - 65) for c in text)


def _enrich_bars(rows: list[dict[str, Any]], total: int) -> list[dict[str, Any]]:
    peak = max((int(row["count"]) for row in rows), default=0) or 1
    denom = total or 1
    out = []
    for row in rows:
        item = dict(row)
        count = int(row["count"])
        item["bar"] = round(100.0 * count / peak, 1)
        item["share"] = round(100.0 * count / denom, 1)
        out.append(item)
    return out


def _merge_gates(
    entries: list[dict[str, Any]], exits: list[dict[str, Any]], *, limit: int = 10
) -> list[dict[str, Any]]:
    """Align start and stop counts on the same route so the two columns are comparable."""
    by_label: dict[str, dict[str, Any]] = {}
    for row in entries:
        label = str(row.get("label") or "/")
        by_label[label] = {"label": label, "entries": int(row.get("count") or 0), "exits": 0}
    for row in exits:
        label = str(row.get("label") or "/")
        item = by_label.setdefault(label, {"label": label, "entries": 0, "exits": 0})
        item["exits"] = int(row.get("count") or 0)
    rows = sorted(
        by_label.values(),
        key=lambda row: row["entries"] + row["exits"],
        reverse=True,
    )[:limit]
    peak = max((max(row["entries"], row["exits"]) for row in rows), default=1) or 1
    for row in rows:
        row["entry_bar"] = round(100.0 * row["entries"] / peak, 1)
        row["exit_bar"] = round(100.0 * row["exits"] / peak, 1)
    return rows


@usage_bp.route("/usage")
@protected
def usage_view(user: User):
    _feature_guard()
    range_key = (request.args.get("range") or DEFAULT_RANGE).strip()
    if range_key not in RANGES:
        range_key = DEFAULT_RANGE
    span, step = RANGES[range_key]
    end_ms = int(time.time() * 1000) + 1
    start_ms = end_ms - span * 1000
    data = usage_store.dashboard(start_ms, end_ms, step_ms=step * 1000)

    bounce = data.get("bounce_rate")
    bounce_pct = round(bounce * 100) if bounce is not None else None
    pps = data.get("pages_per_session")
    geo_status = ip_lookup.sidecar_status()
    has_events = bool(data["pageviews"] or data["events"])

    view_total = int(data["pageviews"] or 0)
    session_total = int(data["sessions"] or 0)
    for key in (
        "sectors",
        "pages",
        "routes",
        "entries",
        "exits",
        "events",
        "countries",
        "cities",
    ):
        denom = session_total if key in ("entries", "exits") else view_total
        data[key] = _enrich_bars(data.get(key) or [], denom)
    for row in data["countries"]:
        row["flag"] = _flag(str(row.get("label") or ""))
    for row in data["cities"]:
        city = str(row.get("label") or "")
        country = str(row.get("country") or "")
        row["display"] = f"{city}, {country}" if country else city
    data["gates"] = _merge_gates(data.get("entries") or [], data.get("exits") or [])
    journey_peak = max((int(j["count"]) for j in data["journeys"]), default=1) or 1
    for row in data["journeys"]:
        row["steps"] = [
            part.strip() for part in str(row.get("label") or "").split("→") if part.strip()
        ]
        row["bar"] = round(100.0 * int(row["count"]) / journey_peak, 1)

    snippet_url = f"{ingest_base_url()}/usage.js"
    token_row = UsageToken.get_or_none()
    chart_payload = {
        "views": data.get("traffic") or [],
        "users": data.get("traffic_users") or [],
        "sectors": data.get("sectors") or [],
        "pages": data.get("pages") or [],
        "transitions": data.get("transitions") or [],
        "entries": data.get("entries") or [],
        "exits": data.get("exits") or [],
        "countries": data.get("countries") or [],
    }

    return render_template(
        "usage.jinja2",
        user=user,
        page="usage",
        range_key=range_key,
        ranges=list(RANGES),
        range_labels=RANGE_LABELS,
        data=data,
        has_events=has_events,
        bounce_display=f"{bounce_pct}%" if bounce_pct is not None else None,
        bounce_pct=bounce_pct if bounce_pct is not None else 0,
        avg_session_display=_format_duration_ms(data.get("avg_session_ms")),
        pages_per_session_display=f"{pps:.1f}" if pps else None,
        chart_payload=chart_payload,
        geo_status=geo_status,
        snippet_url=snippet_url,
        has_site_key=bool(token_row),
        settings_url="/settings/usage",
    )
