from ..utils.security import protected
from ..utils.models import (
    TicketLabelJoin,
    User,
    UserSettings,
    Ticket,
    Project,
    Comment,
    TicketUpdateMessage,
    UserTicketJoin,
    Label,
)
from flask import redirect, render_template, request, jsonify, send_file, Blueprint
import time
import os
import base64
import uuid
import re
from difflib import SequenceMatcher
from ..utils.path import data_path
from ..utils.events import bus, EventTypes
from ..utils.ai_intake import suggest_intake_from_message
from ..utils.ai_changelog import get_ai_config

# Create blueprint
tickets_bp = Blueprint("tickets", __name__)


def populateTickets(tickets: list[Ticket]) -> None:
    """
    Populates the tickets page with tickets from the database.

    Adds labels, comments, and update messages to each ticket.

    Parameters:
        tickets (list): List of Ticket objects to populate.
    """

    for ticket in tickets:
        # Fetch and attach labels
        ticket.labels = [Label.get_or_none(Label.name == tlj.label) for tlj in TicketLabelJoin.select().where(TicketLabelJoin.ticket == ticket.id)]  # type: ignore

        # Fetch and attach comments
        ticket.comments = [comment for comment in Comment.select().where(Comment.ticket == ticket.id).order_by(Comment.id)]  # type: ignore

        # Fetch and attach update messages
        ticket.updates = [update for update in TicketUpdateMessage.select().where(TicketUpdateMessage.ticket == ticket.id).order_by(TicketUpdateMessage.id)]  # type: ignore

        # Add assigned users
        ticket.assignees = [User.get_or_none(User.username == utj.user) for utj in UserTicketJoin.select().where(UserTicketJoin.ticket == ticket.id)]  # type: ignore


def resolve_ticket_view(user: User) -> str:
    explicit = request.args.get("view", "").strip().lower()
    if explicit in {"list", "board"}:
        return explicit

    settings = UserSettings.get_or_none(UserSettings.user == user.username)
    if settings and settings.default_ticket_view in {"list", "board"}:
        return settings.default_ticket_view

    return "list"


@tickets_bp.route("/tickets")
@protected
def tickets_view(user: User):
    tickets = list(Ticket.select().where((Ticket.active == 1) & (Ticket.status != "triage")))
    populateTickets(tickets)
    ticket_view = resolve_ticket_view(user)

    available_users = User.select().order_by(User.username)
    available_labels = Label.select().order_by(Label.name)

    return render_template(
        "tickets.jinja2",
        user=user,
        page="tickets",
        tickets=tickets,
        project=None,
        projects=Project.select().distinct().order_by(Project.name),
        available_users=available_users,
        available_labels=available_labels,
        ticket_view=ticket_view,
        ticket_view_path="/tickets",
        ticket_page_title="Tickets",
        ticket_create_endpoint="/api/tickets",
        ticket_create_status="backlog",
        ticket_base_path="/tickets",
    )


@tickets_bp.route("/tickets/<project_id>")
@protected
def project_tickets_view(user: User, project_id: str):
    project = Project.get_or_none(Project.id == project_id)
    tickets = list(
        Ticket.select().where(
            (Ticket.project == project_id) & (Ticket.active == 1) & (Ticket.status != "triage")
        )
    )
    populateTickets(tickets)
    ticket_view = resolve_ticket_view(user)

    available_users = User.select().order_by(User.username)
    available_labels = Label.select().order_by(Label.name)

    return render_template(
        "tickets.jinja2",
        user=user,
        project=project,
        tickets=tickets,
        page="tickets",
        projects=Project.select().distinct().order_by(Project.name),
        available_users=available_users,
        available_labels=available_labels,
        ticket_view=ticket_view,
        ticket_view_path=f"/tickets/{project_id}",
        ticket_page_title="Tickets",
        ticket_create_endpoint="/api/tickets",
        ticket_create_status="backlog",
        ticket_base_path="/tickets",
    )


@tickets_bp.route("/triage")
@protected
def triage_view(user: User):
    tickets = list(
        Ticket.select()
        .where((Ticket.active == 1) & (Ticket.status == "triage"))
        .order_by(Ticket.created_at.asc())
    )
    populateTickets(tickets)

    available_users = User.select().order_by(User.username)
    available_labels = Label.select().order_by(Label.name)

    return render_template(
        "triage.jinja2",
        user=user,
        page="triage",
        tickets=tickets,
        project=None,
        projects=Project.select().distinct().order_by(Project.name),
        available_users=available_users,
        available_labels=available_labels,
        ticket_view="list",
        ticket_view_path="/triage",
        ticket_page_title="Triage Inbox",
        ticket_create_endpoint="/api/tickets/intake",
        ticket_create_status="triage",
        ticket_base_path="/triage",
        ai_intake_enabled=get_ai_config() is not None,
    )


