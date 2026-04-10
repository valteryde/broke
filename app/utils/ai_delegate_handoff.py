"""One-shot paste pack for an external AI: full ticket context + real Bearer token + HTTP examples."""

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


def _python_broke_client(base: str, token: str, tid: str) -> str:
    """stdlib only — runs in ChatGPT Code Interpreter, Colab, local Python, many agent sandboxes."""
    return (
        "import json, ssl, urllib.error, urllib.request\n"
        "\n"
        f"BASE = {repr(base)}\n"
        f"TOKEN = {repr(token)}\n"
        f"TICKET_ID = {repr(tid)}\n"
        "\n"
        "def broke(method, path, data=None):\n"
        '    url = BASE.rstrip("/") + path\n'
        "    body = None if data is None else json.dumps(data).encode('utf-8')\n"
        "    req = urllib.request.Request(url, data=body, method=method)\n"
        '    req.add_header("Authorization", "Bearer " + TOKEN)\n'
        "    if body is not None:\n"
        '        req.add_header("Content-Type", "application/json")\n'
        "    ctx = ssl.create_default_context()\n"
        "    try:\n"
        "        with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:\n"
        '            return resp.status, resp.read().decode("utf-8", errors="replace")\n'
        "    except urllib.error.HTTPError as e:\n"
        '        return e.code, e.read().decode("utf-8", errors="replace")\n'
        "\n"
        "# Run immediately; paste stdout back to the user if they need proof.\n"
        'print("ping:", broke("GET", "/api/agent/ping"))\n'
        'print("status_in_progress:", broke("PATCH", "/api/agent/tickets/" + TICKET_ID, {"status": "in-progress"}))\n'
    )


def build_ai_delegate_pack_markdown(
    *,
    payload: dict[str, Any],
    base_url: str,
    bearer_token: str,
    expires_at_epoch: int,
) -> str:
    """
    Written for the AI as the reader. Leads with Python (often executable in-product);
    curl is fallback. States clearly that text-only replies do not update Broke.
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

    esc = bearer_token.replace("'", "'\\''")
    py_block = _python_broke_client(base, bearer_token, tid)

    curl_ping = f"curl -sS -g '{base}/api/agent/ping' -H 'Authorization: Bearer {esc}'"
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
        "# Broke — delegated ticket",
        "",
        "## CRITICAL (read before doing anything else)",
        "",
        "**Talking about Broke is not the same as updating Broke.** If you only reply in prose and never perform an HTTP request, **the ticket in Broke will not change**.",
        "",
        "1. **If your environment can run Python** (ChatGPT *Advanced data analysis / Code interpreter*, Google Colab, a local terminal, Cursor agent, etc.): run the **entire** Python block in the next section **first**. You should see HTTP status `200` and JSON for `ping`, then for `status_in_progress`.",
        "2. **If your environment can run shell only**: run the **ping** `curl` first, then the **in-progress** `curl`.",
        "3. **If you cannot run code or shell at all** (plain chat with no tools): **stop** and tell the user clearly: *I cannot reach your Broke server from here.* Give them the **ping** `curl` to run locally and ask them to paste the response back; then continue only after they confirm `200`.",
        "4. **Do not** claim the ticket was updated in Broke unless you actually received a successful HTTP response from this host.",
        "",
        "---",
        "",
        "## Step 1 — Run this Python (preferred; standard library only)",
        "",
        "Execute the whole block as one script. It verifies the token and sets status to `in-progress`.",
        "",
        "```python",
        py_block.rstrip(),
        "```",
        "",
        'Then use `broke("PATCH", "/api/agent/tickets/" + TICKET_ID, {"status": "done"})` when finished. For comments:',
        "",
        "```python",
        'print("comment:", broke("POST", "/api/agent/tickets/" + TICKET_ID + "/comments", {"body": "Your text here"}))',
        "```",
        "",
        "---",
        "",
        "## Step 2 — Or use `curl` (terminal)",
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
        "## Credentials (also embedded in script/curl above)",
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
