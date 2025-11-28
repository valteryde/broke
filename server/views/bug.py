
from urllib.parse import urlparse
from utils.security import secureroute
from utils.models import *
from flask import redirect, render_template, request
from utils.app import app
from peewee import DoesNotExist
import gzip
import json
import hashlib
import time


def generate_fingerprint(exception_type: str | None, exception_value: str | None, stacktrace: str | None) -> str:
    """Generate a fingerprint for grouping similar errors together."""
    # Combine exception type, message, and stacktrace for fingerprinting
    fingerprint_data = f"{exception_type or ''}:{exception_value or ''}:{stacktrace or ''}"
    return hashlib.sha256(fingerprint_data.encode('utf-8')).hexdigest()[:32]


def extract_exception_info(payload: dict) -> tuple[str | None, str | None, str | None]:
    """Extract exception type, value, and stacktrace from a Sentry event payload."""
    exception_type = None
    exception_value = None
    stacktrace_json = None
    
    # Try to get from exception.values (standard Sentry format)
    if 'exception' in payload and 'values' in payload['exception']:
        values = payload['exception']['values']
        if values:
            first_exception = values[0]
            exception_type = first_exception.get('type')
            exception_value = first_exception.get('value')
            if 'stacktrace' in first_exception:
                stacktrace_json = json.dumps(first_exception['stacktrace'])
    
    # Fallback to message field
    if not exception_value:
        exception_value = payload.get('message', payload.get('logentry', {}).get('message'))
    
    return exception_type, exception_value, stacktrace_json


def extract_culprit(payload: dict) -> str | None:
    """Extract the culprit (file/function where error occurred)."""
    # First check if culprit is directly provided
    if 'culprit' in payload:
        return payload['culprit']
    
    # Try to extract from stacktrace
    if 'exception' in payload and 'values' in payload['exception']:
        values = payload['exception']['values']
        if values and 'stacktrace' in values[0]:
            frames = values[0]['stacktrace'].get('frames', [])
            if frames:
                last_frame = frames[-1]
                filename = last_frame.get('filename', last_frame.get('abs_path', ''))
                function = last_frame.get('function', '')
                lineno = last_frame.get('lineno', '')
                return f"{filename}:{function}:{lineno}"
    
    return None


def handle_event_item(part: ProjectPart, payload: dict, event_id: str | None = None) -> ErrorGroup:
    """Handle an event item from a Sentry envelope."""
    exception_type, exception_value, stacktrace_json = extract_exception_info(payload)
    culprit = extract_culprit(payload)
    
    # Generate fingerprint for grouping
    fingerprint = generate_fingerprint(exception_type, exception_value, stacktrace_json)
    
    # Extract additional context
    platform = payload.get('platform')
    environment = payload.get('environment')
    release = payload.get('release')
    contexts = json.dumps(payload.get('contexts', {})) if payload.get('contexts') else None
    tags = json.dumps(payload.get('tags', {})) if payload.get('tags') else None
    extra = json.dumps(payload.get('extra', {})) if payload.get('extra') else None
    
    timestamp = int(time.time())
    
    # Try to find existing error group or create new one
    try:
        error_group = ErrorGroup.get(
            (ErrorGroup.part == part) & 
            (ErrorGroup.fingerprint == fingerprint)
        )
        # Update existing group
        error_group.event_count += 1
        error_group.last_seen = timestamp
        error_group.save()
    except DoesNotExist:
        # Create new group
        error_group = ErrorGroup.create(
            part=part,
            fingerprint=fingerprint,
            exception_type=exception_type,
            exception_value=exception_value,
            culprit=culprit,
            platform=platform,
            environment=environment,
            release=release,
            stacktrace=stacktrace_json,
            contexts=contexts,
            tags=tags,
            extra=extra,
            event_count=1,
            first_seen=timestamp,
            last_seen=timestamp,
            status='unresolved'
        )
    
    # Record this occurrence
    ErrorOccurrence.create(
        error_group=error_group,
        timestamp=timestamp,
        event_id=event_id or payload.get('event_id')
    )
    
    return error_group


