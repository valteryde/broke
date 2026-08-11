"""Tests for the metrics hot tier, Parquet compaction, retention and queries."""

import os
import shutil
import tempfile
import time
from pathlib import Path

from ward import Scope, fixture, test

from app.utils import metrics_store
from app.utils.lineprotocol import parse


@fixture(scope=Scope.Test)
def metrics_home():
    """Point both storage tiers at a throwaway directory for one test."""
    tmp = tempfile.mkdtemp(prefix="broke_metrics_test_")
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


def _write(body: str, precision: str = "s", now: int | None = None):
    return metrics_store.write_points(parse(body, precision=precision), now=now)


@test("write_points stores one row per field and registers each series")
def _(home=metrics_home):
    now = int(time.time())
    result = _write(f"cpu,host=a,cpu=cpu0 usage_idle=90.0,usage_user=10.0 {now}")

    assert result.written == 2
    assert result.dropped == 0
    assert result.hosts == {"a"}
    assert len(metrics_store.list_series("a")) == 2


@test("the host tag becomes its own column and leaves the tag set")
def _(home=metrics_home):
    now = int(time.time())
    _write(f"cpu,host=a,cpu=cpu0 usage_idle=90.0 {now}")

    series = metrics_store.list_series("a")
    assert series[0]["tags"] == {"cpu": "cpu0"}


@test("points without a host tag land under 'unknown'")
def _(home=metrics_home):
    now = int(time.time())
    result = _write(f"cpu usage_idle=90.0 {now}")
    assert result.hosts == {metrics_store.UNKNOWN_HOST}


@test("booleans become 1/0 and strings go to the text column")
def _(home=metrics_home):
    now = int(time.time())
    _write(f'system,host=a active=true,idle=false,name="web" {now}')

    conn = metrics_store.hot_connection()
    rows = dict(conn.execute("SELECT field, value FROM hot_point").fetchall())
    assert rows["active"] == 1.0
    assert rows["idle"] == 0.0
    assert rows["name"] is None

    svalue = conn.execute("SELECT svalue FROM hot_point WHERE field = 'name'").fetchone()
    assert svalue[0] == "web"


@test("tag sets are canonical regardless of the order they arrive in")
def _(home=metrics_home):
    now = int(time.time())
    _write(f"net,host=a,b=2,c=3 rx=1.0 {now}")
    _write(f"net,host=a,c=3,b=2 rx=2.0 {now + 1}")

    assert len(metrics_store.list_series("a")) == 1


@test("the cardinality cap drops new series but keeps existing ones flowing")
def _(home=metrics_home):
    os.environ["METRICS_MAX_SERIES_PER_HOST"] = "3"
    try:
        now = int(time.time())
        first = _write(f"m,host=a f1=1,f2=2,f3=3 {now}")
        assert first.written == 3
        assert first.dropped == 0

        second = _write(f"m,host=a f1=1,f4=4,f5=5 {now + 1}")
        assert second.written == 1
        assert second.dropped == 2

        # A different host gets its own budget.
        third = _write(f"m,host=b f1=1,f2=2 {now + 1}")
        assert third.written == 2
    finally:
        os.environ.pop("METRICS_MAX_SERIES_PER_HOST", None)


@test("compaction moves aged rows into parquet and empties the hot tier")
def _(home=metrics_home):
    now = int(time.time())
    old = now - 7200
    _write(f"cpu,host=a usage_idle=90.0 {old}\ncpu,host=a usage_idle=80.0 {now - 10}")

    result = metrics_store.compact(now=now)
    assert result.files_written == 1
    assert result.rows_compacted == 1

    conn = metrics_store.hot_connection()
    assert conn.execute("SELECT COUNT(*) FROM hot_point").fetchone()[0] == 1
    assert list((home / "metrics").glob("dt=*/*/part-*.parquet"))


@test("compacting twice is a no-op")
def _(home=metrics_home):
    now = int(time.time())
    _write(f"cpu,host=a usage_idle=90.0 {now - 7200}")

    assert metrics_store.compact(now=now).rows_compacted == 1
    assert metrics_store.compact(now=now).rows_compacted == 0
    assert len(list((home / "metrics").glob("dt=*/*/part-*.parquet"))) == 1


@test("compaction leaves no .tmp files behind")
def _(home=metrics_home):
    now = int(time.time())
    _write(f"cpu,host=a usage_idle=90.0 {now - 7200}")
    metrics_store.compact(now=now)

    assert not list((home / "metrics").rglob("*.tmp"))


@test("a query reads back compacted points")
def _(home=metrics_home):
    now = int(time.time())
    old = now - 7200
    _write(f"cpu,host=a usage_idle=90.0 {old}\ncpu,host=a usage_idle=70.0 {old + 60}")
    metrics_store.compact(now=now)

    points = metrics_store.query_series(
        host="a",
        measurement="cpu",
        field="usage_idle",
        start_ms=(old - 60) * 1000,
        end_ms=now * 1000,
        step_ms=60_000,
    )
    assert [p["value"] for p in points] == [90.0, 70.0]


