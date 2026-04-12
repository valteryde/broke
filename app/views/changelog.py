"""
Changelog Views and API Endpoints
Public changelog page + admin editor with AI-native changelog generation.
"""

from ..utils.security import protected
from ..utils.models import (
    User,
    Ticket,
    ChangelogRelease,
    UserTicketJoin,
    WorkCycle,
)
from flask import render_template, request, jsonify, Blueprint, redirect, url_for
from ..utils.ai_changelog import is_ai_enabled, generate_full_changelog, get_ai_config
import time
import json

# Create blueprint
changelog_bp = Blueprint("changelog", __name__)

VALID_CATEGORIES = ["new", "changed", "fixed"]

# Matches sprint board “Done” lane in work_cycles (done / closed / duplicate).
SPRINT_DONE_STATUSES = ("done", "closed", "duplicate")


def _get_current_user_or_none():
    """Try to get the current user without requiring auth."""
    from ..utils.security import get_current_user
    try:
        return get_current_user()
    except Exception:
        return None


def _parse_release_content(release):
    """Parse JSON content from a release into structured data."""
    try:
        data = json.loads(release.content)
        entries = data.get("entries", [])
        notes = data.get("notes", "")
    except (json.JSONDecodeError, TypeError):
        # Fallback for any old markdown content
        entries = []
        notes = release.content or ""

    # Group entries by category
    grouped = {"new": [], "changed": [], "fixed": []}
    for entry in entries:
        cat = entry.get("category", "changed")
        if cat not in grouped:
            cat = "changed"
        grouped[cat].append(entry)

    return {"grouped": grouped, "notes": notes, "entries": entries}


def _get_last_published_timestamp():
    """Get the created_at timestamp of the most recent published release, or 0."""
    last = (
        ChangelogRelease.select(ChangelogRelease.created_at)
        .where(ChangelogRelease.status == "published")
        .order_by(ChangelogRelease.created_at.desc())
        .limit(1)
        .first()
    )
    return last.created_at if last else 0


def _get_available_tickets(since_timestamp=0, limit=50):
    """Get tickets that were created or updated since a given timestamp."""
    from ..utils.models import TicketUpdateMessage, Comment

    query = Ticket.select().where(Ticket.active == 1)

    if since_timestamp > 0:
        # Get IDs of tickets that have recent updates or comments
        recent_updates = TicketUpdateMessage.select(TicketUpdateMessage.ticket).where(TicketUpdateMessage.created_at >= since_timestamp)
        recent_comments = Comment.select(Comment.ticket).where(Comment.created_at >= since_timestamp)

        # Filter tickets to those created recently OR having recent updates/comments
        query = query.where(
            (Ticket.created_at >= since_timestamp) |
            (Ticket.id.in_(recent_updates)) |
            (Ticket.id.in_(recent_comments))
        )

    return list(query.order_by(Ticket.created_at.desc()).limit(limit))


# ============ Public Changelog Page ============

@changelog_bp.route("/changelog")
def changelog_view():
    """Public standalone changelog page — no auth required. Only shows published releases."""
    releases = list(
        ChangelogRelease.select()
        .where(ChangelogRelease.status == 'published')
        .order_by(ChangelogRelease.created_at.desc())
    )

    # Parse content for each release
    parsed_releases = []
    for release in releases:
        parsed = _parse_release_content(release)

        # Fetch contributors for each entry individually
        for entry in parsed["entries"]:
            ticket_id = entry.get("ticket_id")
            if ticket_id:
                query = (UserTicketJoin


                         .select(UserTicketJoin.user)
                         .where(UserTicketJoin.ticket == ticket_id))
                entry["contributors"] = [row.user for row in query]
            else:
                entry["contributors"] = []

        parsed_releases.append({
            "id": release.id,
            "version": release.version,
            "title": release.title,
            "created_at": release.created_at,
            "grouped": parsed["grouped"],
            "notes": parsed["notes"],
        })

    return render_template(
        "changelog.jinja2",
        page="changelog",
        releases=parsed_releases,
    )


@changelog_bp.route("/changelog/manage")
@protected
def changelog_manage_view(user: User):
    """Admin dashboard view — shows all releases (drafts + published)."""
    releases = list(
        ChangelogRelease.select()
        .order_by(ChangelogRelease.created_at.desc())
    )

    return render_template(


        "changelog_manage.jinja2",
        user=user,
        page="changelog",
        releases=releases,
    )


# ============ Admin Editor Views ============
@changelog_bp.route("/changelog/new")
@protected
def changelog_new_view(user: User):
    """Render the editor for creating a new release."""
    ai_enabled = is_ai_enabled()
    since_ts = _get_last_published_timestamp()
    available_tickets = _get_available_tickets(since_ts)

    work_cycles = list(WorkCycle.select().order_by(WorkCycle.created_at.desc()))

    return render_template(
        "changelog_editor.jinja2",
        user=user,
        page="changelog",
        release=None,
        available_tickets=available_tickets,
        ai_enabled=ai_enabled,
        work_cycles=work_cycles,
    )


@changelog_bp.route("/changelog/<int:release_id>/edit")
@protected
def changelog_edit_view(user: User, release_id: int):
    """Render the editor for an existing release."""
    release = ChangelogRelease.get_or_none(ChangelogRelease.id == release_id)
    if not release:
        return redirect(url_for("changelog.changelog_view"))

    ai_enabled = is_ai_enabled()
    since_ts = _get_last_published_timestamp()
    available_tickets = _get_available_tickets(since_ts)
    work_cycles = list(WorkCycle.select().order_by(WorkCycle.created_at.desc()))

    return render_template(
        "changelog_editor.jinja2",
        user=user,
        page="changelog",
        release=release,
        available_tickets=available_tickets,
        ai_enabled=ai_enabled,
        work_cycles=work_cycles,
    )


