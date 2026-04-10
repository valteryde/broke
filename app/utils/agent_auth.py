"""Bearer authentication for agent API routes (no session, no CSRF)."""

from __future__ import annotations

import hashlib
import json
import time
from functools import wraps
from typing import Any, Callable, Iterable, TypeVar

from flask import jsonify, request
from peewee import DoesNotExist

from .models import AgentToken, Ticket, User

F = TypeVar("F", bound=Callable[..., Any])

DEFAULT_AGENT_TTL_SECONDS = 48 * 3600


def _parse_scopes(raw: str | None) -> list[str]:
    try:
        data = json.loads(raw or "[]")
        if isinstance(data, list):
            return [str(x) for x in data]
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def authenticate_agent_bearer() -> tuple[AgentToken | None, User | None, tuple | None]:
    """
    Returns (token_row, user, error_response).
    error_response is (body, status) for jsonify-compatible return.
    """
    auth = request.headers.get("Authorization") or ""
    if not auth.startswith("Bearer "):
        return None, None, (jsonify({"error": "Missing or invalid Authorization"}), 401)
    raw = auth[7:].strip()
    if not raw:
        return None, None, (jsonify({"error": "Missing token"}), 401)

    token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    now = int(time.time())
    try:
        row = AgentToken.get(AgentToken.token_hash == token_hash)
    except DoesNotExist:
        return None, None, (jsonify({"error": "Invalid token"}), 401)

    if row.expires_at < now:
        return None, None, (jsonify({"error": "Token expired"}), 401)

    user = row.user
    if not user:
        return None, None, (jsonify({"error": "Invalid token user"}), 401)

    return row, user, None


def agent_token_allows_scopes(row: AgentToken, required: Iterable[str]) -> bool:
    have = set(_parse_scopes(row.scopes))
    return set(required).issubset(have)


def agent_token_allows_ticket(row: AgentToken, ticket: Ticket) -> bool:
    tid = getattr(row, "ticket_id", None)
    if tid:
        return ticket.id == tid
    if row.project and ticket.project != row.project:
        return False
    if row.work_cycle_id is not None and ticket.work_cycle_id != row.work_cycle_id:
        return False
    return True


def agent_api_protected(*required_scopes: str) -> Callable[[F], F]:
    """Inject (user, agent_token) as first two args after wrapping."""

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any):
            row, user, err = authenticate_agent_bearer()
            if err:
                return err
            assert row is not None and user is not None
            if not agent_token_allows_scopes(row, required_scopes):
                return jsonify({"error": "Insufficient token scope"}), 403
            return func(user, row, *args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator
