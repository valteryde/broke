"""
Settings Views and API Endpoints
Handles user preferences, webhooks, and workspace configuration
"""

import os
from ..utils.security import protected
from ..utils.models import (
    User,
    UserSettings,
    Project,
    Label,
    APIToken,
    Webhook,
    DSNToken,
    GlobalSetting,
    UserCreateToken,
    ProjectPart,
    Ticket,
    WebhookDelivery,
    data_path,
    create_user,
)
from flask import redirect, render_template, request, flash, Blueprint
from ..utils.reltime import time_ago
from peewee import DoesNotExist
import json
import hashlib
import time
import secrets
import re
import uuid
import pyargon2
from ..utils import mail
from ..utils.ai_changelog import get_ai_config
from ..utils.notifications import (
    get_notification_engine_settings,
    save_notification_engine_settings,
)

# Create blueprint
settings_bp = Blueprint("settings", __name__)


MAX_AVATAR_SIZE_BYTES = 5 * 1024 * 1024
ALLOWED_AVATAR_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


def _avatar_magic_is_valid(content_type: str, header_bytes: bytes) -> bool:
    if content_type == "image/png":
        return header_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/jpeg":
        return header_bytes.startswith(b"\xff\xd8\xff")
    if content_type == "image/webp":
        return header_bytes.startswith(b"RIFF") and header_bytes[8:12] == b"WEBP"
    return False


def _delete_existing_avatar_files(avatar_dir: str, username: str):
    for ext in [".png", ".jpg", ".jpeg", ".webp"]:
        path = os.path.join(avatar_dir, f"{username}{ext}")
        if os.path.exists(path):
            os.remove(path)


# ============ Settings Page Routes ============


@settings_bp.route("/settings")
@protected
def settings_view(user: User):
    """Default settings view - redirects to profile"""
    return redirect("/settings/profile")


