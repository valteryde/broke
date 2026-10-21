"""Shared rules for the parked ticket status."""

from __future__ import annotations

PARKED_STATUS = "parked"
PARKED_CYCLE_ERROR = "Parked tickets stay off a sprint. Move the ticket back to backlog first."


def detach_parked_work_cycle(ticket) -> int | None:
    """Drop a parked ticket from its sprint. The estimate is left as it is."""
    if getattr(ticket, "status", None) != PARKED_STATUS:
        return None
    previous = ticket.work_cycle_id
    if not previous:
        return None
    ticket.work_cycle_id = None
    return int(previous)


def parked_cycle_error(ticket, cycle_id) -> str | None:
    """Parked tickets cannot be placed on a sprint."""
    if getattr(ticket, "status", None) != PARKED_STATUS:
        return None
    if cycle_id is None or cycle_id == "" or cycle_id == "null":
        return None
    return PARKED_CYCLE_ERROR
