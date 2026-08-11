"""Tests for the Telegraf ingest endpoints and the Servers pages."""

import base64
import gzip
import json
import os
import re
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
from app.utils.models import MetricsChart, MetricsHost, MetricsToken, database
from app.views.metrics import ingest_base_url


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
    try:
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
    finally:
        MetricsHost.delete().where(MetricsHost.hostname == host).execute()


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


# ============ The Telegraf config snippet ============
#
# Getting the scheme wrong here is not cosmetic: a TLS-terminating proxy answers an
# http:// write with a redirect that Telegraf refuses to follow, and the token has already
# gone out in clear text by the time it fails.


@test("the config snippet advertises https for a proxied install, not the internal hop")
def _(a=app, home=metrics_home):
    with a.test_request_context("/", base_url="http://broke.example.com"):
        assert ingest_base_url() == "https://broke.example.com"


@test("the config snippet trusts the scheme the proxy forwards")
def _(a=app, home=metrics_home):
    with a.test_request_context(
        "/", base_url="http://broke.example.com", headers={"X-Forwarded-Proto": "https"}
    ):
        assert ingest_base_url() == "https://broke.example.com"


@test("a local install keeps http, since nobody put a certificate in front of it")
def _(a=app, home=metrics_home):
    for base in ("http://localhost:5000", "http://127.0.0.1:5000", "http://192.168.1.5:8080"):
        with a.test_request_context("/", base_url=base):
            assert ingest_base_url() == base, base


@test("APP_BASE_URL overrides whatever the request happens to look like")
def _(a=app, home=metrics_home):
    os.environ["APP_BASE_URL"] = "https://metrics.example.com/"
    try:
        with a.test_request_context("/", base_url="http://internal:8000"):
            assert ingest_base_url() == "https://metrics.example.com"
    finally:
        os.environ.pop("APP_BASE_URL", None)


@test("the settings snippet users copy from is https, and says why it must stay that way")
def _(ac=auth_client, u=auth_user, home=metrics_home):
    u.admin = 1
    u.save()

    body = ac.get(
        "/settings/metrics", headers={"X-Forwarded-Proto": "https"}
    ).get_data(as_text=True)
    assert 'urls = ["https://localhost"]' in body
    assert "308 Permanent Redirect" in body


@test("the Servers empty state hands out an https snippet with the reason why")
def _(ac=auth_client, home=metrics_home):
    # MetricsHost lives in app.db, which metrics_home does not isolate, so reaching the
    # empty state means clearing rows this suite shares with everything else. Do it inside
    # a transaction that is rolled back, rather than really deleting anyone's hosts.
    with database.atomic() as txn:
        MetricsHost.delete().execute()

        # Same host so the session cookie survives; the header is what lifts the scheme.
        body = ac.get("/servers", headers={"X-Forwarded-Proto": "https"}).get_data(as_text=True)
        txn.rollback()

    assert 'urls = ["https://localhost"]' in body
    assert "clear text" in body


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
    # One line or twelve, the answer always has the same shape.
    assert len(payload["series"]) == 1
    assert payload["series"][0]["points"][-1]["value"] == 42.0


@test("the query API can invert a percentage, turning idle into usage")
def _(ac=auth_client, home=metrics_home, raw=metrics_token, host=ingest_host):
    ac.post("/api/v2/write?precision=s", data=_body(host, int(time.time())), headers=_auth(raw))

    response = ac.get(
        f"/api/metrics/query?host={host}&measurement=cpu&field=usage_idle&range=1h&invert=1"
    )
    assert response.get_json()["series"][0]["points"][-1]["value"] == 9.5


@test("the query API draws one line per tag set when asked for a family")
def _(ac=auth_client, home=metrics_home, raw=metrics_token, host=ingest_host):
    now = int(time.time())
    body = (
        f"disk,host={host},path=/ used_percent=70.0 {now}\n"
        f"disk,host={host},path=/boot used_percent=10.0 {now}"
    ).encode()
    ac.post("/api/v2/write?precision=s", data=body, headers=_auth(raw))

    payload = ac.get(
        f"/api/metrics/query?host={host}&measurement=disk&field=used_percent"
        "&range=1h&tag_mode=filter&tags=%7B%7D"
    ).get_json()

    assert sorted(line["label"] for line in payload["series"]) == ["path=/", "path=/boot"]


