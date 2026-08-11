"""
Storage for Telegraf metrics: a small SQLite hot tier plus a Parquet cold tier.

Points never touch ``app.db`` — a metrics write burst must not be able to take a write
lock that blocks a ticket save. Instead:

* Ingest appends to ``data/metrics.db`` (WAL), which holds roughly the last hour.
* A compactor moves anything older into ``data/metrics/dt=<date>/<host>/part-*.parquet``.
* Reads union the two tiers, using DuckDB for the Parquet side and plain ``sqlite3``
  for the hot side.

The hot tier is deliberately read with ``sqlite3`` rather than DuckDB's ``sqlite_scanner``
extension, which downloads itself at runtime and would break airgapped installs.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, NamedTuple, Sequence

from .lineprotocol import Point
from .path import data_path

logger = logging.getLogger(__name__)

DEFAULT_RETENTION_DAYS = 365
DEFAULT_MAX_SERIES_PER_HOST = 5000
DEFAULT_HOT_WINDOW_SECONDS = 3600
DEFAULT_COMPACT_INTERVAL_SECONDS = 300

# Telegraf puts the machine name in a "host" tag; it becomes its own column.
HOST_TAG = "host"
UNKNOWN_HOST = "unknown"
MAX_HOST_LENGTH = 255

_UNSAFE_PATH_CHARS = re.compile(r"[^A-Za-z0-9._-]")
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")

_local = threading.local()
_series_cache_lock = threading.Lock()
_known_series: set[str] = set()
_host_series_counts: dict[str, int] = {}
_series_cache_loaded_for: str | None = None


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, "") or default)
    except ValueError:
        return default
    return value if value > 0 else default


def retention_days() -> int:
    return _env_int("METRICS_RETENTION_DAYS", DEFAULT_RETENTION_DAYS)


def max_series_per_host() -> int:
    return _env_int("METRICS_MAX_SERIES_PER_HOST", DEFAULT_MAX_SERIES_PER_HOST)


def hot_window_seconds() -> int:
    return _env_int("METRICS_HOT_WINDOW_SECONDS", DEFAULT_HOT_WINDOW_SECONDS)


def compact_interval_seconds() -> int:
    return _env_int("METRICS_COMPACT_INTERVAL_SECONDS", DEFAULT_COMPACT_INTERVAL_SECONDS)


def metrics_dir() -> Path:
    """Base directory for both tiers; overridable so tests get an isolated lake."""
    override = os.environ.get("BROKE_METRICS_DIR")
    return Path(override) if override else Path(data_path())


def hot_db_path() -> Path:
    return metrics_dir() / "metrics.db"


def lake_dir() -> Path:
    return metrics_dir() / "metrics"


# ============ Hot tier ============

_HOT_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS hot_point (
        ts INTEGER NOT NULL,
        host TEXT NOT NULL,
        measurement TEXT NOT NULL,
        tags TEXT NOT NULL,
        field TEXT NOT NULL,
        value REAL,
        svalue TEXT
    );
    """,
    "CREATE INDEX IF NOT EXISTS hot_point_ts ON hot_point(ts);",
    "CREATE INDEX IF NOT EXISTS hot_point_host_ts ON hot_point(host, ts);",
    """
    CREATE TABLE IF NOT EXISTS series (
        series_key TEXT PRIMARY KEY,
        host TEXT NOT NULL,
        measurement TEXT NOT NULL,
        tags TEXT NOT NULL,
        field TEXT NOT NULL,
        first_seen INTEGER NOT NULL,
        last_seen INTEGER NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS series_host ON series(host);",
)


def hot_connection() -> sqlite3.Connection:
    """One WAL connection per thread and path, created on first use."""
    path = str(hot_db_path())
    conns: dict[str, sqlite3.Connection] = getattr(_local, "conns", None) or {}
    existing = conns.get(path)
    if existing is not None:
        return existing

    hot_db_path().parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    for statement in _HOT_SCHEMA:
        conn.execute(statement)
    conn.commit()

    conns[path] = conn
    _local.conns = conns
    return conn


def close_hot_connection() -> None:
    """Drop this thread's cached connections; used by tests when swapping directories."""
    conns: dict[str, sqlite3.Connection] = getattr(_local, "conns", None) or {}
    for conn in conns.values():
        try:
            conn.close()
        except sqlite3.Error:
            pass
    _local.conns = {}


