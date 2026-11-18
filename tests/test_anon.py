"""Tests for anonymous ticket submission."""

import json
import re
import time
import uuid
from unittest.mock import patch

from ward import Scope, fixture, test

from app.utils.anon_enrich import review_anon_report
from app.utils.anon_intake import checked_fields
from app.utils.models import (
    AnonContact,
    AnonDraft,
    GlobalSetting,
    Ticket,
    TicketUpdateMessage,
)
from tests.fixtures import app, auth_client, auth_user, client, create_test_project

VERIFY_RE = re.compile(r"/anon/verify/([A-Za-z0-9_\-]+)")


def _long(seed: str, words: str) -> str:
    return f"{seed} {words} " + ("detail " * 8)


def problem_answers(seed: str | None = None) -> dict:
    seed = seed or uuid.uuid4().hex[:8]
    return {
        "kind": "problem",
        "title": f"Login fails after reset {seed}",
        "detail": _long(
            seed,
            "I reset the password from the email link and the login page says it is wrong. "
            "I expected the account page after signing in. The billing team has been blocked "
            "since this morning, and it happens on the login page.",
        ),
        "system": f"Chrome on Windows 11, app version 2.4, {seed}",
    }


@fixture(scope=Scope.Test)
def anon_enabled_project(app=app):
    project_id = f"test-anon-proj-{uuid.uuid4().hex[:8]}"
    project = create_test_project(project_id, "Test Anonymous Project", "For testing anon submissions")
    GlobalSetting.delete().where(GlobalSetting.key == "anonymous_settings").execute()
    GlobalSetting.create(
        key="anonymous_settings",
        value=json.dumps(
            {"enabled": True, "message": "Welcome! Please submit your ticket.", "projects": []}
        ),
    )
    yield project
    GlobalSetting.delete().where(GlobalSetting.key == "anonymous_settings").execute()
    project.delete_instance()


@fixture(scope=Scope.Test)
def sent_mail():
    sent: list[dict] = []

    def fake_send(to_email, subject, html_content, text_content=None):
        sent.append(
            {
                "to": to_email,
                "subject": subject,
                "html": html_content or "",
                "text": text_content or "",
            }
        )
        return True

    with (
        patch("app.utils.anon_intake.send_email", fake_send),
        patch("app.views.anon.outbound_mail_configured", return_value=True),
        patch("app.utils.ai_changelog.get_ai_config", return_value=None),
        patch("app.utils.anon_enrich.get_ai_config", return_value=None),
    ):
        yield sent


def _review(c, answers: dict) -> dict:
    response = c.post("/api/anon/review", json=answers)
    assert response.status_code == 200, response.data
    return response.get_json()


def _submit(c, answers: dict, primary: str, copies: list[str] | None = None, token: str | None = None):
    payload = dict(answers)
    payload["review_token"] = token if token is not None else _review(c, answers)["review_token"]
    payload["primary_email"] = primary
    payload["copy_emails"] = copies or []
    payload["priority"] = "urgent"
    payload["project"] = "NOPE"
    return c.post("/api/anon/submit", json=payload)


def _token_for(sent: list[dict], email: str) -> str:
    for message in sent:
        if message["to"] == email and "/anon/verify/" in message["text"]:
            match = VERIFY_RE.search(message["text"])
            if match:
                return match.group(1)
    raise AssertionError(f"no verify link for {email}")


def _confirm(c, sent: list[dict], email: str):
    token = _token_for(sent, email)
    return c.post(f"/anon/verify/{token}", follow_redirects=False)


@test("/anon GET when disabled returns 403")
def _(c=client):
    GlobalSetting.delete().where(GlobalSetting.key == "anonymous_settings").execute()
    GlobalSetting.create(key="anonymous_settings", value=json.dumps({"enabled": False}))
    response = c.get("/anon")
    assert response.status_code == 403
    assert b"disabled" in response.data


@test("/avatar/<username> GET returns 404 when avatar missing")
def _(c=client):
    response = c.get(f"/avatar/missing-user-{int(time.time() * 1000000)}")
    assert response.status_code == 404


@test("/anon GET when enabled shows the kind choice and a checklist renderer")
def _(c=client, project=anon_enabled_project):
    response = c.get("/anon")
    assert response.status_code == 200
    assert b"Problem" in response.data
    assert b"Feature" in response.data
    assert b"Improvement" in response.data
    assert b"What system is this on?" in response.data
    assert b"anon-review-row" in response.data
    assert b"Reading your report" in response.data
    assert b"Quill" not in response.data
    assert b'name="priority"' not in response.data
    assert b"where-project" not in response.data
    assert project.name.encode() not in response.data


