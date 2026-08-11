"""
Telegraf metrics: InfluxDB-compatible ingest plus the Servers pages.

Servers point ``outputs.influxdb_v2`` (or the v1 ``outputs.influxdb``) at Broke. The
write endpoints are deliberately not ``@protected``: they take a bearer token instead of
a session, which is also what keeps them out of CSRF checking.
"""

from __future__ import annotations

import json
import os
import re
import time
import zlib
from datetime import datetime, timezone
from typing import Any

from flask import Blueprint, abort, jsonify, render_template, request

from ..utils.features import FEATURE_METRICS, is_feature_enabled
from ..utils.lineprotocol import LineProtocolError, parse
from ..utils.metrics_auth import verify_metrics_token
from ..utils.models import MetricsChart, MetricsHost, User, database
from ..utils.security import protected
from ..utils import metrics_store

metrics_bp = Blueprint("metrics", __name__)

INFLUXDB_VERSION = "2.7.0"
MAX_BODY_BYTES = 32 * 1024 * 1024

# Ranges offered on the host detail page: label -> (seconds, bucket seconds).
RANGES: dict[str, tuple[int, int]] = {
    "1h": (3600, 30),
    "6h": (6 * 3600, 120),
    "24h": (24 * 3600, 300),
    "7d": (7 * 24 * 3600, 1800),
    "30d": (30 * 24 * 3600, 7200),
}
DEFAULT_RANGE = "24h"

# Presentation only. Nothing here decides what a board shows — that comes from the host's
# saved layout, or from metrics_store.suggest_charts when there is none. These entries just
# make a series that happens to be recognisable read better once it is already on screen.
CHART_HINTS: dict[tuple[str, str], dict[str, Any]] = {
    ("cpu", "usage_idle"): {"title": "CPU usage", "unit": "%", "invert": True},
    ("cpu", "usage_user"): {"title": "CPU user", "unit": "%"},
    ("cpu", "usage_system"): {"title": "CPU system", "unit": "%"},
    ("cpu", "usage_iowait"): {"title": "CPU iowait", "unit": "%"},
    ("mem", "used_percent"): {"title": "Memory used", "unit": "%"},
    ("mem", "available_percent"): {"title": "Memory available", "unit": "%"},
    ("swap", "used_percent"): {"title": "Swap used", "unit": "%"},
    ("system", "load1"): {"title": "Load average (1m)"},
    ("system", "load5"): {"title": "Load average (5m)"},
    ("system", "load15"): {"title": "Load average (15m)"},
    ("system", "n_cpus"): {"title": "CPU count"},
    ("disk", "used_percent"): {"title": "Disk used", "unit": "%", "aggregate": "max"},
    ("diskio", "read_bytes"): {"title": "Disk read", "unit": "bytes", "aggregate": "max"},
    ("diskio", "write_bytes"): {"title": "Disk write", "unit": "bytes", "aggregate": "max"},
    ("net", "bytes_recv"): {"title": "Network received", "unit": "bytes", "aggregate": "max"},
    ("net", "bytes_sent"): {"title": "Network sent", "unit": "bytes", "aggregate": "max"},
    ("processes", "running"): {"title": "Processes running"},
    ("processes", "total"): {"title": "Processes total"},
}

# How many charts a board may hold, so one enthusiastic save cannot make the page unusable.
MAX_BOARD_CHARTS = 24
SUGGESTED_CHART_COUNT = 8


def _infer_unit(field: str) -> str:
    """Guess a unit from the field name so axes format sensibly for unknown series."""
    lowered = field.lower()
    if lowered.endswith("_percent") or lowered.endswith("_pct") or lowered == "percent":
        return "%"
    if "bytes" in lowered:
        return "bytes"
    return ""


def chart_spec(measurement: str, field: str, tags: dict[str, str] | None) -> dict[str, Any]:
    """Everything the template and JS need to draw one series."""
    hint = CHART_HINTS.get((measurement, field), {})
    title = hint.get("title") or f"{measurement}.{field}"
    if tags:
        title += " · " + " ".join(f"{k}={v}" for k, v in sorted(tags.items()))
    return {
        "key": series_key(measurement, field, tags),
        "title": title,
        "unit": hint.get("unit", _infer_unit(field)),
        "measurement": measurement,
        "field": field,
        "tags": tags,
        "aggregate": hint.get("aggregate", "avg"),
        "invert": hint.get("invert", False),
    }