def handle_session_item(part: ProjectPart, payload: dict):
    """Handle a session item from a Sentry envelope."""
    session_id = payload.get('sid')
    if not session_id:
        return None
    
    status = payload.get('status', 'ok')
    started = payload.get('started')
    if isinstance(started, str):
        # Parse ISO timestamp to unix timestamp
        try:
            from datetime import datetime
            started = int(datetime.fromisoformat(started.replace('Z', '+00:00')).timestamp())
        except:
            started = int(time.time())
    
    duration = payload.get('duration')
    errors = payload.get('errors', 0)
    release = payload.get('attrs', {}).get('release')
    environment = payload.get('attrs', {}).get('environment')
    
    # Update or create session
    try:
        session = Session.get(
            (Session.part == part) & 
            (Session.session_id == session_id)
        )
        # Update existing session
        session.status = status
        if duration is not None:
            session.duration = duration
        session.errors = errors
        session.save()
    except DoesNotExist:
        session = Session.create(
            part=part,
            session_id=session_id,
            status=status,
            started=started or int(time.time()),
            duration=duration,
            errors=errors,
            release=release,
            environment=environment
        )
    
    return session


def handle_transaction_item(part: ProjectPart, payload: dict):
    """Handle a transaction (performance) item from a Sentry envelope."""
    transaction_id = payload.get('event_id') or payload.get('transaction_id')
    if not transaction_id:
        return None
    
    name = payload.get('transaction', 'Unknown')
    op = payload.get('contexts', {}).get('trace', {}).get('op')
    
    # Calculate duration from start/end timestamps
    start_timestamp = payload.get('start_timestamp')
    end_timestamp = payload.get('timestamp')
    duration = None
    if start_timestamp and end_timestamp:
        duration = int((end_timestamp - start_timestamp) * 1000)  # Convert to ms
    
    status = payload.get('contexts', {}).get('trace', {}).get('status')
    
    transaction = Transaction.create(
        part=part,
        transaction_id=transaction_id,
        name=name,
        op=op,
        duration=duration,
        status=status,
        timestamp=int(time.time()),
        data=json.dumps(payload.get('spans', []))[:10000] if payload.get('spans') else None
    )
    
    return transaction


def handle_attachment_item(part: ProjectPart, error_group: ErrorGroup, item_headers: dict, payload: str):
    """Handle an attachment item from a Sentry envelope."""
    filename = item_headers.get('filename', 'unknown')
    content_type = item_headers.get('content_type') or item_headers.get('type')
    
    # Store attachment data (base64 encode if binary)
    import base64
    try:
        # Try to store as-is if it's text
        if isinstance(payload, str):
            data = payload
        else:
            data = base64.b64encode(payload).decode('utf-8')
    except:
        data = str(payload)
    
    attachment = Attachment.create(
        error_group=error_group,
        filename=filename,
        content_type=content_type,
        data=data[:100000]  # Limit size
    )
    
    return attachment


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


