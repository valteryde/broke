import base64
import os
import re
import time
import uuid
from difflib import SequenceMatcher

from flask import Blueprint, jsonify, redirect, render_template, request, send_file

from ..utils.ai_changelog import get_ai_config
from ..utils.ai_delegate_handoff import build_ai_delegate_pack_markdown, mint_ticket_delegate_token
from ..utils.ai_intake import suggest_intake_from_message
from ..utils.events import EventTypes, bus
from ..utils.models import (
    Comment,
    Label,
    Project,
    Ticket,
    TicketLabelJoin,
    TicketUpdateMessage,
    User,
    UserSettings,
    UserTicketJoin,
    WorkCycle,
)
from ..utils.path import data_path
from ..utils.security import protected
from ..utils.ticket_markdown import build_ticket_export_payload, ticket_payload_to_markdown

# Create blueprint
tickets_bp = Blueprint("tickets", __name__)

INTAKE_STATUSES = {"intake", "triage"}


def _work_cycles_for_scope(project_id: str | None) -> list:
    """All sprints are workspace-wide; tickets from any project may join."""
    return list(WorkCycle.select().order_by(WorkCycle.created_at.desc()))


def _is_intake_status(value: str | None) -> bool:
    return str(value or "").strip().lower() in INTAKE_STATUSES


from typing import Any

from peewee import prefetch


def populateTickets(tickets_or_query: list[Ticket] | Any, lite: bool = False) -> None:
    """
    Populates the tickets with labels, assignees, and optionally comments/updates.
    Uses manual batched queries to avoid N+1 problems because the schema uses
    CharField for relationships instead of ForeignKeyField.
    """
    if not tickets_or_query:
        return

    # If it's a query, we execute it to get a list
    if not isinstance(tickets_or_query, list):
        tickets = list(tickets_or_query)
    else:
        tickets = tickets_or_query

    if not tickets:
        return

    ticket_dict = {t.id: t for t in tickets if getattr(t, "id", None)}
    ticket_ids = list(ticket_dict.keys())

    # Initialize empty lists safely
    for t in tickets:
        t.labels = getattr(t, "labels", [])
        t.assignees = getattr(t, "assignees", [])
        t.comments = getattr(t, "comments", [])
        t.updates = getattr(t, "updates", [])

    # 1. Bulk Assignees
    utjs = UserTicketJoin.select().where(UserTicketJoin.ticket.in_(ticket_ids))
    user_ids = [utj.user for utj in utjs]
    if user_ids:
        users = {u.username: u for u in User.select().where(User.username.in_(user_ids))}
        for utj in utjs:
            if utj.ticket in ticket_dict and utj.user in users:
                ticket_dict[utj.ticket].assignees.append(users[utj.user])

    # 2. Bulk Labels
    tljs = TicketLabelJoin.select().where(TicketLabelJoin.ticket.in_(ticket_ids))
    label_ids = [tlj.label for tlj in tljs]
    if label_ids:
        labels = {l.name: l for l in Label.select().where(Label.name.in_(label_ids))}
        for tlj in tljs:
            if tlj.ticket in ticket_dict and tlj.label in labels:
                ticket_dict[tlj.ticket].labels.append(labels[tlj.label])

    if not lite:
        # 3. Bulk Comments
        comments = Comment.select().where(Comment.ticket.in_(ticket_ids)).order_by(Comment.id)
        for c in comments:
            if getattr(c, "ticket", None) in ticket_dict:
                ticket_dict[c.ticket].comments.append(c)

        # 4. Bulk Updates
        updates = (
            TicketUpdateMessage.select()
            .where(TicketUpdateMessage.ticket.in_(ticket_ids))
            .order_by(TicketUpdateMessage.id)
        )
        for u in updates:
            if getattr(u, "ticket", None) in ticket_dict:
                ticket_dict[u.ticket].updates.append(u)


def populate_ticket_board_meta(tickets: list[Ticket]) -> None:
    """Attach subticket rollup fields used by Kanban cards."""
    if not tickets:
        return

    ticket_ids = [ticket.id for ticket in tickets if getattr(ticket, "id", None)]
    if not ticket_ids:
        return

    subtickets = list(
        Ticket.select(Ticket.parent_ticket_id, Ticket.status).where(
            (Ticket.parent_ticket_id.in_(ticket_ids)) & (Ticket.active == 1)
        )
    )

    counts: dict[str, int] = {ticket_id: 0 for ticket_id in ticket_ids}
    done_counts: dict[str, int] = {ticket_id: 0 for ticket_id in ticket_ids}
    closed_statuses = {"done", "closed"}

    for child in subtickets:
        parent_id = str(child.parent_ticket_id or "")
        if not parent_id:
            continue
        counts[parent_id] = counts.get(parent_id, 0) + 1
        if child.status in closed_statuses:
            done_counts[parent_id] = done_counts.get(parent_id, 0) + 1

    for ticket in tickets:
        ticket.subticket_count = counts.get(ticket.id, 0)  # type: ignore[attr-defined]
        ticket.subticket_done_count = done_counts.get(ticket.id, 0)  # type: ignore[attr-defined]


def resolve_ticket_view(user: User) -> str:
    explicit = request.args.get("view", "").strip().lower()
    if explicit in {"list", "board"}:
        return explicit

    settings = UserSettings.get_or_none(UserSettings.user == user.username)
    if settings and settings.default_ticket_view in {"list", "board"}:
        return settings.default_ticket_view

    return "list"


def strip_html(text: str) -> str:
    """Very simple HTML tag stripper."""
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", text)


def lite_populate(tickets: list[Ticket]) -> None:
    """Helper to prepare tickets for overview lists with minimal payload."""
    populateTickets(tickets, lite=True)
    for t in tickets:
        # Strip HTML and truncate description for list view
        cleaned = strip_html(t.description or "")
        if len(cleaned) > 500:
            t.description = cleaned[:500] + "..."
        else:
            t.description = cleaned


@tickets_bp.route("/tickets")
@protected
def tickets_view(user: User):
    tickets = list(
        Ticket.select().where((Ticket.active == 1) & (~(Ticket.status.in_(INTAKE_STATUSES))))
    )
    lite_populate(tickets)
    populate_ticket_board_meta(tickets)
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
        available_work_cycles=_work_cycles_for_scope(None),
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
            (Ticket.project == project_id)
            & (Ticket.active == 1)
            & (~(Ticket.status.in_(INTAKE_STATUSES)))
        )
    )
    lite_populate(tickets)
    populate_ticket_board_meta(tickets)
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
        available_work_cycles=_work_cycles_for_scope(project_id),
        ticket_view=ticket_view,
        ticket_view_path=f"/tickets/{project_id}",
        ticket_page_title="Tickets",
        ticket_create_endpoint="/api/tickets",
        ticket_create_status="backlog",
        ticket_base_path="/tickets",
    )


@tickets_bp.route("/triage")
@tickets_bp.route("/intake")
@protected
def triage_view(user: User):
    tickets = list(
        Ticket.select()
        .where((Ticket.active == 1) & (Ticket.status.in_(INTAKE_STATUSES)))
        .order_by(Ticket.created_at.asc())
    )
    lite_populate(tickets)

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
        ticket_view_path="/intake",
        ticket_page_title="Intake Inbox",
        ticket_create_endpoint="/api/tickets/intake",
        ticket_create_status="intake",
        ticket_base_path="/intake",
        ai_intake_enabled=get_ai_config() is not None,
    )