def series_key(measurement: str, field: str, tags: dict[str, str] | None) -> str:
    """Stable identifier for one series, used as a DOM id and by the editor."""
    return f"{measurement}|{field}|{metrics_store.encode_tags(tags or {})}"


_host_touch_cache: dict[str, int] = {}


def _feature_guard():
    if not is_feature_enabled(FEATURE_METRICS):
        abort(404)


# ============ Ingest ============


def _influx_error(message: str, status: int, code: str = "invalid"):
    return jsonify({"code": code, "message": message}), status


def _read_body() -> tuple[str | None, tuple[Any, int] | None]:
    """Return the decoded request body, decompressing when the agent gzipped it."""
    declared = request.content_length
    if declared is not None and declared > MAX_BODY_BYTES:
        return None, _influx_error("request body too large", 413, code="request too large")

    raw = request.get_data(cache=False)
    if len(raw) > MAX_BODY_BYTES:
        return None, _influx_error("request body too large", 413, code="request too large")

    encoding = (request.headers.get("Content-Encoding") or "").lower()
    if "gzip" in encoding or "deflate" in encoding:
        label = "gzip" if "gzip" in encoding else "deflate"
        # Inflate incrementally with a ceiling: the size check above only bounds the
        # compressed bytes, so a small high-ratio body could otherwise expand without
        # limit and exhaust the worker.
        wbits = (16 + zlib.MAX_WBITS) if label == "gzip" else zlib.MAX_WBITS
        decompressor = zlib.decompressobj(wbits)
        try:
            raw = decompressor.decompress(raw, MAX_BODY_BYTES + 1)
        except (OSError, EOFError, zlib.error):
            return None, _influx_error(f"could not decompress {label} body", 400)
        if len(raw) > MAX_BODY_BYTES or decompressor.unconsumed_tail:
            return None, _influx_error(
                "decompressed body too large", 413, code="request too large"
            )

    try:
        return raw.decode("utf-8"), None
    except UnicodeDecodeError:
        return None, _influx_error("body must be utf-8 encoded line protocol", 400)


def _touch_host(hostname: str, now: int) -> None:
    """Keep MetricsHost fresh without writing to app.db on every batch."""
    last = _host_touch_cache.get(hostname, 0)
    if now - last < 30:
        return
    _host_touch_cache[hostname] = now
    try:
        updated = (
            MetricsHost.update(last_seen=now).where(MetricsHost.hostname == hostname).execute()
        )
        if not updated:
            MetricsHost.create(hostname=hostname, first_seen=now, last_seen=now)
    except Exception:
        # A host row is presentation metadata; losing one must not fail an ingest.
        pass


def _handle_write():
    _feature_guard()

    if not verify_metrics_token():
        return _influx_error("unauthorized access", 401, code="unauthorized")

    body, error = _read_body()
    if error:
        return error
    if not body or not body.strip():
        return "", 204

    try:
        points = list(parse(body, precision=request.args.get("precision")))
    except LineProtocolError as exc:
        return _influx_error(f"unable to parse points: {exc}", 400)

    if not points:
        return "", 204

    now = int(time.time())
    try:
        result = metrics_store.write_points(points, now=now)
    except Exception:
        return _influx_error("failed to write points", 500, code="internal error")

    for hostname in result.hosts:
        _touch_host(hostname, now)

    if result.dropped and not result.written:
        return _influx_error(
            "series cardinality limit reached for this host", 429, code="too many requests"
        )
    return "", 204


@metrics_bp.route("/api/v2/write", methods=["POST"])
def influx_v2_write():
    """InfluxDB 2.x write endpoint used by Telegraf's outputs.influxdb_v2."""
    return _handle_write()


@metrics_bp.route("/write", methods=["POST"])
def influx_v1_write():
    """InfluxDB 1.x write endpoint used by Telegraf's outputs.influxdb."""
    return _handle_write()


@metrics_bp.route("/ping", methods=["GET", "HEAD"])
def influx_ping():
    """Version probe the v1 output performs before its first write."""
    _feature_guard()
    return "", 204, {"X-Influxdb-Version": INFLUXDB_VERSION, "X-Influxdb-Build": "broke"}


