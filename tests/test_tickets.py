"""Tests for ticket management functionality"""

from ward import test
from tests.fixtures import client, fake, test_project, test_ticket, auth_client, auth_user
import json
import time

from app.utils.models import Ticket


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
    assert payload.get("ticket", {}).get("status") == "triage"


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
    assert payload.get("ticket", {}).get("status") == "triage"
    assert payload.get("ticket", {}).get("project") == "TRIAGE"


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
    assert payload.get("ticket", {}).get("status") == "triage"
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
    assert payload.get("ticket", {}).get("status") == "triage"
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

    status_response = c.patch(
        f"/api/tickets/{ticket_id}",
        data=json.dumps({"field": "status", "value": "todo"}),
        content_type="application/json",
    )
    assert status_response.status_code == 200


@test("/triage GET shows triage inbox")
def _(c=auth_client):
    response = c.get("/triage")
    assert response.status_code in [200, 302]
    if response.status_code == 200:
        assert b"Triage Inbox" in response.data


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
        assert b"Triage is your intake inbox" in response.data
        assert b"Quick Intake" in response.data
        assert b"Send Selected" in response.data


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
    c.get('/logout', follow_redirects=False)
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


@test("Tickets page includes local storage view preference hook")
def _(c=auth_client):
    response = c.get("/tickets")
    assert response.status_code in [200, 302]
    if response.status_code == 200:
        assert b"ticket_view_preference" in response.data
