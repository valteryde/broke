"""Tests for the Telegraf ingest endpoints and the Servers pages."""

import base64
import gzip
import os
import shutil
import tempfile
import zlib
import time
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

from ward import Scope, fixture, test

from tests.fixtures import app, auth_client, auth_user, client, fake
from app.utils import metrics_store
from app.utils.metrics_auth import generate_token, hash_token
from app.utils.models import MetricsHost, MetricsToken


@fixture(scope=Scope.Test)
def metrics_home():
    """Isolate the metrics tiers so ingest tests never touch the real data dir."""
    tmp = tempfile.mkdtemp(prefix="broke_ingest_test_")
    previous = os.environ.get("BROKE_METRICS_DIR")
    os.environ["BROKE_METRICS_DIR"] = tmp
    metrics_store.close_hot_connection()
    metrics_store.reset_series_cache()

    yield Path(tmp)

    metrics_store.close_hot_connection()
    metrics_store.reset_series_cache()
    if previous is None:
        os.environ.pop("BROKE_METRICS_DIR", None)
    else:
        os.environ["BROKE_METRICS_DIR"] = previous
    shutil.rmtree(tmp, ignore_errors=True)


@fixture(scope=Scope.Test)
def anon_client(app=app):
    """A client with no session of its own.

    The shared ``client`` fixture is global, so by the time these tests run another test
    file may have logged in through it.
    """
    with app.test_client() as c:
        yield c


@fixture(scope=Scope.Test)
def metrics_token():
    raw = generate_token()
    row = MetricsToken.create(
        name=f"test-{int(time.time() * 1000000)}",
        token_hash=hash_token(raw),
        token_preview=raw[:8],
    )
    yield raw
    if MetricsToken.get_or_none(MetricsToken.id == row.id):
        row.delete_instance()


@fixture(scope=Scope.Test)
def ingest_host():
    """Name of a host created by these tests, removed afterwards."""
    hostname = f"testhost-{int(time.time() * 1000000)}"
    yield hostname
    MetricsHost.delete().where(MetricsHost.hostname == hostname).execute()


def _body(hostname: str, ts: int) -> bytes:
    return (
        f"cpu,host={hostname},cpu=cpu-total usage_idle=90.5,usage_user=9.5 {ts}\n"
        f"mem,host={hostname} used_percent=42.0 {ts}\n"
    ).encode("utf-8")


def _auth(raw: str, scheme: str = "Token") -> dict[str, str]:
    return {"Authorization": f"{scheme} {raw}"}


def _csrf(c) -> dict[str, str]:
    cookie = c.get_cookie("broke_csrf")
    return {"X-CSRF-Token": cookie.value} if cookie else {}


# ============ Auth ============


@test("writing without a token is rejected")
def _(c=client, home=metrics_home, host=ingest_host):
    response = c.post("/api/v2/write", data=_body(host, int(time.time())))
    assert response.status_code == 401
    assert response.get_json()["code"] == "unauthorized"


@test("writing with an unknown token is rejected")
def _(c=client, home=metrics_home, host=ingest_host):
    response = c.post(
        "/api/v2/write", data=_body(host, int(time.time())), headers=_auth("not-a-real-token")
    )
    assert response.status_code == 401


@test("the Token prefix that outputs.influxdb_v2 sends is accepted")
def _(c=client, home=metrics_home, raw=metrics_token, host=ingest_host):
    response = c.post(
        "/api/v2/write?org=broke&bucket=broke&precision=s",
        data=_body(host, int(time.time())),
        headers=_auth(raw, "Token"),
    )
    assert response.status_code == 204
    assert response.data == b""


@test("the Bearer prefix is accepted too")
def _(c=client, home=metrics_home, raw=metrics_token, host=ingest_host):
    response = c.post(
        "/api/v2/write?precision=s",
        data=_body(host, int(time.time())),
        headers=_auth(raw, "Bearer"),
    )
    assert response.status_code == 204