@secureroute('/news')
def news_view(user: User):
    # Get current time for calculations
    now = int(time.time())
    today_start = now - (now % 86400)  # Start of today
    
    # Get tickets assigned to the user
    user_ticket_ids = [utj.ticket for utj in UserTicketJoin.select().where(UserTicketJoin.user == user.username)]
    my_tickets = list(Ticket.select().where(Ticket.id.in_(user_ticket_ids)).order_by(Ticket.created_at.desc()))
    
    # Count open tickets (tickets that are not closed)
    open_tickets = Ticket.select().where(
        (Ticket.id.in_(user_ticket_ids)) & 
        (Ticket.status != 'closed')
    ).count()
    
    # Get unresolved errors
    unresolved_errors = ErrorGroup.select().where(ErrorGroup.status == 'unresolved').count()
    
    # Get errors resolved today
    resolved_today = ErrorGroup.select().where(
        (ErrorGroup.status == 'resolved') & 
        (ErrorGroup.last_seen >= today_start)
    ).count()
    
    # Get recent errors (last 5)
    recent_errors = list(ErrorGroup.select().order_by(ErrorGroup.last_seen.desc()).limit(5))
    
    # Get all projects
    projects = list(Project.select().order_by(Project.name))
    
    # Build activity feed from comments and ticket updates
    activities = []
    
    # Add recent comments
    recent_comments = Comment.select().order_by(Comment.created_at.desc()).limit(15)
    for comment in recent_comments:
        activities.append({
            'type': 'comment',
            'icon': 'ph-chat-circle',
            'user': comment.user.username,
            'action': f'commented on {comment.ticket}',
            'text': comment.body,
            'time_ago': time_ago(comment.created_at),
            'timestamp': comment.created_at
        })
    
    # Add recent ticket updates
    recent_updates = TicketUpdateMessage.select().order_by(TicketUpdateMessage.created_at.desc()).limit(10)
    for update in recent_updates:
        activities.append({
            'type': 'update',
            'icon': update.icon.replace('ph ', 'ph-') if update.icon else 'ph-pencil',
            'user': 'System',
            'action': f'{update.title} on {update.ticket}',
            'text': update.message,
            'time_ago': time_ago(update.created_at),
            'timestamp': update.created_at
        })
    
    # Add recent errors to activity
    for error in recent_errors:
        activities.append({
            'type': 'error',
            'icon': 'ph-bug-beetle',
            'user': error.platform or 'Unknown',
            'action': 'triggered an error',
            'text': f"{error.exception_type or 'Error'}: {error.exception_value or 'Unknown error'}",
            'time_ago': time_ago(error.last_seen),
            'timestamp': error.last_seen
        })
    
    # Sort all activities by timestamp (most recent first)
    activities.sort(key=lambda x: x['timestamp'], reverse=True)
    
    return render_template('news.jinja2', 
        user=user,
        page='news',
        my_tickets=my_tickets,
        open_tickets=open_tickets,
        unresolved_errors=unresolved_errors,
        resolved_today=resolved_today,
        recent_errors=recent_errors,
        projects=projects,
        activities=activities[:15]  # Limit to 15 activities
    )


