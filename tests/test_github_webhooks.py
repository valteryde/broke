from ward import test
import json
from fixtures import client


@test("/api/webhooks/github/ Ping event", tags=["webhooks"])
def _(client=client):

    # ? Send a github ping event and verify 200 response

    payload = {
        "zen": "Keep it logically awesome.",
        "hook_id": 123456,
        "repository": {"name": "test-repo"},
    }
    payload_bytes = json.dumps(payload).encode()

    headers = {"X-GitHub-Event": "ping", "Content-Type": "application/json"}

    response = client.post("/api/webhooks/github/", data=payload_bytes, headers=headers)
    assert response.status_code == 200
    data = response.get_json()
    assert data["message"] == "Pong! Webhook configured successfully."
