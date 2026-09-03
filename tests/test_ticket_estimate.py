"""Tests for ticket time estimates."""

import json
import time

from ward import test

from app.utils.models import Ticket, TicketUpdateMessage
from app.utils.ticket_estimate import (
    MAX_ESTIMATE_MINUTES,
    coerce_estimate_minutes,
    format_estimate_minutes,
    parse_estimate_input,
)
from app.utils.ticket_markdown import ticket_payload_to_markdown
from tests.fixtures import auth_client, fake, test_project, test_ticket


@test("format_estimate_minutes uses 8-hour days")
def _():
    assert format_estimate_minutes(None) == ""
    assert format_estimate_minutes(0) == ""
    assert format_estimate_minutes(15) == "15m"
    assert format_estimate_minutes(30) == "30m"
    assert format_estimate_minutes(60) == "1h"
    assert format_estimate_minutes(90) == "1h 30m"
    assert format_estimate_minutes(120) == "2h"
    assert format_estimate_minutes(480) == "1d"
    assert format_estimate_minutes(600) == "1d 2h"
    assert format_estimate_minutes(2400) == "1w"


@test("parse_estimate_input accepts durations and bare hours")
def _():
    assert parse_estimate_input("") is None
    assert parse_estimate_input("none") is None
    assert parse_estimate_input("2") == 120
    assert parse_estimate_input("2h") == 120
    assert parse_estimate_input("30m") == 30
    assert parse_estimate_input("1.5h") == 90
    assert parse_estimate_input("1d") == 480
    assert parse_estimate_input("1d 4h") == 720
    assert parse_estimate_input("1w") == 2400
    assert parse_estimate_input(2) == 120


@test("parse_estimate_input rejects junk and oversized values")
def _():
    raised = False
    try:
        parse_estimate_input("banana")
    except ValueError:
        raised = True
    assert raised

    raised = False
    try:
        parse_estimate_input("2h leftover")
    except ValueError:
        raised = True
    assert raised

    raised = False
    try:
        parse_estimate_input(f"{MAX_ESTIMATE_MINUTES // 60 + 1}h")
    except ValueError:
        raised = True
    assert raised


@test("coerce_estimate_minutes treats integers as minutes")
def _():
    assert coerce_estimate_minutes(120) == 120
    assert coerce_estimate_minutes("120") == 120
    assert coerce_estimate_minutes("2h") == 120
    assert coerce_estimate_minutes("none") is None
    assert coerce_estimate_minutes(0) is None
    assert coerce_estimate_minutes(2, integer_is_minutes=False) == 120


@test("PATCH sets and clears ticket estimate_minutes")
def _(c=auth_client, ticket=test_ticket):
    response = c.patch(
        f"/api/tickets/{ticket.id}",
        data=json.dumps({"field": "estimate_minutes", "value": 120}),
        content_type="application/json",
    )
    assert response.status_code == 200
    payload = json.loads(response.data)
    assert payload["ticket"]["estimate_minutes"] == 120
    assert payload["ticket"]["estimate"] == "2h"

    saved = Ticket.get_by_id(ticket.id)
    assert saved.estimate_minutes == 120

    update = (
        TicketUpdateMessage.select()
        .where(TicketUpdateMessage.ticket == ticket.id)
        .order_by(TicketUpdateMessage.created_at.desc())
        .first()
    )
    assert update is not None
    assert "2h" in update.message

    clear = c.patch(
        f"/api/tickets/{ticket.id}",
        data=json.dumps({"field": "estimate_minutes", "value": None}),
        content_type="application/json",
    )
    assert clear.status_code == 200
    assert Ticket.get_by_id(ticket.id).estimate_minutes is None


@test("PATCH estimate field parses duration strings")
def _(c=auth_client, ticket=test_ticket):
    response = c.patch(
        f"/api/tickets/{ticket.id}",
        data=json.dumps({"field": "estimate", "value": "1d"}),
        content_type="application/json",
    )
    assert response.status_code == 200
    assert Ticket.get_by_id(ticket.id).estimate_minutes == 480


@test("PATCH rejects invalid estimates")
def _(c=auth_client, ticket=test_ticket):
    response = c.patch(
        f"/api/tickets/{ticket.id}",
        data=json.dumps({"field": "estimate_minutes", "value": "nope"}),
        content_type="application/json",
    )
    assert response.status_code == 400


@test("POST create ticket accepts estimate_minutes")
def _(c=auth_client, f=fake, project=test_project):
    response = c.post(
        "/api/tickets",
        data=json.dumps(
            {
                "title": f.sentence(),
                "description": "with estimate",
                "project": project.id,
                "status": "todo",
                "priority": "medium",
                "estimate_minutes": 60,
            }
        ),
        content_type="application/json",
    )
    assert response.status_code == 201
    payload = json.loads(response.data)
    ticket_id = payload["ticket"]["id"]
    assert payload["ticket"]["estimate_minutes"] == 60
    assert Ticket.get_by_id(ticket_id).estimate_minutes == 60


@test("ticket markdown export includes estimate")
def _():
    markdown = ticket_payload_to_markdown(
        {
            "id": "FRO-1",
            "title": "Ship estimates",
            "description": "",
            "project": "FRO",
            "status": "todo",
            "priority": "medium",
            "estimate_minutes": 120,
            "parent_ticket_id": None,
            "work_cycle_id": None,
            "created_at": int(time.time()),
            "labels": [],
            "assignees": [],
            "comments": [],
            "updates": [],
            "subtickets": [],
        }
    )
    assert "- Estimate: 2h" in markdown
