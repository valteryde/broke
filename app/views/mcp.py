"""MCP streamable HTTP endpoint. Tools are discovered from the server, not the client config."""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urlparse

from flask import Blueprint, jsonify, request

from ..utils.bot_actions import (
    TICKET_PRIORITIES,
    TICKET_STATUSES,
    BotToolError,
    add_comment,
    create_ticket,
    get_ticket,
    list_projects,
    list_tickets,
    list_work_cycles,
    update_ticket,
)
from ..utils.bot_auth import authenticate_bot_bearer
from ..utils.models import User

logger = logging.getLogger(__name__)

mcp_bp = Blueprint("mcp", __name__)

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
PREFERRED_PROTOCOL = "2025-03-26"

_STATUS_ENUM = sorted(TICKET_STATUSES)
_PRIORITY_ENUM = sorted(TICKET_PRIORITIES)


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


def tool_definitions() -> list[dict]:
    return [
        _tool(
            "list_projects",
            "List active projects. Use a project id when creating a ticket.",
            {},
            [],
        ),
        _tool(
            "list_work_cycles",
            "List work cycles. Use an id when setting a ticket's work cycle.",
            {},
            [],
        ),
        _tool(
            "list_tickets",
            "List active tickets. Filter by project id, status, "
            "or text in the title and description.",
            {
                "project": {"type": "string", "description": "Project id"},
                "status": {"type": "string", "enum": _STATUS_ENUM},
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            [],
        ),
        _tool(
            "get_ticket",
            "Read one ticket, including description, comments, assignees, labels, and subtickets.",
            {"ticket_id": {"type": "string"}},
            ["ticket_id"],
        ),
        _tool(
            "create_ticket",
            "Create a ticket in a project. You are assigned to it. "
            "Status defaults to todo. Priority defaults to medium.",
            {
                "title": {"type": "string"},
                "project": {"type": "string", "description": "Project id from list_projects"},
                "description": {"type": "string"},
                "status": {"type": "string", "enum": _STATUS_ENUM},
                "priority": {"type": "string", "enum": _PRIORITY_ENUM},
                "estimate_minutes": {
                    "type": "integer",
                    "description": (
                        "Work minutes. A day is 8 hours. A week is 5 days. Maximum is 4 weeks."
                    ),
                },
            },
            ["title", "project"],
        ),
        _tool(
            "update_ticket",
            "Update a ticket's status, append to its description, "
            "set or clear its work cycle, or set or clear its estimate.",
            {
                "ticket_id": {"type": "string"},
                "status": {"type": "string", "enum": _STATUS_ENUM},
                "description_append": {"type": "string"},
                "work_cycle_id": {
                    "type": ["integer", "null"],
                    "description": "Work cycle id, or null to clear it.",
                },
                "estimate_minutes": {
                    "type": ["integer", "null"],
                    "description": "Work minutes, or null to clear the estimate.",
                },
            },
            ["ticket_id"],
        ),
        _tool(
            "add_comment",
            "Comment on a ticket as this bot. The comment shows this bot's username.",
            {
                "ticket_id": {"type": "string"},
                "body": {"type": "string"},
            },
            ["ticket_id", "body"],
        ),
    ]


def _origin_allowed() -> bool:
    origin = (request.headers.get("Origin") or "").strip()
    if not origin:
        return True
    parsed = urlparse(origin)
    expected = urlparse(request.host_url)
    if parsed.hostname != expected.hostname:
        return False
    return (parsed.port or _default_port(parsed.scheme)) == (
        expected.port or _default_port(expected.scheme)
    )


def _default_port(scheme: str | None) -> int | None:
    if scheme == "https":
        return 443
    if scheme == "http":
        return 80
    return None


def _rpc_error(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _rpc_result(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _text_result(payload: Any, *, is_error: bool = False) -> dict:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, indent=2, default=str)}],
        "isError": is_error,
    }


def _instructions(user: User) -> str:
    return (
        f"You are acting as the Broke bot {user.username}. "
        "You can list projects, work cycles, and tickets, read a ticket, create a ticket, "
        "comment, and update status, estimate, work cycle, or append to the description. "
        "You cannot change workspace settings, users, or other bots. "
        "Call list_projects before creating a ticket if you do not already know the project id."
    )


