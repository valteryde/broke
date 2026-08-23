"""Ask a model to lay out a host's dashboard: which charts, grouped under what headings.

Provider-agnostic in the same way as the changelog and intake helpers — an
OpenAI-compatible endpoint configured once in settings.

Two things shape this module. The first is that a model's answer is a *suggestion about
presentation*, never an instruction: every id it returns is looked up in the catalogue it
was given, and anything else is dropped. A hallucinated metric name cannot reach the
database, and a malformed reply costs the operator a click rather than their board.

The second is that charts are offered to the model as small integers rather than as their
family keys. A key like ``prometheus|http_request_duration_seconds_bucket|{}|histogram``
is long, punctuated and easy to mangle a character of; "17" is not. The mapping back is
exact, so a mangled id fails loudly by missing the table instead of quietly selecting the
wrong series.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from .ai_changelog import get_ai_config

logger = logging.getLogger(__name__)

# Ceilings for what a model may propose. They exist so one confused reply cannot produce a
# page nobody can read; the caller's own board limit is applied on save regardless.
MAX_SECTIONS = 6
MAX_CATALOGUE = 150

# How long to let a section name run before it stops being a heading.
MAX_NAME = 60


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _parse_model_json(raw: str) -> dict[str, Any]:
    """Read the model's reply, tolerating the code fence it sometimes wraps JSON in."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("model did not return a JSON object")
    return parsed


def _catalogue_text(catalogue: list[dict[str, Any]]) -> str:
    lines = []
    for index, entry in enumerate(catalogue, start=1):
        detail = _clean(entry.get("detail"))
        label = _clean(entry.get("label")) or f"chart {index}"
        lines.append(f"{index}: {label}" + (f" — {detail}" if detail else ""))
    return "\n".join(lines)


def _build_prompt(
    *,
    hostname: str,
    catalogue: list[dict[str, Any]],
    accents: list[str],
    instruction: str,
    max_charts: int,
) -> str:
    prompt = f"""A server called "{hostname}" reports the metrics below. Lay out a
monitoring dashboard for it: choose the charts worth watching and group them into
sections.

Charts available:
{_catalogue_text(catalogue)}

Reply with JSON only, in this shape:
{{"sections": [{{"name": "Compute", "colour": "blue", "charts": [1, 4]}}], "note": "..."}}

Rules:
- Every id in "charts" must be one of the numbers listed above. Never invent an id.
- Use at most {max_charts} charts in total and at most {MAX_SECTIONS} sections.
- Do not put the same chart in two sections.
- A section name is 1-3 words describing what the group is about, in Title Case.
- "colour" must be one of: {", ".join(accents)}. Give each section a different one.
- Order the sections, and the charts inside them, by what someone diagnosing a problem
  with this server should look at first.
- Leave out charts that would not earn their space.
- "note" is one short sentence about how you grouped things.
"""

    if instruction:
        # Last, and clearly fenced, so the wording of a request cannot be read as a change
        # to the rules above it.
        prompt += (
            "\nThe operator also asked for the following. Follow it where it makes sense,"
            " but keep every rule above:\n"
            f'"""\n{instruction}\n"""\n'
        )

    return prompt


def _normalise_sections(
    parsed: dict[str, Any],
    *,
    catalogue: list[dict[str, Any]],
    accents: list[str],
    max_charts: int,
) -> list[dict[str, Any]]:
    """Turn whatever the model said into sections this app is willing to draw."""
    raw_sections = parsed.get("sections")
    if not isinstance(raw_sections, list):
        return []

    sections: list[dict[str, Any]] = []
    used_keys: set[str] = set()
    used_accents: set[str] = set()
    budget = max_charts

    for raw in raw_sections[:MAX_SECTIONS]:
        if not isinstance(raw, dict) or budget <= 0:
            continue

        keys: list[str] = []
        for item in raw.get("charts") or []:
            if budget <= 0:
                break
            try:
                index = int(item)
            except (TypeError, ValueError):
                continue
            if not 1 <= index <= len(catalogue):
                continue
            key = str(catalogue[index - 1].get("key") or "")
            # A chart belongs to one section; a repeat is a mistake, not a request.
            if not key or key in used_keys:
                continue
            used_keys.add(key)
            keys.append(key)
            budget -= 1

        # A heading with nothing under it is not a section.
        if not keys:
            continue

        accent = _clean(raw.get("colour") or raw.get("accent")).lower()
        if accent not in accents or accent in used_accents:
            accent = next((a for a in accents if a not in used_accents), accents[0])
        used_accents.add(accent)

        name = _clean(raw.get("name"))[:MAX_NAME] or "Section"
        sections.append({"name": name, "accent": accent, "charts": keys})

    return sections


