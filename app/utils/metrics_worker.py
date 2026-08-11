"""
Background maintenance for the metrics lake: compaction and retention.

Two gunicorn workers plus the monitor container all import this module, so the sweep is
guarded by a Redis lock and only one process does the work per interval. Redis is already
a hard dependency, which avoids adding another container just to run a timer.

Installs that would rather isolate the work can disable the in-process thread with
``METRICS_COMPACTION_IN_PROCESS=0`` and run ``python -m app.metrics_worker`` instead; both
paths call :func:`run_maintenance`.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid

from .features import FEATURE_METRICS, is_feature_enabled
from . import metrics_store

logger = logging.getLogger(__name__)

LOCK_KEY = "broke:metrics:compaction-lock"
INITIAL_DELAY_SECONDS = 60
_started = False
_start_lock = threading.Lock()

# Stands in for a token when there is no usable Redis and the sweep runs unguarded,
# so the release path knows there is nothing to free.
_UNGUARDED = "unguarded"

# Redis has no atomic "delete only if I still hold it". Without this compare-and-delete,
# a sweep that outran its TTL would free a lock another process had already taken.
_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


def _redis_client():
    try:
        import redis as redis_lib

        url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        return redis_lib.from_url(url, socket_connect_timeout=2, socket_timeout=2)
    except Exception:
        return None


def _acquire_lock(client, ttl: int) -> str | None:
    """Best effort mutual exclusion. Without Redis, fall through and run anyway.

    Compaction is idempotent, so a rare double run costs duplicated effort, not data.
    Returns the token to release with, or None when another process holds the lock. The
    token is unique per acquisition because a pid alone repeats across containers.
    """
    if client is None:
        return _UNGUARDED
    token = f"{os.getpid()}:{uuid.uuid4().hex}"
    try:
        return token if client.set(LOCK_KEY, token, nx=True, ex=ttl) else None
    except Exception:
        return _UNGUARDED


def _release_lock(client, token: str | None) -> None:
    if client is None or token is None or token == _UNGUARDED:
        return
    try:
        client.eval(_RELEASE_SCRIPT, 1, LOCK_KEY, token)
    except Exception:
        pass


def run_maintenance(*, now: int | None = None) -> dict[str, int]:
    """Run one compaction and retention sweep. Safe to call from anywhere."""
    now = int(now if now is not None else time.time())

    removed_temp = metrics_store.cleanup_orphan_temp_files()
    result = metrics_store.compact(now=now)
    removed_partitions = metrics_store.apply_retention(now=now)

    if result.rows_compacted or removed_partitions:
        logger.info(
            "Metrics maintenance: %s rows into %s file(s), %s expired partition(s) removed",
            result.rows_compacted,
            result.files_written,
            removed_partitions,
        )
    return {
        "files_written": result.files_written,
        "rows_compacted": result.rows_compacted,
        "partitions_removed": removed_partitions,
        "temp_files_removed": removed_temp,
    }


def run_locked_maintenance(*, now: int | None = None) -> dict[str, int] | None:
    """Run a sweep only if this process wins the Redis lock."""
    interval = metrics_store.compact_interval_seconds()
    client = _redis_client()
    token = _acquire_lock(client, max(30, interval - 5))
    if token is None:
        return None
    try:
        return run_maintenance(now=now)
    finally:
        _release_lock(client, token)


def _loop() -> None:
    time.sleep(INITIAL_DELAY_SECONDS)
    while True:
        interval = metrics_store.compact_interval_seconds()
        if not is_feature_enabled(FEATURE_METRICS):
            logger.info("Metrics feature disabled; stopping compaction thread")
            return
        try:
            run_locked_maintenance()
        except Exception:
            logger.exception("Metrics maintenance sweep failed")
        time.sleep(interval)


def start_metrics_worker() -> bool:
    """Start the in-process compaction thread once per process."""
    global _started
    if os.environ.get("METRICS_COMPACTION_IN_PROCESS", "1") in ("0", "false", "False"):
        return False
    if not is_feature_enabled(FEATURE_METRICS):
        return False

    with _start_lock:
        if _started:
            return False
        _started = True

    thread = threading.Thread(target=_loop, daemon=True, name="metrics-compactor")
    thread.start()
    logger.info("Metrics compaction thread started")
    return True
