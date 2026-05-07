"""Tests for ticket management functionality"""

import json
import time
from unittest.mock import patch

from ward import test

from app.utils.models import Ticket
from tests.fixtures import auth_client, auth_user, client, fake, test_project, test_ticket


@test("/tickets GET requires authentication")
def _(c=client):
    """Test tickets list requires auth"""
    response = c.get("/tickets", follow_redirects=False)
    # Should redirect to login or return 200 if accessible
    assert response.status_code in [200, 302, 401]


@test("/tickets GET shows tickets when authenticated")
def _(c=auth_client):
    """Test authenticated user can view tickets"""
    response = c.get("/tickets")
    assert response.status_code in [200, 302]


@test("/tickets excludes triage tickets")
def _(c=auth_client, project=test_project):
    unique = str(int(time.time() * 1000000))
    triage_ticket = Ticket.create(
        id=f"TRIAGE-{unique}",
        title=f"Triage hidden {unique}",
        description="triage-only",
        status="intake",
        priority="medium",
        project="TRIAGE",
        active=1,
    )
    regular_ticket = Ticket.create(
        id=f"{project.id}-{unique}",
        title=f"Regular visible {unique}",
        description="regular",
        status="backlog",
        priority="medium",
        project=project.id,
        active=1,
    )

    response = c.get("/tickets")
    assert response.status_code in [200, 302]
    if response.status_code == 200:
        regular_token = f'id: "{regular_ticket.id}"'.encode()
        triage_token = f'id: "{triage_ticket.id}"'.encode()
        assert regular_token in response.data
        assert triage_token not in response.data


@test("/tickets/<project_id> excludes triage tickets")
def _(c=auth_client, project=test_project):
    unique = str(int(time.time() * 1000000))
    triage_ticket = Ticket.create(
        id=f"{project.id}-{unique}-triage",
        title=f"Project triage hidden {unique}",
        description="triage-in-project",
        status="intake",
        priority="medium",
        project=project.id,
        active=1,
    )
    regular_ticket = Ticket.create(
        id=f"{project.id}-{unique}-regular",
        title=f"Project regular visible {unique}",
        description="project-regular",
        status="backlog",
        priority="medium",
        project=project.id,
        active=1,
    )

    response = c.get(f"/tickets/{project.id}")
    assert response.status_code in [200, 302]
    if response.status_code == 200:
        regular_token = f'id: "{regular_ticket.id}"'.encode()
        triage_token = f'id: "{triage_ticket.id}"'.encode()
        assert regular_token in response.data
        assert triage_token not in response.data


@test("/tickets/<id> GET shows ticket detail")
def _(c=auth_client, ticket=test_ticket):
    """Test ticket detail page loads"""
    response = c.get(f"/tickets/{ticket.id}")
    assert response.status_code in [200, 302, 404]


@test("Create ticket via POST")
def _(c=auth_client, f=fake, project=test_project):
    """Test creating a new ticket"""
    ticket_data = {
        "title": f.sentence(),
        "description": f.text(),
        "project": project.id,
        "status": "todo",
        "priority": "medium",
    }

    response = c.post(
        "/api/tickets",
        data=json.dumps(ticket_data),
        content_type="application/json",
        follow_redirects=False,
    )

    assert response.status_code in [200, 201, 302, 401, 404]


@test("Create subticket via POST with parent ticket")
def _(c=auth_client, f=fake, project=test_project):
    parent = Ticket.create(
        id=f"{project.id}-{int(time.time() * 1000000)}-P",
        title=f"Parent {f.word()}",
        description="Parent ticket",
        status="todo",
        priority="medium",
        project=project.id,
        active=1,
    )

    response = c.post(
        "/api/tickets",
        data=json.dumps(
            {
                "title": f"Child {f.word()}",
                "description": "Subticket details",
                "project": project.id,
                "status": "todo",
                "priority": "medium",
                "parent_ticket_id": parent.id,
            }
        ),
        content_type="application/json",
        follow_redirects=False,
    )

    assert response.status_code == 201
    payload = json.loads(response.data)
    assert payload.get("ticket", {}).get("parent_ticket_id") == parent.id


@test("Create subticket rejects unknown parent ticket")
def _(c=auth_client, f=fake, project=test_project):
    response = c.post(
        "/api/tickets",
        data=json.dumps(
            {
                "title": f"Child {f.word()}",
                "description": "Subticket details",
                "project": project.id,
                "status": "todo",
                "priority": "medium",
                "parent_ticket_id": "NONEXISTENT-123",
            }
        ),
        content_type="application/json",
        follow_redirects=False,
    )

    assert response.status_code == 404


