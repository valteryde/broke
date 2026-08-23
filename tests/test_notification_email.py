"""Tests for notification email content (full event bodies, HTML sanitizing)."""

import json
import os
import time
from unittest.mock import patch

from fixtures import app, test_project
from ward import test

from app.utils.events import EventTypes
from app.utils.models import (
    Comment,
    ErrorGroup,
    ProjectPart,
    Ticket,
    TicketLabelJoin,
    UserTicketJoin,
)
from app.utils.notification_email import (
    build_notification_email,
    html_to_text,
    hydrate_notification_event,
    looks_like_html,
    notification_plain_text,
    sanitize_email_html,
)


@test("sanitize_email_html strips scripts and javascript urls")
def _():
    html = (
        "<p>Hello</p><script>alert(1)</script>"
        '<a href="javascript:alert(2)">x</a>'
        '<img src="javascript:alert(3)">'
    )
    out = sanitize_email_html(html, "https://broke.example")
    assert "Hello" in out
    assert "<script" not in out.lower()
    assert "alert(1)" not in out
    assert "javascript:" not in out.lower()


@test("sanitize_email_html rewrites relative image urls")
def _():
    html = '<p>See</p><img src="/uploads/shot.png" alt="shot">'
    out = sanitize_email_html(html, "https://broke.example")
    assert 'src="https://broke.example/uploads/shot.png"' in out
    assert "shot" in out


@test("html_to_text keeps link targets and image alts")
def _():
    text = html_to_text(
        '<p>Hello</p><p><a href="https://ex.test/a">here</a></p><img alt="diagram">'
    )
    assert "Hello" in text
    assert "https://ex.test/a" in text
    assert "diagram" in text


@test("ticket created email includes full description")
def _(app=app, project=test_project):
    ticket = Ticket.create(
        id=f"MAIL-{int(time.time() * 1000000)}",
        title="Cannot reset password",
        description="<p>Reset links 404 after the proxy change.</p><p>Repro: use forgot-password.</p>",
        status="todo",
        priority="high",
        project=project.id,
        created_at=int(time.time()),
    )
    UserTicketJoin.create(user="ada", ticket=ticket.id)
    TicketLabelJoin.create(ticket=ticket.id, label="auth")
    try:
        with patch.dict(os.environ, {"APP_BASE_URL": "https://broke.example"}):
            view = build_notification_email(
                {
                    "event_type": EventTypes.TICKET_CREATED,
                    "ticket_id": ticket.id,
                    "actor": "bob",
                }
            )
        assert "Cannot reset password" in view["title"]
        assert "Reset links 404 after the proxy change." in (view["body_html"] or "")
        assert "Repro: use forgot-password." in (view["body_text"] or "")
        assert ("Priority", "high") in view["fields"]
        assert ("Labels", "auth") in view["fields"]
        assert ("Assignees", "ada") in view["fields"]
        assert view["cta_url"] == f"https://broke.example/tickets/{project.id}/{ticket.id}"
        assert ticket.title in view["subject"]
    finally:
        TicketLabelJoin.delete().where(TicketLabelJoin.ticket == ticket.id).execute()
        UserTicketJoin.delete().where(UserTicketJoin.ticket == ticket.id).execute()
        ticket.delete_instance()


@test("comment email includes the full comment body")
def _(app=app, project=test_project):
    ticket = Ticket.create(
        id=f"MAILC-{int(time.time() * 1000000)}",
        title="Queue stuck",
        description="<p>ignored for comments</p>",
        status="todo",
        priority="medium",
        project=project.id,
        created_at=int(time.time()),
    )
    body = "<p>" + ("Please look at this trace. " * 20) + "</p>"
    assert len(body) > 180
    comment = Comment.create(
        ticket=ticket.id,
        user="bob",
        body=body,
        created_at=int(time.time()),
        via_agent=0,
    )
    try:
        view = build_notification_email(
            {
                "event_type": EventTypes.TICKET_COMMENTED,
                "ticket_id": ticket.id,
                "comment_id": comment.id,
                "actor": "bob",
            }
        )
        assert "Please look at this trace." in (view["body_text"] or "")
        assert view["body_text"].count("Please look at this trace.") == 20
        assert "ignored for comments" not in (view["body_text"] or "")
        assert view["body_label"] == "Comment"
    finally:
        comment.delete_instance()
        ticket.delete_instance()