# ============ Admin API Endpoints ============
@changelog_bp.route("/api/changelog/tickets", methods=["GET"])
@protected
def api_get_available_tickets(user: User):
    """Get available tickets for the changelog editor pool."""
    show_all = request.args.get("all", "false").lower() == "true"

    if show_all:
        # Get all active tickets regardless of when they were created
        # Increase limit to show a deeper history
        tickets = _get_available_tickets(since_timestamp=0, limit=200)
    else:
        # Only show tickets since the last published release
        since_ts = _get_last_published_timestamp()
        tickets = _get_available_tickets(since_ts, limit=50)

    # Format for JSON response
    result = [
        {"id": t.id, "title": t.title} for t in tickets
    ]
    return jsonify({"success": True, "tickets": result})


@changelog_bp.route("/api/changelog/work-cycles/<int:cycle_id>/done-tickets", methods=["GET"])
@protected
def api_changelog_sprint_done_tickets(user: User, cycle_id: int):
    """Tickets on a sprint in a finished state (done / closed / duplicate) for changelog import."""
    cycle = WorkCycle.get_or_none(WorkCycle.id == cycle_id)
    if not cycle:
        return jsonify({"error": "Sprint not found"}), 404

    rows = (
        Ticket.select()
        .where(
            (Ticket.work_cycle_id == cycle_id)
            & (Ticket.active == 1)
            & (Ticket.status.in_(SPRINT_DONE_STATUSES))
        )
        .order_by(Ticket.created_at.asc())
    )
    tickets = [{"id": t.id, "title": t.title} for t in rows]
    return jsonify({"success": True, "cycle_name": cycle.name, "tickets": tickets})


@changelog_bp.route("/api/changelog/generate", methods=["POST"])
@protected
def api_generate_changelog(user: User):
    """Generate full changelog using AI from a list of tickets with categories."""
    if not is_ai_enabled():
        return jsonify({"error": "AI not configured"}), 400

    data = request.get_json()
    tickets = data.get("tickets", [])

    if not tickets:
        return jsonify({"error": "No tickets provided"}), 400

    # Validate structure
    for t in tickets:
        if "ticket_id" not in t:
            return jsonify({"error": "Each ticket must have a ticket_id"}), 400
        if t.get("category", "changed") not in VALID_CATEGORIES:
            t["category"] = "changed"

    config = get_ai_config()
    language = config.get("language", "English") if config else "English"

    try:
        result = generate_full_changelog(tickets, language)
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@changelog_bp.route("/api/changelog/releases", methods=["POST"])
@protected
def api_create_release(user: User):
    """Save a new changelog release with structured JSON content."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    version = data.get("version", "").strip() or None
    title = data.get("title", "").strip() or None
    content = data.get("content", "")
    status = data.get("status", "draft")

    if status not in ["draft", "published"]:
        return jsonify({"error": "Invalid status"}), 400

    # Validate content is valid JSON with entries
    try:
        content_data = json.loads(content) if isinstance(content, str) else content
        if not isinstance(content_data, dict) or "entries" not in content_data:
            return jsonify({"error": "Content must have entries"}), 400
        # Re-serialize to ensure clean JSON
        content = json.dumps(content_data)
    except (json.JSONDecodeError, TypeError):
        return jsonify({"error": "Content must be valid JSON"}), 400

    if not content_data.get("entries") and not content_data.get("notes", "").strip():
        return jsonify({"error": "Add at least one entry or note"}), 400

    if version:
        existing = ChangelogRelease.get_or_none(ChangelogRelease.version == version)
        if existing:
            return jsonify({"error": f"Version {version} already exists"}), 409

    release = ChangelogRelease.create(
        version=version,
        title=title,
        content=content,
        status=status,
        created_at=int(time.time()),
    )
    return jsonify({"success": True, "id": release.id}), 201


@changelog_bp.route("/api/changelog/releases/<int:release_id>", methods=["PUT"])
@protected
def api_update_release(user: User, release_id: int):
    """Update an existing changelog release."""
    release = ChangelogRelease.get_or_none(ChangelogRelease.id == release_id)
    if not release:
        return jsonify({"error": "Release not found"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    version = data.get("version", "").strip() or None
    status = data.get("status", release.status)
    content = data.get("content", "")

    if status not in ["draft", "published"]:
        return jsonify({"error": "Invalid status"}), 400

    # Validate content
    try:
        content_data = json.loads(content) if isinstance(content, str) else content
        if not isinstance(content_data, dict) or "entries" not in content_data:
            return jsonify({"error": "Content must have entries"}), 400
        content = json.dumps(content_data)
    except (json.JSONDecodeError, TypeError):
        return jsonify({"error": "Content must be valid JSON"}), 400

    if version and version != release.version:
        existing = ChangelogRelease.get_or_none(ChangelogRelease.version == version)
        if existing:
            return jsonify({"error": f"Version {version} already exists"}), 409

    release.version = version
    release.title = data.get("title", "").strip() or None
    release.content = content
    release.status = status
    release.save()

    return jsonify({"success": True}), 200


@changelog_bp.route("/api/changelog/<int:release_id>", methods=["DELETE"])
@protected
def api_delete_changelog(user: User, release_id: int):
    """Delete a changelog release."""
    release = ChangelogRelease.get_or_none(ChangelogRelease.id == release_id)
    if not release:
        return jsonify({"error": "Release not found"}), 404

    release.delete_instance()
    return jsonify({"success": True})