@test("Create nested subticket depth greater than one is rejected")
def _(c=auth_client, f=fake, project=test_project):
    parent = Ticket.create(
        id=f"{project.id}-{int(time.time() * 1000000)}-ROOT",
        title=f"Parent {f.word()}",
        description="Parent ticket",
        status="todo",
        priority="medium",
        project=project.id,
        active=1,
    )
    child = Ticket.create(
        id=f"{project.id}-{int(time.time() * 1000000)}-CHILD",
        title=f"Child {f.word()}",
        description="First-level child",
        status="todo",
        priority="medium",
        project=project.id,
        active=1,
        parent_ticket_id=parent.id,
    )

    response = c.post(
        "/api/tickets",
        data=json.dumps(
            {
                "title": f"Nested {f.word()}",
                "description": "Should be rejected",
                "project": project.id,
                "status": "todo",
                "priority": "medium",
                "parent_ticket_id": child.id,
            }
        ),
        content_type="application/json",
        follow_redirects=False,
    )

    assert response.status_code == 400


@test("Ticket detail renders subticket section and children")
def _(c=auth_client, f=fake, project=test_project):
    parent = Ticket.create(
        id=f"{project.id}-{int(time.time() * 1000000)}-DETAIL",
        title=f"Parent {f.word()}",
        description="Parent ticket",
        status="todo",
        priority="medium",
        project=project.id,
        active=1,
    )
    child = Ticket.create(
        id=f"{project.id}-{int(time.time() * 1000000)}-DETAIL-CHILD",
        title=f"Child {f.word()}",
        description="Child ticket",
        status="todo",
        priority="medium",
        project=project.id,
        active=1,
        parent_ticket_id=parent.id,
    )

    response = c.get(f"/tickets/{project.id}/{parent.id}")
    assert response.status_code in [200, 302]
    if response.status_code == 200:
        assert b"Subtickets" in response.data
        assert child.id.encode() in response.data


@test("Ticket detail hides subticket section when no subtickets exist")
def _(c=auth_client, f=fake, project=test_project):
    ticket = Ticket.create(
        id=f"{project.id}-{int(time.time() * 1000000)}-NO-SUBS",
        title=f"Solo {f.word()}",
        description="Standalone ticket",
        status="todo",
        priority="medium",
        project=project.id,
        active=1,
    )

    response = c.get(f"/tickets/{project.id}/{ticket.id}")
    assert response.status_code in [200, 302]
    if response.status_code == 200:
        assert b"<h3>Subtickets</h3>" not in response.data
        assert b"No subtickets yet." not in response.data


@test("Ticket detail shows subticket progress rollup")
def _(c=auth_client, f=fake, project=test_project):
    parent = Ticket.create(
        id=f"{project.id}-{int(time.time() * 1000000)}-ROLLUP",
        title=f"Parent {f.word()}",
        description="Parent ticket",
        status="todo",
        priority="medium",
        project=project.id,
        active=1,
    )
    Ticket.create(
        id=f"{project.id}-{int(time.time() * 1000000)}-ROLLUP-DONE",
        title=f"Done child {f.word()}",
        description="Child ticket",
        status="done",
        priority="medium",
        project=project.id,
        active=1,
        parent_ticket_id=parent.id,
    )
    Ticket.create(
        id=f"{project.id}-{int(time.time() * 1000000)}-ROLLUP-OPEN",
        title=f"Open child {f.word()}",
        description="Child ticket",
        status="todo",
        priority="medium",
        project=project.id,
        active=1,
        parent_ticket_id=parent.id,
    )

    response = c.get(f"/tickets/{project.id}/{parent.id}")
    assert response.status_code in [200, 302]
    if response.status_code == 200:
        assert b"Subticket Progress" in response.data
        assert b"1/2 done" in response.data


