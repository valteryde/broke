"""Stale ticket overview and manual close-from-queue API."""

import json
import time
from contextlib import contextmanager

import faker
from ward import test

from app.utils.app import create_app
from app.utils.models import Comment, Project, Ticket, TicketUpdateMessage, create_user, database
from app.utils.stale_tickets import clamp_inactive_days, list_stale_rows
from tests.fixtures import fake, test_project


@contextmanager
def logged_in_client(fake: faker.Faker):
    """Flask test client with a fresh user session (avoids Ward global fixture resolution)."""
    if not database.is_closed():
        database.close()
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    username = f"st_{fake.uuid4()[:8]}"
    password = "pw12345678"
    create_user(username, password, f"{username}@example.com")
    with app.test_client() as c:
        login = c.post("/callback", data={"username": username, "password": password})
        assert login.status_code in (302, 301), login.status_code
        try:
            yield c
        finally:
            if not database.is_closed():
                database.close()


@test("clamp_inactive_days bounds input")
def _():
    assert clamp_inactive_days(3) == 7
    assert clamp_inactive_days(90) == 90
    assert clamp_inactive_days(99999) == 3650


@test("list_stale_rows returns tickets past inactivity threshold")
def _(fake=fake, test_project: Project = test_project):
    now = int(time.time())
    old = now - 120 * 86400
    tid = f"{test_project.id}-st-{fake.uuid4()[:8]}"
    Ticket.create(
        id=tid,
        title="Old open",
        description="",
        status="backlog",
        priority="medium",
        project=test_project.id,
        created_at=old,
    )
    rows = list_stale_rows(test_project.id, 90, now=now)
    ids = {r["ticket"].id for r in rows}
    assert tid in ids


@test("close-stale rejects when subtickets still open")
def _(fake=fake, test_project: Project = test_project):
    now = int(time.time())
    old = now - 120 * 86400
    parent_id = f"{test_project.id}-sp-{fake.uuid4()[:8]}"
    child_id = f"{test_project.id}-sc-{fake.uuid4()[:8]}"
    Ticket.create(
        id=parent_id,
        title="Parent",
        description="",
        status="backlog",
        priority="medium",
        project=test_project.id,
        created_at=old,
    )
    Ticket.create(
        id=child_id,
        title="Child",
        description="",
        status="todo",
        priority="medium",
        project=test_project.id,
        created_at=old,
        parent_ticket_id=parent_id,
    )
    with logged_in_client(fake) as c:
        r = c.post(
            f"/api/tickets/{parent_id}/close-stale",
            data=json.dumps({"inactive_days": 30}),
            content_type="application/json",
        )
        assert r.status_code == 409


@test("close-stale closes ticket and adds comment")
def _(fake=fake, test_project: Project = test_project):
    now = int(time.time())
    old = now - 120 * 86400
    tid = f"{test_project.id}-sx-{fake.uuid4()[:8]}"
    Ticket.create(
        id=tid,
        title="Close me",
        description="",
        status="todo",
        priority="medium",
        project=test_project.id,
        created_at=old,
    )
    with logged_in_client(fake) as c:
        r = c.post(
            f"/api/tickets/{tid}/close-stale",
            data=json.dumps({"inactive_days": 90}),
            content_type="application/json",
        )
        assert r.status_code == 200
    t = Ticket.get_by_id(tid)
    assert t.status == "closed"
    cmt = Comment.select().where(Comment.ticket == tid).order_by(Comment.id.desc()).get()
    assert "stale tickets overview" in cmt.body.lower()
    msg = (
        TicketUpdateMessage.select()
        .where(TicketUpdateMessage.ticket == tid)
        .order_by(TicketUpdateMessage.id.desc())
        .get()
    )
    assert "closed" in msg.message.lower()


@test("close-stale 400 when not stale under threshold")
def _(fake=fake, test_project: Project = test_project):
    tid = f"{test_project.id}-sn-{fake.uuid4()[:8]}"
    Ticket.create(
        id=tid,
        title="Fresh",
        description="",
        status="backlog",
        priority="medium",
        project=test_project.id,
        created_at=int(time.time()) - 3600,
    )
    with logged_in_client(fake) as c:
        r = c.post(
            f"/api/tickets/{tid}/close-stale",
            data=json.dumps({"inactive_days": 90}),
            content_type="application/json",
        )
        assert r.status_code == 400


@test("stale tickets page loads when authenticated")
def _(fake=fake):
    with logged_in_client(fake) as c:
        r = c.get("/tickets/stale")
        assert r.status_code == 200
        assert b"Stale tickets" in r.data
