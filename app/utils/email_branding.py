"""Branding constants and Jinja rendering for transactional HTML emails."""

import os
from typing import Any

from flask import render_template

# Mirror app/static/css/master.css — email clients ignore CSS variables.
BRAND = {
    "logo_blue": "#106ecc",
    "bg_gray": "#c6c6c6",
    "bg_white": "#f5f5f5",
    "bg_light_gray": "#eaeaea",
    "secondary": "#666666",
    "danger": "#ef4444",
    "body_font": "'Rubik', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    "heading_font": "'Space Grotesk', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
}

# Per-event accent (matches .status-* / product palette in master.css).
EVENT_ACCENT_HEX: dict[str, str] = {
    "TICKET_CREATED": "#8b5cf6",
    "TICKET_TRIAGED": "#f59e0b",
    "TICKET_STATUS_CHANGED": "#3b82f6",
    "TICKET_COMMENTED": "#106ecc",
    "ANON_TICKET_SUBMITTED": "#22c55e",
}


def email_base_url() -> str:
    return (os.environ.get("APP_BASE_URL", "") or "").strip().rstrip("/")


def email_logo_url() -> str | None:
    base = email_base_url()
    if not base:
        return None
    return f"{base}/static/images/logo_v2.png"


def event_accent_hex(event_type: str | None) -> str:
    if not event_type:
        return BRAND["logo_blue"]
    return EVENT_ACCENT_HEX.get(str(event_type), BRAND["logo_blue"])


def render_email(template_name: str, **kwargs: Any) -> str:
    """Render a Jinja email template; requires Flask app (create_app / get_app)."""
    from .app import get_app

    app = get_app()
    if app is None:
        raise RuntimeError("Flask application not initialized; cannot render email templates")

    ctx = {"brand": BRAND, "email_base_url": email_base_url(), "email_logo_url": email_logo_url()}
    ctx.update(kwargs)
    with app.app_context():
        with app.test_request_context():
            return render_template(template_name, **ctx)
