"""
InfluxDB line protocol parser (stdlib only).

Telegraf's ``outputs.influxdb`` / ``outputs.influxdb_v2`` plugins serialize batches as::

    measurement,tag=value,tag2=value2 field=1i,field2=2.0,field3="s" 1465839830100400200

The measurement, tag keys, tag values and field keys use backslash escaping for the
characters that would otherwise be separators. String field values are double quoted.
Numeric fields may carry an ``i`` (signed) or ``u`` (unsigned) suffix to mark integers.
The trailing timestamp is optional and its unit comes from the request's ``precision``.

Reference: https://docs.influxdata.com/influxdb/v2/reference/syntax/line-protocol/
"""

from __future__ import annotations

import time
from typing import Iterator, NamedTuple

# Multipliers to convert an incoming timestamp into nanoseconds.
PRECISION_TO_NS: dict[str, int] = {
    "ns": 1,
    "u": 1_000,
    "us": 1_000,
    "µs": 1_000,
    "ms": 1_000_000,
    "s": 1_000_000_000,
    "m": 60 * 1_000_000_000,
    "h": 3600 * 1_000_000_000,
}

DEFAULT_PRECISION = "ns"

_TRUE_LITERALS = frozenset({"t", "T", "true", "True", "TRUE"})
_FALSE_LITERALS = frozenset({"f", "F", "false", "False", "FALSE"})


class LineProtocolError(ValueError):
    """Raised when a line cannot be parsed."""


class Point(NamedTuple):
    measurement: str
    tags: dict[str, str]
    fields: dict[str, float | int | bool | str]
    timestamp_ns: int


def precision_multiplier(precision: str | None) -> int:
    """Nanoseconds per unit for an InfluxDB ``precision`` query parameter."""
    key = (precision or DEFAULT_PRECISION).strip()
    if not key:
        key = DEFAULT_PRECISION
    try:
        return PRECISION_TO_NS[key]
    except KeyError:
        raise LineProtocolError(f"unsupported precision '{precision}'") from None


# Characters that carry meaning in the key section (measurement, tag keys, tag values)
# and in field keys, so a backslash in front of any of them is an escape rather than a
# literal. A backslash before anything else stays literal, which is what keeps Windows
# paths such as ``C:\Users`` intact.
_KEY_ESCAPABLE = ", ="


def _split_raw(text: str, separators: str, *, limit: int = 0) -> list[str]:
    """
    Split ``text`` on any character in ``separators`` that is not backslash escaped.

    Backslashes are left in place. The key section is split twice (first on commas, then
    each tag on its equals sign), so escapes must survive the first pass and only be
    resolved by :func:`_unescape` once the leaf token is isolated.
    """
    parts: list[str] = []
    buf: list[str] = []
    escaped = False
    for ch in text:
        if escaped:
            buf.append(ch)
            escaped = False
        elif ch == "\\":
            buf.append(ch)
            escaped = True
        elif ch in separators and (limit <= 0 or len(parts) < limit):
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


def _unescape(text: str, escapable: str = _KEY_ESCAPABLE) -> str:
    """Resolve backslash escapes, keeping a backslash that precedes anything else."""
    out: list[str] = []
    escaped = False
    for ch in text:
        if escaped:
            if ch not in escapable and ch != "\\":
                out.append("\\")
            out.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        else:
            out.append(ch)
    if escaped:
        out.append("\\")
    return "".join(out)


def _split_line(line: str) -> tuple[str, str, str]:
    """Split a line into its (key, fields, timestamp) sections on unescaped spaces.

    Spaces inside a quoted string field value are not separators, so the field section
    has to be scanned with quote awareness rather than a plain split.
    """
    key_end = -1
    escaped = False
    for i, ch in enumerate(line):
        if escaped:
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == " ":
            key_end = i
            break
    if key_end < 0:
        raise LineProtocolError("missing field set")

    fields_end = len(line)
    escaped = False
    in_quotes = False
    for i in range(key_end + 1, len(line)):
        ch = line[i]
        if escaped:
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == '"':
            in_quotes = not in_quotes
        elif ch == " " and not in_quotes:
            fields_end = i
            break

    return line[:key_end], line[key_end + 1 : fields_end], line[fields_end:].strip()


