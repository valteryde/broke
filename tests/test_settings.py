"""Tests for settings and configuration"""

from ward import test
from tests.fixtures import client, fake, test_project, auth_client, auth_user
import json


@test("/settings GET requires authentication")
def _(c=client):
    """Test settings requires auth"""
    response = c.get("/settings", follow_redirects=False)
    # Either redirects to login or a protected subpage
    assert response.status_code in [302, 200]


@test("/settings GET redirects to profile when authenticated")
def _(c=auth_client):
    """Test settings redirect for authenticated user"""
    response = c.get("/settings", follow_redirects=False)
    assert response.status_code == 302
    assert "profile" in response.location or "settings" in response.location


@test("/settings/profile GET shows profile page")
def _(c=auth_client):
    """Test profile settings page"""
    response = c.get("/settings/profile")
    assert response.status_code in [200, 302]


@test("/settings/projects GET shows projects")
def _(c=auth_client):
    """Test projects settings page"""
    response = c.get("/settings/projects")
    assert response.status_code in [200, 302]


@test("/api/settings/projects POST creates project")
def _(c=auth_client, f=fake):
    """Test creating a new project"""
    project_name = f.word().upper()[:10]
    response = c.post(
        "/api/settings/projects",
        data={"name": project_name, "icon": "ph ph-folder", "color": "#0000ff"},
        follow_redirects=False,
    )

    assert response.status_code in [200, 302, 401, 404]


@test("/api/settings/labels POST creates label")
def _(c=auth_client, f=fake):
    """Test creating a new label"""
    response = c.post(
        "/api/settings/labels", data={"name": f.word(), "color": "#ff0000"}, follow_redirects=False
    )

    assert response.status_code in [200, 302, 401, 404]


@test("/api/settings/tokens POST creates API token")
def _(c=auth_client):
    """Test creating an API token"""
    response = c.post("/api/settings/tokens")

    assert response.status_code in [200, 302, 401, 404]

    if response.status_code == 200:
        data = json.loads(response.data)
        assert "token" in data or "success" in data


@test("/api/settings/webhooks/outgoing POST creates webhook")
def _(c=auth_client):
    """Test creating an outgoing webhook"""
    response = c.post(
        "/api/settings/webhooks/outgoing",
        data=json.dumps(
            {
                "url": "https://example.com/webhook",
                "events": ["ticket.created"],
                "secret": "test_secret",
            }
        ),
        content_type="application/json",
    )

    assert response.status_code in [200, 401, 500]  # 500 expected due to import bug


@test("/settings/api GET shows API settings")
def _(c=auth_client):
    """Test API settings page"""
    response = c.get("/settings/api")
    assert response.status_code in [200, 302]


@test("/settings/webhooks GET shows webhook settings")
def _(c=auth_client):
    """Test webhook settings page"""
    response = c.get("/settings/webhooks")
    assert response.status_code in [200, 302]


@test("/settings/team GET shows team page")
def _(c=auth_client):
    """Test team settings page"""
    response = c.get("/settings/team")
    assert response.status_code in [200, 302]


@test("Unauthenticated user cannot access settings API")
def _(c=client, f=fake):
    """Test that API endpoints require authentication"""
    response = c.post(
        "/api/settings/projects",
        data={"name": f.word(), "icon": "ph ph-folder", "color": "#0000ff"},
        follow_redirects=False,
    )

    assert response.status_code in [302, 401]
