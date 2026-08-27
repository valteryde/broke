"""Usage lake: write, dashboard aggregates, compaction."""

import os
import shutil
import tempfile
import time
from pathlib import Path

from ward import Scope, fixture, test

from app.utils import usage_store


@fixture(scope=Scope.Test)
def usage_home():
    tmp = tempfile.mkdtemp(prefix="broke_usage_test_")
    previous = os.environ.get("BROKE_USAGE_DIR")
    os.environ["BROKE_USAGE_DIR"] = tmp
    usage_store.close_hot_connection()
    usage_store.reset_route_cache()
    yield Path(tmp)
    usage_store.close_hot_connection()
    usage_store.reset_route_cache()
    if previous is None:
        os.environ.pop("BROKE_USAGE_DIR", None)
    else:
        os.environ["BROKE_USAGE_DIR"] = previous
    shutil.rmtree(tmp, ignore_errors=True)


def _event(**kwargs):
    now = int(time.time() * 1000)
    row = {
        "ts": now,
        "visitor": "visitor-aaaaaaa",
        "session": "session-aaaaaa",
        "kind": "pageview",
        "path": "/tickets",
        "route": "/tickets",
        "sector": "tickets",
        "referrer_path": None,
        "name": None,
        "country": None,
        "region": None,
        "city": None,
    }
    row.update(kwargs)
    if "path" in kwargs and "route" not in kwargs:
        row["route"] = kwargs["path"]
    return row


@test("write_events stores pageviews and counts uniques")
def _(home=usage_home):
    now = int(time.time() * 1000)
    usage_store.write_events(
        [
            _event(ts=now, visitor="visitor-11111111", session="session-111111"),
            _event(ts=now + 1, visitor="visitor-22222222", session="session-222222"),
            _event(ts=now + 2, visitor="visitor-11111111", session="session-111111", path="/"),
        ]
    )
    data = usage_store.dashboard(now - 1000, now + 10_000, step_ms=1000)
    assert data["pageviews"] == 3
    assert data["uniques"] == 2
    assert data["sessions"] == 2


@test("bounce is sessions with a single pageview")
def _(home=usage_home):
    now = int(time.time() * 1000)
    usage_store.write_events(
        [
            _event(ts=now, visitor="visitor-11111111", session="session-bounce1"),
            _event(ts=now, visitor="visitor-22222222", session="session-stay111", path="/a"),
            _event(ts=now + 1, visitor="visitor-22222222", session="session-stay111", path="/b"),
        ]
    )
    data = usage_store.dashboard(now - 1000, now + 10_000, step_ms=1000)
    assert data["sessions"] == 2
    assert data["bounce_rate"] == 0.5


@test("from-to transitions follow session order")
def _(home=usage_home):
    now = int(time.time() * 1000)
    usage_store.write_events(
        [
            _event(ts=now, session="session-flow111", path="/a"),
            _event(ts=now + 10, session="session-flow111", path="/b"),
            _event(ts=now + 20, session="session-flow111", path="/c"),
        ]
    )
    data = usage_store.dashboard(now - 1000, now + 10_000, step_ms=1000)
    pairs = {(row["frm"], row["to"]) for row in data["transitions"]}
    assert ("/a", "/b") in pairs
    assert ("/b", "/c") in pairs
    labels = {row["label"] for row in data["journeys"]}
    assert "/a → /b → /c" in labels
    assert "/a → /b" not in labels


@test("pages and journeys collapse ticket ids onto the route")
def _(home=usage_home):
    now = int(time.time() * 1000)
    usage_store.write_events(
        [
            _event(
                ts=now,
                session="session-ticket01",
                path="/tickets/BAC-101",
                route="/tickets/:id",
                sector="tickets",
            ),
            _event(
                ts=now + 10,
                session="session-ticket01",
                path="/tickets/BAC-106",
                route="/tickets/:id",
                sector="tickets",
            ),
            _event(
                ts=now + 20,
                session="session-ticket01",
                path="/settings",
                route="/settings",
                sector="settings",
            ),
            _event(
                ts=now,
                session="session-ticket02",
                visitor="visitor-bbbbbbbb",
                path="/tickets/FRO-110",
                route="/tickets/:id",
                sector="tickets",
            ),
        ]
    )
    data = usage_store.dashboard(now - 1000, now + 10_000, step_ms=1000)
    page_labels = {row["label"] for row in data["pages"]}
    assert "/tickets/:id" in page_labels
    assert "/tickets/BAC-101" not in page_labels
    ticket_page = next(row for row in data["pages"] if row["label"] == "/tickets/:id")
    assert ticket_page["count"] == 3
    assert ticket_page["users"] == 2
    pairs = {(row["frm"], row["to"]) for row in data["transitions"]}
    assert ("/tickets/:id", "/settings") in pairs
    assert ("/tickets/:id", "/tickets/:id") not in pairs
    labels = {row["label"] for row in data["journeys"]}
    assert "/tickets/:id → /settings" in labels
    entry_labels = {row["label"] for row in data["entries"]}
    exit_labels = {row["label"] for row in data["exits"]}
    assert "/tickets/:id" in entry_labels
    assert "/settings" in exit_labels


@test("compact moves old hot rows into parquet")
def _(home=usage_home):
    now = int(time.time())
    old_ms = (now - 7200) * 1000
    usage_store.write_events([_event(ts=old_ms)])
    result = usage_store.compact(now=now, older_than_seconds=3600)
    assert result.rows_compacted == 1
    conn = usage_store.hot_connection()
    left = conn.execute("SELECT COUNT(*) FROM hot_event").fetchone()[0]
    assert left == 0
    assert any(home.joinpath("usage").glob("dt=*/*.parquet"))