@test("the query API answers a histogram with quantiles rather than raw buckets")
def _(ac=auth_client, home=metrics_home, raw=metrics_token, host=ingest_host):
    now = int(time.time())
    edges = {"1": 10, "2": 20, "+Inf": 40}
    lines = []
    for step in range(4):
        ts = now - (3 - step) * 30
        for edge, growth in edges.items():
            lines.append(
                f"prometheus,host={host},le={edge} lat_bucket={growth * step} {ts}"
            )
    ac.post("/api/v2/write?precision=s", data="\n".join(lines).encode(), headers=_auth(raw))

    options = quote('{"bucket_by": "tag", "quantiles": [0.5]}', safe="")
    payload = ac.get(
        f"/api/metrics/query?host={host}&measurement=prometheus&field=lat_bucket"
        f"&range=1h&kind=histogram&tag_mode=filter&tags=%7B%7D&options={options}"
    ).get_json()

    assert [line["label"] for line in payload["series"]] == ["p50"]
    # Half of each window's observations land at or below the second edge.
    assert payload["series"][0]["points"][-1]["value"] == 2.0


@test("the query API differentiates a counter instead of drawing its climb since boot")
def _(ac=auth_client, home=metrics_home, raw=metrics_token, host=ingest_host):
    now = int(time.time())
    # 30s apart at 3000 bytes a step, which is 100 bytes per second.
    lines = [
        f"net,host={host},interface=eth0 bytes_recv={3000 * step} {now - (3 - step) * 30}"
        for step in range(4)
    ]
    ac.post("/api/v2/write?precision=s", data="\n".join(lines).encode(), headers=_auth(raw))

    payload = ac.get(
        f"/api/metrics/query?host={host}&measurement=net&field=bytes_recv"
        "&range=1h&transform=rate&tag_mode=filter&tags=%7B%7D"
    ).get_json()

    values = [p["value"] for p in payload["series"][0]["points"]]
    assert values and all(v == 100.0 for v in values)


@test("the query API validates its arguments")
def _(ac=auth_client, home=metrics_home):
    base = "/api/metrics/query?host=a&measurement=cpu&field=x"
    assert ac.get("/api/metrics/query?host=a").status_code == 400
    assert ac.get(f"{base}&range=99y").status_code == 400
    assert ac.get(f"{base}&aggregate=nope").status_code == 400
    assert ac.get(f"{base}&tags=notjson").status_code == 400
    assert ac.get(f"{base}&kind=nope").status_code == 400
    assert ac.get(f"{base}&transform=nope").status_code == 400
    assert ac.get(f"{base}&tag_mode=nope").status_code == 400
    assert ac.get(f"{base}&options=notjson").status_code == 400


# ============ The chart board ============


def _charts_url(host: str) -> str:
    return f"/api/metrics/hosts/{quote(host, safe='')}/charts"


def _family_key(measurement: str, field: str, kind: str = "gauge", tags: str = "{}") -> str:
    """The identifier a board is saved by; mirrors metrics_families.Family.key."""
    return f"{measurement}|{field}|{tags}|{kind}"


@fixture(scope=Scope.Test)
def board_host(c=auth_client, home=metrics_home, raw=metrics_token):
    """A host reporting three measurements, with no board arranged for it."""
    host = f"boardhost-{int(time.time() * 1000000)}"
    now = int(time.time())
    body = "\n".join(
        f"cpu,host={host} usage_idle={80 + i}.0 {now - i * 10}\n"
        f"mem,host={host} used_percent={40 + i}.0 {now - i * 10}\n"
        f"disk,host={host} used_percent={10 + i}.0 {now - i * 10}"
        for i in range(3)
    )
    c.post("/api/v2/write?precision=s", data=body.encode(), headers=_auth(raw))
    c.get("/servers")

    yield host

    MetricsChart.delete().where(MetricsChart.hostname == host).execute()
    MetricsHost.delete().where(MetricsHost.hostname == host).execute()


