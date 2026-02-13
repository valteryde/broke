from ward import test
import hmac
import hashlib
import json
from fixtures import client, test_ticket
from app.views.webhooks import get_github_webhook_secret
from app.utils.models import Ticket, TicketUpdateMessage


@test("/api/webhooks/github/ Push event with valid signature", tags=["webhooks"])
def _(client=client, test_ticket=test_ticket):

    # ? Push a github push event with a valid signature and verify 200 response
    test_ticket.status = "todo"
    test_ticket.save()

    github_secret = get_github_webhook_secret().encode()
    payload = {
        "ref": "refs/heads/main",
        "repository": {"name": "test-repo"},
        "pusher": {"name": "test-user"},
        "commits": [
            {
                "author": {"email": "example@example.com", "name": "Test User"},
                "message": "fix " + test_ticket.id,
                "distinct": True,
                "id": "commitsha123",
            }
        ],
    }
    payload_bytes = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(github_secret, payload_bytes, hashlib.sha256).hexdigest()

    headers = {
        "X-GitHub-Event": "push",
        "X-Hub-Signature-256": signature,
        "Content-Type": "application/json",
    }

    response = client.post("/api/webhooks/github/", data=payload_bytes, headers=headers)
    assert response.status_code == 200
    data = response.get_json()
    assert data["event"] == "push"

    # Verify that the ticket has been updated with the commit message
    ticket = Ticket.get(Ticket.id == test_ticket.id)
    assert ticket.status == "done"

    # Verify that a comment has been added to the ticket
    updates = TicketUpdateMessage.select()
    assert any(test_ticket.id in update.message for update in updates)


@test("/api/webhooks/github/ Push event reference ticket", tags=["webhooks"])
def _(client=client, test_ticket=test_ticket):

    # ? Push a github push event that references a ticket and verify 200 response
    test_ticket.status = "todo"
    test_ticket.save()

    github_secret = get_github_webhook_secret().encode()
    payload = {
        "ref": "refs/heads/main",
        "repository": {"name": "test-repo"},
        "pusher": {"name": "test-user"},
        "commits": [
            {
                "author": {"email": "example@example.com", "name": "Test User"},
                "message": "This commit ref " + test_ticket.id,
                "distinct": True,
                "id": "commitsha456",
            }
        ],
    }
    payload_bytes = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(github_secret, payload_bytes, hashlib.sha256).hexdigest()
    headers = {
        "X-GitHub-Event": "push",
        "X-Hub-Signature-256": signature,
        "Content-Type": "application/json",
    }
    response = client.post("/api/webhooks/github/", data=payload_bytes, headers=headers)
    assert response.status_code == 200
    data = response.get_json()
    assert data["event"] == "push"
    # Verify that the ticket status has not changed
    ticket = Ticket.get(Ticket.id == test_ticket.id)
    assert ticket.status == "todo"

    # Verify that a comment has been added to the ticket
    updates = TicketUpdateMessage.select()
    assert any(test_ticket.id in update.message for update in updates)


@test("/api/webhooks/github/ Push event with invalid signature", tags=["webhooks"])
def _(client=client):

    # ? Push a github push event with an invalid signature and verify 401 response

    payload = {
        "ref": "refs/heads/main",
        "repository": {"name": "test-repo"},
        "pusher": {"name": "test-user"},
    }
    payload_bytes = json.dumps(payload).encode()
    invalid_signature = "sha256=invalidsignature"

    headers = {
        "X-GitHub-Event": "push",
        "X-Hub-Signature-256": invalid_signature,
        "Content-Type": "application/json",
    }

    response = client.post("/api/webhooks/github/", data=payload_bytes, headers=headers)
    assert response.status_code == 401
