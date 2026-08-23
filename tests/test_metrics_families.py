"""Tests for grouping series into families, and for reading them as rates and quantiles.

The Prometheus fixtures mirror what Telegraf's ``inputs.prometheus`` actually writes, in
both of its mappings, because that difference is the whole reason the classifier exists.
"""

import os
import shutil
import tempfile
import time
from pathlib import Path

from ward import Scope, fixture, test

from app.utils import metrics_families as fam
from app.utils import metrics_store
from app.utils.lineprotocol import parse


@fixture(scope=Scope.Test)
def metrics_home():
    """Point both storage tiers at a throwaway directory for one test."""
    tmp = tempfile.mkdtemp(prefix="broke_families_test_")
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


def _write(body: str, now: int | None = None):
    return metrics_store.write_points(parse(body, precision="s"), now=now)


def _by_name(families):
    return {f.name: f for f in families}


EDGES = [".01", ".05", ".25", "1.0", "5.0", "+Inf"]
GROWTH = {".01": 1, ".05": 2, ".25": 3, "1.0": 4, "5.0": 5, "+Inf": 6}


def _write_v1_prometheus(host: str, now: int, steps: int = 4):
    """metric_version = 1: metric name is the measurement, field keys are generic."""
    for i in range(steps):
        ts = now - (steps - 1 - i) * 10
        buckets = ",".join(f"{edge}={GROWTH[edge] * 10 * i}" for edge in EDGES)
        _write(
            f"bbb_meetings_participants,host={host} gauge={10 + i} {ts}"
            f"\nbbb_unique_meetings,host={host} counter={100 + i * 5} {ts}"
            f"\nbbb_api_latency,host={host},endpoint=create"
            f" {buckets},count={60 * i},sum={1.5 * i} {ts}",
            now=now,
        )


def _write_v2_prometheus(host: str, now: int, steps: int = 4):
    """metric_version = 2: metric name is the field, everything shares one measurement."""
    for i in range(steps):
        ts = now - (steps - 1 - i) * 10
        lines = [
            f"prometheus,host={host} bbb_meetings_participants={10 + i} {ts}",
            f"prometheus,host={host} bbb_unique_meetings_total={100 + i * 5} {ts}",
        ]
        for edge in EDGES:
            lines.append(
                f"prometheus,host={host},endpoint=create,le={edge}"
                f" bbb_api_latency_bucket={GROWTH[edge] * 10 * i} {ts}"
            )
        lines.append(
            f"prometheus,host={host},endpoint=create"
            f" bbb_api_latency_count={60 * i},bbb_api_latency_sum={1.5 * i} {ts}"
        )
        _write("\n".join(lines), now=now)


# ============ Classification ============


@test("a metric_version = 2 histogram becomes one family holding all its buckets")
def _(home=metrics_home):
    now = int(time.time())
    _write_v2_prometheus("h", now)

    families = _by_name(fam.families_for_host("h", now=now))
    histogram = families["bbb_api_latency"]

    assert histogram.kind == fam.KIND_HISTOGRAM
    assert histogram.bucket_by == fam.BUCKET_BY_TAG
    assert histogram.bounds == [0.01, 0.05, 0.25, 1.0, 5.0, float("inf")]
    # le is the family's identity, not part of the filter that finds its members.
    assert histogram.tags == {"endpoint": "create"}


@test("a metric_version = 1 histogram becomes one family, with edges read off the fields")
def _(home=metrics_home):
    now = int(time.time())
    _write_v1_prometheus("h", now)

    histogram = _by_name(fam.families_for_host("h", now=now))["bbb_api_latency"]

    assert histogram.kind == fam.KIND_HISTOGRAM
    assert histogram.bucket_by == fam.BUCKET_BY_FIELD
    assert histogram.bounds == [0.01, 0.05, 0.25, 1.0, 5.0, float("inf")]


@test("the _sum and _count beside a histogram do not become charts of their own")
def _(home=metrics_home):
    now = int(time.time())
    _write_v2_prometheus("h", now)

    names = {f.name for f in fam.families_for_host("h", now=now)}
    assert "bbb_api_latency_sum" not in names
    assert "bbb_api_latency_count" not in names

    histogram = _by_name(fam.families_for_host("h", now=now))["bbb_api_latency"]
    assert {m.field for m in histogram.companions} == {
        "bbb_api_latency_sum",
        "bbb_api_latency_count",
    }


