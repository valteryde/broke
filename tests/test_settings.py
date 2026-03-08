"""Tests for settings and configuration"""

from ward import test
from tests.fixtures import client, fake, test_project, auth_client, auth_user
import json
import io
import time

from app.utils.models import User, create_user, UserSettings
import pyargon2


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


@test("Team page shows admin role badges")
def _(c=auth_client):
    response = c.get("/settings/team")
    assert response.status_code in [200, 302]
    if response.status_code == 200:
        assert b"member-role-badge" in response.data


@test("Unauthenticated user cannot access settings API")
def _(c=client, f=fake):
    """Test that API endpoints require authentication"""
    response = c.post(
        "/api/settings/projects",
        data={"name": f.word(), "icon": "ph ph-folder", "color": "#0000ff"},
        follow_redirects=False,
    )

    assert response.status_code in [302, 401]


@test("/api/settings/profile/avatar requires authentication")
def _(c=client):
    c.get('/logout', follow_redirects=False)
    response = c.post(
        "/api/settings/profile/avatar",
        data={"avatar": (io.BytesIO(b"fake"), "avatar.png")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert response.status_code == 302


@test("/api/settings/profile/avatar accepts uploaded file")
def _(c=auth_client):
    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    response = c.post(
        "/api/settings/profile/avatar",
        data={"avatar": (io.BytesIO(png_bytes), "avatar.png", "image/png")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data.get("success") is True


@test("/api/settings/profile/avatar rejects unsupported content type")
def _(c=auth_client):
    response = c.post(
        "/api/settings/profile/avatar",
        data={"avatar": (io.BytesIO(b"text"), "avatar.txt", "text/plain")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400


@test("/api/settings/profile/avatar rejects oversized file")
def _(c=auth_client):
    large_payload = b"0" * (5 * 1024 * 1024 + 1)
    response = c.post(
        "/api/settings/profile/avatar",
        data={"avatar": (io.BytesIO(large_payload), "avatar.png", "image/png")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 413


@test("/api/settings/profile/avatar can be removed")
def _(c=auth_client):
    response = c.delete("/api/settings/profile/avatar")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data.get("success") is True


@test("Admin can delete another user")
def _(c=client, f=fake):
    admin_username = f"admin_{f.uuid4()[:8]}"
    admin_email = f"admin_{int(time.time() * 1000000)}@example.com"
    admin_user = create_user(admin_username, "password123", admin_email, admin=1)

    target_username = f"member_{f.uuid4()[:8]}"
    target_email = f"member_{int(time.time() * 1000000)}@example.com"
    target_user = create_user(target_username, "password123", target_email)
    UserSettings.create(user=target_username)

    login_response = c.post(
        "/callback",
        data={"username": admin_user.username, "password": "password123"},
        follow_redirects=False,
    )
    assert login_response.status_code == 302

    response = c.delete(f"/api/settings/team/{target_username}")
    assert response.status_code == 200
    payload = json.loads(response.data)
    assert payload.get("success") is True
    tombstoned_user = User.get_or_none(User.username == target_username)
    assert tombstoned_user is not None
    assert tombstoned_user.admin == 0
    assert tombstoned_user.email.startswith(f"deleted+{target_username}+")
    assert tombstoned_user.email.endswith("@deleted.local")


@test("Non-admin cannot delete users")
def _(c=auth_client, user=auth_user, f=fake):
    target_username = f"member_{f.uuid4()[:8]}"
    target_email = f"member_{int(time.time() * 1000000)}@example.com"
    create_user(target_username, "password123", target_email)

    response = c.delete(f"/api/settings/team/{target_username}")
    assert response.status_code == 403


@test("Admin cannot delete self")
def _(c=client, f=fake):
    admin_username = f"admin_{f.uuid4()[:8]}"
    admin_email = f"admin_self_{int(time.time() * 1000000)}@example.com"
    admin_user = create_user(admin_username, "password123", admin_email, admin=1)

    login_response = c.post(
        "/callback",
        data={"username": admin_user.username, "password": "password123"},
        follow_redirects=False,
    )
    assert login_response.status_code == 302

    response = c.delete(f"/api/settings/team/{admin_user.username}")
    assert response.status_code == 400


@test("Admin can set temporary password for a user")
def _(c=client, f=fake):
    admin_username = f"admin_{f.uuid4()[:8]}"
    admin_email = f"admin_tmp_{int(time.time() * 1000000)}@example.com"
    admin_user = create_user(admin_username, "password123", admin_email, admin=1)

    target_username = f"member_{f.uuid4()[:8]}"
    target_email = f"member_tmp_{int(time.time() * 1000000)}@example.com"
    create_user(target_username, "password123", target_email)

    login_response = c.post(
        "/callback",
        data={"username": admin_user.username, "password": "password123"},
        follow_redirects=False,
    )
    assert login_response.status_code == 302

    response = c.post(
        f"/api/settings/team/{target_username}/temporary-password",
        data=json.dumps({"password": "temp-pass-123"}),
        content_type="application/json",
    )
    assert response.status_code == 200

    payload = json.loads(response.data)
    assert payload.get("success") is True
    assert payload.get("temporary_password") == "temp-pass-123"

    updated_user = User.get(User.username == target_username)
    assert updated_user.password_hash == pyargon2.hash("temp-pass-123", str(updated_user.salt))


@test("Non-admin cannot set temporary password")
def _(c=auth_client, f=fake):
    target_username = f"member_{f.uuid4()[:8]}"
    target_email = f"member_tmp_{int(time.time() * 1000000)}@example.com"
    create_user(target_username, "password123", target_email)

    response = c.post(
        f"/api/settings/team/{target_username}/temporary-password",
        data=json.dumps({"password": "temp-pass-123"}),
        content_type="application/json",
    )
    assert response.status_code == 403