@test("a bucket straddling the compaction cutoff averages both tiers together")
def _(home=metrics_home):
    now = int(time.time())
    old = now - 7200
    _write(f"cpu,host=a usage_idle=100.0 {old}\ncpu,host=a usage_idle=50.0 {now - 10}")
    metrics_store.compact(now=now)

    # One bucket wide enough to hold the cold point and the hot point.
    points = metrics_store.query_series(
        host="a",
        measurement="cpu",
        field="usage_idle",
        start_ms=(old - 60) * 1000,
        end_ms=(now + 60) * 1000,
        step_ms=24 * 3600 * 1000,
    )
    assert len(points) == 1
    assert points[0]["value"] == 75.0


@test("min, max and sum aggregates are honoured")
def _(home=metrics_home):
    now = int(time.time())
    _write(f"cpu,host=a usage_idle=10.0 {now - 30}\ncpu,host=a usage_idle=30.0 {now - 20}")

    kwargs = dict(
        host="a",
        measurement="cpu",
        field="usage_idle",
        start_ms=(now - 60) * 1000,
        end_ms=(now + 1) * 1000,
        step_ms=3600_000,
    )
    assert metrics_store.query_series(aggregate="min", **kwargs)[0]["value"] == 10.0
    assert metrics_store.query_series(aggregate="max", **kwargs)[0]["value"] == 30.0
    assert metrics_store.query_series(aggregate="sum", **kwargs)[0]["value"] == 40.0
    assert metrics_store.query_series(aggregate="avg", **kwargs)[0]["value"] == 20.0


@test("queries can be narrowed to one tag set")
def _(home=metrics_home):
    now = int(time.time())
    _write(f"disk,host=a,path=/ used=10.0 {now - 5}\ndisk,host=a,path=/data used=90.0 {now - 5}")

    points = metrics_store.query_series(
        host="a",
        measurement="disk",
        field="used",
        start_ms=(now - 60) * 1000,
        end_ms=(now + 1) * 1000,
        step_ms=3600_000,
        tags={"path": "/data"},
    )
    assert points[0]["value"] == 90.0


@test("querying an unknown series returns nothing rather than failing")
def _(home=metrics_home):
    now = int(time.time())
    points = metrics_store.query_series(
        host="nobody",
        measurement="cpu",
        field="usage_idle",
        start_ms=(now - 60) * 1000,
        end_ms=now * 1000,
        step_ms=60_000,
    )
    assert points == []


@test("retention removes day partitions past the horizon")
def _(home=metrics_home):
    lake = home / "metrics"
    (lake / "dt=2020-01-01" / "old-host").mkdir(parents=True)
    (lake / "dt=2020-01-01" / "old-host" / "part-1-1-1.parquet").write_bytes(b"x")
    recent = time.strftime("%Y-%m-%d", time.gmtime())
    (lake / f"dt={recent}" / "new-host").mkdir(parents=True)

    assert metrics_store.apply_retention(now=int(time.time()), days=30) == 1
    assert not (lake / "dt=2020-01-01").exists()
    assert (lake / f"dt={recent}").exists()


@test("retention ignores directories that are not day partitions")
def _(home=metrics_home):
    lake = home / "metrics"
    (lake / "dt=not-a-date").mkdir(parents=True)
    (lake / "stray").mkdir(parents=True)

    assert metrics_store.apply_retention(now=int(time.time()), days=1) == 0
    assert (lake / "dt=not-a-date").exists()
    assert (lake / "stray").exists()


@test("stale .tmp files from a killed compaction are cleaned up")
def _(home=metrics_home):
    lake = home / "metrics" / "dt=2020-01-01"
    lake.mkdir(parents=True)
    orphan = lake / "part-1-1-1.parquet.tmp"
    orphan.write_bytes(b"x")
    os.utime(orphan, (0, 0))

    fresh = lake / "part-2-2-2.parquet.tmp"
    fresh.write_bytes(b"x")

    assert metrics_store.cleanup_orphan_temp_files() == 1
    assert not orphan.exists()
    assert fresh.exists()


@test("host directory names are filesystem safe and collision free")
def _(home=metrics_home):
    awkward = metrics_store.host_dirname("weird/host name")
    assert "/" not in awkward
    assert " " not in awkward
    assert metrics_store.host_dirname("a/b") != metrics_store.host_dirname("a_b")
    assert metrics_store.host_dirname("web-01") == metrics_store.host_dirname("web-01")


