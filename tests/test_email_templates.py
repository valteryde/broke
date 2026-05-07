"""Smoke tests for Jinja email HTML."""

from ward import test


@test("password reset email template includes branding and reset link")
def _():
    from app.utils.app import create_app
    from app.utils.email_branding import render_email

    app = create_app()
    with app.app_context():
        html = render_email(
            "email/password_reset.jinja2",
            display_name="Ada",
            reset_link="https://broke.example/reset/abc",
        )
    assert "Broke" in html
    assert "#106ecc" in html
    assert "https://broke.example/reset/abc" in html
    assert "Ada" in html


@test("notification email template surfaces ticket data and accent color")
def _():
    from app.utils.app import create_app
    from app.utils.email_branding import event_accent_hex, render_email
    from app.utils.events import EventTypes

    app = create_app()
    event = {
        "event_type": EventTypes.TICKET_CREATED,
        "ticket_id": 42,
        "ticket_title": "Fix the widget",
        "project": 3,
        "actor": "bob",
        "details": "New intake",
    }
    with app.app_context():
        html = render_email(
            "email/notification_event.jinja2",
            event=event,
            headline="Ticket created",
            accent=event_accent_hex(EventTypes.TICKET_CREATED),
            ticket_url="https://broke.example/tickets/3/42",
        )
    assert "8b5cf6" in html
    assert "Fix the widget" in html
    assert "https://broke.example/tickets/3/42" in html
    assert "bob" in html


@test("render_email raises when Flask app is not initialized")
def _():
    from app.utils import app as app_module
    from app.utils.email_branding import render_email

    saved = app_module._app
    app_module._app = None
    try:
        try:
            render_email(
                "email/password_reset.jinja2",
                display_name="x",
                reset_link="https://example.com/r",
            )
        except RuntimeError as exc:
            assert "Flask application not initialized" in str(exc)
        else:
            raise AssertionError("expected RuntimeError")
    finally:
        app_module._app = saved
