import json
import sys
import time
from unittest.mock import patch

from ward import test

from app.utils.meeting_notes import (
    MeetingAINotConfigured,
    _fallback_from_parse,
    extract_meeting_work,
    parse_meeting_notes,
)
from app.utils.models import Ticket, UserTicketJoin, create_user
from tests.fixtures import auth_client, client, create_test_project


def _notes():
    return """# billing
webhook died after the deploy
! retry failed invoices from tuesday @valter
they said about 200 rows
= no automatic refunds this quarter
? does stripe retry on 500s
"""


def _fake_openai(reply: str, seen: dict | None = None):
    class _Message:
        def __init__(self, content):
            self.content = content

    class _Choice:
        def __init__(self, content):
            self.message = _Message(content)

    class _Completions:
        def create(self, **kwargs):
            if seen is not None:
                seen.update(kwargs)
            return type("Resp", (), {"choices": [_Choice(reply)]})()

    class _Chat:
        def __init__(self):
            self.completions = _Completions()

    class _Client:
        def __init__(self, **kwargs):
            self.chat = _Chat()

    class _Module:
        def OpenAI(self, **kwargs):
            return _Client(**kwargs)

    return _Module()


@test("meeting notes parser captures marks, owners, and following context")
def _():
    items = parse_meeting_notes(_notes())
    kinds = [item.kind for item in items]
    assert kinds == ["action", "decision", "question"]
    action = items[0]
    assert action.topic == "billing"
    assert "retry failed invoices" in action.text
    assert "valter" in action.assignee_hints
    assert "200 rows" in action.extra
    assert items[1].text.lower().startswith("no automatic refunds")
    assert items[2].kind == "question"


@test("fallback parse still turns ! lines into tickets")
def _():
    items = parse_meeting_notes(_notes())
    result = _fallback_from_parse(
        items,
        [{"id": "billing", "name": "Billing"}, {"id": "web", "name": "Website"}],
        ["valter"],
        "test",
    )
    assert result["source"] == "fallback"
    assert len(result["tickets"]) == 1
    ticket = result["tickets"][0]
    assert ticket["project"] == "billing"
    assert ticket["assignees"] == ["valter"]
    assert "retry" in ticket["title"].lower()
    assert result["decisions"]
    assert result["questions"]
    assert all("refund" not in t["title"].lower() for t in result["tickets"])


@test("extract_meeting_work requires AI")
def _():
    with patch("app.utils.meeting_notes.get_ai_config", return_value=None):
        try:
            extract_meeting_work("talk about invoices", [{"id": "web", "name": "Website"}], [])
        except MeetingAINotConfigured as exc:
            assert "AI is not configured" in str(exc)
        else:
            raise AssertionError("expected MeetingAINotConfigured")


@test("AI extract rewrites messy notes into filled tickets")
def _():
    seen: dict = {}
    reply = json.dumps(
        {
            "tickets": [
                {
                    "title": "Retry failed billing invoices",
                    "description": (
                        "The billing webhook died after the deploy. "
                        "Retry the failed invoices from Tuesday; about 200 rows."
                    ),
                    "project": "billing",
                    "priority": "high",
                    "assignees": ["valter"],
                    "marked": False,
                    "quote": "webhook died, retry invoices tue ~200",
                }
            ],
            "decisions": [{"text": "No automatic refunds this quarter", "topic": "billing"}],
            "questions": [{"text": "Does Stripe retry on HTTP 500?", "topic": "billing"}],
        }
    )
    messy = "webhook died, retry invoices tue ~200. no auto refunds this q. stripe 500?"
    with patch.dict(sys.modules, {"openai": _fake_openai(reply, seen)}), patch(
        "app.utils.meeting_notes.get_ai_config",
        return_value={
            "api_key": "k",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
        },
    ):
        result = extract_meeting_work(
            messy,
            [{"id": "billing", "name": "Billing"}, {"id": "web", "name": "Website"}],
            ["valter"],
            meeting_title="Billing standup",
        )
    assert result["source"] == "ai"
    assert result["tickets"][0]["title"] == "Retry failed billing invoices"
    assert "200 rows" in result["tickets"][0]["description"]
    assert result["tickets"][0]["project"] == "billing"
    assert result["tickets"][0]["assignees"] == ["valter"]
    assert result["decisions"]
    prompt = seen["messages"][1]["content"]
    assert messy in prompt
    assert "Billing standup" in prompt


@test("/meetings requires authentication")
def _(c=client):
    response = c.get("/meetings", follow_redirects=False)
    assert response.status_code in [302, 401]


