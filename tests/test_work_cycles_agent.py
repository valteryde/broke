import time

from fixtures import auth_client, test_project, test_ticket
from ward import test

from app.utils.models import AgentToken, Project, Ticket, WorkCycle


@test("POST /api/work-cycles creates a cycle", tags=["api"])
def _(auth_client=auth_client, test_project=test_project):
    r = auth_client.post(
        "/api/work-cycles",
        json={"name": "Cycle A", "goal": "Ship"},
    )
    assert r.status_code == 201
    data = r.get_json()
    assert data["cycle"]["name"] == "Cycle A"
    cid = data["cycle"]["id"]
    WorkCycle.delete_by_id(cid)


@test("GET /api/work-cycles/<id>/backlog-tickets lists unscheduled tickets", tags=["api"])
def _(auth_client=auth_client, test_ticket=test_ticket):
    wc = WorkCycle.create(name="Sprint with backlog API", project=None, created_at=int(time.time()))
    try:
        prev_cycle = test_ticket.work_cycle_id
        test_ticket.work_cycle_id = None
        test_ticket.save()
        r = auth_client.get(f"/api/work-cycles/{wc.id}/backlog-tickets?limit=50")
        assert r.status_code == 200
        body = r.get_json()
        ids = [t["id"] for t in body.get("tickets", [])]
        assert test_ticket.id in ids
        r404 = auth_client.get("/api/work-cycles/999999999/backlog-tickets")
        assert r404.status_code == 404
    finally:
        test_ticket.work_cycle_id = prev_cycle
        test_ticket.save()
        wc.delete_instance()


@test("POST /api/work-cycles/<id>/tickets adds tickets (any project)", tags=["api"])
def _(auth_client=auth_client, test_project=test_project, test_ticket=test_ticket):
    wc = WorkCycle.create(
        name="Pick sprint",
        project=None,
        created_at=int(time.time()),
    )
    other = WorkCycle.create(
        name="Other proj tagged",
        project="nonexistent-project-xyz",
        created_at=int(time.time()),
    )
    try:
        r = auth_client.post(
            f"/api/work-cycles/{wc.id}/tickets",
            json={"add": [test_ticket.id]},
        )
        assert r.status_code == 200
        assert r.get_json().get("added") == 1
        assert Ticket.get_by_id(test_ticket.id).work_cycle_id == wc.id

        r2 = auth_client.patch(
            f"/api/tickets/{test_ticket.id}",
            json={"field": "work_cycle_id", "value": other.id},
        )
        assert r2.status_code == 200
        assert Ticket.get_by_id(test_ticket.id).work_cycle_id == other.id

        r3 = auth_client.post(
            f"/api/work-cycles/{other.id}/tickets",
            json={"remove": [test_ticket.id]},
        )
        assert r3.status_code == 200
        assert r3.get_json().get("removed") == 1
        assert Ticket.get_by_id(test_ticket.id).work_cycle_id is None
    finally:
        test_ticket.work_cycle_id = None
        test_ticket.save()
        wc.delete_instance()
        other.delete_instance()


@test("Work cycle export returns JSON with tickets", tags=["api"])
def _(auth_client=auth_client, test_ticket=test_ticket):
    wc = WorkCycle.create(name="Exp", project=None, created_at=int(time.time()))
    test_ticket.work_cycle_id = wc.id
    test_ticket.save()
    try:
        r = auth_client.get(f"/api/work-cycles/{wc.id}/export?format=json")
        assert r.status_code == 200
        body = r.get_json()
        assert body["cycle"]["id"] == wc.id
        ids = [t["id"] for t in body["tickets"]]
        assert test_ticket.id in ids
    finally:
        test_ticket.work_cycle_id = None
        test_ticket.save()
        wc.delete_instance()


@test("Agent token can post comment", tags=["api"])
def _(auth_client=auth_client, test_ticket=test_ticket):
    from app.utils.models import Comment

    mint = auth_client.post("/api/settings/agent-tokens", json={})
    assert mint.status_code == 201
    payload = mint.get_json()
    token = payload["token"]
    token_id = payload["token_id"]

    r = auth_client.post(
        f"/api/agent/tickets/{test_ticket.id}/comments",
        headers={"Authorization": f"Bearer {token}"},
        json={"body": "from agent"},
    )
    assert r.status_code == 201
    data = r.get_json()
    cid = data.get("comment_id")
    assert cid is not None
    row = Comment.get_by_id(cid)
    assert int(getattr(row, "via_agent", 0) or 0) == 1

    AgentToken.delete_by_id(token_id)


@test("Scoped agent token rejects wrong project ticket", tags=["api"])
def _(auth_client=auth_client, test_ticket=test_ticket):
    other_proj = Project.create(
        id="other-agent-scope-proj",
        name="Other",
        icon="ph ph-folder",
        color="gray",
    )
    try:
        mint = auth_client.post(
            "/api/settings/agent-tokens",
            json={"project": other_proj.id},
        )
        assert mint.status_code == 201
        payload = mint.get_json()
        token = payload["token"]
        token_id = payload["token_id"]

        r = auth_client.post(
            f"/api/agent/tickets/{test_ticket.id}/comments",
            headers={"Authorization": f"Bearer {token}"},
            json={"body": "nope"},
        )
        assert r.status_code == 403

        AgentToken.delete_by_id(token_id)
    finally:
        other_proj.delete_instance(recursive=True, delete_nullable=True)
