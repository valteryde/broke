"""
Storage for product usage events: a small SQLite hot tier plus a Parquet cold tier.

Events never touch ``app.db`` — a traffic burst must not take a write lock that blocks a
ticket save. The layout matches metrics_store (hot WAL, daily Parquet, DuckDB on read)
but the grain is a visitor event, not a Telegraf point, and there is no host column.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, NamedTuple, Sequence

from .path import data_path

logger = logging.getLogger(__name__)

DEFAULT_RETENTION_DAYS = 365
DEFAULT_MAX_ROUTES = 5000
DEFAULT_HOT_WINDOW_SECONDS = 3600
DEFAULT_COMPACT_INTERVAL_SECONDS = 300
DEFAULT_MAX_AGE_MS = 7 * 24 * 3600 * 1000
MAX_DASHBOARD_ROWS = 20
MAX_JOURNEY_ROWS = 10

_CONTROL_CHARS = __import__("re").compile(r"[\x00-\x1f\x7f]")

_local = threading.local()
_route_cache_lock = threading.Lock()
_known_routes: set[str] = set()
_route_cache_loaded_for: str | None = None


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, "") or default)
    except ValueError:
        return default
    return value if value > 0 else default


def retention_days() -> int:
    return _env_int("USAGE_RETENTION_DAYS", DEFAULT_RETENTION_DAYS)


def max_routes() -> int:
    return _env_int("USAGE_MAX_ROUTES", DEFAULT_MAX_ROUTES)


def hot_window_seconds() -> int:
    return _env_int("USAGE_HOT_WINDOW_SECONDS", DEFAULT_HOT_WINDOW_SECONDS)


def compact_interval_seconds() -> int:
    return _env_int("USAGE_COMPACT_INTERVAL_SECONDS", DEFAULT_COMPACT_INTERVAL_SECONDS)


def usage_dir() -> Path:
    override = os.environ.get("BROKE_USAGE_DIR")
    return Path(override) if override else Path(data_path())


def hot_db_path() -> Path:
    return usage_dir() / "usage.db"


def lake_dir() -> Path:
    return usage_dir() / "usage"


_HOT_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS hot_event (
        ts INTEGER NOT NULL,
        visitor TEXT NOT NULL,
        session TEXT NOT NULL,
        kind TEXT NOT NULL,
        path TEXT NOT NULL,
        route TEXT NOT NULL,
        sector TEXT NOT NULL,
        referrer_path TEXT,
        name TEXT,
        country TEXT,
        region TEXT,
        city TEXT
    );
    """,
    "CREATE INDEX IF NOT EXISTS hot_event_ts ON hot_event(ts);",
    "CREATE INDEX IF NOT EXISTS hot_event_session_ts ON hot_event(session, ts);",
    """
    CREATE TABLE IF NOT EXISTS usage_route (
        route TEXT PRIMARY KEY,
        first_seen INTEGER NOT NULL,
        last_seen INTEGER NOT NULL
    );
    """,
)

EVENT_COLUMNS = (
    "ts",
    "visitor",
    "session",
    "kind",
    "path",
    "route",
    "sector",
    "referrer_path",
    "name",
    "country",
    "region",
    "city",
)


class WriteResult(NamedTuple):
    written: int
    dropped: int


class CompactionResult(NamedTuple):
    files_written: int
    rows_compacted: int


def hot_connection() -> sqlite3.Connection:
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
    conns: dict[str, sqlite3.Connection] = getattr(_local, "conns", None) or {}
    for conn in conns.values():
        try:
            conn.close()
        except sqlite3.Error:
            pass
    _local.conns = {}


def reset_route_cache() -> None:
    global _route_cache_loaded_for
    with _route_cache_lock:
        _known_routes.clear()
        _route_cache_loaded_for = None


def _load_route_cache(conn: sqlite3.Connection) -> None:
    global _route_cache_loaded_for
    path = str(hot_db_path())
    if _route_cache_loaded_for == path:
        return
    _known_routes.clear()
    for (route,) in conn.execute("SELECT route FROM usage_route"):
        _known_routes.add(route)
    _route_cache_loaded_for = path


def _sql_literal(value: str) -> str:
    return value.replace("'", "''")


def _clamp_text(value: Any, limit: int) -> str:
    text = _CONTROL_CHARS.sub("", str(value or "")).strip()
    if len(text) > limit:
        text = text[:limit]
    return text