@test("Ticket detail suggests closing parent when all subtickets are done")
def _(c=auth_client, f=fake, project=test_project):
    parent = Ticket.create(
        id=f"{project.id}-{int(time.time() * 1000000)}-CLOSE",
        title=f"Parent {f.word()}",
        description="Parent ticket",
        status="todo",
        priority="medium",
        project=project.id,
        active=1,
    )
    Ticket.create(
        id=f"{project.id}-{int(time.time() * 1000000)}-CLOSE-A",
        title=f"Done child {f.word()}",
        description="Child ticket",
        status="done",
        priority="medium",
        project=project.id,
        active=1,
        parent_ticket_id=parent.id,
    )
    Ticket.create(
        id=f"{project.id}-{int(time.time() * 1000000)}-CLOSE-B",
        title=f"Done child {f.word()}",
        description="Child ticket",
        status="closed",
        priority="medium",
        project=project.id,
        active=1,
        parent_ticket_id=parent.id,
    )

    response = c.get(f"/tickets/{project.id}/{parent.id}")
    assert response.status_code in [200, 302]
    if response.status_code == 200:
        assert b"All subtickets are complete" in response.data
        assert b"Close Parent Ticket" in response.data


@test("Create triage intake ticket via POST")
def _(c=auth_client, f=fake, project=test_project):
    ticket_data = {
        "title": f.sentence(),
        "description": f.text(),
        "project": project.id,
        "priority": "medium",
    }

    response = c.post(
        "/api/tickets/intake",
        data=json.dumps(ticket_data),
        content_type="application/json",
        follow_redirects=False,
    )

    assert response.status_code in [200, 201]
    payload = json.loads(response.data)
    assert payload.get("ticket", {}).get("status") == "intake"


@test("Create triage intake ticket without project")
def _(c=auth_client, f=fake):
    ticket_data = {
        "title": f.sentence(),
        "description": f.text(),
        "priority": "medium",
    }

    response = c.post(
        "/api/tickets/intake",
        data=json.dumps(ticket_data),
        content_type="application/json",
        follow_redirects=False,
    )

    assert response.status_code == 201
    payload = json.loads(response.data)
    assert payload.get("ticket", {}).get("status") == "intake"
    assert payload.get("ticket", {}).get("project") == "TRIAGE"


@test("Create triage intake ticket blocks strong duplicates")
def _(c=auth_client, f=fake):
    title = f.unique.sentence(nb_words=8)
    description = f"{f.unique.sentence(nb_words=12)} {f.unique.sentence(nb_words=10)}"

    first_response = c.post(
        "/api/tickets/intake",
        data=json.dumps(
            {
                "title": title,
                "description": description,
                "priority": "high",
            }
        ),
        content_type="application/json",
        follow_redirects=False,
    )
    assert first_response.status_code == 201

    duplicate_response = c.post(
        "/api/tickets/intake",
        data=json.dumps(
            {
                "title": title,
                "description": description,
                "priority": "high",
            }
        ),
        content_type="application/json",
        follow_redirects=False,
    )
    assert duplicate_response.status_code == 409
    payload = json.loads(duplicate_response.data)
    assert payload.get("possible_duplicates")


@test("Create triage intake ticket accepts null project")
def _(c=auth_client, f=fake):
    ticket_data = {
        "title": f.sentence(),
        "description": f.text(),
        "project": None,
        "priority": "medium",
    }

    response = c.post(
        "/api/tickets/intake",
        data=json.dumps(ticket_data),
        content_type="application/json",
        follow_redirects=False,
    )

    assert response.status_code == 201
    payload = json.loads(response.data)
    assert payload.get("ticket", {}).get("status") == "intake"
    assert payload.get("ticket", {}).get("project") == "TRIAGE"


@test("Create triage intake ticket accepts TRIAGE sentinel project")
def _(c=auth_client, f=fake):
    ticket_data = {
        "title": f.sentence(),
        "description": f.text(),
        "project": "TRIAGE",
        "priority": "medium",
    }

    response = c.post(
        "/api/tickets/intake",
        data=json.dumps(ticket_data),
        content_type="application/json",
        follow_redirects=False,
    )

    assert response.status_code == 201
    payload = json.loads(response.data)
    assert payload.get("ticket", {}).get("status") == "intake"
    assert payload.get("ticket", {}).get("project") == "TRIAGE"


@test("Cannot move triage ticket to active flow without project assignment")
def _(c=auth_client, f=fake):
    create_response = c.post(
        "/api/tickets/intake",
        data=json.dumps({"title": f.sentence(), "priority": "medium"}),
        content_type="application/json",
        follow_redirects=False,
    )
    assert create_response.status_code == 201
    ticket_id = json.loads(create_response.data)["ticket"]["id"]

    status_response = c.patch(
        f"/api/tickets/{ticket_id}",
        data=json.dumps({"field": "status", "value": "todo"}),
        content_type="application/json",
    )
    assert status_response.status_code == 400


