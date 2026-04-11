"""One-shot paste pack for an external AI: full ticket context + real Bearer token + curl examples."""

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
    """Written for the AI as the reader. curl-only API examples; prose-only replies do not update Broke."""
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

    esc = bearer_token.replace("'", "'\\''")

    curl_get = "curl -sS -k -g" if base.lower().startswith("https:") else "curl -sS -g"
    curl_mut = "curl -sS -k" if base.lower().startswith("https:") else "curl -sS"

    curl_ping = f"{curl_get} '{base}/api/agent/ping' -H 'Authorization: Bearer {esc}'"
    curl_status = (
        f"{curl_mut} -X PATCH '{base}/api/agent/tickets/{tid}' "
        f"-H 'Authorization: Bearer {esc}' -H 'Content-Type: application/json' "
        f'-d \'{{"status":"in-progress"}}\''
    )
    curl_done = (
        f"{curl_mut} -X PATCH '{base}/api/agent/tickets/{tid}' "
        f"-H 'Authorization: Bearer {esc}' -H 'Content-Type: application/json' "
        f'-d \'{{"status":"done"}}\''
    )
    curl_comment = (
        f"{curl_mut} -X POST '{base}/api/agent/tickets/{tid}/comments' "
        f"-H 'Authorization: Bearer {esc}' -H 'Content-Type: application/json' "
        f'-d \'{{"body":"Your update here"}}\''
    )
    curl_append = (
        f"{curl_mut} -X PATCH '{base}/api/agent/tickets/{tid}' "
        f"-H 'Authorization: Bearer {esc}' -H 'Content-Type: application/json' "
        '-d \'{"description_append":"\\n\\nAdded by agent."}\''
    )

    lines = [
        "# Broke — delegated ticket",
        "",
        "## CRITICAL (read before doing anything else)",
        "",
        "**Talking about Broke is not the same as updating Broke.** If you only reply in prose and never perform an HTTP request, **the ticket in Broke will not change**.",
        "",
        "1. **Use `curl` to talk to Broke** (this pack is curl-only). Many agents (e.g. Cursor) can run shell commands: run the **ping** command first, then **mark in progress**, then do the rest as you work.",
        "2. **If you cannot run shell** (plain chat with no tools): **stop** and tell the user clearly: *I cannot reach your Broke server from here.* Give them the **ping** `curl` to run locally and ask them to paste the response back; then continue only after they confirm `200`.",
        "3. **Do not** claim the ticket was updated in Broke unless you actually received a successful HTTP response from this host.",
        "4. **Language:** Always write your **replies to the user** in **English**, even if the ticket title, description, or history is in another language. When posting **comments** or other free-form text to Broke via the API, use **English** unless the user explicitly asks for a different language.",
        "",
        "## HTTPS and HTTP",
        "",
        "- **Use the Base URL as given** (keep the same `http` or `https` scheme). Do not change `http` ↔ `https` unless the user confirms Broke is reachable on the other scheme.",
        "- **`https://`:** TLS encrypts the connection. These **`curl`** lines use **`-k`** (no certificate verification) so self-signed certs and private CAs work. Only use this pack against Broke hosts you trust.",
        "- **`http://`:** Still supported (common for localhost or trusted private networks). There is no transport encryption; treat the network path as trusted.",
        "",
        "---",
        "",
        "## Step 1 — `curl` (run these against Broke)",
        "",
        "For `https://`, **`-k`** skips TLS certificate verification (self-signed / internal CA). Omitted for `http://`.",
        "",
        "**Ping (must return JSON with ok:true):**",
        "",
        "```bash",
        curl_ping,
        "```",
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
        f"Other `status` values: `backlog`, `todo`, `in-progress`, `in-review`, `done`, `closed`.",
        "",
        "---",
        "",
        "## Credentials (also embedded in curl above)",
        "",
        f"- **Base URL:** `{base}`",
        f"- **Ticket id:** `{tid}`",
        f"- **Bearer token** (expires {exp_s}): `{bearer_token}`",
        "",
        "---",
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
        "## Full ticket export (Markdown from Broke)",
        "",
        "Use this for labels, assignees, comments, subtickets, and history.",
        "",
        "---BEGIN-TICKET-EXPORT---",
        full_md,
        "---END-TICKET-EXPORT---",
        "",
    ]
    return "\n".join(lines)
