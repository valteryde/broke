"""Local demo traffic for the Usage page. Called from setup_test_data / ``make populate``."""

from __future__ import annotations

import random
import string
import time
from typing import Any

from . import usage_store

_PAGES = [
    {"path": "/", "route": "/", "sector": "(root)"},
    {"path": "/tickets", "route": "/tickets", "sector": "tickets"},
    {"path": "/tickets/BAC-101", "route": "/tickets/:id", "sector": "tickets"},
    {"path": "/tickets/BAC-106", "route": "/tickets/:id", "sector": "tickets"},
    {"path": "/tickets/FRO-110", "route": "/tickets/:id", "sector": "tickets"},
    {"path": "/errors", "route": "/errors", "sector": "errors"},
    {"path": "/errors/grp-9f3a", "route": "/errors/:id", "sector": "errors"},
    {"path": "/settings", "route": "/settings", "sector": "settings"},
    {"path": "/settings/team", "route": "/settings/team", "sector": "settings"},
    {"path": "/settings/usage", "route": "/settings/usage", "sector": "settings"},
    {"path": "/monitors", "route": "/monitors", "sector": "monitors"},
    {"path": "/servers", "route": "/servers", "sector": "servers"},
    {"path": "/changelog", "route": "/changelog", "sector": "changelog"},
    {"path": "/docs", "route": "/docs", "sector": "docs"},
    {"path": "/login", "route": "/login", "sector": "login"},
]

_BY_PATH = {p["path"]: p for p in _PAGES}

_JOURNEYS = [
    ["/", "/tickets", "/tickets/BAC-106"],
    ["/", "/tickets", "/tickets/BAC-101", "/settings"],
    ["/login", "/", "/tickets"],
    ["/", "/errors", "/errors/grp-9f3a"],
    ["/tickets", "/tickets/FRO-110"],
    ["/", "/docs"],
    ["/settings", "/settings/team"],
    ["/", "/monitors"],
    ["/", "/servers"],
    ["/tickets", "/tickets/BAC-106", "/tickets", "/errors"],
    ["/", "/tickets", "/tickets/BAC-106", "/tickets/FRO-110", "/settings"],
    ["/login", "/tickets"],
    ["/", "/changelog"],
    ["/docs", "/tickets", "/tickets/BAC-101"],
]

_PLACES = [
    ("DK", "Hovedstaden", "Copenhagen"),
    ("DK", "Hovedstaden", "Copenhagen"),
    ("DE", "Berlin", "Berlin"),
    ("GB", "England", "London"),
    ("US", "New York", "New York"),
    ("FR", "Île-de-France", "Paris"),
    ("SE", "Stockholm", "Stockholm"),
    ("NL", "North Holland", "Amsterdam"),
    ("JP", "Tokyo", "Tokyo"),
    (None, None, None),
]

_NAMED_EVENTS = ["invite_sent", "ticket_created", "comment_added", "search"]
_ALPHABET = string.ascii_letters + string.digits


def _rid(rng: random.Random, prefix: str) -> str:
    return prefix + "".join(rng.choice(_ALPHABET) for _ in range(16))


def _session_start(rng: random.Random, now: int) -> int:
    """Bias toward the last day and last week so 24h / 7d / 30d all look busy."""
    roll = rng.random()
    if roll < 0.38:
        span = 24 * 3600
    elif roll < 0.82:
        span = 7 * 24 * 3600
    else:
        span = 21 * 24 * 3600
    return now - rng.randint(90, span)


def _event(
    *,
    ts: int,
    visitor: str,
    session: str,
    page: dict[str, str],
    place: tuple[str | None, str | None, str | None],
    kind: str = "pageview",
    name: str | None = None,
    referrer_path: str | None = None,
) -> dict[str, Any]:
    country, region, city = place
    return {
        "ts": ts * 1000,
        "visitor": visitor,
        "session": session,
        "kind": kind,
        "path": page["path"],
        "route": page["route"],
        "sector": page["sector"],
        "referrer_path": referrer_path,
        "name": name,
        "country": country,
        "region": region,
        "city": city,
    }


def seed_demo_usage(*, now: int | None = None, sessions: int = 180) -> int:
    """Wipe the usage lake and write a few days of plausible product traffic."""
    now = int(now if now is not None else time.time())
    rng = random.Random(42)
    usage_store.wipe()

    rows: list[dict[str, Any]] = []
    returning: dict[str, str] = {}

    for _ in range(sessions):
        if returning and rng.random() < 0.28:
            visitor = rng.choice(list(returning))
        else:
            visitor = _rid(rng, "v")
            returning[visitor] = visitor
        session = _rid(rng, "s")
        place = rng.choice(_PLACES)
        start = min(now - 30, max(now - 21 * 86400, _session_start(rng, now)))

        if rng.random() < 0.34:
            page = rng.choice(_PAGES[:6])
            rows.append(_event(ts=start, visitor=visitor, session=session, page=page, place=place))
            continue

        journey = list(rng.choice(_JOURNEYS))
        cursor = start
        prev = None
        for path in journey:
            page = _BY_PATH[path]
            rows.append(
                _event(
                    ts=cursor,
                    visitor=visitor,
                    session=session,
                    page=page,
                    place=place,
                    referrer_path=prev,
                )
            )
            prev = page["path"]
            cursor += rng.randint(12, 90)
        if rng.random() < 0.22:
            rows.append(
                _event(
                    ts=cursor + rng.randint(2, 20),
                    visitor=visitor,
                    session=session,
                    page=_BY_PATH[journey[-1]],
                    place=place,
                    kind="event",
                    name=rng.choice(_NAMED_EVENTS),
                    referrer_path=prev,
                )
            )

    result = usage_store.write_events(rows, now=now, max_age_ms=None)
    return result.written