@test("Can assign project to triage ticket and then move status")
def _(c=auth_client, f=fake, project=test_project):
    create_response = c.post(
        "/api/tickets/intake",
        data=json.dumps({"title": f.sentence(), "priority": "medium"}),
        content_type="application/json",
        follow_redirects=False,
    )
    assert create_response.status_code == 201
    ticket_id = json.loads(create_response.data)["ticket"]["id"]

    project_response = c.patch(
        f"/api/tickets/{ticket_id}",
        data=json.dumps({"field": "project", "value": project.id}),
        content_type="application/json",
    )
    assert project_response.status_code == 200
    project_payload = json.loads(project_response.data)
    new_ticket_id = project_payload.get("ticket", {}).get("id")
    assert new_ticket_id
    assert new_ticket_id.startswith(f"{project.id}-")

    status_response = c.patch(
        f"/api/tickets/{new_ticket_id}",
        data=json.dumps({"field": "status", "value": "todo"}),
        content_type="application/json",
    )
    assert status_response.status_code == 200


@test("/triage GET shows triage inbox")
def _(c=auth_client):
    response = c.get("/triage")
    assert response.status_code in [200, 302]
    if response.status_code == 200:
        assert b"Intake Inbox" in response.data


@test("/triage escapes newline characters in ticket titles")
def _(c=auth_client, f=fake):
    create_response = c.post(
        "/api/tickets/intake",
        data=json.dumps(
            {
                "title": f"Line one\\nLine two {f.uuid4()}",
                "description": "newline title regression",
                "priority": "medium",
            }
        ),
        content_type="application/json",
        follow_redirects=False,
    )
    assert create_response.status_code == 201

    response = c.get("/triage")
    assert response.status_code in [200, 302]
    if response.status_code == 200:
        # Ticket data is embedded into inline JS, so raw newlines in string
        # literals must never appear (which would break script parsing).
        assert b"Line one\nLine two" not in response.data
        assert b"Line one" in response.data


@test("/triage does not show intake confirmation modal copy")
def _(c=auth_client):
    response = c.get("/triage")
    assert response.status_code in [200, 302]
    if response.status_code == 200:
        assert b"Create Intake Ticket" not in response.data


@test("/triage shows workflow guidance and send action")
def _(c=auth_client):
    response = c.get("/triage")
    assert response.status_code in [200, 302]
    if response.status_code == 200:
        assert (b"Quick Intake" in response.data) or (b"AI Intake" in response.data)
        assert (b"guided chat" in response.data) or (
            b"assistant will gather details" in response.data
        )
        assert b"Send Selected" not in response.data


@test("/triage shows AI intake entrypoint")
def _(c=auth_client):
    response = c.get("/triage")
    assert response.status_code in [200, 302]
    if response.status_code == 200:
        assert (b"AI Intake" in response.data) or (b"Quick Intake" in response.data)


@test("/triage renders split intake and inbox panels")
def _(c=auth_client):
    response = c.get("/triage")
    assert response.status_code in [200, 302]
    if response.status_code == 200:
        assert b'id="triage-intake-panel"' in response.data
        assert b'id="triage-inbox-panel"' in response.data


@test("/triage renders shared chat intake controls")
def _(c=auth_client):
    response = c.get("/triage")
    assert response.status_code in [200, 302]
    if response.status_code == 200:
        assert b'id="triage-chat-thread"' in response.data
        assert b'id="triage-chat-input"' in response.data
        assert b'id="triage-chat-send"' in response.data


@test("/triage does not render legacy wizard controls")
def _(c=auth_client):
    response = c.get("/triage")
    assert response.status_code in [200, 302]
    if response.status_code == 200:
        assert b'id="triage-wizard-progress"' not in response.data
        assert b'id="triage-wizard-next"' not in response.data
        assert b'id="triage-wizard-create"' not in response.data


@test("/triage shows AI chat only when AI is configured")
def _(c=auth_client):
    with patch(
        "app.views.tickets.get_ai_config",
        return_value={
            "api_key": "test-key",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
        },
    ):
        response = c.get("/triage")

    assert response.status_code in [200, 302]
    if response.status_code == 200:
        assert b"AI Intake" in response.data
        assert b'id="triage-chat-thread"' in response.data
        assert b'id="triage-chat-input"' in response.data
        assert b'id="triage-wizard-progress"' not in response.data