@test("the prefix is matched case insensitively")
def _(c=client, home=metrics_home, raw=metrics_token, host=ingest_host):
    response = c.post(
        "/api/v2/write?precision=s",
        data=_body(host, int(time.time())),
        headers={"Authorization": f"token {raw}"},
    )
    assert response.status_code == 204


@test("a v1 client may authenticate with basic auth, as outputs.influxdb sends it")
def _(c=client, home=metrics_home, raw=metrics_token, host=ingest_host):
    credentials = base64.b64encode(f"broke:{raw}".encode()).decode()
    response = c.post(
        "/write?db=telegraf&precision=s",
        data=_body(host, int(time.time())),
        headers={"Authorization": f"Basic {credentials}"},
    )
    assert response.status_code == 204


@test("the p query parameter is refused by default, keeping tokens out of access logs")
def _(c=client, home=metrics_home, raw=metrics_token, host=ingest_host):
    response = c.post(
        f"/write?db=telegraf&precision=s&u=broke&p={raw}",
        data=_body(host, int(time.time())),
    )
    assert response.status_code == 401


@test("the p query parameter works once METRICS_ALLOW_QUERY_TOKEN opts in")
def _(c=client, home=metrics_home, raw=metrics_token, host=ingest_host):
    os.environ["METRICS_ALLOW_QUERY_TOKEN"] = "1"
    try:
        response = c.post(
            f"/write?db=telegraf&precision=s&u=broke&p={raw}",
            data=_body(host, int(time.time())),
        )
    finally:
        os.environ.pop("METRICS_ALLOW_QUERY_TOKEN", None)
    assert response.status_code == 204


@test("a successful write updates the token's last_used")
def _(c=client, home=metrics_home, raw=metrics_token, host=ingest_host):
    c.post(
        "/api/v2/write?precision=s",
        data=_body(host, int(time.time())),
        headers=_auth(raw),
    )
    row = MetricsToken.get(MetricsToken.token_hash == hash_token(raw))
    assert row.last_used is not None


# ============ Payload handling ============


@test("the v1 write endpoint accepts the same payload")
def _(c=client, home=metrics_home, raw=metrics_token, host=ingest_host):
    response = c.post(
        "/write?db=telegraf&precision=s", data=_body(host, int(time.time())), headers=_auth(raw)
    )
    assert response.status_code == 204
    assert metrics_store.list_series(host)


@test("a gzipped body is decompressed")
def _(c=client, home=metrics_home, raw=metrics_token, host=ingest_host):
    response = c.post(
        "/api/v2/write?precision=s",
        data=gzip.compress(_body(host, int(time.time()))),
        headers={**_auth(raw), "Content-Encoding": "gzip"},
    )
    assert response.status_code == 204
    assert metrics_store.list_series(host)


@test("a body that claims to be gzip but is not returns 400")
def _(c=client, home=metrics_home, raw=metrics_token, host=ingest_host):
    response = c.post(
        "/api/v2/write",
        data=b"definitely not gzip",
        headers={**_auth(raw), "Content-Encoding": "gzip"},
    )
    assert response.status_code == 400


@test("malformed line protocol returns an influx-shaped 400")
def _(c=client, home=metrics_home, raw=metrics_token):
    response = c.post("/api/v2/write", data=b"cpu usage=notanumber 1", headers=_auth(raw))
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["code"] == "invalid"
    assert "unable to parse points" in payload["message"]


@test("an empty body is accepted as a no-op")
def _(c=client, home=metrics_home, raw=metrics_token):
    assert c.post("/api/v2/write", data=b"", headers=_auth(raw)).status_code == 204
    assert c.post("/api/v2/write", data=b"\n  \n", headers=_auth(raw)).status_code == 204


@test("an oversized body is rejected with 413")
def _(c=client, home=metrics_home, raw=metrics_token, host=ingest_host):
    with patch("app.views.metrics.MAX_BODY_BYTES", 10):
        response = c.post("/api/v2/write", data=_body(host, int(time.time())), headers=_auth(raw))
    assert response.status_code == 413


