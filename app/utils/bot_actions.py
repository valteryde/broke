"""Ticket actions a bot can take. Same records a person would write."""

from __future__ import annotations

import time
from typing import Any

from peewee import DoesNotExist

from .events import EventTypes, bus
from .models import Comment, Project, Ticket, TicketUpdateMessage, User, UserTicketJoin, WorkCycle
from .ticket_estimate import coerce_estimate_minutes, format_estimate_minutes
from .ticket_markdown import build_ticket_export_payload
from .ticket_status import PARKED_CYCLE_ERROR, detach_parked_work_cycle, parked_cycle_error

TICKET_STATUSES = frozenset(
    {
        "backlog",
        "todo",
        "in-progress",
        "in-review",
        "done",
        "closed",
        "duplicate",
        "parked",
        "intake",
        "triage",
    }
)
TICKET_PRIORITIES = frozenset({"low", "medium", "high", "urgent"})
INTAKE_STATUSES = frozenset({"intake", "triage"})
MAX_LIST = 50


class BotToolError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def list_projects() -> dict[str, Any]:
    rows = Project.select().where(Project.archived == 0).order_by(Project.name)
    return {
        "projects": [{"id": row.id, "name": row.name} for row in rows],
    }


def list_work_cycles() -> dict[str, Any]:
    rows = WorkCycle.select().order_by(WorkCycle.created_at.desc())
    return {
        "work_cycles": [
            {
                "id": row.id,
                "name": row.name,
                "project": row.project,
                "goal": row.goal,
                "starts_at": row.starts_at,
                "ends_at": row.ends_at,
            }
            for row in rows
        ]
    }


def list_tickets(
    *,
    project: str | None = None,
    status: str | None = None,
    query: str | None = None,
    limit: int = 30,
) -> dict[str, Any]:
    limit = max(1, min(int(limit or 30), MAX_LIST))
    q = Ticket.select().where(Ticket.active == 1)
    if project:
        q = q.where(Ticket.project == project)
    if status:
        if status not in TICKET_STATUSES:
            raise BotToolError(f"Unknown status. Use one of: {', '.join(sorted(TICKET_STATUSES))}")
        q = q.where(Ticket.status == status)
    if query:
        needle = query.replace("%", "").replace("_", "").strip()
        if needle:
            q = q.where(Ticket.title.contains(needle) | Ticket.description.contains(needle))
    rows = list(q.order_by(Ticket.created_at.desc()).limit(limit))
    return {
        "tickets": [
            {
                "id": row.id,
                "title": row.title,
                "project": row.project,
                "status": row.status,
                "priority": row.priority,
                "estimate_minutes": row.estimate_minutes,
                "work_cycle_id": row.work_cycle_id,
                "created_at": row.created_at,
            }
            for row in rows
        ]
    }


def get_ticket(ticket_id: str) -> dict[str, Any]:
    payload = build_ticket_export_payload(ticket_id)
    if not payload:
        raise BotToolError("Ticket not found")
    return payload


def create_ticket(
    user: User,
    *,
    title: str,
    project: str,
    description: str = "",
    status: str = "todo",
    priority: str = "medium",
    estimate_minutes: Any = None,
) -> dict[str, Any]:
    from ..views.tickets import generate_unique_ticket_id

    title = (title or "").strip()
    if not title:
        raise BotToolError("Title is required")
    if len(title) > 200:
        raise BotToolError("Title is too long")
    project_id = (project or "").strip()
    if not project_id:
        raise BotToolError("Project is required")
    proj = Project.get_or_none(Project.id == project_id)
    if not proj:
        raise BotToolError("Project not found")
    if proj.archived == 1:
        raise BotToolError("Project is archived")
    if status not in TICKET_STATUSES:
        raise BotToolError(f"Unknown status. Use one of: {', '.join(sorted(TICKET_STATUSES))}")
    if priority not in TICKET_PRIORITIES:
        raise BotToolError(f"Unknown priority. Use one of: {', '.join(sorted(TICKET_PRIORITIES))}")
    if len(description or "") > 50000:
        raise BotToolError("Description is too long")

    minutes = None
    if estimate_minutes is not None:
        try:
            minutes = coerce_estimate_minutes(estimate_minutes, integer_is_minutes=True)
        except ValueError as exc:
            raise BotToolError(str(exc)) from exc

    ticket_id = generate_unique_ticket_id(project_id)
    ticket = Ticket.create(
        id=ticket_id,
        title=title,
        description=description or "",
        status=status,
        priority=priority,
        project=project_id,
        created_at=int(time.time()),
        estimate_minutes=minutes,
    )
    TicketUpdateMessage.create(
        ticket=ticket_id,
        title="Created",
        icon="ph ph-plus",
        message=f"{user.username} created this ticket",
        created_at=int(time.time()),
    )
    UserTicketJoin.create(user=user.username, ticket=ticket_id)
    bus.emit(
        EventTypes.TICKET_CREATED,
        ticket_id=ticket.id,
        ticket_title=ticket.title,
        project=ticket.project,
        status=ticket.status,
        actor=user.username,
        details="Ticket created by bot",
    )
    return {
        "id": ticket.id,
        "title": ticket.title,
        "project": ticket.project,
        "status": ticket.status,
        "priority": ticket.priority,
        "estimate_minutes": ticket.estimate_minutes,
    }