@metrics_bp.route("/health", methods=["GET"])
def influx_health():
    _feature_guard()
    return (
        jsonify(
            {
                "name": "broke",
                "message": "ready for queries and writes",
                "status": "pass",
                "version": INFLUXDB_VERSION,
            }
        ),
        200,
    )


# ============ Pages ============


def _fmt_ago(ts: int | None, now: int) -> str:
    if not ts:
        return "never"
    delta = max(0, now - int(ts))
    if delta < 60:
        return f"{delta}s ago"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    return f"{delta // 86400}d ago"


def _host_summary(host: MetricsHost, now: int) -> dict[str, Any]:
    hostname = host.hostname
    cpu_idle = metrics_store.latest_value(
        host=hostname, measurement="cpu", field="usage_idle", tags={"cpu": "cpu-total"}, now=now
    )
    return {
        "hostname": hostname,
        "last_seen": host.last_seen,
        "last_seen_display": _fmt_ago(host.last_seen, now),
        "online": bool(host.last_seen and now - int(host.last_seen) < 300),
        "cpu": (100.0 - cpu_idle) if cpu_idle is not None else None,
        "memory": metrics_store.latest_value(
            host=hostname, measurement="mem", field="used_percent", now=now
        ),
        "disk": metrics_store.aggregate_latest(
            host=hostname, measurement="disk", field="used_percent", now=now, aggregate="max"
        ),
        "load1": metrics_store.latest_value(
            host=hostname, measurement="system", field="load1", now=now
        ),
        "uptime": metrics_store.latest_value(
            host=hostname, measurement="system", field="uptime", now=now
        ),
    }


def _is_plain_http_host(host: str) -> bool:
    """Whether this host is one nobody would have put a certificate in front of."""
    name = host.partition(":")[0].lower()
    if name in ("localhost", "127.0.0.1", "::1", "[::1]") or name.endswith(".local"):
        return True
    # A bare IP is almost always a LAN install reached over plain HTTP.
    return bool(re.fullmatch(r"[0-9.]+", name))


