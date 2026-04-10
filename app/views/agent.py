"""Agent HTTP API (Bearer token, no CSRF) for comments and limited ticket updates."""

from __future__ import annotations

import time

from flask import Blueprint, jsonify, request

from ..utils.agent_auth import agent_api_protected, agent_token_allows_ticket
from ..utils.events import EventTypes, bus
from ..utils.models import Comment, Ticket, TicketUpdateMessage, User
from ..utils.ticket_markdown import build_ticket_export_payload
from .tickets import extract_and_save_images

agent_bp = Blueprint("agent", __name__)


@agent_bp.route("/api/agent/tickets/<ticket_id>/comments", methods=["POST"])
@agent_api_protected("comment:write")
def agent_post_comment(user: User, agent_token, ticket_id: str):
    data = request.get_json(silent=True) or {}
    body = str(data.get("body") or data.get("content") or "").strip()
    if not body:
        return jsonify({"error": "body or content is required"}), 400

    ticket = Ticket.get_or_none((Ticket.id == ticket_id) & (Ticket.active == 1))
    if not ticket:
        return jsonify({"error": "Ticket not found"}), 404
    if not agent_token_allows_ticket(agent_token, ticket):
        return jsonify({"error": "Token is not valid for this ticket"}), 403

    processed = extract_and_save_images(body)
    comment = Comment.create(
        ticket=ticket_id,
        user=user.username,
        body=processed,
        created_at=int(time.time()),
    )

    TicketUpdateMessage.create(
        ticket=ticket_id,
        title="Comment via agent",
        icon="ph ph-robot",
        message=f"{user.username} (agent) added a comment",
        created_at=int(time.time()),
    )

    bus.emit(
        EventTypes.TICKET_COMMENTED,
        ticket_id=ticket.id,
        ticket_title=ticket.title,
        project=ticket.project,
        status=ticket.status,
        actor=user.username,
        details="Agent API comment",
    )

    return (
        jsonify({"success": True, "comment_id": comment.id}),
        201,
    )


@agent_bp.route("/api/agent/tickets/<ticket_id>", methods=["PATCH"])
@agent_api_protected("ticket:write")
def agent_patch_ticket(user: User, agent_token, ticket_id: str):
    data = request.get_json(silent=True) or {}
    if not data:
        return jsonify({"error": "No data provided"}), 400

    allowed = {"status", "description_append", "work_cycle_id"}
    if not any(k in data for k in allowed):
        return jsonify({"error": "No recognized fields to update"}), 400

    ticket = Ticket.get_or_none((Ticket.id == ticket_id) & (Ticket.active == 1))
    if not ticket:
        return jsonify({"error": "Ticket not found"}), 404
    if not agent_token_allows_ticket(agent_token, ticket):
        return jsonify({"error": "Token is not valid for this ticket"}), 403

    extra = set(data.keys()) - allowed
    if extra:
        return jsonify({"error": f"Unsupported fields: {sorted(extra)}"}), 400

    if "status" in data:
        ticket.status = str(data["status"])
        ticket.save()
        TicketUpdateMessage.create(
            ticket=ticket_id,
            title="Status changed",
            icon="ph ph-arrow-right",
            message=f"{user.username} (agent) set status to {ticket.status}",
            created_at=int(time.time()),
        )

    if "description_append" in data:
        append = str(data.get("description_append") or "")
        if append.strip():
            sep = "" if not (ticket.description or "").strip() else "\n\n"
            ticket.description = (ticket.description or "") + sep + append
            ticket.save()
            TicketUpdateMessage.create(
                ticket=ticket_id,
                title="Description appended",
                icon="ph ph-note-pencil",
                message=f"{user.username} (agent) appended to the description",
                created_at=int(time.time()),
            )

    if "work_cycle_id" in data:
        from ..utils.models import WorkCycle

        raw = data["work_cycle_id"]
        if raw is None or raw == "":
            ticket.work_cycle_id = None
        else:
            try:
                cid = int(raw)
            except (TypeError, ValueError):
                return jsonify({"error": "work_cycle_id must be int or null"}), 400
            cycle = WorkCycle.get_or_none(WorkCycle.id == cid)
            if not cycle:
                return jsonify({"error": "Work cycle not found"}), 404
            ticket.work_cycle_id = cid
        ticket.save()
        TicketUpdateMessage.create(
            ticket=ticket_id,
            title="Work cycle changed",
            icon="ph ph-calendar",
            message=f"{user.username} (agent) updated work cycle assignment",
            created_at=int(time.time()),
        )

    return jsonify({"success": True}), 200


@agent_bp.route("/api/agent/tickets/<ticket_id>/export", methods=["GET"])
@agent_api_protected("ticket:read")
def agent_export_ticket(user: User, agent_token, ticket_id: str):
    ticket = Ticket.get_or_none((Ticket.id == ticket_id) & (Ticket.active == 1))
    if not ticket:
        return jsonify({"error": "Ticket not found"}), 404
    if not agent_token_allows_ticket(agent_token, ticket):
        return jsonify({"error": "Token is not valid for this ticket"}), 403

    payload = build_ticket_export_payload(ticket_id)
    if not payload:
        return jsonify({"error": "Ticket not found"}), 404
    return jsonify(payload), 200
