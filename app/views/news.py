from ..utils.security import protected
from ..utils.models import (
    User,
    Ticket,
    UserTicketJoin,
    ErrorGroup,
    Project,
    ProjectPart,
    Comment,
    TicketUpdateMessage,
    TicketLabelJoin,
)
from flask import render_template, redirect, Blueprint, request, Response
from urllib.parse import urlencode
import json
import time
import csv
import io
from ..utils.path import data_path, path

# Create blueprint
news_bp = Blueprint("news", __name__)

LOW_SIGNAL_UPDATE_TITLES = {
    "Title changed",
    "Description updated",
    "Priority changed",
    "Assignees changed",
    "Labels changed",
}


def time_ago(timestamp: int) -> str:
    """Convert a Unix timestamp to a human-readable 'time ago' string."""
    now = int(time.time())
    diff = now - timestamp

    if diff < 60:
        return "just now"
    elif diff < 3600:
        minutes = diff // 60
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif diff < 86400:
        hours = diff // 3600
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    elif diff < 604800:
        days = diff // 86400
        return f"{days} day{'s' if days != 1 else ''} ago"
    elif diff < 2592000:
        weeks = diff // 604800
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"
    else:
        months = diff // 2592000
        return f"{months} month{'s' if months != 1 else ''} ago"


@news_bp.route("/news")
@protected
def news_view(user: User):

    print("-1->", data_path("app.db"))
    print("-2->", path("..", "data", "app.db"))

    # Get current time for calculations
    now = int(time.time())
    today_start = now - (now % 86400)  # Start of today

    # Get tickets assigned to the user
    user_ticket_ids = [
        utj.ticket for utj in UserTicketJoin.select().where(UserTicketJoin.user == user.username)
    ]
    my_tickets = list(
        Ticket.select().where(Ticket.id.in_(user_ticket_ids)).order_by(Ticket.created_at.desc())
    )

    # Count open tickets (tickets that are not closed)
    open_tickets = (
        Ticket.select()
        .where((Ticket.id.in_(user_ticket_ids)) & (Ticket.status != "closed"))
        .count()
    )

    # Get unresolved errors
    unresolved_errors = ErrorGroup.select().where(ErrorGroup.status == "unresolved").count()

    # Get errors resolved today
    resolved_today = (
        ErrorGroup.select()
        .where((ErrorGroup.status == "resolved") & (ErrorGroup.last_seen >= today_start))
        .count()
    )

    # Get recent errors (last 5)
    recent_errors = list(ErrorGroup.select().order_by(ErrorGroup.last_seen.desc()).limit(5))

    # Get all projects
    projects = list(Project.select().order_by(Project.name))

    # Build activity feed from comments and ticket updates
    activities = []

    # Add recent comments
    recent_comments = Comment.select().order_by(Comment.created_at.desc()).limit(15)
    for comment in recent_comments:
        activities.append(
            {
                "type": "comment",
                "icon": "ph-chat-circle",
                "user": comment.user.username,
                "action": f"commented on {comment.ticket}",
                "text": comment.body,
                "time_ago": time_ago(comment.created_at),
                "timestamp": comment.created_at,
            }
        )

    # Add recent ticket updates
    recent_updates = (
        TicketUpdateMessage.select().order_by(TicketUpdateMessage.created_at.desc()).limit(10)
    )
    for update in recent_updates:
        activities.append(
            {
                "type": "update",
                "icon": update.icon.replace("ph ", "") if update.icon else "ph-pencil",
                "user": "System",
                "action": f"{update.title} on {update.ticket}",
                "text": update.message,
                "time_ago": time_ago(update.created_at),
                "timestamp": update.created_at,
            }
        )

    # Add recent errors to activity
    for error in recent_errors:
        activities.append(
            {
                "type": "error",
                "icon": "ph-bug-beetle",
                "user": error.platform or "Unknown",
                "action": "triggered an error",
                "text": f"{error.exception_type or 'Error'}: {error.exception_value or 'Unknown error'}",
                "time_ago": time_ago(error.last_seen),
                "timestamp": error.last_seen,
            }
        )

    # Sort all activities by timestamp (most recent first)
    activities.sort(key=lambda x: x["timestamp"], reverse=True)

    return render_template(
        "news.jinja2",
        user=user,
        page="news",
        my_tickets=my_tickets,
        open_tickets=open_tickets,
        unresolved_errors=unresolved_errors,
        resolved_today=resolved_today,
        recent_errors=recent_errors,
        projects=projects,
        activities=activities[:15],  # Limit to 15 activities
    )


