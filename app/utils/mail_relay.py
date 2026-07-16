"""HTTPS email relay client (broke-saas / compatible panels)."""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urljoin

import requests

logger = logging.getLogger(__name__)

RELAY_SEND_PATH = "relay/v1/send/"

ENV_RELAY_BASE_URL = "BROKE_MAIL_RELAY_BASE_URL"
ENV_RELAY_TOKEN = "BROKE_MAIL_RELAY_TOKEN"


def relay_base_url_from_environment() -> str:
    return (os.environ.get(ENV_RELAY_BASE_URL) or "").strip().rstrip("/")


def relay_token_from_environment() -> str:
    return (os.environ.get(ENV_RELAY_TOKEN) or "").strip()


def relay_send_url(base_url: str) -> str:
    base = base_url.strip().rstrip("/") + "/"
    return urljoin(base, RELAY_SEND_PATH)


def send_via_relay(
    base_url: str,
    token: str,
    to_email: str,
    subject: str,
    html_content: str,
    text_content: str | None,
    from_email: str | None,
) -> bool:
    if "\n" in subject or "\r" in subject:
        logger.warning("Refusing to send email: subject contains newline characters")
        return False

    if not text_content and not (html_content or "").strip():
        logger.warning("Refusing relay send: need text and/or html body")
        return False

    url = relay_send_url(base_url)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }

    body: dict[str, Any] = {
        "to": [to_email],
        "cc": [],
        "bcc": [],
        "reply_to": [],
        "subject": subject,
        "text": text_content or "",
        "html": html_content or "",
    }
    if from_email:
        body["from"] = from_email

    try:
        response = requests.post(url, json=body, headers=headers, timeout=30)
    except requests.RequestException as exc:
        logger.error("Mail relay request failed: %s", exc)
        return False

    try:
        payload = response.json()
    except ValueError:
        logger.error("Mail relay returned non-JSON response (HTTP %s)", response.status_code)
        return False

    if response.status_code == 200 and payload.get("ok") is True:
        tenant = payload.get("tenant")
        n = payload.get("recipients")
        logger.info("Mail relay accepted send (tenant=%s recipients=%s)", tenant, n)
        return True

    err = payload.get("error") if isinstance(payload, dict) else None
    code = ""
    message = ""
    if isinstance(err, dict):
        code = str(err.get("code") or "")
        message = str(err.get("message") or "")
    detail = f"{code} {message}".strip() or response.text[:500]

    if response.status_code in (401, 403):
        logger.warning("Mail relay rejected send (non-retriable): HTTP %s %s", response.status_code, detail)
    else:
        logger.error("Mail relay send failed: HTTP %s %s", response.status_code, detail)
    return False