@settings_bp.route("/settings/<section>")
@protected
def settings_section_view(user: User, section: str):  # noqa: C901
    """Render settings page for a specific section"""

    admin_only_sections = {"email", "webhooks", "sentry", "ai"}
    if section in admin_only_sections and user.admin != 1:
        flash("Unauthorized. Admins only.", "error")
        return redirect("/settings/profile")

    # Map sections to their display titles
    section_titles = {
        "profile": "Profile",
        "preferences": "Preferences",
        "notifications": "Notifications",
        "email": "Email Service",
        "security": "Security",
        "general": "General",
        "projects": "Projects",
        "team": "Team Members",
        "labels": "Labels",
        "api": "API & Tokens",
        "webhooks": "Webhooks",
        "sentry": "Sentry Integration",
        "updates": "Updates",
        "trash": "Trash",
        "anonymous": "Anonymous Access",
        "danger": "Danger Zone",
        "ai": "AI Integration",
    }

    section_title = section_titles.get(section, section.title())

    # Get or create user settings
    user_settings = get_or_create_user_settings(user)

    # Base context
    context = {
        "user": user,
        "page": "settings",
        "section": section,
        "section_title": section_title,
        "user_settings": user_settings,
    }

    # Section-specific data
    if section == "profile":
        context["user_settings"] = user_settings

    elif section == "preferences":
        context["user_settings"] = user_settings

    elif section == "notifications":
        context["user_settings"] = user_settings
        context["notification_engine"] = get_notification_engine_settings()

    elif section == "email":
        context["smtp_password_configured"] = False
        try:
            setting = GlobalSetting.get(GlobalSetting.key == "smtp_settings")
            raw = json.loads(setting.value)
            context["smtp_settings"] = {
                "host": raw.get("host", ""),
                "port": raw.get("port", 587),
                "username": raw.get("username", ""),
                "password": "",
                "from": raw.get("from", ""),
                "use_tls": bool(raw.get("use_tls", True)),
            }
            context["smtp_password_configured"] = bool(str(raw.get("password", "")).strip())
        except (DoesNotExist, json.JSONDecodeError):
            env_password = os.environ.get("SMTP_PASSWORD", "")
            context["smtp_settings"] = {
                "host": os.environ.get("SMTP_HOST", ""),
                "port": int(os.environ.get("SMTP_PORT", 587)),
                "username": os.environ.get("SMTP_USER", ""),
                "password": "",
                "from": os.environ.get("SMTP_FROM", ""),
                "use_tls": True,
            }
            context["smtp_password_configured"] = bool(env_password.strip())

    elif section == "projects":
        context["projects"] = list(Project.select().order_by(Project.name))

    elif section == "team":
        context["team_members"] = list(User.select().order_by(User.username))

    elif section == "labels":
        context["labels"] = list(Label.select().order_by(Label.name))

    elif section == "api":
        context["api_tokens"] = list(
            APIToken.select()
            .where(APIToken.user == user.username)
            .order_by(APIToken.created_at.desc())
        )

    elif section == "webhooks":
        context["projects"] = list(Project.select().order_by(Project.name))
        context["base_url"] = request.host_url.rstrip("/")
        context["webhook_secret_configured"] = bool(get_webhook_secret())
        context["github_webhook_secret_configured"] = bool(get_github_webhook_secret())

        # Outgoing webhooks
        context["outgoing_webhooks"] = list(
            Webhook.select()
            .where(Webhook.user == user.username)
            .order_by(Webhook.created_at.desc())
        )

        # Recent webhook activity
        context["webhook_activity"] = get_recent_webhook_activity(user, limit=10)

    elif section == "sentry":
        context["project_parts"] = list(ProjectPart.select())
        context["base_url"] = request.host_url.rstrip("/")

        # Get DSN token if it exists
        try:
            dsn_token = DSNToken.get()
            context["dsn_token"] = dsn_token
            preview = str(dsn_token.token_preview or "").strip()
            if not preview and dsn_token.token:
                preview = str(dsn_token.token)[:8]
            context["dsn_token_preview"] = preview
        except DoesNotExist:
            context["dsn_token"] = None
            context["dsn_token_preview"] = ""

    elif section == "trash":
        # Fetch deleted tickets
        context["deleted_tickets"] = list(
            Ticket.select().where(Ticket.active == 0).order_by(Ticket.created_at.desc())
        )

    elif section == "anonymous":
        try:
            setting = GlobalSetting.get(GlobalSetting.key == "anonymous_settings")
            context["anon_settings"] = json.loads(setting.value)
        except DoesNotExist:
            context["anon_settings"] = {
                "enabled": False,
                "message": "Welcome! Please submit your ticket below.",
                "projects": [],
            }
        context["projects"] = list(Project.select().order_by(Project.name))

    elif section == "ai":
        default_ai_settings = {
            "api_key": "",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
            "language": "English",
        }

        context["ai_settings_source"] = "none"
        context["ai_settings_api_key_present"] = False

        try:
            setting = GlobalSetting.get(GlobalSetting.key == "ai_settings")
            saved = json.loads(setting.value)
            if saved.get("api_key"):
                context["ai_settings"] = {
                    **default_ai_settings,
                    **saved,
                    "api_key": "",
                }
                context["ai_settings_source"] = "database"
                context["ai_settings_api_key_present"] = True
            else:
                raise DoesNotExist
        except (DoesNotExist, json.JSONDecodeError):
            active = get_ai_config()
            if active:
                context["ai_settings"] = {
                    **default_ai_settings,
                    **active,
                    # Do not prefill secret from env into the input field.
                    "api_key": "",
                }
                context["ai_settings_source"] = "environment"
                context["ai_settings_api_key_present"] = True
            else:
                context["ai_settings"] = default_ai_settings

    elif section == "updates":
        from ..utils.updater import get_update_info, is_auto_check_enabled, get_sidecar_status
        context["update_info"] = get_update_info()
        context["auto_check_enabled"] = is_auto_check_enabled()
        context["sidecar_status"] = get_sidecar_status()

    return render_template("settings.jinja2", **context)


# ============ Settings API Endpoints ============


@settings_bp.route("/api/settings/profile", methods=["POST"])
@protected
def api_update_profile(user: User):
    """Update user profile settings"""
    data = request.get_json()

    # Update email if provided
    if "email" in data:
        email = data["email"].strip()
        if email and email != user.email:
            # Check if email is already taken
            try:
                existing = User.get(User.email == email)
                if existing.username != user.username:
                    return json.dumps({"error": "Email already in use"}), 400
            except DoesNotExist:
                pass
            user.email = email
            user.save()

    # Update display name in settings
    if "display_name" in data:
        settings = get_or_create_user_settings(user)
        settings.display_name = data["display_name"].strip()
        settings.save()

    return json.dumps({"success": True}), 200


