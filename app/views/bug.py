import os

from ..utils.security import protected
from ..utils.events import EventTypes, bus
from ..utils.models import (
    User,
    Project,
    ProjectPart,
    ErrorGroup,
    ErrorOccurrence,
    Ticket,
    Attachment,
    Session,
    Transaction,
    DSNToken,
    active_projects_ordered,
)
from flask import redirect, render_template, request, Blueprint
from peewee import DoesNotExist
import gzip
import json
import hashlib
import hmac
import time
import re
import base64
from logging import getLogger
from urllib.parse import urlparse

logger = getLogger(__name__)

# Create blueprint
bug_bp = Blueprint("bug", __name__)

ERROR_ESCALATION_MILESTONES = (10, 50, 100, 500, 1000)
ERROR_SPIKE_WINDOW_SEC = 600
ERROR_SPIKE_MIN_OCCURRENCES = 5
ERROR_SPIKE_EMAIL_COOLDOWN_SEC = 3600


def _format_error_core_details(error_group: ErrorGroup) -> str:
    et = error_group.exception_type or "Unknown"
    ev = error_group.exception_value or ""
    lines = [f"Exception: {et}: {ev}".strip()]
    if error_group.culprit:
        lines.append(f"Culprit: {error_group.culprit}")
    lines.append(f"Total occurrences: {error_group.event_count}")
    return "\n".join(lines)


def _error_event_kwargs(part: ProjectPart, error_group: ErrorGroup, details: str) -> dict:
    base_url = os.environ.get("APP_BASE_URL", "").strip().rstrip("/")
    kwargs: dict = {
        "project": str(part.project_id),
        "part_name": part.name,
        "error_group_id": error_group.id,
        "actor": "ingest",
        "status": error_group.status,
        "details": details,
        "environment": error_group.environment,
        "release": error_group.release,
    }
    if base_url:
        kwargs["error_url"] = f"{base_url}/errors/{part.project_id}/{part.id}/{error_group.id}"
    return kwargs


def _emit_error_notifications_after_occurrence(
    part: ProjectPart,
    error_group: ErrorGroup,
    *,
    is_new: bool,
    was_resolved: bool,
    was_ignored: bool,
    old_count: int,
    timestamp: int,
) -> None:
    core = _format_error_core_details(error_group)
    if is_new:
        bus.emit(EventTypes.ERROR_NEW, **_error_event_kwargs(part, error_group, core))
        return

    if was_resolved:
        reg_details = f"{core}\nPreviously resolved; reopened on new occurrence."
        bus.emit(EventTypes.ERROR_REGRESSION, **_error_event_kwargs(part, error_group, reg_details))

    if was_ignored or error_group.status == "ignored":
        return

    new_count = error_group.event_count
    escalation_reasons: list[str] = []
    spike_notifies = False

    for m in ERROR_ESCALATION_MILESTONES:
        if old_count < m <= new_count:
            escalation_reasons.append(
                f"Volume milestone: {new_count} total occurrences (crossed {m})"
            )
            break

    cutoff = timestamp - ERROR_SPIKE_WINDOW_SEC
    n_spike = (
        ErrorOccurrence.select()
        .where(
            (ErrorOccurrence.error_group == error_group) & (ErrorOccurrence.timestamp >= cutoff)
        )
        .count()
    )
    if n_spike >= ERROR_SPIKE_MIN_OCCURRENCES:
        last_spike = error_group.last_escalation_spike_email_at
        if last_spike is None or timestamp - last_spike >= ERROR_SPIKE_EMAIL_COOLDOWN_SEC:
            escalation_reasons.append(
                f"Spike: {n_spike} events in the last {ERROR_SPIKE_WINDOW_SEC // 60} minutes"
            )
            spike_notifies = True

    if escalation_reasons:
        details = f"{core}\n" + "\n".join(escalation_reasons)
        bus.emit(EventTypes.ERROR_ESCALATING, **_error_event_kwargs(part, error_group, details))
        if spike_notifies:
            error_group.last_escalation_spike_email_at = timestamp
            error_group.save(only=[ErrorGroup.last_escalation_spike_email_at])


