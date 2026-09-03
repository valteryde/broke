"""Parse and format ticket time estimates.

Stored as minutes. A day is 8 hours of work; a week is 5 days.
"""

from __future__ import annotations

import re
from typing import Any

MINUTES_PER_HOUR = 60
MINUTES_PER_DAY = 8 * MINUTES_PER_HOUR
MINUTES_PER_WEEK = 5 * MINUTES_PER_DAY
MAX_ESTIMATE_MINUTES = 4 * MINUTES_PER_WEEK  # 4 work weeks

_CLEAR_VALUES = {"", "none", "null", "no", "clear", "-", "0", "no estimate"}

_TOKEN_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(w(?:eeks?)?|d(?:ays?)?|h(?:ours?|rs?)?|m(?:ins?|inutes?)?)?",
    re.IGNORECASE,
)


def format_estimate_minutes(minutes: int | None) -> str:
    """Human label such as ``2h`` or ``1d 4h``. Empty when unset."""
    if minutes is None:
        return ""
    try:
        remaining = int(minutes)
    except (TypeError, ValueError):
        return ""
    if remaining <= 0:
        return ""

    weeks, remaining = divmod(remaining, MINUTES_PER_WEEK)
    days, remaining = divmod(remaining, MINUTES_PER_DAY)
    hours, remaining = divmod(remaining, MINUTES_PER_HOUR)
    parts: list[str] = []
    if weeks:
        parts.append(f"{weeks}w")
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if remaining:
        parts.append(f"{remaining}m")
    return " ".join(parts)


def parse_estimate_input(value: Any, *, bare_unit: str = "hours") -> int | None:
    """Parse a duration string or number into minutes.

    Bare numbers use ``bare_unit`` (``hours`` or ``minutes``). Empty / none clears.
    Raises ``ValueError`` when the value cannot be understood.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("Estimate must be a duration, not a boolean")
    if isinstance(value, (int, float)):
        amount = float(value)
        if bare_unit == "minutes":
            minutes = int(round(amount))
        else:
            minutes = int(round(amount * MINUTES_PER_HOUR))
        return _clamp_minutes(minutes, integer_is_minutes=True)

    text = str(value).strip()
    if text.lower() in _CLEAR_VALUES:
        return None

    cleaned = re.sub(r"[,+]|and", " ", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return None

    total = 0.0
    consumed = 0
    for match in _TOKEN_RE.finditer(cleaned):
        if match.start() != consumed and cleaned[consumed : match.start()].strip():
            raise ValueError("Could not parse time estimate")
        # Allow a single space between tokens
        consumed = match.end()
        amount = float(match.group(1))
        unit = (match.group(2) or "").lower()
        if not unit:
            if bare_unit == "minutes":
                total += amount
            else:
                total += amount * MINUTES_PER_HOUR
        elif unit.startswith("w"):
            total += amount * MINUTES_PER_WEEK
        elif unit.startswith("d"):
            total += amount * MINUTES_PER_DAY
        elif unit.startswith("h"):
            total += amount * MINUTES_PER_HOUR
        else:
            total += amount

    if consumed < len(cleaned) and cleaned[consumed:].strip():
        raise ValueError("Could not parse time estimate")
    if consumed == 0:
        raise ValueError("Could not parse time estimate")

    minutes = int(round(total))
    if minutes <= 0:
        return None
    if minutes > MAX_ESTIMATE_MINUTES:
        raise ValueError("Estimate is too large")
    return minutes


def coerce_estimate_minutes(value: Any, *, integer_is_minutes: bool = True) -> int | None:
    """Normalize PATCH/API payloads into minutes or ``None``."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("Estimate must be a duration, not a boolean")
    if isinstance(value, (int, float)):
        return _clamp_minutes(int(round(float(value))), integer_is_minutes=integer_is_minutes)

    text = str(value).strip()
    if text.lower() in _CLEAR_VALUES:
        return None
    if re.fullmatch(r"-?\d+", text):
        return _clamp_minutes(int(text), integer_is_minutes=integer_is_minutes)
    return parse_estimate_input(text, bare_unit="hours")


def _clamp_minutes(minutes: int, *, integer_is_minutes: bool) -> int | None:
    if not integer_is_minutes:
        minutes = int(round(minutes * MINUTES_PER_HOUR))
    if minutes <= 0:
        return None
    if minutes > MAX_ESTIMATE_MINUTES:
        raise ValueError("Estimate is too large")
    return minutes