def build_timeline_events(project_id: str | None = None, days: int = 30) -> dict:
    """
    Build a comprehensive timeline of events across tickets, comments, errors, and updates.
    
    Returns a dictionary with:
    - events: List of timeline events
    - stats: Summary statistics
    - activity_by_day: Activity counts by day for heatmap
    - top_contributors: Most active users
    """
    from datetime import datetime, timedelta
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
            'date_str': dt.strftime('%Y-%m-%d'),
            'date_day': dt.strftime('%d'),
            'date_month': dt.strftime('%b'),
            'date_full': dt.strftime('%A, %B %d, %Y'),
            'time_str': dt.strftime('%I:%M %p'),
            'date_key': dt.strftime('%Y-%m-%d')
        }
    
    # Get tickets
    ticket_query = Ticket.select()
    if project_id:
        ticket_query = ticket_query.where(Ticket.project == project_id)
    if cutoff > 0:
        ticket_query = ticket_query.where(Ticket.created_at >= cutoff)
    
    for ticket in ticket_query:
        date_parts = format_date_parts(ticket.created_at)
        activity_by_day[date_parts['date_key']] += 1
        
        # Get assignees for the ticket
        assignees = [utj.user for utj in UserTicketJoin.select().where(UserTicketJoin.ticket == ticket.id)]
        for user in assignees:
            user_activity[user] += 1
        
        events.append({
            'type': 'ticket',
            'type_label': 'Ticket Created',
            'icon': 'ph-ticket',
            'title': f'{ticket.id}: {ticket.title}',
            'description': ticket.description[:300] if ticket.description else None,
            'timestamp': ticket.created_at,
            'link': f'/tickets/{ticket.project}/{ticket.id}',
            'meta': {
                'project': ticket.project,
                'ticket_id': ticket.id,
                'status': ticket.status,
                'priority': ticket.priority
            },
            **date_parts
        })
    
    # Get comments
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
            except:
                continue
        
        date_parts = format_date_parts(comment.created_at)
        activity_by_day[date_parts['date_key']] += 1
        user_activity[comment.user.username] += 1
        
        events.append({
            'type': 'comment',
            'type_label': 'Comment',
            'icon': 'ph-chat-circle',
            'title': f'Comment on {comment.ticket}',
            'description': comment.body[:200] if comment.body else None,
            'timestamp': comment.created_at,
            'link': f'/tickets/{Ticket.get(Ticket.id == comment.ticket).project}/{comment.ticket}' if Ticket.get_or_none(Ticket.id == comment.ticket) else None,
            'meta': {
                'user': comment.user.username,
                'ticket_id': comment.ticket
            },
            **date_parts
        })
    
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
            except:
                continue
        
        date_parts = format_date_parts(update.created_at)
        activity_by_day[date_parts['date_key']] += 1
        
        events.append({
            'type': 'update',
            'type_label': update.title,
            'icon': update.icon.replace('ph ', 'ph-') if update.icon else 'ph-pencil',
            'title': f'{update.title}',
            'description': update.message,
            'timestamp': update.created_at,
            'link': f'/tickets/{Ticket.get(Ticket.id == update.ticket).project}/{update.ticket}' if Ticket.get_or_none(Ticket.id == update.ticket) else None,
            'meta': {
                'ticket_id': update.ticket
            },
            **date_parts
        })
    
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
            except:
                continue
        
        date_parts = format_date_parts(error.last_seen)
        activity_by_day[date_parts['date_key']] += 1
        
        events.append({
            'type': 'error',
            'type_label': 'Error',
            'icon': 'ph-bug-beetle',
            'title': f'{error.exception_type or "Error"}: {error.exception_value or "Unknown"}',
            'description': error.culprit,
            'timestamp': error.last_seen,
            'link': f'/errors/{error.part.project.id}/{error.part.id}/{error.id}' if error.part else None,
            'meta': {
                'project': error.part.project.id if error.part else None,
                'event_count': error.event_count,
                'status': error.status
            },
            **date_parts
        })
    
    # Sort events by timestamp (most recent first)
    events.sort(key=lambda x: x['timestamp'], reverse=True)
    
    # Calculate statistics
    tickets_all = list(Ticket.select() if not project_id else Ticket.select().where(Ticket.project == project_id))
    tickets_created = len([t for t in tickets_all if t.created_at >= cutoff]) if cutoff > 0 else len(tickets_all)
    tickets_closed = len([t for t in tickets_all if t.status == 'closed'])
    tickets_in_progress = len([t for t in tickets_all if t.status == 'in-progress'])
    
    total_comments = Comment.select().count()
    total_errors = ErrorGroup.select().count()
    errors_resolved = ErrorGroup.select().where(ErrorGroup.status == 'resolved').count()
    
    # Get unique active users
    active_users = len(set(user_activity.keys()))
    
    # Calculate effort breakdown (simplified)
    total_tickets = len(tickets_all)
    bug_tickets = len([t for t in tickets_all if any(l.label == 'bug' for l in TicketLabelJoin.select().where(TicketLabelJoin.ticket == t.id))])
    feature_tickets = len([t for t in tickets_all if any(l.label == 'feature' for l in TicketLabelJoin.select().where(TicketLabelJoin.ticket == t.id))])
    other_tickets = total_tickets - bug_tickets - feature_tickets
    
    total = bug_tickets + feature_tickets + other_tickets
    effort_bugs = (bug_tickets / total * 100) if total > 0 else 0
    effort_features = (feature_tickets / total * 100) if total > 0 else 0
    effort_tickets = (other_tickets / total * 100) if total > 0 else 0
    
    # Top contributors
    top_contributors = []
    max_activity = max(user_activity.values()) if user_activity else 1
    for username, count in sorted(user_activity.items(), key=lambda x: x[1], reverse=True)[:5]:
        top_contributors.append({
            'username': username,
            'activity_count': count,
            'percentage': (count / max_activity) * 100
        })
    
    # Calculate date range
    if events:
        oldest = min(e['timestamp'] for e in events)
        newest = max(e['timestamp'] for e in events)
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
        'events': events,
        'total_events': len(events),
        'date_range': date_range,
        'tickets_created': tickets_created,
        'tickets_closed': tickets_closed,
        'tickets_in_progress': tickets_in_progress,
        'total_comments': total_comments,
        'total_errors': total_errors,
        'errors_resolved': errors_resolved,
        'active_users': active_users,
        'effort_tickets': round(effort_tickets, 1),
        'effort_bugs': round(effort_bugs, 1),
        'effort_features': round(effort_features, 1),
        'top_contributors': top_contributors,
        'activity_by_day': dict(activity_by_day)
    }


