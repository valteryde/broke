"""
Telegraf metrics: InfluxDB-compatible ingest plus the Servers pages.

Servers point ``outputs.influxdb_v2`` (or the v1 ``outputs.influxdb``) at Broke. The
write endpoints are deliberately not ``@protected``: they take a bearer token instead of
a session, which is also what keeps them out of CSRF checking.
"""

from __future__ import annotations

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
from ..utils.models import MetricsHost, User
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

# Series drawn on the host detail page, in order.
CHART_SPECS: list[dict[str, Any]] = [
    {
        "key": "cpu",
        "title": "CPU usage",
        "unit": "%",
        "measurement": "cpu",
        "field": "usage_idle",
        "tags": {"cpu": "cpu-total"},
        "invert": True,
    },
    {
        "key": "memory",
        "title": "Memory used",
        "unit": "%",
        "measurement": "mem",
        "field": "used_percent",
        "tags": {},
    },
    {
        "key": "swap",
        "title": "Swap used",
        "unit": "%",
        "measurement": "swap",
        "field": "used_percent",
        "tags": {},
    },
    {
        "key": "load",
        "title": "Load average (1m)",
        "unit": "",
        "measurement": "system",
        "field": "load1",
        "tags": {},
    },
    {
        "key": "disk",
        "title": "Disk used (busiest mount)",
        "unit": "%",
        "measurement": "disk",
        "field": "used_percent",
        "tags": None,
        "aggregate": "max",
    },
    {
        "key": "disk_io_read",
        "title": "Disk read",
        "unit": "bytes",
        "measurement": "diskio",
        "field": "read_bytes",
        "tags": None,
        "aggregate": "max",
    },
    {
        "key": "net_recv",
        "title": "Network received",
        "unit": "bytes",
        "measurement": "net",
        "field": "bytes_recv",
        "tags": None,
        "aggregate": "max",
    },
    {
        "key": "processes",
        "title": "Processes running",
        "unit": "",
        "measurement": "processes",
        "field": "running",
        "tags": {},
    },
]

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

    return render_template(
        "server_detail.jinja2",
        user=user,
        page="servers",
        host=host,
        summary=_host_summary(host, now),
        charts=CHART_SPECS,
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
        import json

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
    _host_touch_cache.pop(hostname, None)
    return jsonify({"ok": True})
