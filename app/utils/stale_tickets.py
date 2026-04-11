"""
Detect tickets with no recent activity (stale) for the manual stale-queue UI.

Activity = latest of: ticket creation, any comment, or any ticket update message.
"""

from __future__ import annotations

import time
from typing import Any

from peewee import fn

from .events import EventTypes, bus
from .models import Comment, Ticket, TicketUpdateMessage, User

OPEN_STATUSES = frozenset(
    {
        "backlog",
        "todo",
        "in-progress",
        "in-review",
    }
)
TERMINAL_STATUSES = frozenset({"done", "closed", "duplicate"})


def clamp_inactive_days(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = 90
    return max(7, min(n, 3650))


def last_activity_maps(ticket_ids: list[str]) -> tuple[dict[str, int], dict[str, int]]:
    if not ticket_ids:
        return {}, {}
    comment_rows = (
        Comment.select(Comment.ticket, fn.MAX(Comment.created_at).alias("mx"))
        .where(Comment.ticket.in_(ticket_ids))
        .group_by(Comment.ticket)
    )
    comment_map = {row.ticket: int(row.mx) for row in comment_rows}
    update_rows = (
        TicketUpdateMessage.select(
            TicketUpdateMessage.ticket, fn.MAX(TicketUpdateMessage.created_at).alias("mx")
        )
        .where(TicketUpdateMessage.ticket.in_(ticket_ids))
        .group_by(TicketUpdateMessage.ticket)
    )
    update_map = {row.ticket: int(row.mx) for row in update_rows}
    return comment_map, update_map


def has_open_subtickets(ticket_id: str) -> bool:
    return (
        Ticket.select()
        .where(
            (Ticket.parent_ticket_id == ticket_id)
            & (Ticket.active == 1)
            & (~(Ticket.status.in_(TERMINAL_STATUSES)))
        )
        .exists()
    )


def last_touch_for_ticket(
    ticket: Ticket, comment_map: dict[str, int], update_map: dict[str, int]
) -> int:
    return max(
        int(ticket.created_at or 0),
        int(comment_map.get(ticket.id, 0)),
        int(update_map.get(ticket.id, 0)),
    )


def list_stale_rows(
    project_id: str | None,
    inactive_days: int,
    now: int | None = None,
) -> list[dict[str, Any]]:
    """
    Return rows for tickets that are stale under the given threshold.
    Each row: ticket, last_activity (unix), days_idle (int), blocked (open subtickets).
    """
    ts = int(now if now is not None else time.time())
    inactive_days = clamp_inactive_days(inactive_days)
    cutoff = ts - inactive_days * 86400

    q = (Ticket.active == 1) & (Ticket.status.in_(OPEN_STATUSES))
    if project_id:
        q &= Ticket.project == project_id

    candidates = list(Ticket.select().where(q).order_by(Ticket.project, Ticket.id))
    if not candidates:
        return []

    ticket_ids = [t.id for t in candidates]
    comment_map, update_map = last_activity_maps(ticket_ids)
    rows: list[dict[str, Any]] = []
    for t in candidates:
        last_touch = last_touch_for_ticket(t, comment_map, update_map)
        if last_touch >= cutoff:
            continue
        rows.append(
            {
                "ticket": t,
                "last_activity": last_touch,
                "days_idle": max(0, (ts - last_touch) // 86400),
                "blocked": has_open_subtickets(t.id),
            }
        )
    rows.sort(key=lambda r: (-r["days_idle"], r["ticket"].project, r["ticket"].id))
    return rows


def ticket_matches_stale_rule(
    ticket_id: str, inactive_days: int, now: int | None = None
) -> tuple[bool, Ticket | None, int]:
    """Whether this ticket is currently stale; returns (ok, ticket_or_none, last_touch)."""
    ts = int(now if now is not None else time.time())
    inactive_days = clamp_inactive_days(inactive_days)
    cutoff = ts - inactive_days * 86400
    ticket = Ticket.get_or_none(
        (Ticket.id == ticket_id) & (Ticket.active == 1) & (Ticket.status.in_(OPEN_STATUSES))
    )
    if not ticket:
        return False, None, 0
    cm, um = last_activity_maps([ticket_id])
    last_touch = last_touch_for_ticket(ticket, cm, um)
    if last_touch >= cutoff:
        return False, ticket, last_touch
    return True, ticket, last_touch


def close_ticket_as_stale(
    ticket: Ticket,
    user: User,
    inactive_days: int,
    now: int | None = None,
) -> None:
    """Set status closed, add comment + activity message. Caller must verify stale first."""
    ts = int(now if now is not None else time.time())
    inactive_days = clamp_inactive_days(inactive_days)
    cm, um = last_activity_maps([ticket.id])
    last_touch = last_touch_for_ticket(ticket, cm, um)
    last_day = time.strftime("%Y-%m-%d", time.gmtime(last_touch))

    old_status = ticket.status
    body = (
        f"Closed from the stale tickets overview: no activity for at least {inactive_days} days "
        f"(last activity {last_day} UTC)."
    )
    if len(body) > 250:
        body = body[:247] + "..."

    Comment.create(ticket=ticket.id, user=user, body=body, created_at=ts)

    ticket.status = "closed"
    ticket.save()

    TicketUpdateMessage.create(
        ticket=ticket.id,
        title="Status changed",
        icon="ph ph-arrow-right",
        message=f"{user.username} changed status from {old_status} to closed (stale queue)",
        created_at=ts,
    )

    bus.emit(
        EventTypes.TICKET_STATUS_CHANGED,
        ticket_id=ticket.id,
        ticket_title=ticket.title,
        project=ticket.project,
        status="closed",
        actor=user.username,
        details=f"Closed from stale overview ({inactive_days}d rule)",
    )
