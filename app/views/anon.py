import json
import os
import re
import secrets
import time

import pyargon2
from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    url_for,
)

from ..utils.anon_intake import (
    KINDS,
    build_review,
    create_ticket_from_draft,
    delete_draft,
    delete_upload,
    draft_is_expired,
    file_report_now,
    find_contact,
    kind_form_specs,
    normalize_answers,
    notify_verified,
    open_draft_count,
    parse_emails,
    review_token_matches,
    save_report_image,
    send_confirm_mail,
    send_received_mail,
    store_draft,
    structural_notes,
)
from ..utils.app import limiter
from ..utils.events import EventTypes, bus
from ..utils.mail import outbound_mail_configured
from ..utils.models import (
    AnonContact,
    AnonDraft,
    GlobalSetting,
    PasswordResetToken,
    Ticket,
    TicketUpdateMessage,
    User,
    data_path,
)

anon_bp = Blueprint("anon", __name__)


def _build_external_base_url() -> str:
    configured = os.environ.get("APP_BASE_URL", "").strip().rstrip("/")
    if configured:
        return configured
    return request.host_url.rstrip("/")


def _external_app_root_url() -> str:
    """Public origin plus optional BROKE_APPLICATION_PREFIX (for outbound email links)."""
    base = _build_external_base_url()
    pref = str(current_app.config.get("BROKE_APPLICATION_PREFIX") or "").strip().rstrip("/")
    return f"{base}{pref}" if pref else base


def _find_avatar_file(avatar_dir: str, username: str) -> str | None:
    for ext in [".png", ".jpg", ".jpeg", ".webp"]:
        candidate = os.path.join(avatar_dir, f"{username}{ext}")
        if os.path.exists(candidate):
            return f"{username}{ext}"
    return None


def get_anon_settings():
    try:
        setting = GlobalSetting.get(GlobalSetting.key == "anonymous_settings")
        return json.loads(setting.value)
    except (GlobalSetting.DoesNotExist, json.JSONDecodeError):
        return {
            "enabled": False,
            "message": "Welcome! Please submit your ticket below.",
        }


def _read_report(data: dict):
    kind = str(data.get("kind", "")).strip().lower()
    if kind not in KINDS:
        return None, None, (
            jsonify({"error": "Choose problem, feature, or improvement.", "field": "kind"}),
            400,
        )
    return kind, normalize_answers(kind, data), None


@anon_bp.route("/anon")
def anon_index():
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
        welcome_message=settings.get("message", ""),
        mail_configured=outbound_mail_configured(),
        kind_specs=kind_form_specs(),
    )


@anon_bp.route("/anon/<project_id>")
def anon_wizard(project_id: str):
    # Legacy compatibility: route all project-specific anon URLs to unified form.
    return redirect(url_for("anon.anon_index"))


@anon_bp.route("/api/anon/review", methods=["POST"])
@limiter.limit("30 per hour")
def api_anon_review():
    settings = get_anon_settings()
    if not settings.get("enabled"):
        return jsonify({"error": "Anonymous tickets disabled"}), 403

    data = request.get_json(silent=True) or {}
    kind, answers, error = _read_report(data)
    if error:
        return error
    return jsonify(build_review(kind, answers)), 200


@anon_bp.route("/api/anon/submit", methods=["POST"])
@limiter.limit("10 per hour")
def api_anon_submit():
    settings = get_anon_settings()
    if not settings.get("enabled"):
        return jsonify({"error": "Anonymous tickets disabled"}), 403

    data = request.get_json(silent=True) or {}
    kind, answers, error = _read_report(data)
    if error:
        return error
    notes = structural_notes(kind, answers)
    if notes:
        return jsonify({"error": notes[0]["message"], "field": notes[0]["field"]}), 400
    if not review_token_matches(str(data.get("review_token", "")), kind, answers):
        return (
            jsonify({"error": "Check this report again before sending.", "field": "review_token"}),
            400,
        )

    def _take_image():
        image_value = str(data.get("image") or "").strip()
        if not image_value:
            return None, None
        return save_report_image(image_value)

    if not outbound_mail_configured():
        image_src, image_error = _take_image()
        if image_error:
            return jsonify({"error": image_error, "field": "image"}), 400
        try:
            ticket = file_report_now(kind, answers, image_src)
        except Exception:
            delete_upload(image_src)
            current_app.logger.exception("Could not file an anonymous report without mail")
            return jsonify({"error": "Could not file the report."}), 500
        return (
            jsonify(
                {
                    "success": True,
                    "pending": False,
                    "track": f"/anon/track/{ticket.anonymous_secret}",
                }
            ),
            201,
        )

    primary, copies, email_field, email_error = parse_emails(
        data.get("primary_email", ""),
        data.get("copy_emails", []),
    )
    if email_error:
        return jsonify({"error": email_error, "field": email_field}), 400
    if open_draft_count(primary) >= 3:
        return (
            jsonify(
                {
                    "error": "A confirmation is already waiting for this address.",
                    "field": "primary_email",
                }
            ),
            400,
        )

    image_src, image_error = _take_image()
    if image_error:
        return jsonify({"error": image_error, "field": "image"}), 400

    draft, primary_token, copy_tokens = store_draft(kind, answers, primary, copies, image_src)
    if not send_confirm_mail(primary, "primary", primary_token, answers["title"]):
        delete_upload(image_src)
        delete_draft(draft)
        return jsonify({"error": "Could not send the confirmation email."}), 503

    for email, token in copy_tokens:
        if not send_confirm_mail(email, "copy", token, answers["title"]):
            current_app.logger.warning("Copy confirmation was not sent to %s", email)

    return jsonify({"success": True, "pending": True}), 201


