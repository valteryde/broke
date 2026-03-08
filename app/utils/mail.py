import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import logging
from .events import bus
from .models import GlobalSetting
import json

logger = logging.getLogger(__name__)


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
        record = GlobalSetting.get_or_none(GlobalSetting.key == "smtp_settings")
        if record and record.value:
            stored = json.loads(record.value)
            settings["host"] = str(stored.get("host", settings["host"]))
            settings["port"] = int(stored.get("port", settings["port"]))
            settings["username"] = str(stored.get("username", settings["username"]))
            settings["password"] = str(stored.get("password", settings["password"]))
            settings["from"] = str(stored.get("from", settings["from"]))
            settings["use_tls"] = bool(stored.get("use_tls", True))
    except Exception:
        # Keep env/default settings if settings table is unavailable or malformed.
        pass

    return settings

def send_email(to_email, subject, html_content):
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
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_from
    msg["To"] = to_email

    part1 = MIMEText(html_content, "html")
    msg.attach(part1)

    try:
        server = smtplib.SMTP(smtp_host, int(smtp_port))
        server.ehlo()
        if use_tls and smtp_host not in ["localhost", "127.0.0.1"]:
            server.starttls()
            if smtp_user and smtp_password:
                server.login(smtp_user, smtp_password)
        server.sendmail(smtp_from, to_email, msg.as_string())
        server.quit()
        logger.info(f"Email sent to {to_email}")
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")

def handle_password_reset(user=None, token=None, reset_url=None, **_event):
    if not user or not token:
        return

    reset_link = reset_url
    if not reset_link:
        base_url = os.environ.get("APP_BASE_URL", "").strip().rstrip("/")
        if not base_url:
            logger.warning("APP_BASE_URL not configured. Skipping password reset email for %s", user.email)
            return
        reset_link = f"{base_url}/reset-password/{token}"

    html = f"""
    <html>
      <body>
        <h2>Password Reset</h2>
        <p>Hello {user.username},</p>
        <p>You requested a password reset. Click the link below to set a new password:</p>
        <p><a href="{reset_link}">Reset Password</a></p>
        <p>If you didn't request this, you can safely ignore this email.</p>
      </body>
    </html>
    """
    send_email(user.email, "Password Reset", html)

# Subscribe to events
bus.subscribe("USER_PASSWORD_RESET", handle_password_reset)
