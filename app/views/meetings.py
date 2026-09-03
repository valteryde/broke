"""Meeting notes: capture in the meeting, create project tickets on Done."""

from __future__ import annotations

import html
import json
import time
from datetime import datetime
from typing import Any

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from ..utils.ai_changelog import is_ai_enabled
from ..utils.events import EventTypes, bus
from ..utils.meeting_notes import (
    MeetingAIFailed,
    MeetingAINotConfigured,
    extract_meeting_work,
)
from ..utils.models import (
    Meeting,
    Project,
    Ticket,
    TicketUpdateMessage,
    User,
    UserTicketJoin,
    active_projects_ordered,
    database,
)
from ..utils.reltime import time_ago
from ..utils.security import protected
from .tickets import generate_unique_ticket_id

meetings_bp = Blueprint("meetings", __name__)


def _default_title() -> str:
    return datetime.now().strftime("Meeting · %d %b %Y")


def _projects_payload() -> list[dict[str, str]]:
    return [{"id": project.id, "name": project.name} for project in active_projects_ordered()]


def _usernames() -> list[str]:
    return [user.username for user in User.select()]


def _meeting_dict(meeting: Meeting, *, include_notes: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": meeting.id,
        "title": meeting.title,
        "status": meeting.status,
        "created_by": meeting.created_by,
        "created_at": meeting.created_at,
        "updated_at": meeting.updated_at,
        "done_at": meeting.done_at,
    }
    if include_notes:
        payload["notes"] = meeting.notes or ""
    result = _load_result(meeting)
    if result is not None:
        payload["result"] = result
    return payload


def _load_result(meeting: Meeting) -> dict[str, Any] | None:
    raw = meeting.result_json
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _text_to_html(text: str) -> str:
    escaped = html.escape((text or "").strip())
    if not escaped:
        return ""
    return "".join(f"<p>{line if line else '<br>'}</p>" for line in escaped.split("\n"))


def _ticket_description(draft: dict[str, Any], meeting: Meeting) -> str:
    body = str(draft.get("description") or "").strip()
    html_body = _text_to_html(body)
    footer = f"<p><em>From meeting: {html.escape(meeting.title)}</em></p>"
    return f"{html_body}{footer}" if html_body else footer


def _create_tickets_from_extract(
    meeting: Meeting,
    user: User,
    extract: dict[str, Any],
) -> dict[str, Any]:
    created: list[dict[str, Any]] = []
    skipped = list(extract.get("skipped") or [])
    now = int(time.time())

    with database.atomic():
        for draft in extract.get("tickets") or []:
            if not isinstance(draft, dict):
                continue
            title = str(draft.get("title") or "").strip()
            project_id = str(draft.get("project") or "").strip()
            if not title or not project_id:
                if title:
                    skipped.append({"title": title, "reason": "No matching project"})
                continue

            project = Project.get_or_none(Project.id == project_id)
            if not project or project.archived == 1:
                skipped.append({"title": title, "reason": "No matching project"})
                continue

            ticket_id = generate_unique_ticket_id(project_id)
            priority = str(draft.get("priority") or "medium").strip().lower() or "medium"
            ticket = Ticket.create(
                id=ticket_id,
                title=title,
                description=_ticket_description(draft, meeting),
                status="backlog",
                priority=priority,
                project=project_id,
                created_at=now,
                meeting_id=meeting.id,
            )
            TicketUpdateMessage.create(
                ticket=ticket_id,
                title="Created",
                icon="ph ph-plus",
                message=f"{user.username} created this ticket from meeting notes",
                created_at=now,
            )
            assignees = draft.get("assignees") or []
            if not isinstance(assignees, list):
                assignees = []
            assignee_names = [str(a).strip() for a in assignees if str(a or "").strip()]
            for name in assignee_names:
                UserTicketJoin.create(user=name, ticket=ticket_id)

            created.append(
                {
                    "id": ticket.id,
                    "title": ticket.title,
                    "project": ticket.project,
                    "status": ticket.status,
                    "priority": ticket.priority,
                    "assignees": assignee_names,
                    "marked": bool(draft.get("marked")),
                }
            )

        result = {
            "tickets": created,
            "decisions": extract.get("decisions") or [],
            "questions": extract.get("questions") or [],
            "skipped": skipped,
            "source": extract.get("source") or "fallback",
            "reason": extract.get("reason") or "",
        }
        meeting.status = "done"
        meeting.done_at = now
        meeting.updated_at = now
        meeting.result_json = json.dumps(result)
        meeting.save()

    for ticket in created:
        bus.emit(
            EventTypes.TICKET_CREATED,
            ticket_id=ticket["id"],
            ticket_title=ticket["title"],
            project=ticket["project"],
            status=ticket["status"],
            actor=user.username,
            details="Ticket created from meeting notes",
        )

    return result