@test("purging a host clears both tiers")
def _(home=metrics_home):
    now = int(time.time())
    _write(f"cpu,host=a usage_idle=1.0 {now - 7200}\ncpu,host=b usage_idle=1.0 {now - 7200}")
    metrics_store.compact(now=now)

    metrics_store.purge_host("a")

    assert metrics_store.list_series("a") == []
    assert metrics_store.list_series("b") != []
    assert not list((home / "metrics").glob(f"dt=*/{metrics_store.host_dirname('a')}"))
    assert list((home / "metrics").glob(f"dt=*/{metrics_store.host_dirname('b')}"))


@test("latest_value and aggregate_latest summarise the newest readings")
def _(home=metrics_home):
    now = int(time.time())
    _write(
        f"disk,host=a,path=/ used_percent=10.0 {now - 60}\n"
        f"disk,host=a,path=/ used_percent=20.0 {now - 5}\n"
        f"disk,host=a,path=/data used_percent=80.0 {now - 5}"
    )

    latest = metrics_store.latest_value(
        host="a", measurement="disk", field="used_percent", tags={"path": "/"}, now=now
    )
    assert latest == 20.0

    busiest = metrics_store.aggregate_latest(
        host="a", measurement="disk", field="used_percent", now=now, aggregate="max"
    )
    assert busiest == 80.0


@test("readings older than the lookback window are ignored")
def _(home=metrics_home):
    now = int(time.time())
    _write(f"mem,host=a used_percent=50.0 {now - 4000}")

    assert (
        metrics_store.latest_value(
            host="a", measurement="mem", field="used_percent", within_seconds=900, now=now
        )
        is None
    )


@test("store_stats reports both tiers")
def _(home=metrics_home):
    now = int(time.time())
    _write(f"cpu,host=a usage_idle=1.0 {now}")

    stats = metrics_store.store_stats()
    assert stats["hot_rows"] == 1
    assert stats["series_count"] == 1
    assert stats["host_count"] == 1
    assert stats["retention_days"] == metrics_store.retention_days()


@test("maintenance runs compaction and retention in one sweep")
def _(home=metrics_home):
    from app.utils.metrics_worker import run_maintenance

    now = int(time.time())
    _write(f"cpu,host=a usage_idle=1.0 {now - 7200}")

    result = run_maintenance(now=now)
    assert result["rows_compacted"] == 1
    assert result["files_written"] == 1


# ============ Suggesting a starting board ============


def _keys(charts):
    return [(c["measurement"], c["field"]) for c in charts]


@test("a series that moves is suggested over one that never budges")
def _(home=metrics_home):
    now = int(time.time())
    for offset in range(3):
        _write(
            f"cpu,host=a usage_guest=0.0,usage_idle={80 + offset}.0 {now - offset * 10}",
            now=now,
        )

    assert _keys(metrics_store.suggest_charts("a")) == [("cpu", "usage_idle")]


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

    suggested = metrics_store.suggest_charts("a")
    measurements = [m for m, _ in _keys(suggested)]
    assert sorted(measurements) == ["cpu", "disk", "mem"]
    assert len(measurements) == len(set(measurements))


@test("the suggestion honours its limit")
def _(home=metrics_home):
    now = int(time.time())
    body = "\n".join(f"m{i},host=a value={i}.0 {now}" for i in range(10))
    _write(body, now=now)

    assert len(metrics_store.suggest_charts("a", limit=4)) == 4


@test("string-only series are never suggested, since there is nothing to plot")
def _(home=metrics_home):
    now = int(time.time())
    _write(f'system,host=a name="web",load1=1.5 {now}', now=now)

    assert _keys(metrics_store.suggest_charts("a")) == [("system", "load1")]


@test("a host whose hot window has been compacted away still gets a suggestion")
def _(home=metrics_home):
    now = int(time.time())
    _write(f"cpu,host=a usage_idle=90.0 {now - 7200}", now=now)
    metrics_store.compact(now=now)

    # No hot rows left to judge variance by, so this falls through to the catalogue.
    assert metrics_store.suggest_charts("a", now=now) != []


@test("a host that has sent nothing gets an empty suggestion rather than an error")
def _(home=metrics_home):
    assert metrics_store.suggest_charts("nobody") == []


@test("text-only series are identified so the picker can leave them out")
def _(home=metrics_home):
    now = int(time.time())
    _write(f'system,host=a uptime_format=" 1:20",load1=1.5 {now}', now=now)

    text_only = metrics_store.text_only_series("a", now=now)
    assert ("system", "uptime_format", "{}") in text_only
    assert ("system", "load1", "{}") not in text_only


@test("a series with no recent points is not assumed to be text")
def _(home=metrics_home):
    now = int(time.time())
    _write(f"cpu,host=a usage_idle=90.0 {now - 7200}", now=now)

    # Outside the hot window there is no evidence either way, and guessing "text" here
    # would quietly hide a chartable series from the picker.
    assert metrics_store.text_only_series("a", now=now) == set()
