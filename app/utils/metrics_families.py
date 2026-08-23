"""
Folding the flat series catalogue into things worth putting on one chart.

The store keeps one row per ``(measurement, field, tags)`` because that is what line
protocol delivers, but very little monitoring data is actually one line on its own. A
Prometheus histogram arrives as a dozen cumulative bucket counters that only mean
something read together; a counter is a ramp until you differentiate it; ``disk`` reports
the same field once per mount. This module is the layer that recognises those shapes and
hands the rest of the app *families* instead of loose series.

Classification happens at read time from the catalogue rather than being recorded at
ingest. Nothing here is baked into stored data, so a rule that turns out to be wrong is a
code change rather than a migration plus a backfill.

Two Telegraf mappings have to be understood, because ``inputs.prometheus`` can emit
either and the default is not the one most examples show:

* ``metric_version = 1`` makes the Prometheus metric name the *measurement* and gives
  fields generic keys — ``gauge``, ``counter``, or for a histogram one field per bucket
  boundary (``0.01``, ``+Inf``) alongside ``count`` and ``sum``.
* ``metric_version = 2`` makes the metric name the *field* and puts everything in a
  single measurement (``prometheus`` unless overridden), with bucket boundaries in an
  ``le`` tag and summary quantiles in a ``quantile`` tag.

So the bucket axis is fields in one mapping and a tag in the other. ``bucket_by`` records
which, and the query layer groups accordingly.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any, Iterable

from . import metrics_store

# Tags Prometheus uses to carry a bucket edge. They are part of the family's identity
# rather than part of its tag filter, so they are stripped when grouping.
BUCKET_TAG = "le"
QUANTILE_TAG = "quantile"

KIND_GAUGE = "gauge"
KIND_COUNTER = "counter"
KIND_HISTOGRAM = "histogram"
KIND_SUMMARY = "summary"

BUCKET_BY_TAG = "tag"
BUCKET_BY_FIELD = "field"
BUCKET_BY_NONE = ""

TRANSFORM_RAW = "raw"
TRANSFORM_RATE = "rate"

# Quantiles drawn for a histogram or reported for a summary that has no opinion.
DEFAULT_QUANTILES = (0.5, 0.9, 0.99)

# Generic field keys Telegraf writes under metric_version = 1. When a series uses one the
# real metric name is the measurement, so the field is noise in a label.
GENERIC_FIELDS = {"gauge", "counter", "untyped"}

# Companion series every histogram and summary carries. They are absorbed into the family
# rather than offered as charts of their own.
AGGREGATE_FIELDS = {"count", "sum"}
AGGREGATE_SUFFIXES = ("_count", "_sum")

# Measurements that are only a container for metrics named by their field, which is what
# metric_version = 2 produces. Naming one in a chart title says nothing, so it is dropped.
CONTAINER_MEASUREMENTS = {"prometheus"}

# Series that count upwards forever, where the reading anyone wants is the rate. This
# decides how a series is *interpreted*, never whether it appears: a chart is on a board
# because someone put it there or because the data earned it, and nothing in this set
# changes that.
CUMULATIVE_FIELDS: dict[str, frozenset[str]] = {
    "net": frozenset(
        {
            "bytes_sent",
            "bytes_recv",
            "packets_sent",
            "packets_recv",
            "err_in",
            "err_out",
            "drop_in",
            "drop_out",
        }
    ),
    "diskio": frozenset(
        {
            "reads",
            "writes",
            "read_bytes",
            "write_bytes",
            "read_time",
            "write_time",
            "io_time",
            "weighted_io_time",
        }
    ),
    "kernel": frozenset({"context_switches", "interrupts", "processes_forked", "entropy_avail"}),
}


def parse_bound(raw: str) -> float | None:
    """A bucket edge from a tag value or a field name, or None if it is not one.

    ``+Inf`` is the final bucket of every Prometheus histogram and parses to infinity,
    which is exactly what the quantile maths wants as an open upper edge.
    """
    text = (raw or "").strip()
    if not text:
        return None
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(value) else value


def is_cumulative(measurement: str, field: str) -> bool:
    """Whether a series counts upwards from process start rather than reporting a level."""
    if field == "counter":
        return True
    # The Prometheus convention, and the one exporters follow most consistently.
    if field.endswith("_total"):
        return True
    if measurement == "cpu" and field.startswith("time_"):
        return True
    return field in CUMULATIVE_FIELDS.get(measurement, frozenset())


@dataclass
class Member:
    """One stored series belonging to a family."""

    field: str
    tags: dict[str, str]
    bound: float | None = None


@dataclass
class Family:
    """A set of series that belong on one chart.

    ``measurement``, ``field`` and ``tags`` together are the selector: enough to find the
    members again in the catalogue later, which is what a saved board stores. ``members``
    is the resolution of that selector against the catalogue as it looked when the family
    was built, used for labelling and for the picker.
    """

    kind: str
    measurement: str
    field: str
    tags: dict[str, str]
    name: str
    members: list[Member] = dataclass_field(default_factory=list)
    # Series that belong to the family but are not drawn: the _sum and _count a histogram
    # carries. Tracked so they are not offered as charts in their own right.
    companions: list[Member] = dataclass_field(default_factory=list)
    bucket_by: str = BUCKET_BY_NONE
    transform: str = TRANSFORM_RAW
    tag_mode: str = "filter"
    last_seen: int = 0
    # Options read back off a saved row. They win over anything derived, so a board keeps
    # drawing what it was told to even if the catalogue has since changed shape.
    stored_options: dict[str, Any] = dataclass_field(default_factory=dict)

    @property
    def key(self) -> str:
        """Stable identity for the DOM, the picker and de-duplication."""
        return "|".join(
            (self.measurement, self.field, metrics_store.encode_tags(self.tags), self.kind)
        )

    @property
    def fields(self) -> list[str]:
        """Every field this family reads, which is more than one only for a v1 histogram."""
        return sorted({member.field for member in self.members}) or [self.field]

    @property
    def title(self) -> str:
        """A readable name, given that the two Telegraf mappings hide it in different places."""
        if self.field in GENERIC_FIELDS or self.bucket_by == BUCKET_BY_FIELD:
            # metric_version = 1: the measurement is the metric name and the field is
            # Telegraf's placeholder.
            return self.measurement
        if self.measurement in CONTAINER_MEASUREMENTS:
            return self.name
        return f"{self.measurement}.{self.name}"

    @property
    def bounds(self) -> list[float]:
        return [m.bound for m in self.members if m.bound is not None]

    @property
    def tag_sets(self) -> list[dict[str, str]]:
        return [member.tags for member in self.members]

    def options(self) -> dict[str, Any]:
        """The parts of the selector that do not fit in a column of their own."""
        payload: dict[str, Any] = dict(self.stored_options)
        payload["bucket_by"] = self.bucket_by
        if self.bucket_by == BUCKET_BY_FIELD and not payload.get("fields"):
            payload["fields"] = self.fields
        if self.kind in (KIND_HISTOGRAM, KIND_SUMMARY) and not payload.get("quantiles"):
            payload["quantiles"] = list(DEFAULT_QUANTILES)
        return payload


def _strip(tags: dict[str, str], key: str) -> dict[str, str]:
    return {k: v for k, v in tags.items() if k != key}


def _base_name(field: str, suffix: str) -> str:
    return field[: -len(suffix)] if suffix and field.endswith(suffix) else field


class _Builder:
    """Accumulates families across the classification passes.

    Each series may only be claimed once, which is what lets the passes run from the most
    certain signal to the least: whatever a later, more speculative rule looks at has
    already had the series that identified themselves taken out of it.
    """

    def __init__(self) -> None:
        self.families: dict[str, Family] = {}
        self.claimed: set[tuple[str, str, str]] = set()
        # Where a metric_version = 2 family can be found from its base name, so the _sum
        # and _count beside it can be attached instead of becoming charts of their own.
        self.by_base: dict[tuple[str, str, str], str] = {}

    @staticmethod
    def identity(entry: dict[str, Any]) -> tuple[str, str, str]:
        return (
            entry["measurement"],
            entry["field"],
            metrics_store.encode_tags(entry.get("tags") or {}),
        )

    def add(
        self, family: Family, member: Member, entry: dict[str, Any], *, companion: bool = False
    ) -> Family:
        existing = self.families.setdefault(family.key, family)
        (existing.companions if companion else existing.members).append(member)
        existing.last_seen = max(existing.last_seen, int(entry.get("last_seen") or 0))
        self.claimed.add(self.identity(entry))
        return existing

    def unclaimed(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [entry for entry in entries if self.identity(entry) not in self.claimed]


def _pass_tagged_buckets(builder: _Builder, entries: list[dict[str, Any]]) -> None:
    """Series that name their own bucket edge in a tag, the metric_version = 2 shape."""
    for entry in entries:
        tags = dict(entry.get("tags") or {})
        measurement, field = entry["measurement"], entry["field"]

        if BUCKET_TAG in tags:
            kind, base, edge = KIND_HISTOGRAM, _base_name(field, "_bucket"), tags[BUCKET_TAG]
        elif QUANTILE_TAG in tags:
            kind, base, edge = KIND_SUMMARY, field, tags[QUANTILE_TAG]
        else:
            continue

        rest = _strip(tags, BUCKET_TAG if kind == KIND_HISTOGRAM else QUANTILE_TAG)
        family = builder.add(
            Family(
                kind=kind,
                measurement=measurement,
                field=field,
                tags=rest,
                name=base,
                bucket_by=BUCKET_BY_TAG,
            ),
            Member(field, tags, parse_bound(edge)),
            entry,
        )
        builder.by_base[(measurement, base, metrics_store.encode_tags(rest))] = family.key


def _pass_companions(builder: _Builder, entries: list[dict[str, Any]]) -> None:
    """The _sum and _count a metric_version = 2 histogram writes next to its buckets.

    On their own each would look like an ordinary gauge and add a chart nobody asked for
    to both the board and the picker.
    """
    for entry in builder.unclaimed(entries):
        field = entry["field"]
        suffix = next((s for s in AGGREGATE_SUFFIXES if field.endswith(s)), None)
        if suffix is None:
            continue
        lookup = (
            entry["measurement"],
            field[: -len(suffix)],
            metrics_store.encode_tags(entry.get("tags") or {}),
        )
        owner = builder.families.get(builder.by_base.get(lookup, ""))
        if owner is not None:
            owner.companions.append(Member(field, dict(entry.get("tags") or {})))
            builder.claimed.add(builder.identity(entry))


def _pass_field_buckets(builder: _Builder, entries: list[dict[str, Any]]) -> None:
    """The metric_version = 1 shape, where bucket edges are field names.

    Requires ``count`` and ``sum`` alongside, so a measurement that merely happens to have
    a field called ``0`` is not mistaken for a histogram.
    """
    by_tagset: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for entry in builder.unclaimed(entries):
        key = (entry["measurement"], metrics_store.encode_tags(entry.get("tags") or {}))
        by_tagset.setdefault(key, []).append(entry)

    for (measurement, _), group in by_tagset.items():
        names = {e["field"] for e in group}
        bounded = {n: parse_bound(n) for n in names}
        bounded = {n: b for n, b in bounded.items() if b is not None}
        if not bounded or not (AGGREGATE_FIELDS & names):
            continue

        # Every Prometheus histogram ends in a +Inf bucket; a summary's keys are quantiles
        # in [0, 1] and it has no such terminator.
        kind = KIND_HISTOGRAM if any(math.isinf(b) for b in bounded.values()) else KIND_SUMMARY
        representative = min(bounded, key=lambda n: (bounded[n], n))

        for entry in group:
            name = entry["field"]
            if name not in bounded and name not in AGGREGATE_FIELDS:
                continue
            tags = dict(entry.get("tags") or {})
            builder.add(
                Family(
                    kind=kind,
                    measurement=measurement,
                    field=representative,
                    tags=tags,
                    name=measurement,
                    bucket_by=BUCKET_BY_FIELD,
                    tag_mode="exact",
                ),
                Member(field=name, tags=tags, bound=bounded.get(name)),
                entry,
                companion=name not in bounded,
            )


def _pass_plain(builder: _Builder, entries: list[dict[str, Any]]) -> None:
    """Ordinary readings.

    Tag sets collapse into one family, so a host reporting a field once per disk or per
    core gets a single chart with several lines rather than five near-identical tiles.
    """
    for entry in builder.unclaimed(entries):
        measurement, field = entry["measurement"], entry["field"]
        cumulative = is_cumulative(measurement, field)
        builder.add(
            Family(
                kind=KIND_COUNTER if cumulative else KIND_GAUGE,
                measurement=measurement,
                field=field,
                tags={},
                name=measurement if field in GENERIC_FIELDS else field,
                transform=TRANSFORM_RATE if cumulative else TRANSFORM_RAW,
            ),
            Member(field=field, tags=dict(entry.get("tags") or {})),
            entry,
        )


def classify(series: Iterable[dict[str, Any]]) -> list[Family]:
    """Group a host's catalogue into families.

    The passes run in order of how certain their signal is. An ``le`` tag says "histogram
    bucket" outright, so those series are claimed first; the shape-based rule that has to
    infer a metric_version = 1 histogram from its field names only ever sees what is left
    over, and so cannot misread a series that already identified itself.
    """
    entries = list(series)
    builder = _Builder()

    _pass_tagged_buckets(builder, entries)
    _pass_companions(builder, entries)
    _pass_field_buckets(builder, entries)
    _pass_plain(builder, entries)

    ordered = sorted(builder.families.values(), key=lambda f: (f.measurement, f.name, f.field))
    for family in ordered:
        family.members.sort(
            key=lambda m: (
                math.inf if m.bound is None else m.bound,
                m.field,
                metrics_store.encode_tags(m.tags),
            )
        )
    return ordered


def families_for_host(host: str, *, now: int | None = None) -> list[Family]:
    """Every chartable family a host offers, string-only series excluded.

    Telegraf mixes text in with numbers — ``system.uptime_format`` and friends — and there
    is nothing to draw for those, so they are dropped before classification rather than
    being offered as a chart that would always be blank.
    """
    text_only = metrics_store.text_only_series(host, now=now)
    series = [
        entry
        for entry in metrics_store.list_series(host)
        if (entry["measurement"], entry["field"], metrics_store.encode_tags(entry["tags"]))
        not in text_only
    ]
    return classify(series)


def find_family(host: str, *, measurement: str, field: str, tags: dict[str, str], kind: str):
    """Re-resolve a saved selector against the catalogue as it stands now."""
    wanted = "|".join((measurement, field, metrics_store.encode_tags(tags), kind))
    for family in families_for_host(host):
        if family.key == wanted:
            return family
    return None


# ============ Transforms ============


def rate(points: list[dict[str, Any]], *, step_ms: int) -> list[dict[str, Any]]:
    """Per-second change of a cumulative series.

    A counter restarts at zero whenever the process behind it does, which shows up as a
    drop. There is no way to know how far it had climbed before the reset, so the sample
    is dropped rather than guessed at — one gap in the line is honest, a huge negative
    spike is not.
    """
    if len(points) < 2:
        return []

    out: list[dict[str, Any]] = []
    previous = points[0]
    for current in points[1:]:
        elapsed = (current["ts"] - previous["ts"]) / 1000.0
        delta = current["value"] - previous["value"]
        previous = current
        if elapsed <= 0 or delta < 0:
            continue
        out.append({"ts": current["ts"], "value": delta / elapsed})
    return out


def _increase_by_bucket(
    buckets: list[tuple[float, list[dict[str, Any]]]],
) -> dict[int, list[tuple[float, float]]]:
    """Turn cumulative bucket counters into per-timestamp increases.

    Prometheus quantiles are read over a window, not since the beginning of time: the
    cumulative counts would answer "what has the latency been across the whole life of
    this process", which barely moves once a service has been up a while.
    """
    per_ts: dict[int, list[tuple[float, float]]] = {}
    for bound, points in buckets:
        previous: dict[str, Any] | None = None
        for point in points:
            if previous is not None:
                delta = point["value"] - previous["value"]
                if delta >= 0:
                    per_ts.setdefault(point["ts"], []).append((bound, delta))
            previous = point
    return per_ts


def histogram_quantile(
    buckets: list[tuple[float, list[dict[str, Any]]]], quantile: float
) -> list[dict[str, Any]]:
    """Estimate a quantile over time from cumulative histogram buckets.

    Buckets are cumulative — each holds "observations at or below this edge" — so the
    crossing point is found by walking the edges in order. Within the bucket that crosses,
    the value is interpolated linearly between its lower and upper edge, which is the same
    approximation Prometheus makes and carries the same caveat: the answer is only ever as
    precise as the bucket layout.
    """
    if not buckets or not 0 < quantile < 1:
        return []

    ordered = sorted(buckets, key=lambda b: b[0])
    per_ts = _increase_by_bucket(ordered)

    out: list[dict[str, Any]] = []
    for ts in sorted(per_ts):
        edges = sorted(per_ts[ts], key=lambda pair: pair[0])
        total = max(count for _, count in edges) if edges else 0.0
        if total <= 0:
            continue

        target = quantile * total
        lower_edge = 0.0
        lower_count = 0.0
        value: float | None = None
        for bound, cumulative in edges:
            if cumulative >= target:
                if math.isinf(bound):
                    # Nothing bounds the final bucket, so its lower edge is the best
                    # statement that can be made: "at least this".
                    value = lower_edge
                else:
                    span = cumulative - lower_count
                    fraction = (target - lower_count) / span if span > 0 else 0.0
                    value = lower_edge + (bound - lower_edge) * fraction
                break
            lower_edge, lower_count = bound, cumulative

        if value is not None:
            out.append({"ts": ts, "value": value})
    return out


# ============ Suggestions ============


def suggest(host: str, *, limit: int = 8, now: int | None = None) -> list[Family]:
    """A starting board for a host nobody has arranged yet.

    Ranked over families rather than raw series, which is what stops a host whose metrics
    all share one measurement — everything Telegraf scrapes with ``metric_version = 2``
    lands in ``prometheus`` — from collapsing to a single chart.

    The ordering is data-driven. A family whose values moved beats one that sat still,
    which separates a live reading from a flag pinned at 1 or a counter nobody increments.
    Beyond that the only preference is for breadth: the first chart from a measurement
    outranks the second, so the board describes the whole host before it describes one
    corner of it in detail.
    """
    now = int(now if now is not None else time.time())
    families = families_for_host(host)
    if not families:
        return []

    varying = _varying_series(host, now=now)

    def moved(family: Family) -> bool:
        return any(
            (family.measurement, member.field, metrics_store.encode_tags(member.tags)) in varying
            for member in family.members
        )

    # A histogram or a rate is interesting even when the underlying counters look flat
    # over a short window, so they are never demoted for stillness alone.
    scored = [
        (
            family,
            moved(family) or family.kind in (KIND_HISTOGRAM, KIND_SUMMARY, KIND_COUNTER),
        )
        for family in families
    ]

    picked: list[Family] = []
    taken: set[str] = set()
    seen_measurements: set[str] = set()
    for wanted_new_measurement in (True, False):
        for family, interesting in scored:
            if len(picked) >= limit:
                break
            if family.key in taken or not interesting:
                continue
            if wanted_new_measurement and family.measurement in seen_measurements:
                continue
            seen_measurements.add(family.measurement)
            taken.add(family.key)
            picked.append(family)

    if not picked:
        picked = [family for family, _ in scored][:limit]
    return picked[:limit]


def _varying_series(host: str, *, now: int) -> set[tuple[str, str, str]]:
    """Series whose value changed inside the hot window, keyed by (measurement, field, tags)."""
    start_ms = (now - metrics_store.hot_window_seconds()) * 1000
    rows = (
        metrics_store.hot_connection()
        .execute(
            "SELECT measurement, field, tags FROM hot_point"
            " WHERE host = ? AND ts >= ? AND value IS NOT NULL"
            " GROUP BY measurement, field, tags"
            " HAVING MAX(value) > MIN(value)",
            (host, start_ms),
        )
        .fetchall()
    )
    return {(row[0], row[1], row[2] or "{}") for row in rows}


def label_for(family: Family, member_field: str, tags: dict[str, str]) -> str:
    """What one line inside a family chart is called in the legend."""
    if family.bucket_by == BUCKET_BY_TAG:
        edge = tags.get(BUCKET_TAG) or tags.get(QUANTILE_TAG) or ""
        return edge or family.name
    if family.bucket_by == BUCKET_BY_FIELD:
        return member_field

    distinguishing = {k: v for k, v in sorted(tags.items())}
    if distinguishing:
        return " ".join(f"{k}={v}" for k, v in distinguishing.items())
    return family.name


def selector_from_row(row: Any) -> dict[str, Any]:
    """Normalise a stored MetricsChart row into the arguments the query layer wants."""
    try:
        tags = json.loads(row.tags or "{}")
    except json.JSONDecodeError:
        tags = {}
    try:
        options = json.loads(getattr(row, "options", None) or "{}")
    except json.JSONDecodeError:
        options = {}
    return {
        "measurement": str(row.measurement),
        "field": str(row.field),
        "tags": tags if isinstance(tags, dict) else {},
        "kind": str(getattr(row, "kind", None) or KIND_GAUGE),
        "transform": str(getattr(row, "transform", None) or TRANSFORM_RAW),
        "tag_mode": str(getattr(row, "tag_mode", None) or "exact"),
        "options": options if isinstance(options, dict) else {},
    }


def family_from_selector(selector: dict[str, Any]) -> Family:
    """Rebuild a family from a saved selector, without consulting the catalogue.

    A board has to render even for a host that has gone quiet, so this reproduces the
    naming ``classify`` would have arrived at rather than looking the members up again.
    """
    options = selector.get("options") or {}
    bucket_by = str(options.get("bucket_by") or "")
    measurement = selector["measurement"]
    field = selector["field"]
    kind = selector.get("kind") or KIND_GAUGE

    if kind == KIND_HISTOGRAM and bucket_by == BUCKET_BY_TAG:
        name = _base_name(field, "_bucket")
    elif field in GENERIC_FIELDS or bucket_by == BUCKET_BY_FIELD:
        name = measurement
    else:
        name = field

    return Family(
        kind=kind,
        measurement=measurement,
        field=field,
        tags=selector.get("tags") or {},
        name=name,
        bucket_by=bucket_by,
        transform=selector.get("transform") or TRANSFORM_RAW,
        tag_mode=selector.get("tag_mode") or "exact",
        stored_options=options,
    )