def reset_series_cache() -> None:
    global _series_cache_loaded_for
    with _series_cache_lock:
        _known_series.clear()
        _host_series_counts.clear()
        _series_cache_loaded_for = None


def _load_series_cache(conn: sqlite3.Connection) -> None:
    """Populate the in-process view of known series, used only for the cardinality cap."""
    global _series_cache_loaded_for
    path = str(hot_db_path())
    if _series_cache_loaded_for == path:
        return
    _known_series.clear()
    _host_series_counts.clear()
    for series_key, host in conn.execute("SELECT series_key, host FROM series"):
        _known_series.add(series_key)
        _host_series_counts[host] = _host_series_counts.get(host, 0) + 1
    _series_cache_loaded_for = path


def _authoritative_host_count(conn: sqlite3.Connection, host: str, refreshed: set[str]) -> int:
    """Series count for one host, re-read from SQLite at most once per batch.

    The in-process cache only ever sees the series this worker admitted, so relying on it
    alone would let every gunicorn worker hand out a full cap independently. Reading the
    shared table back is what makes the cap mean one number per host across the install.
    The ``series_host`` index keeps this cheap, and it only runs on batches that actually
    introduce a new series, which is rare once an agent's shape settles.
    """
    if host not in refreshed:
        row = conn.execute("SELECT COUNT(*) FROM series WHERE host = ?", (host,)).fetchone()
        _host_series_counts[host] = int(row[0]) if row else 0
        refreshed.add(host)
    return _host_series_counts.get(host, 0)


def _series_key(host: str, measurement: str, tags: str, field: str) -> str:
    return f"{host}\x1f{measurement}\x1f{tags}\x1f{field}"


def normalize_host(raw: str | None) -> str:
    """
    Clamp an agent-supplied host tag to something safe to store and display.

    The value arrives from whoever holds a write token, so it is untrusted. Templates
    escape it on the way out; this only keeps control characters and unbounded strings
    out of the database, the Parquet partition names, and the settings list.
    """
    host = _CONTROL_CHARS.sub("", str(raw or "")).strip()
    if len(host) > MAX_HOST_LENGTH:
        host = host[:MAX_HOST_LENGTH]
    return host or UNKNOWN_HOST


def encode_tags(tags: dict[str, str]) -> str:
    """Canonical JSON for a tag set, minus the host tag, with keys sorted."""
    return json.dumps(
        {k: v for k, v in sorted(tags.items()) if k != HOST_TAG},
        separators=(",", ":"),
        ensure_ascii=False,
    )


class WriteResult(NamedTuple):
    written: int
    dropped: int
    hosts: set[str]