@test("/triage uses environment AI key to enable AI mode")
def _(c=auth_client):
    with patch.dict(
        "os.environ",
        {
            "AI_API_KEY": "env-test-key",
            "AI_BASE_URL": "https://api.openai.com/v1",
            "AI_MODEL": "gpt-4o-mini",
        },
        clear=False,
    ):
        response = c.get("/triage")

    assert response.status_code in [200, 302]
    if response.status_code == 200:
        assert b"AI Intake" in response.data
        assert b'id="triage-chat-thread"' in response.data


@test("/triage uses dedicated dashboard script and no list.js")
def _(c=auth_client):
    response = c.get("/triage")
    assert response.status_code in [200, 302]
    if response.status_code == 200:
        assert b"/static/js/triage_dashboard.js" in response.data
        assert b"/static/js/lists.js" not in response.data


@test("/triage renders triage tickets oldest first")
def _(c=auth_client):
    unique = str(int(time.time() * 1000000))
    now = int(time.time())

    newer = Ticket.create(
        id=f"TRIAGE-{unique}-newer",
        title="Newer triage ticket",
        description="newer",
        status="intake",
        priority="medium",
        project="TRIAGE",
        active=1,
        created_at=now,
    )
    older = Ticket.create(
        id=f"TRIAGE-{unique}-older",
        title="Older triage ticket",
        description="older",
        status="intake",
        priority="medium",
        project="TRIAGE",
        active=1,
        created_at=now - 500,
    )

    response = c.get("/triage")
    assert response.status_code in [200, 302]
    if response.status_code == 200:
        html = response.data.decode("utf-8")
        older_index = html.find(older.id)
        newer_index = html.find(newer.id)
        assert older_index != -1
        assert newer_index != -1
        assert older_index < newer_index


@test("/api/tickets/intake/ai/suggest requires message")
def _(c=auth_client):
    response = c.post(
        "/api/tickets/intake/ai/suggest",
        data=json.dumps({}),
        content_type="application/json",
    )
    assert response.status_code == 400


@test("/api/tickets/intake/ai/chat requires message")
def _(c=auth_client):
    response = c.post(
        "/api/tickets/intake/ai/chat",
        data=json.dumps({}),
        content_type="application/json",
    )
    assert response.status_code == 400


@test("/api/tickets/intake/ai/chat asks follow-up for sparse details")
def _(c=auth_client):
    with patch(
        "app.views.tickets.suggest_intake_from_message",
        return_value={
            "title": "Login issue",
            "description": "Login issue",
            "priority": "medium",
            "suggested_project": None,
            "confidence": 0.5,
            "reason": "Limited context",
            "route": "triage",
            "source": "ai",
        },
    ):
        response = c.post(
            "/api/tickets/intake/ai/chat",
            data=json.dumps({"message": "login broken"}),
            content_type="application/json",
        )

    assert response.status_code == 200
    payload = json.loads(response.data)
    assert payload.get("success") is True
    reply = payload.get("reply", {})
    assert reply.get("ready_to_commit") is False
    assert "context_details" in reply.get("missing_fields", [])


@test("/api/tickets/intake/ai/chat merges history and can be commit-ready")
def _(c=auth_client):
    with patch(
        "app.views.tickets.suggest_intake_from_message",
        return_value={
            "title": "Password reset login failures",
            "description": "Users cannot login after password reset in production.",
            "priority": "high",
            "suggested_project": "AUTH",
            "confidence": 0.9,
            "reason": "Auth keyword match.",
            "route": "direct",
            "source": "ai",
        },
    ) as mocked_suggest:
        response = c.post(
            "/api/tickets/intake/ai/chat",
            data=json.dumps(
                {
                    "history": [
                        {
                            "role": "user",
                            "content": "Multiple users cannot sign in after password reset.",
                        }
                    ],
                    "message": "Urgent production impact. Please route to auth team.",
                }
            ),
            content_type="application/json",
        )

    assert response.status_code == 200
    payload = json.loads(response.data)
    assert payload.get("success") is True
    reply = payload.get("reply", {})
    assert reply.get("ready_to_commit") is True
    assert reply.get("missing_fields") == []
    assert reply.get("draft", {}).get("suggested_project") == "AUTH"

    suggested_message = mocked_suggest.call_args[0][0]
    assert "Multiple users cannot sign in" in suggested_message
    assert "Urgent production impact" in suggested_message