@tickets_bp.route("/triage/<project_id>")
@protected
def triage_project_view(user: User, project_id: str):
    project = Project.get_or_none(Project.id == project_id)
    tickets = list(
        Ticket.select().where(
            (Ticket.project == project_id) & (Ticket.active == 1) & (Ticket.status == "triage")
        ).order_by(Ticket.created_at.asc())
    )
    populateTickets(tickets)

    available_users = User.select().order_by(User.username)
    available_labels = Label.select().order_by(Label.name)

    return render_template(
        "triage.jinja2",
        user=user,
        page="triage",
        tickets=tickets,
        project=project,
        projects=Project.select().distinct().order_by(Project.name),
        available_users=available_users,
        available_labels=available_labels,
        ticket_view="list",
        ticket_view_path=f"/triage/{project_id}",
        ticket_page_title="Triage Inbox",
        ticket_create_endpoint="/api/tickets/intake",
        ticket_create_status="triage",
        ticket_base_path="/triage",
        ai_intake_enabled=get_ai_config() is not None,
    )


@tickets_bp.route("/tickets/<project_id>/<ticket_id>")
@protected
def ticket_detail_view(user: User, project_id: str, ticket_id: str):
    ticket = Ticket.get_or_none(Ticket.id == ticket_id)

    if ticket is None or ticket.active == 0:
        return redirect(f"/tickets/{project_id}")

    populateTickets([ticket])  # type: ignore

    available_users = User.select().order_by(User.username)
    available_labels = Label.select().order_by(Label.name)

    comments = Comment.select().where(Comment.ticket == ticket_id).order_by(Comment.id)  # type: ignore
    updates = TicketUpdateMessage.select().where(TicketUpdateMessage.ticket == ticket_id).order_by(TicketUpdateMessage.id)  # type: ignore

    return render_template(
        "ticket.jinja2",
        user=user,
        ticket=ticket,
        project=Project.get_or_none(Project.id == project_id),
        page="tickets",
        available_users=available_users,
        available_labels=available_labels,
        comments=comments,
        updates=updates,
    )


# ============ Ticket API Endpoints ============


def generate_ticket_id(project_id: str) -> str:
    """Generate a ticket ID in the format PROJ-123"""
    # Find the highest ticket number for this project
    existing_tickets = Ticket.select().where(Ticket.project == project_id)
    max_num = 0
    for ticket in existing_tickets:
        # Extract number from ID like "PROJ-123"
        parts = ticket.id.split("-")
        if len(parts) >= 2:
            try:
                num = int(parts[-1])
                if num > max_num:
                    max_num = num
            except ValueError:
                pass

    return f"{project_id}-{max_num + 1}"


def generate_unique_ticket_id(project_id: str) -> str:
    """Generate a ticket ID and guard against rare collisions."""
    candidate = generate_ticket_id(project_id)
    while Ticket.get_or_none(Ticket.id == candidate):
        prefix, _, suffix = candidate.rpartition("-")
        if suffix.isdigit():
            candidate = f"{prefix}-{int(suffix) + 1}"
        else:
            candidate = f"{project_id}-{int(time.time())}"
    return candidate


def extract_and_save_images(html_content: str) -> str:
    """
    Extract base64 images from HTML content, save them to disk,
    and replace with URLs.
    """
    if not html_content:
        return html_content

    # Match base64 images in src attributes
    pattern = r'src="data:image/([^;]+);base64,([^"]+)"'

    def replace_image(match):
        image_type = match.group(1)
        base64_data = match.group(2)

        # Generate unique filename
        filename = f"{uuid.uuid4().hex}.{image_type}"

        # Ensure upload directory exists
        upload_dir = data_path("uploads")
        os.makedirs(upload_dir, exist_ok=True)

        # Save image to disk
        filepath = os.path.join(upload_dir, filename)
        try:
            image_data = base64.b64decode(base64_data)
            with open(filepath, "wb") as f:
                f.write(image_data)

            # Return URL to saved image
            return f'src="/uploads/{filename}"'
        except Exception:
            # If save fails, keep original
            return match.group(0)

    return re.sub(pattern, replace_image, html_content)