@anon_bp.route("/anon/verify/<token>", methods=["GET", "POST"])
@limiter.limit("30 per hour", methods=["POST"])
def anon_verify(token: str):
    contact = find_contact(token)
    if contact is None:
        return (
            render_template(
                "error_message.jinja2",
                error_code=404,
                error_message="Tracking link invalid or expired.",
            ),
            404,
        )
    draft = AnonDraft.get_by_id(contact.draft_id)
    expired = draft_is_expired(draft)
    if request.method == "GET":
        return render_template(
            "anon_verify.jinja2",
            expired=expired,
            confirmed=bool(contact.verified_at) and draft.ticket_id is None,
            token=token,
        )

    if expired:
        return (
            render_template("anon_verify.jinja2", expired=True, confirmed=False, token=token),
            400,
        )

    if contact.role == "copy" and draft.ticket_id is None:
        if not contact.verified_at:
            contact.verified_at = int(time.time())
            contact.save(only=[AnonContact.verified_at])
        return render_template(
            "anon_verify.jinja2",
            expired=False,
            confirmed=True,
            token=token,
        )

    if draft.ticket_id and contact.role == "copy":
        ticket = Ticket.get(Ticket.id == draft.ticket_id)
        if not contact.verified_at:
            contact.verified_at = int(time.time())
            contact.ticket = ticket.id
            contact.save(only=[AnonContact.verified_at, AnonContact.ticket])
        send_received_mail(contact, ticket)
        return redirect(url_for("anon.anon_track", secret=ticket.anonymous_secret))

    ticket = create_ticket_from_draft(draft, contact)
    notify_verified(ticket)
    return redirect(url_for("anon.anon_track", secret=ticket.anonymous_secret))


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

    ticket.updates = list(
        TicketUpdateMessage.select()
        .where((TicketUpdateMessage.ticket == ticket.id) & (TicketUpdateMessage.public == 1))
        .order_by(TicketUpdateMessage.id)
    )
    kind_match = re.search(r'data-anon-kind="(problem|feature|improvement)"', ticket.description or "")
    kind_label = KINDS[kind_match.group(1)].label if kind_match else ""
    return render_template(
        "anon_track.jinja2",
        ticket=ticket,
        kind_label=kind_label,
        track_secret=secret,
    )


@anon_bp.route("/anon/media/<filename>")
def anon_media(filename: str):
    if not re.fullmatch(r"[a-f0-9]{32}\.(png|jpe?g|webp|gif)", filename):
        return "", 404
    referenced = Ticket.get_or_none(
        Ticket.anonymous_secret.is_null(False) & Ticket.description.contains(filename)
    )
    path = data_path("uploads", filename)
    if referenced is None or not os.path.isfile(path):
        return "", 404
    return send_file(path)


@anon_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        user = User.get_or_none(User.email == email)
        if user:
            token = secrets.token_urlsafe(32)
            PasswordResetToken.create(token=token, user=user.username, created_at=int(time.time()))
            bus.emit(
                EventTypes.USER_PASSWORD_RESET,
                async_dispatch=False,
                recipient_email=user.email,
                username=user.username,
                token=token,
                reset_url=f"{_external_app_root_url()}/reset-password/{token}",
            )
        flash("If your email is registered, you will receive a password reset link.", "success")
        return redirect(url_for("auth.login"))
    return render_template("forgot_password.jinja2")


@anon_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token: str):
    reset_token = PasswordResetToken.get_or_none(PasswordResetToken.token == token)
    if not reset_token:
        flash("Invalid or expired password reset token.", "error")
        return redirect(url_for("auth.login"))

    if int(time.time()) - reset_token.created_at > 86400:
        reset_token.delete_instance()
        flash("Password reset token has expired.", "error")
        return redirect(url_for("auth.login"))

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
            return redirect(url_for("auth.login"))

        flash("User not found.", "error")
        return redirect(url_for("auth.login"))

    return render_template("reset_password.jinja2", token=token)


@anon_bp.route("/avatar/<username>")
def get_avatar(username: str):
    avatar_dir = data_path("avatars")
    avatar_file = _find_avatar_file(avatar_dir, username)
    if avatar_file:
        return send_from_directory(avatar_dir, avatar_file)
    return "", 404