@test("a small body that inflates past the limit is rejected rather than buffered")
def _(c=client, home=metrics_home, raw=metrics_token):
    # Compresses to a few hundred bytes, so only a post-decompression check catches it.
    bomb = gzip.compress(b"a" * (8 * 1024 * 1024))
    assert len(bomb) < 64 * 1024

    with patch("app.views.metrics.MAX_BODY_BYTES", 1024 * 1024):
        response = c.post(
            "/api/v2/write",
            data=bomb,
            headers={**_auth(raw), "Content-Encoding": "gzip"},
        )
    assert response.status_code == 413
    assert response.get_json()["code"] == "request too large"


@test("a deflate body is decompressed")
def _(c=client, home=metrics_home, raw=metrics_token, host=ingest_host):
    response = c.post(
        "/api/v2/write?precision=s",
        data=zlib.compress(_body(host, int(time.time()))),
        headers={**_auth(raw), "Content-Encoding": "deflate"},
    )
    assert response.status_code == 204
    assert metrics_store.list_series(host)


@test("a hostname carrying markup is escaped on every page that renders it")
def _(ac=auth_client, home=metrics_home, raw=metrics_token):
    # The host tag comes from whoever holds a write token, so it is untrusted input.
    # Templates are .jinja2, which Flask does not autoescape, hence the explicit filters.
    host = "evil</script><script>alert(1)</script>"
    ac.post(
        "/api/v2/write?precision=s",
        data=f"mem,host={host} used_percent=1.0 {int(time.time())}\n".encode(),
        headers=_auth(raw),
    )
    assert MetricsHost.get_or_none(MetricsHost.hostname == host) is not None

    for path in ("/servers", f"/servers/{quote(host, safe='')}"):
        body = ac.get(path).get_data(as_text=True)
        assert "<script>alert(1)</script>" not in body, path
        assert "&lt;/script&gt;&lt;script&gt;" in body, path


@test("the precision parameter scales incoming timestamps")
def _(c=client, home=metrics_home, raw=metrics_token, host=ingest_host):
    now = int(time.time())
    c.post(
        "/api/v2/write?precision=s",
        data=f"cpu,host={host} usage_idle=50.0 {now}\n".encode(),
        headers=_auth(raw),
    )
    stored = metrics_store.hot_connection().execute(
        "SELECT ts FROM hot_point WHERE host = ?", (host,)
    ).fetchone()
    assert stored[0] == now * 1000


@test("a write without a timestamp is stored at the current time")
def _(c=client, home=metrics_home, raw=metrics_token, host=ingest_host):
    before = int(time.time()) * 1000
    c.post(
        "/api/v2/write",
        data=f"cpu,host={host} usage_idle=50.0\n".encode(),
        headers=_auth(raw),
    )
    stored = metrics_store.hot_connection().execute(
        "SELECT ts FROM hot_point WHERE host = ?", (host,)
    ).fetchone()
    assert stored[0] >= before


@test("ingest registers the host so it shows up on the Servers page")
def _(c=client, home=metrics_home, raw=metrics_token, host=ingest_host):
    c.post("/api/v2/write?precision=s", data=_body(host, int(time.time())), headers=_auth(raw))

    row = MetricsHost.get_or_none(MetricsHost.hostname == host)
    assert row is not None
    assert row.last_seen >= row.first_seen


# ============ Compatibility probes ============


@test("ping answers with an InfluxDB version header")
def _(c=client, home=metrics_home):
    response = c.get("/ping")
    assert response.status_code == 204
    assert response.headers["X-Influxdb-Version"]


@test("health reports a passing status")
def _(c=client, home=metrics_home):
    response = c.get("/health")
    assert response.status_code == 200
    assert response.get_json()["status"] == "pass"


