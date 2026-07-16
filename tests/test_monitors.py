import os
import time
from unittest.mock import MagicMock, patch

from fixtures import auth_client, test_project
from ward import test

from app.utils.events import EventTypes
from app.utils.features import FEATURE_MONITORS
from app.utils.models import Monitor, MonitorCheck
from app.utils.monitors import (
    apply_check_result,
    clamp_interval,
    heartbeat_slots,
    perform_http_check,
    prune_old_checks,
    uptime_percent,
    validate_monitor_url,
)


def _make_monitor(project, **kwargs):
    defaults = dict(
        project=project,
        name="M",
        url="https://example.com",
        interval_seconds=60,
        timeout_seconds=10,
        expected_status=200,
        enabled=1,
        status="unknown",
        created_at=int(time.time()),
    )
    defaults.update(kwargs)
    return Monitor.create(**defaults)


def _cleanup_monitor(m):
    if not m:
        return
    MonitorCheck.delete().where(MonitorCheck.monitor == m.id).execute()
    if Monitor.get_or_none(Monitor.id == m.id):
        m.delete_instance()


@test("validate_monitor_url accepts http(s) only")
def _():
    assert validate_monitor_url("https://example.com/health") is None
    assert validate_monitor_url("http://example.com") is None
    assert validate_monitor_url("ftp://example.com") is not None
    assert validate_monitor_url("not-a-url") is not None
    assert validate_monitor_url("") is not None


@test("clamp_interval enforces minimum 60")
def _():
    assert clamp_interval(30) == 60
    assert clamp_interval(120) == 120
    assert clamp_interval("bad") == 60


@test("POST /api/monitors creates a monitor", tags=["api"])
def _(auth_client=auth_client, test_project=test_project):
    r = auth_client.post(
        "/api/monitors",
        json={
            "project": test_project.id,
            "name": "Homepage",
            "url": "https://example.com/",
            "interval_seconds": 60,
            "expected_status": 200,
            "timeout_seconds": 10,
        },
    )
    assert r.status_code == 201
    data = r.get_json()
    assert data["monitor"]["name"] == "Homepage"
    assert data["monitor"]["status"] == "unknown"
    assert "heartbeat" in data["monitor"]
    assert data["monitor"]["uptime_24h"] is None
    mid = data["monitor"]["id"]
    Monitor.delete_by_id(mid)


@test("POST /api/monitors rejects invalid url", tags=["api"])
def _(auth_client=auth_client, test_project=test_project):
    r = auth_client.post(
        "/api/monitors",
        json={
            "project": test_project.id,
            "name": "Bad",
            "url": "ftp://example.com/",
        },
    )
    assert r.status_code == 400


@test("PATCH and DELETE /api/monitors/<id>", tags=["api"])
def _(auth_client=auth_client, test_project=test_project):
    m = _make_monitor(test_project, name="API", url="https://example.com/api")
    try:
        r = auth_client.patch(
            f"/api/monitors/{m.id}",
            json={"name": "API v2", "enabled": False},
        )
        assert r.status_code == 200
        body = r.get_json()["monitor"]
        assert body["name"] == "API v2"
        assert body["enabled"] is False

        r2 = auth_client.delete(f"/api/monitors/{m.id}")
        assert r2.status_code == 200
        assert Monitor.get_or_none(Monitor.id == m.id) is None
    finally:
        _cleanup_monitor(m)


@test("monitors feature flag returns 404 when disabled", tags=["api"])
def _(auth_client=auth_client, test_project=test_project):
    with patch.dict(os.environ, {"BROKE_DISABLED_FEATURES": FEATURE_MONITORS}):
        r = auth_client.get("/api/monitors")
        assert r.status_code == 404
        r2 = auth_client.get("/monitors")
        assert r2.status_code == 404


@test("perform_http_check treats matching status as ok")
def _():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch("app.utils.monitors.requests.get", return_value=mock_resp) as get:
        ok, err, code, ms = perform_http_check(
            "https://example.com", expected_status=200, timeout_seconds=5
        )
        assert ok is True
        assert err is None
        assert code == 200
        assert ms is not None
        get.assert_called_once()


@test("perform_http_check fails on unexpected status")
def _():
    mock_resp = MagicMock()
    mock_resp.status_code = 503
    with patch("app.utils.monitors.requests.get", return_value=mock_resp):
        ok, err, code, ms = perform_http_check("https://example.com", expected_status=200)
        assert ok is False
        assert "503" in (err or "")
        assert code == 503


@test("apply_check_result records MonitorCheck and last_response_ms")
def _(test_project=test_project):
    m = _make_monitor(test_project)
    try:
        with patch("app.utils.monitors.bus.emit"):
            apply_check_result(m, ok=True, error=None, status_code=200, response_ms=42)
        m = Monitor.get_by_id(m.id)
        assert m.last_response_ms == 42
        checks = list(MonitorCheck.select().where(MonitorCheck.monitor == m.id))
        assert len(checks) == 1
        assert checks[0].ok == 1
        assert checks[0].response_ms == 42
        assert checks[0].status_code == 200
    finally:
        _cleanup_monitor(m)


