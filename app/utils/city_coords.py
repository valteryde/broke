"""City coordinates for the Usage map.

Names come from Natural Earth 10m populated places (public domain), folded so
DB-IP English names still match. Pixel positions use the same Miller projection
as ``world-110m.json``.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from pathlib import Path
from typing import Any

# Must match the projection used to build app/static/js/vendor/world-110m.json.
MAP_WIDTH = 1400.0
MAP_HEIGHT = 700.0
LAT_MIN = -56.0
LAT_MAX = 84.0
LON_MIN = -168.0
LON_MAX = 192.0

_EXTRA = str.maketrans(
    {
        "ø": "o",
        "Ø": "o",
        "å": "a",
        "Å": "a",
        "ł": "l",
        "Ł": "l",
        "đ": "d",
        "Đ": "d",
        "ð": "d",
        "Ð": "d",
        "þ": "th",
        "Þ": "th",
        "ß": "ss",
        "æ": "ae",
        "Æ": "ae",
        "œ": "oe",
        "Œ": "oe",
    }
)

_CITIES: dict[str, dict[str, list[float]]] | None = None


def fold_name(text: str) -> str:
    value = (text or "").translate(_EXTRA)
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^a-z0-9]+", " ", value.lower())
    return " ".join(value.split())


def _cities() -> dict[str, dict[str, list[float]]]:
    global _CITIES
    if _CITIES is None:
        path = Path(__file__).with_name("world_cities.json")
        _CITIES = json.loads(path.read_text())
    return _CITIES


def lookup(city: str, country: str | None) -> tuple[float, float] | None:
    iso = (country or "").strip().upper()
    key = fold_name(city)
    if len(iso) != 2 or len(key) < 3:
        return None
    pair = _cities().get(iso, {}).get(key)
    if not pair or len(pair) < 2:
        return None
    return float(pair[0]), float(pair[1])


def project(lon: float, lat: float) -> tuple[float, float]:
    """Miller cylindrical, cropped and scaled like the Usage world map."""
    wrapped = lon + 360.0 if lon < LON_MIN else lon
    lat_c = max(-85.0, min(85.0, lat))
    x = (wrapped - LON_MIN) / (LON_MAX - LON_MIN) * MAP_WIDTH
    mill_y = 1.25 * math.log(math.tan(math.pi / 4 + 0.4 * math.radians(lat_c)))
    mill_max = 1.25 * math.log(math.tan(math.pi / 4 + 0.4 * math.radians(LAT_MAX)))
    mill_min = 1.25 * math.log(math.tan(math.pi / 4 + 0.4 * math.radians(LAT_MIN)))
    y = (mill_max - mill_y) / (mill_max - mill_min) * MAP_HEIGHT
    return x, y


def point_for(city: str, country: str | None) -> dict[str, float] | None:
    found = lookup(city, country)
    if found is None:
        return None
    lon, lat = found
    x, y = project(lon, lat)
    return {"x": round(x, 1), "y": round(y, 1)}


def attach_points(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for row in rows:
        point = point_for(str(row.get("label") or ""), row.get("country"))
        if point:
            row.update(point)
    return rows