@tickets_bp.route("/api/tickets", methods=["POST"])
@protected
def create_ticket(user: User):
    """Create a new ticket"""
    data = request.get_json()

    if not data:
        return jsonify({"error": "No data provided"}), 400

    project_id = data.get("project")
    if not project_id:
        return jsonify({"error": "Project is required"}), 400

    # Verify project exists
    project = Project.get_or_none(Project.id == project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    # Generate ticket ID
    ticket_id = generate_unique_ticket_id(project_id)

    # Create ticket with defaults
    ticket = Ticket.create(
        id=ticket_id,
        title=data.get("title", ""),
        description=data.get("description", ""),
        status=data.get("status", "todo"),
        priority=data.get("priority", "medium"),
        project=project_id,
        created_at=int(time.time()),
    )

    # Create initial activity message
    TicketUpdateMessage.create(
        ticket=ticket_id,
        title="Created",
        icon="ph ph-plus",
        message=f"{user.username} created this ticket",
        created_at=int(time.time()),
    )

    # Auto assign ticket to creator
    UserTicketJoin.create(user=user.username, ticket=ticket_id)

    bus.emit(
        EventTypes.TICKET_CREATED,
        ticket_id=ticket.id,
        ticket_title=ticket.title,
        project=ticket.project,
        status=ticket.status,
        actor=user.username,
        details="Ticket created manually",
    )

    return (
        jsonify(
            {
                "success": True,
                "ticket": {
                    "id": ticket.id,
                    "title": ticket.title,
                    "project": ticket.project,
                    "status": ticket.status,
                    "priority": ticket.priority,
                },
            }
        ),
        201,
    )


@tickets_bp.route("/api/tickets/intake", methods=["POST"])
@protected
def create_intake_ticket(user: User):
    """Create a triage-first ticket used by PM workflows."""
    data = request.get_json(silent=True) or {}

    raw_project_id = data.get("project")
    requested_project_id = "" if raw_project_id is None else str(raw_project_id).strip()
    if requested_project_id.upper() == "TRIAGE":
        requested_project_id = ""
    if requested_project_id.lower() in {"none", "null"}:
        requested_project_id = ""

    project_id = "TRIAGE"
    if requested_project_id:
        project = Project.get_or_none(Project.id == requested_project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404
        project_id = requested_project_id

    title = str(data.get("title", "")).strip()
    description = str(data.get("description", "")).strip()
    possible_duplicates = _find_possible_duplicate_tickets(title, description)
    if _has_blocking_duplicate(possible_duplicates):
        return (
            jsonify(
                {
                    "error": "Possible duplicate ticket found",
                    "possible_duplicates": possible_duplicates,
                }
            ),
            409,
        )

    ticket_id = generate_unique_ticket_id(project_id)
    ticket = Ticket.create(
        id=ticket_id,
        title=title,
        description=description,
        status="triage",
        priority=data.get("priority", "medium"),
        project=project_id,
        created_at=int(time.time()),
    )

    TicketUpdateMessage.create(
        ticket=ticket_id,
        title="Intake created",
        icon="ph ph-tray",
        message=f"{user.username} created this ticket in triage",
        created_at=int(time.time()),
    )

    bus.emit(
        EventTypes.TICKET_TRIAGED,
        ticket_id=ticket.id,
        ticket_title=ticket.title,
        project=ticket.project,
        status=ticket.status,
        actor=user.username,
        details=(
            "Ticket entered triage inbox without project assignment"
            if ticket.project == "TRIAGE"
            else f"Ticket entered triage inbox for project {ticket.project}"
        ),
    )

    return (
        jsonify(
            {
                "success": True,
                "ticket": {
                    "id": ticket.id,
                    "title": ticket.title,
                    "project": ticket.project,
                    "status": ticket.status,
                    "priority": ticket.priority,
                },
            }
        ),
        201,
    )


def _collect_chat_user_context(history: list[dict], message: str) -> str:
    """Merge prior user chat turns and latest message into one intake context."""
    parts: list[str] = []

    for turn in history:
        if not isinstance(turn, dict):
            continue
        if str(turn.get("role", "")).strip().lower() != "user":
            continue
        content = str(turn.get("content", "")).strip()
        if content:
            parts.append(content)

    if message:
        parts.append(message)

    return "\n".join(parts).strip()


def _missing_intake_fields(chat_context: str) -> list[str]:
    """Heuristic required-field check for conversational intake readiness."""
    missing: list[str] = []
    lowered = chat_context.lower()
    words = [token for token in re.split(r"\s+", chat_context) if token]

    if len(words) < 8:
        missing.append("context_details")

    impact_tokens = {
        "urgent",
        "critical",
        "outage",
        "blocked",
        "blocking",
        "impact",
        "cannot",
        "can't",
        "fails",
        "failure",
        "production",
        "customer",
    }
    if not any(token in lowered for token in impact_tokens):
        missing.append("impact")

    return missing


def _build_follow_up_message(missing_fields: list[str], draft: dict) -> str:
    """Generate the assistant response for the next chat turn."""
    if not missing_fields:
        target = draft.get("suggested_project") or "triage"
        return (
            f"I have enough to draft this ticket (title: {draft.get('title', 'Untitled')}). "
            f"Proposed destination: {target}. Confirm and I can create it."
        )

    questions: list[str] = []
    if "context_details" in missing_fields:
        questions.append("Can you share a bit more context (steps, scope, or examples)?")
    if "impact" in missing_fields:
        questions.append("What is the urgency or user/business impact?")
    if "confidence" in missing_fields:
        questions.append("I can draft this, but confidence is low. Can you share one more detail so I can improve accuracy?")

    return " ".join(questions)


def _chat_missing_fields(chat_context: str, draft: dict) -> list[str]:
    """Determine whether follow-up is needed for chat intake.

    If AI returned a high-confidence structured draft, treat it as ready and avoid
    forcing heuristic questions. Fall back to heuristic checks for non-AI drafts
    or low-confidence AI output.
    """
    source = str(draft.get("source", "")).strip().lower()
    title = str(draft.get("title", "")).strip()
    description = str(draft.get("description", "")).strip()
    confidence_raw = draft.get("confidence", 0.0)
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = 0.0

    if source == "ai":
        if not title or len(title) < 4 or not description or len(description) < 12:
            return ["context_details"]
        if confidence < 0.55:
            return ["confidence"]
        return []

    return _missing_intake_fields(chat_context)


def _normalize_similarity_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())).strip()