@test("/anon GET when mail is off still offers send")
def _(c=client, project=anon_enabled_project):
    with patch("app.views.anon.outbound_mail_configured", return_value=False):
        response = c.get("/anon")
    assert response.status_code == 200
    assert b"cannot send a confirmation" not in response.data
    assert b"data-mail-off" not in response.data
    assert b"Send" in response.data


@test("/anon/<project_id> GET redirects to /anon")
def _(c=client, project=anon_enabled_project):
    response = c.get(f"/anon/{project.id}")
    assert response.status_code == 302
    assert response.location.endswith("/anon")

    response = c.get("/anon/invalid-project-id")
    assert response.status_code == 302
    assert response.location.endswith("/anon")


@test("review of a thin report returns notes and stores nothing")
def _(c=client, project=anon_enabled_project, sent=sent_mail):
    before_drafts = AnonDraft.select().count()
    before_tickets = Ticket.select().count()
    answers = problem_answers()
    answers["title"] = "Short"
    payload = _review(c, answers)
    assert payload["ready"] is False
    assert payload["headline"]
    assert payload["notes"]
    assert "review_token" not in payload
    assert any(note["field"] == "title" for note in payload["notes"])
    assert AnonDraft.select().count() == before_drafts
    assert Ticket.select().count() == before_tickets
    assert sent == []


@test("a ready review returns a token and still stores nothing")
def _(c=client, project=anon_enabled_project, sent=sent_mail):
    before = AnonDraft.select().count()
    payload = _review(c, problem_answers())
    assert payload["ready"] is True
    assert payload["review_token"]
    assert len(payload["notes"]) == 3
    assert AnonDraft.select().count() == before


@test("submit without a token stores nothing")
def _(c=client, project=anon_enabled_project, sent=sent_mail):
    before = AnonDraft.select().count()
    response = c.post(
        "/api/anon/submit",
        json={**problem_answers(), "primary_email": "a@example.com"},
    )
    assert response.status_code == 400
    assert AnonDraft.select().count() == before
    body = response.get_json()
    assert "ticket_id" not in body
    assert "secret" not in body


@test("submit with a token for different answers stores nothing")
def _(c=client, project=anon_enabled_project, sent=sent_mail):
    answers = problem_answers()
    token = _review(c, answers)["review_token"]
    answers["title"] = answers["title"] + " edited"
    before = AnonDraft.select().count()
    response = _submit(c, answers, "a@example.com", token=token)
    assert response.status_code == 400
    assert AnonDraft.select().count() == before


@test("a failed immediate filing leaves no ticket")
def _(c=client, project=anon_enabled_project):
    answers = problem_answers()

    def explode(*_args, **_kwargs):
        raise RuntimeError("update row failed")

    with (
        patch("app.utils.ai_changelog.get_ai_config", return_value=None),
        patch("app.utils.anon_enrich.get_ai_config", return_value=None),
        patch("app.views.anon.outbound_mail_configured", return_value=False),
        patch("app.utils.anon_intake.TicketUpdateMessage.create", explode),
    ):
        token = _review(c, answers)["review_token"]
        response = _submit(c, answers, "a@example.com", token=token)
    assert response.status_code == 500, response.data
    assert Ticket.select().where(Ticket.title == answers["title"]).count() == 0


@test("submit with mail unconfigured creates the ticket")
def _(c=client, project=anon_enabled_project):
    answers = problem_answers()
    with (
        patch("app.utils.ai_changelog.get_ai_config", return_value=None),
        patch("app.utils.anon_enrich.get_ai_config", return_value=None),
        patch("app.views.anon.outbound_mail_configured", return_value=False),
    ):
        token = _review(c, answers)["review_token"]
        response = _submit(c, answers, "a@example.com", token=token)
    assert response.status_code == 201, response.data
    body = response.get_json()
    assert body["success"] is True
    assert body["pending"] is False
    assert body["track"].startswith("/anon/track/")
    assert "ticket_id" not in body
    ticket = Ticket.get(Ticket.title == answers["title"])
    assert ticket.status == "intake"
    assert ticket.project == "TRIAGE"
    assert f"/anon/track/{ticket.anonymous_secret}" == body["track"]
    assert AnonDraft.select().where(AnonDraft.payload.contains(answers["title"])).count() == 0
    track = c.get(body["track"])
    assert track.status_code == 200
    assert answers["title"].encode() in track.data