@settings_bp.route("/api/settings/profile/avatar", methods=["POST", "DELETE"])
@protected
def api_update_avatar(user: User):
    """Upload or remove user avatar."""
    if request.method == "DELETE":
        avatar_dir = data_path("avatars")
        os.makedirs(avatar_dir, exist_ok=True)
        _delete_existing_avatar_files(avatar_dir, user.username)
        return json.dumps({"success": True}), 200

    if "avatar" not in request.files:
        return json.dumps({"error": "No file part"}), 400

    file = request.files["avatar"]
    if file.filename == "":
        return json.dumps({"error": "No selected file"}), 400

    if file:
        content_type = (file.content_type or "").lower()
        extension = ALLOWED_AVATAR_TYPES.get(content_type)
        if not extension:
            return json.dumps({"error": "Unsupported avatar format"}), 400

        file.stream.seek(0, os.SEEK_END)
        size = file.stream.tell()
        file.stream.seek(0)
        if size > MAX_AVATAR_SIZE_BYTES:
            return json.dumps({"error": "Avatar file too large (max 5 MB)"}), 413

        header = file.stream.read(12)
        file.stream.seek(0)
        if not _avatar_magic_is_valid(content_type, header):
            return json.dumps({"error": "Invalid avatar file"}), 400

        avatar_dir = data_path("avatars")
        os.makedirs(avatar_dir, exist_ok=True)
        _delete_existing_avatar_files(avatar_dir, user.username)
        file.save(os.path.join(avatar_dir, f"{user.username}{extension}"))

        return json.dumps({"success": True}), 200

    return json.dumps({"error": "Invalid upload payload"}), 400


@settings_bp.route("/api/settings/preferences", methods=["POST"])
@protected
def api_update_preferences(user: User):
    """Update user preferences"""
    data = request.get_json()
    settings = get_or_create_user_settings(user)

    # Update preferences
    if "theme" in data:
        settings.theme = data["theme"]
    if "compact_mode" in data:
        settings.compact_mode = 1 if data["compact_mode"] else 0
    if "animations" in data:
        settings.animations = 1 if data["animations"] else 0
    if "home_page" in data:
        settings.home_page = data["home_page"]
    if "ticket_view" in data:
        settings.default_ticket_view = data["ticket_view"]
    if "timezone" in data:
        settings.timezone = data["timezone"]
    if "date_format" in data:
        settings.date_format = data["date_format"]

    settings.save()

    return json.dumps({"success": True}), 200


@settings_bp.route("/api/settings/notifications", methods=["POST"])
@protected
def api_update_notifications(user: User):
    """Update notification settings"""
    data = request.get_json()
    settings = get_or_create_user_settings(user)

    # Update notification preferences (stored as JSON)
    notification_prefs = json.loads(settings.notification_settings or "{}")
    notification_prefs.update(data)
    settings.notification_settings = json.dumps(notification_prefs)
    settings.save()

    return json.dumps({"success": True}), 200


@settings_bp.route("/api/settings/notifications/engine", methods=["GET"])
@protected
def api_get_notification_engine_settings(user: User):
    if user.admin != 1:
        return json.dumps({"error": "Unauthorized. Admins only."}), 403
    return json.dumps({"success": True, "settings": get_notification_engine_settings()}), 200


@settings_bp.route("/api/settings/notifications/engine", methods=["POST"])
@protected
def api_update_notification_engine_settings(user: User):
    if user.admin != 1:
        return json.dumps({"error": "Unauthorized. Admins only."}), 403

    payload = request.get_json(silent=True) or {}
    updated = save_notification_engine_settings(payload)
    return json.dumps({"success": True, "settings": updated}), 200


@settings_bp.route("/api/settings/anonymous", methods=["POST"])
@protected
def api_update_anonymous(user: User):
    """Update anonymous access settings"""

    data = request.get_json()

    # Validate and structure data
    settings = {
        "enabled": bool(data.get("enabled", False)),
        "message": data.get("message", "").strip(),
        "projects": [],
    }

    # Save to GlobalSetting
    try:
        setting = GlobalSetting.get(GlobalSetting.key == "anonymous_settings")
        setting.value = json.dumps(settings)
        setting.save()
    except DoesNotExist:
        GlobalSetting.create(key="anonymous_settings", value=json.dumps(settings))

    return json.dumps({"success": True}), 200


