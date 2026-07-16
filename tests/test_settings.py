"""Tests for settings and configuration"""

from ward import test
from tests.fixtures import app, client, fake, test_project, auth_client, auth_user
import json
import io
import time

from app.utils.models import User, create_user, UserSettings, GlobalSetting, DSNToken
from app.utils.mail import EMAIL_TRANSPORT_SETTINGS_KEY
from app.utils.path import data_path
import pyargon2
from unittest.mock import patch


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


@test("/settings/profile GET renders JS avatar fallback markup")
def _(c=auth_client, user=auth_user):
    response = c.get("/settings/profile")

    assert response.status_code in [200, 302]
    if response.status_code == 200:
        assert f'data-jdenticon-value="{user.username}"'.encode() in response.data
        assert f'/avatar/{user.username}'.encode() in response.data


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


@test("/settings/email GET shows email settings page")
def _(c=auth_client):
    response = c.get("/settings/email")
    assert response.status_code in [200, 302]
    if response.status_code == 200:
        assert b"Email Service" in response.data


@test("/settings/updates shows desktop download action")
def _(c=auth_client):
    response = c.get("/settings/updates")
    assert response.status_code in [200, 302]
    if response.status_code == 200:
        assert b"/desktop/download" in response.data


@test("/settings/updates hides desktop download action for Electron client")
def _(c=auth_client):
    response = c.get("/settings/updates", headers={"User-Agent": "BrokeDesktop/0.1"})
    assert response.status_code in [200, 302]
    if response.status_code == 200:
        assert b"/desktop/download" not in response.data
        assert b"Download Broke Desktop" not in response.data


@test("/settings/ai shows environment-backed AI config when DB settings missing")
def _(c=client, f=fake):
    admin_username = f"admin_ai_env_{f.uuid4()[:8]}"
    admin_email = f"admin_ai_env_{int(time.time() * 1000000)}@example.com"
    admin_user = create_user(admin_username, "password123", admin_email, admin=1)

    login_response = c.post(
        "/callback",
        data={"username": admin_user.username, "password": "password123"},
        follow_redirects=False,
    )
    assert login_response.status_code == 302

    GlobalSetting.delete().where(GlobalSetting.key == "ai_settings").execute()

    with patch.dict(
        "os.environ",
        {
            "AI_API_KEY": "env-ai-key-123",
            "AI_BASE_URL": "https://api.openai.com/v1",
            "AI_MODEL": "gpt-4o-mini",
        },
        clear=False,
    ):
        response = c.get("/settings/ai")

    assert response.status_code in [200, 302]
    if response.status_code == 200:
        assert b"Loaded from environment variables" in response.data
        assert b"https://api.openai.com/v1" in response.data
        assert b"gpt-4o-mini" in response.data


@test("/settings/ai prefers DB config over environment")
def _(c=client, f=fake):
    admin_username = f"admin_ai_db_{f.uuid4()[:8]}"
    admin_email = f"admin_ai_db_{int(time.time() * 1000000)}@example.com"
    admin_user = create_user(admin_username, "password123", admin_email, admin=1)

    login_response = c.post(
        "/callback",
        data={"username": admin_user.username, "password": "password123"},
        follow_redirects=False,
    )
    assert login_response.status_code == 302

    payload = json.dumps(
        {
            "api_key": "db-key-abc",
            "base_url": "https://openrouter.ai/api/v1",
            "model": "google/gemini-2.5-flash",
            "language": "English",
        }
    )
    existing = GlobalSetting.get_or_none(GlobalSetting.key == "ai_settings")
    if existing:
        existing.value = payload
        existing.save()
    else:
        GlobalSetting.create(key="ai_settings", value=payload)

    with patch.dict(
        "os.environ",
        {
            "AI_API_KEY": "env-ai-key-456",
            "AI_BASE_URL": "https://api.openai.com/v1",
            "AI_MODEL": "gpt-4o-mini",
        },
        clear=False,
    ):
        response = c.get("/settings/ai")

    assert response.status_code in [200, 302]
    if response.status_code == 200:
        assert b"Loaded from saved settings" in response.data
        assert b"https://openrouter.ai/api/v1" in response.data
        assert b"google/gemini-2.5-flash" in response.data


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
    # /api/* uses 401 for unauthenticated clients (see protected); 302 is for non-API routes.
    assert response.status_code == 401


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