@test("primary send failure deletes the draft")
def _(c=client, project=anon_enabled_project):
    answers = problem_answers()

    def fail_send(*_args, **_kwargs):
        return False

    with (
        patch("app.utils.anon_intake.send_email", fail_send),
        patch("app.views.anon.outbound_mail_configured", return_value=True),
        patch("app.utils.ai_changelog.get_ai_config", return_value=None),
    ):
        token = _review(c, answers)["review_token"]
        response = _submit(c, answers, "fail@example.com", token=token)
    assert response.status_code == 503
    assert AnonDraft.select().where(AnonDraft.payload.contains(answers["title"])).count() == 0
    assert Ticket.select().where(Ticket.title == answers["title"]).count() == 0


@test("copy send failure leaves the draft and that copy unconfirmed")
def _(c=client, project=anon_enabled_project):
    answers = problem_answers()
    primary = f"primary-{uuid.uuid4().hex[:6]}@example.com"
    copy = f"copy-{uuid.uuid4().hex[:6]}@example.com"

    def send(to_email, subject, html_content, text_content=None):
        return "copy-" not in to_email

    with (
        patch("app.utils.anon_intake.send_email", send),
        patch("app.views.anon.outbound_mail_configured", return_value=True),
        patch("app.utils.ai_changelog.get_ai_config", return_value=None),
    ):
        token = _review(c, answers)["review_token"]
        response = _submit(c, answers, primary, copies=[copy], token=token)
    assert response.status_code == 201
    contact = AnonContact.get(AnonContact.email == copy)
    assert contact.verified_at is None
    assert contact.role == "copy"


@test("valid submit creates a draft and no ticket")
def _(c=client, project=anon_enabled_project, sent=sent_mail):
    answers = problem_answers()
    email = f"p-{uuid.uuid4().hex[:6]}@example.com"
    before = Ticket.select().count()
    response = _submit(c, answers, email)
    assert response.status_code == 201
    body = response.get_json()
    assert body == {"success": True, "pending": True}
    assert "ticket_id" not in body
    assert "possible_duplicates" not in body
    assert Ticket.select().count() == before
    assert AnonDraft.select().where(AnonDraft.payload.contains(answers["title"])).count() == 1
    assert sent[0]["to"] == email
    assert answers["title"] in sent[0]["text"]


@test("a fourth open draft for the same address is rejected")
def _(c=client, project=anon_enabled_project, sent=sent_mail):
    email = f"cap-{uuid.uuid4().hex[:6]}@example.com"
    for _ in range(3):
        response = _submit(c, problem_answers(), email)
        assert response.status_code == 201
    response = _submit(c, problem_answers(), email)
    assert response.status_code == 400
    assert b"already waiting" in response.data


@test("unknown kind and a missing feature answer are rejected by name")
def _(c=client, project=anon_enabled_project, sent=sent_mail):
    unknown = c.post("/api/anon/review", json={"kind": "other", "title": "Hello there friend"})
    assert unknown.status_code == 400
    assert unknown.get_json()["field"] == "kind"

    feature = {
        "kind": "feature",
        "title": "Add an export button for invoices",
        "missing": "short",
    }
    payload = _review(c, feature)
    assert payload["ready"] is False
    assert any(note["field"] == "missing" for note in payload["notes"])
    assert any(note["field"] == "gap" for note in payload["notes"])
    assert any(note["field"] == "avoid" for note in payload["notes"])

    assert _review(c, problem_answers())["ready"] is True

    thin_system = problem_answers()
    thin_system["system"] = "phone"
    system_notes = _review(c, thin_system)
    assert system_notes["ready"] is False
    assert any(note["field"] == "system" and note["ok"] is False for note in system_notes["notes"])

    missing_system = problem_answers()
    missing_system.pop("system")
    missing_notes = _review(c, missing_system)
    assert missing_notes["ready"] is False
    assert any(note["field"] == "system" for note in missing_notes["notes"])


@test("GET verify does not create a ticket")
def _(c=client, project=anon_enabled_project, sent=sent_mail):
    answers = problem_answers()
    email = f"get-{uuid.uuid4().hex[:6]}@example.com"
    assert _submit(c, answers, email).status_code == 201
    before = Ticket.select().count()
    token = _token_for(sent, email)
    response = c.get(f"/anon/verify/{token}")
    assert response.status_code == 200
    assert b"Confirm" in response.data
    assert Ticket.select().count() == before
    contact = AnonContact.get(AnonContact.email == email)
    assert contact.verified_at is None


