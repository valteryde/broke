"""
Pull request webhook tests
"""


from ward import test, fixture, Scope
from app.utils.app import app
import hmac
import hashlib
import json
from fixtures import client, test_ticket
from app.views.webhooks import get_github_webhook_secret
from app.utils.models import Project, Ticket, TicketUpdateMessage



@test("/api/webhooks/github/ Pull request merged event with valid signature", tags=["webhooks"])
def _(client=client, test_ticket=test_ticket):

    # ? Push a github pull request merged event with a valid signature and verify 200 response
    test_ticket.status = "todo"
    test_ticket.save()
    
    github_secret = get_github_webhook_secret().encode()
    payload = {
        "action": "closed",
        "number": 42,
        "pull_request": {
            "title": "Fix " + test_ticket.id,
            "body": "This PR fixes the issue.",
            "html_url": "https://github.com/test-repo/pull/42",
            "merged": True
        },
        "repository": {
            "name": "test-repo"
        }
    }
    payload_bytes = json.dumps(payload).encode()
    signature = 'sha256=' + hmac.new(github_secret, payload_bytes, hashlib.sha256).hexdigest()
    headers = {
        'X-GitHub-Event': 'pull_request',
        'X-Hub-Signature-256': signature,
        'Content-Type': 'application/json'
    }

    response = client.post("/api/webhooks/github/", data=payload_bytes, headers=headers)
    assert response.status_code == 200
    data = response.get_json()
    assert data['action'] == 'merged'
    assert test_ticket.id in data['closed_tickets']

    # Verify that the ticket has been updated to closed
    ticket = Ticket.get(Ticket.id == test_ticket.id)
    assert ticket.status == "closed"

    # Verify that a comment has been added to the ticket
    updates = TicketUpdateMessage.select()
    assert any(test_ticket.id in update.message for update in updates)


@test("/api/webhooks/github/ Pull request opened event with valid signature", tags=["webhooks"])
def _(client=client, test_ticket=test_ticket):

    # ? Push a github pull request opened event with a valid signature and verify 200 response
    test_ticket.status = "todo"
    test_ticket.save()
    
    github_secret = get_github_webhook_secret().encode()
    payload = {
        "action": "opened",
        "number": 43,
        "pull_request": {
            "title": "Implement feature for ref " + test_ticket.id,
            "body": "This PR implements the feature.",
            "html_url": "https://github.com/test-repo/pull/43",
        },
        "repository": {
            "name": "test-repo"
        }
    }
    payload_bytes = json.dumps(payload).encode()
    signature = 'sha256=' + hmac.new(github_secret, payload_bytes, hashlib.sha256).hexdigest()
    headers = {
        'X-GitHub-Event': 'pull_request',
        'X-Hub-Signature-256': signature,
        'Content-Type': 'application/json'
    }
    response = client.post("/api/webhooks/github/", data=payload_bytes, headers=headers)
    assert response.status_code == 200
    data = response.get_json()
    assert data['action'] == 'opened'
    
    # Verify that the ticket has been updated to in review
    ticket = Ticket.get(Ticket.id == test_ticket.id)
    print(ticket.status)
    assert ticket.status == "in-review"