def ingest_base_url() -> str:
    """The URL to hand out in a Telegraf config, as https wherever that can be true.

    Broke normally sits behind a proxy that terminates TLS, so ``request.host_url``
    describes the plain-HTTP hop between the proxy and gunicorn and would advertise an
    ``http://`` endpoint. Telegraf will not follow the redirect such a proxy answers
    http with — it reports the 308 as a write failure — and the token would already have
    crossed the internet in clear text by then. So prefer the operator's APP_BASE_URL,
    then the scheme the proxy reports, and only fall back to http for local installs.
    """
    configured = os.environ.get("APP_BASE_URL", "").strip().rstrip("/")
    if configured:
        return configured

    scheme, _, host = request.host_url.rstrip("/").partition("://")
    forwarded = (request.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower()
    if forwarded in ("http", "https"):
        scheme = forwarded
    elif scheme == "http" and not _is_plain_http_host(host):
        scheme = "https"
    return f"{scheme}://{host}"


@metrics_bp.route("/servers")
@protected
def servers_list_view(user: User):
    _feature_guard()
    now = int(time.time())
    hosts = list(MetricsHost.select().order_by(MetricsHost.hostname))
    rows = [_host_summary(host, now) for host in hosts]
    return render_template(
        "servers_list.jinja2",
        user=user,
        page="servers",
        rows=rows,
        base_url=ingest_base_url(),
        online_count=sum(1 for r in rows if r["online"]),
    )


def resolve_board(hostname: str) -> tuple[list[dict[str, Any]], bool]:
    """The host's board, and whether a human arranged it.

    No saved rows is meaningful rather than empty: it means nobody has chosen anything for
    this host yet, so we suggest a board from the data instead of leaving the page blank.
    The suggestion is not written to the database — leaving it unsaved keeps it responsive
    to whatever the agent starts or stops sending, right up until someone edits it.
    """
    saved = list(
        MetricsChart.select()
        .where(MetricsChart.hostname == hostname)
        .order_by(MetricsChart.position, MetricsChart.id)
    )
    if saved:
        charts = []
        for row in saved:
            try:
                tags = json.loads(row.tags or "{}")
            except json.JSONDecodeError:
                tags = {}
            charts.append(chart_spec(str(row.measurement), str(row.field), tags))
        return charts, True

    suggested = metrics_store.suggest_charts(hostname, limit=SUGGESTED_CHART_COUNT)
    return [chart_spec(s["measurement"], s["field"], s["tags"]) for s in suggested], False


@metrics_bp.route("/servers/<path:hostname>")
@protected
def server_detail_view(user: User, hostname: str):
    _feature_guard()
    host = MetricsHost.get_or_none(MetricsHost.hostname == hostname)
    if not host:
        abort(404)

    now = int(time.time())
    range_key = request.args.get("range", DEFAULT_RANGE)
    if range_key not in RANGES:
        range_key = DEFAULT_RANGE

    series = metrics_store.list_series(hostname)
    measurements: dict[str, list[dict[str, Any]]] = {}
    for entry in series:
        measurements.setdefault(entry["measurement"], []).append(entry)

    charts, customised = resolve_board(hostname)
    # A string field would only ever draw an empty chart, so keep it out of the picker.
    text_only = metrics_store.text_only_series(hostname, now=now)

    return render_template(
        "server_detail.jinja2",
        user=user,
        page="servers",
        host=host,
        summary=_host_summary(host, now),
        charts=charts,
        board_customised=customised,
        board_data={
            "host": hostname,
            "charts": [
                {"key": c["key"], "measurement": c["measurement"], "field": c["field"]}
                for c in charts
            ],
            "available": [
                {
                    "key": series_key(e["measurement"], e["field"], e["tags"]),
                    "measurement": e["measurement"],
                    "field": e["field"],
                    "tags": e["tags"],
                }
                for e in series
                if (e["measurement"], e["field"], metrics_store.encode_tags(e["tags"]))
                not in text_only
            ],
        },
        ranges=list(RANGES.keys()),
        current_range=range_key,
        measurements=measurements,
        series_count=len(series),
        first_seen_display=datetime.fromtimestamp(
            int(host.first_seen), tz=timezone.utc
        ).strftime("%Y-%m-%d %H:%M UTC"),
    )


# ============ Query API ============


@metrics_bp.route("/api/metrics/query")
@protected
def api_query(user: User):
    """Bucketed values for one series; backs every chart on the detail page."""
    _feature_guard()

    hostname = (request.args.get("host") or "").strip()
    measurement = (request.args.get("measurement") or "").strip()
    field = (request.args.get("field") or "").strip()
    if not hostname or not measurement or not field:
        return jsonify({"error": "host, measurement and field are required"}), 400

    range_key = request.args.get("range", DEFAULT_RANGE)
    if range_key not in RANGES:
        return jsonify({"error": f"range must be one of {', '.join(RANGES)}"}), 400
    span_seconds, step_seconds = RANGES[range_key]

    # The window is half-open, so it ends at the close of the in-progress bucket rather
    # than at "now". Otherwise a point written this very second, or by an agent whose
    # clock runs slightly fast, would fall outside the range and vanish from the chart.
    now = int(time.time())
    end_ms = ((now // step_seconds) + 1) * step_seconds * 1000
    start_ms = end_ms - span_seconds * 1000

    tags: dict[str, str] | None = None
    raw_tags = request.args.get("tags")
    if raw_tags:
        try:
            parsed = json.loads(raw_tags)
        except json.JSONDecodeError:
            return jsonify({"error": "tags must be a JSON object"}), 400
        if not isinstance(parsed, dict):
            return jsonify({"error": "tags must be a JSON object"}), 400
        tags = {str(k): str(v) for k, v in parsed.items()}

    aggregate = request.args.get("aggregate", "avg")
    if aggregate not in ("avg", "min", "max", "sum"):
        return jsonify({"error": "aggregate must be avg, min, max or sum"}), 400

    points = metrics_store.query_series(
        host=hostname,
        measurement=measurement,
        field=field,
        start_ms=start_ms,
        end_ms=end_ms,
        step_ms=step_seconds * 1000,
        tags=tags,
        aggregate=aggregate,
    )

    if request.args.get("invert") in ("1", "true"):
        points = [{"ts": p["ts"], "value": 100.0 - p["value"]} for p in points]

    return jsonify(
        {
            "host": hostname,
            "measurement": measurement,
            "field": field,
            "range": range_key,
            "step_seconds": step_seconds,
            "start": start_ms,
            "end": end_ms,
            "points": points,
        }
    )


@metrics_bp.route("/api/metrics/hosts")
@protected
def api_hosts(user: User):
    _feature_guard()
    now = int(time.time())
    hosts = list(MetricsHost.select().order_by(MetricsHost.hostname))
    return jsonify({"hosts": [_host_summary(host, now) for host in hosts]})


@metrics_bp.route("/api/metrics/hosts/<path:hostname>", methods=["DELETE"])
@protected
def api_delete_host(user: User, hostname: str):
    """Forget a host: its rows, its catalogue entries and its Parquet partitions."""
    _feature_guard()
    if user.admin != 1:
        return jsonify({"error": "Unauthorized. Admins only."}), 403

    host = MetricsHost.get_or_none(MetricsHost.hostname == hostname)
    if not host:
        return jsonify({"error": "Host not found"}), 404

    metrics_store.purge_host(hostname)
    host.delete_instance()
    MetricsChart.delete().where(MetricsChart.hostname == hostname).execute()
    _host_touch_cache.pop(hostname, None)
    return jsonify({"ok": True})


# ============ Board layout ============


def _board_payload(hostname: str) -> dict[str, Any]:
    charts, customised = resolve_board(hostname)
    return {
        "charts": [
            {
                "key": c["key"],
                "title": c["title"],
                "measurement": c["measurement"],
                "field": c["field"],
                "tags": c["tags"],
            }
            for c in charts
        ],
        "customised": customised,
    }


@metrics_bp.route("/api/metrics/hosts/<path:hostname>/charts")
@protected
def api_get_charts(user: User, hostname: str):
    _feature_guard()
    if not MetricsHost.get_or_none(MetricsHost.hostname == hostname):
        return jsonify({"error": "Host not found"}), 404
    return jsonify(_board_payload(hostname))


@metrics_bp.route("/api/metrics/hosts/<path:hostname>/charts", methods=["PUT"])
@protected
def api_save_charts(user: User, hostname: str):
    """Replace a host's board. The order of the list is the order on the page."""
    _feature_guard()
    if not MetricsHost.get_or_none(MetricsHost.hostname == hostname):
        return jsonify({"error": "Host not found"}), 404

    payload = request.get_json(silent=True) or {}
    requested = payload.get("charts")
    if not isinstance(requested, list):
        return jsonify({"error": "charts must be a list"}), 400
    if len(requested) > MAX_BOARD_CHARTS:
        return jsonify({"error": f"a board holds at most {MAX_BOARD_CHARTS} charts"}), 400
    if not requested:
        # "No rows" already means "nobody arranged this host", so an empty board could not
        # be told apart from an unarranged one and would silently revert on the next load.
        # Rejecting it keeps that distinction honest; DELETE is how you ask for the
        # suggestion back.
        return jsonify({"error": "a board needs at least one chart"}), 400

    known = {
        series_key(e["measurement"], e["field"], e["tags"]): e
        for e in metrics_store.list_series(hostname)
    }

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for position, item in enumerate(requested):
        if not isinstance(item, dict):
            return jsonify({"error": "each chart must be an object"}), 400
        measurement = str(item.get("measurement") or "")
        field = str(item.get("field") or "")
        tags = item.get("tags")
        if not isinstance(tags, dict):
            tags = {}
        tags = {str(k): str(v) for k, v in tags.items()}

        key = series_key(measurement, field, tags)
        if key not in known:
            return jsonify({"error": f"{measurement}.{field} is not a series this host sent"}), 400
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "hostname": hostname,
                "measurement": measurement,
                "field": field,
                "tags": metrics_store.encode_tags(tags),
                "position": position,
                "created_at": int(time.time()),
            }
        )

    # Replace wholesale: positions are only meaningful as a complete sequence, and this
    # keeps a removed chart from lingering because its row happened not to be overwritten.
    with database.atomic():
        MetricsChart.delete().where(MetricsChart.hostname == hostname).execute()
        if rows:
            MetricsChart.insert_many(rows).execute()

    return jsonify(_board_payload(hostname))


@metrics_bp.route("/api/metrics/hosts/<path:hostname>/charts", methods=["DELETE"])
@protected
def api_reset_charts(user: User, hostname: str):
    """Drop the saved board so the host falls back to a suggestion from its data."""
    _feature_guard()
    if not MetricsHost.get_or_none(MetricsHost.hostname == hostname):
        return jsonify({"error": "Host not found"}), 404

    MetricsChart.delete().where(MetricsChart.hostname == hostname).execute()
    return jsonify(_board_payload(hostname))