@test("a summary is recognised by its quantile tag rather than an le tag")
def _(home=metrics_home):
    now = int(time.time())
    for q in ("0", "0.5", "1"):
        _write(f"prometheus,host=h,quantile={q} gc_seconds=0.5 {now}", now=now)

    summary = _by_name(fam.families_for_host("h", now=now))["gc_seconds"]
    assert summary.kind == fam.KIND_SUMMARY
    assert summary.bounds == [0.0, 0.5, 1.0]


@test("a metric_version = 1 summary is told from a histogram by its missing +Inf bucket")
def _(home=metrics_home):
    now = int(time.time())
    _write(
        f"go_gc_duration_seconds,host=h 0=0.1,0.5=0.2,1=0.3,count=4,sum=0.6 {now}",
        now=now,
    )

    family = _by_name(fam.families_for_host("h", now=now))["go_gc_duration_seconds"]
    assert family.kind == fam.KIND_SUMMARY


@test("a measurement that merely has a numeric field is not mistaken for a histogram")
def _(home=metrics_home):
    now = int(time.time())
    # No count and sum alongside, so there is nothing to suggest these are bucket edges.
    _write(f"weird,host=h 0=1.0,1=2.0 {now}", now=now)

    assert {f.kind for f in fam.families_for_host("h", now=now)} == {fam.KIND_GAUGE}


@test("a counter is charted as a rate, and Telegraf's generic field keys are unwrapped")
def _(home=metrics_home):
    now = int(time.time())
    _write_v1_prometheus("h", now)

    families = _by_name(fam.families_for_host("h", now=now))
    counter = families["bbb_unique_meetings"]

    assert counter.kind == fam.KIND_COUNTER
    assert counter.transform == fam.TRANSFORM_RATE
    # metric_version = 1 names the field "counter", so the title comes from the measurement.
    assert counter.title == "bbb_unique_meetings"
    assert families["bbb_meetings_participants"].kind == fam.KIND_GAUGE


@test("Telegraf's own cumulative fields are charted as rates too")
def _(home=metrics_home):
    now = int(time.time())
    _write(
        f"net,host=h,interface=eth0 bytes_recv=1000 {now}" f"\nmem,host=h used_percent=40.0 {now}",
        now=now,
    )

    families = _by_name(fam.families_for_host("h", now=now))
    assert families["bytes_recv"].transform == fam.TRANSFORM_RATE
    assert families["used_percent"].transform == fam.TRANSFORM_RAW


@test("one field reported per device becomes a single family drawing several lines")
def _(home=metrics_home):
    now = int(time.time())
    _write(
        f"disk,host=h,path=/ used_percent=70.0 {now}"
        f"\ndisk,host=h,path=/boot used_percent=10.0 {now}"
        f"\ndisk,host=h,path=/home used_percent=30.0 {now}",
        now=now,
    )

    families = fam.families_for_host("h", now=now)
    assert len(families) == 1
    assert len(families[0].members) == 3
    # An empty filter with tag_mode "filter" is what matches all three mounts.
    assert families[0].tags == {}
    assert families[0].tag_mode == "filter"


@test("the same field under two measurements stays two distinct, distinguishable charts")
def _(home=metrics_home):
    now = int(time.time())
    _write(
        f"mem,host=h used_percent=40.0 {now}\ndisk,host=h,path=/ used_percent=70.0 {now}",
        now=now,
    )

    titles = sorted(f.title for f in fam.families_for_host("h", now=now))
    assert titles == ["disk.used_percent", "mem.used_percent"]


@test("a string-only series is not offered as a family, since there is nothing to plot")
def _(home=metrics_home):
    now = int(time.time())
    _write(f'system,host=h uptime_format=" 1:20",load1=1.5 {now}', now=now)

    assert [f.name for f in fam.families_for_host("h", now=now)] == ["load1"]


# ============ Transforms ============


@test("a rate is the per-second change of a counter")
def _():
    points = [{"ts": 0, "value": 0.0}, {"ts": 10_000, "value": 500.0}]
    assert fam.rate(points, step_ms=10_000) == [{"ts": 10_000, "value": 50.0}]


