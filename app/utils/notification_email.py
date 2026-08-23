"""Build notification email (and Slack) bodies from event payloads."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from html import escape, unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

from .email_branding import email_base_url
from .error_markdown import build_error_export_payload, compact_stacktrace_text
from .events import EventTypes
from .models import Comment, ErrorGroup, Monitor, Ticket, TicketLabelJoin, UserTicketJoin

BODY_MAX_CHARS = 50_000
STACK_MAX_CHARS = 12_000
SUBJECT_TITLE_MAX = 90
PREHEADER_MAX = 140

EVENT_SUBJECTS = {
    EventTypes.TICKET_CREATED: "Ticket created",
    EventTypes.TICKET_TRIAGED: "Ticket sent to triage",
    EventTypes.TICKET_STATUS_CHANGED: "Ticket status changed",
    EventTypes.TICKET_COMMENTED: "New ticket comment",
    EventTypes.ANON_TICKET_SUBMITTED: "Anonymous ticket submitted",
    EventTypes.ERROR_NEW: "New error group",
    EventTypes.ERROR_REGRESSION: "Error regressed",
    EventTypes.ERROR_ESCALATING: "Error escalating",
    EventTypes.MONITOR_DOWN: "Monitor down",
    EventTypes.MONITOR_UP: "Monitor recovered",
}

_ERROR_EVENTS = {
    EventTypes.ERROR_NEW,
    EventTypes.ERROR_REGRESSION,
    EventTypes.ERROR_ESCALATING,
}
_TICKET_DESCRIPTION_EVENTS = {
    EventTypes.TICKET_CREATED,
    EventTypes.TICKET_TRIAGED,
    EventTypes.ANON_TICKET_SUBMITTED,
    EventTypes.TICKET_STATUS_CHANGED,
}
_LOW_VALUE_DETAILS = {
    "ticket created manually",
    "ticket created from ai intake",
    "anonymous ticket entered intake inbox",
    "agent api comment",
}

_BLOCK_TAGS = {
    "p",
    "div",
    "br",
    "li",
    "tr",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "blockquote",
    "pre",
    "ul",
    "ol",
    "table",
    "hr",
}
_ALLOWED_TAGS = {
    "p",
    "br",
    "div",
    "span",
    "strong",
    "b",
    "em",
    "i",
    "u",
    "s",
    "a",
    "ul",
    "ol",
    "li",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "blockquote",
    "pre",
    "code",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "img",
    "hr",
}
_ALLOWED_ATTRS = {
    "a": {"href", "title"},
    "img": {"src", "alt", "width", "height"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
}
_VOID_TAGS = {"br", "img", "hr"}
_SKIP_TAGS = {"script", "style", "iframe", "object", "embed", "form", "link", "meta", "noscript"}
_TAG_STYLES = {
    "p": "margin:0 0 10px 0;line-height:1.55;",
    "h1": "margin:0 0 12px;font-size:18px;font-weight:600;line-height:1.3;",
    "h2": "margin:0 0 10px;font-size:16px;font-weight:600;line-height:1.3;",
    "h3": "margin:0 0 8px;font-size:15px;font-weight:600;line-height:1.3;",
    "ul": "margin:0 0 10px;padding-left:20px;",
    "ol": "margin:0 0 10px;padding-left:20px;",
    "li": "margin:0 0 4px;",
    "blockquote": "margin:0 0 10px;padding-left:12px;border-left:3px solid #eaeaea;color:#666666;",
    "pre": "margin:0;white-space:pre-wrap;word-break:break-word;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px;line-height:1.45;",
    "code": "font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px;",
    "a": "color:#106ecc;text-decoration:underline;",
    "img": "max-width:100%;height:auto;border:0;",
}
_PRE_STYLE = (
    "margin:0;white-space:pre-wrap;word-break:break-word;"
    "font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px;"
    "line-height:1.45;color:#111827;"
)


def looks_like_html(value: str) -> bool:
    return bool(re.search(r"<[a-zA-Z][^>]*>", value or ""))


class _HTMLToTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")
        ad = {k.lower(): v for k, v in attrs if v is not None}
        if tag == "img":
            self.parts.append(f"[{ad.get('alt') or ad.get('src') or 'image'}]")
        elif tag == "a" and ad.get("href"):
            self.parts.append(f"{ad['href']} ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCK_TAGS and tag != "br":
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def html_to_text(html: str) -> str:
    if not html:
        return ""
    parser = _HTMLToTextParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return unescape(re.sub(r"<[^>]+>", "", html)).strip()
    text = unescape("".join(parser.parts))
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _safe_url(value: str | None, *, base: str) -> str | None:
    if not value:
        return None
    raw = value.strip()
    lowered = raw.lower()
    if (
        lowered.startswith("javascript:")
        or lowered.startswith("data:")
        or lowered.startswith("vbscript:")
    ):
        return None
    if raw.startswith("//"):
        return None
    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https", "mailto"}:
        return raw
    if raw.startswith("/") and base:
        return urljoin(base.rstrip("/") + "/", raw.lstrip("/"))
    return None


class _SanitizeParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=False)
        self.base_url = base_url
        self.out: list[str] = []
        self._skip_depth = 0

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._skip_depth:
            return
        self.handle_starttag(tag, attrs)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self._skip_depth:
            self._skip_depth += 1
            return
        if tag in _SKIP_TAGS:
            self._skip_depth = 1
            return
        if tag not in _ALLOWED_TAGS:
            return
        attr_map = {k.lower(): v for k, v in attrs if v is not None}
        allowed = _ALLOWED_ATTRS.get(tag, set())
        kept: list[tuple[str, str]] = []
        for name, val in attr_map.items():
            if name not in allowed:
                continue
            if name in {"href", "src"}:
                safe = _safe_url(val, base=self.base_url)
                if not safe:
                    continue
                val = safe
            kept.append((name, val))
        if tag == "img" and not any(k == "src" for k, _ in kept):
            return
        style = _TAG_STYLES.get(tag)
        if style:
            kept.append(("style", style))
        attrs_html = "".join(f' {k}="{escape(str(v), quote=True)}"' for k, v in kept)
        if tag in _VOID_TAGS:
            self.out.append(f"<{tag}{attrs_html} />")
        else:
            self.out.append(f"<{tag}{attrs_html}>")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._skip_depth:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag in _SKIP_TAGS or tag not in _ALLOWED_TAGS or tag in _VOID_TAGS:
            return
        self.out.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.out.append(escape(data, quote=False))

    def handle_entityref(self, name: str) -> None:
        if not self._skip_depth:
            self.out.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self._skip_depth:
            self.out.append(f"&#{name};")


def sanitize_email_html(html: str, base_url: str = "") -> str:
    parser = _SanitizeParser(base_url)
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return escape(html_to_text(html))
    return "".join(parser.out)


def _clip(text: str, limit: int) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n…(truncated)\n"


def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _pre_html(text: str) -> str:
    return f'<pre style="{_PRE_STYLE}">{escape(text)}</pre>'


def _fmt_ts(ts: Any) -> str | None:
    if ts is None or ts == "":
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError, OSError):
        return str(ts)


def _add_field(fields: list[tuple[str, str]], label: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, (list, tuple)):
        text = ", ".join(str(item).strip() for item in value if str(item).strip())
    else:
        text = str(value).strip()
    if text:
        fields.append((label, text))


def _useful_details(details: Any) -> str | None:
    text = str(details or "").strip()
    if not text:
        return None
    if text.lower() in _LOW_VALUE_DETAILS:
        return None
    return text


def _hydrate_ticket(out: dict) -> None:
    ticket_id = out.get("ticket_id")
    if ticket_id is None or not str(ticket_id).strip():
        return
    ticket = Ticket.get_or_none(Ticket.id == str(ticket_id))
    if not ticket:
        return
    out.setdefault("ticket_title", ticket.title)
    out.setdefault("project", ticket.project)
    out.setdefault("status", ticket.status)
    out.setdefault("priority", ticket.priority)
    if "description" not in out:
        out["description"] = ticket.description or ""
    if "labels" not in out:
        out["labels"] = [
            row.label for row in TicketLabelJoin.select().where(TicketLabelJoin.ticket == ticket.id)
        ]
    if "assignees" not in out:
        out["assignees"] = [
            row.user for row in UserTicketJoin.select().where(UserTicketJoin.ticket == ticket.id)
        ]


def _hydrate_comment(out: dict) -> None:
    comment_id = out.get("comment_id")
    if comment_id is None or out.get("comment_body"):
        return
    comment = Comment.get_or_none(Comment.id == comment_id)
    if not comment:
        return
    out["comment_body"] = comment.body or ""
    out["comment_via_agent"] = bool(getattr(comment, "via_agent", 0) or 0)


def _apply_error_payload(out: dict, payload: dict) -> None:
    out.setdefault("exception_type", payload.get("exception_type"))
    out.setdefault("exception_value", payload.get("exception_value"))
    out.setdefault("culprit", payload.get("culprit"))
    out.setdefault("platform", payload.get("platform"))
    out.setdefault("environment", payload.get("environment"))
    out.setdefault("release", payload.get("release"))
    out.setdefault("event_count", payload.get("event_count"))
    out.setdefault("status", payload.get("status"))
    out.setdefault("first_seen", payload.get("first_seen"))
    out.setdefault("last_seen", payload.get("last_seen"))
    part = payload.get("part") if isinstance(payload.get("part"), dict) else None
    if part:
        out.setdefault("part_id", part.get("id"))
        out.setdefault("part_name", part.get("name"))
    tags = payload.get("tags") if isinstance(payload.get("tags"), dict) else {}
    if tags and "tags" not in out:
        out["tags"] = tags
    contexts = payload.get("contexts") if isinstance(payload.get("contexts"), dict) else {}
    if contexts and "contexts" not in out:
        out["contexts"] = contexts
    out["stacktrace_text"] = compact_stacktrace_text(
        payload.get("stacktrace"), max_chars=STACK_MAX_CHARS
    )


def _hydrate_error(out: dict) -> None:
    error_group_id = out.get("error_group_id")
    if error_group_id is None:
        return
    try:
        error_id = int(error_group_id)
    except (TypeError, ValueError):
        return
    payload = build_error_export_payload(error_id)
    if payload:
        _apply_error_payload(out, payload)
        return
    if "stacktrace_text" in out:
        return
    group = ErrorGroup.get_or_none(ErrorGroup.id == error_id)
    if not group:
        return
    out.setdefault("exception_type", group.exception_type)
    out.setdefault("exception_value", group.exception_value)
    out.setdefault("culprit", group.culprit)


def _hydrate_monitor(out: dict) -> None:
    monitor_id = out.get("monitor_id")
    if monitor_id is None:
        return
    monitor = Monitor.get_or_none(Monitor.id == monitor_id)
    if not monitor:
        return
    out.setdefault("monitor_name", monitor.name)
    out.setdefault("checked_url", monitor.url)
    out.setdefault("last_error", monitor.last_error)
    out.setdefault("response_ms", monitor.last_response_ms)
    out.setdefault("expected_status", monitor.expected_status)
    out.setdefault("status", monitor.status)
    project_id = monitor.project_id if hasattr(monitor, "project_id") else str(monitor.project)
    out.setdefault("project", str(project_id))


def _attach_cta_urls(out: dict) -> None:
    base = email_base_url()
    if not base:
        return
    if out.get("ticket_id") is not None and out.get("project") is not None:
        out.setdefault("ticket_url", f"{base}/tickets/{out['project']}/{out['ticket_id']}")
    if out.get("error_group_id") is not None and out.get("part_id") is not None:
        out.setdefault("error_url", f"{base}/errors/{out['part_id']}/{out['error_group_id']}")
    if out.get("monitor_id") is not None and not out.get("monitor_url"):
        out["monitor_url"] = f"{base}/monitors/{out['monitor_id']}"


def hydrate_notification_event(event: dict) -> dict:
    """Fill ticket / error / monitor content from the database when ids are present."""
    out = dict(event)
    _hydrate_ticket(out)
    _hydrate_comment(out)
    _hydrate_error(out)
    _hydrate_monitor(out)
    _attach_cta_urls(out)
    return out


def _exception_title(event: dict) -> str | None:
    etype = str(event.get("exception_type") or "").strip()
    evalue = str(event.get("exception_value") or "").strip()
    if etype and evalue:
        return f"{etype}: {evalue}"
    return etype or evalue or None


def _context_summary(contexts: Any) -> str | None:
    if not isinstance(contexts, dict) or not contexts:
        return None
    parts: list[str] = []
    for key in ("os", "browser", "runtime", "device"):
        ctx = contexts.get(key)
        if not isinstance(ctx, dict):
            continue
        name = ctx.get("name") or ctx.get("family") or key
        detail = ctx.get("version") or ctx.get("model") or ""
        parts.append(f"{key}: {name} {detail}".strip())
    return "; ".join(parts) if parts else None


def _tag_summary(tags: Any) -> str | None:
    if not isinstance(tags, dict) or not tags:
        return None
    items = []
    for key, value in list(tags.items())[:12]:
        items.append(f"{key}={value}")
    extra = max(0, len(tags) - 12)
    text = ", ".join(items)
    if extra:
        text += f" (+{extra} more)"
    return text


def _body_from_content(raw: str, *, as_html: bool, base_url: str) -> tuple[str | None, str | None]:
    raw = raw or ""
    if not raw.strip():
        return None, None
    clipped = _clip(raw, BODY_MAX_CHARS)
    if as_html and looks_like_html(clipped):
        return sanitize_email_html(clipped, base_url), html_to_text(clipped)
    return _pre_html(clipped), clipped


def _cta(event: dict) -> tuple[str | None, str | None]:
    if event.get("ticket_url"):
        return str(event["ticket_url"]), "Open ticket →"
    if event.get("error_url"):
        return str(event["error_url"]), "Open error →"
    if event.get("monitor_url"):
        return str(event["monitor_url"]), "Open monitor →"
    return None, None


def build_notification_email(event: dict, *, hydrated: bool = False) -> dict[str, Any]:
    """Return template kwargs: headline, title, fields, body, CTA, subject."""
    data = event if hydrated else hydrate_notification_event(event)
    event_type = data.get("event_type")
    headline = EVENT_SUBJECTS.get(event_type, event_type or "Broke notification")
    base = email_base_url()
    fields: list[tuple[str, str]] = []
    title: str | None = None
    body_label: str | None = None
    body_html: str | None = None
    body_text: str | None = None

    if event_type in _ERROR_EVENTS:
        title = _exception_title(data)
        _add_field(fields, "Error group", data.get("error_group_id"))
        _add_field(fields, "Part", data.get("part_name"))
        _add_field(fields, "Status", data.get("status"))
        _add_field(fields, "Environment", data.get("environment"))
        _add_field(fields, "Release", data.get("release"))
        _add_field(fields, "Platform", data.get("platform"))
        _add_field(fields, "Culprit", data.get("culprit"))
        _add_field(fields, "Occurrences", data.get("event_count"))
        _add_field(fields, "First seen", _fmt_ts(data.get("first_seen")))
        _add_field(fields, "Last seen", _fmt_ts(data.get("last_seen")))
        _add_field(fields, "Context", _context_summary(data.get("contexts")))
        _add_field(fields, "Tags", _tag_summary(data.get("tags")))
        _add_field(fields, "Why", data.get("reason"))
        stack = str(data.get("stacktrace_text") or "").strip()
        if stack:
            body_label = "Stacktrace"
            body_html, body_text = _pre_html(stack), stack
        elif data.get("details"):
            body_label = "Details"
            body_html, body_text = _body_from_content(
                str(data["details"]), as_html=False, base_url=base
            )
    elif event_type in {EventTypes.MONITOR_DOWN, EventTypes.MONITOR_UP}:
        title = data.get("monitor_name") or None
        _add_field(fields, "Checked URL", data.get("checked_url"))
        _add_field(fields, "Project", data.get("project"))
        _add_field(fields, "Status", data.get("status"))
        _add_field(fields, "HTTP status", data.get("status_code"))
        _add_field(fields, "Expected status", data.get("expected_status"))
        if data.get("response_ms") is not None:
            _add_field(fields, "Response time", f"{data.get('response_ms')} ms")
        if event_type == EventTypes.MONITOR_DOWN:
            err = str(data.get("last_error") or "").strip()
            if err:
                body_label = "Error"
                body_html, body_text = _pre_html(err), err
    else:
        title = str(data.get("ticket_title") or "").strip() or None
        _add_field(
            fields, "Ticket", f"#{data['ticket_id']}" if data.get("ticket_id") is not None else None
        )
        _add_field(fields, "Project", data.get("project"))
        _add_field(fields, "Priority", data.get("priority"))
        if event_type == EventTypes.TICKET_STATUS_CHANGED and data.get("old_status"):
            _add_field(fields, "Status", f"{data.get('old_status')} → {data.get('status')}")
        else:
            _add_field(fields, "Status", data.get("status"))
        _add_field(fields, "Labels", data.get("labels"))
        _add_field(fields, "Assignees", data.get("assignees"))
        _add_field(fields, "Actor", data.get("actor") or data.get("user") or "System")
        _add_field(fields, "Details", _useful_details(data.get("details")))

        if event_type == EventTypes.TICKET_COMMENTED:
            raw = str(data.get("comment_body") or data.get("details") or "")
            via_agent = bool(data.get("comment_via_agent"))
            body_label = "Comment"
            body_html, body_text = _body_from_content(raw, as_html=not via_agent, base_url=base)
        elif event_type in _TICKET_DESCRIPTION_EVENTS:
            raw = str(data.get("description") or "")
            if raw.strip():
                body_label = "Description"
                body_html, body_text = _body_from_content(raw, as_html=True, base_url=base)

    if event_type in _ERROR_EVENTS:
        _add_field(fields, "Actor", data.get("actor") or "ingest")
    elif event_type in {EventTypes.MONITOR_DOWN, EventTypes.MONITOR_UP}:
        _add_field(fields, "Actor", data.get("actor") or "monitor")

    cta_url, cta_label = _cta(data)
    preheader_src = title or (body_text or "").replace("\n", " ")
    preheader = _truncate(
        f"{headline} — {preheader_src}" if preheader_src else headline, PREHEADER_MAX
    )
    subject_title = title or str(data.get("monitor_name") or data.get("ticket_title") or "").strip()
    if subject_title:
        subject = f"Broke: {headline}: {_truncate(subject_title, SUBJECT_TITLE_MAX)}"
    else:
        subject = f"Broke: {headline}"

    return {
        "headline": headline,
        "title": title,
        "fields": fields,
        "body_label": body_label,
        "body_html": body_html,
        "body_text": body_text,
        "cta_url": cta_url,
        "cta_label": cta_label,
        "preheader": preheader,
        "subject": subject,
    }


def notification_plain_text(view: dict[str, Any]) -> str:
    lines = [str(view.get("headline") or "Broke notification"), ""]
    if view.get("title"):
        lines.append(str(view["title"]))
        lines.append("")
    for label, value in view.get("fields") or []:
        lines.append(f"{label}: {value}")
    if view.get("body_text"):
        lines.append("")
        if view.get("body_label"):
            lines.append(str(view["body_label"]))
        lines.append(str(view["body_text"]))
    if view.get("cta_url"):
        lines.append("")
        lines.append(f"{view.get('cta_label') or 'Open'}: {view['cta_url']}")
    return "\n".join(lines).strip() + "\n"