def _token_set(text: str) -> set[str]:
    return {token for token in _normalize_similarity_text(text).split(" ") if len(token) > 2}


def _combined_similarity(title_a: str, desc_a: str, title_b: str, desc_b: str) -> float:
    normalized_title_a = _normalize_similarity_text(title_a)
    normalized_title_b = _normalize_similarity_text(title_b)
    normalized_desc_a = _normalize_similarity_text(desc_a)[:800]
    normalized_desc_b = _normalize_similarity_text(desc_b)[:800]

    if not normalized_title_a or not normalized_title_b:
        return 0.0

    title_ratio = SequenceMatcher(None, normalized_title_a, normalized_title_b).ratio()
    desc_ratio = (
        SequenceMatcher(None, normalized_desc_a, normalized_desc_b).ratio()
        if normalized_desc_a and normalized_desc_b
        else 0.0
    )

    tokens_a = _token_set(f"{normalized_title_a} {normalized_desc_a}")
    tokens_b = _token_set(f"{normalized_title_b} {normalized_desc_b}")
    token_overlap = 0.0
    if tokens_a and tokens_b:
        token_overlap = len(tokens_a & tokens_b) / len(tokens_a | tokens_b)

    return max(
        title_ratio,
        0.65 * title_ratio + 0.35 * token_overlap,
        0.5 * title_ratio + 0.25 * desc_ratio + 0.25 * token_overlap,
    )


def _find_possible_duplicate_tickets(title: str, description: str, limit: int = 3) -> list[dict]:
    normalized_title = _normalize_similarity_text(title)
    if not normalized_title:
        return []

    matches: list[dict] = []
    candidates = (
        Ticket.select()
        .where(Ticket.active == 1)
        .order_by(Ticket.created_at.desc())
        .limit(400)
    )

    for candidate in candidates:
        score = _combined_similarity(
            title,
            description,
            candidate.title or "",
            candidate.description or "",
        )
        if score < 0.74:
            continue
        matches.append(
            {
                "id": candidate.id,
                "title": candidate.title,
                "project": candidate.project,
                "status": candidate.status,
                "score": round(score, 4),
            }
        )

    matches.sort(key=lambda row: row.get("score", 0), reverse=True)
    return matches[:limit]


def _has_blocking_duplicate(possible_duplicates: list[dict]) -> bool:
    if not possible_duplicates:
        return False
    top_score = float(possible_duplicates[0].get("score") or 0)
    return top_score >= 0.86