@tickets_bp.route("/triage/<project_id>")
@tickets_bp.route("/intake/<project_id>")
@protected
def triage_project_view(user: User, project_id: str):
    project = Project.get_or_none(Project.id == project_id)
    tickets = list(
        Ticket.select()
        .where(
            (Ticket.project == project_id)
            & (Ticket.active == 1)
            & (Ticket.status.in_(INTAKE_STATUSES))
        )
        .order_by(Ticket.created_at.asc())
    )
    lite_populate(tickets)

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
        ticket_view_path=f"/intake/{project_id}",
        ticket_page_title="Intake Inbox",
        ticket_create_endpoint="/api/tickets/intake",
        ticket_create_status="intake",
        ticket_base_path="/intake",
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
    subtickets = list(
        Ticket.select()
        .where((Ticket.parent_ticket_id == ticket_id) & (Ticket.active == 1))
        .order_by(Ticket.created_at.asc())
    )

    subticket_count = len(subtickets)
    closed_statuses = {"done", "closed"}
    subticket_done_count = sum(1 for child in subtickets if child.status in closed_statuses)
    all_subtickets_done = subticket_count > 0 and subticket_done_count == subticket_count

    parent_ticket = None
    if ticket.parent_ticket_id:
        parent_ticket = Ticket.get_or_none(Ticket.id == ticket.parent_ticket_id)

    work_cycles = list(WorkCycle.select().order_by(WorkCycle.created_at.desc()))

    return render_template(
        "ticket.jinja2",
        user=user,
        ticket=ticket,
        project=Project.get_or_none(Project.id == project_id),
        page="tickets",
        available_users=available_users,
        available_labels=available_labels,
        available_work_cycles=work_cycles,
        comments=comments,
        updates=updates,
        subtickets=subtickets,
        parent_ticket=parent_ticket,
        subticket_count=subticket_count,
        subticket_done_count=subticket_done_count,
        all_subtickets_done=all_subtickets_done,
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

    requested_project_id = str(data.get("project") or "").strip()
    parent_ticket_id = str(data.get("parent_ticket_id") or "").strip() or None

    parent_ticket = None
    if parent_ticket_id:
        parent_ticket = Ticket.get_or_none((Ticket.id == parent_ticket_id) & (Ticket.active == 1))
        if not parent_ticket:
            return jsonify({"error": "Parent ticket not found"}), 404
        if parent_ticket.parent_ticket_id:
            return jsonify({"error": "Only one subticket level is supported"}), 400

    project_id = requested_project_id
    if parent_ticket:
        if requested_project_id and requested_project_id != parent_ticket.project:
            return jsonify({"error": "Subticket project must match parent project"}), 400
        project_id = parent_ticket.project

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
        parent_ticket_id=parent_ticket_id,
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
                    "parent_ticket_id": ticket.parent_ticket_id,
                },
            }
        ),
        201,
    )