def build_timeline_events(
    project_id: str | None = None, days: int = 30, detailed: bool = False
) -> dict:  # noqa: C901
    """
    Build a comprehensive timeline of events across tickets, comments, errors, and updates.

    Returns a dictionary with:
    - events: List of timeline events
    - stats: Summary statistics
    - activity_by_day: Activity counts by day for heatmap
    - top_contributors: Most active users
    """
    from datetime import datetime
    from collections import defaultdict

    now = int(time.time())
    cutoff = now - (days * 86400) if days > 0 else 0

    events = []
    activity_by_day = defaultdict(int)
    user_activity = defaultdict(int)

    # Helper to format date parts
    def format_date_parts(timestamp: int) -> dict:
        dt = datetime.fromtimestamp(timestamp)
        return {
            "date_str": dt.strftime("%Y-%m-%d"),
            "date_day": dt.strftime("%d"),
            "date_month": dt.strftime("%b"),
            "date_full": dt.strftime("%A, %B %d, %Y"),
            "time_str": dt.strftime("%I:%M %p"),
            "date_key": dt.strftime("%Y-%m-%d"),
        }

    # Get tickets
    ticket_query = Ticket.select()
    if project_id:
        ticket_query = ticket_query.where(Ticket.project == project_id)
    if cutoff > 0:
        ticket_query = ticket_query.where(Ticket.created_at >= cutoff)

    for ticket in ticket_query:
        date_parts = format_date_parts(ticket.created_at)
        activity_by_day[date_parts["date_key"]] += 1

        # Get assignees for the ticket
        assignees = [
            utj.user for utj in UserTicketJoin.select().where(UserTicketJoin.ticket == ticket.id)
        ]
        for user in assignees:
            user_activity[user] += 1

        events.append(
            {
                "type": "ticket",
                "type_label": "Ticket Created",
                "icon": "ph-ticket",
                "title": f"{ticket.id}: {ticket.title}",
                "description": ticket.description[:300] if ticket.description else None,
                "timestamp": ticket.created_at,
                "link": f"/tickets/{ticket.project}/{ticket.id}",
                "meta": {
                    "project": ticket.project,
                    "ticket_id": ticket.id,
                    "status": ticket.status,
                    "priority": ticket.priority,
                },
                **date_parts,
            }
        )

    # Comments are useful for deep audits, but too noisy for default timeline reading.
    if detailed:
        comment_query = Comment.select()
        if cutoff > 0:
            comment_query = comment_query.where(Comment.created_at >= cutoff)

        for comment in comment_query:
            # Filter by project if specified
            if project_id:
                try:
                    ticket = Ticket.get(Ticket.id == comment.ticket)
                    if ticket.project != project_id:
                        continue
                except Exception:
                    continue

            date_parts = format_date_parts(comment.created_at)
            activity_by_day[date_parts["date_key"]] += 1
            user_activity[comment.user.username] += 1

            events.append(
                {
                    "type": "comment",
                    "type_label": "Comment",
                    "icon": "ph-chat-circle",
                    "title": f"Comment on {comment.ticket}",
                    "description": comment.body[:200] if comment.body else None,
                    "timestamp": comment.created_at,
                    "link": (
                        f"/tickets/{Ticket.get(Ticket.id == comment.ticket).project}/{comment.ticket}"
                        if Ticket.get_or_none(Ticket.id == comment.ticket)
                        else None
                    ),
                    "meta": {"user": comment.user.username, "ticket_id": comment.ticket},
                    **date_parts,
                }
            )

    # Get ticket updates
    update_query = TicketUpdateMessage.select()
    if cutoff > 0:
        update_query = update_query.where(TicketUpdateMessage.created_at >= cutoff)

    for update in update_query:
        # Filter by project if specified
        if project_id:
            try:
                ticket = Ticket.get(Ticket.id == update.ticket)
                if ticket.project != project_id:
                    continue
            except Exception:
                continue

        if not detailed and update.title in LOW_SIGNAL_UPDATE_TITLES:
            continue

        date_parts = format_date_parts(update.created_at)
        activity_by_day[date_parts["date_key"]] += 1

        # Extract icon class - stored as "ph ph-icon-name", we need just "ph-icon-name"
        icon = update.icon.replace("ph ", "") if update.icon else "ph-pencil"

        events.append(
            {
                "type": "update",
                "type_label": update.title,
                "icon": icon,
                "title": f"{update.title}",
                "description": update.message,
                "timestamp": update.created_at,
                "link": (
                    f"/tickets/{Ticket.get(Ticket.id == update.ticket).project}/{update.ticket}"
                    if Ticket.get_or_none(Ticket.id == update.ticket)
                    else None
                ),
                "meta": {"ticket_id": update.ticket},
                **date_parts,
            }
        )

    # Get errors
    error_query = ErrorGroup.select()
    if cutoff > 0:
        error_query = error_query.where(ErrorGroup.last_seen >= cutoff)

    for error in error_query:
        # Filter by project if specified
        if project_id:
            try:
                if error.part.project.id != project_id:
                    continue
            except Exception:
                continue

        date_parts = format_date_parts(error.last_seen)
        activity_by_day[date_parts["date_key"]] += 1

        events.append(
            {
                "type": "error",
                "type_label": "Error",
                "icon": "ph-bug-beetle",
                "title": f'{error.exception_type or "Error"}: {error.exception_value or "Unknown"}',
                "description": error.culprit,
                "timestamp": error.last_seen,
                "link": (
                    f"/errors/{error.part.project.id}/{error.part.id}/{error.id}"
                    if error.part
                    else None
                ),
                "meta": {
                    "project": error.part.project.id if error.part else None,
                    "event_count": error.event_count,
                    "status": error.status,
                },
                **date_parts,
            }
        )

    # Sort events by timestamp (most recent first)
    events.sort(key=lambda x: x["timestamp"], reverse=True)

    # Post-process: Group consecutive updates for the same ticket
    grouped_events = []
    current_group = None

    for event in events:
        if event["type"] == "update":
            ticket_id = event["meta"].get("ticket_id")

            if (
                current_group
                and current_group["type"] == "update_group"
                and current_group["meta"].get("ticket_id") == ticket_id
            ):
                # Add to existing group
                current_group["events"].append(event)
                # Keep the group timestamp as the most recent event's timestamp
            else:
                # Create new group
                current_group = {
                    "type": "update_group",
                    "type_label": "Updates",
                    "icon": "ph-stack",
                    "title": "Multiple Updates",  # Will be updated with count
                    "description": "",
                    "timestamp": event["timestamp"],
                    "link": event["link"],
                    "meta": {
                        "ticket_id": ticket_id,
                        "project": event.get("meta", {}).get(
                            "project"
                        ),  # inherit project if available
                    },
                    "events": [event],
                    # Copy date parts from the most recent event
                    "date_str": event["date_str"],
                    "date_day": event["date_day"],
                    "date_month": event["date_month"],
                    "date_full": event["date_full"],
                    "time_str": event["time_str"],
                    "date_key": event["date_key"],
                }
                grouped_events.append(current_group)
        else:
            current_group = None
            grouped_events.append(event)

    # Finalize groups (update titles, handle single-item groups)
    final_events = []
    for event in grouped_events:
        if event["type"] == "update_group":
            count = len(event["events"])
            if count == 1:
                # Flatten back to single event
                final_events.append(event["events"][0])
            else:
                event["title"] = f"{count} Updates"
                event["type_label"] = f"{count} Updates"
                final_events.append(event)
        else:
            final_events.append(event)

    events = final_events

    # Calculate statistics
    tickets_all = list(
        Ticket.select() if not project_id else Ticket.select().where(Ticket.project == project_id)
    )
    tickets_created = (
        len([t for t in tickets_all if t.created_at >= cutoff]) if cutoff > 0 else len(tickets_all)
    )
    tickets_closed = len([t for t in tickets_all if t.status == "closed"])
    tickets_in_progress = len([t for t in tickets_all if t.status == "in-progress"])

    total_comments = Comment.select().count()
    total_errors = ErrorGroup.select().count()
    errors_resolved = ErrorGroup.select().where(ErrorGroup.status == "resolved").count()

    # Get unique active users
    active_users = len(set(user_activity.keys()))

    # Calculate effort breakdown (simplified)
    total_tickets = len(tickets_all)
    bug_tickets = len(
        [
            ticket
            for ticket in tickets_all
            if any(
                label_model.label == "bug"
                for label_model in TicketLabelJoin.select().where(TicketLabelJoin.ticket == ticket.id)
            )
        ]
    )
    feature_tickets = len(
        [
            t
            for t in tickets_all
            if any(
                label_model.label == "feature"
                for label_model in TicketLabelJoin.select().where(TicketLabelJoin.ticket == t.id)
            )
        ]
    )
    other_tickets = total_tickets - bug_tickets - feature_tickets

    total = bug_tickets + feature_tickets + other_tickets
    effort_bugs = (bug_tickets / total * 100) if total > 0 else 0
    effort_features = (feature_tickets / total * 100) if total > 0 else 0
    effort_tickets = (other_tickets / total * 100) if total > 0 else 0

    # Top contributors
    top_contributors = []
    max_activity = max(user_activity.values()) if user_activity else 1
    for username, count in sorted(user_activity.items(), key=lambda x: x[1], reverse=True)[:5]:
        top_contributors.append(
            {
                "username": username,
                "activity_count": count,
                "percentage": (count / max_activity) * 100,
            }
        )

    # Calculate date range
    if events:
        oldest = min(e["timestamp"] for e in events)
        newest = max(e["timestamp"] for e in events)
        days_span = (newest - oldest) // 86400
        if days_span == 0:
            date_range = "Today"
        elif days_span == 1:
            date_range = "2 days"
        elif days_span < 7:
            date_range = f"{days_span} days"
        elif days_span < 30:
            date_range = f"{days_span // 7} weeks"
        else:
            date_range = f"{days_span // 30} months"
    else:
        date_range = "No data"

    return {
        "events": events,
        "total_events": len(events),
        "date_range": date_range,
        "tickets_created": tickets_created,
        "tickets_closed": tickets_closed,
        "tickets_in_progress": tickets_in_progress,
        "total_comments": total_comments,
        "total_errors": total_errors,
        "errors_resolved": errors_resolved,
        "active_users": active_users,
        "effort_tickets": round(effort_tickets, 1),
        "effort_bugs": round(effort_bugs, 1),
        "effort_features": round(effort_features, 1),
        "top_contributors": top_contributors,
        "activity_by_day": dict(activity_by_day),
    }