@test("POST verify creates one intake ticket and a second POST does not")
def _(c=client, project=anon_enabled_project, sent=sent_mail):
    answers = problem_answers()
    email = f"post-{uuid.uuid4().hex[:6]}@example.com"
    assert _submit(c, answers, email).status_code == 201
    first = _confirm(c, sent, email)
    assert first.status_code == 302
    ticket = Ticket.get(Ticket.title == answers["title"])
    assert ticket.status == "intake"
    assert ticket.project == "TRIAGE"
    assert ticket.priority == "medium"
    assert ticket.estimate_minutes is None
    assert ticket.anonymous_secret
    assert "What system is this on?" in ticket.description
    assert answers["system"] in ticket.description
    assert first.location.endswith(f"/anon/track/{ticket.anonymous_secret}")
    second = _confirm(c, sent, email)
    assert second.status_code == 302
    assert second.location == first.location
    assert Ticket.select().where(Ticket.title == answers["title"]).count() == 1


@test("an unconfirmed copy does not block, and an early copy is mailed when the ticket exists")
def _(c=client, project=anon_enabled_project, sent=sent_mail):
    answers = problem_answers()
    primary = f"prim-{uuid.uuid4().hex[:6]}@example.com"
    copy = f"copy-{uuid.uuid4().hex[:6]}@example.com"
    assert _submit(c, answers, primary, copies=[copy]).status_code == 201
    copy_mail = next(item for item in sent if item["to"] == copy)
    assert answers["title"] not in copy_mail["text"]
    assert answers["title"] not in copy_mail["html"]
    _confirm(c, sent, copy)
    assert Ticket.select().where(Ticket.title == answers["title"]).count() == 0
    assert AnonContact.get(AnonContact.email == copy).verified_at is not None
    _confirm(c, sent, primary)
    received = [item for item in sent if item["subject"] == "We received your report"]
    assert {item["to"] for item in received} == {primary, copy}


@test("a copy who confirms later receives the tracking mail once")
def _(c=client, project=anon_enabled_project, sent=sent_mail):
    answers = problem_answers()
    primary = f"late-p-{uuid.uuid4().hex[:6]}@example.com"
    copy = f"late-c-{uuid.uuid4().hex[:6]}@example.com"
    assert _submit(c, answers, primary, copies=[copy]).status_code == 201
    _confirm(c, sent, primary)
    _confirm(c, sent, copy)
    _confirm(c, sent, copy)
    received = [item for item in sent if item["to"] == copy and item["subject"] == "We received your report"]
    assert len(received) == 1


@test("an expired confirm creates nothing")
def _(c=client, project=anon_enabled_project, sent=sent_mail):
    answers = problem_answers()
    email = f"old-{uuid.uuid4().hex[:6]}@example.com"
    assert _submit(c, answers, email).status_code == 201
    draft = AnonDraft.get(AnonDraft.payload.contains(answers["title"]))
    draft.expires_at = int(time.time()) - 10
    draft.save()
    response = _confirm(c, sent, email)
    assert response.status_code == 400
    assert Ticket.select().where(Ticket.title == answers["title"]).count() == 0


@test("duplicate hints stay on the internal row")
def _(c=client, project=anon_enabled_project, sent=sent_mail):
    answers = problem_answers()
    existing = Ticket.create(
        id=f"DUP-{uuid.uuid4().hex[:6]}",
        title=answers["title"],
        description=answers["detail"],
        status="todo",
        priority="low",
        project=project.id,
        created_at=int(time.time()),
    )
    email = f"dup-{uuid.uuid4().hex[:6]}@example.com"
    assert _submit(c, answers, email).status_code == 201
    confirmed = _confirm(c, sent, email)
    assert b"possible_duplicates" not in confirmed.data
    ticket = Ticket.get(Ticket.title == answers["title"], Ticket.anonymous_secret.is_null(False))
    internal = TicketUpdateMessage.get(
        (TicketUpdateMessage.ticket == ticket.id)
        & (TicketUpdateMessage.title == "Anonymous ticket created")
    )
    assert existing.id in internal.message
    assert internal.public == 0
    track = c.get(confirmed.location)
    assert existing.id.encode() not in track.data
    assert b"Problem" in track.data
    assert b"We received this report." in track.data
    assert project.name.encode() not in track.data
    assert b"TRIAGE" not in track.data


