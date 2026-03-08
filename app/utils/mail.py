import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import logging
from .events import bus

logger = logging.getLogger(__name__)

def send_email(to_email, subject, html_content):
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = os.environ.get("SMTP_PORT", 587)
    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    smtp_from = os.environ.get("SMTP_FROM", "noreply@broke.dk")

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
        # Only starttls if not localhost/testing
        if smtp_host not in ["localhost", "127.0.0.1"]:
            server.starttls()
            if smtp_user and smtp_password:
                server.login(smtp_user, smtp_password)
        server.sendmail(smtp_from, to_email, msg.as_string())
        server.quit()
        logger.info(f"Email sent to {to_email}")
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")

def handle_password_reset(user=None, token=None, reset_url=None):
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