def _parse_timeline_days(raw_days: str | None) -> int:
    if not raw_days:
        return 30
    if raw_days == "all":
        return 0
    try:
        days = int(raw_days)
    except (TypeError, ValueError):
        return 30
    return max(1, min(days, 3650))


def _parse_timeline_detail(raw_detail: str | None) -> bool:
    if not raw_detail:
        return False
    return raw_detail.strip().lower() in {"1", "true", "all", "detailed", "full"}


def _timeline_query_suffix(days: int, detailed: bool) -> str:
    params = {}
    if days == 0:
        params["days"] = "all"
    elif days != 30:
        params["days"] = str(days)
    if detailed:
        params["detail"] = "all"
    return f"?{urlencode(params)}" if params else ""


def _timeline_mode_url(base_path: str, days: int, detailed: bool) -> str:
    return f"{base_path}{_timeline_query_suffix(days, detailed)}"


def build_reports_summary(days: int = 30) -> dict:
    """Build rollup stats and per-project rows for the reports dashboard."""
    now = int(time.time())
    cutoff = now - (days * 86400)

    closed_statuses = {"closed", "done"}

    tickets_created = (
        Ticket.select()
        .where((Ticket.active == 1) & (Ticket.created_at >= cutoff))
        .count()
    )
    tickets_closed = (
        Ticket.select()
        .where((Ticket.active == 1) & (Ticket.status.in_(closed_statuses)) & (Ticket.created_at >= cutoff))
        .count()
    )

    triage_tickets = list(
        Ticket.select()
        .where((Ticket.active == 1) & (Ticket.status == "triage"))
        .order_by(Ticket.created_at.asc())
    )
    triage_backlog = len(triage_tickets)
    avg_triage_age_days = 0.0
    if triage_tickets:
        total_age_seconds = sum(max(0, now - ticket.created_at) for ticket in triage_tickets)
        avg_triage_age_days = round(total_age_seconds / triage_backlog / 86400, 1)

    unresolved_errors = ErrorGroup.select().where(ErrorGroup.status == "unresolved").count()
    resolved_errors = ErrorGroup.select().where(ErrorGroup.status == "resolved").count()

    project_rows = []
    for project in Project.select().order_by(Project.name):
        active_tickets = (
            Ticket.select()
            .where(
                (Ticket.project == project.id)
                & (Ticket.active == 1)
                & (~(Ticket.status.in_(closed_statuses)))
                & (Ticket.status != "triage")
            )
            .count()
        )
        closed_tickets = (
            Ticket.select()
            .where(
                (Ticket.project == project.id)
                & (Ticket.active == 1)
                & (Ticket.status.in_(closed_statuses))
            )
            .count()
        )
        triage_count = (
            Ticket.select()
            .where(
                (Ticket.project == project.id)
                & (Ticket.active == 1)
                & (Ticket.status == "triage")
            )
            .count()
        )

        part_ids = [part.id for part in ProjectPart.select(ProjectPart.id).where(ProjectPart.project == project.id)]
        unresolved_project_errors = 0
        resolved_project_errors = 0
        if part_ids:
            unresolved_project_errors = (
                ErrorGroup.select()
                .where((ErrorGroup.part.in_(part_ids)) & (ErrorGroup.status == "unresolved"))
                .count()
            )
            resolved_project_errors = (
                ErrorGroup.select()
                .where((ErrorGroup.part.in_(part_ids)) & (ErrorGroup.status == "resolved"))
                .count()
            )

        project_rows.append(
            {
                "project_id": project.id,
                "project_name": project.name,
                "active_tickets": active_tickets,
                "closed_tickets": closed_tickets,
                "triage_tickets": triage_count,
                "unresolved_errors": unresolved_project_errors,
                "resolved_errors": resolved_project_errors,
            }
        )

    return {
        "window_days": days,
        "tickets_created": tickets_created,
        "tickets_closed": tickets_closed,
        "triage_backlog": triage_backlog,
        "avg_triage_age_days": avg_triage_age_days,
        "unresolved_errors": unresolved_errors,
        "resolved_errors": resolved_errors,
        "project_rows": project_rows,
    }