def update_ticket(
    user: User,
    *,
    ticket_id: str,
    status: str | None = None,
    description_append: str | None = None,
    work_cycle_id: Any = None,
    estimate_minutes: Any = None,
    fields_set: set[str],
) -> dict[str, Any]:
    if not fields_set:
        raise BotToolError("No fields to update")
    try:
        ticket = Ticket.get((Ticket.id == ticket_id) & (Ticket.active == 1))
    except DoesNotExist:
        raise BotToolError("Ticket not found") from None

    if (
        "status" in fields_set
        and status == "parked"
        and "work_cycle_id" in fields_set
        and work_cycle_id not in (None, "")
    ):
        raise BotToolError(PARKED_CYCLE_ERROR)

    if "status" in fields_set:
        if status not in TICKET_STATUSES:
            raise BotToolError(f"Unknown status. Use one of: {', '.join(sorted(TICKET_STATUSES))}")
        old_status = ticket.status
        if (
            old_status in INTAKE_STATUSES
            and status not in INTAKE_STATUSES
            and (not ticket.project or ticket.project == "TRIAGE")
        ):
            raise BotToolError("Assign a project before moving this ticket out of intake")
        ticket.status = status
        cleared_cycle = detach_parked_work_cycle(ticket)
        save_fields = [Ticket.status]
        if cleared_cycle:
            save_fields.append(Ticket.work_cycle_id)
        ticket.save(only=save_fields)
        TicketUpdateMessage.create(
            ticket=ticket.id,
            title="Status changed",
            icon="ph ph-arrow-right",
            message=f"{user.username} changed status from {old_status} to {status}",
            created_at=int(time.time()),
        )
        if cleared_cycle:
            TicketUpdateMessage.create(
                ticket=ticket.id,
                title="Removed from work cycle",
                icon="ph ph-calendar-x",
                message=f"{user.username} parked this ticket and removed it from the work cycle",
                created_at=int(time.time()),
            )
        bus.emit(
            EventTypes.TICKET_STATUS_CHANGED,
            ticket_id=ticket.id,
            ticket_title=ticket.title,
            project=ticket.project,
            status=status,
            old_status=old_status,
            actor=user.username,
            details=f"Status changed from {old_status} to {status}",
        )

    if "description_append" in fields_set:
        append = str(description_append or "")
        if len(append) > 20000:
            raise BotToolError("Description append is too long")
        if append.strip():
            sep = "" if not (ticket.description or "").strip() else "\n\n"
            ticket.description = (ticket.description or "") + sep + append
            ticket.save(only=[Ticket.description])
            TicketUpdateMessage.create(
                ticket=ticket.id,
                title="Description appended",
                icon="ph ph-note-pencil",
                message=f"{user.username} appended to the description",
                created_at=int(time.time()),
            )

    if "work_cycle_id" in fields_set:
        cycle_error = parked_cycle_error(ticket, work_cycle_id)
        if cycle_error:
            raise BotToolError(cycle_error)
        if work_cycle_id is None or work_cycle_id == "":
            ticket.work_cycle_id = None
        else:
            try:
                cycle_id = int(work_cycle_id)
            except (TypeError, ValueError):
                raise BotToolError("work_cycle_id must be an integer or null") from None
            if not WorkCycle.get_or_none(WorkCycle.id == cycle_id):
                raise BotToolError("Work cycle not found")
            ticket.work_cycle_id = cycle_id
        ticket.save(only=[Ticket.work_cycle_id])
        TicketUpdateMessage.create(
            ticket=ticket.id,
            title="Work cycle changed",
            icon="ph ph-calendar",
            message=f"{user.username} updated work cycle assignment",
            created_at=int(time.time()),
        )

    if "estimate_minutes" in fields_set:
        try:
            minutes = coerce_estimate_minutes(estimate_minutes, integer_is_minutes=True)
        except ValueError as exc:
            raise BotToolError(str(exc)) from exc
        old_label = format_estimate_minutes(ticket.estimate_minutes) or "none"
        ticket.estimate_minutes = minutes
        ticket.save(only=[Ticket.estimate_minutes])
        new_label = format_estimate_minutes(minutes) or "none"
        TicketUpdateMessage.create(
            ticket=ticket.id,
            title="Estimate changed",
            icon="ph ph-timer",
            message=f"{user.username} changed estimate from {old_label} to {new_label}",
            created_at=int(time.time()),
        )

    return {
        "id": ticket.id,
        "status": ticket.status,
        "estimate_minutes": ticket.estimate_minutes,
        "work_cycle_id": ticket.work_cycle_id,
    }


def add_comment(user: User, *, ticket_id: str, body: str) -> dict[str, Any]:
    from ..views.tickets import extract_and_save_images

    text = (body or "").strip()
    if not text:
        raise BotToolError("Comment body is required")
    if len(text) > 20000:
        raise BotToolError("Comment is too long")
    ticket = Ticket.get_or_none((Ticket.id == ticket_id) & (Ticket.active == 1))
    if not ticket:
        raise BotToolError("Ticket not found")

    processed = extract_and_save_images(text)
    comment = Comment.create(
        ticket=ticket_id,
        user=user.username,
        body=processed,
        created_at=int(time.time()),
        via_agent=0,
    )
    bus.emit(
        EventTypes.TICKET_COMMENTED,
        ticket_id=ticket.id,
        ticket_title=ticket.title,
        project=ticket.project,
        status=ticket.status,
        actor=user.username,
        comment_id=comment.id,
        comment_body=processed,
        comment_via_agent=False,
    )
    return {"comment_id": comment.id, "ticket_id": ticket.id}
