from werkzeug import Response
from ..utils.models import GlobalSetting, Project, Ticket, TicketUpdateMessage
from flask import Blueprint, render_template, request, redirect, jsonify
import time
import json
import secrets
import hashlib
import html
from ..utils.app import limiter
from typing import Literal
from flask import flash, send_from_directory
from ..utils.models import User, PasswordResetToken, data_path
from ..utils.events import bus
from ..utils.events import EventTypes
import pyargon2
import os

anon_bp = Blueprint("anon", __name__)


def _build_external_base_url() -> str:
    configured = os.environ.get("APP_BASE_URL", "").strip().rstrip("/")
    if configured:
        return configured
    return request.host_url.rstrip("/")


def _find_avatar_file(avatar_dir: str, username: str) -> str | None:
    for ext in [".png", ".jpg", ".jpeg", ".webp"]:
        candidate = os.path.join(avatar_dir, f"{username}{ext}")
        if os.path.exists(candidate):
            return f"{username}{ext}"
    return None


def _avatar_placeholder_svg(username: str) -> str:
    safe_username = (username or "user").strip() or "user"
    initial = html.escape(safe_username[:1].upper())
    title = html.escape(safe_username)
    palette = [
        "#0f766e",
        "#1d4ed8",
        "#7c3aed",
        "#c2410c",
        "#be123c",
        "#047857",
    ]
    color = palette[hashlib.sha256(safe_username.lower().encode("utf-8")).digest()[0] % len(palette)]
    return f"""<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"128\" height=\"128\" viewBox=\"0 0 128 128\" role=\"img\" aria-label=\"Avatar placeholder for {title}\"><rect width=\"128\" height=\"128\" rx=\"64\" fill=\"{color}\"/><text x=\"50%\" y=\"50%\" dominant-baseline=\"central\" text-anchor=\"middle\" fill=\"white\" font-family=\"Arial, sans-serif\" font-size=\"54\" font-weight=\"700\">{initial}</text></svg>"""


def get_anon_settings():
    try:
        setting = GlobalSetting.get(GlobalSetting.key == "anonymous_settings")
        return json.loads(setting.value)
    except (GlobalSetting.DoesNotExist, json.JSONDecodeError):
        return {
            "enabled": False,
            "message": "Welcome! Please submit your ticket below.",
        }


@anon_bp.route("/anon")
def anon_index() -> tuple[str, Literal[403]] | tuple[str, Literal[500]] | Response | str:
    settings = get_anon_settings()

    if not settings.get("enabled"):
        return (
            render_template(
                "error_message.jinja2",
                error_code=403,
                error_message="Anonymous tickets are currently disabled.",
            ),
            403,
        )

    return render_template(
        "anon_wizard.jinja2",
        step="form",
        welcome_message=settings.get("message", ""),
    )


@anon_bp.route("/anon/<project_id>")
def anon_wizard(project_id: str):
    # Legacy compatibility: route all project-specific anon URLs to unified form.
    return redirect("/anon")