@news_bp.route("/timeline")
@protected
def timeline_view(user: User):
    days = _parse_timeline_days(request.args.get("days"))
    detail_mode = _parse_timeline_detail(request.args.get("detail"))
    data = build_timeline_events(project_id=None, days=days, detailed=detail_mode)

    return render_template(
        "timeline.jinja2",
        user=user,
        page="timeline",
        projects=list(Project.select().order_by(Project.name)),
        project=None,
        events=data["events"][:50],  # Limit initial load
        events_json=json.dumps(data["events"][:100]),
        activity_by_day=json.dumps(data["activity_by_day"]),
        query_suffix=_timeline_query_suffix(days, detail_mode),
        compact_url=_timeline_mode_url("/timeline", days, False),
        detailed_url=_timeline_mode_url("/timeline", days, True),
        detail_mode=detail_mode,
        selected_days="all" if days == 0 else str(days),
        has_more_events=len(data["events"]) > 50,
        total_events=data["total_events"],
        date_range=data["date_range"],
        tickets_created=data["tickets_created"],
        tickets_closed=data["tickets_closed"],
        tickets_in_progress=data["tickets_in_progress"],
        total_comments=data["total_comments"],
        total_errors=data["total_errors"],
        errors_resolved=data["errors_resolved"],
        active_users=data["active_users"],
        effort_tickets=data["effort_tickets"],
        effort_bugs=data["effort_bugs"],
        effort_features=data["effort_features"],
        top_contributors=data["top_contributors"],
    )