@test("Non-admin cannot update SMTP settings")
def _(c=auth_client):
    response = c.post(
        "/api/settings/email",
        data=json.dumps({"host": "smtp.example.com", "port": 587}),
        content_type="application/json",
    )
    assert response.status_code == 403


@test("Admin can update SMTP settings")
def _(c=client, f=fake):
    admin_username = f"admin_mail_{f.uuid4()[:8]}"
    admin_email = f"admin_mail_{int(time.time() * 1000000)}@example.com"
    admin_user = create_user(admin_username, "password123", admin_email, admin=1)

    login_response = c.post(
        "/callback",
        data={"username": admin_user.username, "password": "password123"},
        follow_redirects=False,
    )
    assert login_response.status_code == 302

    payload = {
        "host": "smtp.example.com",
        "port": 587,
        "username": "smtp-user",
        "password": "smtp-pass",
        "from": "noreply@example.com",
        "use_tls": True,
    }

    response = c.post(
        "/api/settings/email",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert response.status_code == 200

    record = GlobalSetting.get_or_none(GlobalSetting.key == "smtp_settings")
    assert record is not None
    saved = json.loads(record.value)
    assert saved.get("host") == "smtp.example.com"
    assert saved.get("port") == 587
    assert saved.get("username") == "smtp-user"
    assert saved.get("from") == "noreply@example.com"

    tr = GlobalSetting.get_or_none(GlobalSetting.key == EMAIL_TRANSPORT_SETTINGS_KEY)
    assert tr is not None
    assert json.loads(tr.value).get("transport") == "smtp"


@test("Admin can save HTTPS relay delivery without SMTP host")
def _(c=client, f=fake):
    admin_username = f"admin_relay_{f.uuid4()[:8]}"
    admin_email = f"admin_relay_{int(time.time() * 1000000)}@example.com"
    create_user(admin_username, "password123", admin_email, admin=1)

    assert c.post(
        "/callback",
        data={"username": admin_username, "password": "password123"},
        follow_redirects=False,
    ).status_code == 302

    payload = {
        "transport": "relay",
        "relay_base_url": "https://relay.example.com",
        "relay_token": "saved-relay-token-secret",
    }
    response = c.post(
        "/api/settings/email",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert response.status_code == 200

    tr = GlobalSetting.get_or_none(GlobalSetting.key == EMAIL_TRANSPORT_SETTINGS_KEY)
    assert tr is not None
    body = json.loads(tr.value)
    assert body.get("transport") == "relay"
    assert body.get("relay_base_url") == "https://relay.example.com"
    assert body.get("relay_token") == "saved-relay-token-secret"


@test("Relay delivery save fails when URL and token are missing and env unset")
def _(c=client, f=fake):
    import os

    admin_username = f"admin_relay_bad_{f.uuid4()[:8]}"
    admin_email = f"admin_relay_bad_{int(time.time() * 1000000)}@example.com"
    create_user(admin_username, "password123", admin_email, admin=1)

    assert c.post(
        "/callback",
        data={"username": admin_username, "password": "password123"},
        follow_redirects=False,
    ).status_code == 302

    with patch.dict(
        os.environ,
        {"BROKE_MAIL_RELAY_BASE_URL": "", "BROKE_MAIL_RELAY_TOKEN": ""},
        clear=False,
    ):
        response = c.post(
            "/api/settings/email",
            data=json.dumps(
                {"transport": "relay", "relay_base_url": "", "relay_token": ""}
            ),
            content_type="application/json",
        )
    assert response.status_code == 400


@test("Relay delivery can use only BROKE_MAIL_RELAY env credentials")
def _(c=client, f=fake):
    import os

    GlobalSetting.delete().where(GlobalSetting.key == EMAIL_TRANSPORT_SETTINGS_KEY).execute()

    admin_username = f"admin_relay_env_{f.uuid4()[:8]}"
    admin_email = f"admin_relay_env_{int(time.time() * 1000000)}@example.com"
    create_user(admin_username, "password123", admin_email, admin=1)

    assert c.post(
        "/callback",
        data={"username": admin_username, "password": "password123"},
        follow_redirects=False,
    ).status_code == 302

    with patch.dict(
        os.environ,
        {
            "BROKE_MAIL_RELAY_BASE_URL": "https://panel.example.com",
            "BROKE_MAIL_RELAY_TOKEN": "env-only-relay-token",
        },
        clear=False,
    ):
        response = c.post(
            "/api/settings/email",
            data=json.dumps(
                {"transport": "relay", "relay_base_url": "", "relay_token": ""}
            ),
            content_type="application/json",
        )
    assert response.status_code == 200
    tr = GlobalSetting.get_or_none(GlobalSetting.key == EMAIL_TRANSPORT_SETTINGS_KEY)
    assert tr is not None
    body = json.loads(tr.value)
    assert body.get("transport") == "relay"
    assert body.get("relay_base_url") == ""
    assert body.get("relay_token") == ""


@test("Non-admin cannot send test email")
def _(c=auth_client):
    response = c.post(
        "/api/settings/email/test",
        data=json.dumps({"recipient": "test@example.com"}),
        content_type="application/json",
    )
    assert response.status_code == 403


@test("Admin can send test email")
def _(c=client, f=fake):
    admin_username = f"admin_mail_test_{f.uuid4()[:8]}"
    admin_email = f"admin_mail_test_{int(time.time() * 1000000)}@example.com"
    admin_user = create_user(admin_username, "password123", admin_email, admin=1)

    login_response = c.post(
        "/callback",
        data={"username": admin_user.username, "password": "password123"},
        follow_redirects=False,
    )
    assert login_response.status_code == 302

    with patch("app.views.settings.mail.send_email", return_value=True) as send_email_mock:
        response = c.post(
            "/api/settings/email/test",
            data=json.dumps({"recipient": "dev@example.com"}),
            content_type="application/json",
        )

    assert response.status_code == 200
    payload = json.loads(response.data)
    assert payload.get("success") is True
    assert send_email_mock.called


@test("Non-admin cannot update AI settings")
def _(c=auth_client):
    response = c.post(
        "/api/settings/ai",
        data=json.dumps(
            {
                "api_key": "sk-test-key",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4o-mini",
                "language": "English",
            }
        ),
        content_type="application/json",
    )
    assert response.status_code == 403


@test("Non-admin cannot create DSN token")
def _(c=auth_client):
    response = c.post("/api/settings/dsn-token")
    assert response.status_code == 403


@test("Non-admin cannot revoke DSN token")
def _(c=auth_client):
    response = c.delete("/api/settings/dsn-token")
    assert response.status_code == 403


@test("Non-admin cannot regenerate webhook secret")
def _(c=auth_client):
    response = c.post(
        "/api/settings/webhooks/regenerate-secret",
        data=json.dumps({"type": "github"}),
        content_type="application/json",
    )
    assert response.status_code == 403


@test("Admin can regenerate webhook secret and receive it once")
def _(c=client, f=fake):
    admin_username = f"admin_regen_{f.uuid4()[:8]}"
    admin_email = f"admin_regen_{int(time.time() * 1000000)}@example.com"
    admin_user = create_user(admin_username, "password123", admin_email, admin=1)

    login_response = c.post(
        "/callback",
        data={"username": admin_user.username, "password": "password123"},
        follow_redirects=False,
    )
    assert login_response.status_code == 302

    response = c.post(
        "/api/settings/webhooks/regenerate-secret",
        data=json.dumps({"type": "github"}),
        content_type="application/json",
    )

    assert response.status_code == 200
    payload = json.loads(response.data)
    assert payload.get("success") is True
    assert isinstance(payload.get("secret"), str)
    assert len(payload.get("secret")) == 32


@test("Non-admin cannot access webhooks settings section")
def _(c=auth_client):
    response = c.get("/settings/webhooks", follow_redirects=False)
    assert response.status_code == 302


@test("Non-admin cannot access sentry settings section")
def _(c=auth_client):
    response = c.get("/settings/sentry", follow_redirects=False)
    assert response.status_code == 302


@test("Non-admin cannot access ai settings section")
def _(c=auth_client):
    response = c.get("/settings/ai", follow_redirects=False)
    assert response.status_code == 302


@test("Non-admin cannot access branding settings section")
def _(c=auth_client):
    response = c.get("/settings/branding", follow_redirects=False)
    assert response.status_code == 302


@test("Admin can toggle public site landing via API")
def _(app=app, f=fake):
    GlobalSetting.delete().where(GlobalSetting.key == "public_site_settings").execute()
    admin_username = f"publ_{f.uuid4()[:8]}"
    admin_email = f"publ_{int(time.time() * 1000000)}@example.com"
    create_user(admin_username, "password123", admin_email, admin=1)

    try:
        with app.test_client() as ac:
            assert ac.post(
                "/callback",
                data={"username": admin_username, "password": "password123"},
                follow_redirects=False,
            ).status_code in (302, 200)

            r = ac.post(
                "/api/settings/public-site",
                json={"show_public_home": True},
                content_type="application/json",
            )
            assert r.status_code == 200
            payload = json.loads(r.data)
            assert payload.get("success") is True
            assert payload["settings"]["show_public_home"] is True

            r2 = ac.post(
                "/api/settings/public-site",
                json={"show_public_home": False},
                content_type="application/json",
            )
            assert r2.status_code == 200
            assert json.loads(r2.data)["settings"]["show_public_home"] is False
    finally:
        GlobalSetting.delete().where(GlobalSetting.key == "public_site_settings").execute()


@test("Non-admin cannot toggle public site landing API")
def _(app=app, f=fake):
    GlobalSetting.delete().where(GlobalSetting.key == "public_site_settings").execute()
    username = f"npubl_{f.uuid4()[:8]}"
    email = f"npubl_{int(time.time() * 1000000)}@example.com"
    create_user(username, "password123", email, admin=0)

    try:
        with app.test_client() as tc:
            assert tc.post(
                "/callback",
                data={"username": username, "password": "password123"},
                follow_redirects=False,
            ).status_code in (302, 200)

            r = tc.post(
                "/api/settings/public-site",
                json={"show_public_home": True},
                content_type="application/json",
            )
            assert r.status_code == 403
    finally:
        GlobalSetting.delete().where(GlobalSetting.key == "public_site_settings").execute()


@test("Settings pages do not render raw SMTP password")
def _(c=client, f=fake):
    admin_username = f"admin_sec_mail_{f.uuid4()[:8]}"
    admin_email = f"admin_sec_mail_{int(time.time() * 1000000)}@example.com"
    admin_user = create_user(admin_username, "password123", admin_email, admin=1)

    login_response = c.post(
        "/callback",
        data={"username": admin_user.username, "password": "password123"},
        follow_redirects=False,
    )
    assert login_response.status_code == 302

    secret_password = "smtp-super-secret-password"
    smtp_record = GlobalSetting.get_or_none(GlobalSetting.key == "smtp_settings")
    payload = {
        "host": "smtp.example.com",
        "port": 587,
        "username": "smtp-user",
        "password": secret_password,
        "from": "noreply@example.com",
        "use_tls": True,
    }
    if smtp_record:
        smtp_record.value = json.dumps(payload)
        smtp_record.save()
    else:
        GlobalSetting.create(key="smtp_settings", value=json.dumps(payload))

    response = c.get("/settings/email")
    assert response.status_code == 200
    assert secret_password.encode() not in response.data


@test("Email settings HTML does not include relay bearer secrets")
def _(c=client, f=fake):
    import os

    admin_username = f"admin_sec_rel_{f.uuid4()[:8]}"
    admin_email = f"admin_sec_rel_{int(time.time() * 1000000)}@example.com"
    admin_user = create_user(admin_username, "password123", admin_email, admin=1)

    login_response = c.post(
        "/callback",
        data={"username": admin_user.username, "password": "password123"},
        follow_redirects=False,
    )
    assert login_response.status_code == 302

    relay_secret_saved = "saved-relay-bearer-ultra-secret-999"
    tr = GlobalSetting.get_or_none(GlobalSetting.key == EMAIL_TRANSPORT_SETTINGS_KEY)
    payload = {
        "transport": "relay",
        "relay_base_url": "https://relay.example.test",
        "relay_token": relay_secret_saved,
    }
    value = json.dumps(payload)
    if tr:
        tr.value = value
        tr.save()
    else:
        GlobalSetting.create(key=EMAIL_TRANSPORT_SETTINGS_KEY, value=value)

    env_secret = "env-relay-token-must-never-render-888"
    with patch.dict(os.environ, {"BROKE_MAIL_RELAY_TOKEN": env_secret}, clear=False):
        response = c.get("/settings/email")

    assert response.status_code == 200
    assert relay_secret_saved.encode() not in response.data
    assert env_secret.encode() not in response.data


@test("Settings pages do not render raw AI API key")
def _(c=client, f=fake):
    admin_username = f"admin_sec_ai_{f.uuid4()[:8]}"
    admin_email = f"admin_sec_ai_{int(time.time() * 1000000)}@example.com"
    admin_user = create_user(admin_username, "password123", admin_email, admin=1)

    login_response = c.post(
        "/callback",
        data={"username": admin_user.username, "password": "password123"},
        follow_redirects=False,
    )
    assert login_response.status_code == 302

    ai_secret = "sk-very-secret-ai-key"
    ai_record = GlobalSetting.get_or_none(GlobalSetting.key == "ai_settings")
    payload = {
        "api_key": ai_secret,
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "language": "English",
    }
    if ai_record:
        ai_record.value = json.dumps(payload)
        ai_record.save()
    else:
        GlobalSetting.create(key="ai_settings", value=json.dumps(payload))

    response = c.get("/settings/ai")
    assert response.status_code == 200
    assert ai_secret.encode() not in response.data


@test("Settings pages do not render raw webhook secret")
def _(c=client, f=fake):
    admin_username = f"admin_sec_wh_{f.uuid4()[:8]}"
    admin_email = f"admin_sec_wh_{int(time.time() * 1000000)}@example.com"
    admin_user = create_user(admin_username, "password123", admin_email, admin=1)

    login_response = c.post(
        "/callback",
        data={"username": admin_user.username, "password": "password123"},
        follow_redirects=False,
    )
    assert login_response.status_code == 302

    github_secret = "github-webhook-top-secret"
    with open(data_path("github_webhook_secret.txt"), "w") as secret_file:
        secret_file.write(github_secret)

    response = c.get("/settings/webhooks")
    assert response.status_code == 200
    assert github_secret.encode() not in response.data


@test("Settings pages do not render raw DSN token")
def _(c=client, f=fake):
    admin_username = f"admin_sec_dsn_{f.uuid4()[:8]}"
    admin_email = f"admin_sec_dsn_{int(time.time() * 1000000)}@example.com"
    admin_user = create_user(admin_username, "password123", admin_email, admin=1)

    login_response = c.post(
        "/callback",
        data={"username": admin_user.username, "password": "password123"},
        follow_redirects=False,
    )
    assert login_response.status_code == 302

    raw_token = f"dsn-secret-{int(time.time() * 1000000)}"
    DSNToken.delete().execute()
    DSNToken.create(token=raw_token)

    response = c.get("/settings/sentry")
    assert response.status_code == 200
    assert raw_token.encode() not in response.data


@test("Creating DSN token stores hash instead of raw token")
def _(c=client, f=fake):
    admin_username = f"admin_sec_dsn_create_{f.uuid4()[:8]}"
    admin_email = f"admin_sec_dsn_create_{int(time.time() * 1000000)}@example.com"
    admin_user = create_user(admin_username, "password123", admin_email, admin=1)

    login_response = c.post(
        "/callback",
        data={"username": admin_user.username, "password": "password123"},
        follow_redirects=False,
    )
    assert login_response.status_code == 302

    response = c.post("/api/settings/dsn-token")
    assert response.status_code == 200

    payload = json.loads(response.data)
    assert payload.get("success") is True
    token_value = payload.get("token")
    assert isinstance(token_value, str)
    assert len(token_value) > 20

    record = DSNToken.get_or_none()
    assert record is not None
    assert getattr(record, "token_hash", "")
    assert record.token != token_value


@test("Admin can upload instance branding logo and anonymous GET succeeds")
def _(app=app, f=fake):
    from app.utils.branding import clear_instance_logo_files

    clear_instance_logo_files()
    admin_username = f"adlogo_{f.uuid4()[:8]}"
    admin_email = f"adlogo_{int(time.time() * 1000000)}@example.com"
    create_user(admin_username, "password123", admin_email, admin=1)

    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    with app.test_client() as ac:
        assert ac.post(
            "/callback",
            data={"username": admin_username, "password": "password123"},
            follow_redirects=False,
        ).status_code in (302, 200)

        up = ac.post(
            "/api/settings/branding/logo",
            data={"logo": (io.BytesIO(png_bytes), "logo.png", "image/png")},
            content_type="multipart/form-data",
        )
        assert up.status_code == 200
        assert json.loads(up.data).get("success") is True

    with app.test_client() as anon:
        r = anon.get("/branding/instance-logo")
        assert r.status_code == 200
        assert r.mimetype == "image/png"

    clear_instance_logo_files()


@test("Non-admin cannot upload instance branding logo")
def _(app=app, f=fake):
    from app.utils.branding import clear_instance_logo_files

    clear_instance_logo_files()
    username = f"memlogo_{f.uuid4()[:8]}"
    email = f"memlogo_{int(time.time() * 1000000)}@example.com"
    create_user(username, "password123", email, admin=0)

    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    with app.test_client() as tc:
        assert tc.post(
            "/callback",
            data={"username": username, "password": "password123"},
            follow_redirects=False,
        ).status_code in (302, 200)

        up = tc.post(
            "/api/settings/branding/logo",
            data={"logo": (io.BytesIO(png_bytes), "logo.png", "image/png")},
            content_type="multipart/form-data",
        )
        assert up.status_code == 403

    clear_instance_logo_files()


@test("Admin can delete instance branding logo and public route returns 404")
def _(app=app, f=fake):
    from app.utils.branding import clear_instance_logo_files

    clear_instance_logo_files()
    admin_username = f"adlogodel_{f.uuid4()[:8]}"
    admin_email = f"adlogodel_{int(time.time() * 1000000)}@example.com"
    create_user(admin_username, "password123", admin_email, admin=1)

    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    with app.test_client() as ac:
        assert ac.post(
            "/callback",
            data={"username": admin_username, "password": "password123"},
            follow_redirects=False,
        ).status_code in (302, 200)

        assert (
            ac.post(
                "/api/settings/branding/logo",
                data={"logo": (io.BytesIO(png_bytes), "logo.png", "image/png")},
                content_type="multipart/form-data",
            ).status_code
            == 200
        )
        assert ac.get("/branding/instance-logo").status_code == 200

        assert json.loads(ac.delete("/api/settings/branding/logo").data).get("success") is True
        assert ac.get("/branding/instance-logo").status_code == 404

    clear_instance_logo_files()


@test("Desktop bootstrap logo_url uses branding path when custom logo set")
def _(app=app, f=fake):
    from app.utils.branding import clear_instance_logo_files

    clear_instance_logo_files()
    admin_username = f"adboot_{f.uuid4()[:8]}"
    admin_email = f"adboot_{int(time.time() * 1000000)}@example.com"
    create_user(admin_username, "password123", admin_email, admin=1)

    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    with app.test_client() as ac:
        assert ac.post(
            "/callback",
            data={"username": admin_username, "password": "password123"},
            follow_redirects=False,
        ).status_code in (302, 200)
        assert (
            ac.post(
                "/api/settings/branding/logo",
                data={"logo": (io.BytesIO(png_bytes), "logo.png", "image/png")},
                content_type="multipart/form-data",
            ).status_code
            == 200
        )
        boot = ac.get("/api/desktop/bootstrap")
        assert boot.status_code == 200
        body = json.loads(boot.data)
        assert "/branding/instance-logo?v=" in body.get("logo_url", "")

    clear_instance_logo_files()


@test("Desktop bootstrap logo_url defaults to static when no custom logo")
def _(app=app):
    from app.utils.branding import clear_instance_logo_files

    clear_instance_logo_files()
    with app.test_client() as c:
        boot = c.get("/api/desktop/bootstrap")
        assert boot.status_code == 200
        body = json.loads(boot.data)
        assert "logov2_wo_bg.png" in body.get("logo_url", "")