@test("a host nobody has arranged gets charts drawn from what it actually sent")
def _(ac=auth_client, home=metrics_home, host=board_host):
    payload = ac.get(_charts_url(host)).get_json()

    assert payload["customised"] is False
    assert sorted(c["measurement"] for c in payload["charts"]) == ["cpu", "disk", "mem"]


@test("the detail page says its charts were picked automatically")
def _(ac=auth_client, home=metrics_home, host=board_host):
    body = ac.get(f"/servers/{quote(host, safe='')}").get_data(as_text=True)
    assert "picked from what this server is actually sending" in body


@test("saving a board keeps the order it was given")
def _(ac=auth_client, home=metrics_home, host=board_host):
    response = ac.put(
        _charts_url(host),
        json={
            "charts": [
                {"key": _family_key("disk", "used_percent")},
                {"key": _family_key("cpu", "usage_idle")},
            ]
        },
        headers=_csrf(ac),
    )
    assert response.status_code == 200

    payload = response.get_json()
    assert payload["customised"] is True
    assert [c["measurement"] for c in payload["charts"]] == ["disk", "cpu"]

    # And the order survives a fresh read rather than only the response.
    again = ac.get(_charts_url(host)).get_json()
    assert [c["measurement"] for c in again["charts"]] == ["disk", "cpu"]


@test("a saved board replaces the suggestion on the page, with no automatic note")
def _(ac=auth_client, home=metrics_home, host=board_host):
    ac.put(
        _charts_url(host),
        json={"charts": [{"key": _family_key("mem", "used_percent")}]},
        headers=_csrf(ac),
    )

    body = ac.get(f"/servers/{quote(host, safe='')}").get_data(as_text=True)
    assert "picked from what this server is actually sending" not in body
    assert body.count('class="met-chart"') == 1


@test("an empty board is refused rather than silently reverting to the suggestion")
def _(ac=auth_client, home=metrics_home, host=board_host):
    # No rows already means "nobody arranged this host", so an empty save would come back
    # as the suggestion on the next load and look like the save had been ignored.
    response = ac.put(_charts_url(host), json={"charts": []}, headers=_csrf(ac))
    assert response.status_code == 400

    assert ac.get(_charts_url(host)).get_json()["customised"] is False


@test("saving rejects a series the host never sent")
def _(ac=auth_client, home=metrics_home, host=board_host):
    response = ac.put(
        _charts_url(host),
        json={"charts": [{"key": _family_key("nope", "nope")}]},
        headers=_csrf(ac),
    )
    assert response.status_code == 400
    assert "not something this host sends" in response.get_json()["error"]


@test("saving rejects a chart whose kind the host's data does not support")
def _(ac=auth_client, home=metrics_home, host=board_host):
    # The series exists, but nothing about it says histogram, so the selector the browser
    # asked for is not one this server would ever have built.
    response = ac.put(
        _charts_url(host),
        json={"charts": [{"key": _family_key("cpu", "usage_idle", kind="histogram")}]},
        headers=_csrf(ac),
    )
    assert response.status_code == 400


@test("saving rejects a board larger than the cap")
def _(ac=auth_client, home=metrics_home, host=board_host):
    charts = [{"key": _family_key("cpu", "usage_idle")}] * 40
    response = ac.put(_charts_url(host), json={"charts": charts}, headers=_csrf(ac))
    assert response.status_code == 400


@test("resetting a board brings the data-driven suggestion back")
def _(ac=auth_client, home=metrics_home, host=board_host):
    ac.put(
        _charts_url(host),
        json={"charts": [{"key": _family_key("mem", "used_percent")}]},
        headers=_csrf(ac),
    )
    assert ac.get(_charts_url(host)).get_json()["customised"] is True

    payload = ac.delete(_charts_url(host), headers=_csrf(ac)).get_json()
    assert payload["customised"] is False
    assert len(payload["charts"]) == 3


