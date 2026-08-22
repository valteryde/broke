"""Visitor IP extraction and sidecar client."""

import os
from unittest.mock import patch

from ward import test

from app.utils import ip_lookup


class _Headers(dict):
    def get(self, key, default=None):
        for name, value in self.items():
            if name.lower() == key.lower():
                return value
        return default


@test("visitor_ip prefers CF-Connecting-IP")
def _():
    headers = _Headers({"CF-Connecting-IP": "203.0.113.9", "X-Forwarded-For": "10.0.0.1"})
    assert ip_lookup.visitor_ip(headers, "127.0.0.1") == "203.0.113.9"


@test("visitor_ip ignores X-Forwarded-For unless BROKE_TRUST_PROXY")
def _():
    headers = _Headers({"X-Forwarded-For": "203.0.113.9"})
    with patch.dict(os.environ, {"BROKE_TRUST_PROXY": "0"}, clear=False):
        assert ip_lookup.visitor_ip(headers, "10.1.1.1") == "10.1.1.1"
    with patch.dict(os.environ, {"BROKE_TRUST_PROXY": "1"}, clear=False):
        assert ip_lookup.visitor_ip(headers, "10.1.1.1") == "203.0.113.9"


@test("lookup_place returns nulls when IP_URL is unset")
def _():
    with patch.dict(os.environ, {"IP_URL": ""}, clear=False):
        place = ip_lookup.lookup_place("8.8.8.8")
        assert place == {"country": None, "region": None, "city": None}


@test("lookup_place returns nulls when the sidecar errors")
def _():
    with patch.dict(os.environ, {"IP_URL": "http://127.0.0.1:9"}, clear=False):
        with patch("app.utils.ip_lookup.requests.get", side_effect=OSError("down")):
            place = ip_lookup.lookup_place("8.8.8.8")
    assert place["country"] is None
    assert place["city"] is None


@test("lookup_place does not call the sidecar for private IPs")
def _():
    with patch.dict(os.environ, {"IP_URL": "http://broke-ip:9998"}, clear=False):
        with patch("app.utils.ip_lookup.requests.get") as get:
            place = ip_lookup.lookup_place("10.0.0.8")
    assert place == {"country": None, "region": None, "city": None}
    get.assert_not_called()


@test("resolve_geo prefers a CDN country header and still fills city from the sidecar")
def _():
    headers = _Headers({"CF-Connecting-IP": "8.8.8.8", "CF-IPCountry": "DK"})
    sidecar = {"country": "US", "region": "Massachusetts", "city": "Boston"}
    with patch("app.utils.ip_lookup.lookup_place", return_value=sidecar):
        place = ip_lookup.resolve_geo(headers, "127.0.0.1")
    assert place["country"] == "DK"
    assert place["city"] == "Boston"
    assert place["region"] == "Massachusetts"