def normalize_message(message: str | None) -> str:
    """Normalize error message by removing dynamic content for better grouping."""
    if not message:
        return ""

    # Remove UUIDs (various formats)
    message = re.sub(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        "<UUID>",
        message,
        flags=re.IGNORECASE,
    )

    # Remove hex addresses/pointers (0x...)
    message = re.sub(r"0x[0-9a-f]+", "<HEX>", message, flags=re.IGNORECASE)

    # Remove pure numbers (but preserve words with numbers like "utf8")
    message = re.sub(r"\b\d+\b", "<N>", message)

    # Remove quoted strings (file paths, variable values, etc.)
    message = re.sub(r'"[^"]*"', '"<STR>"', message)
    message = re.sub(r"'[^']*'", "'<STR>'", message)

    # Remove IP addresses
    message = re.sub(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "<IP>", message)

    # Remove timestamps (ISO format)
    message = re.sub(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}", "<TIMESTAMP>", message)

    return message


def extract_frame_signatures(stacktrace_json: str | None) -> list[str]:
    """Extract function call signatures from stacktrace frames for fingerprinting."""
    if not stacktrace_json:
        return []

    try:
        stacktrace = json.loads(stacktrace_json)
        frames = stacktrace.get("frames", [])

        signatures = []
        # Use last 5 frames (most relevant to the error)
        for frame in frames[-5:]:
            module = frame.get("module") or frame.get("filename") or ""
            function = frame.get("function") or ""
            # Create signature without line numbers or variables
            signatures.append(f"{module}:{function}")

        return signatures
    except (json.JSONDecodeError, TypeError):
        return []


def generate_fingerprint(
    exception_type: str | None, exception_value: str | None, stacktrace: str | None
) -> str:
    """Generate a fingerprint for grouping similar errors together.

    Uses frame-based fingerprinting with message normalization:
    - Exception type (e.g., ValueError, TypeError)
    - Normalized error message (dynamic values removed)
    - Function call chain (module:function, no line numbers)
    """
    # Normalize the error message to remove dynamic content
    normalized_value = normalize_message(exception_value)

    # Extract frame signatures (module:function pairs)
    frame_signatures = extract_frame_signatures(stacktrace)
    frames_str = "|".join(frame_signatures)

    # Build fingerprint from stable components
    fingerprint_data = f"{exception_type or ''}:{normalized_value}:{frames_str}"
    return hashlib.sha256(fingerprint_data.encode("utf-8")).hexdigest()[:32]


def extract_exception_info(payload: dict) -> tuple[str | None, str | None, str | None]:
    """Extract exception type, value, and stacktrace from a Sentry event payload."""
    exception_type = None
    exception_value = None
    stacktrace_json = None

    # Try to get from exception.values (standard Sentry format)
    if "exception" in payload and "values" in payload["exception"]:
        values = payload["exception"]["values"]
        if values:
            first_exception = values[0]
            exception_type = first_exception.get("type")
            exception_value = first_exception.get("value")
            if "stacktrace" in first_exception:
                stacktrace_json = json.dumps(first_exception["stacktrace"])

    # Fallback to message field
    if not exception_value:
        exception_value = payload.get("message", payload.get("logentry", {}).get("message"))

    return exception_type, exception_value, stacktrace_json


def extract_culprit(payload: dict) -> str | None:
    """Extract the culprit (file/function where error occurred)."""
    # First check if culprit is directly provided
    if "culprit" in payload:
        return payload["culprit"]

    # Try to extract from stacktrace
    if "exception" in payload and "values" in payload["exception"]:
        values = payload["exception"]["values"]
        if values and "stacktrace" in values[0]:
            frames = values[0]["stacktrace"].get("frames", [])
            if frames:
                last_frame = frames[-1]
                filename = last_frame.get("filename", last_frame.get("abs_path", ""))
                function = last_frame.get("function", "")
                lineno = last_frame.get("lineno", "")
                return f"{filename}:{function}:{lineno}"

    return None


