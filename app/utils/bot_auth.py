"""Bearer tokens for bot users. One active token per bot, shown once."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import time

from flask import jsonify, request
from peewee import DoesNotExist

from .models import BotToken, User

USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{1,31}$")


def hash_bot_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def mint_bot_token(bot: User) -> str:
    """Revoke the previous token and return a new raw token."""
    BotToken.update(revoked=1).where(
        (BotToken.user == bot.username) & (BotToken.revoked == 0)
    ).execute()
    raw = secrets.token_urlsafe(32)
    BotToken.create(
        user=bot.username,
        token_hash=hash_bot_token(raw),
        token_preview=raw[:8],
        created_at=int(time.time()),
        revoked=0,
    )
    return raw


def revoke_bot_tokens(username: str) -> None:
    BotToken.update(revoked=1).where(BotToken.user == username).execute()


def can_manage_bot(actor: User, bot: User) -> bool:
    if not bot.is_bot or bot.bot_disabled:
        return False
    if actor.admin == 1:
        return True
    return bot.bot_owner == actor.username


def mcp_config_block(base_url: str, token: str) -> str:
    return json.dumps(
        {
            "mcpServers": {
                "broke": {
                    "url": f"{base_url.rstrip('/')}/mcp",
                    "headers": {"Authorization": f"Bearer {token}"},
                }
            }
        },
        indent=2,
    )


def public_base_url() -> str:
    root = (request.script_root or "").rstrip("/")
    return request.host_url.rstrip("/") + root


def authenticate_bot_bearer() -> tuple[User | None, tuple | None]:
    """Return (bot user, error response). error response is (body, status)."""
    auth = request.headers.get("Authorization") or ""
    if not auth.startswith("Bearer "):
        return None, (jsonify({"error": "Missing or invalid Authorization"}), 401)
    raw = auth[7:].strip()
    if not raw:
        return None, (jsonify({"error": "Missing token"}), 401)

    try:
        row = BotToken.get((BotToken.token_hash == hash_bot_token(raw)) & (BotToken.revoked == 0))
    except DoesNotExist:
        return None, (jsonify({"error": "Invalid token"}), 401)

    user = row.user
    if not user or not user.is_bot or user.bot_disabled:
        return None, (jsonify({"error": "Invalid token"}), 401)

    row.last_used = int(time.time())
    row.save(only=[BotToken.last_used])
    return user, None
