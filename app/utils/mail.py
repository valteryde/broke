import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import logging
from .events import bus
from .models import GlobalSetting, database
import json

logger = logging.getLogger(__name__)


def _merge_db_smtp_over_env(settings: dict, stored: dict) -> None:
    """Apply DB settings; only non-empty string values override env (empty never wipes env)."""
    for key in ("host", "username", "password", "from"):
        if key not in stored:
            continue
        raw = stored.get(key)
        if raw is None:
            continue
        merged = str(raw).strip()
        if merged:
            settings[key] = merged

    if "port" in stored:
        try:
            p = int(stored["port"])
            if 0 < p <= 65535:
                settings["port"] = p
        except (TypeError, ValueError):
            pass

    if "use_tls" in stored:
        settings["use_tls"] = bool(stored["use_tls"])


def _load_smtp_settings() -> dict:
    settings = {
        "host": os.environ.get("SMTP_HOST", "").strip(),
        "port": int(os.environ.get("SMTP_PORT", 587)),
        "username": os.environ.get("SMTP_USER", "").strip(),
        "password": os.environ.get("SMTP_PASSWORD", "").strip(),
        "from": os.environ.get("SMTP_FROM", "noreply@broke.dk").strip(),
        "use_tls": True,
    }

    try:
        with database.connection_context():
            record = GlobalSetting.get_or_none(GlobalSetting.key == "smtp_settings")
            if record and record.value:
                stored = json.loads(record.value)
                if isinstance(stored, dict):
                    _merge_db_smtp_over_env(settings, stored)
    except Exception:
        # Keep env/default settings if settings table is unavailable or malformed.
        pass

    return settings


def send_email(to_email, subject, html_content, text_content=None):
    """Send one HTML email (optional multipart plain + HTML). Returns True on success, False when skipped or on failure."""
    smtp_settings = _load_smtp_settings()
    smtp_host = smtp_settings["host"]
    smtp_port = smtp_settings["port"]
    smtp_user = smtp_settings["username"]
    smtp_password = smtp_settings["password"]
    smtp_from = smtp_settings["from"]
    use_tls = smtp_settings["use_tls"]

    if not smtp_host:
        logger.warning(
            "SMTP not configured. Skipping email to %s. "
            "Admins can recover access by setting a temporary password from team settings.",
            to_email,
        )
        return False

    smtp_from = (smtp_from or "").strip() or (smtp_user if "@" in smtp_user else "") or os.environ.get(
        "SMTP_FROM", "noreply@broke.dk"
    ).strip()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_from
    msg["To"] = to_email

    if text_content:
        msg.attach(MIMEText(text_content, "plain", "utf-8"))
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    port = int(smtp_port)
    host_lower = smtp_host.strip().lower()
    is_local = host_lower in ("localhost", "127.0.0.1")
    # Port 465 uses implicit TLS (SSL from connect); STARTTLS on 465 will not work.
    use_implicit_ssl = port == 465

    try:
        if use_implicit_ssl:
            server = smtplib.SMTP_SSL(smtp_host, port)
            server.ehlo()
        else:
            server = smtplib.SMTP(smtp_host, port)
            server.ehlo()
            if use_tls and not is_local:
                server.starttls()
                server.ehlo()

        if smtp_user and smtp_password:
            server.login(smtp_user, smtp_password)

        server.sendmail(smtp_from, to_email, msg.as_string())
        server.quit()
        logger.info(f"Email sent to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        return False


def handle_password_reset(
    user=None, token=None, reset_url=None, recipient_email=None, username=None, **_event
):
    to_email = (recipient_email or "").strip()
    if not to_email and user is not None:
        to_email = (getattr(user, "email", None) or "").strip()
    display_name = (username or "").strip()
    if not display_name and user is not None:
        display_name = (getattr(user, "username", None) or "").strip()

    if not to_email or not token:
        return

    reset_link = reset_url
    if not reset_link:
        base_url = os.environ.get("APP_BASE_URL", "").strip().rstrip("/")
        if not base_url:
            logger.warning(
                "APP_BASE_URL not configured. Skipping password reset email for %s", to_email
            )
            return
        reset_link = f"{base_url}/reset-password/{token}"

    greeting = display_name or "there"
    from .email_branding import render_email

    html = render_email(
        "email/password_reset.jinja2",
        display_name=greeting,
        reset_link=reset_link,
    )
    text = render_email(
        "email/password_reset.txt.jinja2",
        display_name=greeting,
        reset_link=reset_link,
    )
    send_email(to_email, "Password Reset", html, text_content=text)


# Subscribe to events
bus.subscribe("USER_PASSWORD_RESET", handle_password_reset)