@test("a counter reset is dropped rather than drawn as a negative spike")
def _():
    points = [
        {"ts": 0, "value": 100.0},
        {"ts": 10_000, "value": 140.0},
        {"ts": 20_000, "value": 5.0},
        {"ts": 30_000, "value": 25.0},
    ]
    values = [p["value"] for p in fam.rate(points, step_ms=10_000)]
    assert values == [4.0, 2.0]
    assert all(v >= 0 for v in values)


@test("a single reading has no rate to report")
def _():
    assert fam.rate([{"ts": 0, "value": 1.0}], step_ms=1000) == []


@test("a quantile is interpolated inside the bucket where the count crosses it")
def _():
    # Increases of 10/20/30/40 across the buckets, so 40 observations in the window.
    buckets = [
        (1.0, [{"ts": 0, "value": 0.0}, {"ts": 10_000, "value": 10.0}]),
        (2.0, [{"ts": 0, "value": 0.0}, {"ts": 10_000, "value": 20.0}]),
        (5.0, [{"ts": 0, "value": 0.0}, {"ts": 10_000, "value": 30.0}]),
        (float("inf"), [{"ts": 0, "value": 0.0}, {"ts": 10_000, "value": 40.0}]),
    ]

    # p25 lands on 10 of 40, exactly the top of the first bucket.
    assert fam.histogram_quantile(buckets, 0.25) == [{"ts": 10_000, "value": 1.0}]
    assert fam.histogram_quantile(buckets, 0.5) == [{"ts": 10_000, "value": 2.0}]
    # Above the last finite edge there is nothing to interpolate towards, so the best
    # statement is that edge itself rather than infinity.
    assert fam.histogram_quantile(buckets, 0.9) == [{"ts": 10_000, "value": 5.0}]


@test("a quantile is read over the window, not over the counter's whole lifetime")
def _():
    # A long history of slow requests: 1000 observations, only 10 of which were fast. The
    # window holds 100 more, and every one of them landed in the fast bucket.
    buckets = [
        (1.0, [{"ts": 0, "value": 10.0}, {"ts": 10_000, "value": 110.0}]),
        (float("inf"), [{"ts": 0, "value": 1000.0}, {"ts": 10_000, "value": 1100.0}]),
    ]

    # Read cumulatively the median would sit in the slow bucket and report 1.0. Taking the
    # increase instead says what actually happened recently, which is that it was fast.
    assert fam.histogram_quantile(buckets, 0.5) == [{"ts": 10_000, "value": 0.5}]


@test("a window in which nothing was observed reports no quantile at all")
def _():
    buckets = [
        (1.0, [{"ts": 0, "value": 5.0}, {"ts": 10_000, "value": 5.0}]),
        (float("inf"), [{"ts": 0, "value": 5.0}, {"ts": 10_000, "value": 5.0}]),
    ]
    assert fam.histogram_quantile(buckets, 0.5) == []


@test("a quantile outside the open interval is refused rather than guessed at")
def _():
    buckets = [(1.0, [{"ts": 0, "value": 0.0}, {"ts": 10_000, "value": 10.0}])]
    assert fam.histogram_quantile(buckets, 0.0) == []
    assert fam.histogram_quantile(buckets, 1.0) == []
    assert fam.histogram_quantile([], 0.5) == []


@test("bucket edges parse from tag values and field names alike, including +Inf")
def _():
    assert fam.parse_bound("+Inf") == float("inf")
    assert fam.parse_bound(".05") == 0.05
    assert fam.parse_bound("1.0") == 1.0
    assert fam.parse_bound("gauge") is None
    assert fam.parse_bound("") is None
    assert fam.parse_bound("nan") is None


# ============ Suggestions ============


@test("a host whose metrics share one measurement still gets a board, not one chart")
def _(home=metrics_home):
    now = int(time.time())
    _write_v2_prometheus("h", now)

    suggested = fam.suggest("h", now=now)

    # Every series here is in the "prometheus" measurement. Ranking by family rather than
    # by measurement is the only reason this is more than a single tile.
    assert len(suggested) == 3
    assert sorted(f.name for f in suggested) == [
        "bbb_api_latency",
        "bbb_meetings_participants",
        "bbb_unique_meetings_total",
    ]


