"""Background maintenance for the usage lake: compaction and retention."""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid

from . import usage_store
from .features import FEATURE_USAGE, is_feature_enabled

logger = logging.getLogger(__name__)

LOCK_KEY = "broke:usage:compaction-lock"
INITIAL_DELAY_SECONDS = 75
_started = False
_start_lock = threading.Lock()
_UNGUARDED = "unguarded"

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
    now = int(now if now is not None else time.time())
    removed_temp = usage_store.cleanup_orphan_temp_files()
    result = usage_store.compact(now=now)
    removed_partitions = usage_store.apply_retention(now=now)
    if result.rows_compacted or removed_partitions:
        logger.info(
            "Usage maintenance: %s rows into %s file(s), %s expired partition(s) removed",
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
    interval = usage_store.compact_interval_seconds()
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
        interval = usage_store.compact_interval_seconds()
        if not is_feature_enabled(FEATURE_USAGE):
            logger.info("Usage feature disabled; stopping compaction thread")
            return
        try:
            run_locked_maintenance()
        except Exception:
            logger.exception("Usage maintenance sweep failed")
        time.sleep(interval)


def start_usage_worker() -> bool:
    global _started
    if os.environ.get("USAGE_COMPACTION_IN_PROCESS", "1") in ("0", "false", "False"):
        return False
    if not is_feature_enabled(FEATURE_USAGE):
        return False

    with _start_lock:
        if _started:
            return False
        _started = True

    thread = threading.Thread(target=_loop, daemon=True, name="usage-compactor")
    thread.start()
    logger.info("Usage compaction thread started")
    return True
