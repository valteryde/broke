"""Per-ticket 'Let AI do it' — single paste with minted token + full context."""

import re

from fixtures import auth_client, test_project, test_ticket
from ward import test

from app.utils.models import AgentToken, Ticket


@test("POST ai-delegate-pack is blocked until ai_delegate is on", tags=["api"])
def _(auth_client=auth_client, test_ticket=test_ticket):
    test_ticket.ai_delegate = 0
    test_ticket.save()
    r = auth_client.post(f"/api/tickets/{test_ticket.id}/ai-delegate-pack", json={})
    assert r.status_code == 400


@test("POST ai-delegate-pack includes token and curl; token works for agent PATCH", tags=["api"])
def _(auth_client=auth_client, test_ticket=test_ticket):
    test_ticket.ai_delegate = 0
    test_ticket.status = "backlog"
    test_ticket.save()
    token_id = None
    try:
        on = auth_client.patch(
            f"/api/tickets/{test_ticket.id}",
            json={"field": "ai_delegate", "value": True},
        )
        assert on.status_code == 200

        pack = auth_client.post(f"/api/tickets/{test_ticket.id}/ai-delegate-pack", json={})
        assert pack.status_code == 200
        token_id = pack.headers.get("X-Agent-Token-Id")
        assert token_id
        text = pack.get_data(as_text=True)
        assert test_ticket.id in text
        assert "curl -sS" in text
        assert "/api/agent/tickets/" in text
        assert "YOUR_TOKEN" not in text
        # Bearer appears as code line and inside curl
        assert "Authorization: Bearer" in text
        assert "urllib.request" in text

        m = re.search(r"-H 'Authorization: Bearer ([^']+)'", text)
        assert m
        inner = m.group(1)
        assert len(inner) > 20

        ping = auth_client.get(
            "/api/agent/ping",
            headers={"Authorization": f"Bearer {inner}"},
        )
        assert ping.status_code == 200
        assert ping.get_json().get("ok") is True

        agent = auth_client.patch(
            f"/api/agent/tickets/{test_ticket.id}",
            headers={"Authorization": f"Bearer {inner}"},
            json={"status": "in-progress"},
        )
        assert agent.status_code == 200
        t2 = Ticket.get_by_id(test_ticket.id)
        assert t2.status == "in-progress"
    finally:
        test_ticket.status = "todo"
        test_ticket.ai_delegate = 0
        test_ticket.save()
        if token_id:
            try:
                AgentToken.delete_by_id(int(token_id))
            except Exception:
                pass


@test("Ticket-scoped delegate token rejects other ticket", tags=["api"])
def _(auth_client=auth_client, test_project=test_project, test_ticket=test_ticket):
    other_id = f"{test_project.id}-delegate-other-{test_ticket.id[-8:]}"
    other = Ticket.create(
        id=other_id,
        title="Other",
        description="x",
        project=test_project.id,
        status="backlog",
        priority="medium",
    )
    token_id = None
    try:
        auth_client.patch(
            f"/api/tickets/{test_ticket.id}",
            json={"field": "ai_delegate", "value": True},
        )
        pack = auth_client.post(f"/api/tickets/{test_ticket.id}/ai-delegate-pack", json={})
        assert pack.status_code == 200
        token_id = pack.headers.get("X-Agent-Token-Id")
        text = pack.get_data(as_text=True)
        m = re.search(r"-H 'Authorization: Bearer ([^']+)'", text)
        assert m
        inner = m.group(1)
        bad = auth_client.patch(
            f"/api/agent/tickets/{other_id}",
            headers={"Authorization": f"Bearer {inner}"},
            json={"status": "in-progress"},
        )
        assert bad.status_code == 403
    finally:
        other.delete_instance(recursive=True, delete_nullable=True)
        test_ticket.ai_delegate = 0
        test_ticket.save()
        if token_id:
            try:
                AgentToken.delete_by_id(int(token_id))
            except Exception:
                pass
