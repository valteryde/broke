"""Telegraf-style isolated ingest tests for the usage beacon endpoint."""

import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from ward import Scope, fixture, test

from app.utils import usage_store
from app.utils.models import UsageToken
from app.utils.usage_auth import generate_token, hash_token
from tests.fixtures import app, auth_client, client


@fixture(scope=Scope.Test)
def usage_home():
    tmp = tempfile.mkdtemp(prefix="broke_usage_ingest_")
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


@fixture(scope=Scope.Test)
def usage_key(app=app):
    UsageToken.delete().execute()
    raw = generate_token()
    UsageToken.create(
        token_hash=hash_token(raw),
        token_preview=raw[:8],
        created_at=int(time.time()),
    )
    yield raw
    UsageToken.delete().execute()


def _post(c, raw_key, payload):
    body = dict(payload)
    body["k"] = raw_key
    return c.post(
        "/ingest/usage",
        data=json.dumps(body),
        content_type="text/plain",
    )


@test("POST /ingest/usage rejects a missing key")
def _(c=client, home=usage_home):
    response = c.post(
        "/ingest/usage",
        data=json.dumps({"vid": "visitor-aaaaaaa", "sid": "session-aaaaaa", "e": []}),
        content_type="text/plain",
    )
    assert response.status_code == 401


@test("POST /ingest/usage rejects a query-string key")
def _(c=client, home=usage_home, raw=usage_key):
    response = c.post(
        f"/ingest/usage?k={raw}",
        data=json.dumps(
            {
                "vid": "visitor-aaaaaaa",
                "sid": "session-aaaaaa",
                "e": [{"kind": "pageview", "path": "/"}],
            }
        ),
        content_type="text/plain",
    )
    assert response.status_code == 401


@test("POST /ingest/usage stores a normalized ticket path")
def _(c=client, home=usage_home, raw=usage_key):
    with patch(
        "app.views.usage.ip_lookup.resolve_geo",
        return_value={"country": "DK", "region": "Hovedstaden", "city": "Copenhagen"},
    ):
        response = _post(
            c,
            raw,
            {
                "vid": "visitor-aaaaaaa",
                "sid": "session-aaaaaa",
                "e": [{"kind": "pageview", "path": "/tickets/BAC-106?x=1"}],
            },
        )
    assert response.status_code == 204
    conn = usage_store.hot_connection()
    row = conn.execute("SELECT path, route, sector, country, city FROM hot_event").fetchone()
    assert row[0] == "/tickets/BAC-106"
    assert row[1] == "/tickets/:id"
    assert row[2] == "tickets"
    assert row[3] == "DK"
    assert row[4] == "Copenhagen"
    columns = [r[1] for r in conn.execute("PRAGMA table_info(hot_event)").fetchall()]
    assert "ip" not in columns


@test("POST /ingest/usage succeeds when IP lookup is down")
def _(c=client, home=usage_home, raw=usage_key):
    with patch.dict(os.environ, {"IP_URL": "http://127.0.0.1:9"}, clear=False):
        with patch("app.utils.ip_lookup.requests.get", side_effect=OSError("down")):
            response = c.post(
                "/ingest/usage",
                data=json.dumps(
                    {
                        "k": raw,
                        "vid": "visitor-bbbbbbbb",
                        "sid": "session-bbbbbb",
                        "e": [{"kind": "pageview", "path": "/"}],
                    }
                ),
                content_type="text/plain",
                headers={"CF-Connecting-IP": "8.8.8.8"},
            )
    assert response.status_code == 204
    conn = usage_store.hot_connection()
    row = conn.execute("SELECT country, city FROM hot_event").fetchone()
    assert row[0] is None
    assert row[1] is None


@test("POST /ingest/usage is 404 when usage is disabled")
def _(c=client, home=usage_home, raw=usage_key):
    with patch("app.views.usage.is_feature_enabled", return_value=False):
        response = _post(
            c,
            raw,
            {
                "vid": "visitor-aaaaaaa",
                "sid": "session-aaaaaa",
                "e": [{"kind": "pageview", "path": "/"}],
            },
        )
    assert response.status_code == 404


@test("GET /usage requires authentication")
def _(c=client):
    response = c.get("/usage", follow_redirects=False)
    assert response.status_code in (302, 401)


@test("GET /usage renders a shell without querying the lake")
def _(c=auth_client, home=usage_home):
    with patch("app.utils.usage_store.dashboard") as dash:
        response = c.get("/usage")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Usage" in body
    assert 'id="usage-page"' in body
    assert "Loading usage" in body
    assert 'id="usage-pages"' not in body
    assert "Copenhagen" not in body
    dash.assert_not_called()


@test("GET /api/usage requires authentication")
def _(c=client):
    response = c.get("/api/usage", follow_redirects=False)
    assert response.status_code in (302, 401)


@test("GET /api/usage is 404 when usage is disabled")
def _(c=auth_client, home=usage_home):
    with patch("app.views.usage.is_feature_enabled", return_value=False):
        response = c.get("/api/usage")
    assert response.status_code == 404


@test("GET /api/usage returns flow, gates, journeys, and countries")
def _(c=auth_client, home=usage_home):
    now = int(time.time() * 1000) - 2000
    usage_store.write_events(
        [
            {
                "ts": now,
                "visitor": "visitor-aaaaaaa",
                "session": "session-aaaaaa",
                "kind": "pageview",
                "path": "/",
                "route": "/",
                "sector": "(root)",
                "country": "DK",
                "region": "Hovedstaden",
                "city": "Copenhagen",
            },
            {
                "ts": now + 10,
                "visitor": "visitor-aaaaaaa",
                "session": "session-aaaaaa",
                "kind": "pageview",
                "path": "/tickets",
                "route": "/tickets",
                "sector": "tickets",
                "country": "DK",
                "region": "Hovedstaden",
                "city": "Copenhagen",
            },
        ]
    )
    response = c.get("/api/usage")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["has_events"] is True
    assert payload["pageviews"] == 2
    pages = {row["label"] for row in payload["pages"]}
    assert "/tickets" in pages
    assert payload["gates"]
    assert payload["journeys"]
    journey_steps = [step for row in payload["journeys"] for step in row["steps"]]
    assert "/tickets" in journey_steps
    cities = {row["label"] for row in payload["cities"]}
    assert "Copenhagen" in cities
    copenhagen = next(row for row in payload["cities"] if row["label"] == "Copenhagen")
    assert copenhagen["country"] == "DK"
    assert 685.0 <= copenhagen["x"] <= 703.0
    assert 195.0 <= copenhagen["y"] <= 213.0
    countries = {row["label"] for row in payload["countries"]}
    assert "DK" in countries
    assert payload["has_geo"] is True


@test("GET /usage.js serves the beacon")
def _(c=client):
    response = c.get("/usage.js")
    assert response.status_code == 200
    assert b"BrokeUsage" in response.data
    assert response.headers.get("Access-Control-Allow-Origin") == "*"
