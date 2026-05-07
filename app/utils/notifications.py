import json
import logging
import os
import time
from typing import Iterable
from urllib.parse import urlparse

import requests

from .email_branding import email_base_url, event_accent_hex, render_email
from .events import bus, EventTypes
from .mail import send_email
from .models import GlobalSetting, NotificationEventLog, User, database

logger = logging.getLogger(__name__)

DEFAULT_ENGINE_SETTINGS = {
    "channels": {
        "email": {"enabled": True},
        "slack": {"enabled": False, "webhook_url": ""},
    },
    "event_channels": {
        EventTypes.TICKET_CREATED: ["email"],
        EventTypes.TICKET_TRIAGED: ["email"],
        EventTypes.TICKET_STATUS_CHANGED: ["email"],
        EventTypes.TICKET_COMMENTED: ["email"],
        EventTypes.ANON_TICKET_SUBMITTED: ["email"],
        EventTypes.ERROR_NEW: ["email"],
        EventTypes.ERROR_REGRESSION: ["email"],
        EventTypes.ERROR_ESCALATING: ["email"],
    },
}

EVENT_SUBJECTS = {
    EventTypes.TICKET_CREATED: "Ticket created",
    EventTypes.TICKET_TRIAGED: "Ticket sent to triage",
    EventTypes.TICKET_STATUS_CHANGED: "Ticket status changed",
    EventTypes.TICKET_COMMENTED: "New ticket comment",
    EventTypes.ANON_TICKET_SUBMITTED: "Anonymous ticket submitted",
    EventTypes.ERROR_NEW: "New error group",
    EventTypes.ERROR_REGRESSION: "Error regressed",
    EventTypes.ERROR_ESCALATING: "Error escalating",
}


_ENGINE_INITIALIZED = False


def _load_engine_settings() -> dict:
    settings = dict(DEFAULT_ENGINE_SETTINGS)
    channels = dict(DEFAULT_ENGINE_SETTINGS["channels"])
    event_channels = dict(DEFAULT_ENGINE_SETTINGS["event_channels"])

    record = GlobalSetting.get_or_none(GlobalSetting.key == "notification_engine_settings")
    if not record or not record.value:
        settings["channels"] = channels
        settings["event_channels"] = event_channels
        return settings

    try:
        stored = json.loads(record.value)
    except json.JSONDecodeError:
        settings["channels"] = channels
        settings["event_channels"] = event_channels
        return settings

    stored_channels = stored.get("channels", {}) if isinstance(stored, dict) else {}
    for channel_name, channel_defaults in channels.items():
        merged = dict(channel_defaults)
        if isinstance(stored_channels.get(channel_name), dict):
            merged.update(stored_channels[channel_name])
        channels[channel_name] = merged

    if isinstance(stored, dict) and isinstance(stored.get("event_channels"), dict):
        for event_type, channel_list in stored["event_channels"].items():
            if isinstance(channel_list, list):
                event_channels[event_type] = [str(name) for name in channel_list]

    settings["channels"] = channels
    settings["event_channels"] = event_channels
    return settings


def get_notification_engine_settings() -> dict:
    return _load_engine_settings()


def save_notification_engine_settings(payload: dict) -> dict:
    current = _load_engine_settings()

    if isinstance(payload.get("channels"), dict):
        for channel_name, config in payload["channels"].items():
            if channel_name not in current["channels"] or not isinstance(config, dict):
                continue
            merged = dict(current["channels"][channel_name])
            merged.update(config)
            current["channels"][channel_name] = merged

    if isinstance(payload.get("event_channels"), dict):
        for event_type, channels in payload["event_channels"].items():
            if not isinstance(channels, list):
                continue
            current["event_channels"][event_type] = [str(channel) for channel in channels]

    record = GlobalSetting.get_or_none(GlobalSetting.key == "notification_engine_settings")
    if record:
        record.value = json.dumps(current)
        record.save()
    else:
        GlobalSetting.create(key="notification_engine_settings", value=json.dumps(current))

    return current


def _build_recipients(event: dict) -> list[str]:
    explicit = event.get("recipient_emails")
    if isinstance(explicit, list):
        recipients = [str(email).strip() for email in explicit if str(email).strip()]
        if recipients:
            return recipients

    admins = [row.email for row in User.select().where(User.admin == 1)]
    return [email for email in admins if email]


