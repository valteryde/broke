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
    """Written for the AI as the reader: ticket context first, then curl-only API examples."""
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

    heading = title if title else (f"Ticket `{tid}`" if tid else "Ticket")
    lines = [
        f"# {heading}",
        "",
        f"- **Ticket id:** `{tid}`",
        f"- **Project:** `{project}`",
        f"- **Status:** `{status}`",
        f"- **Priority:** `{priority}`",
        "",
        "## Description (plain text)",
        "",
        desc_plain or "_(empty)_",
        "",
        "---",
        "",
        "## Full ticket record",
        "",
        "Labels, assignees, comments, subtickets, and change history (export layout below).",
        "",
        "---BEGIN-TICKET-EXPORT---",
        full_md,
        "---END-TICKET-EXPORT---",
        "",
        "---",
        "",
        "## Updating this ticket (HTTP API)",
        "",
        "### Before you start",
        "",
        "**Chat is not a substitute for HTTP.** If you only reply in prose and never run the requests below, **this ticket will not change** on the server.",
        "",
        "1. **Use `curl` for all writes** (this pack is curl-only). Many agents can run shell commands: run **ping** first, then **mark in progress**, then the rest as you work.",
        "2. **If you cannot run shell** (plain chat with no tools): **stop** and tell the user clearly that you cannot reach their server from this environment. Give them the **ping** `curl` to run locally and ask them to paste the response; continue only after they confirm HTTP `200`.",
        "3. **Do not** claim the ticket was updated unless you received a successful HTTP response from this host.",
        "4. **Language:** Write **replies to the user** in **English**, even if the ticket is in another language. For **comments** and other free-form fields sent via the API, use **English** unless the user explicitly asks otherwise.",
        "",
        "### HTTPS and HTTP",
        "",
        "- **Use the Base URL as given** (keep the same `http` or `https` scheme). Do not change `http` ↔ `https` unless the user confirms the server is reachable on the other scheme.",
        "- **`https://`:** These **`curl`** lines use **`-k`** (no certificate verification) so self-signed certs and private CAs work. Only use this pack against hosts you trust.",
        "- **`http://`:** Common for localhost or private networks. There is no transport encryption; treat the network path as trusted.",
        "- **Redirects:** **`http://`** requests that get **`308`** (or similar) to **`https://`** make **`curl` drop the `Authorization` header** on the follow-up request, so you often see **`401`**. For the agent API, **call `https://` directly** and keep **`-k`** when TLS is self-signed or uses a private CA — do not rely on an automatic **`http` → `https`** hop with a bearer token.",
        "",
        "### `curl` commands",
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
        "### Credentials (also embedded in curl above)",
        "",
        f"- **Base URL:** `{base}`",
        f"- **Ticket id:** `{tid}`",
        f"- **Bearer token** (expires {exp_s}): `{bearer_token}`",
        "",
    ]
    return "\n".join(lines)