@settings_bp.route("/api/settings/ai", methods=["POST"])
@protected
def api_update_ai(user: User):
    """Update AI configuration (admin only usually, but let's assume they have access to settings)"""

    if user.admin != 1:
        return json.dumps({"error": "Unauthorized. Admins only."}), 403

    data = request.get_json()

    api_key = str(data.get("api_key", "")).strip()

    existing_record = GlobalSetting.get_or_none(GlobalSetting.key == "ai_settings")
    existing_settings = {}
    if existing_record and existing_record.value:
        try:
            existing_settings = json.loads(existing_record.value)
        except json.JSONDecodeError:
            existing_settings = {}

    # Keep previously saved key when the redacted field is left blank.
    if not api_key and existing_settings.get("api_key"):
        api_key = str(existing_settings.get("api_key", "")).strip()

    # Validate and structure data
    settings = {
        "api_key": api_key,
        "base_url": data.get("base_url", "https://api.openai.com/v1").strip(),
        "model": data.get("model", "gpt-4o-mini").strip(),
        "language": data.get("language", "English").strip(),
    }

    # If empty API key, we remove it to disable AI
    if not settings["api_key"]:
        try:
            setting = GlobalSetting.get(GlobalSetting.key == "ai_settings")
            setting.delete_instance()
        except DoesNotExist:
            pass
        return json.dumps({"success": True, "message": "AI Integration disabled"}), 200

    # Save to GlobalSetting
    if existing_record:
        existing_record.value = json.dumps(settings)
        existing_record.save()
    else:
        GlobalSetting.create(key="ai_settings", value=json.dumps(settings))

    return json.dumps({"success": True, "message": "AI Integration settings saved"}), 200


@settings_bp.route("/api/settings/email", methods=["POST"])
@protected
def api_update_email_settings(user: User):
    """Update SMTP email settings (admin only)."""
    if user.admin != 1:
        return json.dumps({"error": "Unauthorized. Admins only."}), 403

    data = request.get_json(silent=True) or {}
    host = str(data.get("host", "")).strip()
    if not host:
        return json.dumps({"error": "SMTP host is required"}), 400

    try:
        port = int(data.get("port", 587))
    except (TypeError, ValueError):
        return json.dumps({"error": "SMTP port must be a number"}), 400

    if port <= 0 or port > 65535:
        return json.dumps({"error": "SMTP port is out of range"}), 400

    existing_record = GlobalSetting.get_or_none(GlobalSetting.key == "smtp_settings")
    existing_settings = {}
    if existing_record and existing_record.value:
        try:
            existing_settings = json.loads(existing_record.value)
        except json.JSONDecodeError:
            existing_settings = {}

    password = str(data.get("password", "")).strip()
    if not password and existing_settings.get("password"):
        password = str(existing_settings.get("password", "")).strip()

    settings = {
        "host": host,
        "port": port,
        "username": str(data.get("username", "")).strip(),
        "password": password,
        "from": str(data.get("from", "")).strip(),
        "use_tls": bool(data.get("use_tls", True)),
    }

    if existing_record:
        existing_record.value = json.dumps(settings)
        existing_record.save()
    else:
        GlobalSetting.create(key="smtp_settings", value=json.dumps(settings))

    return json.dumps({"success": True}), 200


@settings_bp.route("/api/settings/email/test", methods=["POST"])
@protected
def api_send_test_email(user: User):
    """Send a test email using current SMTP configuration (admin only)."""
    if user.admin != 1:
        return json.dumps({"error": "Unauthorized. Admins only."}), 403

    data = request.get_json(silent=True) or {}
    recipient = str(data.get("recipient", "")).strip() or user.email
    if not recipient:
        return json.dumps({"error": "Recipient email is required"}), 400

    html = f"""
    <html>
        <body>
            <h2>Broke SMTP Test</h2>
            <p>Hello {user.username},</p>
            <p>This is a test email from Broke.</p>
            <p>If you received this message, your SMTP configuration is working.</p>
        </body>
    </html>
    """

    mail.send_email(recipient, "Broke SMTP Test Email", html)
    return json.dumps({"success": True}), 200