def _build_event_text(event: dict) -> str:
    event_type = event.get("event_type", "Unknown Event")
    ticket_id = event.get("ticket_id")
    ticket_title = event.get("ticket_title")
    error_group_id = event.get("error_group_id")
    part_name = event.get("part_name")
    error_url = event.get("error_url")
    environment = event.get("environment")
    release = event.get("release")
    actor = event.get("actor") or event.get("user") or "System"
    details = event.get("details") or ""
    project = event.get("project")
    status = event.get("status")

    lines = [f"Event: {event_type}"]
    if ticket_id:
        lines.append(f"Ticket: {ticket_id}")
    if ticket_title:
        lines.append(f"Title: {ticket_title}")
    if error_group_id is not None:
        lines.append(f"Error group: {error_group_id}")
    if part_name:
        lines.append(f"Part: {part_name}")
    if project:
        lines.append(f"Project: {project}")
    if environment:
        lines.append(f"Environment: {environment}")
    if release:
        lines.append(f"Release: {release}")
    if status:
        lines.append(f"Status: {status}")
    if details:
        lines.append(f"Details: {details}")
    if error_url:
        lines.append(f"Link: {error_url}")
    lines.append(f"Actor: {actor}")

    return "\n".join(lines)


def _ticket_link(event: dict) -> str | None:
    base = email_base_url().strip().rstrip("/")
    tid = event.get("ticket_id")
    proj = event.get("project")
    if not base or tid is None or proj is None:
        return None
    return f"{base}/tickets/{proj}/{tid}"


def _dispatch_email(event: dict, recipients: Iterable[str]):
    subject = EVENT_SUBJECTS.get(event.get("event_type"), event.get("event_type", "Broke notification"))
    headline = subject
    accent = event_accent_hex(event.get("event_type"))
    ticket_url = _ticket_link(event)

    html = render_email(
        "email/notification_event.jinja2",
        event=event,
        headline=headline,
        accent=accent,
        ticket_url=ticket_url,
    )
    text = render_email(
        "email/notification_event.txt.jinja2",
        event=event,
        headline=headline,
        ticket_url=ticket_url,
    )

    for email in recipients:
        if not send_email(email, f"Broke: {subject}", html, text_content=text):
            raise RuntimeError(f"Failed to send notification email to {email}")


def _dispatch_slack(event: dict, webhook_url: str):
    parsed = urlparse(str(webhook_url or "").strip())
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise ValueError("Slack webhook URL must use HTTPS")

    # Tests use https://example.com/... as a placeholder; avoid real HTTP (SSL noise,
    # non-2xx from a non-webhook URL) while still exercising routing and validation.
    if (
        str(os.environ.get("FLASK_ENV", "")).strip().lower() == "testing"
        and (parsed.hostname or "").lower() == "example.com"
    ):
        return

    text = _build_event_text(event)
    response = requests.post(
        webhook_url,
        json={"text": text},
        timeout=5,
    )
    response.raise_for_status()


def _log_delivery(event_type: str, channel: str, status: str, message: str = ""):
    try:
        NotificationEventLog.create(
            event_type=event_type,
            channel=channel,
            status=status,
            detail=message[:500],
            created_at=int(time.time()),
        )
    except Exception:
        logger.exception("Failed to write notification event log")


def handle_notification_event(**event):
    with database.connection_context():
        _handle_notification_event_impl(**event)


def _handle_notification_event_impl(**event):
    settings = _load_engine_settings()
    event_type = event.get("event_type")
    if not event_type:
        return

    channels_for_event = settings["event_channels"].get(event_type, [])
    recipients = _build_recipients(event)

    for channel_name in channels_for_event:
        try:
            if channel_name == "email":
                if not settings["channels"].get("email", {}).get("enabled", True):
                    continue
                if not recipients:
                    continue
                _dispatch_email(event, recipients)
                _log_delivery(event_type, "email", "success")
            elif channel_name == "slack":
                channel_config = settings["channels"].get("slack", {})
                if not channel_config.get("enabled", False):
                    continue
                webhook_url = str(channel_config.get("webhook_url", "")).strip()
                if not webhook_url:
                    continue
                _dispatch_slack(event, webhook_url)
                _log_delivery(event_type, "slack", "success")
        except Exception as exc:
            logger.exception("Notification dispatch failed")
            _log_delivery(event_type, channel_name, "error", str(exc))


def initialize_notification_engine():
    global _ENGINE_INITIALIZED
    if _ENGINE_INITIALIZED:
        return

    for event_type in [
        EventTypes.TICKET_CREATED,
        EventTypes.TICKET_TRIAGED,
        EventTypes.TICKET_STATUS_CHANGED,
        EventTypes.TICKET_COMMENTED,
        EventTypes.ANON_TICKET_SUBMITTED,
        EventTypes.ERROR_NEW,
        EventTypes.ERROR_REGRESSION,
        EventTypes.ERROR_ESCALATING,
    ]:
        bus.subscribe(event_type, handle_notification_event)

    _ENGINE_INITIALIZED = True