def write_points(points: Iterable[Point], *, now: int | None = None) -> WriteResult:
    """
    Append parsed points to the hot tier.

    Each field of each point becomes one row. Series beyond the per-host cardinality cap
    are dropped so one misconfigured agent cannot flood the lake, while series already
    known keep flowing.
    """
    now = int(now if now is not None else time.time())
    conn = hot_connection()

    rows: list[tuple[int, str, str, str, str, float | None, str | None]] = []
    batch_series: dict[str, tuple[str, str, str, str]] = {}
    dropped = 0
    hosts: set[str] = set()

    with _series_cache_lock:
        _load_series_cache(conn)
        cap = max_series_per_host()
        refreshed: set[str] = set()

        for point in points:
            host = normalize_host(point.tags.get(HOST_TAG))
            tags = encode_tags(point.tags)
            ts_ms = point.timestamp_ns // 1_000_000
            hosts.add(host)

            for field, raw in point.fields.items():
                key = _series_key(host, point.measurement, tags, field)
                if key not in _known_series and key not in batch_series:
                    if _authoritative_host_count(conn, host, refreshed) >= cap:
                        dropped += 1
                        continue
                    _host_series_counts[host] = _host_series_counts.get(host, 0) + 1
                    _known_series.add(key)
                batch_series[key] = (host, point.measurement, tags, field)

                if isinstance(raw, bool):
                    value: float | None = 1.0 if raw else 0.0
                    svalue: str | None = None
                elif isinstance(raw, (int, float)):
                    value, svalue = float(raw), None
                else:
                    value, svalue = None, str(raw)
                rows.append((ts_ms, host, point.measurement, tags, field, value, svalue))

    if not rows:
        return WriteResult(0, dropped, hosts)

    series_rows = [
        (key, host, measurement, tags, field, now, now)
        for key, (host, measurement, tags, field) in batch_series.items()
    ]

    with conn:
        conn.executemany(
            "INSERT INTO hot_point (ts, host, measurement, tags, field, value, svalue)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.executemany(
            "INSERT INTO series (series_key, host, measurement, tags, field, first_seen, last_seen)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(series_key) DO UPDATE SET last_seen = excluded.last_seen",
            series_rows,
        )

    return WriteResult(len(rows), dropped, hosts)


# ============ Cold tier ============


def host_dirname(host: str) -> str:
    """Filesystem-safe directory for a host.

    The hash suffix keeps two hosts that sanitize to the same string apart. Correctness
    never depends on this name: ``host`` is also a column inside every Parquet file.
    """
    safe = _UNSAFE_PATH_CHARS.sub("_", host)[:48] or "host"
    digest = hashlib.sha1(host.encode("utf-8")).hexdigest()[:8]  # nosec B324 - not security
    return f"{safe}-{digest}"


def _partition_dir(day: str, host: str) -> Path:
    return lake_dir() / f"dt={day}" / host_dirname(host)


def _duckdb_connection():
    """One in-memory DuckDB per thread; it is only ever a query engine over files.

    Extension autoloading is off so a query can never try to fetch anything over the
    network. Parquet support is built into DuckDB core, so nothing else is needed.
    """
    conn = getattr(_local, "duck", None)
    if conn is None:
        import duckdb

        conn = duckdb.connect(
            config={
                "autoinstall_known_extensions": False,
                "autoload_known_extensions": False,
            }
        )
        _local.duck = conn
    return conn


class CompactionResult(NamedTuple):
    files_written: int
    rows_compacted: int


def compact(*, now: int | None = None, older_than_seconds: int | None = None) -> CompactionResult:
    """
    Move hot rows older than the hot window into Parquet, one file per day and host.

    Ordering is write, rename, then delete, so an unclean shutdown can never lose points.
    The filename is derived from the rowid range being compacted, so a retry after a
    crash between rename and delete overwrites the same file instead of duplicating it.
    """
    now = int(now if now is not None else time.time())
    window = older_than_seconds if older_than_seconds is not None else hot_window_seconds()
    cutoff_ms = (now - window) * 1000

    conn = hot_connection()
    groups = conn.execute(
        "SELECT DISTINCT date(ts / 1000, 'unixepoch') AS day, host"
        " FROM hot_point WHERE ts < ? ORDER BY day, host",
        (cutoff_ms,),
    ).fetchall()

    files_written = 0
    rows_compacted = 0
    for day, host in groups:
        written = _compact_group(conn, day=day, host=host, cutoff_ms=cutoff_ms)
        if written:
            files_written += 1
            rows_compacted += written

    if rows_compacted:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    return CompactionResult(files_written, rows_compacted)


