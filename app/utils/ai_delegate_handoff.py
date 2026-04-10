"""One-shot paste pack for an external AI: full ticket context + real Bearer token + copy-paste curls."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from html import unescape
from typing import TYPE_CHECKING, Any

from .models import AgentToken
from .ticket_markdown import ticket_payload_to_markdown

if TYPE_CHECKING:
    from .models import Ticket, User

_DELEGATE_TTL = 7 * 24 * 3600  # one week; revoke in Settings → Agent tokens if needed
_MAX_EMBED_CHARS = 80_000


def _strip_html_to_text(html: str) -> str:
    if not html:
        return ""
    t = re.sub(r"(?is)<br\s*/?>", "\n", html)
    t = re.sub(r"(?is)</p>", "\n\n", t)
    t = re.sub(r"(?is)<[^>]+>", "", t)
    return unescape(t).strip()


def mint_ticket_delegate_token(*, user: "User", ticket: "Ticket") -> tuple[str, AgentToken]:
    """Bearer token valid only for this ticket (and usual scope checks)."""
    raw = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    now = int(time.time())
    scopes = ["comment:write", "ticket:write", "ticket:read"]
    at = AgentToken.create(
        user=user.username,
        token_hash=token_hash,
        token_preview=raw[:8],
        expires_at=now + _DELEGATE_TTL,
        scopes=json.dumps(scopes),
        project=ticket.project,
        work_cycle_id=ticket.work_cycle_id,
        ticket_id=ticket.id,
        created_at=now,
    )
    return raw, at


def build_ai_delegate_pack_markdown(
    *,
    payload: dict[str, Any],
    base_url: str,
    bearer_token: str,
    expires_at_epoch: int,
) -> str:
    """
    Written for the AI as the reader. Single copy-paste block: context + working curl one-liners.
    """
    base = base_url.rstrip("/")
    tid = str(payload.get("id") or "")
    title = (payload.get("title") or "").replace("\n", " ").strip()
    status = payload.get("status") or ""
    project = payload.get("project") or ""
    priority = payload.get("priority") or ""
    desc_raw = str(payload.get("description") or "")
    desc_plain = _strip_html_to_text(desc_raw)
    if len(desc_plain) > 12_000:
        desc_plain = desc_plain[:12_000] + "\n\n…(truncated)"

    from datetime import datetime, timezone

    exp_s = datetime.fromtimestamp(expires_at_epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    full_md = ticket_payload_to_markdown(payload)
    if len(full_md) > _MAX_EMBED_CHARS:
        full_md = full_md[:_MAX_EMBED_CHARS] + "\n\n…(truncated for paste size)"

    # One-line curls — no shell line continuations (copy-paste friendly).
    esc = bearer_token.replace("'", "'\\''")
    curl_status = (
        f"curl -sS -X PATCH '{base}/api/agent/tickets/{tid}' "
        f"-H 'Authorization: Bearer {esc}' -H 'Content-Type: application/json' "
        f'-d \'{{"status":"in-progress"}}\''
    )
    curl_done = (
        f"curl -sS -X PATCH '{base}/api/agent/tickets/{tid}' "
        f"-H 'Authorization: Bearer {esc}' -H 'Content-Type: application/json' "
        f'-d \'{{"status":"done"}}\''
    )
    curl_comment = (
        f"curl -sS -X POST '{base}/api/agent/tickets/{tid}/comments' "
        f"-H 'Authorization: Bearer {esc}' -H 'Content-Type: application/json' "
        f'-d \'{{"body":"Your update here"}}\''
    )
    curl_append = (
        f"curl -sS -X PATCH '{base}/api/agent/tickets/{tid}' "
        f"-H 'Authorization: Bearer {esc}' -H 'Content-Type: application/json' "
        '-d \'{"description_append":"\\n\\nAdded by agent."}\''
    )

    lines = [
        "# Broke — delegated ticket (read this whole message)",
        "",
        "You are expected to **do the work** (research, coding, analysis) and to **update Broke** over HTTP using the token below. The human pastes this once; you drive the ticket to completion.",
        "",
        "## Rules",
        "",
        f"- **Base URL:** `{base}`",
        f"- **Ticket id:** `{tid}`",
        f"- **Bearer token** (secret, expires {exp_s}):",
        "",
        f"`{bearer_token}`",
        "",
        "- Use **only** the `curl` examples below (or equivalent HTTP) against this host. Start work → set status `in-progress` → comment progress → finish → set `done` or `in-review`.",
        "- You may **append** to the description with `description_append`; do not assume you can replace the whole description via this API.",
        "",
        "## Quick ticket summary",
        "",
        f"- **Title:** {title}",
        f"- **Project:** `{project}`",
        f"- **Status (current):** `{status}`",
        f"- **Priority:** `{priority}`",
        "",
        "### Description (plain text)",
        "",
        desc_plain or "_(empty)_",
        "",
        "## Copy-paste `curl` (token already filled — run in a terminal)",
        "",
        "**Mark in progress:**",
        "",
        "```bash",
        curl_status,
        "```",
        "",
        "**Post a comment:**",
        "",
        "```bash",
        curl_comment,
        "```",
        "",
        "**Mark done:**",
        "",
        "```bash",
        curl_done,
        "```",
        "",
        "**Append description:**",
        "",
        "```bash",
        curl_append,
        "```",
        "",
        "Other `status` values include: `backlog`, `todo`, `in-progress`, `in-review`, `done`, `closed`.",
        "",
        "## Full ticket export (Markdown from Broke)",
        "",
        "Use this for labels, assignees, comments thread, subtickets, and history.",
        "",
        "---BEGIN-TICKET-EXPORT---",
        full_md,
        "---END-TICKET-EXPORT---",
        "",
    ]
    return "\n".join(lines)
