"""broke-ip sidecar helpers: private IPs, MMDB extract, monthly filename, auth."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

from ward import test

IP_DIR = Path(__file__).resolve().parents[1] / "ip"
if str(IP_DIR) not in sys.path:
    sys.path.insert(0, str(IP_DIR))

import geo  # noqa: E402
import main as ip_main  # noqa: E402
import update  # noqa: E402


@test("is_private_ip rejects loopback and RFC1918")
def _():
    assert geo.is_private_ip("127.0.0.1")
    assert geo.is_private_ip("10.0.0.5")
    assert geo.is_private_ip("192.168.1.9")
    assert geo.is_private_ip("")
    assert geo.is_private_ip("not-an-ip")
    assert not geo.is_private_ip("8.8.8.8")


@test("extract_place reads country region city and ignores coordinates")
def _():
    record = {
        "country": {"iso_code": "DK", "names": {"en": "Denmark"}},
        "subdivisions": [{"iso_code": "84", "names": {"en": "Hovedstaden"}}],
        "city": {"names": {"en": "Copenhagen"}},
        "location": {"latitude": 55.67, "longitude": 12.56},
    }
    country, region, city = geo.extract_place(record)
    assert country == "DK"
    assert region == "Hovedstaden"
    assert city == "Copenhagen"


@test("month_stamp and download_url use UTC year-month")
def _():
    stamp = update.month_stamp(0)
    assert stamp == "1970-01"
    assert (
        update.download_url(stamp)
        == "https://download.db-ip.com/free/dbip-city-lite-1970-01.mmdb.gz"
    )


@test("lookup uses the query IP not the caller and skips private IPs")
def _():
    fake = MagicMock()
    fake.get.return_value = {
        "country": {"iso_code": "US"},
        "city": {"names": {"en": "Boston"}},
    }
    ip_main.reader._db = fake
    ip_main.reader.path = "fake.mmdb"
    ip_main.cache.clear()
    ip_main.SERVICE_TOKEN = ""

    client = ip_main.app.test_client()
    private = client.get("/lookup?ip=127.0.0.1")
    assert private.status_code == 200
    assert private.get_json()["country"] is None
    fake.get.assert_not_called()

    public = client.get("/lookup?ip=8.8.8.8", environ_base={"REMOTE_ADDR": "1.2.3.4"})
    assert public.status_code == 200
    body = public.get_json()
    assert body["country"] == "US"
    assert body["city"] == "Boston"
    fake.get.assert_called_once_with("8.8.8.8")


@test("lookup requires bearer token when IP_SERVICE_TOKEN is set")
def _():
    ip_main.SERVICE_TOKEN = "secret-token"
    ip_main.cache.clear()
    client = ip_main.app.test_client()
    denied = client.get("/lookup?ip=8.8.8.8")
    assert denied.status_code == 401
    allowed = client.get(
        "/lookup?ip=8.8.8.8",
        headers={"Authorization": "Bearer secret-token"},
    )
    assert allowed.status_code == 200
    ip_main.SERVICE_TOKEN = ""
