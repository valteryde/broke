from ..utils.security import protected
from peewee import prefetch
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
    Label,
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


def build_timeline_events(  # noqa: C901
    project_id: str | None = None, 
    days: int = 30, 
    detailed: bool = False,
    offset: int = 0,
    limit: int = 50
) -> dict:
    """
    Build a comprehensive timeline of events across tickets, comments, errors, and updates.
    Uses manual batching to avoid N+1 query problems.
    """
    from datetime import datetime
    from collections import defaultdict

    now = int(time.time())
    cutoff = now - (days * 86400) if days > 0 else 0

    events = []
    # Note: Stats are still calculated over the full range, but events are paginated
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

    # 1. Fetch Tickets
    ticket_query = Ticket.select()
    if project_id:
        ticket_query = ticket_query.where(Ticket.project == project_id)
    if cutoff > 0:
        ticket_query = ticket_query.where(Ticket.created_at >= cutoff)
    
    # We fetch them to a list for manual batching
    tickets = list(ticket_query)
    ticket_dict = {t.id: t for t in tickets if getattr(t, 'id', None)}
    ticket_ids = list(ticket_dict.keys())

    # Bulk Assignees
    if ticket_ids:
        utjs = UserTicketJoin.select().where(UserTicketJoin.ticket.in_(ticket_ids))
        user_ids = [utj.user for utj in utjs]
        if user_ids:
            users = {u.username: u for u in User.select().where(User.username.in_(user_ids))}
            for utj in utjs:
                if utj.ticket in ticket_dict and utj.user in users:
                    user_activity[utj.user] += 1
    
    # Bulk Labels (for stats)
    for t in tickets:
        if not hasattr(t, "labels"):
            t.labels = []
            
    if ticket_ids:
        tljs = TicketLabelJoin.select().where(TicketLabelJoin.ticket.in_(ticket_ids))
        label_ids = [tlj.label for tlj in tljs]
        if label_ids:
            labels = {l.name: l for l in Label.select().where(Label.name.in_(label_ids))}
            for tlj in tljs:
                if tlj.ticket in ticket_dict and tlj.label in labels:
                    ticket_dict[tlj.ticket].labels.append(labels[tlj.label])

    for ticket in tickets:
        date_parts = format_date_parts(ticket.created_at)
        activity_by_day[date_parts["date_key"]] += 1

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

    # 2. Fetch Comments (if detailed)
    if detailed:
        comment_query = Comment.select()
        if cutoff > 0:
            comment_query = comment_query.where(Comment.created_at >= cutoff)
        
        comments = list(comment_query)
        # Fetch tickets and users for comments in bulk
        c_ticket_ids = [c.ticket for c in comments if c.ticket]
        if c_ticket_ids:
            c_tickets = {t.id: t for t in Ticket.select(Ticket.id, Ticket.project).where(Ticket.id.in_(c_ticket_ids))}
        else:
            c_tickets = {}
            
        c_user_ids = [c.user_id for c in comments if c.user_id]
        if c_user_ids:
            c_users = {u.username: u for u in User.select(User.username).where(User.username.in_(c_user_ids))}
        else:
            c_users = {}

        for comment in comments:
            c_ticket = c_tickets.get(comment.ticket)
            if not c_ticket:
                continue
                
            # Filter by project if specified
            if project_id and c_ticket.project != project_id:
                continue

            date_parts = format_date_parts(comment.created_at)
            activity_by_day[date_parts["date_key"]] += 1
            
            username = c_users[comment.user_id].username if comment.user_id in c_users else str(comment.user_id)
            user_activity[username] += 1

            events.append(
                {
                    "type": "comment",
                    "type_label": "Comment",
                    "icon": "ph-chat-circle",
                    "title": f"Comment on {comment.ticket}",
                    "description": comment.body[:200] if comment.body else None,
                    "timestamp": comment.created_at,
                    "link": f"/tickets/{c_ticket.project}/{comment.ticket}",
                    "meta": {"user": username, "ticket_id": comment.ticket},
                    **date_parts,
                }
            )

    # 3. Fetch Updates
    update_query = TicketUpdateMessage.select()
    if cutoff > 0:
        update_query = update_query.where(TicketUpdateMessage.created_at >= cutoff)
    
    updates = list(update_query)
    u_ticket_ids = [u.ticket for u in updates if u.ticket]
    if u_ticket_ids:
        u_tickets = {t.id: t for t in Ticket.select(Ticket.id, Ticket.project).where(Ticket.id.in_(u_ticket_ids))}
    else:
        u_tickets = {}

    for update in updates:
        u_ticket = u_tickets.get(update.ticket)
        if not u_ticket:
            continue
            
        if project_id and u_ticket.project != project_id:
            continue

        if not detailed and update.title in LOW_SIGNAL_UPDATE_TITLES:
            continue

        date_parts = format_date_parts(update.created_at)
        activity_by_day[date_parts["date_key"]] += 1

        icon = update.icon.replace("ph ", "") if update.icon else "ph-pencil"

        events.append(
            {
                "type": "update",
                "type_label": update.title,
                "icon": icon,
                "title": f"{update.title}",
                "description": update.message,
                "timestamp": update.created_at,
                "link": f"/tickets/{u_ticket.project}/{update.ticket}",
                "meta": {"ticket_id": update.ticket},
                **date_parts,
            }
        )

    # 4. Fetch Errors
    error_query = ErrorGroup.select()
    if cutoff > 0:
        error_query = error_query.where(ErrorGroup.last_seen >= cutoff)
    
    errors_prefetched = prefetch(error_query, ProjectPart.select(), Project.select())

    for error in errors_prefetched:
        if project_id:
            if not error.part or error.part.project_id != project_id:
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
                "link": f"/errors/{error.part.project_id}/{error.part_id}/{error.id}" if error.part else None,
                "meta": {
                    "project": error.part.project_id if error.part else None,
                    "event_count": error.event_count,
                    "status": error.status,
                },
                **date_parts,
            }
        )

    # Sort all events by timestamp (most recent first)
    events.sort(key=lambda x: x["timestamp"], reverse=True)

    # Group consecutive updates for the same ticket
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
                current_group["events"].append(event)
            else:
                current_group = {
                    "type": "update_group",
                    "type_label": "Updates",
                    "icon": "ph-stack",
                    "title": "Multiple Updates",
                    "description": "",
                    "timestamp": event["timestamp"],
                    "link": event["link"],
                    "meta": {
                        "ticket_id": ticket_id,
                        "project": event.get("meta", {}).get("project"),
                    },
                    "events": [event],
                    **{k: event[k] for k in ["date_str", "date_day", "date_month", "date_full", "time_str", "date_key"]}
                }
                grouped_events.append(current_group)
        else:
            current_group = None
            grouped_events.append(event)

    # Finalize groups
    final_events = []
    for event in grouped_events:
        if event["type"] == "update_group":
            count = len(event["events"])
            if count == 1:
                final_events.append(event["events"][0])
            else:
                event["title"] = f"{count} Updates"
                event["type_label"] = f"{count} Updates"
                final_events.append(event)
        else:
            final_events.append(event)

    # Total events before pagination
    total_events_count = len(final_events)
    
    # Paginate
    paginated_events = final_events[offset : offset + limit]

    # Calculate statistics (cached or batch)
    stats = {}
    if offset == 0:
        # Only calc full stats on first page
        tickets_all = tickets
        tickets_created = len([t for t in tickets_all if t.created_at >= cutoff]) if cutoff > 0 else len(tickets_all)
        tickets_closed = len([t for t in tickets_all if t.status == "closed"])
        tickets_in_progress = len([t for t in tickets_all if t.status == "in-progress"])

        total_comments = Comment.select().count()
        total_errors = ErrorGroup.select().count()
        errors_resolved = ErrorGroup.select().where(ErrorGroup.status == "resolved").count()

        active_users = len(set(user_activity.keys()))

        # Effort breakdown
        total = tickets_created # Use created in window
        bug_tickets = 0
        feature_tickets = 0
        for t in tickets_all:
            if t.created_at < cutoff and cutoff > 0: continue
            labels = [l.name for l in t.labels]
            if "bug" in labels: bug_tickets += 1
            elif "feature" in labels: feature_tickets += 1
        
        other_tickets = total - bug_tickets - feature_tickets
        effort_bugs = (bug_tickets / total * 100) if total > 0 else 0
        effort_features = (feature_tickets / total * 100) if total > 0 else 0
        effort_tickets = (other_tickets / total * 100) if total > 0 else 0

        # Top contributors
        top_contributors = []
        max_activity = max(user_activity.values()) if user_activity else 1
        for username, count in sorted(user_activity.items(), key=lambda x: x[1], reverse=True)[:5]:
            top_contributors.append({
                "username": username,
                "activity_count": count,
                "percentage": (count / max_activity) * 100,
            })

        # Calculate date range
        date_range = "No data"
        if final_events:
            oldest = min(e["timestamp"] for e in final_events)
            newest = max(e["timestamp"] for e in final_events)
            days_span = (newest - oldest) // 86400
            if days_span == 0: date_range = "Today"
            elif days_span == 1: date_range = "2 days"
            elif days_span < 7: date_range = f"{days_span} days"
            elif days_span < 30: date_range = f"{days_span // 7} weeks"
            else: date_range = f"{days_span // 30} months"

        stats = {
            "total_events": total_events_count,
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

    return {
        "events": paginated_events,
        "has_more": (offset + limit) < total_events_count,
        "total": total_events_count,
        **stats
    }


@news_bp.route("/api/timeline/events")
@protected
def api_timeline_events(user: User):
    project_id = request.args.get("project")
    days = _parse_timeline_days(request.args.get("days"))
    detail_mode = _parse_timeline_detail(request.args.get("detail"))
    offset = int(request.args.get("offset", 0))
    limit = int(request.args.get("limit", 50))
    
    data = build_timeline_events(
        project_id=project_id, 
        days=days, 
        detailed=detail_mode, 
        offset=offset, 
        limit=limit
    )
    return Response(json.dumps(data), mimetype="application/json")


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
    """
    Build rollup stats and per-project rows for the reports dashboard.
    Optimized to use bulk queries instead of per-project loops.
    """
    now = int(time.time())
    cutoff = now - (days * 86400)
    closed_statuses = {"closed", "done"}
    intake_statuses = {"intake", "triage"}

    # 1. Global counts
    tickets_created = Ticket.select().where((Ticket.active == 1) & (Ticket.created_at >= cutoff)).count()
    tickets_closed = Ticket.select().where((Ticket.active == 1) & (Ticket.status.in_(closed_statuses)) & (Ticket.created_at >= cutoff)).count()
    
    unresolved_errors = ErrorGroup.select().where(ErrorGroup.status == "unresolved").count()
    resolved_errors = ErrorGroup.select().where(ErrorGroup.status == "resolved").count()

    # 2. Triage / Intake Backlog
    triage_tickets = list(Ticket.select().where((Ticket.active == 1) & (Ticket.status.in_(intake_statuses))))
    triage_backlog = len(triage_tickets)
    avg_triage_age_days = 0.0
    if triage_tickets:
        total_age_seconds = sum(max(0, now - ticket.created_at) for ticket in triage_tickets)
        avg_triage_age_days = round(total_age_seconds / triage_backlog / 86400, 1)

    # 3. Project-specific stats (Batch)
    # We'll get counts for all projects in one go for each category
    from peewee import fn

    def get_project_counts(filter_expr):
        query = (Ticket.select(Ticket.project, fn.COUNT(Ticket.id).alias('count'))
                .where((Ticket.active == 1) & filter_expr)
                .group_by(Ticket.project))
        return {str(r.project): r.count for r in query}

    active_counts = get_project_counts((~Ticket.status.in_(closed_statuses)) & (~Ticket.status.in_(intake_statuses)))
    closed_counts = get_project_counts(Ticket.status.in_(closed_statuses))
    triage_counts = get_project_counts(Ticket.status.in_(intake_statuses))

    # Error counts per project
    error_query = (ErrorGroup.select(Project.id.alias('project_id'), ErrorGroup.status, fn.COUNT(ErrorGroup.id).alias('count'))
                  .join(ProjectPart).join(Project)
                  .group_by(Project.id, ErrorGroup.status)).dicts()
    
    unresolved_error_counts = {}
    resolved_error_counts = {}
    for r in error_query:
        if r['status'] == 'unresolved':
            unresolved_error_counts[str(r['project_id'])] = r['count']
        else:
            resolved_error_counts[str(r['project_id'])] = r['count']

    project_rows = []
    for project in Project.select().order_by(Project.name):
        pid = str(project.id)
        project_rows.append({
            "project_id": project.id,
            "project_name": project.name,
            "active_tickets": active_counts.get(pid, 0),
            "closed_tickets": closed_counts.get(pid, 0),
            "triage_tickets": triage_counts.get(pid, 0),
            "unresolved_errors": unresolved_error_counts.get(pid, 0),
            "resolved_errors": resolved_error_counts.get(pid, 0),
        })

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
    summary = build_reports_summary(days=30)

    return render_template(
        "timeline.jinja2",
        user=user,
        page="reports",
        summary=summary,
        projects=list(Project.select().order_by(Project.name)),
        project=None,
        events=data["events"],  # Already limited by build_timeline_events
        events_json=json.dumps(data["events"]),
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
    summary = build_reports_summary(days=30)

    return render_template(
        "timeline.jinja2",
        user=user,
        page="reports",
        summary=summary,
        projects=list(Project.select().order_by(Project.name)),
        project=project,
        events=data["events"],
        events_json=json.dumps(data["events"]),
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
    return redirect("/timeline")


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
