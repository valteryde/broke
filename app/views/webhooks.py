from ..utils.models import Project
from flask import request, Blueprint
from peewee import DoesNotExist
import json
import hashlib
import re
from .settings import get_github_webhook_secret
import hmac
from ..utils.models import Ticket, TicketUpdateMessage

# Create blueprint
webhooks_bp = Blueprint("webhooks", __name__)

# * GitHub Webhook Handlers * #
TICKET_RESOLVE_PATTERN = re.compile(
    r"(?:fix|fixes|fixed|close|closes|closed|resolve|resolves|resolved)\s*#?([\w-]+)", re.IGNORECASE
)
TICKET_REFER_PATTERN = re.compile(r"(?:ref|refs|about|see|related)\s*#?([\w-]+)", re.IGNORECASE)


def handle_github_push_event(payload: dict, project: Project) -> dict:
    """Handle GitHub push events - link commits to tickets."""

    commits = payload.get("commits", [])
    linked_tickets = []

    for commit in commits:
        message = commit.get("message", "")
        commit_sha = commit.get("id", "")[:8]
        commit_url = commit.get("url", "")
        author = commit.get("author", {}).get("name", "Unknown")

        matches_resolve = TICKET_RESOLVE_PATTERN.findall(message)
        matches_refere = TICKET_REFER_PATTERN.findall(message)

        for ticket_id_str in matches_resolve:
            try:
                ticket_id = ticket_id_str
                ticket = Ticket.get(Ticket.id == ticket_id)

                ticket.status = "done"
                ticket.save()

                linked_tickets.append({"ticket_id": ticket_id, "commit": commit_sha})
            except (DoesNotExist, ValueError):
                continue

        for ticket_id_str in matches_resolve + matches_refere:
            try:
                ticket_id = ticket_id_str
                ticket = Ticket.get(Ticket.id == ticket_id)

                TicketUpdateMessage.create(
                    ticket=ticket.id,
                    title="Commit Linked",
                    icon="ph ph-git-commit",
                    message=f"Commit [{commit_sha}]({commit_url}) by {author}\n\n> {message.split(chr(10))[0]}",
                )

                if re.search(
                    r"(?:fix|fixes|fixed|close|closes|closed)\s*#" + ticket_id_str,
                    message,
                    re.IGNORECASE,
                ):
                    ticket.status = "closed"
                    ticket.save()

                linked_tickets.append({"ticket_id": ticket_id, "commit": commit_sha})
            except (DoesNotExist, ValueError):
                continue

    return {"action": "push", "commits_processed": len(commits), "linked_tickets": linked_tickets}


def handle_github_pr_event(payload: dict, project: Project) -> dict:
    """Handle GitHub pull request events."""

    action = payload.get("action", "")
    pr = payload.get("pull_request", {})

    pr_number = pr.get("number")
    pr_title = pr.get("title", "")
    pr_body = pr.get("body", "") or ""
    pr_url = pr.get("html_url", "")
    merged = pr.get("merged", False)

    if action == "opened":
        # Set the PR ticket to "in review"
        all_text = f"{pr_title} {pr_body}"
        matches = TICKET_REFER_PATTERN.findall(all_text)
        for ticket_id_str in matches:
            try:
                ticket = Ticket.get(Ticket.id == ticket_id_str)
                ticket.status = "in-review"
                ticket.save()

                TicketUpdateMessage.create(
                    ticket=ticket.id,
                    title="PR Opened",
                    icon="ph ph-git-pull-request",
                    message=f"PR #{pr_number} opened: [{pr_title}]({pr_url})",
                )

            except (DoesNotExist, ValueError):
                continue

    if action == "closed" and merged:
        all_text = f"{pr_title} {pr_body}"
        matches = TICKET_RESOLVE_PATTERN.findall(all_text)
        closed_tickets = []

        for ticket_id_str in matches:
            try:
                ticket = Ticket.get(Ticket.id == ticket_id_str)
                ticket.status = "closed"
                ticket.save()

                TicketUpdateMessage.create(
                    ticket=ticket.id,
                    title="PR Merged - Ticket Closed",
                    icon="ph ph-check-fat",
                    message=f"Closed via PR #{pr_number}: [{pr_title}]({pr_url})",
                )

                closed_tickets.append(ticket_id_str)
            except (DoesNotExist, ValueError):
                continue

        return {"action": "merged", "pr_number": pr_number, "closed_tickets": closed_tickets}

    return {"action": action, "pr_number": pr_number}


# ============ GitHub Webhook Handler ============
@webhooks_bp.route("/api/webhooks/github/", methods=["POST"])
def github_webhook():
    """
    Handle incoming GitHub webhook events.

    Supported events:
    - issues: Create tickets from GitHub issues
    - push: Link commits to tickets
    - pull_request: Track PRs and close tickets on merge
    - issue_comment: Sync comments to tickets
    """

    # Get the event type from headers
    event_type = request.headers.get("X-GitHub-Event", "ping")
    delivery_id = request.headers.get("X-GitHub-Delivery", "")
    secret = request.headers.get("X-Hub-Signature-256", "")

    # Handle ping event (GitHub sends this when webhook is created)
    if event_type == "ping":
        return {"message": "Pong! Webhook configured successfully."}, 200

    # Verify signature
    payload_body = request.data
    try:
        payload = request.get_json()
        repo = payload.get("repository", {})
        repo_name = repo.get("name", "")

        # Get the webhook secret for this project
        github_secret = get_github_webhook_secret()

        computed_signature = (
            "sha256=" + hmac.new(github_secret.encode(), payload_body, hashlib.sha256).hexdigest()
        )

        if not hmac.compare_digest(computed_signature, secret):
            return json.dumps({"error": "Invalid signature"}), 401
    except Exception:
        return json.dumps({"error": "Error verifying signature"}), 400

    try:
        payload = request.get_json()
    except Exception:
        return json.dumps({"error": "Invalid JSON payload"}), 400

    if not payload:
        return json.dumps({"error": "Empty payload"}), 400

    # Get repository info
    repo = payload.get("repository", {})
    repo_name = repo.get("name", "")

    # Find a matching project by name, or use the first available project
    project = None
    try:
        project = Project.get(Project.name == repo_name)
    except DoesNotExist:
        project = Project.select().first()

    if not project:
        return json.dumps({"error": "No projects found"}), 404

    response_data = {"event": event_type, "delivery_id": delivery_id}

    # Handle different event types
    if event_type == "push":
        response_data.update(handle_github_push_event(payload, project))
    elif event_type == "pull_request":
        response_data.update(handle_github_pr_event(payload, project))
    else:
        response_data["message"] = f'Event type "{event_type}" received but not processed'

    return response_data, 200