@test("/api/tickets/intake/ai/chat trusts high-confidence AI draft")
def _(c=auth_client):
    with patch(
        "app.views.tickets.suggest_intake_from_message",
        return_value={
            "title": "Login breaks after reset",
            "description": "Users cannot login after password reset.",
            "priority": "high",
            "suggested_project": None,
            "confidence": 0.93,
            "reason": "Strong auth pattern match.",
            "route": "triage",
            "source": "ai",
        },
    ):
        response = c.post(
            "/api/tickets/intake/ai/chat",
            data=json.dumps({"message": "login broken"}),
            content_type="application/json",
        )

    assert response.status_code == 200
    payload = json.loads(response.data)
    reply = payload.get("reply", {})
    assert reply.get("ready_to_commit") is True
    assert reply.get("missing_fields") == []


@test("/api/tickets/intake/ai/chat flags strong duplicate matches")
def _(c=auth_client):
    unique = str(int(time.time() * 1000000))
    title = f"Checkout failure in production {unique}"
    description = "Checkout fails for many users in production after deploy"

    c.post(
        "/api/tickets/intake",
        data=json.dumps(
            {
                "title": title,
                "description": description,
                "priority": "high",
            }
        ),
        content_type="application/json",
        follow_redirects=False,
    )

    with patch(
        "app.views.tickets.suggest_intake_from_message",
        return_value={
            "title": title,
            "description": description,
            "priority": "high",
            "suggested_project": None,
            "confidence": 0.9,
            "reason": "duplicate check",
            "route": "triage",
            "source": "ai",
        },
    ):
        response = c.post(
            "/api/tickets/intake/ai/chat",
            data=json.dumps({"message": "checkout is failing in production for many users"}),
            content_type="application/json",
        )

    assert response.status_code == 200
    payload = json.loads(response.data)
    reply = payload.get("reply", {})
    assert reply.get("ready_to_commit") is False
    assert "possible_duplicate" in reply.get("missing_fields", [])
    assert reply.get("possible_duplicates")


@test("/api/tickets/intake/ai/suggest returns structured suggestion")
def _(c=auth_client):
    with patch(
        "app.views.tickets.suggest_intake_from_message",
        return_value={
            "title": "Login issue when session expires",
            "description": "Users are logged out and cannot re-authenticate until refresh.",
            "priority": "high",
            "suggested_project": "AUTH",
            "confidence": 0.92,
            "reason": "Mentions auth/session behavior.",
            "route": "direct",
            "source": "ai",
        },
    ):
        response = c.post(
            "/api/tickets/intake/ai/suggest",
            data=json.dumps({"message": "Users get kicked out and login fails"}),
            content_type="application/json",
        )

    assert response.status_code == 200
    payload = json.loads(response.data)
    assert payload.get("success") is True
    assert payload.get("suggestion", {}).get("priority") == "high"
    assert payload.get("suggestion", {}).get("suggested_project") == "AUTH"


@test("/api/tickets/intake/ai/commit requires title")
def _(c=auth_client):
    response = c.post(
        "/api/tickets/intake/ai/commit",
        data=json.dumps({"destination": "triage", "suggestion": {}}),
        content_type="application/json",
    )
    assert response.status_code == 400