@settings_bp.route("/api/settings/security/password", methods=["POST"])
@protected
def api_change_password(user: User):
    """Change user password"""
    import pyargon2

    data = request.get_json()
    current_password = data.get("current_password", "")
    new_password = data.get("new_password", "")

    # Verify current password
    if pyargon2.hash(current_password, str(user.salt)) != user.password_hash:
        return json.dumps({"error": "Current password is incorrect"}), 400

    # Validate new password
    if len(new_password) < 8:
        return json.dumps({"error": "Password must be at least 8 characters"}), 400

    # Update password
    user.password_hash = pyargon2.hash(new_password, str(user.salt))  # type: ignore
    user.save()

    return json.dumps({"success": True, "message": "Password updated successfully"}), 200


# ============ Webhook API Endpoints ============


@settings_bp.route("/api/settings/webhooks/regenerate-secret", methods=["POST"])
@protected
def api_regenerate_webhook_secret(user: User):
    """Regenerate webhook secret"""

    if user.admin != 1:
        return json.dumps({"error": "Unauthorized. Admins only."}), 403

    data = request.get_json()
    secret_type = data.get("type", "github")

    settings = get_or_create_user_settings(user)
    new_secret = ""

    if secret_type == "github":
        new_secret = secrets.token_hex(16)
        settings.github_webhook_secret = new_secret
    else:
        new_secret = secrets.token_hex(16)
        settings.webhook_secret = new_secret

    settings.save()

    return json.dumps({"success": True, "secret": new_secret}), 200


@settings_bp.route("/api/settings/webhooks/outgoing", methods=["POST"])
@protected
def api_create_outgoing_webhook(user: User):
    """Create a new outgoing webhook"""
    data = request.get_json()
    url = data.get("url", "").strip()
    events = data.get("events", [])
    secret = data.get("secret", "")

    if not url:
        return json.dumps({"error": "URL is required"}), 400

    # Validate URL format
    if not url.startswith(("http://", "https://")):
        return json.dumps({"error": "Invalid URL format"}), 400

    webhook = Webhook.create(
        user=user.username,
        url=url,
        events=json.dumps(events),
        secret=secret,
        active=True,
        created_at=int(time.time()),
    )

    return json.dumps({"success": True, "webhook_id": webhook.id}), 200


@settings_bp.route("/api/settings/webhooks/<int:webhook_id>", methods=["DELETE"])
@protected
def api_delete_webhook(user: User, webhook_id: int):
    """Delete an outgoing webhook"""
    try:
        webhook = Webhook.get((Webhook.id == webhook_id) & (Webhook.user == user.username))
        webhook.delete_instance()
        return json.dumps({"success": True}), 200
    except DoesNotExist:
        return json.dumps({"error": "Webhook not found"}), 404


@settings_bp.route("/api/settings/webhooks/<int:webhook_id>/test", methods=["POST"])
@protected
def api_test_webhook(user: User, webhook_id: int):
    """Send a test event to a webhook"""
    import requests

    try:
        webhook = Webhook.get((Webhook.id == webhook_id) & (Webhook.user == user.username))
    except DoesNotExist:
        return json.dumps({"error": "Webhook not found"}), 404

    # Send test payload
    test_payload = {
        "event": "test",
        "timestamp": int(time.time()),
        "message": "This is a test webhook from Broke",
    }

    try:
        response = requests.post(
            webhook.url,
            json=test_payload,
            headers={
                "Content-Type": "application/json",
                "X-Broke-Event": "test",
                "X-Broke-Delivery": secrets.token_hex(8),
            },
            timeout=10,
        )

        status_code = response.status_code

        # Log successful delivery
        log_webhook_delivery(webhook, "test", status_code, "success")

        return json.dumps({"success": True, "status_code": status_code}), 200

    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if e.response else 0
        log_webhook_delivery(webhook, "test", status_code, "error")
        return json.dumps({"success": False, "status_code": status_code}), 200

    except Exception as e:
        log_webhook_delivery(webhook, "test", 0, "error")
        return json.dumps({"error": str(e)}), 500