@anon_bp.route("/api/anon/submit", methods=["POST"])
@limiter.limit("100 per hour")
def api_anon_submit():
    settings = get_anon_settings()
    if not settings.get("enabled"):
        return jsonify({"error": "Anonymous tickets disabled"}), 403

    data = request.get_json(silent=True) or {}

    title = str(data.get("title", "Anonymous Ticket")).strip() or "Anonymous Ticket"
    description = str(data.get("description", "")).strip()

    from .tickets import _find_possible_duplicate_tickets, _has_blocking_duplicate

    possible_duplicates = _find_possible_duplicate_tickets(title, description)
    has_duplicate_match = _has_blocking_duplicate(possible_duplicates)

    project_id = "TRIAGE"

    # Generate ticket ID (reusing logic from tickets.py or duplicating for cleanliness)
    # Ideally should be a shared utility, but for now copying logic is safer than refactoring widely
    existing_tickets = Ticket.select().where(Ticket.project == project_id)
    max_num = 0
    for t in existing_tickets:
        parts = t.id.split("-")
        if len(parts) >= 2:
            try:
                num = int(parts[-1])
                if num > max_num:
                    max_num = num
            except ValueError:
                pass
    ticket_id = f"{project_id}-{max_num + 1}"
    while Ticket.get_or_none(Ticket.id == ticket_id):
        max_num += 1
        ticket_id = f"{project_id}-{max_num + 1}"

    # Generate Secret
    secret = secrets.token_urlsafe(16)

    Ticket.create(
        id=ticket_id,
        title=title,
        description=description,
        status="intake",  # Anonymous submissions always go through intake.
        priority=data.get("priority", "medium"),
        project=project_id,
        created_at=int(time.time()),
        anonymous_secret=secret,
    )

    duplicate_note = ""
    if has_duplicate_match:
        duplicate_ids = ", ".join(
            [str(match.get("id", "")).strip() for match in possible_duplicates[:3] if match.get("id")]
        )
        if duplicate_ids:
            duplicate_note = f" Potential duplicate candidates: {duplicate_ids}."

    TicketUpdateMessage.create(
        ticket=ticket_id,
        title="Anonymous Ticket Created",
        icon="ph ph-mask-happy",
        message=f"A user submitted this ticket anonymously to intake.{duplicate_note}",
        created_at=int(time.time()),
    )

    bus.emit(
        EventTypes.ANON_TICKET_SUBMITTED,
        ticket_id=ticket_id,
        ticket_title=title,
        project=project_id,
        status="intake",
        actor="anonymous",
        details="Anonymous ticket entered intake inbox",
    )

    return jsonify({"success": True, "secret": secret, "ticket_id": ticket_id}), 201


@anon_bp.route("/anon/track/<secret>")
def anon_track(secret: str):
    ticket = Ticket.get_or_none(Ticket.anonymous_secret == secret)
    if not ticket:
        return (
            render_template(
                "error_message.jinja2",
                error_code=404,
                error_message="Tracking link invalid or expired.",
            ),
            404,
        )

    project = Project.get_or_none(Project.id == ticket.project)

    # Populate minimal data
    ticket.updates = list(
        TicketUpdateMessage.select()
        .where(TicketUpdateMessage.ticket == ticket.id)
        .order_by(TicketUpdateMessage.id)
    )

    return render_template("anon_track.jinja2", ticket=ticket, project=project)


@anon_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        user = User.get_or_none(User.email == email)
        if user:
            token = secrets.token_urlsafe(32)
            PasswordResetToken.create(token=token, user=user.username, created_at=int(time.time()))
            base_url = _build_external_base_url()
            bus.emit(
                "USER_PASSWORD_RESET",
                user=user,
                token=token,
                reset_url=f"{base_url}/reset-password/{token}",
            )
        # Always show success to prevent email enumeration
        flash("If your email is registered, you will receive a password reset link.", "success")
        return redirect("/login")
    return render_template("forgot_password.jinja2")


@anon_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token: str):
    reset_token = PasswordResetToken.get_or_none(PasswordResetToken.token == token)
    if not reset_token:
        flash("Invalid or expired password reset token.", "error")
        return redirect("/login")

    # Check expiration (e.g. 24 hours = 86400 seconds)
    if int(time.time()) - reset_token.created_at > 86400:
        reset_token.delete_instance()
        flash("Password reset token has expired.", "error")
        return redirect("/login")

    if request.method == "POST":
        password = request.form.get("password", "").strip()
        if len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
            return render_template("reset_password.jinja2", token=token)

        user = User.get_or_none(User.username == reset_token.user)
        if user:
            user.password_hash = pyargon2.hash(password, str(user.salt))
            user.save()
            reset_token.delete_instance()
            flash("Password reset successful. Please log in.", "success")
            return redirect("/login")

        flash("User not found.", "error")
        return redirect("/login")

    return render_template("reset_password.jinja2", token=token)


@anon_bp.route("/avatar/<username>")
def get_avatar(username: str):
    avatar_dir = data_path("avatars")
    avatar_file = _find_avatar_file(avatar_dir, username)
    if avatar_file:
        return send_from_directory(avatar_dir, avatar_file)

    response = Response(_avatar_placeholder_svg(username), mimetype="image/svg+xml")
    response.headers["Cache-Control"] = "public, max-age=300"
    return response
