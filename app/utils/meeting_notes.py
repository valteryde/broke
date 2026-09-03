"""Parse meeting-note shorthand and turn it into project ticket drafts.

Line-start marks (optional, meeting-speed):
  # topic     sticky heading until the next #
  ! action    work to do
  = decision  record only, never a ticket
  ? question  record only unless later promoted

Inline marks:
  @name       owner
  /projectid  optional project pin (only if it matches a real project)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from .ai_changelog import get_ai_config

logger = logging.getLogger(__name__)

_ALLOWED_PRIORITIES = {"urgent", "high", "medium", "low", "none"}


class MeetingNotesError(ValueError):
    """Base error for meeting-note extraction."""


class MeetingAINotConfigured(MeetingNotesError):
    """AI settings are missing, so notes cannot be analyzed."""


class MeetingAIFailed(MeetingNotesError):
    """The model request failed or returned unusable output."""


_MARK_RE = re.compile(r"^(?P<mark>[#!=?])\s*(?P<body>.*)$")
_AT_RE = re.compile(r"@([A-Za-z0-9._-]+)")
_SLASH_RE = re.compile(r"(?<![A-Za-z0-9:/])/([A-Za-z0-9_-]+)\b")


@dataclass
class ParsedItem:
    kind: str  # action, decision, question
    text: str
    topic: str | None = None
    extra: str = ""
    assignee_hints: list[str] = field(default_factory=list)
    project_hints: list[str] = field(default_factory=list)
    quote: str = ""


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _inline_hints(text: str) -> tuple[str, list[str], list[str]]:
    assignees = [m.group(1) for m in _AT_RE.finditer(text or "")]
    project_hints = [m.group(1) for m in _SLASH_RE.finditer(text or "")]
    cleaned = _AT_RE.sub("", text or "")
    cleaned = _SLASH_RE.sub("", cleaned)
    return _normalize_space(cleaned), assignees, project_hints


def parse_meeting_notes(notes: str) -> list[ParsedItem]:
    """Split a notes dump into actions, decisions, and questions."""
    items: list[ParsedItem] = []
    topic: str | None = None
    current: ParsedItem | None = None
    preamble: list[str] = []

    def flush() -> None:
        nonlocal current
        if current is not None:
            current.extra = current.extra.strip()
            items.append(current)
            current = None

    for raw in (notes or "").splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            if current is not None and current.extra:
                current.extra += "\n"
            continue

        marked = _MARK_RE.match(stripped)
        if marked:
            mark = marked.group("mark")
            body = marked.group("body") or ""
            if mark == "#":
                flush()
                topic_text, _, _ = _inline_hints(body)
                topic = topic_text or None
                preamble = []
                continue

            kind = {"!": "action", "=": "decision", "?": "question"}[mark]
            flush()
            text, assignees, project_hints = _inline_hints(body)
            extra_parts = list(preamble)
            preamble = []
            current = ParsedItem(
                kind=kind,
                text=text or _normalize_space(body),
                topic=topic,
                extra="\n".join(extra_parts).strip(),
                assignee_hints=assignees,
                project_hints=project_hints,
                quote=stripped,
            )
            continue

        text, assignees, project_hints = _inline_hints(stripped)
        if current is not None:
            if current.extra:
                current.extra += "\n" + (text or stripped)
            else:
                current.extra = text or stripped
            current.assignee_hints.extend(assignees)
            current.project_hints.extend(project_hints)
        else:
            preamble.append(text or stripped)

    flush()
    return items


def match_project(
    hints: list[str],
    topic: str | None,
    haystack: str,
    projects: list[dict[str, str]],
) -> str | None:
    """Pick a project id from explicit hints, topic, or keyword overlap."""
    if not projects:
        return None
    if len(projects) == 1:
        return str(projects[0].get("id") or "") or None

    by_id = {
        str(p.get("id") or "").lower(): str(p.get("id") or "") for p in projects if p.get("id")
    }
    for hint in hints:
        key = (hint or "").strip().lower()
        if key in by_id:
            return by_id[key]

    lowered_topic = (topic or "").strip().lower()
    if lowered_topic in by_id:
        return by_id[lowered_topic]

    best_id = None
    best_score = 0
    blob = f"{topic or ''} {haystack or ''}".lower()
    for project in projects:
        project_id = str(project.get("id") or "").strip()
        project_name = str(project.get("name") or "").strip()
        if not project_id:
            continue
        score = 0
        if project_id.lower() in blob:
            score += 3
        if project_name.lower() and project_name.lower() in blob:
            score += 2
        for token in re.split(r"[^a-zA-Z0-9]+", project_name.lower()):
            if token and len(token) > 2 and token in blob:
                score += 1
        if score > best_score:
            best_score = score
            best_id = project_id
    if best_score == 0:
        return None
    return best_id


def match_usernames(hints: list[str], usernames: list[str]) -> list[str]:
    by_lower = {name.lower(): name for name in usernames if name}
    out: list[str] = []
    seen: set[str] = set()
    for hint in hints:
        real = by_lower.get((hint or "").strip().lower())
        if real and real not in seen:
            seen.add(real)
            out.append(real)
    return out


def _item_description(item: ParsedItem) -> str:
    parts: list[str] = []
    if item.topic:
        parts.append(f"Topic: {item.topic}")
    if item.extra:
        parts.append(item.extra)
    return "\n\n".join(parts).strip()


def _fallback_from_parse(
    items: list[ParsedItem],
    projects: list[dict[str, str]],
    usernames: list[str],
    reason: str,
) -> dict[str, Any]:
    tickets: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    decisions: list[dict[str, str]] = []
    questions: list[dict[str, str]] = []

    for item in items:
        if item.kind == "decision":
            decisions.append({"text": item.text, "topic": item.topic or ""})
            continue
        if item.kind == "question":
            questions.append({"text": item.text, "topic": item.topic or ""})
            continue
        if item.kind != "action" or not item.text:
            continue

        haystack = f"{item.text} {item.extra}"
        project_id = match_project(item.project_hints, item.topic, haystack, projects)
        draft = {
            "title": item.text[:140],
            "description": _item_description(item) or item.text,
            "project": project_id,
            "priority": "medium",
            "assignees": match_usernames(item.assignee_hints, usernames),
            "marked": True,
            "quote": item.quote,
        }
        if not project_id:
            skipped.append({"title": draft["title"], "reason": "No matching project"})
            continue
        tickets.append(draft)

    return {
        "tickets": tickets,
        "decisions": decisions,
        "questions": questions,
        "skipped": skipped,
        "source": "fallback",
        "reason": reason,
    }


def _parse_model_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return json.loads(text)


def _normalize_priority(value: Any) -> str:
    priority = str(value or "medium").strip().lower()
    if priority not in _ALLOWED_PRIORITIES:
        return "medium"
    return priority


def _normalize_ai_extract(
    parsed: dict[str, Any],
    items: list[ParsedItem],
    projects: list[dict[str, str]],
    usernames: list[str],
) -> dict[str, Any]:
    project_ids = {str(p.get("id")) for p in projects if p.get("id")}
    tickets: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    for raw in parsed.get("tickets") or []:
        if not isinstance(raw, dict):
            continue
        title = _normalize_space(str(raw.get("title") or ""))[:140]
        if not title:
            continue
        description = str(raw.get("description") or "").strip() or title
        project_id = str(raw.get("project") or "").strip()
        if project_id not in project_ids:
            project_id = (
                match_project(
                    [project_id] if project_id else [],
                    str(raw.get("topic") or "") or None,
                    f"{title} {description}",
                    projects,
                )
                or ""
            )
        assignees_raw = raw.get("assignees") or []
        if isinstance(assignees_raw, str):
            assignees_raw = [assignees_raw]
        if not isinstance(assignees_raw, list):
            assignees_raw = []
        assignees = match_usernames([str(a) for a in assignees_raw], usernames)
        draft = {
            "title": title,
            "description": description,
            "project": project_id or None,
            "priority": _normalize_priority(raw.get("priority")),
            "assignees": assignees,
            "marked": bool(raw.get("marked")),
            "quote": str(raw.get("quote") or "").strip(),
        }
        if not project_id:
            project_id = str(projects[0].get("id") or "") if projects else ""
            draft["project"] = project_id or None
        if not project_id:
            skipped.append({"title": title, "reason": "No matching project"})
            continue
        tickets.append(draft)

    decisions = []
    for raw in parsed.get("decisions") or []:
        if isinstance(raw, dict):
            text = _normalize_space(str(raw.get("text") or ""))
            if text:
                decisions.append({"text": text, "topic": str(raw.get("topic") or "")})
        elif isinstance(raw, str) and raw.strip():
            decisions.append({"text": _normalize_space(raw), "topic": ""})

    questions = []
    for raw in parsed.get("questions") or []:
        if isinstance(raw, dict):
            text = _normalize_space(str(raw.get("text") or ""))
            if text:
                questions.append({"text": text, "topic": str(raw.get("topic") or "")})
        elif isinstance(raw, str) and raw.strip():
            questions.append({"text": _normalize_space(raw), "topic": ""})

    # Keep explicit ! actions even if the model dropped them.
    covered = {_normalize_space(t["title"]).lower() for t in tickets}
    for item in items:
        if item.kind != "action" or not item.text:
            continue
        key = _normalize_space(item.text).lower()
        if any(key in c or c in key for c in covered):
            continue
        fallback_one = _fallback_from_parse([item], projects, usernames, "")
        for ticket in fallback_one["tickets"]:
            tickets.append(ticket)
            covered.add(_normalize_space(ticket["title"]).lower())
        skipped.extend(fallback_one["skipped"])

    if not decisions:
        decisions = [
            {"text": i.text, "topic": i.topic or ""} for i in items if i.kind == "decision"
        ]
    if not questions:
        questions = [
            {"text": i.text, "topic": i.topic or ""} for i in items if i.kind == "question"
        ]

    return {
        "tickets": tickets,
        "decisions": decisions,
        "questions": questions,
        "skipped": skipped,
        "source": "ai",
        "reason": "AI extracted work from meeting notes.",
    }


def extract_meeting_work(
    notes: str,
    projects: list[dict[str, str]],
    usernames: list[str],
    meeting_title: str = "",
) -> dict[str, Any]:
    """Send the full notes dump to AI and return filled-in ticket drafts."""
    if not (notes or "").strip():
        raise ValueError("Notes are required")

    items = parse_meeting_notes(notes)
    config = get_ai_config()
    if not config:
        raise MeetingAINotConfigured(
            "AI is not configured. Add an API key in Settings → AI Integration."
        )

    try:
        import openai
    except ImportError as exc:
        raise MeetingAIFailed(
            "The openai package is missing, so notes cannot be analyzed."
        ) from exc

    project_lines = [f"- {p.get('id')}: {p.get('name')}" for p in projects if p.get("id")]
    project_text = "\n".join(project_lines) if project_lines else "- (none available)"
    user_text = ", ".join(usernames) if usernames else "(none)"
    parsed_hint = json.dumps(
        [
            {
                "kind": item.kind,
                "text": item.text,
                "topic": item.topic,
                "extra": item.extra,
                "assignees": item.assignee_hints,
                "project_hints": item.project_hints,
            }
            for item in items
        ],
        ensure_ascii=False,
    )
    title_line = (meeting_title or "").strip() or "(untitled meeting)"

    prompt = f"""You analyze meeting notes for an issue tracker.

