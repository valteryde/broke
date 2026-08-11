"""Tests for the InfluxDB line protocol parser used by the Telegraf ingest."""

from ward import raises, test

from app.utils.lineprotocol import (
    LineProtocolError,
    parse,
    parse_line,
    precision_multiplier,
)


@test("parses measurement, tags, fields and timestamp")
def _():
    point = parse_line("cpu,host=web-01,cpu=cpu0 usage_idle=97.5 1465839830100400200")
    assert point.measurement == "cpu"
    assert point.tags == {"host": "web-01", "cpu": "cpu0"}
    assert point.fields == {"usage_idle": 97.5}
    assert point.timestamp_ns == 1465839830100400200


@test("parses a line with no tags")
def _():
    point = parse_line("uptime value=1234i 1000")
    assert point.measurement == "uptime"
    assert point.tags == {}
    assert point.fields == {"value": 1234}


@test("integer suffix i produces an int, not a float")
def _():
    point = parse_line("mem total=8589934592i 1")
    assert point.fields["total"] == 8589934592
    assert isinstance(point.fields["total"], int)


@test("unsigned suffix u is accepted")
def _():
    point = parse_line("mem total=42u 1")
    assert point.fields["total"] == 42


@test("negative unsigned field value is rejected")
def _():
    with raises(LineProtocolError):
        parse_line("mem total=-42u 1")


@test("all boolean spellings are recognised")
def _():
    for literal in ("t", "T", "true", "True", "TRUE"):
        assert parse_line(f"m v={literal} 1").fields["v"] is True
    for literal in ("f", "F", "false", "False", "FALSE"):
        assert parse_line(f"m v={literal} 1").fields["v"] is False


@test("string field values are unquoted and unescaped")
def _():
    point = parse_line(r'syslog message="hello \"world\"" 1')
    assert point.fields["message"] == 'hello "world"'


@test("commas and spaces inside a quoted string are not separators")
def _():
    point = parse_line('syslog message="a, b c",severity=3i 1')
    assert point.fields["message"] == "a, b c"
    assert point.fields["severity"] == 3


@test("escaped commas, spaces and equals in the key section")
def _():
    point = parse_line(r"my\ measurement,tag\=key=tag\,value field=1 1")
    assert point.measurement == "my measurement"
    assert point.tags == {"tag=key": "tag,value"}


@test("escaped space in a tag value does not end the key section")
def _():
    point = parse_line(r"disk,path=/mnt/my\ disk used=1i 1")
    assert point.tags == {"path": "/mnt/my disk"}
    assert point.fields == {"used": 1}


@test("backslash before a non-separator is preserved")
def _():
    point = parse_line(r"win,path=C:\Users used=1i 1")
    assert point.tags == {"path": r"C:\Users"}


@test("missing timestamp falls back to now")
def _():
    point = parse_line("cpu usage=1.0", now_ns=123456789)
    assert point.timestamp_ns == 123456789


@test("precision multiplier scales the timestamp to nanoseconds")
def _():
    point = parse_line("cpu usage=1.0 1465839830", multiplier=precision_multiplier("s"))
    assert point.timestamp_ns == 1465839830 * 1_000_000_000


@test("precision multipliers cover the influx units")
def _():
    assert precision_multiplier("ns") == 1
    assert precision_multiplier("us") == 1_000
    assert precision_multiplier("ms") == 1_000_000
    assert precision_multiplier("s") == 1_000_000_000
    assert precision_multiplier(None) == 1


@test("unsupported precision is rejected")
def _():
    with raises(LineProtocolError):
        precision_multiplier("fortnights")


@test("parse skips blank lines and comments")
def _():
    body = "\n".join(
        [
            "# a comment",
            "",
            "cpu,host=a usage=1.0 1",
            "   ",
            "mem,host=a used=2i 2",
        ]
    )
    points = list(parse(body, precision="s"))
    assert len(points) == 2
    assert [p.measurement for p in points] == ["cpu", "mem"]


@test("a batch of telegraf-shaped lines round-trips")
def _():
    body = (
        "cpu,cpu=cpu-total,host=web-01 usage_idle=95.2,usage_user=3.1 1465839830100400200\n"
        "mem,host=web-01 used_percent=41.5,total=8589934592i 1465839830100400200\n"
        'system,host=web-01 uptime_format="2 days,  3:04" 1465839830100400200\n'
    )
    points = list(parse(body))
    assert len(points) == 3
    assert points[0].fields["usage_user"] == 3.1
    assert points[1].fields["total"] == 8589934592
    assert points[2].fields["uptime_format"] == "2 days,  3:04"


@test("missing field set is rejected")
def _():
    with raises(LineProtocolError):
        parse_line("cpu,host=web-01")


@test("missing measurement is rejected")
def _():
    with raises(LineProtocolError):
        parse_line(",host=web-01 value=1 1")


@test("malformed field value is rejected")
def _():
    with raises(LineProtocolError):
        parse_line("cpu usage=notanumber 1")


@test("malformed timestamp is rejected")
def _():
    with raises(LineProtocolError):
        parse_line("cpu usage=1.0 not-a-timestamp")


@test("unterminated string field value is rejected")
def _():
    with raises(LineProtocolError):
        parse_line('syslog message="unterminated 1')