# ============ MEMBERS ============
@settings_bp.route("/api/settings/team/invite", methods=["POST"])
@protected
def api_invite_team_member(user: User):
    """Invite a new team member by creating a create token"""

    data = request.form
    name = data.get("name", "").strip()
    # is_admin = data.get("admin", "off") == "on"

    if not name:
        flash("Name is required to invite a team member.", "error")
        return redirect("/settings/team")

    # Generate a temporary invite token
    invite_token = secrets.token_urlsafe(32)
    invite_token_hash = hashlib.sha256(invite_token.encode()).hexdigest()

    UserCreateToken.create(
        token=invite_token_hash,
        created_at=int(time.time()),
        name=name,
    )

    base_url = request.host_url.rstrip("/")

    return render_template(
        "invite_sent.jinja2",
        name=name,
        token=invite_token,
        base_url=base_url,
        user=user,
        page="settings",
        section="team",
    )


@settings_bp.route("/api/settings/team/<username>", methods=["DELETE"])
@protected
def api_delete_team_member(user: User, username: str):
    """Delete a team member (Admin only) using tombstone strategy."""
    if user.admin != 1:
        return json.dumps({"error": "Unauthorized. Admins only."}), 403

    if user.username == username:
        return json.dumps({"error": "You cannot delete yourself."}), 400

    try:
        target_user = User.get(User.username == username)

        # Keep the user row for history references (comments, update authors),
        # but revoke access and clear user-specific settings/integrations.
        from ..utils.models import UserSettings, Webhook, APIToken, UserTicketJoin

        UserSettings.delete().where(UserSettings.user == username).execute()
        Webhook.delete().where(Webhook.user == username).execute()
        APIToken.delete().where(APIToken.user == username).execute()
        UserTicketJoin.delete().where(UserTicketJoin.user == username).execute()

        target_user.salt = uuid.uuid4().hex
        target_user.password_hash = pyargon2.hash(uuid.uuid4().hex, target_user.salt)
        target_user.email = f"deleted+{username}+{int(time.time())}@deleted.local"
        target_user.admin = 0
        target_user.save()

        return json.dumps({"success": True}), 200
    except DoesNotExist:
        return json.dumps({"error": "User not found"}), 404


@settings_bp.route("/api/settings/team/<username>/temporary-password", methods=["POST"])
@protected
def api_set_temporary_password(user: User, username: str):
    """Set a temporary password for a user when admins need manual recovery."""
    if user.admin != 1:
        return json.dumps({"error": "Unauthorized. Admins only."}), 403

    try:
        target_user = User.get(User.username == username)
    except DoesNotExist:
        return json.dumps({"error": "User not found"}), 404

    # Default to generated secret if admin does not provide one.
    payload = request.get_json(silent=True) or {}
    temp_password = (payload.get("password") or "").strip() or secrets.token_urlsafe(10)
    if len(temp_password) < 8:
        return json.dumps({"error": "Temporary password must be at least 8 characters"}), 400

    target_user.salt = uuid.uuid4().hex
    target_user.password_hash = pyargon2.hash(temp_password, target_user.salt)
    target_user.admin = 0
    target_user.save()

    return json.dumps({"success": True, "temporary_password": temp_password}), 200


@settings_bp.route("/welcome/<token>", methods=["GET", "POST"])
def welcome_new_member(token: str):
    """Welcome a new team member and allow them to set up their account"""

    # Verify the token
    try:

        invite = UserCreateToken.get(
            UserCreateToken.token == hashlib.sha256(token.encode()).hexdigest()
        )

    except DoesNotExist:
        flash("Invalid or expired invite token.", "error")
        return redirect("/login")

    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()
        email = request.form.get("email", "").strip()

        # Validate and create user account
        if len(password) < 8:
            flash("Password must be at least 8 characters long.", "error")
            return redirect(request.url)

        create_user(
            username,
            password,
            email,
        )

        # Delete the invite token after use
        invite.delete_instance()

        flash("Account created successfully! Please log in.", "success")
        return redirect("/news")

    return render_template("welcome_new_member.jinja2", token=token, name=invite.name)


# ============ API Token Endpoints ============
@settings_bp.route("/api/settings/tokens", methods=["POST"])
@protected
def api_create_token(user: User):
    """Create a new API token"""

    # Generate secure token
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    api_token = APIToken.create(
        user=user.username,
        token_hash=token_hash,
        token_preview=token[:8],
        created_at=int(time.time()),
    )

    # Return the full token only once
    return (
        json.dumps(
            {
                "success": True,
                "token": token,
                "token_id": api_token.id,
            }
        ),
        200,
    )