def handle_event_item(part: ProjectPart, payload: dict, event_id: str | None = None) -> ErrorGroup:
    """Handle an event item from a Sentry envelope."""
    exception_type, exception_value, stacktrace_json = extract_exception_info(payload)
    culprit = extract_culprit(payload)

    # Generate fingerprint for grouping
    fingerprint = generate_fingerprint(exception_type, exception_value, stacktrace_json)

    # Extract additional context
    platform = payload.get("platform")
    environment = payload.get("environment")
    release = payload.get("release")
    contexts = json.dumps(payload.get("contexts", {})) if payload.get("contexts") else None
    tags = json.dumps(payload.get("tags", {})) if payload.get("tags") else None
    extra = json.dumps(payload.get("extra", {})) if payload.get("extra") else None

    timestamp = int(time.time())

    # Try to find existing error group or create new one
    try:
        error_group = ErrorGroup.get(
            (ErrorGroup.part == part) & (ErrorGroup.fingerprint == fingerprint)
        )
        old_count = error_group.event_count
        was_resolved = error_group.status == "resolved"
        was_ignored = error_group.status == "ignored"
        error_group.event_count += 1
        error_group.last_seen = timestamp
        # Regression detection: reopen issues that were previously resolved.
        if error_group.status == "resolved":
            error_group.status = "unresolved"
        error_group.save()
        is_new = False
    except DoesNotExist:
        old_count = 0
        was_resolved = False
        was_ignored = False
        is_new = True
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
            status="unresolved",
        )

    # Record this occurrence
    ErrorOccurrence.create(
        error_group=error_group, timestamp=timestamp, event_id=event_id or payload.get("event_id")
    )

    _emit_error_notifications_after_occurrence(
        part,
        error_group,
        is_new=is_new,
        was_resolved=was_resolved,
        was_ignored=was_ignored,
        old_count=old_count,
        timestamp=timestamp,
    )

    return error_group


def handle_session_item(part: ProjectPart, payload: dict):
    """Handle a session item from a Sentry envelope."""
    session_id = payload.get("sid")
    if not session_id:
        return None

    status = payload.get("status", "ok")
    started = payload.get("started")
    if isinstance(started, str):
        # Parse ISO timestamp to unix timestamp
        try:
            from datetime import datetime

            started = int(datetime.fromisoformat(started.replace("Z", "+00:00")).timestamp())
        except ValueError:
            started = int(time.time())

    duration = payload.get("duration")
    errors = payload.get("errors", 0)
    release = payload.get("attrs", {}).get("release")
    environment = payload.get("attrs", {}).get("environment")

    # Update or create session
    try:
        session = Session.get((Session.part == part) & (Session.session_id == session_id))
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
            environment=environment,
        )

    return session


def handle_transaction_item(part: ProjectPart, payload: dict):
    """Handle a transaction (performance) item from a Sentry envelope."""
    transaction_id = payload.get("event_id") or payload.get("transaction_id")
    if not transaction_id:
        return None

    name = payload.get("transaction", "Unknown")
    op = payload.get("contexts", {}).get("trace", {}).get("op")

    # Calculate duration from start/end timestamps
    start_timestamp = payload.get("start_timestamp")
    end_timestamp = payload.get("timestamp")
    duration = None
    if start_timestamp and end_timestamp:
        duration = int((end_timestamp - start_timestamp) * 1000)  # Convert to ms

    status = payload.get("contexts", {}).get("trace", {}).get("status")

    transaction = Transaction.create(
        part=part,
        transaction_id=transaction_id,
        name=name,
        op=op,
        duration=duration,
        status=status,
        timestamp=int(time.time()),
        data=json.dumps(payload.get("spans", []))[:10000] if payload.get("spans") else None,
    )

    return transaction