@secureroute('/timeline')
def timeline_view(user: User):
    data = build_timeline_events(project_id=None, days=30)
    
    return render_template('timeline.jinja2',
        user=user,
        page='timeline',
        projects=list(Project.select().order_by(Project.name)),
        project=None,
        events=data['events'][:50],  # Limit initial load
        events_json=json.dumps(data['events'][:100]),
        activity_by_day=json.dumps(data['activity_by_day']),
        has_more_events=len(data['events']) > 50,
        total_events=data['total_events'],
        date_range=data['date_range'],
        tickets_created=data['tickets_created'],
        tickets_closed=data['tickets_closed'],
        tickets_in_progress=data['tickets_in_progress'],
        total_comments=data['total_comments'],
        total_errors=data['total_errors'],
        errors_resolved=data['errors_resolved'],
        active_users=data['active_users'],
        effort_tickets=data['effort_tickets'],
        effort_bugs=data['effort_bugs'],
        effort_features=data['effort_features'],
        top_contributors=data['top_contributors']
    )


@secureroute('/timeline/<project_id>')
def timeline_project_view(user: User, project_id: str):
    project = Project.get_or_none(Project.id == project_id)
    if not project:
        return redirect('/timeline')
    
    data = build_timeline_events(project_id=project_id, days=30)
    
    return render_template('timeline.jinja2',
        user=user,
        page='timeline',
        projects=list(Project.select().order_by(Project.name)),
        project=project,
        events=data['events'][:50],
        events_json=json.dumps(data['events'][:100]),
        activity_by_day=json.dumps(data['activity_by_day']),
        has_more_events=len(data['events']) > 50,
        total_events=data['total_events'],
        date_range=data['date_range'],
        tickets_created=data['tickets_created'],
        tickets_closed=data['tickets_closed'],
        tickets_in_progress=data['tickets_in_progress'],
        total_comments=data['total_comments'],
        total_errors=data['total_errors'],
        errors_resolved=data['errors_resolved'],
        active_users=data['active_users'],
        effort_tickets=data['effort_tickets'],
        effort_bugs=data['effort_bugs'],
        effort_features=data['effort_features'],
        top_contributors=data['top_contributors']
    )


@secureroute('/errors')
def parts_view(user: User):
    
    # Project parts
    project_parts = ProjectPart.select()

    return render_template('parts.jinja2', 
        user=user,
        project = None,
        projects = Project.select(),
        project_parts = project_parts,
        page = 'errors'
    )


@secureroute('/errors/<project_id>')
def parts_specific_view(user: User, project_id: str):
    
    # Project parts
    project_parts = ProjectPart.select().where(ProjectPart.project == project_id)

    return render_template('parts.jinja2', 
        user=user,
        project = Project.get(Project.id == project_id),
        projects = Project.select(),
        project_parts = project_parts,
        page = 'errors'
    )

@secureroute('/errors/<project_id>/<int:part_id>')
def part_view(user: User, project_id: str, part_id: int):
    
    part = ProjectPart.get((ProjectPart.project == project_id) & (ProjectPart.id == part_id))
    error_groups = ErrorGroup.select().where(ErrorGroup.part == part_id).order_by(ErrorGroup.last_seen.desc()).limit(100)

    return render_template('part.jinja2', 
        user=user,
        project = Project.get(Project.id == project_id),
        part = part,
        error_groups = error_groups,
        page = 'errors'
    )