@test("a histogram is suggested once, not once per bucket")
def _(home=metrics_home):
    now = int(time.time())
    _write_v1_prometheus("h", now)

    suggested = fam.suggest("h", now=now)
    assert [f.name for f in suggested].count("bbb_api_latency") == 1
    assert all(not f.name.startswith("+Inf") for f in suggested)


@test("a series that moves is suggested over one that never budges")
def _(home=metrics_home):
    now = int(time.time())
    for offset in range(3):
        _write(
            f"cpu,host=a usage_guest=0.0,usage_idle={80 + offset}.0 {now - offset * 10}",
            now=now,
        )

    assert [f.name for f in fam.suggest("a", now=now)] == ["usage_idle"]


@test("the suggestion spreads across measurements instead of stacking one")
def _(home=metrics_home):
    now = int(time.time())
    for offset in range(3):
        ts = now - offset * 10
        _write(
            f"cpu,host=a usage_idle={80 + offset}.0,usage_user={offset}.0 {ts}"
            f"\nmem,host=a used_percent={40 + offset}.0 {ts}"
            f"\ndisk,host=a used_percent={10 + offset}.0 {ts}",
            now=now,
        )

    measurements = [f.measurement for f in fam.suggest("a", now=now)[:3]]
    assert sorted(measurements) == ["cpu", "disk", "mem"]


@test("the suggestion honours its limit")
def _(home=metrics_home):
    now = int(time.time())
    body = "\n".join(f"m{i},host=a value={i}.0 {now}" for i in range(10))
    _write(body, now=now)

    assert len(fam.suggest("a", limit=4, now=now)) == 4


@test("a host that has sent nothing gets an empty suggestion rather than an error")
def _(home=metrics_home):
    assert fam.suggest("nobody") == []


@test("a host whose hot window has been compacted away still gets a suggestion")
def _(home=metrics_home):
    now = int(time.time())
    _write(f"cpu,host=a usage_idle=90.0 {now - 7200}", now=now)
    metrics_store.compact(now=now)

    # No hot rows left to judge variance by, so this falls back to the catalogue.
    assert fam.suggest("a", now=now) != []


# ============ Round-tripping a saved selector ============


@test("a saved selector rebuilds the family it was saved from")
def _(home=metrics_home):
    now = int(time.time())
    _write_v2_prometheus("h", now)
    original = _by_name(fam.families_for_host("h", now=now))["bbb_api_latency"]

    class Row:
        measurement = original.measurement
        field = original.field
        tags = metrics_store.encode_tags(original.tags)
        kind = original.kind
        transform = original.transform
        tag_mode = original.tag_mode
        options = '{"bucket_by": "tag", "quantiles": [0.5]}'

    rebuilt = fam.family_from_selector(fam.selector_from_row(Row()))

    assert rebuilt.key == original.key
    assert rebuilt.name == "bbb_api_latency"
    assert rebuilt.title == "bbb_api_latency"
    # A stored option wins over the default, so a board keeps the quantiles it was given.
    assert rebuilt.options()["quantiles"] == [0.5]


@test("a selector row written before this feature still reads as a plain series")
def _(home=metrics_home):
    class LegacyRow:
        measurement = "mem"
        field = "used_percent"
        tags = "{}"
        kind = "gauge"
        transform = "raw"
        tag_mode = "exact"
        options = "{}"

    selector = fam.selector_from_row(LegacyRow())
    rebuilt = fam.family_from_selector(selector)

    assert rebuilt.kind == fam.KIND_GAUGE
    assert rebuilt.transform == fam.TRANSFORM_RAW
    assert rebuilt.tag_mode == "exact"
    assert rebuilt.title == "mem.used_percent"


@test("a selector carrying unreadable JSON degrades instead of raising")
def _(home=metrics_home):
    class BrokenRow:
        measurement = "mem"
        field = "used_percent"
        tags = "not json"
        kind = "gauge"
        transform = "raw"
        tag_mode = "exact"
        options = "also not json"

    selector = fam.selector_from_row(BrokenRow())
    assert selector["tags"] == {}
    assert selector["options"] == {}
