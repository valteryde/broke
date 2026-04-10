"""Build ticket export payloads and Markdown for human and AI handoff."""

from __future__ import annotations

from typing import Any

from peewee import DoesNotExist

from .models import Comment, Ticket, TicketLabelJoin, TicketUpdateMessage, UserTicketJoin, WorkCycle


def build_ticket_export_payload(ticket_id: str) -> dict[str, Any] | None:
    """Load ticket and related rows into the same shape as single-ticket JSON export."""
    try:
        ticket = Ticket.get((Ticket.id == ticket_id) & (Ticket.active == 1))
    except DoesNotExist:
        return None

    comments = list(
        Comment.select().where(Comment.ticket == ticket_id).order_by(Comment.created_at.asc())
    )
    updates = list(
        TicketUpdateMessage.select()
        .where(TicketUpdateMessage.ticket == ticket_id)
        .order_by(TicketUpdateMessage.created_at.asc())
    )
    labels = [
        row.label for row in TicketLabelJoin.select().where(TicketLabelJoin.ticket == ticket_id)
    ]
    assignees = [
        row.user for row in UserTicketJoin.select().where(UserTicketJoin.ticket == ticket_id)
    ]
    subtickets = list(
        Ticket.select()
        .where((Ticket.parent_ticket_id == ticket_id) & (Ticket.active == 1))
        .order_by(Ticket.created_at.asc())
    )

    return {
        "id": ticket.id,
        "title": ticket.title,
        "description": ticket.description,
        "project": ticket.project,
        "status": ticket.status,
        "priority": ticket.priority,
        "parent_ticket_id": ticket.parent_ticket_id,
        "work_cycle_id": ticket.work_cycle_id,
        "ai_delegate": bool(getattr(ticket, "ai_delegate", 0) or 0),
        "created_at": ticket.created_at,
        "labels": labels,
        "assignees": assignees,
        "comments": [
            {
                "id": comment.id,
                "user": comment.user.username,
                "body": comment.body,
                "created_at": comment.created_at,
            }
            for comment in comments
        ],
        "updates": [
            {
                "title": update.title,
                "icon": update.icon,
                "message": update.message,
                "created_at": update.created_at,
            }
            for update in updates
        ],
        "subtickets": [
            {
                "id": child.id,
                "title": child.title,
                "status": child.status,
                "priority": child.priority,
                "created_at": child.created_at,
            }
            for child in subtickets
        ],
    }


def ticket_payload_to_markdown(payload: dict[str, Any]) -> str:
    """Render export payload as Markdown (same layout as legacy single-ticket export)."""
    ticket_id = payload["id"]
    labels = payload.get("labels") or []
    assignees = payload.get("assignees") or []
    comments = payload.get("comments") or []
    updates = payload.get("updates") or []
    subtickets = payload.get("subtickets") or []
    wc = payload.get("work_cycle_id")

    markdown_lines = [
        f"# Ticket {ticket_id}",
        "",
        f"- Title: {payload.get('title', '')}",
        f"- Project: {payload.get('project', '')}",
        f"- Status: {payload.get('status', '')}",
        f"- Priority: {payload.get('priority', '')}",
        f"- Parent Ticket: {payload.get('parent_ticket_id') or 'None'}",
        f"- Work cycle id: {wc if wc is not None else 'None'}",
        f"- External AI handoff: {'yes' if payload.get('ai_delegate') else 'no'}",
        f"- Created At (epoch): {payload.get('created_at', '')}",
        f"- Labels: {', '.join(labels) if labels else 'None'}",
        f"- Assignees: {', '.join(assignees) if assignees else 'None'}",
        "",
        "## Description",
        "",
        str(payload.get("description") or ""),
        "",
        "## Comments",
        "",
    ]

    if comments:
        for comment in comments:
            markdown_lines.extend(
                [
                    f"### {comment['user']} ({comment['created_at']})",
                    "",
                    str(comment.get("body") or ""),
                    "",
                ]
            )
    else:
        markdown_lines.append("No comments.")
        markdown_lines.append("")

    markdown_lines.append("## Updates")
    markdown_lines.append("")
    if updates:
        for update in updates:
            markdown_lines.append(
                f"- **{update['title']}** ({update['created_at']}): {update['message']}"
            )
    else:
        markdown_lines.append("No updates.")

    markdown_lines.append("")
    markdown_lines.append("## Subtickets")
    markdown_lines.append("")
    if subtickets:
        for child in subtickets:
            markdown_lines.append(
                f"- {child['id']} | {child['title']} | {child['status']} | {child['priority']}"
            )
    else:
        markdown_lines.append("No subtickets.")

    return "\n".join(markdown_lines)


def cycle_assistant_instruction_block(base_url: str, cycle_id: int) -> str:
    """Static guidance for external AI + git/Broke integration."""
    cycle_url = f"{base_url.rstrip('/')}/work-cycles/{cycle_id}"
    return "\n".join(
        [
            "## Instructions for the assistant",
            "",
            "- Propose ordered next steps, risks, and open questions for the human.",
            "- When committing code that maps to a ticket, put the ticket id in the **commit subject** using Broke's GitHub webhook conventions:",
            "  - **Resolve / done-style:** `fix TICKET-ID`, `close TICKET-ID`, `resolve TICKET-ID` (optional `#` before the id, e.g. `fix #ABC-1`).",
            "  - **Reference only:** `ref TICKET-ID`, `see TICKET-ID`, `related TICKET-ID`.",
            "- Prefer one primary ticket per commit when possible; use the commit body for extra refs.",
            "- After push, Broke links commits to tickets when the GitHub webhook is configured.",
            f"- Work cycle in Broke: {cycle_url}",
            "",
        ]
    )


def work_cycle_to_export_dict(cycle: WorkCycle) -> dict[str, Any]:
    return {
        "id": cycle.id,
        "name": cycle.name,
        "goal": cycle.goal,
        "project": cycle.project,
        "starts_at": cycle.starts_at,
        "ends_at": cycle.ends_at,
        "created_at": cycle.created_at,
    }


def build_cycle_markdown_document(
    cycle: WorkCycle,
    ticket_payloads: list[dict[str, Any]],
    base_url: str,
) -> str:
    """Full markdown pack for a work cycle + all tickets."""
    lines: list[str] = [
        f"# Work cycle: {cycle.name}",
        "",
        f"- Cycle id: {cycle.id}",
        f"- Project scope: {cycle.project if cycle.project else 'All projects'}",
        f"- Goal: {cycle.goal or 'None'}",
        f"- Starts (epoch): {cycle.starts_at if cycle.starts_at is not None else 'None'}",
        f"- Ends (epoch): {cycle.ends_at if cycle.ends_at is not None else 'None'}",
        "",
        "---",
        "",
    ]
    lines.append(cycle_assistant_instruction_block(base_url, cycle.id))
    lines.append("---")
    lines.append("")

    for i, payload in enumerate(ticket_payloads):
        if i:
            lines.append("")
            lines.append("---")
            lines.append("")
        lines.append(ticket_payload_to_markdown(payload))

    return "\n".join(lines)