@test("status mail reaches confirmed contacts and skips staff names")
def _(auth=auth_client, user=auth_user, project=anon_enabled_project, sent=sent_mail):
    answers = problem_answers()
    email = f"stat-{uuid.uuid4().hex[:6]}@example.com"
    assert _submit(auth, answers, email).status_code == 201
    confirmed = _confirm(auth, sent, email)
    ticket = Ticket.get(Ticket.anonymous_secret.is_null(False), Ticket.title == answers["title"])
    before = len(sent)
    response = auth.patch(
        f"/api/tickets/{ticket.id}",
        json={"field": "status", "value": "triage"},
    )
    assert response.status_code == 200, response.data
    public = TicketUpdateMessage.get(
        (TicketUpdateMessage.ticket == ticket.id) & (TicketUpdateMessage.public == 1) & (TicketUpdateMessage.title == "Status")
    )
    assert public.message == "Status is now Triage."
    assert user.username not in public.message
    status_mail = [item for item in sent[before:] if item["subject"] == "Update on your report"]
    assert [item["to"] for item in status_mail] == [email]
    assert user.username not in status_mail[0]["text"]
    assert ticket.project not in status_mail[0]["text"]
    track = auth.get(confirmed.location)
    assert user.username.encode() not in track.data
    assert b"Status is now Triage." in track.data
    assert project.name.encode() not in track.data

    phrase = f"staff-only-{uuid.uuid4().hex}"
    comment = auth.post(
        f"/api/tickets/{ticket.id}/comments",
        json={"content": phrase},
    )
    assert comment.status_code == 201
    track = auth.get(confirmed.location)
    assert phrase.encode() not in track.data
    assert all(phrase not in item["text"] and phrase not in item["html"] for item in sent)


@test("a public reply is mailed and shown on the tracking page")
def _(auth=auth_client, project=anon_enabled_project, sent=sent_mail):
    answers = problem_answers()
    email = f"reply-{uuid.uuid4().hex[:6]}@example.com"
    assert _submit(auth, answers, email).status_code == 201
    confirmed = _confirm(auth, sent, email)
    ticket = Ticket.get(Ticket.title == answers["title"])
    phrase = f"Please send the receipt number {uuid.uuid4().hex[:6]}"
    response = auth.post(f"/api/tickets/{ticket.id}/public-reply", json={"body": phrase})
    assert response.status_code == 201, response.data
    track = auth.get(confirmed.location)
    assert phrase.encode() in track.data
    reply_mail = [item for item in sent if item["subject"] == "A reply to your report"]
    assert reply_mail[-1]["to"] == email
    assert phrase in reply_mail[-1]["text"]
    page = auth.get(f"/tickets/{ticket.project}/{ticket.id}")
    assert page.status_code == 200
    assert b"Reply to reporter" in page.data
    assert email.encode() in page.data


@test("intake assist fills priority, estimate, and project without showing the reason")
def _(c=client, project=anon_enabled_project, sent=sent_mail):
    answers = problem_answers()
    email = f"ai-{uuid.uuid4().hex[:6]}@example.com"
    reason = f"Because login is blocked for the whole billing team {uuid.uuid4().hex[:6]}."

    def fake_enrich(_ticket, _kind, _answers, _projects):
        return {
            "priority": "high",
            "estimate": "4h",
            "suggested_project": project.id,
            "confidence": 0.91,
            "reason": reason,
        }

    with patch("app.utils.anon_enrich.enrich_anon_ticket", fake_enrich):
        assert _submit(c, answers, email).status_code == 201
        confirmed = _confirm(c, sent, email)
    ticket = Ticket.get(Ticket.id == Ticket.get(Ticket.title == answers["title"]).id)
    assert ticket.priority == "high"
    assert ticket.estimate_minutes == 240
    assert ticket.project == project.id
    assert ticket.status == "intake"
    note = TicketUpdateMessage.get(
        (TicketUpdateMessage.ticket == ticket.id) & (TicketUpdateMessage.title == "Intake assist")
    )
    assert reason in note.message
    assert note.public == 0
    track = c.get(confirmed.location)
    assert reason.encode() not in track.data
    assert b"4h" not in track.data
    assert project.name.encode() not in track.data
    assert project.id.encode() not in track.data


@test("intake assist leaves defaults when AI is disabled")
def _(c=client, project=anon_enabled_project, sent=sent_mail):
    answers = problem_answers()
    email = f"off-{uuid.uuid4().hex[:6]}@example.com"
    assert _submit(c, answers, email).status_code == 201
    _confirm(c, sent, email)
    ticket = Ticket.get(Ticket.title == answers["title"])
    assert ticket.priority == "medium"
    assert ticket.estimate_minutes is None
    assert ticket.project == "TRIAGE"
    note = TicketUpdateMessage.get(
        (TicketUpdateMessage.ticket == ticket.id) & (TicketUpdateMessage.title == "Intake assist")
    )
    assert note.message == "Intake assist could not score this ticket."