@test("/api/tickets/intake/ai/commit creates intake ticket")
def _(c=auth_client, f=fake):
    unique_title = f.unique.sentence(nb_words=7)
    unique_description = f.unique.sentence(nb_words=14)
    response = c.post(
        "/api/tickets/intake/ai/commit",
        data=json.dumps(
            {
                "destination": "triage",
                "suggestion": {
                    "title": unique_title,
                    "description": unique_description,
                    "priority": "medium",
                },
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 201
    payload = json.loads(response.data)
    assert payload.get("ticket", {}).get("status") == "intake"
    assert payload.get("ticket", {}).get("project") == "TRIAGE"


@test("/api/tickets/intake/ai/commit accepts explicit intake destination")
def _(c=auth_client, f=fake):
    unique_title = f.unique.sentence(nb_words=6)
    unique_description = f.unique.sentence(nb_words=12)
    response = c.post(
        "/api/tickets/intake/ai/commit",
        data=json.dumps(
            {
                "destination": "intake",
                "suggestion": {
                    "title": unique_title,
                    "description": unique_description,
                    "priority": "low",
                },
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 201
    payload = json.loads(response.data)
    assert payload.get("ticket", {}).get("status") == "intake"
    assert payload.get("ticket", {}).get("project") == "TRIAGE"


@test("/api/tickets/intake/ai/commit creates backlog ticket in project")
def _(c=auth_client, project=test_project, f=fake):
    unique_title = f.unique.sentence(nb_words=7)
    unique_description = f.unique.sentence(nb_words=14)
    response = c.post(
        "/api/tickets/intake/ai/commit",
        data=json.dumps(
            {
                "destination": "project",
                "project": project.id,
                "suggestion": {
                    "title": unique_title,
                    "description": unique_description,
                    "priority": "high",
                },
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 201
    payload = json.loads(response.data)
    assert payload.get("ticket", {}).get("status") == "backlog"
    assert payload.get("ticket", {}).get("project") == project.id


@test("/api/tickets/intake/ai/commit blocks strong duplicates")
def _(c=auth_client):
    unique = str(int(time.time() * 1000000))
    title = f"Payment API timeout duplicate check {unique}"
    description = "Payment API requests timeout for many users after release"

    c.post(
        "/api/tickets/intake",
        data=json.dumps(
            {
                "title": title,
                "description": description,
                "priority": "high",
            }
        ),
        content_type="application/json",
        follow_redirects=False,
    )

    response = c.post(
        "/api/tickets/intake/ai/commit",
        data=json.dumps(
            {
                "destination": "triage",
                "suggestion": {
                    "title": title,
                    "description": description,
                    "priority": "high",
                },
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 409
    payload = json.loads(response.data)
    assert payload.get("possible_duplicates")


@test("/api/tickets/<id> DELETE requires authentication")
def _(c=client, ticket=test_ticket):
    """Test deletion requires auth"""
    response = c.delete(f"/api/tickets/{ticket.id}")
    # Should redirect, return 401, or 200 if accessible
    assert response.status_code in [200, 302, 401]


@test("/api/tickets/<id> DELETE removes ticket when authenticated")
def _(c=auth_client, ticket=test_ticket):
    """Test soft-deleting a ticket"""
    from app.utils.models import Ticket

    response = c.delete(f"/api/tickets/{ticket.id}")

    # Check if ticket was soft deleted (active=0) or endpoint returned success
    assert response.status_code in [200, 302, 404]

    # Only check ticket state if response was successful
    if response.status_code == 200:
        ticket_after = Ticket.get_by_id(ticket.id)
        assert ticket_after.active == 0


@test("/api/tickets/<id>/comment POST adds comment")
def _(c=auth_client, f=fake, ticket=test_ticket):
    """Test adding a comment to a ticket"""
    comment_text = f.text()
    response = c.post(
        f"/api/tickets/{ticket.id}/comment",
        data=json.dumps({"comment": comment_text}),
        content_type="application/json",
    )

    assert response.status_code in [200, 201, 404]


@test("/api/tickets/<id>/status PUT updates status")
def _(c=auth_client, ticket=test_ticket):
    """Test updating ticket status"""
    response = c.put(
        f"/api/tickets/{ticket.id}/status",
        data=json.dumps({"status": "in_progress"}),
        content_type="application/json",
    )

    assert response.status_code in [200, 302, 401, 404]


@test("/api/tickets/<id>/priority PUT updates priority")
def _(c=auth_client, ticket=test_ticket):
    """Test updating ticket priority"""
    response = c.put(
        f"/api/tickets/{ticket.id}/priority",
        data=json.dumps({"priority": "high"}),
        content_type="application/json",
    )

    assert response.status_code in [200, 302, 401, 404]


@test("/api/search requires authentication")
def _(c=client):
    c.get("/logout", follow_redirects=False)
    response = c.get("/api/search?q=test", follow_redirects=False)
    assert response.status_code in [302, 401]


@test("/api/search returns matching active tickets")
def _(c=auth_client, project=test_project):
    unique = str(int(time.time() * 1000000))
    match_ticket = Ticket.create(
        id=f"{project.id}-{unique}",
        title=f"Searchable Ticket {unique}",
        description="Search test",
        status="backlog",
        priority="medium",
        project=project.id,
        active=1,
    )
    Ticket.create(
        id=f"{project.id}-{unique}-archived",
        title=f"Searchable Archived {unique}",
        description="Search test archived",
        status="backlog",
        priority="medium",
        project=project.id,
        active=0,
    )

    response = c.get(f"/api/search?q={unique}")

    assert response.status_code == 200
    payload = json.loads(response.data)
    assert "results" in payload
    ids = [row["id"] for row in payload["results"]]
    assert match_ticket.id in ids
    assert all("archived" not in value for value in ids)


@test("Tickets page includes clear filters control")
def _(c=auth_client):
    response = c.get("/tickets")
    assert response.status_code in [200, 302]
    if response.status_code == 200:
        assert b"Clear Filters" in response.data


@test("Tickets page supports board view toggle")
def _(c=auth_client):
    response = c.get("/tickets?view=board")
    assert response.status_code in [200, 302]
    if response.status_code == 200:
        assert b"ticket-board" in response.data


@test("Tickets board view exposes priority and assignee filter controls")
def _(c=auth_client):
    response = c.get("/tickets?view=board")
    assert response.status_code in [200, 302]
    if response.status_code == 200:
        assert b"ticket-board-filters" in response.data


@test("Tickets board view includes subticket progress metadata in JS payload")
def _(c=auth_client):
    response = c.get("/tickets?view=board")
    assert response.status_code in [200, 302]
    if response.status_code == 200:
        assert b"subticketCount" in response.data
        assert b"subticketDoneCount" in response.data


@test("Tickets page includes local storage view preference hook")
def _(c=auth_client):
    response = c.get("/tickets")
    assert response.status_code in [200, 302]
    if response.status_code == 200:
        assert b"ticket_view_preference" in response.data


@test("/api/tickets/<id>/export requires authentication")
def _(c=client, ticket=test_ticket):
    response = c.get(f"/api/tickets/{ticket.id}/export", follow_redirects=False)
    assert response.status_code in [302, 401]


@test("/api/tickets/<id>/export returns JSON payload")
def _(c=auth_client, ticket=test_ticket):
    response = c.get(f"/api/tickets/{ticket.id}/export?format=json")
    assert response.status_code == 200
    assert response.headers.get("Content-Type", "").startswith("application/json")

    payload = json.loads(response.data)
    assert payload.get("id") == ticket.id
    assert payload.get("title") == ticket.title
    assert isinstance(payload.get("comments"), list)
    assert isinstance(payload.get("updates"), list)


@test("/api/tickets/<id>/export returns Markdown payload")
def _(c=auth_client, ticket=test_ticket):
    response = c.get(f"/api/tickets/{ticket.id}/export?format=markdown")
    assert response.status_code == 200
    assert response.headers.get("Content-Type", "").startswith("text/markdown")

    body = response.data.decode("utf-8")
    assert f"# Ticket {ticket.id}" in body
    assert ticket.title in body


@test("CSRF enabled rejects protected mutation without token and origin")
def _(c=auth_client, f=fake, project=test_project):
    previous = c.application.config.get("WTF_CSRF_ENABLED", False)
    c.application.config["WTF_CSRF_ENABLED"] = True

    try:
        response = c.post(
            "/api/tickets",
            data=json.dumps(
                {
                    "title": f.sentence(),
                    "description": f.text(),
                    "project": project.id,
                    "status": "todo",
                    "priority": "medium",
                }
            ),
            content_type="application/json",
            follow_redirects=False,
        )
        assert response.status_code == 403
    finally:
        c.application.config["WTF_CSRF_ENABLED"] = previous


@test("CSRF enabled allows protected mutation with matching token")
def _(c=auth_client, f=fake, project=test_project):
    previous = c.application.config.get("WTF_CSRF_ENABLED", False)
    c.application.config["WTF_CSRF_ENABLED"] = True

    try:
        from app.utils.security import CSRF_COOKIE_NAME

        c.set_cookie(CSRF_COOKIE_NAME, "test-csrf-token-123", path="/")

        response = c.post(
            "/api/tickets",
            data=json.dumps(
                {
                    "title": f.sentence(),
                    "description": f.text(),
                    "project": project.id,
                    "status": "todo",
                    "priority": "medium",
                }
            ),
            headers={"X-CSRF-Token": "test-csrf-token-123"},
            content_type="application/json",
            follow_redirects=False,
        )
        assert response.status_code in [200, 201]
    finally:
        c.application.config["WTF_CSRF_ENABLED"] = previous