@secureroute('/errors/<project_id>/<int:part_id>/<int:error_id>')
def error_detail_view(user: User, project_id: str, part_id: int, error_id: int):
    """Display detailed view of an error group."""
    
    # Get the error group
    try:
        error = ErrorGroup.get(
            (ErrorGroup.id == error_id) & 
            (ErrorGroup.part == part_id)
        )
    except DoesNotExist:
        return 'Error not found', 404
    
    part = ProjectPart.get(ProjectPart.id == part_id)
    project = Project.get(Project.id == project_id)
    
    # Parse stacktrace JSON
    stacktrace_frames = []
    if error.stacktrace:
        try:
            stacktrace_data = json.loads(error.stacktrace)
            # Sentry stacktrace format has 'frames' array
            frames = stacktrace_data.get('frames', [])
            # Reverse to show most recent call first (like Python tracebacks)
            stacktrace_frames = list(reversed(frames))
        except json.JSONDecodeError:
            pass
    
    # Parse contexts JSON
    contexts = {}
    if error.contexts:
        try:
            contexts = json.loads(error.contexts)
        except json.JSONDecodeError:
            pass
    
    # Parse tags JSON
    tags = {}
    if error.tags:
        try:
            tags = json.loads(error.tags)
        except json.JSONDecodeError:
            pass
    
    # Get occurrences
    occurrences = list(ErrorOccurrence.select().where(
        ErrorOccurrence.error_group == error_id
    ).order_by(ErrorOccurrence.timestamp.desc()).limit(100))
    
    # Build occurrence chart (last 14 days)
    from datetime import datetime, timedelta
    from collections import defaultdict
    
    today = datetime.now().date()
    day_counts = defaultdict(int)
    
    for occ in occurrences:
        occ_date = datetime.fromtimestamp(occ.timestamp).date()
        day_counts[occ_date] += 1
    
    # Create chart data for last 14 days
    occurrence_chart = []
    for i in range(13, -1, -1):
        day = today - timedelta(days=i)
        day_label = day.strftime('%d')
        count = day_counts.get(day, 0)
        occurrence_chart.append((day_label, count))
    
    max_occurrences = max((count for _, count in occurrence_chart), default=1)
    
    # Related ticket
    ticket = Ticket.select().where(Ticket.error == error.id).first()

    return render_template('error.jinja2',
        user=user,
        project=project,
        part=part,
        error=error,
        stacktrace_frames=stacktrace_frames,
        contexts=contexts,
        tags=tags,
        occurrences=occurrences,
        occurrence_chart=occurrence_chart,
        max_occurrences=max_occurrences,
        ticket=ticket,
        page='errors'
    )


@app.route('/api/errors/<int:error_id>/status', methods=['POST']) # type: ignore
def update_error_status(error_id: int):
    """API endpoint to update error status."""
    try:
        error = ErrorGroup.get(ErrorGroup.id == error_id)
    except DoesNotExist:
        return json.dumps({'error': 'Error not found'}), 404
    
    data = request.get_json()
    new_status = data.get('status')
    
    if new_status not in ['unresolved', 'resolved', 'ignored']:
        return json.dumps({'error': 'Invalid status'}), 400
    
    error.status = new_status
    error.save()
    
    return json.dumps({'success': True, 'status': new_status}), 200


# @secureroute('/')