@test("apply_check_result unknown→up does not emit MONITOR_UP")
def _(test_project=test_project):
    m = _make_monitor(test_project, name="U")
    try:
        with patch("app.utils.monitors.bus.emit") as emit:
            emitted = apply_check_result(m, ok=True, error=None, response_ms=10)
            assert emitted is None
            emit.assert_not_called()
        m = Monitor.get_by_id(m.id)
        assert m.status == "up"
    finally:
        _cleanup_monitor(m)


@test("apply_check_result up→down emits MONITOR_DOWN")
def _(test_project=test_project):
    m = _make_monitor(test_project, name="D", status="up")
    try:
        with patch("app.utils.monitors.bus.emit") as emit:
            emitted = apply_check_result(m, ok=False, error="Timeout after 10s", response_ms=10000)
            assert emitted == EventTypes.MONITOR_DOWN
            emit.assert_called_once()
            assert emit.call_args[0][0] == EventTypes.MONITOR_DOWN
        m = Monitor.get_by_id(m.id)
        assert m.status == "down"
        assert "Timeout" in (m.last_error or "")
    finally:
        _cleanup_monitor(m)


@test("apply_check_result down→up emits MONITOR_UP")
def _(test_project=test_project):
    m = _make_monitor(test_project, name="R", status="down", last_error="was down")
    try:
        with patch("app.utils.monitors.bus.emit") as emit:
            emitted = apply_check_result(m, ok=True, error=None, response_ms=12)
            assert emitted == EventTypes.MONITOR_UP
            emit.assert_called_once()
            assert emit.call_args[0][0] == EventTypes.MONITOR_UP
        m = Monitor.get_by_id(m.id)
        assert m.status == "up"
        assert m.last_error is None
    finally:
        _cleanup_monitor(m)


@test("apply_check_result unknown→down emits MONITOR_DOWN")
def _(test_project=test_project):
    m = _make_monitor(test_project, name="First fail")
    try:
        with patch("app.utils.monitors.bus.emit") as emit:
            emitted = apply_check_result(
                m, ok=False, error="Expected status 200, got 500", status_code=500
            )
            assert emitted == EventTypes.MONITOR_DOWN
            emit.assert_called_once()
    finally:
        _cleanup_monitor(m)


@test("heartbeat_slots: down wins; empty when no data")
def _(test_project=test_project):
    m = _make_monitor(test_project, name="HB")
    now = int(time.time())
    try:
        empty = heartbeat_slots(m.id, hours=24, slots=4, now=now)
        assert len(empty) == 4
        assert all(s["state"] == "empty" for s in empty)

        # Put a failure in the last slot and a success in an earlier slot of same window
        MonitorCheck.create(
            monitor=m, checked_at=now - 100, ok=0, status_code=500, response_ms=5, error="fail"
        )
        MonitorCheck.create(
            monitor=m, checked_at=now - 20 * 3600, ok=1, status_code=200, response_ms=20, error=None
        )
        slots = heartbeat_slots(m.id, hours=24, slots=4, now=now)
        assert slots[-1]["state"] == "down"
        assert any(s["state"] == "up" for s in slots[:-1])
    finally:
        _cleanup_monitor(m)


@test("uptime_percent with mixed ok/fail")
def _(test_project=test_project):
    m = _make_monitor(test_project, name="UP")
    now = int(time.time())
    try:
        assert uptime_percent(m.id, now=now) is None
        for ok in (1, 1, 0, 1):
            MonitorCheck.create(
                monitor=m,
                checked_at=now - 60,
                ok=ok,
                status_code=200 if ok else 500,
                response_ms=10,
                error=None if ok else "x",
            )
        pct = uptime_percent(m.id, now=now)
        assert pct == 75.0
    finally:
        _cleanup_monitor(m)


@test("prune_old_checks removes older than retention cutoff")
def _(test_project=test_project):
    m = _make_monitor(test_project, name="PR")
    now = int(time.time())
    try:
        old = MonitorCheck.create(
            monitor=m, checked_at=now - 100000, ok=1, status_code=200, response_ms=1, error=None
        )
        recent = MonitorCheck.create(
            monitor=m, checked_at=now - 10, ok=1, status_code=200, response_ms=1, error=None
        )
        deleted = prune_old_checks(older_than=now - 1000)
        assert deleted >= 1
        assert MonitorCheck.get_or_none(MonitorCheck.id == old.id) is None
        assert MonitorCheck.get_or_none(MonitorCheck.id == recent.id) is not None
    finally:
        _cleanup_monitor(m)