# ============ Feature flag ============


@test("every metrics route disappears when the feature is disabled")
def _(c=client, home=metrics_home, raw=metrics_token):
    os.environ["BROKE_DISABLED_FEATURES"] = "metrics"
    try:
        assert c.post("/api/v2/write", data=b"", headers=_auth(raw)).status_code == 404
        assert c.post("/write", data=b"", headers=_auth(raw)).status_code == 404
        assert c.get("/ping").status_code == 404
        assert c.get("/health").status_code == 404
    finally:
        os.environ.pop("BROKE_DISABLED_FEATURES", None)


# ============ Pages and query API ============


@test("the Servers pages require authentication")
def _(c=anon_client, home=metrics_home):
    assert c.get("/servers", follow_redirects=False).status_code in (302, 401)
    assert c.get("/api/metrics/hosts", follow_redirects=False).status_code in (302, 401)


@test("the Servers list shows a reporting host")
def _(ac=auth_client, home=metrics_home, raw=metrics_token, host=ingest_host):
    ac.post("/api/v2/write?precision=s", data=_body(host, int(time.time())), headers=_auth(raw))

    response = ac.get("/servers")
    assert response.status_code == 200
    assert host in response.get_data(as_text=True)


@test("the host detail page renders its charts and measurement explorer")
def _(ac=auth_client, home=metrics_home, raw=metrics_token, host=ingest_host):
    ac.post("/api/v2/write?precision=s", data=_body(host, int(time.time())), headers=_auth(raw))

    response = ac.get(f"/servers/{host}?range=6h")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "met-charts" in body
    assert "met-explorer" in body


@test("an unknown host is a 404")
def _(ac=auth_client, home=metrics_home):
    assert ac.get("/servers/does-not-exist").status_code == 404


@test("the query API returns bucketed points")
def _(ac=auth_client, home=metrics_home, raw=metrics_token, host=ingest_host):
    now = int(time.time())
    ac.post("/api/v2/write?precision=s", data=_body(host, now), headers=_auth(raw))

    response = ac.get(
        f"/api/metrics/query?host={host}&measurement=mem&field=used_percent&range=1h"
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["range"] == "1h"
    assert payload["points"][-1]["value"] == 42.0


@test("the query API can invert a percentage, turning idle into usage")
def _(ac=auth_client, home=metrics_home, raw=metrics_token, host=ingest_host):
    ac.post("/api/v2/write?precision=s", data=_body(host, int(time.time())), headers=_auth(raw))

    response = ac.get(
        f"/api/metrics/query?host={host}&measurement=cpu&field=usage_idle&range=1h&invert=1"
    )
    assert response.get_json()["points"][-1]["value"] == 9.5


@test("the query API validates its arguments")
def _(ac=auth_client, home=metrics_home):
    assert ac.get("/api/metrics/query?host=a").status_code == 400
    assert ac.get("/api/metrics/query?host=a&measurement=cpu&field=x&range=99y").status_code == 400
    assert (
        ac.get("/api/metrics/query?host=a&measurement=cpu&field=x&aggregate=nope").status_code
        == 400
    )
    assert (
        ac.get("/api/metrics/query?host=a&measurement=cpu&field=x&tags=notjson").status_code == 400
    )


@test("deleting a host is admin only and clears its metrics")
def _(ac=auth_client, u=auth_user, home=metrics_home, raw=metrics_token, host=ingest_host):
    ac.post("/api/v2/write?precision=s", data=_body(host, int(time.time())), headers=_auth(raw))
    ac.get("/servers")

    assert ac.delete(f"/api/metrics/hosts/{host}", headers=_csrf(ac)).status_code == 403

    u.admin = 1
    u.save()
    assert ac.delete(f"/api/metrics/hosts/{host}", headers=_csrf(ac)).status_code == 200
    assert MetricsHost.get_or_none(MetricsHost.hostname == host) is None
    assert metrics_store.list_series(host) == []
