"""City Lite lookups: private-IP guard, MMDB extract, in-process LRU."""

from __future__ import annotations

import ipaddress
import logging
from collections import OrderedDict
from typing import Any

logger = logging.getLogger("broke-ip")

CACHE_SIZE = 4096

# (country ISO, region, city) — all optional strings
Place = tuple[str | None, str | None, str | None]


class Reader:
    """Swap-friendly wrapper so tests can inject a fake MMDB."""

    def __init__(self, path: str | None = None, database: Any = None):
        self.path = path
        self._db = database

    def open(self, path: str) -> None:
        import maxminddb

        db = maxminddb.open_database(path)
        old = self._db
        self._db = db
        self.path = path
        if old is not None:
            try:
                old.close()
            except Exception:
                pass

    def close(self) -> None:
        if self._db is not None:
            try:
                self._db.close()
            except Exception:
                pass
        self._db = None
        self.path = None

    def get(self, ip: str) -> dict | None:
        if self._db is None:
            return None
        try:
            record = self._db.get(ip)
        except (ValueError, TypeError):
            return None
        return record if isinstance(record, dict) else None

    @property
    def loaded(self) -> bool:
        return self._db is not None

    @property
    def metadata_count(self) -> int | None:
        if self._db is None:
            return None
        meta = getattr(self._db, "metadata", None)
        if meta is None:
            return None
        return getattr(meta, "node_count", None)


def is_private_ip(raw: str) -> bool:
    """True for empty, unparseable, loopback, link-local, or RFC1918/ULA addresses."""
    text = (raw or "").strip()
    if not text:
        return True
    try:
        addr = ipaddress.ip_address(text)
    except ValueError:
        return True
    return bool(
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def _name(node: Any) -> str | None:
    if not isinstance(node, dict):
        return None
    names = node.get("names")
    if isinstance(names, dict):
        for key in ("en", "en-US"):
            value = names.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for value in names.values():
            if isinstance(value, str) and value.strip():
                return value.strip()
    iso = node.get("iso_code")
    if isinstance(iso, str) and iso.strip():
        return iso.strip()
    return None


def extract_place(record: dict | None) -> Place:
    """Pull country / region / city out of a DB-IP or GeoLite-shaped MMDB record."""
    if not record:
        return None, None, None

    country_node = record.get("country") if isinstance(record.get("country"), dict) else {}
    iso = country_node.get("iso_code")
    country = iso.strip().upper() if isinstance(iso, str) and iso.strip() else None

    region = None
    subdivisions = record.get("subdivisions")
    if isinstance(subdivisions, list) and subdivisions:
        region = _name(subdivisions[0])
    if region is None:
        for key in ("subdivisions", "state", "province"):
            node = record.get(key)
            if isinstance(node, dict):
                region = _name(node)
                if region:
                    break

    city_node = record.get("city")
    city = _name(city_node) if isinstance(city_node, dict) else None
    if city is None and isinstance(record.get("city"), str):
        city = record["city"].strip() or None

    return country, region, city


class PlaceCache:
    def __init__(self, size: int = CACHE_SIZE):
        self.size = size
        self._data: OrderedDict[str, Place] = OrderedDict()

    def get(self, ip: str) -> Place | None:
        place = self._data.get(ip)
        if place is None:
            return None
        self._data.move_to_end(ip)
        return place

    def put(self, ip: str, place: Place) -> None:
        if ip in self._data:
            self._data.move_to_end(ip)
            self._data[ip] = place
            return
        self._data[ip] = place
        if len(self._data) > self.size:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()