def handle_attachment_item(
    part: ProjectPart, error_group: ErrorGroup, item_headers: dict, payload: str | bytes
):
    """Handle an attachment item from a Sentry envelope."""
    filename = item_headers.get("filename", "unknown")
    content_type = item_headers.get("content_type") or item_headers.get("type")

    if isinstance(payload, bytes):
        try:
            data = payload.decode("utf-8")
        except UnicodeDecodeError:
            data = base64.b64encode(payload).decode("ascii")
    else:
        data = payload

    attachment = Attachment.create(
        error_group=error_group,
        filename=filename,
        content_type=content_type,
        data=data[:100000],  # Limit size
    )

    return attachment


@bug_bp.route("/errors")
@protected
def parts_view(user: User):

    # Project parts
    project_parts = ProjectPart.select()

    return render_template(
        "parts.jinja2",
        user=user,
        project=None,
        projects=active_projects_ordered(),
        project_parts=project_parts,
        page="errors",
    )


@bug_bp.route("/errors/<project_id>")
@protected
def parts_specific_view(user: User, project_id: str):

    # Project parts
    project_parts = ProjectPart.select().where(ProjectPart.project == project_id)

    return render_template(
        "parts.jinja2",
        user=user,
        project=Project.get(Project.id == project_id),
        projects=active_projects_ordered(),
        project_parts=project_parts,
        page="errors",
    )


# ============ Parts API Endpoints ============


@bug_bp.route("/api/parts", methods=["POST"])
@protected
def api_create_part(user: User):
    """Create a new project part (service)"""
    import json

    data = request.get_json()

    project_id = data.get("project_id", "").strip()
    name = data.get("name", "").strip()
    description = data.get("description", "").strip()

    if not project_id:
        return json.dumps({"error": "Project is required"}), 400

    if not name:
        return json.dumps({"error": "Name is required"}), 400

    # Verify project exists
    try:
        Project.get(Project.id == project_id)
    except DoesNotExist:
        return json.dumps({"error": "Project not found"}), 404

    # Check if part already exists for this project
    existing = (
        ProjectPart.select()
        .where((ProjectPart.project == project_id) & (ProjectPart.name == name))
        .first()
    )

    if existing:
        return json.dumps({"error": "A part with this name already exists in this project"}), 400

    part = ProjectPart.create(project=project_id, name=name, description=description or "")

    return (
        json.dumps(
            {
                "success": True,
                "part": {
                    "id": part.id,
                    "project_id": project_id,
                    "name": part.name,
                    "description": part.description,
                },
            }
        ),
        200,
    )


@bug_bp.route("/errors/<project_id>/<int:part_id>")
@protected
def part_view(user: User, project_id: str, part_id: int):

    part = ProjectPart.get((ProjectPart.project == project_id) & (ProjectPart.id == part_id))
    error_groups = (
        ErrorGroup.select()
        .where(ErrorGroup.part == part_id)
        .order_by(ErrorGroup.last_seen.desc())
        .limit(100)
    )
    part_error_count = ErrorGroup.select().where(ErrorGroup.part == part_id).count()

    return render_template(
        "part.jinja2",
        user=user,
        project=Project.get(Project.id == project_id),
        part=part,
        error_groups=error_groups,
        part_error_count=part_error_count,
        page="errors",
    )


@bug_bp.route("/errors/<project_id>/<int:part_id>/<int:error_id>")
@protected
def error_detail_view(user: User, project_id: str, part_id: int, error_id: int):
    """Display detailed view of an error group."""

    # Get the error group
    try:
        error = ErrorGroup.get((ErrorGroup.id == error_id) & (ErrorGroup.part == part_id))
    except DoesNotExist:
        return "Error not found", 404

    part = ProjectPart.get(ProjectPart.id == part_id)
    project = Project.get(Project.id == project_id)

    # Parse stacktrace JSON
    stacktrace_frames = []
    if error.stacktrace:
        try:
            stacktrace_data = json.loads(error.stacktrace)
            # Sentry stacktrace format has 'frames' array
            frames = stacktrace_data.get("frames", [])
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
    occurrences = list(
        ErrorOccurrence.select()
        .where(ErrorOccurrence.error_group == error_id)
        .order_by(ErrorOccurrence.timestamp.desc())
        .limit(100)
    )

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
        day_label = day.strftime("%d")
        count = day_counts.get(day, 0)
        occurrence_chart.append((day_label, count))

    max_occurrences = max((count for _, count in occurrence_chart), default=1)

    # Related ticket
    ticket = Ticket.select().where(Ticket.error == error.id).first()

    return render_template(
        "error.jinja2",
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
        page="errors",
    )


