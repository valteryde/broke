import json
import time
from ward import test
from app.utils.models import Ticket, ChangelogRelease, GlobalSetting, Project, WorkCycle
from tests.fixtures import auth_client, test_project, test_ticket, client


@test("changelog public view respects published status")
def _(client=client):
    ts = str(int(time.time() * 1000))
    content_draft = json.dumps({"entries": [{"text": "Secret draft change", "category": "new"}], "notes": ""})
    content_pub = json.dumps({"entries": [{"text": "Public visible change", "category": "changed"}], "notes": ""})

    draft_rel = ChangelogRelease.create(version=f"d-{ts}", title="Draft Release", content=content_draft, status="draft")
    pub_rel = ChangelogRelease.create(version=f"p-{ts}", title="Published Release", content=content_pub, status="published")

    response = client.get("/changelog")

    assert response.status_code == 200
    assert b"Published Release" in response.data
    assert b"Public visible change" in response.data
    assert b"Draft Release" not in response.data
    assert b"Secret draft change" not in response.data


@test("public changelog groups entries by category")
def _(client=client):
    ts = str(int(time.time() * 1000))
    content = json.dumps({
        "entries": [
            {"text": "Added new dashboard", "category": "new"},
            {"text": "Improved loading speed", "category": "changed"},
            {"text": "Fixed login bug", "category": "fixed"},
        ],
        "notes": "Minor stability improvements."
    })

    ChangelogRelease.create(version=f"cat-{ts}", title="Category Test", content=content, status="published")

    response = client.get("/changelog")
    assert response.status_code == 200
    assert b"Added new dashboard" in response.data
    assert b"Improved loading speed" in response.data
    assert b"Fixed login bug" in response.data
    assert b"Minor stability improvements." in response.data


@test("editor view responds with 200")
def _(client=auth_client):
    response = client.get("/changelog/new")
    assert response.status_code == 200
    assert b"New Release" in response.data


@test("can create a release with JSON content")
def _(client=auth_client, project=test_project):
    ts = str(int(time.time() * 1000))
    content = json.dumps({
        "entries": [
            {"text": "We have added a new report feature", "category": "new", "ticket_id": None},
            {"text": "We have improved dashboard performance", "category": "changed", "ticket_id": None},
        ],
        "notes": ""
    })

    payload = {
        "version": f"c-{ts}",
        "title": "Welcome Update",
        "content": content,
        "status": "draft"
    }

    response = client.post(
        "/api/changelog/releases",
        data=json.dumps(payload),
        content_type="application/json"
    )

    assert response.status_code == 201
    data = json.loads(response.data)
    assert data["success"] is True

    release = ChangelogRelease.get(ChangelogRelease.version == f"c-{ts}")
    assert release.title == "Welcome Update"
    assert release.status == "draft"

    stored = json.loads(release.content)
    assert len(stored["entries"]) == 2
    assert stored["entries"][0]["category"] == "new"


@test("can delete a release")
def _(client=auth_client, project=test_project):
    ts = str(int(time.time() * 1000))
    content = json.dumps({"entries": [{"text": "bye", "category": "changed"}], "notes": ""})
    release = ChangelogRelease.create(version=f"del-{ts}", title="To Delete", content=content, status="published")

    response = client.delete(f"/api/changelog/{release.id}")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["success"] is True

    assert ChangelogRelease.get_or_none(ChangelogRelease.id == release.id) is None


@test("rejects invalid content format")
def _(client=auth_client, project=test_project):
    ts = str(int(time.time() * 1000))

    # Plain string content should be rejected
    payload = {
        "version": f"bad-{ts}",
        "title": "Bad Format",
        "content": "just a plain string",
        "status": "draft"
    }

    response = client.post(
        "/api/changelog/releases",
        data=json.dumps(payload),
        content_type="application/json"
    )
    assert response.status_code == 400


@test("changelog API returns done sprint tickets only")
def _(client=auth_client, project=test_project):
    wc = WorkCycle.create(name="API sprint import", project=None, created_at=int(time.time()))
    ts = int(time.time() * 1000)
    tid_done = f"SPR-D-{ts}"
    tid_todo = f"SPR-T-{ts}"
    Ticket.create(
        id=tid_done,
        title="Shipped feature",
        description="",
        project=project.id,
        status="done",
        priority="medium",
        work_cycle_id=wc.id,
    )
    Ticket.create(
        id=tid_todo,
        title="Still in progress",
        description="",
        project=project.id,
        status="in-progress",
        priority="medium",
        work_cycle_id=wc.id,
    )

    try:
        response = client.get(f"/api/changelog/work-cycles/{wc.id}/done-tickets")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["success"] is True
        ids = [t["id"] for t in data["tickets"]]
        assert tid_done in ids
        assert tid_todo not in ids
    finally:
        Ticket.delete().where(Ticket.id.in_([tid_done, tid_todo])).execute()
        wc.delete_instance()


@test("changelog API 404 for unknown sprint done-tickets")
def _(client=auth_client):
    response = client.get("/api/changelog/work-cycles/999999999/done-tickets")
    assert response.status_code == 404