@test("agent comment email includes markdown body as text")
def _():
    view = build_notification_email(
        {
            "event_type": EventTypes.TICKET_COMMENTED,
            "ticket_id": "T-1",
            "ticket_title": "Ship it",
            "project": "p",
            "actor": "agent-bot",
            "comment_body": "Done.\n\n- ran tests\n- **fixed** the race",
            "comment_via_agent": True,
        },
        hydrated=True,
    )
    assert "ran tests" in (view["body_text"] or "")
    assert "**fixed**" in (view["body_text"] or "")
    assert "<script" not in (view["body_html"] or "").lower()


@test("error email includes exception, stacktrace, and error CTA")
def _(app=app):
    part = ProjectPart.create(name=f"api-{int(time.time() * 1000000)}", description="api")
    group = ErrorGroup.create(
        part=part,
        fingerprint=f"fp-{int(time.time() * 1000000)}",
        exception_type="TypeError",
        exception_value="cannot unpack None",
        culprit="workers.py in handle",
        platform="python",
        environment="production",
        release="1.4.2",
        event_count=12,
        status="unresolved",
        stacktrace=json.dumps(
            {
                "frames": [
                    {
                        "filename": "workers.py",
                        "function": "handle",
                        "lineno": 44,
                        "in_app": True,
                        "context_line": "a, b = payload",
                        "vars": {"token": "should-not-leak"},
                    }
                ]
            }
        ),
    )
    try:
        with patch.dict(os.environ, {"APP_BASE_URL": "https://broke.example"}):
            view = build_notification_email(
                {
                    "event_type": EventTypes.ERROR_ESCALATING,
                    "error_group_id": group.id,
                    "reason": "Volume milestone: 12 total occurrences (crossed 10)",
                }
            )
        html_and_text = (view["body_html"] or "") + (view["body_text"] or "")
        assert "TypeError: cannot unpack None" == view["title"]
        assert "workers.py:44" in html_and_text
        assert "a, b = payload" in html_and_text
        assert "should-not-leak" not in html_and_text
        assert "token" not in html_and_text
        assert any(
            label == "Why" and "Volume milestone" in value for label, value in view["fields"]
        )
        assert view["cta_url"] == f"https://broke.example/errors/{part.id}/{group.id}"
        assert view["cta_label"] == "Open error →"
        assert "Error escalating" in view["subject"]
    finally:
        group.delete_instance()
        part.delete_instance()


@test("monitor down email includes checked URL and error")
def _():
    view = build_notification_email(
        {
            "event_type": EventTypes.MONITOR_DOWN,
            "monitor_id": 9,
            "monitor_name": "Homepage",
            "checked_url": "https://status.example/health",
            "last_error": "Expected status 200, got 503",
            "status_code": 503,
            "response_ms": 1200,
            "expected_status": 200,
            "project": "web",
            "status": "down",
            "monitor_url": "https://broke.example/monitors/9",
        },
        hydrated=True,
    )
    assert view["title"] == "Homepage"
    assert ("Checked URL", "https://status.example/health") in view["fields"]
    assert "Expected status 200, got 503" in (view["body_text"] or "")
    assert view["cta_url"] == "https://broke.example/monitors/9"
    text = notification_plain_text(view)
    assert "Homepage" in text
    assert "503" in text


@test("hydrate_notification_event fills ticket description from the database")
def _(app=app, project=test_project):
    ticket = Ticket.create(
        id=f"HYDR-{int(time.time() * 1000000)}",
        title="Hydrated",
        description="<p>Stored body</p>",
        status="intake",
        priority="low",
        project=project.id,
        created_at=int(time.time()),
    )
    try:
        out = hydrate_notification_event({"ticket_id": ticket.id})
        assert out["description"] == "<p>Stored body</p>"
        assert out["priority"] == "low"
        assert looks_like_html(out["description"])
    finally:
        ticket.delete_instance()