@test("creating a meeting and finishing it opens tickets in the project")
def _(c=auth_client):
    unique = str(int(time.time() * 1000000))
    project = create_test_project(f"pay{unique}", "Payments")
    listed = c.get("/meetings")
    assert listed.status_code == 200
    assert b"New meeting" in listed.data

    created = c.post("/api/meetings", json={})
    assert created.status_code == 201
    meeting_id = created.get_json()["meeting"]["id"]

    patched = c.patch(
        f"/api/meetings/{meeting_id}",
        json={
            "title": "Billing standup",
            "notes": "retry failed invoices after the webhook died",
        },
    )
    assert patched.status_code == 200

    fake_extract = {
        "tickets": [
            {
                "title": "Retry failed invoices",
                "description": "The webhook died. Retry the failed invoices.",
                "project": project.id,
                "priority": "medium",
                "assignees": [],
                "marked": False,
                "quote": "retry failed invoices after the webhook died",
            }
        ],
        "decisions": [{"text": "No refunds this quarter", "topic": ""}],
        "questions": [],
        "skipped": [],
        "source": "ai",
        "reason": "test",
    }
    with patch("app.views.meetings.extract_meeting_work", return_value=fake_extract):
        done = c.post(f"/api/meetings/{meeting_id}/done", json={})
    assert done.status_code == 200
    body = done.get_json()
    tickets = body["result"]["tickets"]
    assert len(tickets) == 1
    ticket = Ticket.get_by_id(tickets[0]["id"])
    assert ticket.project == project.id
    assert ticket.status == "backlog"
    assert ticket.meeting_id == meeting_id
    assert "Retry failed invoices" == ticket.title

    again = c.post(f"/api/meetings/{meeting_id}/done", json={})
    assert again.status_code == 200
    assert again.get_json().get("already_done") is True
    assert Ticket.select().where(Ticket.meeting_id == meeting_id).count() == 1

    page = c.get(f"/meetings/{meeting_id}")
    assert page.status_code == 200
    assert b"What came out" in page.data
    assert ticket.id.encode() in page.data


@test("done with empty notes is rejected")
def _(c=auth_client):
    created = c.post("/api/meetings", json={"title": "Empty"})
    meeting_id = created.get_json()["meeting"]["id"]
    done = c.post(f"/api/meetings/{meeting_id}/done", json={"notes": "  "})
    assert done.status_code == 400


@test("done without AI configured is rejected")
def _(c=auth_client):
    unique = str(int(time.time() * 1000000))
    create_test_project(f"web{unique}", "Website")
    created = c.post("/api/meetings", json={})
    meeting_id = created.get_json()["meeting"]["id"]
    with patch(
        "app.views.meetings.extract_meeting_work",
        side_effect=MeetingAINotConfigured("AI is not configured"),
    ):
        done = c.post(
            f"/api/meetings/{meeting_id}/done",
            json={"notes": "talk about the pricing page"},
        )
    assert done.status_code == 400
    assert "AI is not configured" in done.get_json()["error"]


@test("done uses AI extract when configured")
def _(c=auth_client):
    unique = str(int(time.time() * 1000000))
    project = create_test_project(f"web{unique}", "Website")
    created = c.post("/api/meetings", json={})
    meeting_id = created.get_json()["meeting"]["id"]
    c.patch(
        f"/api/meetings/{meeting_id}",
        json={"notes": "Alice will rewrite the pricing CTA this week."},
    )
    fake_extract = {
        "tickets": [
            {
                "title": "Rewrite pricing CTA",
                "description": "Alice will rewrite the pricing CTA this week.",
                "project": project.id,
                "priority": "medium",
                "assignees": [],
                "marked": False,
                "quote": "Alice will rewrite the pricing CTA this week.",
            }
        ],
        "decisions": [],
        "questions": [],
        "skipped": [],
        "source": "ai",
        "reason": "test",
    }
    with patch("app.views.meetings.extract_meeting_work", return_value=fake_extract):
        done = c.post(f"/api/meetings/{meeting_id}/done", json={})
    assert done.status_code == 200
    tickets = done.get_json()["result"]["tickets"]
    assert len(tickets) == 1
    assert tickets[0]["project"] == project.id
    assert tickets[0]["title"] == "Rewrite pricing CTA"


@test("meeting done assigns mentioned users")
def _(c=auth_client):
    unique = str(int(time.time() * 1000000))
    project = create_test_project(f"ops{unique}", "Ops")
    uname = f"jordan_{unique}"
    other = create_user(uname, "password123", f"{uname}@example.com")
    created = c.post("/api/meetings", json={})
    meeting_id = created.get_json()["meeting"]["id"]
    fake_extract = {
        "tickets": [
            {
                "title": "Rotate staging keys",
                "description": "Rotate the staging keys.",
                "project": project.id,
                "priority": "medium",
                "assignees": [uname],
                "marked": True,
                "quote": f"rotate the staging keys @{uname}",
            }
        ],
        "decisions": [],
        "questions": [],
        "skipped": [],
        "source": "ai",
        "reason": "test",
    }
    with patch("app.views.meetings.extract_meeting_work", return_value=fake_extract):
        done = c.post(
            f"/api/meetings/{meeting_id}/done",
            json={"notes": f"rotate the staging keys @{uname}"},
        )
    assert done.status_code == 200
    ticket_id = done.get_json()["result"]["tickets"][0]["id"]
    joined = [row.user for row in UserTicketJoin.select().where(UserTicketJoin.ticket == ticket_id)]
    assert other.username in joined