def _parse_key(key_section: str) -> tuple[str, dict[str, str]]:
    parts = _split_raw(key_section, ",")
    measurement = _unescape(parts[0])
    if not measurement:
        raise LineProtocolError("missing measurement")

    tags: dict[str, str] = {}
    for part in parts[1:]:
        if not part:
            continue
        kv = _split_raw(part, "=", limit=1)
        if len(kv) != 2 or not kv[0]:
            raise LineProtocolError(f"malformed tag '{part}'")
        tags[_unescape(kv[0])] = _unescape(kv[1])
    return measurement, tags


def _split_field_set(field_section: str) -> list[str]:
    """Split the field set on commas that sit outside of a quoted string value."""
    parts: list[str] = []
    buf: list[str] = []
    escaped = False
    in_quotes = False
    for ch in field_section:
        if escaped:
            buf.append(ch)
            escaped = False
            continue
        if ch == "\\":
            buf.append(ch)
            escaped = True
        elif ch == '"':
            in_quotes = not in_quotes
            buf.append(ch)
        elif ch == "," and not in_quotes:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


def _parse_string_field(raw: str) -> str:
    """Strip the surrounding quotes and resolve ``\\"`` and ``\\\\`` escapes."""
    if len(raw) < 2 or raw[-1] != '"':
        raise LineProtocolError("unterminated string field value")

    out: list[str] = []
    escaped = False
    for ch in raw[1:-1]:
        if escaped:
            if ch not in ('"', "\\"):
                out.append("\\")
            out.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        else:
            out.append(ch)
    if escaped:
        out.append("\\")
    return "".join(out)


def _parse_field_value(raw: str) -> float | int | bool | str:
    if not raw:
        raise LineProtocolError("empty field value")

    if raw[0] == '"':
        return _parse_string_field(raw)

    if raw in _TRUE_LITERALS:
        return True
    if raw in _FALSE_LITERALS:
        return False

    suffix = raw[-1]
    if suffix in ("i", "u"):
        body = raw[:-1]
        try:
            value = int(body)
        except ValueError:
            raise LineProtocolError(f"malformed integer field value '{raw}'") from None
        if suffix == "u" and value < 0:
            raise LineProtocolError(f"negative unsigned field value '{raw}'")
        return value

    try:
        return float(raw)
    except ValueError:
        raise LineProtocolError(f"malformed field value '{raw}'") from None


def _parse_field_set(field_section: str) -> dict[str, float | int | bool | str]:
    fields: dict[str, float | int | bool | str] = {}
    for part in _split_field_set(field_section):
        if not part:
            continue
        kv = _split_raw(part, "=", limit=1)
        if len(kv) != 2 or not kv[0]:
            raise LineProtocolError(f"malformed field '{part}'")
        fields[_unescape(kv[0])] = _parse_field_value(kv[1])
    if not fields:
        raise LineProtocolError("missing field set")
    return fields


def parse_line(line: str, *, multiplier: int = 1, now_ns: int | None = None) -> Point:
    """Parse a single non-empty, non-comment line into a :class:`Point`."""
    key_section, field_section, ts_section = _split_line(line)
    measurement, tags = _parse_key(key_section)
    fields = _parse_field_set(field_section)

    if ts_section:
        try:
            timestamp_ns = int(ts_section) * multiplier
        except ValueError:
            raise LineProtocolError(f"malformed timestamp '{ts_section}'") from None
    else:
        timestamp_ns = now_ns if now_ns is not None else time.time_ns()

    return Point(measurement, tags, fields, timestamp_ns)


def parse(body: str, *, precision: str | None = None) -> Iterator[Point]:
    """
    Yield a :class:`Point` for every line in an line protocol payload.

    Blank lines and ``#`` comments are skipped. Raises :class:`LineProtocolError` on the
    first malformed line so the caller can answer with a 400 the way InfluxDB does.
    """
    multiplier = precision_multiplier(precision)
    now_ns = time.time_ns()
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        yield parse_line(line, multiplier=multiplier, now_ns=now_ns)
