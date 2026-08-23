"""Export an error group as JSON or Markdown for copy/paste (no tokens)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from peewee import DoesNotExist

from .models import ErrorGroup, ErrorOccurrence, ProjectPart, Ticket

_MAX_MD_CHARS = 80_000
_MAX_VAR_CHARS = 400
_MAX_VARS_PER_FRAME = 40
_MAX_OCCURRENCES = 20
_MAX_EXTRA_CHARS = 8_000


def _fmt_ts(ts: Any) -> str:
    if ts is None or ts == "":
        return ""
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError, OSError):
        return str(ts)


def _parse_json(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


def _stringify(value: Any, limit: int = _MAX_VAR_CHARS) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, default=str, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(value)
    if len(text) > limit:
        return text[:limit] + "…"
    return text


def _stacktrace_frames(stacktrace: Any) -> list[dict[str, Any]]:
    if isinstance(stacktrace, dict):
        frames = stacktrace.get("frames") or []
        if isinstance(frames, list):
            return [f for f in frames if isinstance(f, dict)]
    return []


def build_error_export_payload(error_id: int) -> dict[str, Any] | None:
    """Load an error group and related rows into a JSON-serializable payload."""
    try:
        error = ErrorGroup.get_by_id(error_id)
    except DoesNotExist:
        return None

    part: ProjectPart | None = None
    try:
        part = error.part
    except DoesNotExist:
        part = None

    ticket = Ticket.select().where(Ticket.error == error.id).first()
    occurrences = list(
        ErrorOccurrence.select()
        .where(ErrorOccurrence.error_group == error.id)
        .order_by(ErrorOccurrence.timestamp.desc())
        .limit(_MAX_OCCURRENCES)
    )

    return {
        "id": error.id,
        "status": error.status,
        "exception_type": error.exception_type,
        "exception_value": error.exception_value,
        "culprit": error.culprit,
        "platform": error.platform,
        "environment": error.environment,
        "release": error.release,
        "fingerprint": error.fingerprint,
        "event_count": error.event_count,
        "first_seen": error.first_seen,
        "last_seen": error.last_seen,
        "part": ({"id": part.id, "name": part.name} if part is not None else None),
        "ticket": (
            {"id": ticket.id, "project": ticket.project, "title": ticket.title}
            if ticket is not None
            else None
        ),
        "tags": _parse_json(error.tags, {}),
        "contexts": _parse_json(error.contexts, {}),
        "extra": _parse_json(error.extra, None),
        "stacktrace": _parse_json(error.stacktrace, None),
        "occurrences": [
            {"timestamp": occ.timestamp, "event_id": occ.event_id} for occ in occurrences
        ],
    }


def _format_frame_code(frame: dict[str, Any]) -> list[str]:
    pre = frame.get("pre_context") or []
    post = frame.get("post_context") or []
    context = frame.get("context_line")
    lineno = frame.get("lineno")
    if not isinstance(pre, list):
        pre = []
    if not isinstance(post, list):
        post = []
    if context is None and not pre and not post:
        return []

    start = int(lineno) - len(pre) if lineno else 1
    lines_src: list[str] = [str(x) if x is not None else "" for x in pre]
    if context is not None:
        lines_src.append(str(context))
    elif lineno:
        lines_src.append(f"# line {lineno}")
    lines_src.extend(str(x) if x is not None else "" for x in post)

    highlight = len(pre) if context is not None else -1
    width = max(len(str(start + len(lines_src) - 1)), 1)
    out = ["```"]
    for i, src in enumerate(lines_src):
        mark = ">" if i == highlight else " "
        num = start + i
        out.append(f"{mark} {num:>{width}} | {src}")
    out.append("```")
    return out


def _format_frame_vars(frame: dict[str, Any]) -> list[str]:
    vars_map = frame.get("vars")
    if not isinstance(vars_map, dict) or not vars_map:
        return []
    items = list(vars_map.items())
    extra = max(0, len(items) - _MAX_VARS_PER_FRAME)
    items = items[:_MAX_VARS_PER_FRAME]
    lines = ["", "**Locals**", ""]
    for name, value in items:
        lines.append(f"- `{name}`: `{_stringify(value)}`")
    if extra:
        lines.append(f"- …and {extra} more")
    return lines


def _format_stacktrace(stacktrace: Any) -> list[str]:
    frames = _stacktrace_frames(stacktrace)
    if not frames:
        return ["No stacktrace available.", ""]

    lines = [
        "Frames are oldest → newest (most recent call last).",
        "",
    ]
    for frame in frames:
        filename = frame.get("filename") or frame.get("abs_path") or "unknown"
        function = frame.get("function") or "(anonymous)"
        lineno = frame.get("lineno")
        loc = f"{filename}:{lineno}" if lineno else str(filename)
        in_app = bool(frame.get("in_app"))
        badge = " (in-app)" if in_app else ""
        lines.append(f"### `{loc}` in `{function}`{badge}")
        lines.append("")
        code = _format_frame_code(frame)
        if code:
            lines.extend(code)
            lines.append("")
        var_lines = _format_frame_vars(frame)
        if var_lines:
            lines.extend(var_lines)
            lines.append("")
    return lines


def _format_contexts(contexts: Any) -> list[str]:
    if not isinstance(contexts, dict) or not contexts:
        return []
    lines = ["## Context", ""]
    for key in ("os", "browser", "runtime", "device"):
        ctx = contexts.get(key)
        if not isinstance(ctx, dict):
            continue
        name = ctx.get("name") or ctx.get("family") or key
        detail = ctx.get("version") or ctx.get("model") or ""
        if detail:
            lines.append(f"- **{key}:** {name} {detail}".rstrip())
        else:
            lines.append(f"- **{key}:** {name}")
    extra_keys = [k for k in contexts.keys() if k not in {"os", "browser", "runtime", "device"}]
    for key in extra_keys:
        lines.append(f"- **{key}:** `{_stringify(contexts[key], 240)}`")
    lines.append("")
    return lines


def error_payload_to_markdown(payload: dict[str, Any]) -> str:
    """Render an error export payload as Markdown."""
    heading = payload.get("exception_type") or "Error"
    message = str(payload.get("exception_value") or "").strip() or "_(no message)_"
    part = payload.get("part") or {}
    part_name = part.get("name") if isinstance(part, dict) else None
    ticket = payload.get("ticket")
    tags = payload.get("tags") if isinstance(payload.get("tags"), dict) else {}

    lines = [
        f"# {heading}",
        "",
        message,
        "",
        f"- **Error id:** `{payload.get('id', '')}`",
        f"- **Status:** `{payload.get('status') or ''}`",
        f"- **Part:** `{part_name or ''}`",
        f"- **Culprit:** `{payload.get('culprit') or ''}`",
        f"- **Platform:** `{payload.get('platform') or ''}`",
        f"- **Environment:** `{payload.get('environment') or ''}`",
        f"- **Release:** `{payload.get('release') or ''}`",
        f"- **Events:** {payload.get('event_count') or 0}",
        f"- **First seen:** {_fmt_ts(payload.get('first_seen'))}",
        f"- **Last seen:** {_fmt_ts(payload.get('last_seen'))}",
        f"- **Fingerprint:** `{payload.get('fingerprint') or ''}`",
    ]
    if isinstance(ticket, dict) and ticket.get("id"):
        lines.append(f"- **Related ticket:** `{ticket.get('id')}` ({ticket.get('project') or ''})")
    else:
        lines.append("- **Related ticket:** None")
    lines.append("")

    if tags:
        lines.append("## Tags")
        lines.append("")
        for key, value in tags.items():
            lines.append(f"- `{key}`: `{_stringify(value, 200)}`")
        lines.append("")

    lines.extend(_format_contexts(payload.get("contexts")))

    extra = payload.get("extra")
    if extra not in (None, {}, []):
        extra_text = _stringify(extra, _MAX_EXTRA_CHARS)
        lines.extend(["## Extra", "", "```json", extra_text, "```", ""])

    lines.extend(["## Stacktrace", ""])
    lines.extend(_format_stacktrace(payload.get("stacktrace")))

    occurrences = payload.get("occurrences") or []
    lines.extend(["## Occurrences", ""])
    if occurrences:
        for occ in occurrences:
            if not isinstance(occ, dict):
                continue
            event_id = occ.get("event_id") or ""
            suffix = f" `{event_id}`" if event_id else ""
            lines.append(f"- {_fmt_ts(occ.get('timestamp'))}{suffix}")
        total = payload.get("event_count") or 0
        shown = len(occurrences)
        if isinstance(total, int) and total > shown:
            lines.append(f"- …and {total - shown} more")
    else:
        lines.append("No occurrences recorded.")
    lines.append("")

    text = "\n".join(lines)
    if len(text) > _MAX_MD_CHARS:
        text = text[:_MAX_MD_CHARS] + "\n\n…(truncated for paste size)\n"
    return text