### Ingest endpoint for Sentry-like error messages
@app.route('/ingest/api/<int:part>/envelope/', methods=['POST']) # type: ignore
@app.route('/ingest/<int:part>/envelope', methods=['POST']) # type: ignore
def ingest_envelope_view(part: int):
    """
    Handle Sentry envelope format.
    
    Envelope format:
    - Line 1: Envelope headers (JSON) - contains event_id, sent_at, dsn, etc.
    - For each item:
        - Item header line (JSON) - contains type, length, content_type, etc.
        - Item payload (JSON or binary depending on type)
    
    Items are separated by newlines. An envelope can contain multiple items.
    """
    
    # Validate the project part exists
    try:
        project_part = ProjectPart.get(ProjectPart.id == part)
    except DoesNotExist:
        return 'Invalid DSN', 404
    
    # Try to decompress gzip data, fall back to raw data
    try:
        decompressed_data = gzip.decompress(request.data)
        data = decompressed_data.decode('utf-8')
    except:
        # Maybe it's not gzipped
        try:
            data = request.data.decode('utf-8')
        except:
            return 'Invalid data encoding', 400
    
    # Split into lines
    lines = data.split('\n')
    if len(lines) < 1:
        return 'Empty envelope', 400
    
    # Parse envelope headers (first line)
    try:
        envelope_headers = json.loads(lines[0])
    except json.JSONDecodeError:
        envelope_headers = {}
    
    event_id = envelope_headers.get('event_id')
    
    # Process items (remaining lines come in pairs: header + payload)
    i = 1
    current_error_group = None
    processed_items = []
    
    while i < len(lines):
        # Skip empty lines
        if not lines[i].strip():
            i += 1
            continue
        
        # Parse item header
        try:
            item_headers = json.loads(lines[i])
        except json.JSONDecodeError:
            i += 1
            continue
        
        item_type = item_headers.get('type', 'unknown')
        item_length = item_headers.get('length')
        
        # Get item payload
        i += 1
        if i >= len(lines):
            break
        
        # Handle multi-line payloads based on length
        if item_length:
            # Reconstruct payload from length
            payload_str = ''
            remaining_length = item_length
            while i < len(lines) and remaining_length > 0:
                line = lines[i]
                payload_str += line
                remaining_length -= len(line.encode('utf-8'))
                if remaining_length > 0:
                    payload_str += '\n'
                    remaining_length -= 1
                i += 1
        else:
            payload_str = lines[i]
            i += 1
        
        # Parse payload as JSON if possible
        try:
            payload = json.loads(payload_str)
        except json.JSONDecodeError:
            payload = payload_str  # Keep as string for attachments
        
        # Handle different item types
        try:
            if item_type == 'event' and isinstance(payload, dict):
                current_error_group = handle_event_item(project_part, payload, event_id)
                processed_items.append('event')
                
            elif item_type == 'session' and isinstance(payload, dict):
                handle_session_item(project_part, payload)
                processed_items.append('session')
                
            elif item_type == 'sessions' and isinstance(payload, dict):
                # Aggregated sessions format
                for session_data in payload.get('aggregates', []):
                    # Create a synthetic session payload
                    synthetic_payload = {
                        'sid': f"aggregate_{int(time.time())}",
                        'status': 'ok',
                        'started': session_data.get('started'),
                        'attrs': payload.get('attrs', {})
                    }
                    handle_session_item(project_part, synthetic_payload)
                processed_items.append('sessions')
                
            elif item_type == 'transaction' and isinstance(payload, dict):
                handle_transaction_item(project_part, payload)
                processed_items.append('transaction')
                
            elif item_type == 'attachment':
                if current_error_group:
                    handle_attachment_item(project_part, current_error_group, item_headers, payload_str)
                processed_items.append('attachment')
                
            elif item_type == 'client_report':
                # Client reports are telemetry about dropped events, we can ignore or log
                processed_items.append('client_report')
                
            else:
                # Unknown type, log and continue
                print(f"Unknown envelope item type: {item_type}")
                processed_items.append(f'unknown:{item_type}')
                
        except Exception as e:
            print(f"Error processing {item_type} item: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    if not processed_items:
        return 'No items processed', 400
    
    return f'OK: processed {", ".join(processed_items)}', 200


@app.route('/api/errors/<int:error_id>/create_ticket', methods=['GET']) # type: ignore
def create_ticket_from_error(error_id: int):
    """Create a ticket in an external system from the error."""
    try:
        error = ErrorGroup.get(ErrorGroup.id == error_id)
    except DoesNotExist:
        return 'Error not found', 404
    
    # Example: Create a ticket in a hypothetical ticketing system
    ticket_id = f"{error.part.project.id}-E{error.id}"
    Ticket.create(
        id = ticket_id,
        title=f"Error: {error.exception_value or 'No message'}",
        description=f"An error occurred:\n\nType: {error.exception_type}\nValue: {error.exception_value}\nCulprit: {error.culprit}",
        status='open',
        created_at=int(time.time()),
        project = error.part.project,
        priority = 'high',
        error = error,
    )

    return redirect(f'/tickets/{error.part.project.id}/{ticket_id}')