@tickets_bp.route("/api/tickets/intake/ai/chat", methods=["POST"])
@protected
def chat_ai_intake_ticket(user: User):
    """Conversational AI intake step that gathers details before commit."""
    data = request.get_json(silent=True) or {}
    message = str(data.get("message", "")).strip()

    if not message:
        return jsonify({"error": "Message is required"}), 400

    history_raw = data.get("history") or []
    history = history_raw if isinstance(history_raw, list) else []
    chat_context = _collect_chat_user_context(history, message)

    projects = [
        {"id": project.id, "name": project.name}
        for project in Project.select().order_by(Project.name)
    ]
    draft = suggest_intake_from_message(chat_context, projects)

    missing_fields = _chat_missing_fields(chat_context, draft)
    possible_duplicates = _find_possible_duplicate_tickets(
        str(draft.get("title", "")),
        str(draft.get("description", "")),
    )
    has_blocking_duplicate = _has_blocking_duplicate(possible_duplicates)
    if has_blocking_duplicate:
        missing_fields = [*missing_fields, "possible_duplicate"]

    ready_to_commit = len(missing_fields) == 0
    assistant_message = _build_follow_up_message(missing_fields, draft)
    if has_blocking_duplicate:
        top = possible_duplicates[0]
        assistant_message = (
            f"This looks very similar to {top.get('id')} ({top.get('title')}). "
            "Please review likely duplicates before creating a new ticket."
        )

    return (
        jsonify(
            {
                "success": True,
                "reply": {
                    "message": assistant_message,
                    "draft": draft,
                    "missing_fields": missing_fields,
                    "possible_duplicates": possible_duplicates,
                    "ready_to_commit": ready_to_commit,
                },
            }
        ),
        200,
    )


@tickets_bp.route("/api/tickets/intake/ai/suggest", methods=["POST"])
@protected
def suggest_intake_ticket(user: User):
    """Suggest project/priority/title from free-form intake text."""
    data = request.get_json(silent=True) or {}
    message = str(data.get("message", "")).strip()

    if not message:
        return jsonify({"error": "Message is required"}), 400

    projects = [
        {"id": project.id, "name": project.name}
        for project in Project.select().order_by(Project.name)
    ]
    suggestion = suggest_intake_from_message(message, projects)

    return jsonify({"success": True, "suggestion": suggestion}), 200


