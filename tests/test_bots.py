"""Bot users and the MCP endpoint."""

import json

import pyargon2
from ward import test

from app.utils.models import Comment, Ticket, User, database
from tests.fixtures import app, auth_client, auth_user, fake, test_project, test_ticket


def _rpc(c, token, method, params=None, req_id=1, origin=None):
    body = {"jsonrpc": "2.0", "method": method, "params": params or {}}
    if req_id is not None:
        body["id"] = req_id
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if origin:
        headers["Origin"] = origin
    return c.post("/mcp", json=body, headers=headers)


def _bot_name(fake) -> str:
    return "b" + fake.uuid4().replace("-", "")[:12]


def _create_bot(c, username):
    return c.post("/api/settings/bots", json={"username": username})


@test("settings bots page explains the endpoint")
def _(c=auth_client):
    response = c.get("/settings/bots")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Create a bot" in body
    assert "/mcp" in body


@test("creating a bot returns a token and config once")
def _(c=auth_client, user=auth_user, fake=fake):
    username = _bot_name(fake)
    response = _create_bot(c, username)
    assert response.status_code == 201
    data = response.get_json()
    assert data["token"]
    config = json.loads(data["mcp_config"])
    assert config["mcpServers"]["broke"]["url"].endswith("/mcp")
    assert data["token"] in config["mcpServers"]["broke"]["headers"]["Authorization"]

    bot = User.get(User.username == username)
    assert bot.is_bot == 1
    assert bot.email is None
    assert bot.admin == 0
    assert bot.bot_owner == user.username
    page = c.get("/settings/bots").get_data(as_text=True)
    assert username in page
    assert data["token"] not in page


@test("a bot cannot sign in with a password")
def _(app=app, auth=auth_client, fake=fake):
    username = _bot_name(fake)
    created = _create_bot(auth, username)
    assert created.status_code == 201
    bot = User.get(User.username == username)
    bot.password_hash = pyargon2.hash("secretpass", bot.salt)
    bot.save()

    with app.test_client() as c:
        response = c.post(
            "/callback",
            data={"username": username, "password": "secretpass"},
            follow_redirects=False,
        )
    assert response.status_code == 302
    assert "news" not in (response.location or "")


@test("another user cannot rotate or remove a bot they do not own")
def _(c=auth_client, owner=auth_user, fake=fake):
    username = _bot_name(fake)
    created = _create_bot(c, username)
    assert created.status_code == 201
    with c.application.test_client() as other:
        from app.utils.models import create_user

        stranger_name = "s" + fake.uuid4().replace("-", "")[:12]
        stranger = create_user(
            stranger_name,
            "testpassword123",
            f"{stranger_name}@example.com",
        )
        login = other.post(
            "/callback",
            data={"username": stranger.username, "password": "testpassword123"},
            follow_redirects=False,
        )
        assert login.status_code == 302
        assert other.post(f"/api/settings/bots/{username}/token").status_code == 404
        assert other.delete(f"/api/settings/bots/{username}").status_code == 404
    assert User.get(User.username == username).bot_disabled == 0
    assert owner.username


@test("MCP initialize lists tools and a later call can comment and update")
def _(c=auth_client, ticket=test_ticket, project=test_project, fake=fake):
    username = _bot_name(fake)
    created = _create_bot(c, username)
    token = created.get_json()["token"]

    init = _rpc(c, token, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}})
    assert init.status_code == 200
    body = init.get_json()
    assert body["result"]["serverInfo"]["name"] == "broke"
    assert username in body["result"]["instructions"]
    names = [tool["name"] for tool in _rpc(c, token, "tools/list").get_json()["result"]["tools"]]
    assert "list_tickets" in names
    assert "add_comment" in names
    assert "create_ticket" in names

    listed = _rpc(
        c,
        token,
        "tools/call",
        {"name": "list_tickets", "arguments": {"project": project.id}},
    )
    tickets = json.loads(listed.get_json()["result"]["content"][0]["text"])["tickets"]
    assert any(row["id"] == ticket.id for row in tickets)

    commented = _rpc(
        c,
        token,
        "tools/call",
        {"name": "add_comment", "arguments": {"ticket_id": ticket.id, "body": "Shipped the fix."}},
    )
    assert commented.get_json()["result"]["isError"] is False
    comment = Comment.get((Comment.ticket == ticket.id) & (Comment.body == "Shipped the fix."))
    assert comment.user.username == username
    assert int(comment.via_agent or 0) == 0

    updated = _rpc(
        c,
        token,
        "tools/call",
        {
            "name": "update_ticket",
            "arguments": {"ticket_id": ticket.id, "status": "in-progress", "estimate_minutes": 90},
        },
    )
    assert updated.get_json()["result"]["isError"] is False
    fresh = Ticket.get(Ticket.id == ticket.id)
    assert fresh.status == "in-progress"
    assert fresh.estimate_minutes == 90

    made = _rpc(
        c,
        token,
        "tools/call",
        {
            "name": "create_ticket",
            "arguments": {"title": "Follow up", "project": project.id, "description": "Later"},
        },
    )
    made_body = json.loads(made.get_json()["result"]["content"][0]["text"])
    assert made_body["project"] == project.id
    assert Ticket.get(Ticket.id == made_body["id"]).title == "Follow up"


@test("MCP rejects a missing token, a revoked token, and a foreign origin")
def _(c=auth_client, fake=fake):
    username = _bot_name(fake)
    created = _create_bot(c, username)
    token = created.get_json()["token"]
    assert _rpc(c, None, "initialize").status_code == 401

    rotated = c.post(f"/api/settings/bots/{username}/token")
    assert rotated.status_code == 200
    new_token = rotated.get_json()["token"]
    assert new_token != token
    assert _rpc(c, token, "tools/list").status_code == 401
    assert _rpc(c, new_token, "tools/list").status_code == 200

    note = c.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers={"Authorization": f"Bearer {new_token}"},
    )
    assert note.status_code == 202

    removed = c.delete(f"/api/settings/bots/{username}")
    assert removed.status_code == 200
    assert _rpc(c, new_token, "tools/list").status_code == 401

    other_name = _bot_name(fake)
    created_again = _create_bot(c, other_name)
    live = created_again.get_json()["token"]
    blocked = _rpc(c, live, "tools/list", origin="https://evil.example")
    assert blocked.status_code == 403


@test("user email can be null after the bot migration")
def _(app=app):
    rows = database.execute_sql('PRAGMA table_info("user")').fetchall()
    info = {row[1]: row for row in rows}
    assert info["email"][3] == 0
    assert "is_bot" in info
    assert "bot_disabled" in info
    assert app is not None