@tickets_bp.route("/api/tickets/intake", methods=["POST"])
@protected
def create_intake_ticket(user: User):
    """Create an intake-first ticket used by PM workflows."""
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
        status="intake",
        priority=data.get("priority", "medium"),
        project=project_id,
        created_at=int(time.time()),
    )

    TicketUpdateMessage.create(
        ticket=ticket_id,
        title="Intake created",
        icon="ph ph-tray",
        message=f"{user.username} created this ticket in intake",
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
            "Ticket entered intake inbox without project assignment"
            if ticket.project == "TRIAGE"
            else f"Ticket entered intake inbox for project {ticket.project}"
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
        target = draft.get("suggested_project") or "intake"
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
        questions.append(
            "I can draft this, but confidence is low. Can you share one more detail so I can improve accuracy?"
        )

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
        Ticket.select().where(Ticket.active == 1).order_by(Ticket.created_at.desc()).limit(400)
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
    destination = str(data.get("destination", "intake")).strip().lower()

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
        project_id = str(data.get("project") or suggestion.get("suggested_project") or "").strip()
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

    if destination == "triage":
        destination = "intake"

    if destination != "intake":
        return jsonify({"error": "Unknown destination"}), 400

    ticket_id = generate_unique_ticket_id("TRIAGE")
    ticket = Ticket.create(
        id=ticket_id,
        title=title,
        description=description,
        status="intake",
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
        details="Ticket entered intake inbox from AI intake",
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
            _is_intake_status(old_status)
            and (not _is_intake_status(value))
            and (not ticket.project or ticket.project == "TRIAGE")
        ):
            return jsonify({"error": "Assign a project before moving ticket out of intake"}), 400

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

        if ticket.parent_ticket_id:
            parent = Ticket.get_or_none(Ticket.id == ticket.parent_ticket_id)
            if parent and parent.project != target_project:
                return jsonify({"error": "Subticket project must match parent project"}), 400

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

    elif field == "ai_delegate":
        if value in (True, 1, "1", "true", "yes"):
            on = True
        elif value in (False, 0, "0", "false", "no", None, "", "null"):
            on = False
        else:
            return jsonify({"error": "ai_delegate must be true or false"}), 400

        prev = int(getattr(ticket, "ai_delegate", 0) or 0)
        ticket.ai_delegate = 1 if on else 0

        if on and prev == 0:
            if ticket.status in {"backlog", "intake", "triage"}:
                old_status = ticket.status
                ticket.status = "todo"
                TicketUpdateMessage.create(
                    ticket=ticket_id,
                    title="Status changed",
                    icon="ph ph-arrow-right",
                    message=f"{user.username} set status from {old_status} to todo (Let AI do it)",
                    created_at=int(time.time()),
                )
                bus.emit(
                    EventTypes.TICKET_STATUS_CHANGED,
                    ticket_id=ticket.id,
                    ticket_title=ticket.title,
                    project=ticket.project,
                    status="todo",
                    actor=user.username,
                    details="Moved to todo for external AI handoff",
                )
            TicketUpdateMessage.create(
                ticket=ticket_id,
                title="External AI",
                icon="ph ph-robot",
                message=f"{user.username} enabled Let AI do it — copy API handoff from the ticket sidebar",
                created_at=int(time.time()),
            )
        elif not on and prev == 1:
            TicketUpdateMessage.create(
                ticket=ticket_id,
                title="External AI",
                icon="ph ph-robot",
                message=f"{user.username} turned off Let AI do it",
                created_at=int(time.time()),
            )

        ticket.save()
        return jsonify(
            {
                "success": True,
                "ticket": {
                    "status": ticket.status,
                    "ai_delegate": bool(ticket.ai_delegate),
                },
            }
        )

    elif field == "work_cycle_id":
        if value is None or value == "" or value == "null":
            if ticket.work_cycle_id:
                TicketUpdateMessage.create(
                    ticket=ticket_id,
                    title="Removed from work cycle",
                    icon="ph ph-calendar-x",
                    message=f"{user.username} removed this ticket from the work cycle",
                    created_at=int(time.time()),
                )
            ticket.work_cycle_id = None
            ticket.save()
        else:
            try:
                cid = int(value)
            except (TypeError, ValueError):
                return jsonify({"error": "work_cycle_id must be an integer or null"}), 400
            cycle = WorkCycle.get_or_none(WorkCycle.id == cid)
            if not cycle:
                return jsonify({"error": "Work cycle not found"}), 404
            old_cid = ticket.work_cycle_id
            ticket.work_cycle_id = cid
            ticket.save()
            msg = f"{user.username} set work cycle to {cycle.name} (#{cid})"
            if old_cid and old_cid != cid:
                msg = f"{user.username} moved this ticket to work cycle {cycle.name} (#{cid})"
            TicketUpdateMessage.create(
                ticket=ticket_id,
                title="Work cycle changed",
                icon="ph ph-calendar",
                message=msg,
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
        details=(processed_content[:180] + "...")
        if len(processed_content) > 180
        else processed_content,
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
            (Ticket.active == 1) & ((Ticket.id.contains(query)) | (Ticket.title.contains(query)))
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


@tickets_bp.route("/api/tickets/<ticket_id>/ai-delegate-pack", methods=["POST"])
@protected
def ticket_ai_delegate_pack(user: User, ticket_id: str):
    """
    One paste for an external AI: full ticket export + minted Bearer token + working curl one-liners.
    Mints a new ticket-scoped agent token on each call (revoke extras under Settings → Agent tokens).
    """
    ticket = Ticket.get_or_none((Ticket.id == ticket_id) & (Ticket.active == 1))
    if not ticket:
        return jsonify({"error": "Ticket not found"}), 404
    if not int(getattr(ticket, "ai_delegate", 0) or 0):
        return (
            jsonify({"error": "Turn on “Let AI do it” on this ticket first"}),
            400,
        )
    payload = build_ticket_export_payload(ticket_id)
    if not payload:
        return jsonify({"error": "Ticket not found"}), 404
    raw, row = mint_ticket_delegate_token(user=user, ticket=ticket)
    base = request.url_root or "/"
    text = build_ai_delegate_pack_markdown(
        payload=payload,
        base_url=base,
        bearer_token=raw,
        expires_at_epoch=row.expires_at,
    )
    return (
        text,
        200,
        {
            "Content-Type": "text/markdown; charset=utf-8",
            "X-Agent-Token-Id": str(row.id),
        },
    )


@tickets_bp.route("/api/tickets/<ticket_id>/export", methods=["GET"])
@protected
def export_ticket(user: User, ticket_id: str):
    """Export a ticket as JSON or Markdown."""
    payload = build_ticket_export_payload(ticket_id)
    if not payload:
        return jsonify({"error": "Ticket not found"}), 404

    export_format = str(request.args.get("format", "markdown")).strip().lower()
    if export_format in {"json", "application/json"}:
        return jsonify(payload), 200

    if export_format not in {"md", "markdown", "text/markdown"}:
        return jsonify({"error": "Unsupported export format"}), 400

    content = ticket_payload_to_markdown(payload)
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
