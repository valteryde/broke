
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