@settings_bp.route("/api/settings/tokens/<int:token_id>", methods=["DELETE"])
@protected
def api_delete_token(user: User, token_id: int):
    """Delete an API token"""

    try:
        token = APIToken.get((APIToken.id == token_id) & (APIToken.user == user.username))
        token.delete_instance()
        return json.dumps({"success": True}), 200
    except DoesNotExist:
        return json.dumps({"error": "Token not found"}), 404


# ============ DSN Token Endpoints ============


@settings_bp.route("/api/settings/dsn-token", methods=["POST"])
@protected
def api_create_dsn_token(user: User):
    """Create or replace the DSN token - only one can exist"""

    if user.admin != 1:
        return json.dumps({"error": "Unauthorized. Admins only."}), 403

    # Delete any existing DSN token
    DSNToken.delete().execute()

    # Generate secure token
    token = secrets.token_urlsafe(32)

    dsn_token = DSNToken.create(
        token="",
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        token_preview=token[:8],
        created_at=int(time.time()),
    )

    return (
        json.dumps(
            {
                "success": True,
                "token": token,
                "token_id": dsn_token.id,
            }
        ),
        200,
    )


@settings_bp.route("/api/settings/dsn-token", methods=["DELETE"])
@protected
def api_revoke_dsn_token(user: User):
    """Revoke the DSN token"""

    if user.admin != 1:
        return json.dumps({"error": "Unauthorized. Admins only."}), 403

    count = DSNToken.delete().execute()

    if count > 0:
        return json.dumps({"success": True}), 200
    else:
        return json.dumps({"error": "No DSN token exists"}), 404


@settings_bp.route("/api/settings/projects", methods=["POST"])
@protected
def api_create_project(user: User):
    """Create a new project"""

    data = request.form
    name = data.get("name", "").strip()

    if not name:
        return json.dumps({"error": "Project name is required"}), 400

    # Generate project ID from name
    project_id = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:3].upper()

    # Check if project exists
    try:
        Project.get(Project.id == project_id)

        # TODO: Handle ID conflicts better (e.g., append numbers)
        flash("Project ID already exists. Please choose a different name.", "error")

        return redirect("/settings/projects")
    except DoesNotExist:
        pass

    Project.create(
        id=project_id,
        name=name,
        icon=data.get("icon", "ph ph-folder"),
        color=data.get("color", "#106ecc"),
    )

    flash(f'Project "{name}" created successfully.', "success")

    return redirect("/settings/projects")


@settings_bp.route("/api/settings/projects/delete/<project_id>", methods=["GET"])
@protected
def api_delete_project(user: User, project_id: str):
    """Delete a project"""

    try:
        project = Project.get(Project.id == project_id)
        # Delete associated parts first
        ProjectPart.delete().where(ProjectPart.project == project_id).execute()
        project.delete_instance()

        flash(f'Project "{project.name}" deleted successfully.', "success")

        return redirect("/settings/projects")
    except DoesNotExist:

        flash("Project not found.", "error")

        return redirect("/settings/projects")


@settings_bp.route("/api/settings/projects/update/<project_id>", methods=["GET", "POST"])
@protected
def api_update_project(user: User, project_id: str):
    """Update project details"""

    try:
        project = Project.get(Project.id == project_id)
    except DoesNotExist:
        flash("Project not found.", "error")
        return redirect("/settings/projects")

    data = request.form

    project.name = data.get("name", project.name)
    project.icon = data.get("icon", project.icon)
    project.color = data.get("color", project.color)
    project.save()

    flash(f'Project "{project.id}" updated successfully.', "success")
    return redirect("/settings/projects")


@settings_bp.route("/api/settings/labels", methods=["POST"])
@protected
def api_create_label(user: User):
    """Create a new label"""

    data = request.form
    name = data.get("name", "").strip()
    color = data.get("color", "#0075E3")

    if not name:
        flash("Label name is required.", "error")
        return redirect("/settings/labels")

    try:
        Label.get(Label.name == name)
        flash("Label already exists.", "error")
        return redirect("/settings/labels")
    except DoesNotExist:
        pass

    Label.create(name=name, color=color)

    flash(f'Label "{name}" created successfully.', "success")
    return redirect("/settings/labels")