@news_bp.route("/timeline/<project_id>")
@protected
def timeline_project_view(user: User, project_id: str):
    project = Project.get_or_none(Project.id == project_id)
    if not project:
        return redirect("/timeline")

    days = _parse_timeline_days(request.args.get("days"))
    detail_mode = _parse_timeline_detail(request.args.get("detail"))
    data = build_timeline_events(project_id=project_id, days=days, detailed=detail_mode)

    return render_template(
        "timeline.jinja2",
        user=user,
        page="timeline",
        projects=list(Project.select().order_by(Project.name)),
        project=project,
        events=data["events"][:50],
        events_json=json.dumps(data["events"][:100]),
        activity_by_day=json.dumps(data["activity_by_day"]),
        query_suffix=_timeline_query_suffix(days, detail_mode),
        compact_url=_timeline_mode_url(f"/timeline/{project.id}", days, False),
        detailed_url=_timeline_mode_url(f"/timeline/{project.id}", days, True),
        detail_mode=detail_mode,
        selected_days="all" if days == 0 else str(days),
        has_more_events=len(data["events"]) > 50,
        total_events=data["total_events"],
        date_range=data["date_range"],
        tickets_created=data["tickets_created"],
        tickets_closed=data["tickets_closed"],
        tickets_in_progress=data["tickets_in_progress"],
        total_comments=data["total_comments"],
        total_errors=data["total_errors"],
        errors_resolved=data["errors_resolved"],
        active_users=data["active_users"],
        effort_tickets=data["effort_tickets"],
        effort_bugs=data["effort_bugs"],
        effort_features=data["effort_features"],
        top_contributors=data["top_contributors"],
    )


@news_bp.route("/reports")
@protected
def reports_view(user: User):
    summary = build_reports_summary(days=30)
    return render_template(
        "reports.jinja2",
        user=user,
        page="reports",
        summary=summary,
    )


@news_bp.route("/reports/export.csv")
@protected
def reports_export_csv(user: User):
    summary = build_reports_summary(days=30)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "project_id",
            "project_name",
            "active_tickets",
            "closed_tickets",
            "triage_tickets",
            "unresolved_errors",
            "resolved_errors",
        ]
    )

    for row in summary["project_rows"]:
        writer.writerow(
            [
                row["project_id"],
                row["project_name"],
                row["active_tickets"],
                row["closed_tickets"],
                row["triage_tickets"],
                row["unresolved_errors"],
                row["resolved_errors"],
            ]
        )

    csv_content = output.getvalue()
    output.close()

    return Response(
        csv_content,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=reports.csv"},
    )
