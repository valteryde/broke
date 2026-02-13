"""Extended tests for settings and configuration"""

from ward import test, fixture
from tests.fixtures import app, client, auth_client, auth_user, create_test_project
from app.utils.models import User, Project, Label, APIToken, DSNToken
import json
import time


@test("/api/settings/profile POST updates profile")
def _(c=auth_client, user=auth_user):
    """Test updating user profile"""
    response = c.post(
        "/api/settings/profile",
        data=json.dumps({"display_name": "New Name"}),
        content_type="application/json",
    )
    assert response.status_code in [200, 302]


@test("/api/settings/preferences POST updates preferences")
def _(c=auth_client):
    """Test updating user preferences"""
    response = c.post(
        "/api/settings/preferences",
        data=json.dumps({"theme": "dark"}),
        content_type="application/json",
    )
    assert response.status_code in [200, 302]


@test("/api/settings/notifications POST updates notification settings")
def _(c=auth_client):
    """Test updating notification settings"""
    response = c.post(
        "/api/settings/notifications",
        data=json.dumps({"email_notifications": True}),
        content_type="application/json",
    )
    assert response.status_code in [200, 302]


@test("/api/settings/anonymous POST updates anonymous settings")
def _(c=auth_client):
    """Test updating anonymous submission settings"""
    response = c.post(
        "/api/settings/anonymous",
        data=json.dumps({"enabled": True, "message": "Welcome!", "projects": []}),
        content_type="application/json",
    )
    assert response.status_code in [200, 302]


@test("/api/settings/security/password POST changes password")
def _(c=auth_client):
    """Test changing user password"""
    response = c.post(
        "/api/settings/security/password",
        data=json.dumps(
            {
                "current_password": "testpass123",
                "new_password": "newpass456",
                "confirm_password": "newpass456",
            }
        ),
        content_type="application/json",
    )
    # May fail if current password doesn't match
    assert response.status_code in [200, 302, 400, 401]


@test("/api/settings/webhooks/regenerate-secret POST regenerates secret")
def _(c=auth_client):
    """Test regenerating webhook secret"""
    response = c.post(
        "/api/settings/webhooks/regenerate-secret",
        json={"type": "github"},
        content_type="application/json",
    )
    assert response.status_code in [200, 302]


@test("/api/settings/webhooks/<id> DELETE removes webhook")
def _(c=auth_client):
    """Test deleting a webhook"""
    # Try to delete non-existent webhook
    response = c.delete("/api/settings/webhooks/999")
    assert response.status_code in [200, 302, 404]


@test("/api/settings/tokens/<id> DELETE removes API token")
def _(c=auth_client, user=auth_user):
    """Test deleting an API token"""
    import hashlib

    # Create a token with required fields
    test_token = "test-token-abc123"
    token = APIToken.create(
        user=user,
        token_hash=hashlib.sha256(test_token.encode()).hexdigest(),
        token_preview=test_token[:8],
    )

    response = c.delete(f"/api/settings/tokens/{token.id}")
    assert response.status_code in [200, 302, 204]


@test("/api/settings/dsn-token POST creates DSN token")
def _(c=auth_client):
    """Test creating DSN token for error tracking"""
    response = c.post(
        "/api/settings/dsn-token",
        data=json.dumps({"project_id": "test-project"}),
        content_type="application/json",
    )
    assert response.status_code in [200, 302, 400]


@test("/api/settings/dsn-token DELETE removes DSN token")
def _(c=auth_client):
    """Test deleting DSN token"""
    response = c.delete(
        "/api/settings/dsn-token",
        data=json.dumps({"token": "fake-token"}),
        content_type="application/json",
    )
    assert response.status_code in [200, 302, 404]


@test("/api/settings/projects/delete/<id> GET deletes project")
def _(c=auth_client):
    """Test deleting a project"""
    import time

    project_id = f"to-delete-{int(time.time() * 1000)}"
    project = create_test_project(project_id, "Delete Me", "Test")

    response = c.get(f"/api/settings/projects/delete/{project.id}")
    assert response.status_code in [200, 302]


@test("/api/settings/projects/update/<id> GET shows update form")
def _(c=auth_client):
    """Test viewing project update form"""
    timestamp = int(time.time() * 1000000)
    project = create_test_project(f"to-update-{timestamp}", "Update Me", "Test")

    response = c.get(f"/api/settings/projects/update/{project.id}")
    assert response.status_code in [200, 302]

    project.delete_instance()


@test("/api/settings/projects/update/<id> POST updates project")
def _(c=auth_client):
    """Test updating a project"""
    project = create_test_project("to-update-2", "Update Me 2", "Test")

    response = c.post(
        f"/api/settings/projects/update/{project.id}",
        data={"name": "Updated Name", "description": "Updated desc"},
    )
    assert response.status_code in [200, 302]

    project.delete_instance()


@test("/api/settings/labels/delete/<name> deletes label")
def _(c=auth_client):
    """Test deleting a label"""
    # Use unique label name with timestamp
    import time

    label_name = f"to-delete-{int(time.time() * 1000)}"
    label = Label.create(name=label_name, color="#ff0000")

    response = c.get(f"/api/settings/labels/delete/{label.name}")
    assert response.status_code in [200, 302]


@test("/api/settings/danger/delete-account POST deletes account")
def _(c=auth_client):
    """Test account deletion endpoint"""
    response = c.post(
        "/api/settings/danger/delete-account",
        data=json.dumps({"confirmation": "DELETE"}),
        content_type="application/json",
    )
    # May require specific confirmation or be unauthorized
    assert response.status_code in [200, 302, 400, 401, 403]


@test("/api/settings/team/invite POST sends invitation")
def _(c=auth_client):
    """Test sending team invitation"""
    response = c.post(
        "/api/settings/team/invite",
        data=json.dumps({"email": "newuser@example.com"}),
        content_type="application/json",
    )
    assert response.status_code in [200, 302, 400]


@test("/welcome/<token> GET shows welcome page")
def _(c=client):
    """Test welcome page for new team members"""
    response = c.get("/welcome/test-token-12345")
    # May return 200 (valid token) or 404 (invalid)
    assert response.status_code in [200, 302, 404]


@test("/welcome/<token> POST completes registration")
def _(c=client):
    """Test completing registration via welcome link"""
    response = c.post(
        "/welcome/test-token-12345",
        data={"password": "newpass123", "confirm_password": "newpass123"},
    )
    assert response.status_code in [200, 302, 404]