@bug_bp.route("/api/errors/<int:error_id>/status", methods=["POST"])  # type: ignore
@protected
def update_error_status(user: User, error_id: int):
    """API endpoint to update error status."""
    try:
        error = ErrorGroup.get(ErrorGroup.id == error_id)
    except DoesNotExist:
        return json.dumps({"error": "Error not found"}), 404

    data = request.get_json()
    new_status = data.get("status")

    if new_status not in ["unresolved", "resolved", "ignored"]:
        return json.dumps({"error": "Invalid status"}), 400

    error.status = new_status
    error.save()

    return json.dumps({"success": True, "status": new_status}), 200


def _ingest_content_type_allowed() -> bool:
    """Sentry allows a small set of Content-Types for the same envelope body behavior."""
    ct = (request.content_type or "").partition(";")[0].strip().lower()
    return ct in {
        "",
        "application/x-sentry-envelope",
        "text/plain",
        "multipart/form-data",
        "application/x-www-form-urlencoded",
    }


def _decompressed_ingest_body() -> bytes:
    raw = request.get_data(cache=False)
    try:
        return gzip.decompress(raw)
    except Exception:
        return raw


def _split_envelope_header(raw: bytes) -> tuple[dict, int]:
    """Parse the envelope header line; return (headers dict, index after first newline)."""
    if not raw:
        return {}, 0
    nl = raw.find(b"\n")
    if nl < 0:
        line_b = raw
        after = len(raw)
    else:
        line_b = raw[:nl]
        after = nl + 1
    try:
        line = line_b.decode("utf-8")
        headers = json.loads(line)
        if not isinstance(headers, dict):
            return {}, after
        return headers, after
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}, after


def sentry_public_key_from_dsn(dsn: str | None) -> str | None:
    """Extract the public key (username) from a Sentry DSN URL."""
    if not dsn or not isinstance(dsn, str):
        return None
    try:
        parsed = urlparse(dsn.strip())
        user = parsed.username
        return user if user else None
    except Exception:
        return None


def _basic_auth_public_key() -> str | None:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            return decoded.split(":")[0] or None
        except Exception:
            return None
    return None


def _x_sentry_auth_public_key() -> str | None:
    sentry_auth = request.headers.get("X-Sentry-Auth", "")
    if not sentry_auth:
        return None
    if sentry_auth.startswith("Sentry "):
        sentry_auth = sentry_auth[7:]
    for part in sentry_auth.split(","):
        part = part.strip()
        if part.startswith("sentry_key="):
            return part[11:].strip() or None
    return None


def _query_sentry_public_key() -> str | None:
    key = request.args.get("sentry_key", type=str)
    return key if key else None