def wipe() -> None:
    """Drop the hot db and parquet lake. Used when reseeding local demo data."""
    close_hot_connection()
    reset_route_cache()
    root = usage_dir()
    for name in ("usage.db", "usage.db-wal", "usage.db-shm"):
        path = root / name
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    lake = lake_dir()
    if lake.exists():
        import shutil

        shutil.rmtree(lake, ignore_errors=True)


def write_events(
    events: Sequence[dict[str, Any]],
    *,
    now: int | None = None,
    max_age_ms: int | None = DEFAULT_MAX_AGE_MS,
) -> WriteResult:
    """Append usage events. Drops rows whose route would exceed the cardinality cap."""
    now = int(now if now is not None else time.time())
    now_ms = now * 1000
    conn = hot_connection()
    with _route_cache_lock:
        _load_route_cache(conn)

    cap = max_routes()
    written = 0
    dropped = 0
    rows: list[tuple[Any, ...]] = []
    new_routes: dict[str, int] = {}

    for event in events:
        route = _clamp_text(event.get("route"), 512) or "/"
        with _route_cache_lock:
            known = route in _known_routes or route in new_routes
            if not known:
                if len(_known_routes) + len(new_routes) >= cap:
                    # Authoritative count in case other workers admitted routes.
                    count = conn.execute("SELECT COUNT(*) FROM usage_route").fetchone()
                    live = int(count[0]) if count else 0
                    if live >= cap and route not in _known_routes:
                        dropped += 1
                        continue
                new_routes[route] = now

        ts = event.get("ts")
        try:
            ts_ms = int(ts)
        except (TypeError, ValueError):
            ts_ms = now_ms
        if ts_ms < 1_000_000_000_000:
            ts_ms *= 1000
        if ts_ms > now_ms + 60_000:
            ts_ms = now_ms
        if max_age_ms is not None and ts_ms < now_ms - max_age_ms:
            ts_ms = now_ms

        kind = _clamp_text(event.get("kind"), 16) or "pageview"
        if kind not in ("pageview", "event"):
            kind = "pageview"

        rows.append(
            (
                ts_ms,
                _clamp_text(event.get("visitor"), 64) or "unknown",
                _clamp_text(event.get("session"), 64) or "unknown",
                kind,
                _clamp_text(event.get("path"), 512) or "/",
                route,
                _clamp_text(event.get("sector"), 128) or "(root)",
                _clamp_text(event.get("referrer_path"), 512) or None,
                _clamp_text(event.get("name"), 64) or None,
                _clamp_text(event.get("country"), 8) or None,
                _clamp_text(event.get("region"), 128) or None,
                _clamp_text(event.get("city"), 128) or None,
            )
        )
        written += 1

    if not rows:
        return WriteResult(written=0, dropped=dropped)

    with conn:
        conn.executemany(
            "INSERT INTO hot_event ("
            " ts, visitor, session, kind, path, route, sector,"
            " referrer_path, name, country, region, city"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        for route, seen in new_routes.items():
            conn.execute(
                "INSERT INTO usage_route (route, first_seen, last_seen) VALUES (?, ?, ?)"
                " ON CONFLICT(route) DO UPDATE SET last_seen = excluded.last_seen",
                (route, seen, seen),
            )

    with _route_cache_lock:
        _known_routes.update(new_routes)

    return WriteResult(written=written, dropped=dropped)


def _duckdb_connection():
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


def _partition_dir(day: str) -> Path:
    return lake_dir() / f"dt={day}"


def compact(*, now: int | None = None, older_than_seconds: int | None = None) -> CompactionResult:
    """Move hot rows older than the hot window into Parquet, one file per day."""
    now = int(now if now is not None else time.time())
    window = older_than_seconds if older_than_seconds is not None else hot_window_seconds()
    cutoff_ms = (now - window) * 1000

    conn = hot_connection()
    days = conn.execute(
        "SELECT DISTINCT date(ts / 1000, 'unixepoch') AS day"
        " FROM hot_event WHERE ts < ? ORDER BY day",
        (cutoff_ms,),
    ).fetchall()

    files_written = 0
    rows_compacted = 0
    for (day,) in days:
        written = _compact_day(conn, day=day, cutoff_ms=cutoff_ms)
        if written:
            files_written += 1
            rows_compacted += written

    if rows_compacted:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    return CompactionResult(files_written=files_written, rows_compacted=rows_compacted)


def _compact_day(conn: sqlite3.Connection, *, day: str, cutoff_ms: int) -> int:
    rows = conn.execute(
        "SELECT rowid, ts, visitor, session, kind, path, route, sector,"
        " referrer_path, name, country, region, city"
        " FROM hot_event"
        " WHERE ts < ? AND date(ts / 1000, 'unixepoch') = ?"
        " ORDER BY ts",
        (cutoff_ms, day),
    ).fetchall()
    if not rows:
        return 0

    rowids = [r[0] for r in rows]
    payload = [r[1:] for r in rows]

    target_dir = _partition_dir(day)
    target_dir.mkdir(parents=True, exist_ok=True)
    name = f"part-{min(rowids)}-{max(rowids)}-{len(rowids)}.parquet"
    final_path = target_dir / name
    tmp_path = target_dir / f"{name}.tmp"

    duck = _duckdb_connection()
    duck.execute("DROP TABLE IF EXISTS usage_compact_batch;")
    duck.execute(
        "CREATE TABLE usage_compact_batch ("
        " ts BIGINT, visitor VARCHAR, session VARCHAR, kind VARCHAR,"
        " path VARCHAR, route VARCHAR, sector VARCHAR, referrer_path VARCHAR,"
        " name VARCHAR, country VARCHAR, region VARCHAR, city VARCHAR)"
    )
    duck.executemany(
        "INSERT INTO usage_compact_batch VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        payload,
    )
    copy_sql = (
        "COPY (SELECT * FROM usage_compact_batch ORDER BY ts)"
        f" TO '{_sql_literal(str(tmp_path))}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )  # nosec B608 - sanitized path
    duck.execute(copy_sql)
    duck.execute("DROP TABLE IF EXISTS usage_compact_batch;")

    os.replace(tmp_path, final_path)
    with conn:
        conn.executemany("DELETE FROM hot_event WHERE rowid = ?", [(r,) for r in rowids])
    return len(rowids)


def apply_retention(*, now: int | None = None, days: int | None = None) -> int:
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


def _cold_glob() -> str | None:
    root = lake_dir()
    if not root.exists():
        return None
    return str(root / "dt=*" / "*.parquet")


def _cold_has_files() -> bool:
    root = lake_dir()
    if not root.exists():
        return False
    return any(root.glob("dt=*/*.parquet"))


def _load_events(start_ms: int, end_ms: int):
    """Register DuckDB table ``usage_events`` covering both tiers for the range."""
    duck = _duckdb_connection()
    duck.execute("DROP TABLE IF EXISTS usage_events;")
    duck.execute(
        "CREATE TABLE usage_events ("
        " ts BIGINT, visitor VARCHAR, session VARCHAR, kind VARCHAR,"
        " path VARCHAR, route VARCHAR, sector VARCHAR, referrer_path VARCHAR,"
        " name VARCHAR, country VARCHAR, region VARCHAR, city VARCHAR)"
    )

    hot_rows = (
        hot_connection()
        .execute(
            "SELECT ts, visitor, session, kind, path, route, sector,"
            " referrer_path, name, country, region, city"
            " FROM hot_event WHERE ts >= ? AND ts < ?",
            (start_ms, end_ms),
        )
        .fetchall()
    )
    if hot_rows:
        duck.executemany(
            "INSERT INTO usage_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            hot_rows,
        )

    if _cold_has_files():
        pattern = _cold_glob()
        if pattern:
            try:
                duck.execute(
                    "INSERT INTO usage_events SELECT ts, visitor, session, kind, path,"
                    " route, sector, referrer_path, name, country, region, city"
                    " FROM read_parquet(?, hive_partitioning = true, union_by_name = true)"
                    " WHERE ts >= ? AND ts < ?",
                    [pattern, start_ms, end_ms],
                )
            except Exception:
                logger.exception("Usage cold query failed")
    return duck


def _fetch_pairs(duck, sql: str, limit: int = MAX_DASHBOARD_ROWS) -> list[dict[str, Any]]:
    rows = duck.execute(sql).fetchall()
    out = []
    for row in rows[:limit]:
        out.append({"label": row[0] or "(none)", "count": int(row[1] or 0)})
    return out


def _fill_series(
    rows: list[dict[str, Any]], start_ms: int, end_ms: int, step_ms: int
) -> list[dict[str, Any]]:
    by_ts = {int(row["ts"]): int(row["value"]) for row in rows}
    t = (start_ms // step_ms) * step_ms
    filled = []
    while t < end_ms:
        filled.append({"ts": t, "value": by_ts.get(t, 0)})
        t += step_ms
    return filled


def dashboard(start_ms: int, end_ms: int, *, step_ms: int) -> dict[str, Any]:
    """Everything the Usage page needs for a time range."""
    empty = {
        "pageviews": 0,
        "uniques": 0,
        "sessions": 0,
        "bounce_rate": None,
        "bounced": 0,
        "pages_per_session": None,
        "avg_session_ms": None,
        "traffic": [],
        "traffic_users": [],
        "sectors": [],
        "pages": [],
        "routes": [],
        "entries": [],
        "exits": [],
        "transitions": [],
        "journeys": [],
        "events": [],
        "countries": [],
        "cities": [],
        "has_geo": False,
    }
    if step_ms <= 0 or end_ms <= start_ms:
        return empty

    duck = _load_events(start_ms, end_ms)
    total = duck.execute("SELECT COUNT(*) FROM usage_events WHERE kind = 'pageview'").fetchone()
    pageviews = int(total[0]) if total else 0
    if pageviews == 0 and not duck.execute("SELECT COUNT(*) FROM usage_events").fetchone()[0]:
        return empty

    uniques = int(
        duck.execute("SELECT COUNT(DISTINCT visitor) FROM usage_events").fetchone()[0] or 0
    )

    session_stats = duck.execute("""
        SELECT COUNT(*), AVG(duration), SUM(CASE WHEN views = 1 THEN 1 ELSE 0 END)
        FROM (
            SELECT session,
                   SUM(CASE WHEN kind = 'pageview' THEN 1 ELSE 0 END) AS views,
                   MAX(ts) - MIN(ts) AS duration
            FROM usage_events
            GROUP BY session
        )
        """).fetchone()
    sessions = int(session_stats[0] or 0) if session_stats else 0
    avg_session_ms = (
        int(session_stats[1]) if session_stats and session_stats[1] is not None else None
    )
    bounced = int(session_stats[2] or 0) if session_stats else 0
    bounce_rate = (bounced / sessions) if sessions else None
    pages_per_session = (pageviews / sessions) if sessions else None

    traffic_rows = duck.execute(
        "SELECT (ts // ?) * ? AS bucket, COUNT(*) FROM usage_events"
        " WHERE kind = 'pageview' GROUP BY 1 ORDER BY 1",
        [step_ms, step_ms],
    ).fetchall()
    traffic = _fill_series(
        [{"ts": int(row[0]), "value": int(row[1])} for row in traffic_rows],
        start_ms,
        end_ms,
        step_ms,
    )
    user_rows = duck.execute(
        "SELECT (ts // ?) * ? AS bucket, COUNT(DISTINCT visitor) FROM usage_events"
        " WHERE kind = 'pageview' GROUP BY 1 ORDER BY 1",
        [step_ms, step_ms],
    ).fetchall()
    traffic_users = _fill_series(
        [{"ts": int(row[0]), "value": int(row[1])} for row in user_rows],
        start_ms,
        end_ms,
        step_ms,
    )

    sectors = _fetch_pairs(
        duck,
        "SELECT sector, COUNT(*) FROM usage_events WHERE kind = 'pageview'"
        " GROUP BY 1 ORDER BY 2 DESC LIMIT 20",
    )
    page_rows = duck.execute(
        "SELECT route, COUNT(*), COUNT(DISTINCT visitor) FROM usage_events"
        " WHERE kind = 'pageview' GROUP BY 1 ORDER BY 2 DESC LIMIT 20"
    ).fetchall()
    pages = [
        {"label": row[0] or "/", "count": int(row[1] or 0), "users": int(row[2] or 0)}
        for row in page_rows
    ]
    routes = _fetch_pairs(
        duck,
        "SELECT route, COUNT(*) FROM usage_events WHERE kind = 'pageview'"
        " GROUP BY 1 ORDER BY 2 DESC LIMIT 20",
    )

    entries = _fetch_pairs(
        duck,
        """
        SELECT route, COUNT(*) FROM (
            SELECT route, row_number() OVER (PARTITION BY session ORDER BY ts) AS rn
            FROM usage_events WHERE kind = 'pageview'
        ) WHERE rn = 1 GROUP BY 1 ORDER BY 2 DESC LIMIT 20
        """,
    )
    exits = _fetch_pairs(
        duck,
        """
        SELECT route, COUNT(*) FROM (
            SELECT route, row_number() OVER (PARTITION BY session ORDER BY ts DESC) AS rn
            FROM usage_events WHERE kind = 'pageview'
        ) WHERE rn = 1 GROUP BY 1 ORDER BY 2 DESC LIMIT 20
        """,
    )

    transition_rows = duck.execute("""
        SELECT prev, route, COUNT(*) FROM (
            SELECT route, lag(route) OVER (PARTITION BY session ORDER BY ts) AS prev
            FROM usage_events WHERE kind = 'pageview'
        ) WHERE prev IS NOT NULL AND prev <> route
        GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 80
        """).fetchall()
    transitions = [{"frm": row[0], "to": row[1], "count": int(row[2])} for row in transition_rows]

    journey_rows = duck.execute("""
        WITH ordered AS (
            SELECT session, route, ts,
                   lag(route) OVER (PARTITION BY session ORDER BY ts) AS prev
            FROM usage_events WHERE kind = 'pageview'
        ),
        steps AS (
            SELECT session, route, ts,
                   row_number() OVER (PARTITION BY session ORDER BY ts) AS rn
            FROM ordered
            WHERE prev IS NULL OR prev <> route
        ),
        totals AS (
            SELECT session, max(rn) AS n FROM steps GROUP BY session
        ),
        capped AS (
            SELECT s.session,
                   string_agg(s.route, ' → ' ORDER BY s.rn) AS journey
            FROM steps s
            WHERE s.rn <= 5
            GROUP BY s.session
        )
        SELECT CASE WHEN t.n > 5 THEN c.journey || ' → …' ELSE c.journey END,
               COUNT(*)
        FROM capped c
        JOIN totals t USING (session)
        WHERE t.n >= 2
        GROUP BY 1
        ORDER BY 2 DESC
        LIMIT 10
        """).fetchall()
    journeys = [{"label": row[0], "count": int(row[1])} for row in journey_rows]

    event_rows = duck.execute(
        "SELECT name, COUNT(*) FROM usage_events WHERE kind = 'event' AND name IS NOT NULL"
        " GROUP BY 1 ORDER BY 2 DESC LIMIT 20"
    ).fetchall()
    events = [{"label": row[0], "count": int(row[1])} for row in event_rows]

    country_rows = duck.execute(
        "SELECT country, COUNT(*) FROM usage_events"
        " WHERE country IS NOT NULL AND country <> ''"
        " GROUP BY 1 ORDER BY 2 DESC LIMIT 20"
    ).fetchall()
    countries = [{"label": row[0], "count": int(row[1])} for row in country_rows]

    city_rows = duck.execute(
        """
        SELECT city, country, cnt FROM (
            SELECT city, country, cnt,
                   row_number() OVER (
                       PARTITION BY country
                       ORDER BY cnt DESC
                   ) AS rn
            FROM (
                SELECT city, country, COUNT(*) AS cnt
                FROM usage_events
                WHERE city IS NOT NULL AND city <> ''
                GROUP BY city, country
            )
        )
        WHERE rn <= ?
        ORDER BY cnt DESC
        """,
        [MAX_DASHBOARD_ROWS],
    ).fetchall()
    cities = [
        {"label": row[0], "country": row[1] or None, "count": int(row[2])}
        for row in city_rows
    ]

    return {
        "pageviews": pageviews,
        "uniques": uniques,
        "sessions": sessions,
        "bounce_rate": bounce_rate,
        "bounced": bounced,
        "pages_per_session": pages_per_session,
        "avg_session_ms": avg_session_ms,
        "traffic": traffic,
        "traffic_users": traffic_users,
        "sectors": sectors,
        "pages": pages,
        "routes": routes,
        "entries": entries,
        "exits": exits,
        "transitions": transitions,
        "journeys": journeys,
        "events": events,
        "countries": countries,
        "cities": cities,
        "has_geo": bool(countries or cities),
    }


def store_stats() -> dict[str, Any]:
    conn = hot_connection()
    hot_rows = conn.execute("SELECT COUNT(*) FROM hot_event").fetchone()
    routes = conn.execute("SELECT COUNT(*) FROM usage_route").fetchone()
    hot_bytes = hot_db_path().stat().st_size if hot_db_path().exists() else 0
    lake_bytes = 0
    root = lake_dir()
    if root.exists():
        for path in root.rglob("*.parquet"):
            try:
                lake_bytes += path.stat().st_size
            except OSError:
                pass
    return {
        "retention_days": retention_days(),
        "hot_rows": int(hot_rows[0]) if hot_rows else 0,
        "route_count": int(routes[0]) if routes else 0,
        "hot_bytes": hot_bytes,
        "lake_bytes": lake_bytes,
    }