def _call_tool(user: User, name: str, arguments: dict) -> dict:
    try:
        if name == "list_projects":
            payload = list_projects()
        elif name == "list_work_cycles":
            payload = list_work_cycles()
        elif name == "list_tickets":
            raw_limit = arguments.get("limit")
            try:
                limit = int(raw_limit) if raw_limit is not None else 30
            except (TypeError, ValueError):
                return _text_result({"error": "limit must be an integer"}, is_error=True)
            payload = list_tickets(
                project=arguments.get("project") or None,
                status=arguments.get("status") or None,
                query=arguments.get("query") or None,
                limit=limit,
            )
        elif name == "get_ticket":
            payload = get_ticket(str(arguments.get("ticket_id") or ""))
        elif name == "create_ticket":
            payload = create_ticket(
                user,
                title=str(arguments.get("title") or ""),
                project=str(arguments.get("project") or ""),
                description=str(arguments.get("description") or ""),
                status=str(arguments.get("status") or "todo"),
                priority=str(arguments.get("priority") or "medium"),
                estimate_minutes=arguments.get("estimate_minutes")
                if "estimate_minutes" in arguments
                else None,
            )
        elif name == "update_ticket":
            fields = set(arguments) - {"ticket_id"}
            payload = update_ticket(
                user,
                ticket_id=str(arguments.get("ticket_id") or ""),
                status=arguments.get("status"),
                description_append=arguments.get("description_append"),
                work_cycle_id=arguments.get("work_cycle_id"),
                estimate_minutes=arguments.get("estimate_minutes"),
                fields_set=fields,
            )
        elif name == "add_comment":
            payload = add_comment(
                user,
                ticket_id=str(arguments.get("ticket_id") or ""),
                body=str(arguments.get("body") or ""),
            )
        else:
            return _text_result({"error": f"Unknown tool: {name}"}, is_error=True)
    except BotToolError as exc:
        return _text_result({"error": exc.message}, is_error=True)
    except Exception:
        logger.exception("MCP tool %s failed", name)
        return _text_result({"error": "Tool failed"}, is_error=True)
    return _text_result(payload)


def _handle_message(user: User, message: Any) -> dict | None:
    if not isinstance(message, dict):
        return _rpc_error(None, -32600, "Invalid request")
    method = message.get("method")
    req_id = message.get("id", None)
    is_notification = "id" not in message
    params = message.get("params") or {}
    if params is None:
        params = {}
    if not isinstance(params, dict):
        if is_notification:
            return None
        return _rpc_error(req_id, -32602, "Invalid params")

    if method == "notifications/initialized" or method == "notifications/cancelled":
        return None
    if method == "initialize":
        client_version = str(params.get("protocolVersion") or "")
        version = client_version if client_version in PROTOCOL_VERSIONS else PREFERRED_PROTOCOL
        return _rpc_result(
            req_id,
            {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "broke", "version": "1"},
                "instructions": _instructions(user),
            },
        )
    if method == "ping":
        return _rpc_result(req_id, {})
    if method == "tools/list":
        return _rpc_result(req_id, {"tools": tool_definitions()})
    if method == "resources/list":
        return _rpc_result(req_id, {"resources": []})
    if method == "prompts/list":
        return _rpc_result(req_id, {"prompts": []})
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str) or not name:
            return _rpc_error(req_id, -32602, "Tool name is required")
        if not isinstance(arguments, dict):
            return _rpc_error(req_id, -32602, "Tool arguments must be an object")
        return _rpc_result(req_id, _call_tool(user, name, arguments))
    if is_notification:
        return None
    return _rpc_error(req_id, -32601, "Method not found")


@mcp_bp.route("/mcp", methods=["GET", "POST", "DELETE"])
def mcp_endpoint():
    if request.method == "GET":
        response = jsonify(_rpc_error(None, -32000, "This server does not offer an SSE stream"))
        response.status_code = 405
        response.headers["Allow"] = "POST, DELETE"
        return response
    if request.method == "DELETE":
        return "", 204
    if not _origin_allowed():
        return jsonify(_rpc_error(None, -32000, "Origin not allowed")), 403

    user, err = authenticate_bot_bearer()
    if err:
        body, status = err
        return body, status

    payload = request.get_json(force=False, silent=True)
    if payload is None:
        return jsonify(_rpc_error(None, -32700, "Parse error")), 400

    assert user is not None
    if isinstance(payload, list):
        responses = []
        for item in payload:
            result = _handle_message(user, item)
            if result is not None:
                responses.append(result)
        if not responses:
            return "", 202
        return jsonify(responses)

    result = _handle_message(user, payload)
    if result is None:
        return "", 202
    return jsonify(result)