@tickets_bp.route("/api/tickets/intake/ai/commit", methods=["POST"])
@protected
def commit_ai_intake_ticket(user: User):
    """Create a ticket from an AI suggestion after explicit user confirmation."""
    data = request.get_json(silent=True) or {}
    suggestion = data.get("suggestion") or {}
    destination = str(data.get("destination", "triage")).strip().lower()

    title = str(suggestion.get("title", "")).strip()
    if not title:
        return jsonify({"error": "Suggestion title is required"}), 400

    description = str(suggestion.get("description", "")).strip()
    possible_duplicates = _find_possible_duplicate_tickets(title, description)
    if _has_blocking_duplicate(possible_duplicates):
        return (
            jsonify(
                {
                    "error": "Possible duplicate ticket found",
                    "possible_duplicates": possible_duplicates,
                }
            ),
            409,
        )

    priority = str(suggestion.get("priority", "medium")).strip().lower()
    if priority not in {"urgent", "high", "medium", "low", "none"}:
        priority = "medium"

    if destination == "project":
        project_id = str(
            data.get("project")
            or suggestion.get("suggested_project")
            or ""
        ).strip()
        if not project_id:
            return jsonify({"error": "Project is required for project destination"}), 400

        project = Project.get_or_none(Project.id == project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404

        ticket_id = generate_unique_ticket_id(project_id)
        ticket = Ticket.create(
            id=ticket_id,
            title=title,
            description=description,
            status="backlog",
            priority=priority,
            project=project_id,
            created_at=int(time.time()),
        )

        TicketUpdateMessage.create(
            ticket=ticket_id,
            title="Created",
            icon="ph ph-plus",
            message=f"{user.username} created this ticket from AI intake",
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
            details="Ticket created from AI intake",
        )

        return jsonify(
            {
                "success": True,
                "ticket": {
                    "id": ticket.id,
                    "title": ticket.title,
                    "project": ticket.project,
                    "status": ticket.status,
                    "priority": ticket.priority,
                },
            }
        ), 201

    if destination != "triage":
        return jsonify({"error": "Unknown destination"}), 400

    ticket_id = generate_unique_ticket_id("TRIAGE")
    ticket = Ticket.create(
        id=ticket_id,
        title=title,
        description=description,
        status="triage",
        priority=priority,
        project="TRIAGE",
        created_at=int(time.time()),
    )

    TicketUpdateMessage.create(
        ticket=ticket_id,
        title="Intake created",
        icon="ph ph-tray",
        message=f"{user.username} created this ticket from AI intake",
        created_at=int(time.time()),
    )

    bus.emit(
        EventTypes.TICKET_TRIAGED,
        ticket_id=ticket.id,
        ticket_title=ticket.title,
        project=ticket.project,
        status=ticket.status,
        actor=user.username,
        details="Ticket entered triage inbox from AI intake",
    )

    return jsonify(
        {
            "success": True,
            "ticket": {
                "id": ticket.id,
                "title": ticket.title,
                "project": ticket.project,
                "status": ticket.status,
                "priority": ticket.priority,
            },
        }
    ), 201


@tickets_bp.route("/api/tickets/<ticket_id>", methods=["PUT", "PATCH"])
@protected
def update_ticket(user: User, ticket_id: str):  # noqa: C901
    """Update a ticket field"""
    data = request.get_json()

    if not data:
        return jsonify({"error": "No data provided"}), 400

    ticket = Ticket.get_or_none(Ticket.id == ticket_id)
    if not ticket:
        return jsonify({"error": "Ticket not found"}), 404

    field = data.get("field")
    value = data.get("value")
    # old_value = data.get("oldValue")

    if not field:
        return jsonify({"error": "Field is required"}), 400

    # Rate limit for update messages (10 minutes = 600 seconds)
    UPDATE_MESSAGE_COOLDOWN = 600

    def should_create_update_message(ticket_id: str, title: str) -> bool:
        """Check if enough time has passed since the last update message of this type"""
        last_update = (
            TicketUpdateMessage.select()
            .where((TicketUpdateMessage.ticket == ticket_id) & (TicketUpdateMessage.title == title))
            .order_by(TicketUpdateMessage.created_at.desc())
            .first()
        )

        if not last_update:
            return True

        return int(time.time()) - last_update.created_at >= UPDATE_MESSAGE_COOLDOWN

    # Handle different field types
    if field == "title":
        ticket.title = value
        ticket.save()

        # Rate-limited update message
        if should_create_update_message(ticket_id, "Title changed"):
            TicketUpdateMessage.create(
                ticket=ticket_id,
                title="Title changed",
                icon="ph ph-pencil",
                message=f"{user.username} changed the title",
                created_at=int(time.time()),
            )

    elif field == "description":
        # Extract and save base64 images
        processed_description = extract_and_save_images(value)

        if processed_description == ticket.description:
            return jsonify({"success": True})

        ticket.description = processed_description
        ticket.save()

        # Rate-limited update message
        if should_create_update_message(ticket_id, "Description updated"):
            TicketUpdateMessage.create(
                ticket=ticket_id,
                title="Description updated",
                icon="ph ph-note-pencil",
                message=f"{user.username} updated the description",
                created_at=int(time.time()),
            )

    elif field == "status":
        old_status = ticket.status
        if (
            old_status == "triage"
            and value != "triage"
            and (not ticket.project or ticket.project == "TRIAGE")
        ):
            return jsonify({"error": "Assign a project before moving ticket out of triage"}), 400

        ticket.status = value
        ticket.save()

        TicketUpdateMessage.create(
            ticket=ticket_id,
            title="Status changed",
            icon="ph ph-arrow-right",
            message=f"{user.username} changed status from {old_status} to {value}",
            created_at=int(time.time()),
        )

        bus.emit(
            EventTypes.TICKET_STATUS_CHANGED,
            ticket_id=ticket.id,
            ticket_title=ticket.title,
            project=ticket.project,
            status=value,
            actor=user.username,
            details=f"Status changed from {old_status} to {value}",
        )

    elif field == "project":
        target_project = str(value or "").strip()
        if not target_project:
            return jsonify({"error": "Project is required"}), 400

        project = Project.get_or_none(Project.id == target_project)
        if not project:
            return jsonify({"error": "Project not found"}), 404

        old_project = ticket.project
        ticket.project = target_project
        ticket.save()

        TicketUpdateMessage.create(
            ticket=ticket_id,
            title="Project changed",
            icon="ph ph-folder-simple",
            message=f"{user.username} changed project from {old_project} to {target_project}",
            created_at=int(time.time()),
        )

    elif field == "priority":
        old_priority = ticket.priority
        ticket.priority = value
        ticket.save()

        TicketUpdateMessage.create(
            ticket=ticket_id,
            title="Priority changed",
            icon="ph ph-cell-signal-full",
            message=f"{user.username} changed priority from {old_priority} to {value}",
            created_at=int(time.time()),
        )

    elif field == "assignees":
        # Value should be list of user objects with id property
        # Clear existing assignments
        UserTicketJoin.delete().where(UserTicketJoin.ticket == ticket_id).execute()

        # Add new assignments
        assigned_usernames = []
        if value:
            for assignee in value:
                user_id = assignee.get("id") if isinstance(assignee, dict) else assignee
                UserTicketJoin.create(user=user_id, ticket=ticket_id)
                assigned_usernames.append(user_id)

        TicketUpdateMessage.create(
            ticket=ticket_id,
            title="Assignees changed",
            icon="ph ph-users-three",
            message=f'{user.username} updated assignees to: {", ".join(assigned_usernames) if assigned_usernames else "unassigned"}',
            created_at=int(time.time()),
        )

    elif field == "labels":
        # Clear existing labels
        TicketLabelJoin.delete().where(TicketLabelJoin.ticket == ticket_id).execute()

        # Add new labels
        label_names = []
        if value:
            for label in value:
                label_name = label.get("name") if isinstance(label, dict) else label
                TicketLabelJoin.create(ticket=ticket_id, label=label_name)
                label_names.append(label_name)

        TicketUpdateMessage.create(
            ticket=ticket_id,
            title="Labels changed",
            icon="ph ph-tag",
            message=f'{user.username} updated labels to: {", ".join(label_names) if label_names else "none"}',
            created_at=int(time.time()),
        )

    else:
        return jsonify({"error": f"Unknown field: {field}"}), 400

    return jsonify({"success": True})


@tickets_bp.route("/api/tickets/<ticket_id>/comments", methods=["POST"])
@protected
def add_comment(user: User, ticket_id: str):
    """Add a comment to a ticket"""
    data = request.get_json()

    if not data:
        return jsonify({"error": "No data provided"}), 400

    ticket = Ticket.get_or_none(Ticket.id == ticket_id)
    if not ticket:
        return jsonify({"error": "Ticket not found"}), 404

    content = data.get("content", "")
    if not content.strip():
        return jsonify({"error": "Comment content is required"}), 400

    # Extract and save any images in the comment
    processed_content = extract_and_save_images(content)

    comment = Comment.create(
        ticket=ticket_id, user=user.username, body=processed_content, created_at=int(time.time())
    )

    bus.emit(
        EventTypes.TICKET_COMMENTED,
        ticket_id=ticket.id,
        ticket_title=ticket.title,
        project=ticket.project,
        status=ticket.status,
        actor=user.username,
        details=(processed_content[:180] + "...") if len(processed_content) > 180 else processed_content,
    )

    return (
        jsonify(
            {
                "success": True,
                "comment": {
                    "id": comment.id,
                    "user": user.username,
                    "body": comment.body,
                    "created_at": comment.created_at,
                },
            }
        ),
        201,
    )


@tickets_bp.route("/api/comments/<int:comment_id>", methods=["DELETE"])
@protected
def delete_comment(user: User, comment_id: int):
    """Delete a comment"""
    comment = Comment.get_or_none(Comment.id == comment_id)
    if not comment:
        return jsonify({"error": "Comment not found"}), 404

    # Only allow the comment author or admin to delete
    if comment.user.username != user.username and not user.admin:
        return jsonify({"error": "Not authorized"}), 403

    comment.delete_instance()

    return jsonify({"success": True})


@tickets_bp.route("/api/projects", methods=["GET"])
@protected
def get_projects(user: User):
    """Get all projects for the dropdown"""
    projects = Project.select().order_by(Project.name)

    return jsonify(
        {
            "projects": [
                {"id": p.id, "name": p.name, "icon": p.icon, "color": p.color} for p in projects
            ]
        }
    )


@tickets_bp.route("/api/search", methods=["GET"])
@protected
def api_search(user: User):
    """Global search for active tickets by id/title."""
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"results": []}), 200

    try:
        limit = int(request.args.get("limit", 12))
    except ValueError:
        limit = 12
    limit = max(1, min(limit, 50))

    matches = (
        Ticket.select()
        .where(
            (Ticket.active == 1)
            & ((Ticket.id.contains(query)) | (Ticket.title.contains(query)))
        )
        .order_by(Ticket.created_at.desc())
        .limit(limit)
    )

    results = [
        {
            "id": ticket.id,
            "title": ticket.title,
            "project": ticket.project,
            "status": ticket.status,
            "priority": ticket.priority,
            "url": f"/tickets/{ticket.project}/{ticket.id}",
        }
        for ticket in matches
    ]

    return jsonify({"results": results}), 200