def _compact_group(conn: sqlite3.Connection, *, day: str, host: str, cutoff_ms: int) -> int:
    rows = conn.execute(
        "SELECT rowid, ts, host, measurement, tags, field, value, svalue"
        " FROM hot_point"
        " WHERE ts < ? AND host = ? AND date(ts / 1000, 'unixepoch') = ?"
        " ORDER BY measurement, field, tags, ts",
        (cutoff_ms, host, day),
    ).fetchall()
    if not rows:
        return 0

    rowids = [r[0] for r in rows]
    payload = [r[1:] for r in rows]

    target_dir = _partition_dir(day, host)
    target_dir.mkdir(parents=True, exist_ok=True)
    name = f"part-{min(rowids)}-{max(rowids)}-{len(rowids)}.parquet"
    final_path = target_dir / name
    tmp_path = target_dir / f"{name}.tmp"

    duck = _duckdb_connection()
    duck.execute("DROP TABLE IF EXISTS compact_batch;")
    duck.execute(
        "CREATE TABLE compact_batch ("
        " ts BIGINT, host VARCHAR, measurement VARCHAR, tags VARCHAR,"
        " field VARCHAR, value DOUBLE, svalue VARCHAR)"
    )
    duck.executemany("INSERT INTO compact_batch VALUES (?, ?, ?, ?, ?, ?, ?)", payload)
    # DuckDB cannot bind the COPY target, so the path is interpolated. It is built from
    # the configured lake directory, an ISO date produced by SQLite and host_dirname(),
    # which strips everything outside [A-Za-z0-9._-]; quotes are escaped as well.
    copy_sql = (
        "COPY (SELECT * FROM compact_batch ORDER BY measurement, field, tags, ts)"
        f" TO '{_sql_literal(str(tmp_path))}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )  # nosec B608 - sanitized, quote-escaped path; no user-supplied SQL
    duck.execute(copy_sql)
    duck.execute("DROP TABLE IF EXISTS compact_batch;")

    os.replace(tmp_path, final_path)

    with conn:
        conn.executemany("DELETE FROM hot_point WHERE rowid = ?", [(r,) for r in rowids])

    return len(rowids)


def apply_retention(*, now: int | None = None, days: int | None = None) -> int:
    """Delete whole day partitions past the retention horizon. Returns dirs removed."""
    import shutil

    now = int(now if now is not None else time.time())
    keep = days if days is not None else retention_days()
    cutoff = datetime.fromtimestamp(now, tz=timezone.utc).date() - timedelta(days=keep)

    root = lake_dir()
    if not root.exists():
        return 0

    removed = 0
    for entry in root.iterdir():
        if not entry.is_dir() or not entry.name.startswith("dt="):
            continue
        try:
            day = date.fromisoformat(entry.name[3:])
        except ValueError:
            continue
        if day < cutoff:
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
    return removed


def cleanup_orphan_temp_files(*, older_than_seconds: int = 3600) -> int:
    """Remove ``.tmp`` Parquet files left behind by a compaction that died mid-write."""
    root = lake_dir()
    if not root.exists():
        return 0
    threshold = time.time() - older_than_seconds
    removed = 0
    for tmp in root.rglob("*.parquet.tmp"):
        try:
            if tmp.stat().st_mtime < threshold:
                tmp.unlink()
                removed += 1
        except OSError:
            continue
    return removed


# ============ Queries ============


def _sql_literal(value: str) -> str:
    return value.replace("'", "''")


def _cold_glob(host: str | None) -> str | None:
    root = lake_dir()
    if not root.exists():
        return None
    if host:
        pattern = str(root / "dt=*" / host_dirname(host) / "*.parquet")
    else:
        pattern = str(root / "dt=*" / "*" / "*.parquet")
    return pattern


def _cold_has_files(host: str | None) -> bool:
    root = lake_dir()
    if not root.exists():
        return False
    if host:
        return any((root).glob(f"dt=*/{host_dirname(host)}/*.parquet"))
    return any(root.glob("dt=*/*/*.parquet"))


class Bucket(NamedTuple):
    ts: int
    total: float
    count: int
    minimum: float
    maximum: float


def _merge_buckets(*sources: Sequence[Bucket]) -> dict[int, Bucket]:
    merged: dict[int, Bucket] = {}
    for source in sources:
        for bucket in source:
            existing = merged.get(bucket.ts)
            if existing is None:
                merged[bucket.ts] = bucket
            else:
                merged[bucket.ts] = Bucket(
                    bucket.ts,
                    existing.total + bucket.total,
                    existing.count + bucket.count,
                    min(existing.minimum, bucket.minimum),
                    max(existing.maximum, bucket.maximum),
                )
    return merged


def query_series(
    *,
    host: str,
    measurement: str,
    field: str,
    start_ms: int,
    end_ms: int,
    step_ms: int,
    tags: dict[str, str] | None = None,
    aggregate: str = "avg",
) -> list[dict[str, Any]]:
    """
    Bucketed values for one series over a time range, unioning the hot and cold tiers.

    Both tiers return sum/count/min/max per bucket rather than a finished average, so a
    bucket that straddles the compaction cutoff still aggregates correctly.
    """
    if step_ms <= 0:
        raise ValueError("step_ms must be positive")

    # An empty dict is a real filter meaning "the series carrying no tags beyond host",
    # which is how mem/swap/system charts are addressed. Only None means "any tag set".
    tags_json = None if tags is None else encode_tags(tags)

    hot = _query_hot_buckets(
        host=host,
        measurement=measurement,
        field=field,
        start_ms=start_ms,
        end_ms=end_ms,
        step_ms=step_ms,
        tags_json=tags_json,
    )
    cold = _query_cold_buckets(
        host=host,
        measurement=measurement,
        field=field,
        start_ms=start_ms,
        end_ms=end_ms,
        step_ms=step_ms,
        tags_json=tags_json,
    )

    merged = _merge_buckets(hot, cold)
    points: list[dict[str, Any]] = []
    for ts in sorted(merged):
        bucket = merged[ts]
        if aggregate == "max":
            value = bucket.maximum
        elif aggregate == "min":
            value = bucket.minimum
        elif aggregate == "sum":
            value = bucket.total
        else:
            value = bucket.total / bucket.count if bucket.count else 0.0
        points.append({"ts": ts, "value": value})
    return points


def _query_hot_buckets(
    *,
    host: str,
    measurement: str,
    field: str,
    start_ms: int,
    end_ms: int,
    step_ms: int,
    tags_json: str | None,
) -> list[Bucket]:
    sql = (
        "SELECT (ts / ?) * ? AS bucket, SUM(value), COUNT(value), MIN(value), MAX(value)"
        " FROM hot_point"
        " WHERE host = ? AND measurement = ? AND field = ?"
        " AND ts >= ? AND ts < ? AND value IS NOT NULL"
    )
    params: list[Any] = [step_ms, step_ms, host, measurement, field, start_ms, end_ms]
    if tags_json is not None:
        sql += " AND tags = ?"
        params.append(tags_json)
    sql += " GROUP BY bucket ORDER BY bucket"

    conn = hot_connection()
    return [
        Bucket(int(row[0]), float(row[1] or 0.0), int(row[2]), float(row[3]), float(row[4]))
        for row in conn.execute(sql, params)
        if row[2]
    ]


def _query_cold_buckets(
    *,
    host: str,
    measurement: str,
    field: str,
    start_ms: int,
    end_ms: int,
    step_ms: int,
    tags_json: str | None,
) -> list[Bucket]:
    if not _cold_has_files(host):
        return []
    pattern = _cold_glob(host)
    if not pattern:
        return []

    sql = (
        "SELECT (ts // ?) * ? AS bucket, SUM(value), COUNT(value), MIN(value), MAX(value)"
        " FROM read_parquet(?, hive_partitioning = true, union_by_name = true)"
        " WHERE host = ? AND measurement = ? AND field = ?"
        " AND ts >= ? AND ts < ? AND value IS NOT NULL"
    )
    params: list[Any] = [step_ms, step_ms, pattern, host, measurement, field, start_ms, end_ms]
    if tags_json is not None:
        sql += " AND tags = ?"
        params.append(tags_json)
    sql += " GROUP BY bucket ORDER BY bucket"

    duck = _duckdb_connection()
    try:
        rows = duck.execute(sql, params).fetchall()
    except Exception:
        logger.exception("Metrics cold query failed")
        return []
    return [
        Bucket(int(r[0]), float(r[1] or 0.0), int(r[2]), float(r[3]), float(r[4]))
        for r in rows
        if r[2]
    ]


def list_series(host: str) -> list[dict[str, Any]]:
    """Every series a host has ever written, from the hot tier's series catalogue."""
    conn = hot_connection()
    rows = conn.execute(
        "SELECT measurement, field, tags, first_seen, last_seen"
        " FROM series WHERE host = ? ORDER BY measurement, field, tags",
        (host,),
    ).fetchall()
    return [
        {
            "measurement": r[0],
            "field": r[1],
            "tags": json.loads(r[2] or "{}"),
            "first_seen": r[3],
            "last_seen": r[4],
        }
        for r in rows
    ]


def list_measurements(host: str) -> list[str]:
    conn = hot_connection()
    rows = conn.execute(
        "SELECT DISTINCT measurement FROM series WHERE host = ? ORDER BY measurement",
        (host,),
    ).fetchall()
    return [r[0] for r in rows]


def text_only_series(host: str, *, now: int | None = None) -> set[tuple[str, str, str]]:
    """Series that have arrived recently carrying only text, keyed by (measurement, field, tags).

    Telegraf mixes string fields in with numbers — ``system.uptime_format`` and friends —
    and there is nothing to draw for those. A series with no recent rows at all is absent
    from the result rather than reported as text: we simply do not know, and guessing wrong
    would hide a real chart.
    """
    now = int(now if now is not None else time.time())
    start_ms = (now - hot_window_seconds()) * 1000

    rows = hot_connection().execute(
        "SELECT measurement, field, tags FROM hot_point"
        " WHERE host = ? AND ts >= ?"
        " GROUP BY measurement, field, tags"
        " HAVING SUM(CASE WHEN value IS NOT NULL THEN 1 ELSE 0 END) = 0",
        (host, start_ms),
    ).fetchall()
    return {(r[0], r[1], r[2] or "{}") for r in rows}


def suggest_charts(host: str, *, limit: int = 8, now: int | None = None) -> list[dict[str, Any]]:
    """A starting board for a host nobody has arranged yet.

    Deliberately not a list of metrics we consider interesting: the picks come from what
    this agent actually sent. Two data-driven rules do the work. A series whose value moved
    over the window beats one that sat still, which is what separates a live reading from a
    counter pinned at zero or a constant flag. And at most one field per measurement is
    taken, so the board spans the host instead of showing eight views of the CPU.

    String-valued series are skipped: there is nothing to plot.
    """
    now = int(now if now is not None else time.time())
    start_ms = (now - hot_window_seconds()) * 1000

    rows = hot_connection().execute(
        "SELECT measurement, field, tags, MIN(value), MAX(value), COUNT(value)"
        " FROM hot_point"
        " WHERE host = ? AND ts >= ? AND value IS NOT NULL"
        " GROUP BY measurement, field, tags",
        (host, start_ms),
    ).fetchall()

    candidates = [
        {
            "measurement": r[0],
            "field": r[1],
            "tags": json.loads(r[2] or "{}"),
            "varies": r[3] is not None and r[4] is not None and r[4] > r[3],
            "points": r[5],
        }
        for r in rows
    ]

    if not candidates:
        # Nothing recent to judge — a host that stopped reporting, or one whose window has
        # already been compacted away. Fall back to the durable catalogue so the board is
        # still populated, just without the variance signal.
        candidates = [
            {**entry, "varies": False, "points": 0}
            for entry in list_series(host)
        ]

    candidates.sort(
        key=lambda c: (not c["varies"], c["measurement"], c["field"], encode_tags(c["tags"]))
    )

    picked: list[dict[str, Any]] = []
    seen_measurements: set[str] = set()
    for candidate in candidates:
        if candidate["measurement"] in seen_measurements:
            continue
        seen_measurements.add(candidate["measurement"])
        picked.append(
            {
                "measurement": candidate["measurement"],
                "field": candidate["field"],
                "tags": candidate["tags"],
            }
        )
        if len(picked) >= limit:
            break
    return picked


def latest_value(
    *,
    host: str,
    measurement: str,
    field: str,
    tags: dict[str, str] | None = None,
    within_seconds: int = 900,
    now: int | None = None,
) -> float | None:
    """Most recent numeric value for a series, looked up in the hot tier only.

    Agents report every few seconds, so anything still relevant to a status page is by
    definition inside the hot window; falling through to Parquet would cost far more.
    """
    now = int(now if now is not None else time.time())
    start_ms = (now - within_seconds) * 1000

    sql = (
        "SELECT value FROM hot_point"
        " WHERE host = ? AND measurement = ? AND field = ? AND ts >= ? AND value IS NOT NULL"
    )
    params: list[Any] = [host, measurement, field, start_ms]
    if tags is not None:
        sql += " AND tags = ?"
        params.append(encode_tags(tags))
    sql += " ORDER BY ts DESC LIMIT 1"

    row = hot_connection().execute(sql, params).fetchone()
    return float(row[0]) if row else None


def aggregate_latest(
    *,
    host: str,
    measurement: str,
    field: str,
    within_seconds: int = 900,
    now: int | None = None,
    aggregate: str = "max",
) -> float | None:
    """Latest value per tag set for a series, reduced to a single number.

    Used where a host reports one series per device — the busiest disk, for instance —
    and the overview only has room for one figure.
    """
    now = int(now if now is not None else time.time())
    start_ms = (now - within_seconds) * 1000

    func = {"max": "MAX", "min": "MIN", "sum": "SUM", "avg": "AVG"}.get(aggregate, "MAX")
    sql = (
        f"SELECT {func}(v) FROM ("
        "  SELECT tags, ("
        "    SELECT value FROM hot_point i"
        "    WHERE i.host = o.host AND i.measurement = o.measurement"
        "      AND i.field = o.field AND i.tags = o.tags AND i.ts >= ?"
        "      AND i.value IS NOT NULL"
        "    ORDER BY i.ts DESC LIMIT 1"
        "  ) AS v"
        "  FROM (SELECT DISTINCT host, measurement, field, tags FROM hot_point"
        "        WHERE host = ? AND measurement = ? AND field = ? AND ts >= ?) o"
        ") WHERE v IS NOT NULL"
    )
    row = hot_connection().execute(
        sql, (start_ms, host, measurement, field, start_ms)
    ).fetchone()
    return float(row[0]) if row and row[0] is not None else None


def lake_size_bytes() -> int:
    root = lake_dir()
    if not root.exists():
        return 0
    total = 0
    for parquet in root.rglob("*.parquet"):
        try:
            total += parquet.stat().st_size
        except OSError:
            continue
    return total


def store_stats() -> dict[str, Any]:
    """Numbers for the settings page: tier sizes and catalogue counts."""
    conn = hot_connection()
    hot_rows = conn.execute("SELECT COUNT(*) FROM hot_point").fetchone()[0]
    series_count = conn.execute("SELECT COUNT(*) FROM series").fetchone()[0]
    hosts = conn.execute("SELECT COUNT(DISTINCT host) FROM series").fetchone()[0]
    try:
        hot_bytes = hot_db_path().stat().st_size
    except OSError:
        hot_bytes = 0
    return {
        "hot_rows": hot_rows,
        "hot_bytes": hot_bytes,
        "series_count": series_count,
        "host_count": hosts,
        "lake_bytes": lake_size_bytes(),
        "retention_days": retention_days(),
    }


def purge_host(host: str) -> None:
    """Forget a host entirely: hot rows, catalogue entries and every Parquet partition."""
    import shutil

    conn = hot_connection()
    with conn:
        conn.execute("DELETE FROM hot_point WHERE host = ?", (host,))
        conn.execute("DELETE FROM series WHERE host = ?", (host,))
    reset_series_cache()

    root = lake_dir()
    if root.exists():
        for partition in root.glob(f"dt=*/{host_dirname(host)}"):
            shutil.rmtree(partition, ignore_errors=True)