@meetings_bp.route("/meetings")
@protected
def meetings_list_view(user: User):
    meetings = list(Meeting.select().order_by(Meeting.created_at.desc(), Meeting.id.desc()))
    counts: dict[int, int] = {}
    if meetings:
        ids = [m.id for m in meetings]
        for ticket in Ticket.select(Ticket.meeting_id).where(
            (Ticket.meeting_id.in_(ids)) & (Ticket.active == 1)
        ):
            counts[ticket.meeting_id] = counts.get(ticket.meeting_id, 0) + 1
    rows = []
    for meeting in meetings:
        rows.append(
            {
                "meeting": meeting,
                "created_ago": time_ago(meeting.created_at),
                "ticket_count": counts.get(meeting.id, 0),
            }
        )
    return render_template(
        "meetings_list.jinja2",
        user=user,
        page="meetings",
        rows=rows,
        ai_enabled=is_ai_enabled(),
    )


@meetings_bp.route("/meetings/<int:meeting_id>")
@protected
def meeting_detail_view(user: User, meeting_id: int):
    meeting = Meeting.get_or_none(Meeting.id == meeting_id)
    if not meeting:
        return redirect(url_for("meetings.meetings_list_view"))
    result = _load_result(meeting)
    project_names = {p["id"]: p["name"] for p in _projects_payload()}
    ticket_groups = []
    if result:
        grouped: dict[str, dict[str, Any]] = {}
        for ticket in result.get("tickets") or []:
            pid = str(ticket.get("project") or "")
            if pid not in grouped:
                grouped[pid] = {
                    "id": pid,
                    "name": project_names.get(pid, pid),
                    "tickets": [],
                }
                ticket_groups.append(grouped[pid])
            grouped[pid]["tickets"].append(ticket)
    return render_template(
        "meeting_detail.jinja2",
        user=user,
        page="meetings",
        meeting=meeting,
        result=result,
        ticket_groups=ticket_groups,
        is_done=meeting.status == "done",
        ai_enabled=is_ai_enabled(),
    )


@meetings_bp.route("/api/meetings", methods=["POST"])
@protected
def create_meeting(user: User):
    data = request.get_json(silent=True) or {}
    title = str(data.get("title") or "").strip() or _default_title()
    notes = str(data.get("notes") or "")
    now = int(time.time())
    meeting = Meeting.create(
        title=title,
        notes=notes,
        created_by=user.username,
        status="open",
        created_at=now,
        updated_at=now,
    )
    return jsonify({"success": True, "meeting": _meeting_dict(meeting)}), 201


@meetings_bp.route("/api/meetings/<int:meeting_id>", methods=["PATCH"])
@protected
def update_meeting(user: User, meeting_id: int):
    meeting = Meeting.get_or_none(Meeting.id == meeting_id)
    if not meeting:
        return jsonify({"error": "Meeting not found"}), 404
    if meeting.status == "done":
        return jsonify({"error": "This meeting is already done"}), 400

    data = request.get_json(silent=True) or {}
    if "title" in data:
        title = str(data.get("title") or "").strip()
        if title:
            meeting.title = title
    if "notes" in data:
        meeting.notes = str(data.get("notes") or "")
    meeting.updated_at = int(time.time())
    meeting.save()
    return jsonify({"success": True, "meeting": _meeting_dict(meeting)})


@meetings_bp.route("/api/meetings/<int:meeting_id>/done", methods=["POST"])
@protected
def finish_meeting(user: User, meeting_id: int):
    meeting = Meeting.get_or_none(Meeting.id == meeting_id)
    if not meeting:
        return jsonify({"error": "Meeting not found"}), 404

    if meeting.status == "done":
        return jsonify({"success": True, "meeting": _meeting_dict(meeting), "already_done": True})

    data = request.get_json(silent=True) or {}
    if "notes" in data:
        meeting.notes = str(data.get("notes") or "")
    if "title" in data:
        title = str(data.get("title") or "").strip()
        if title:
            meeting.title = title

    notes = (meeting.notes or "").strip()
    if not notes:
        return jsonify({"error": "Add some notes first"}), 400

    projects = _projects_payload()
    if not projects:
        return jsonify({"error": "Create a project before turning notes into tickets"}), 400

    meeting.updated_at = int(time.time())
    meeting.save()

    try:
        extract = extract_meeting_work(
            meeting.notes or "",
            projects,
            _usernames(),
            meeting_title=meeting.title,
        )
    except MeetingAINotConfigured as exc:
        return jsonify({"error": str(exc)}), 400
    except MeetingAIFailed as exc:
        return jsonify({"error": str(exc)}), 502
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    result = _create_tickets_from_extract(meeting, user, extract)
    return (
        jsonify(
            {
                "success": True,
                "meeting": _meeting_dict(meeting),
                "result": result,
            }
        ),
        200,
    )