@test("intake assist does not overwrite a priority set before it runs")
def _(c=client, project=anon_enabled_project, sent=sent_mail):
    from app.utils.anon_enrich import handle_anon_ticket_enrich

    answers = problem_answers()
    email = f"keep-{uuid.uuid4().hex[:6]}@example.com"
    with patch("app.utils.anon_enrich.handle_anon_ticket_enrich", lambda **_kwargs: None):
        assert _submit(c, answers, email).status_code == 201
        _confirm(c, sent, email)
    ticket = Ticket.get(Ticket.title == answers["title"])
    ticket.priority = "low"
    ticket.save()

    def fake_enrich(*_args, **_kwargs):
        return {
            "priority": "urgent",
            "estimate": "1d",
            "suggested_project": project.id,
            "confidence": 0.95,
            "reason": "Should not replace a staff priority.",
        }

    with patch("app.utils.anon_enrich.enrich_anon_ticket", fake_enrich):
        handle_anon_ticket_enrich(ticket_id=ticket.id)
    ticket = Ticket.get(Ticket.id == ticket.id)
    assert ticket.priority == "low"
    note = TicketUpdateMessage.get(
        (TicketUpdateMessage.ticket == ticket.id) & (TicketUpdateMessage.title == "Intake assist")
    )
    assert "staff priority" in note.message


@test("the staff intake helper is not used")
def _(c=client, project=anon_enabled_project, sent=sent_mail):
    def explode(*_args, **_kwargs):
        raise AssertionError("suggest_intake_from_message was called")

    answers = problem_answers()
    email = f"helper-{uuid.uuid4().hex[:6]}@example.com"
    with patch("app.utils.ai_intake.suggest_intake_from_message", explode):
        assert _review(c, answers)["ready"] is True
        assert _submit(c, answers, email).status_code == 201
        assert _confirm(c, sent, email).status_code == 302


@test("the report check passes a usable answer instead of demanding more")
def _():
    seen = {}

    def complete(_config, system, user, max_tokens):
        seen["system"] = system
        seen["user"] = user
        return json.dumps(
            {
                "headline": "Login fails after a password reset",
                "notes": [
                    {"field": "title", "ok": True, "message": "The name says the login failure."},
                    {"field": "detail", "ok": True, "message": "The reset then wrong password is specific."},
                    {"field": "system", "ok": True, "message": "Chrome on Windows is enough to look."},
                ],
            }
        )

    answers = problem_answers("fair")
    with (
        patch("app.utils.anon_enrich.get_ai_config", return_value={"api_key": "test", "model": "test"}),
        patch("app.utils.anon_enrich._complete", complete),
    ):
        verdict = review_anon_report("problem", answers, checked_fields("problem", answers))
    assert verdict["headline"]
    prompt = seen["user"]
    assert answers["detail"] in prompt
    assert "Set ok to false while any of these are vague" not in prompt
    assert "Do not ask again for something the current text already says." in prompt
    assert "Do not ask for something they cannot know" in prompt
    assert "Enough: what broke, and where it shows up." in prompt
    assert "A missing version is fine" in prompt
    assert "When you are unsure whether one more detail is required, pass." in prompt


@test("a configured review that fails stays closed")
def _(c=client, project=anon_enabled_project, sent=sent_mail):
    answers = problem_answers()
    with (
        patch("app.utils.ai_changelog.get_ai_config", return_value={"api_key": "test"}),
        patch("app.utils.anon_enrich.review_anon_report", return_value=None),
    ):
        payload = _review(c, answers)
    assert payload["ready"] is False
    assert "review_token" not in payload
    assert payload["notes"] == [
        {
            "field": "",
            "ok": False,
            "message": "The check did not finish. Try again in a moment.",
        }
    ]
    before = AnonDraft.select().count()
    response = c.post(
        "/api/anon/submit",
        json={**answers, "primary_email": "closed@example.com"},
    )
    assert response.status_code == 400
    assert AnonDraft.select().count() == before


@test("Anonymous settings disabled by default")
def _(c=client):
    GlobalSetting.delete().where(GlobalSetting.key == "anonymous_settings").execute()
    response = c.get("/anon")
    assert response.status_code == 403