@tickets_bp.route("/api/tickets/<ticket_id>/export", methods=["GET"])
@protected
def export_ticket(user: User, ticket_id: str):
    """Export a ticket as JSON or Markdown."""
    ticket = Ticket.get_or_none(Ticket.id == ticket_id)
    if not ticket or ticket.active == 0:
        return jsonify({"error": "Ticket not found"}), 404

    comments = list(Comment.select().where(Comment.ticket == ticket_id).order_by(Comment.created_at.asc()))
    updates = list(
        TicketUpdateMessage.select()
        .where(TicketUpdateMessage.ticket == ticket_id)
        .order_by(TicketUpdateMessage.created_at.asc())
    )
    labels = [row.label for row in TicketLabelJoin.select().where(TicketLabelJoin.ticket == ticket_id)]
    assignees = [row.user for row in UserTicketJoin.select().where(UserTicketJoin.ticket == ticket_id)]

    payload = {
        "id": ticket.id,
        "title": ticket.title,
        "description": ticket.description,
        "project": ticket.project,
        "status": ticket.status,
        "priority": ticket.priority,
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
    }

    export_format = str(request.args.get("format", "markdown")).strip().lower()
    if export_format in {"json", "application/json"}:
        return jsonify(payload), 200

    if export_format not in {"md", "markdown", "text/markdown"}:
        return jsonify({"error": "Unsupported export format"}), 400

    markdown_lines = [
        f"# Ticket {ticket.id}",
        "",
        f"- Title: {ticket.title}",
        f"- Project: {ticket.project}",
        f"- Status: {ticket.status}",
        f"- Priority: {ticket.priority}",
        f"- Created At (epoch): {ticket.created_at}",
        f"- Labels: {', '.join(labels) if labels else 'None'}",
        f"- Assignees: {', '.join(assignees) if assignees else 'None'}",
        "",
        "## Description",
        "",
        ticket.description or "",
        "",
        "## Comments",
        "",
    ]

    if comments:
        for comment in comments:
            markdown_lines.extend(
                [
                    f"### {comment.user.username} ({comment.created_at})",
                    "",
                    comment.body or "",
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
            markdown_lines.extend(
                [
                    f"- **{update.title}** ({update.created_at}): {update.message}",
                ]
            )
    else:
        markdown_lines.append("No updates.")

    content = "\n".join(markdown_lines)
    return content, 200, {"Content-Type": "text/markdown; charset=utf-8"}


@tickets_bp.route("/uploads/<path:filename>", methods=["GET"])
@protected
def get_uploads(user: User, filename: str):
    """Get all uploads for the user (placeholder)"""

    return send_file(data_path("uploads", filename))


@tickets_bp.route("/api/tickets/<ticket_id>", methods=["DELETE"])
@protected
def delete_ticket(user: User, ticket_id: str):
    """Soft delete a ticket"""
    ticket = Ticket.get_or_none(Ticket.id == ticket_id)

    if not ticket:
        return jsonify({"error": "Ticket not found"}), 404

    ticket.active = 0
    ticket.save()

    # Log deletion?
    TicketUpdateMessage.create(
        ticket=ticket_id,
        title="Ticket deleted",
        icon="ph ph-trash",
        message=f"{user.username} deleted this ticket",
        created_at=int(time.time()),
    )

    return jsonify({"success": True})


@tickets_bp.route("/api/tickets/<ticket_id>/restore", methods=["POST"])
@protected
def restore_ticket(user: User, ticket_id: str):
    """Restore a soft-deleted ticket"""
    ticket = Ticket.get_or_none(Ticket.id == ticket_id)

    if not ticket:
        return jsonify({"error": "Ticket not found"}), 404

    ticket.active = 1
    ticket.save()

    TicketUpdateMessage.create(
        ticket=ticket_id,
        title="Ticket restored",
        icon="ph ph-arrow-u-up-left",
        message=f"{user.username} restored this ticket",
        created_at=int(time.time()),
    )

    return jsonify({"success": True})


@tickets_bp.route("/api/tickets/<ticket_id>/hard", methods=["DELETE"])
@protected
def delete_ticket_hard(user: User, ticket_id: str):
    """Hard delete a ticket and all its associations"""
    ticket = Ticket.get_or_none(Ticket.id == ticket_id)

    if not ticket:
        return jsonify({"error": "Ticket not found"}), 404

    # Delete all associations manually since we use CharField IDs
    Comment.delete().where(Comment.ticket == ticket_id).execute()
    TicketUpdateMessage.delete().where(TicketUpdateMessage.ticket == ticket_id).execute()
    UserTicketJoin.delete().where(UserTicketJoin.ticket == ticket_id).execute()
    TicketLabelJoin.delete().where(TicketLabelJoin.ticket == ticket_id).execute()

    # Finally delete the ticket
    ticket.delete_instance()

    return jsonify({"success": True})
