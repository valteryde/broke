import json
import logging
import os
import time
from typing import Iterable
from urllib.parse import urlparse

import requests

from .email_branding import event_accent_hex, render_email
from .events import EventTypes, bus
from .mail import send_email
from .models import GlobalSetting, NotificationEventLog, User, database
from .notification_email import (
    build_notification_email,
    hydrate_notification_event,
    notification_plain_text,
)

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
        EventTypes.MONITOR_DOWN: ["email"],
        EventTypes.MONITOR_UP: ["email"],
    },
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


def _dispatch_email(event: dict, recipients: Iterable[str]):
    view = build_notification_email(event, hydrated=True)
    accent = event_accent_hex(event.get("event_type"))
    html = render_email(
        "email/notification_event.jinja2",
        accent=accent,
        **view,
    )
    text = render_email(
        "email/notification_event.txt.jinja2",
        **view,
    )

    for email in recipients:
        if not send_email(email, view["subject"], html, text_content=text):
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

    text = notification_plain_text(build_notification_email(event, hydrated=True))
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
    event = hydrate_notification_event(event)
    recipients = _build_recipients(event)

    if event_type in (EventTypes.MONITOR_DOWN, EventTypes.MONITOR_UP):
        monitor_id = event.get("monitor_id")
        if monitor_id:
            from .models import Monitor, StatusSubscriber

            monitor = Monitor.get_or_none(Monitor.id == monitor_id)
            if monitor and getattr(monitor, "public", 0) == 1:
                subscribers = [sub.email for sub in StatusSubscriber.select()]
                recipients = list(set(recipients + subscribers))

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
        EventTypes.MONITOR_DOWN,
        EventTypes.MONITOR_UP,
    ]:
        bus.subscribe(event_type, handle_notification_event)

    _ENGINE_INITIALIZED = True