def iter_sentry_envelope_items(raw: bytes, start: int):
    """Yield (item_headers dict, payload bytes) per Sentry envelope semantics."""
    pos = start
    n = len(raw)
    while pos < n:
        while pos < n and raw[pos] == 10:  # \n
            pos += 1
        if pos >= n:
            break
        nl = raw.find(b"\n", pos)
        if nl < 0:
            break
        try:
            item_headers = json.loads(raw[pos:nl].decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            break
        if not isinstance(item_headers, dict):
            break
        pos = nl + 1
        if pos > n:
            break

        length = item_headers.get("length")
        if length is not None:
            try:
                blen = int(length)
            except (TypeError, ValueError):
                break
            if blen < 0 or pos + blen > n:
                break
            payload = raw[pos : pos + blen]
            pos += blen
            if pos < n:
                if raw[pos] == 10:
                    pos += 1
                else:
                    break
        else:
            next_nl = raw.find(b"\n", pos)
            if next_nl < 0:
                payload = raw[pos:]
                pos = n
            else:
                payload = raw[pos:next_nl]
                pos = next_nl + 1

        yield item_headers, payload


def _decode_item_payload(payload: bytes) -> tuple[object, bytes]:
    """Return (json object or raw bytes) for dispatch; dict/list primitives for JSON."""
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return payload, payload
    try:
        return json.loads(text), payload
    except json.JSONDecodeError:
        return text, payload


def verify_dsn_token(*, envelope_public_key: str | None = None) -> bool:
    """Verify the DSN token from the request.

    Credentials may be provided (Sentry-compatible) via:
    1. Basic auth username (Sentry SDK default)
    2. X-Sentry-Auth sentry_key
    3. sentry_key query parameter
    4. Public key embedded in the envelope ``dsn`` header

    If more than one is present, all must identify the same key.
    """
    sources: list[str | None] = [
        _basic_auth_public_key(),
        _x_sentry_auth_public_key(),
        _query_sentry_public_key(),
        envelope_public_key,
    ]
    keys = [s for s in sources if s]
    if not keys:
        return False
    if len(set(keys)) != 1:
        logger.info("DSN auth mismatch: inconsistent credentials in request")
        return False
    token = keys[0]

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()

    # Verify token exists in database (hashed primary path + legacy plaintext fallback).
    try:
        dsn_token = (
            DSNToken.select()
            .where((DSNToken.token_hash == token_hash) | (DSNToken.token == token))
            .first()
        )
        if not dsn_token:
            return False

        if dsn_token.token_hash:
            if not hmac.compare_digest(str(dsn_token.token_hash), token_hash):
                return False
        elif dsn_token.token:
            if not hmac.compare_digest(str(dsn_token.token), token):
                return False
        else:
            return False

        # Update last used timestamp
        dsn_token.last_used = int(time.time())
        dsn_token.save()
        return True
    except Exception:
        return False


# Ingest endpoint for Sentry-like error messages
@bug_bp.route("/ingest/api/<int:part>/envelope/", methods=["POST"])  # type: ignore
@bug_bp.route("/ingest/<int:part>/envelope", methods=["POST"])  # type: ignore
def ingest_envelope_view(part: int):  # noqa: C901
    """
    Handle Sentry envelope format.

    Envelope format:
    - Line 1: Envelope headers (JSON) - contains event_id, sent_at, dsn, etc.
    - For each item:
        - Item header line (JSON) - contains type, length, content_type, etc.
        - Item payload (JSON or binary depending on type); ``length`` is a byte count.

    Items are separated by newlines. An envelope can contain multiple items.
    """
    if not _ingest_content_type_allowed():
        return "Unsupported Content-Type", 415

    raw = _decompressed_ingest_body()
    if not raw:
        return "Empty envelope", 400

    envelope_headers, items_start = _split_envelope_header(raw)
    env_key = sentry_public_key_from_dsn(envelope_headers.get("dsn"))

    if not verify_dsn_token(envelope_public_key=env_key):
        logger.info("Unauthorized DSN token attempt")
        return "Unauthorized: Invalid or missing DSN token", 401

    try:
        project_part = ProjectPart.get(ProjectPart.id == part)
    except DoesNotExist:
        return "Invalid DSN", 404

    event_id = envelope_headers.get("event_id")
    current_error_group = None
    processed_items = []

    for item_headers, payload_bytes in iter_sentry_envelope_items(raw, items_start):
        item_type = item_headers.get("type", "unknown")
        payload, raw_payload = _decode_item_payload(payload_bytes)

        try:
            if item_type == "event" and isinstance(payload, dict):
                current_error_group = handle_event_item(project_part, payload, event_id)
                processed_items.append("event")

            elif item_type == "session" and isinstance(payload, dict):
                handle_session_item(project_part, payload)
                processed_items.append("session")

            elif item_type == "sessions" and isinstance(payload, dict):
                for session_data in payload.get("aggregates", []):
                    synthetic_payload = {
                        "sid": f"aggregate_{int(time.time())}",
                        "status": "ok",
                        "started": session_data.get("started"),
                        "attrs": payload.get("attrs", {}),
                    }
                    handle_session_item(project_part, synthetic_payload)
                processed_items.append("sessions")

            elif item_type == "transaction" and isinstance(payload, dict):
                handle_transaction_item(project_part, payload)
                processed_items.append("transaction")

            elif item_type == "attachment":
                if current_error_group:
                    handle_attachment_item(
                        project_part, current_error_group, item_headers, raw_payload
                    )
                processed_items.append("attachment")

            elif item_type == "client_report":
                processed_items.append("client_report")

            else:
                print(f"Unknown envelope item type: {item_type}")
                processed_items.append(f"unknown:{item_type}")

        except Exception as e:
            print(f"Error processing {item_type} item: {e}")
            import traceback

            traceback.print_exc()
            continue

    if not processed_items:
        return "No items processed", 400

    return f'OK: processed {", ".join(processed_items)}', 200


@bug_bp.route("/api/errors/<int:error_id>/create_ticket", methods=["GET"])  # type: ignore
@protected
def create_ticket_from_error(user: User, error_id: int):
    """Create a ticket in an external system from the error."""
    try:
        error = ErrorGroup.get(ErrorGroup.id == error_id)
    except DoesNotExist:
        return "Error not found", 404

    # Example: Create a ticket in a hypothetical ticketing system
    ticket_id = f"{error.part.project.id}-E{error.id}"
    Ticket.create(
        id=ticket_id,
        title=f"Error: {error.exception_value or 'No message'}",
        description=f"An error occurred:\n\nType: {error.exception_type}\nValue: {error.exception_value}\nCulprit: {error.culprit}",
        status="open",
        created_at=int(time.time()),
        project=error.part.project,
        priority="high",
        error=error,
    )

    return redirect(f"/tickets/{error.part.project.id}/{ticket_id}")


@bug_bp.route("/api/errors/<int:error_id>", methods=["DELETE"])
@protected
def delete_error(user: User, error_id: int):
    """Hard delete an error group and its related data."""
    try:
        error = ErrorGroup.get(ErrorGroup.id == error_id)
    except DoesNotExist:
        return json.dumps({"error": "Error not found"}), 404

    # Cascade delete occurrences and attachments
    ErrorOccurrence.delete().where(ErrorOccurrence.error_group == error.id).execute()
    Attachment.delete().where(Attachment.error_group == error.id).execute()

    # Delete the error group itself
    error.delete_instance()

    return json.dumps({"success": True}), 200


@bug_bp.route("/api/projects/<project_id>/parts/<int:part_id>/errors", methods=["DELETE"])
@protected
def delete_all_part_errors(user: User, project_id: str, part_id: int):
    """Delete every error group (and related rows) for a project part."""
    try:
        ProjectPart.get((ProjectPart.id == part_id) & (ProjectPart.project == project_id))
    except DoesNotExist:
        return json.dumps({"error": "Part not found"}), 404

    error_ids = [row.id for row in ErrorGroup.select(ErrorGroup.id).where(ErrorGroup.part == part_id)]
    if not error_ids:
        return json.dumps({"success": True, "deleted": 0}), 200

    ErrorOccurrence.delete().where(ErrorOccurrence.error_group.in_(error_ids)).execute()
    Attachment.delete().where(Attachment.error_group.in_(error_ids)).execute()
    Ticket.update(error=None).where(Ticket.error.in_(error_ids)).execute()
    deleted = ErrorGroup.delete().where(ErrorGroup.id.in_(error_ids)).execute()

    return json.dumps({"success": True, "deleted": deleted}), 200
