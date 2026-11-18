"""Public /anon reports: questions, confirm-by-email, and reporter mail.

The staff intake chat is not used here. A report check may talk to the sender
before submit, and intake assist may fill staff fields after the ticket exists.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import json
import logging
import os
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any

from flask import current_app, has_app_context, has_request_context, request

from .email_branding import render_email
from .events import EventTypes, bus
from .mail import send_email
from .models import AnonContact, AnonDraft, Project, Ticket, TicketUpdateMessage, database

logger = logging.getLogger(__name__)

DRAFT_TTL_SECONDS = 86400
REVIEW_TTL_SECONDS = 1800
MAX_COPY_EMAILS = 5
MAX_OPEN_DRAFTS = 3
MAX_IMAGE_BYTES = 2 * 1024 * 1024
TITLE_MIN = 10
TITLE_MAX = 140

EMAIL_RE = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$")
IMAGE_KINDS = {
    "png": b"\x89PNG\r\n\x1a\n",
    "jpg": b"\xff\xd8\xff",
    "jpeg": b"\xff\xd8\xff",
    "gif": b"GIF8",
    "webp": b"RIFF",
}

STATUS_LABELS = {
    "backlog": "Backlog",
    "todo": "To do",
    "in-progress": "In progress",
    "in-review": "In review",
    "done": "Done",
    "closed": "Closed",
    "duplicate": "Duplicate",
    "parked": "Parked",
    "intake": "Intake",
    "triage": "Triage",
}


@dataclass(frozen=True)
class ReportField:
    key: str
    label: str
    minimum: int
    maximum: int
    required: bool
    hint: str = ""
    example: str = ""


@dataclass(frozen=True)
class ReportKind:
    key: str
    label: str
    title_label: str
    title_example: str
    fields: tuple[ReportField, ...]
    judged: tuple[str, ...]


KINDS: dict[str, ReportKind] = {
    "problem": ReportKind(
        key="problem",
        label="Problem",
        title_label="What should we call this?",
        title_example="Login fails after a password reset",
        fields=(
            ReportField(
                "detail",
                "What is broken?",
                30,
                4000,
                True,
                "Enough: what broke, and where it shows up. Expected result and who is affected help, but do not fail once the break and the place are clear. Too thin: it is broken, or it should work.",
                "The login page says the password is wrong after I reset it.",
            ),
            ReportField(
                "system",
                "What system is this on?",
                8,
                400,
                True,
                "Enough: a named app, site, browser, or device. A missing version is fine, including when they say they do not know it. Too thin: my computer, or my phone, with no product.",
                "Chrome on Windows 11, app version 2.4",
            ),
        ),
        judged=("detail", "system"),
    ),
    "feature": ReportKind(
        key="feature",
        label="Feature",
        title_label="What should we call this?",
        title_example="Export this month's invoices",
        fields=(
            ReportField(
                "missing",
                "What is missing?",
                30,
                4000,
                True,
                "Enough: the thing that does not exist yet and who it is for. Too thin: describing a screen that already exists, or saying make it better.",
                "A button on the invoice page that downloads this month's charges for the billing team.",
            ),
            ReportField(
                "gap",
                "Why isn't the current system enough?",
                30,
                4000,
                True,
                "Enough: the job people do today because this is missing. Too thin: a wish with no current gap.",
                "We copy every invoice into a spreadsheet by hand. The page only shows one invoice at a time.",
            ),
            ReportField(
                "avoid",
                "What broken thing must this not copy?",
                30,
                4000,
                True,
                "Enough: one real flaw the new thing must not repeat, or a clear statement that nothing existing should be copied. Too thin: make it like the other page. Do not demand a broken system when they said there is nothing to copy.",
                "Do not copy the old export. It drops tax lines and only works for one currency.",
            ),
        ),
        judged=("missing", "gap", "avoid"),
    ),
    "improvement": ReportKind(
        key="improvement",
        label="Improvement",
        title_label="What should we call this?",
        title_example="Show the date on each row",
        fields=(
            ReportField(
                "today",
                "What do you do today?",
                30,
                4000,
                True,
                "Enough: the steps they take now. Too thin: describing the new design instead of the current work.",
                "I open every invoice row just to see the date.",
            ),
            ReportField(
                "failure",
                "What is actually wrong with that?",
                30,
                4000,
                True,
                "Enough: one real cost, miss, or delay those steps cause. Too thin: it should be better, or a new name for the same steps.",
                "A list of 40 invoices takes ten minutes, and I still miss the ones from last month.",
            ),
            ReportField(
                "change",
                "What should change in the work?",
                30,
                4000,
                True,
                "Enough: what changes in the work itself. Too thin: only a new label, color, or extra screen that keeps the same steps.",
                "Show the date on each row. Do not add another page that still hides it.",
            ),
        ),
        judged=("today", "failure", "change"),
    ),
}


def kind_form_specs() -> list[dict[str, Any]]:
    specs = []
    for kind in KINDS.values():
        specs.append(
            {
                "key": kind.key,
                "label": kind.label,
                "title_label": kind.title_label,
                "title_example": kind.title_example,
                "fields": [
                    {
                        "key": field.key,
                        "label": field.label,
                        "required": field.required,
                        "example": field.example,
                    }
                    for field in kind.fields
                ],
            }
        )
    return specs


def status_label(slug: str) -> str:
    return STATUS_LABELS.get(slug, slug.replace("-", " ").capitalize())


def external_root() -> str:
    """Public origin plus the optional application prefix. Empty when unknown."""
    configured = os.environ.get("APP_BASE_URL", "").strip().rstrip("/")
    prefix = ""
    if has_app_context():
        prefix = str(current_app.config.get("BROKE_APPLICATION_PREFIX") or "").strip().rstrip("/")
    if configured:
        return f"{configured}{prefix}" if prefix else configured
    if has_request_context():
        base = request.host_url.rstrip("/")
        return f"{base}{prefix}" if prefix else base
    logger.warning("APP_BASE_URL is unset and there is no request to copy a host from")
    return ""


def _secret() -> bytes:
    key = current_app.secret_key
    if isinstance(key, bytes):
        return key
    return str(key).encode()


def normalize_answers(kind: str, data: dict) -> dict[str, str]:
    spec = KINDS[kind]
    answers = {"title": str(data.get("title", "")).strip()}
    for field in spec.fields:
        answers[field.key] = str(data.get(field.key, "")).strip()
    return answers


def checked_fields(kind: str, answers: dict[str, str]) -> list[ReportField]:
    spec = KINDS[kind]
    title = ReportField("title", spec.title_label, TITLE_MIN, TITLE_MAX, True)
    fields = [title]
    for field in spec.fields:
        if field.required or answers.get(field.key):
            fields.append(field)
    return fields


def structural_notes(kind: str, answers: dict[str, str]) -> list[dict[str, Any]]:
    notes = []
    for field in checked_fields(kind, answers):
        text = answers.get(field.key, "")
        if field.required and len(text) < field.minimum:
            notes.append(
                {
                    "field": field.key,
                    "ok": False,
                    "message": (
                        f"Say more about {field.label.rstrip('?').lower()}. "
                        f"Use at least {field.minimum} characters."
                    )[:160],
                }
            )
        elif len(text) > field.maximum:
            notes.append(
                {
                    "field": field.key,
                    "ok": False,
                    "message": f"Shorten {field.label.rstrip('?').lower()} to {field.maximum} characters."[
                        :160
                    ],
                }
            )
    return notes


def passing_notes(kind: str, answers: dict[str, str]) -> list[dict[str, Any]]:
    notes = []
    for field in checked_fields(kind, answers):
        notes.append(
            {
                "field": field.key,
                "ok": True,
                "message": f"{field.label.rstrip('?')} is filled in.",
            }
        )
    return notes


def canonical_answers(kind: str, answers: dict[str, str]) -> str:
    spec = KINDS[kind]
    body = {"kind": kind, "title": answers.get("title", "")}
    for field in spec.fields:
        body[field.key] = answers.get(field.key, "")
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def make_review_token(kind: str, answers: dict[str, str]) -> str:
    expires = int(time.time()) + REVIEW_TTL_SECONDS
    digest = hmac.new(
        _secret(),
        f"{expires}.{canonical_answers(kind, answers)}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{expires}.{digest}"


def review_token_matches(token: str, kind: str, answers: dict[str, str]) -> bool:
    expires_text, separator, digest = str(token or "").partition(".")
    if not separator or not digest:
        return False
    try:
        expires = int(expires_text)
    except ValueError:
        return False
    if expires < int(time.time()):
        return False
    expected = hmac.new(
        _secret(),
        f"{expires}.{canonical_answers(kind, answers)}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, digest)


def build_review(kind: str, answers: dict[str, str]) -> dict[str, Any]:
    """Checklist for the sender. Writes nothing."""
    from .ai_changelog import get_ai_config

    notes = structural_notes(kind, answers)
    if notes:
        return {"ready": False, "headline": "Add the missing details.", "notes": notes}

    if get_ai_config() is None:
        return {
            "ready": True,
            "headline": "This is specific enough to send.",
            "notes": passing_notes(kind, answers),
            "review_token": make_review_token(kind, answers),
        }

    from .anon_enrich import review_anon_report

    verdict = review_anon_report(kind, answers, checked_fields(kind, answers))
    if not verdict:
        return {
            "ready": False,
            "headline": "Try the check again.",
            "notes": [
                {
                    "field": "",
                    "ok": False,
                    "message": "The check did not finish. Try again in a moment.",
                }
            ],
        }

    ready = all(bool(note.get("ok")) for note in verdict["notes"])
    payload = {
        "ready": ready,
        "headline": verdict["headline"],
        "notes": verdict["notes"],
    }
    if ready:
        payload["review_token"] = make_review_token(kind, answers)
    return payload


def parse_emails(primary: str, copies: Any) -> tuple[str, list[str], str | None, str | None]:
    primary_email = str(primary or "").strip().lower()
    if not primary_email or len(primary_email) > 254 or not EMAIL_RE.match(primary_email):
        return "", [], "primary_email", "Use a plain email address."

    raw_copies: list[str] = []
    if isinstance(copies, str):
        raw_copies = re.split(r"[\s,;]+", copies)
    elif isinstance(copies, list):
        raw_copies = [str(item) for item in copies]
    cleaned: list[str] = []
    for item in raw_copies:
        email = item.strip().lower()
        if not email:
            continue
        if email == primary_email:
            return "", [], "copy_emails", "That address is already the primary."
        if len(email) > 254 or not EMAIL_RE.match(email):
            return "", [], "copy_emails", "Use a plain email address for each extra recipient."
        if email not in cleaned:
            cleaned.append(email)
    if len(cleaned) > MAX_COPY_EMAILS:
        return "", [], "copy_emails", "You can add up to five extra emails."
    return primary_email, cleaned, None, None


def open_draft_count(email: str) -> int:
    now = int(time.time())
    return (
        AnonDraft.select()
        .join(AnonContact)
        .where(
            (AnonContact.email == email)
            & (AnonContact.role == "primary")
            & AnonDraft.consumed_at.is_null()
            & (AnonDraft.expires_at > now)
        )
        .count()
    )


def _paragraph(text: str) -> str:
    escaped = html.escape(text).replace("\n", "<br>")
    return f"<p>{escaped}</p>"


def description_html(kind: str, answers: dict[str, str], image_src: str | None) -> str:
    spec = KINDS[kind]
    parts = [
        f'<div data-anon-kind="{html.escape(kind)}">',
        f"<p><strong>{html.escape(spec.label)}</strong></p>",
        f"<h2>{html.escape(spec.title_label.rstrip('?'))}</h2>",
        _paragraph(answers.get("title", "")),
    ]
    for field in spec.fields:
        text = answers.get(field.key, "")
        if not text:
            continue
        parts.append(f"<h2>{html.escape(field.label)}</h2>")
        parts.append(_paragraph(text))
    if image_src:
        parts.append(f'<img src="{html.escape(image_src, quote=True)}" alt="">')
    parts.append("</div>")
    return "".join(parts)


def _image_extension(header: bytes, declared: str) -> str | None:
    declared = declared.lower().strip()
    if declared == "jpeg":
        declared = "jpg"
    if declared not in {"png", "jpg", "gif", "webp"}:
        return None
    if declared == "png" and header.startswith(IMAGE_KINDS["png"]):
        return "png"
    if declared == "jpg" and header.startswith(IMAGE_KINDS["jpg"]):
        return "jpg"
    if declared == "gif" and header.startswith(IMAGE_KINDS["gif"]):
        return "gif"
    if declared == "webp" and header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "webp"
    return None


def save_report_image(data_url: str) -> tuple[str | None, str | None]:
    """Store one image under uploads. Returns (public src, error)."""
    import base64
    import os as os_mod
    import uuid

    from .models import data_path

    match = re.match(r"^data:image/([a-zA-Z0-9.+-]+);base64,([A-Za-z0-9+/=\s]+)$", data_url or "")
    if not match:
        return None, "Attach a png, jpeg, webp, or gif."
    try:
        raw = base64.b64decode(re.sub(r"\s+", "", match.group(2)), validate=True)
    except (ValueError, TypeError):
        return None, "Attach a png, jpeg, webp, or gif."
    if len(raw) > MAX_IMAGE_BYTES:
        return None, "The image must be 2 MB or smaller."
    extension = _image_extension(raw[:16], match.group(1))
    if not extension:
        return None, "Attach a png, jpeg, webp, or gif."

    filename = f"{uuid.uuid4().hex}.{extension}"
    folder = data_path("uploads")
    os_mod.makedirs(folder, exist_ok=True)
    path = os_mod.path.join(str(folder), filename)
    with open(path, "wb") as handle:
        handle.write(raw)

    prefix = ""
    if has_app_context():
        prefix = str(current_app.config.get("BROKE_APPLICATION_PREFIX") or "").strip().rstrip("/")
    src = f"{prefix}/anon/media/{filename}" if prefix else f"/anon/media/{filename}"
    return src, None


def delete_upload(src: str | None) -> None:
    if not src or "/anon/media/" not in src:
        return
    filename = src.rsplit("/", 1)[-1]
    if not re.fullmatch(r"[a-f0-9]{32}\.(png|jpe?g|webp|gif)", filename):
        return
    from .models import data_path

    path = data_path("uploads", filename)
    if os.path.isfile(path):
        os.remove(path)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _new_contact(draft: AnonDraft, email: str, role: str) -> str:
    token = secrets.token_urlsafe(32)
    AnonContact.create(
        draft=draft,
        email=email,
        role=role,
        token_hash=_hash_token(token),
        created_at=int(time.time()),
    )
    return token


def _render_pair(html_name: str, text_name: str, **context: Any) -> tuple[str, str]:
    from flask import render_template

    from .email_branding import BRAND, email_base_url, email_logo_url

    ctx = {
        "brand": BRAND,
        "email_base_url": email_base_url(),
        "email_logo_url": email_logo_url(),
        **context,
    }
    if has_request_context():
        return render_template(html_name, **ctx), render_template(text_name, **ctx)
    return render_email(html_name, **context), render_email(text_name, **context)


def send_confirm_mail(email: str, role: str, token: str, title: str) -> bool:
    root = external_root()
    if not root:
        return False
    link = f"{root}/anon/verify/{token}"
    if role == "primary":
        html_body, text_body = _render_pair(
            "email/anon_confirm.jinja2",
            "email/anon_confirm.txt.jinja2",
            title=title,
            confirm_link=link,
        )
        subject = "Confirm your report"
    else:
        html_body, text_body = _render_pair(
            "email/anon_copy_confirm.jinja2",
            "email/anon_copy_confirm.txt.jinja2",
            confirm_link=link,
        )
        subject = "Confirm you want updates"
    return bool(send_email(email, subject, html_body, text_content=text_body))


def send_received_mail(contact: AnonContact, ticket: Ticket) -> None:
    if contact.tracking_sent_at or not contact.verified_at or not ticket.anonymous_secret:
        return
    root = external_root()
    if not root:
        logger.warning("Skipping tracking mail for %s; no public root", contact.email)
        return
    link = f"{root}/anon/track/{ticket.anonymous_secret}"
    html_body, text_body = _render_pair(
        "email/anon_received.jinja2",
        "email/anon_received.txt.jinja2",
        title=ticket.title,
        track_link=link,
    )
    if send_email(contact.email, "We received your report", html_body, text_content=text_body):
        contact.tracking_sent_at = int(time.time())
        contact.save(only=[AnonContact.tracking_sent_at])


def confirmed_contacts(ticket_id: str) -> list[AnonContact]:
    return list(
        AnonContact.select().where(
            (AnonContact.ticket == ticket_id) & AnonContact.verified_at.is_null(False)
        )
    )


def confirmed_reporter_emails(ticket_id: str) -> list[str]:
    return [contact.email for contact in confirmed_contacts(ticket_id)]


def send_status_mail(ticket: Ticket, new_status: str) -> None:
    root = external_root()
    if not root or not ticket.anonymous_secret:
        if ticket.anonymous_secret and not root:
            logger.warning("Skipping status mail for %s; no public root", ticket.id)
        return
    label = status_label(new_status)
    link = f"{root}/anon/track/{ticket.anonymous_secret}"
    sentence = f"Your report is now {label}."
    html_body, text_body = _render_pair(
        "email/anon_status.jinja2",
        "email/anon_status.txt.jinja2",
        title=ticket.title,
        status_label=label,
        sentence=sentence,
        track_link=link,
    )
    for contact in confirmed_contacts(ticket.id):
        send_email(contact.email, "Update on your report", html_body, text_content=text_body)


def send_reply_mail(ticket: Ticket, reply: str) -> None:
    root = external_root()
    if not root or not ticket.anonymous_secret:
        if ticket.anonymous_secret and not root:
            logger.warning("Skipping reply mail for %s; no public root", ticket.id)
        return
    link = f"{root}/anon/track/{ticket.anonymous_secret}"
    html_body, text_body = _render_pair(
        "email/anon_reply.jinja2",
        "email/anon_reply.txt.jinja2",
        title=ticket.title,
        reply_text=reply,
        track_link=link,
    )
    for contact in confirmed_contacts(ticket.id):
        send_email(contact.email, "A reply to your report", html_body, text_content=text_body)


def record_anon_public_status(ticket: Ticket, new_status: str) -> None:
    if not getattr(ticket, "anonymous_secret", None):
        return
    TicketUpdateMessage.create(
        ticket=ticket.id,
        title="Status",
        icon="ph ph-arrow-right",
        message=f"Status is now {status_label(new_status)}.",
        created_at=int(time.time()),
        public=1,
    )
    try:
        send_status_mail(ticket, new_status)
    except Exception:
        logger.exception("Failed to mail status for %s", ticket.id)


def plain_reply(value: str) -> str:
    text = re.sub(r"<[^>]*>", "", value or "")
    return text.strip()


def post_public_reply(ticket: Ticket, author, body: str) -> str | None:
    """Store a reporter-visible reply. Returns an error string, or None."""
    if not ticket.anonymous_secret:
        return "This ticket has no reporter to reach."
    text = plain_reply(body)
    if not text:
        return "Write a reply first."
    if len(text) > 4000:
        return "Keep the reply to 4000 characters."
    TicketUpdateMessage.create(
        ticket=ticket.id,
        title="Reply",
        icon="ph ph-chat-circle",
        message=text,
        created_at=int(time.time()),
        author=author,
        public=1,
    )
    try:
        send_reply_mail(ticket, text)
    except Exception:
        logger.exception("Failed to mail reply for %s", ticket.id)
    return None


def _next_ticket_id(project_id: str) -> str:
    existing = Ticket.select().where(Ticket.project == project_id)
    max_num = 0
    for ticket in existing:
        parts = ticket.id.split("-")
        if len(parts) >= 2:
            try:
                max_num = max(max_num, int(parts[-1]))
            except ValueError:
                continue
    ticket_id = f"{project_id}-{max_num + 1}"
    while Ticket.get_or_none(Ticket.id == ticket_id):
        max_num += 1
        ticket_id = f"{project_id}-{max_num + 1}"
    return ticket_id


def create_ticket_from_draft(draft: AnonDraft, contact: AnonContact) -> Ticket:
    """Claim the draft and create the intake ticket. Caller already checked expiry."""
    now = int(time.time())
    claimed = (
        AnonDraft.update(consumed_at=now)
        .where((AnonDraft.id == draft.id) & AnonDraft.consumed_at.is_null())
        .execute()
    )
    if not claimed:
        fresh = AnonDraft.get_by_id(draft.id)
        if fresh.ticket_id:
            return Ticket.get(Ticket.id == fresh.ticket_id)
        raise RuntimeError("This confirmation was already used.")

    payload = json.loads(draft.payload)
    try:
        ticket = Ticket.create(
            id=_next_ticket_id("TRIAGE"),
            title=payload["title"],
            description=payload["description_html"],
            status="intake",
            priority="medium",
            project="TRIAGE",
            created_at=now,
            anonymous_secret=secrets.token_urlsafe(16),
        )
    except Exception:
        AnonDraft.update(consumed_at=None).where(AnonDraft.id == draft.id).execute()
        raise

    draft.ticket_id = ticket.id
    draft.save(only=[AnonDraft.ticket_id])
    AnonContact.update(ticket=ticket.id).where(AnonContact.draft == draft).execute()
    contact.verified_at = now
    contact.ticket = ticket.id
    contact.save(only=[AnonContact.verified_at, AnonContact.ticket])

    return _finish_intake_ticket(ticket, payload)


def file_report_now(kind: str, answers: dict[str, str], image_src: str | None) -> Ticket:
    """Create the intake ticket immediately. Used when outbound mail is not configured."""
    now = int(time.time())
    payload = {
        "kind": kind,
        "title": answers["title"],
        "answers": answers,
        "description_html": description_html(kind, answers, image_src),
        "image_src": image_src,
    }
    with database.atomic():
        ticket = Ticket.create(
            id=_next_ticket_id("TRIAGE"),
            title=payload["title"],
            description=payload["description_html"],
            status="intake",
            priority="medium",
            project="TRIAGE",
            created_at=now,
            anonymous_secret=secrets.token_urlsafe(16),
        )
        _write_intake_rows(ticket, payload)
    try:
        _emit_intake(ticket)
    except Exception:
        logger.exception("Anonymous ticket %s was filed but notifications failed", ticket.id)
    return ticket


def _finish_intake_ticket(ticket: Ticket, payload: dict) -> Ticket:
    _write_intake_rows(ticket, payload)
    _emit_intake(ticket)
    return ticket


def _write_intake_rows(ticket: Ticket, payload: dict) -> None:
    duplicate_note = ""
    try:
        from ..views.tickets import _find_possible_duplicate_tickets, _has_blocking_duplicate

        matches = _find_possible_duplicate_tickets(ticket.title, ticket.description)
        if _has_blocking_duplicate(matches):
            ids = ", ".join(str(match.get("id", "")).strip() for match in matches[:3] if match.get("id"))
            if ids:
                duplicate_note = f" Potential duplicate candidates: {ids}."
    except Exception:
        logger.exception("Duplicate check failed for %s", ticket.id)

    now = int(ticket.created_at)
    kind_label = KINDS[payload["kind"]].label.lower()
    TicketUpdateMessage.create(
        ticket=ticket.id,
        title="Anonymous ticket created",
        icon="ph ph-mask-happy",
        message=f"Anonymous {kind_label} submitted.{duplicate_note}",
        created_at=now,
        public=0,
    )
    TicketUpdateMessage.create(
        ticket=ticket.id,
        title="Received",
        icon="ph ph-check",
        message="We received this report.",
        created_at=now,
        public=1,
    )


def _emit_intake(ticket: Ticket) -> None:
    bus.emit(
        EventTypes.ANON_TICKET_SUBMITTED,
        ticket_id=ticket.id,
        ticket_title=ticket.title,
        project=ticket.project,
        status=ticket.status,
        actor="anonymous",
        details="Anonymous ticket entered intake inbox",
    )
    testing = has_app_context() and bool(current_app.config.get("TESTING"))
    bus.emit(
        EventTypes.ANON_TICKET_ENRICH,
        async_dispatch=not testing,
        ticket_id=ticket.id,
    )


def notify_verified(ticket: Ticket) -> None:
    for contact in confirmed_contacts(ticket.id):
        try:
            send_received_mail(contact, ticket)
        except Exception:
            logger.exception("Failed to send tracking mail to %s", contact.email)


def find_contact(token: str) -> AnonContact | None:
    if not token:
        return None
    return AnonContact.get_or_none(AnonContact.token_hash == _hash_token(token))


def draft_is_expired(draft: AnonDraft) -> bool:
    return draft.consumed_at is None and int(draft.expires_at) < int(time.time())


def store_draft(
    kind: str,
    answers: dict[str, str],
    primary: str,
    copies: list[str],
    image_src: str | None,
) -> tuple[AnonDraft, str, list[tuple[str, str]]]:
    now = int(time.time())
    payload = {
        "kind": kind,
        "title": answers["title"],
        "answers": answers,
        "description_html": description_html(kind, answers, image_src),
        "image_src": image_src,
    }
    with database.atomic():
        draft = AnonDraft.create(
            payload=json.dumps(payload),
            created_at=now,
            expires_at=now + DRAFT_TTL_SECONDS,
        )
        primary_token = _new_contact(draft, primary, "primary")
        copy_tokens = [(email, _new_contact(draft, email, "copy")) for email in copies]
    return draft, primary_token, copy_tokens


def delete_draft(draft: AnonDraft) -> None:
    AnonContact.delete().where(AnonContact.draft == draft).execute()
    draft.delete_instance()


def active_project(project_id: str) -> Project | None:
    if not project_id or project_id == "TRIAGE":
        return None
    return Project.get_or_none((Project.id == project_id) & (Project.archived == 0))