@fixture(scope=Scope.Test)
def prometheus_host(c=auth_client, home=metrics_home, raw=metrics_token):
    """A host scraped with metric_version = 2, so everything shares one measurement."""
    host = f"promhost-{int(time.time() * 1000000)}"
    now = int(time.time())
    edges = {"1": 10, "2": 20, "+Inf": 40}

    lines = []
    for step in range(3):
        ts = now - (2 - step) * 20
        lines.append(f"prometheus,host={host} bbb_meetings_participants={10 + step} {ts}")
        lines.append(f"prometheus,host={host} bbb_recordings_processing={step} {ts}")
        for edge, growth in edges.items():
            lines.append(
                f"prometheus,host={host},le={edge} bbb_api_latency_bucket={growth * step} {ts}"
            )
        lines.append(
            f"prometheus,host={host} bbb_api_latency_count={40 * step},"
            f"bbb_api_latency_sum={0.5 * step} {ts}"
        )
    c.post("/api/v2/write?precision=s", data="\n".join(lines).encode(), headers=_auth(raw))
    c.get("/servers")

    yield host

    MetricsChart.delete().where(MetricsChart.hostname == host).execute()
    MetricsHost.delete().where(MetricsHost.hostname == host).execute()


@test("a Prometheus host does not collapse to a single chart just because it has one measurement")
def _(ac=auth_client, home=metrics_home, host=prometheus_host):
    payload = ac.get(_charts_url(host)).get_json()

    # Every series here sits in the "prometheus" measurement. Suggesting per family rather
    # than per measurement is the only reason this is a board and not one tile.
    assert payload["customised"] is False
    assert len(payload["charts"]) == 3
    assert {c["measurement"] for c in payload["charts"]} == {"prometheus"}


@test("a histogram is suggested as one chart, drawn as quantiles")
def _(ac=auth_client, home=metrics_home, host=prometheus_host):
    charts = ac.get(_charts_url(host)).get_json()["charts"]
    histograms = [c for c in charts if c["kind"] == "histogram"]

    assert len(histograms) == 1
    assert histograms[0]["title"] == "bbb_api_latency (quantiles)"


def _board_data(body: str) -> dict:
    """The config the page hands the board editor."""
    match = re.search(r"BrokeMetrics\.initEditor\((\{.*?\})\);", body, re.DOTALL)
    assert match, "the detail page did not initialise the board editor"
    return json.loads(match.group(1))


@test("the picker offers a histogram once rather than once per bucket")
def _(ac=auth_client, home=metrics_home, host=prometheus_host):
    body = ac.get(f"/servers/{quote(host, safe='')}").get_data(as_text=True)
    available = _board_data(body)["available"]

    # Three buckets plus a _sum and a _count went in. One entry should come out, and the
    # companions should not be offered as charts in their own right.
    latency = [entry for entry in available if entry["label"] == "bbb_api_latency"]
    assert len(latency) == 1
    assert latency[0]["kind"] == "histogram"
    assert latency[0]["note"] == "histogram · 3 buckets"
    assert not [e for e in available if e["label"].startswith("bbb_api_latency_")]


@test("the board endpoints 404 for an unknown host and when metrics are disabled")
def _(ac=auth_client, home=metrics_home, host=board_host):
    assert ac.get(_charts_url("no-such-host")).status_code == 404

    os.environ["BROKE_DISABLED_FEATURES"] = "metrics"
    try:
        assert ac.get(_charts_url(host)).status_code == 404
    finally:
        os.environ.pop("BROKE_DISABLED_FEATURES", None)


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


@test("clearing a host's data is admin only and leaves the host and its board alone")
def _(ac=auth_client, u=auth_user, home=metrics_home, host=board_host):
    ac.put(
        _charts_url(host),
        json={"charts": [{"key": _family_key("mem", "used_percent")}]},
        headers=_csrf(ac),
    )

    url = f"/api/metrics/hosts/{quote(host, safe='')}/data"
    assert ac.delete(url, headers=_csrf(ac)).status_code == 403

    u.admin = 1
    u.save()
    assert ac.delete(url, headers=_csrf(ac)).status_code == 200

    assert metrics_store.list_series(host) == []
    assert MetricsHost.get_or_none(MetricsHost.hostname == host) is not None
    board = ac.get(_charts_url(host)).get_json()
    assert board["customised"] is True
    assert [c["field"] for c in board["charts"]] == ["used_percent"]