The notes are often messy: fragments, shorthand, typos, or half-finished sentences.
Read the ENTIRE notes dump. Rewrite it into clear tickets and records.
Do not wait for perfect wording. Infer the intended work from context.

Return JSON only with keys:
- tickets: array of {{title, description, project, priority, assignees, marked, quote}}
- decisions: array of {{text, topic}}
- questions: array of {{text, topic}}

Rules:
- Create a ticket for every piece of work someone should do, fix, check, ship, or follow up on.
- Optional line marks: # topic, ! action, = decision, ? question, @name owner, /projectid pin.
- Treat marks as hints only. Unmarked prose that sounds like work MUST still become a ticket.
- ! lines MUST become tickets (marked=true). Other inferred tickets use marked=false.
- = decisions must NEVER become tickets. Record them under decisions, including "we will not".
- ? questions go under questions, unless they are clearly assigned work.
- title: rewrite scribbles into a short actionable title (5-12 words).
- description: fill in what the notes imply so a teammate can act. Include nearby context.
  Do not invent facts that are not implied by the notes.
- project: must be one of the available project ids. Pick the best fit from wording and topics.
  If still unclear, pick the closest project. Do not drop a ticket for a weak project match.
- priority: urgent, high, medium, low, or none.
- assignees: only usernames from the provided list (or empty).
- quote: the original snippet this ticket came from.
- Output JSON only.

Meeting title:
{title_line}

Available projects:
{project_text}

Usernames:
{user_text}

Parsed marks (optional hints, may be empty or incomplete):
{parsed_hint}

Raw notes:
{notes}
"""

    try:
        client = openai.OpenAI(
            api_key=config["api_key"], base_url=config.get("base_url", "https://api.openai.com/v1")
        )
        response = client.chat.completions.create(
            model=config.get("model", "gpt-4o-mini"),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You turn messy meeting notes into clear issue-tracker JSON. "
                        "Output only valid JSON with the required keys."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=4000,
        )
        parsed = _parse_model_json(response.choices[0].message.content or "")
        if not isinstance(parsed, dict):
            raise ValueError("Model did not return an object")
        return _normalize_ai_extract(parsed, items, projects, usernames)
    except MeetingNotesError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("Meeting notes AI extract failed: %s", exc)
        raise MeetingAIFailed("Could not analyze the meeting notes. Try Done again.") from exc