def _fallback_sections(
    catalogue: list[dict[str, Any]],
    *,
    accents: list[str],
    max_charts: int,
) -> list[dict[str, Any]]:
    """Group by what the metric is about, which is the arrangement the data already implies.

    Not as good as a model reading the host, but it is the same shape of answer, so the
    button does something useful on an install that has no AI configured and on the day the
    provider is down.
    """
    order: list[str] = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry in catalogue[:max_charts]:
        group = str(entry.get("group") or "other")
        if group not in grouped:
            grouped[group] = []
            order.append(group)
        grouped[group].append(entry)

    sections = []
    used_accents: set[str] = set()
    for group in order[:MAX_SECTIONS]:
        entries = grouped[group]
        accent = str(entries[0].get("accent") or "")
        if accent not in accents or accent in used_accents:
            accent = next((a for a in accents if a not in used_accents), accents[0])
        used_accents.add(accent)

        sections.append(
            {
                "name": _clean(entries[0].get("group_label") or group)[:MAX_NAME] or "Metrics",
                "accent": accent,
                "charts": [str(e["key"]) for e in entries],
            }
        )
    return sections


def arrange(
    *,
    hostname: str,
    catalogue: list[dict[str, Any]],
    accents: list[str],
    instruction: str = "",
    max_charts: int = 12,
) -> dict[str, Any]:
    """Propose a sectioned board for a host.

    Returns sections of family keys the caller handed in, never anything else, plus a note
    for the operator and whether a model or the fallback produced it. Nothing is saved:
    this is a proposal for someone to look at.
    """
    catalogue = [entry for entry in catalogue if entry.get("key")][:MAX_CATALOGUE]
    if not catalogue:
        return {
            "sections": [],
            "note": "This host has nothing that can be charted yet.",
            "source": "fallback",
        }

    accents = list(accents) or ["blue"]
    instruction = _clean(instruction)[:400]

    def fallback(note: str) -> dict[str, Any]:
        return {
            "sections": _fallback_sections(catalogue, accents=accents, max_charts=max_charts),
            "note": note,
            "source": "fallback",
        }

    config = get_ai_config()
    if not config:
        return fallback("AI is not configured, so charts were grouped by measurement.")

    try:
        import openai
    except ImportError:
        return fallback("The openai package is missing, so charts were grouped by measurement.")

    try:
        client = openai.OpenAI(
            api_key=config["api_key"],
            base_url=config.get("base_url", "https://api.openai.com/v1"),
        )
        response = client.chat.completions.create(
            model=config.get("model", "gpt-4o-mini"),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You lay out server monitoring dashboards. You output only valid"
                        " JSON with the required keys."
                    ),
                },
                {
                    "role": "user",
                    "content": _build_prompt(
                        hostname=hostname,
                        catalogue=catalogue,
                        accents=accents,
                        instruction=instruction,
                        max_charts=max_charts,
                    ),
                },
            ],
            temperature=0.2,
            max_tokens=900,
        )

        parsed = _parse_model_json(response.choices[0].message.content or "")
        sections = _normalise_sections(
            parsed, catalogue=catalogue, accents=accents, max_charts=max_charts
        )
        if not sections:
            return fallback(
                "The model did not pick any charts, so they were grouped by measurement."
            )

        return {
            "sections": sections,
            "note": _clean(parsed.get("note"))[:200] or "Arranged by AI.",
            "source": "ai",
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("AI board arrangement failed for %s: %s", hostname, exc)
        return fallback("The AI request failed, so charts were grouped by measurement.")