@settings_bp.route("/api/settings/labels/delete/<label_name>")
@protected
def api_delete_label(user: User, label_name: str):
    """Delete a label"""

    try:
        label = Label.get(Label.name == label_name)
        label.delete_instance()
        flash(f'Label "{label_name}" deleted successfully.', "success")
    except DoesNotExist:
        flash("Label not found.", "error")
    return redirect("/settings/labels")


# ============ Danger Zone ============


@settings_bp.route("/api/settings/danger/delete-account", methods=["POST"])
@protected
def api_delete_account(user: User):
    """Delete user account"""
    import pyargon2

    data = request.get_json()
    password = data.get("password", "")

    # Verify password
    if pyargon2.hash(password, user.salt) != user.password_hash:
        return json.dumps({"error": "Incorrect password"}), 400

    # Delete user data
    UserSettings.delete().where(UserSettings.user == user.username).execute()
    Webhook.delete().where(Webhook.user == user.username).execute()
    APIToken.delete().where(APIToken.user == user.username).execute()

    # Finally delete user
    user.delete_instance()

    return json.dumps({"success": True}), 200


# ============ Helper Functions ============


def get_or_create_user_settings(user: User) -> "UserSettings":
    """Get or create user settings"""
    try:
        return UserSettings.get(UserSettings.user == user.username)
    except DoesNotExist:
        return UserSettings.create(
            user=user.username,
            theme="light",
            compact_mode=0,
            animations=1,
            home_page="news",
            default_ticket_view="list",
            timezone="UTC",
            date_format="dmy",
            notification_settings="{}",
            github_settings="{}",
            webhook_secret=secrets.token_hex(16),
            github_webhook_secret=secrets.token_hex(16),
        )


def get_secret_from_txt_file(fpath: str) -> str:

    # Get or create settings
    if not os.path.exists(data_path(fpath)):
        with open(data_path(fpath), "w") as f:
            f.write(secrets.token_hex(16))

    with open(data_path(fpath), "r") as f:
        secret = f.read().strip()

    return secret


def get_webhook_secret() -> str:
    """Get or generate webhook secret"""
    return get_secret_from_txt_file("webhook_secret.txt")


def get_github_webhook_secret() -> str:
    """Get or generate webhook secret"""
    return get_secret_from_txt_file("github_webhook_secret.txt")


def get_recent_webhook_activity(user: User, limit: int = 10) -> list:
    """Get recent webhook delivery activity"""
    try:
        deliveries = (
            WebhookDelivery.select()
            .join(Webhook)
            .where(Webhook.user == user.username)
            .order_by(WebhookDelivery.timestamp.desc())
            .limit(limit)
        )

        return [
            {
                "event": d.event,
                "status": d.status,
                "response_code": d.response_code,
                "time": time_ago(d.timestamp),
            }
            for d in deliveries
        ]
    except Exception:
        return []


def log_webhook_delivery(webhook: "Webhook", event: str, response_code: int, status: str):
    """Log a webhook delivery attempt"""
    try:
        WebhookDelivery.create(
            webhook=webhook,
            event=event,
            response_code=response_code,
            status=status,
            timestamp=int(time.time()),
        )
    except Exception:
        pass


# ============ Updates API Endpoints ============


@settings_bp.route("/api/settings/updates/check", methods=["POST"])
@protected
def api_check_update(user: User):
    """Manually trigger an update check"""
    from ..utils.updater import check_for_update

    info = check_for_update()
    return json.dumps(info or {"error": "Failed to check"}), 200


@settings_bp.route("/api/settings/updates/apply", methods=["POST"])
@protected
def api_apply_update(user: User):
    """Trigger the updater sidecar to pull and restart"""
    from ..utils.updater import apply_update

    result = apply_update()
    if "error" in result:
        return json.dumps(result), 500
    return json.dumps(result), 200


@settings_bp.route("/api/settings/updates/toggle", methods=["POST"])
@protected
def api_toggle_auto_check(user: User):
    """Toggle automatic update checking"""
    from ..utils.updater import set_auto_check_enabled, is_auto_check_enabled

    data = request.get_json()
    enabled = data.get("enabled", not is_auto_check_enabled())
    set_auto_check_enabled(enabled)
    return json.dumps({"success": True, "enabled": enabled}), 200
