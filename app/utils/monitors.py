"""HTTP(S) uptime check helpers used by the monitor worker and tests."""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urlparse

import requests

from .email_branding import email_base_url
from .events import EventTypes, bus
from .models import Monitor, MonitorCheck

logger = logging.getLogger(__name__)

MIN_INTERVAL_SECONDS = 60
MAX_TIMEOUT_SECONDS = 60
DEFAULT_TIMEOUT_SECONDS = 10
DEFAULT_INTERVAL_SECONDS = 60
DEFAULT_EXPECTED_STATUS = 200
CHECK_RETENTION_SECONDS = 48 * 3600
HEARTBEAT_HOURS = 24
HEARTBEAT_SLOTS = 48


def validate_monitor_url(url: str) -> str | None:
    """Return an error message if url is invalid, else None."""
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme.lower() not in {"http", "https"}:
        return "URL must use http or https"
    if not parsed.netloc:
        return "URL must include a host"
    return None


def clamp_interval(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL_SECONDS
    return max(MIN_INTERVAL_SECONDS, n)


def clamp_timeout(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS
    return max(1, min(MAX_TIMEOUT_SECONDS, n))


def perform_http_check(
    url: str,
    *,
    expected_status: int = DEFAULT_EXPECTED_STATUS,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[bool, str | None, int | None, int | None]:
    """
    GET url and return (ok, error_message, status_code, response_ms).
    ok is True when status matches expected_status.
    """
    started = time.perf_counter()
    try:
        response = requests.get(
            url,
            timeout=timeout_seconds,
            allow_redirects=True,
            headers={"User-Agent": "BrokeMonitor/1.0"},
        )
    except requests.Timeout:
        ms = int((time.perf_counter() - started) * 1000)
        return False, f"Timeout after {timeout_seconds}s", None, ms
    except requests.RequestException as exc:
        ms = int((time.perf_counter() - started) * 1000)
        msg = str(exc).strip() or exc.__class__.__name__
        return False, msg[:500], None, ms

    ms = int((time.perf_counter() - started) * 1000)
    if response.status_code != expected_status:
        return (
            False,
            f"Expected status {expected_status}, got {response.status_code}",
            response.status_code,
            ms,
        )
    return True, None, response.status_code, ms


def _monitor_event_kwargs(monitor: Monitor, *, status: str, details: str) -> dict[str, Any]:
    base = email_base_url().strip().rstrip("/")
    monitor_url = f"{base}/monitors/{monitor.id}" if base else None
    project_id = monitor.project_id if hasattr(monitor, "project_id") else str(monitor.project)
    return {
        "project": str(project_id),
        "actor": "monitor",
        "status": status,
        "details": details,
        "monitor_id": monitor.id,
        "monitor_name": monitor.name,
        "monitor_url": monitor_url,
    }


def prune_old_checks(*, older_than: int | None = None) -> int:
    """Delete MonitorCheck rows older than retention. Returns deleted count."""
    cutoff = int(older_than if older_than is not None else time.time() - CHECK_RETENTION_SECONDS)
    return MonitorCheck.delete().where(MonitorCheck.checked_at < cutoff).execute()


def apply_check_result(
    monitor: Monitor,
    *,
    ok: bool,
    error: str | None,
    status_code: int | None = None,
    response_ms: int | None = None,
    now: int | None = None,
    emit: bool = True,
    record_check: bool = True,
) -> str | None:
    """
    Update monitor from a check result. Returns the event type emitted, if any.
    Transitions:
      - unknown → up: no event
      - unknown → down: MONITOR_DOWN
      - up → down: MONITOR_DOWN
      - down → up: MONITOR_UP
      - same status: no event
    """
    ts = int(now if now is not None else time.time())
    previous = (monitor.status or "unknown").strip().lower()
    new_status = "up" if ok else "down"

    monitor.last_checked_at = ts
    monitor.last_error = None if ok else (error or "Check failed")[:500]
    if response_ms is not None:
        monitor.last_response_ms = int(response_ms)

    if record_check:
        MonitorCheck.create(
            monitor=monitor,
            checked_at=ts,
            ok=1 if ok else 0,
            status_code=status_code,
            response_ms=response_ms,
            error=None if ok else (error or "Check failed")[:500],
        )

    emitted: str | None = None
    if previous != new_status:
        monitor.status = new_status
        monitor.last_status_change_at = ts
        if emit:
            if new_status == "down":
                details = f"{monitor.name} ({monitor.url}): {monitor.last_error}"
                bus.emit(
                    EventTypes.MONITOR_DOWN,
                    **_monitor_event_kwargs(monitor, status="down", details=details),
                )
                emitted = EventTypes.MONITOR_DOWN
            elif new_status == "up" and previous == "down":
                details = f"{monitor.name} ({monitor.url}): recovered"
                bus.emit(
                    EventTypes.MONITOR_UP,
                    **_monitor_event_kwargs(monitor, status="up", details=details),
                )
                emitted = EventTypes.MONITOR_UP
    else:
        monitor.status = new_status

    monitor.save()
    return emitted


def due_monitors(now: int | None = None) -> list[Monitor]:
    """Enabled monitors whose interval has elapsed (or never checked)."""
    ts = int(now if now is not None else time.time())
    due: list[Monitor] = []
    for m in Monitor.select().where(Monitor.enabled == 1):
        if m.last_checked_at is None:
            due.append(m)
            continue
        interval = max(MIN_INTERVAL_SECONDS, int(m.interval_seconds or DEFAULT_INTERVAL_SECONDS))
        if ts - int(m.last_checked_at) >= interval:
            due.append(m)
    return due


def run_due_checks(*, emit: bool = True) -> int:
    """Check all due monitors. Returns number of checks performed."""
    count = 0
    for monitor in due_monitors():
        ok, error, status_code, response_ms = perform_http_check(
            monitor.url,
            expected_status=int(monitor.expected_status or DEFAULT_EXPECTED_STATUS),
            timeout_seconds=clamp_timeout(monitor.timeout_seconds),
        )
        apply_check_result(
            monitor,
            ok=ok,
            error=error,
            status_code=status_code,
            response_ms=response_ms,
            emit=emit,
        )
        count += 1
        logger.info(
            "monitor check id=%s name=%s ok=%s ms=%s error=%s",
            monitor.id,
            monitor.name,
            ok,
            response_ms,
            error,
        )
    if count:
        deleted = prune_old_checks()
        if deleted:
            logger.info("Pruned %s old monitor check(s)", deleted)
    return count


def _window_start(now: int, hours: int) -> int:
    return int(now) - int(hours) * 3600


def heartbeat_slots(
    monitor_id: int,
    *,
    hours: int = HEARTBEAT_HOURS,
    slots: int = HEARTBEAT_SLOTS,
    now: int | None = None,
) -> list[dict[str, Any]]:
    """
    Bucket last `hours` into `slots` cells.
    State: down if any failure in slot, else up if any success, else empty.
    """
    ts = int(now if now is not None else time.time())
    window = max(1, int(hours)) * 3600
    n_slots = max(1, int(slots))
    slot_len = window // n_slots
    start = ts - window

    result: list[dict[str, Any]] = []
    for i in range(n_slots):
        t0 = start + i * slot_len
        t1 = start + (i + 1) * slot_len if i < n_slots - 1 else ts
        result.append({"t0": t0, "t1": t1, "state": "empty"})

    checks = (
        MonitorCheck.select()
        .where(
            (MonitorCheck.monitor == monitor_id)
            & (MonitorCheck.checked_at >= start)
            & (MonitorCheck.checked_at <= ts)
        )
        .order_by(MonitorCheck.checked_at.asc())
    )
    for check in checks:
        idx = min(n_slots - 1, max(0, (int(check.checked_at) - start) // slot_len))
        cell = result[idx]
        if check.ok == 0:
            cell["state"] = "down"
        elif cell["state"] == "empty":
            cell["state"] = "up"
    return result


def uptime_percent(
    monitor_id: int,
    *,
    hours: int = HEARTBEAT_HOURS,
    now: int | None = None,
) -> float | None:
    """Return 0–100 uptime percentage, or None if no checks in the window."""
    ts = int(now if now is not None else time.time())
    start = _window_start(ts, hours)
    q = MonitorCheck.select().where(
        (MonitorCheck.monitor == monitor_id) & (MonitorCheck.checked_at >= start)
    )
    total = q.count()
    if total == 0:
        return None
    ok_count = q.where(MonitorCheck.ok == 1).count()
    return round(100.0 * ok_count / total, 2)


def avg_response_ms(
    monitor_id: int,
    *,
    hours: int = HEARTBEAT_HOURS,
    now: int | None = None,
) -> int | None:
    """Average response_ms over checks that recorded a latency."""
    ts = int(now if now is not None else time.time())
    start = _window_start(ts, hours)
    rows = list(
        MonitorCheck.select(MonitorCheck.response_ms).where(
            (MonitorCheck.monitor == monitor_id)
            & (MonitorCheck.checked_at >= start)
            & (MonitorCheck.response_ms.is_null(False))
        )
    )
    values = [int(r.response_ms) for r in rows if r.response_ms is not None]
    if not values:
        return None
    return int(round(sum(values) / len(values)))


def monitor_stats(monitor: Monitor, *, now: int | None = None) -> dict[str, Any]:
    """Bundle heartbeat + uptime stats for UI/API."""
    mid = int(monitor.id)
    return {
        "uptime_24h": uptime_percent(mid, now=now),
        "avg_response_ms": avg_response_ms(mid, now=now),
        "last_response_ms": monitor.last_response_ms,
        "heartbeat": heartbeat_slots(mid, now=now),
    }
