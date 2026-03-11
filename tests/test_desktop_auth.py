"""Tests for desktop handshake and device authentication endpoints."""

from ward import test
from tests.fixtures import client, auth_user
from urllib.parse import unquote
from unittest.mock import patch
import time

from app.utils.models import DeviceToken
from app.utils.path import data_path


@test("/api/desktop/handshake returns broke metadata and challenge token")
def _(c=client):
    response = c.get("/api/desktop/handshake?nonce=abc123")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["product"] == "broke"
    assert payload["nonce_echo"] == "abc123"
    assert payload["challenge_token"]
    assert payload["auth_methods"] == ["device_token"]


@test("/api/desktop/device-login rejects missing or invalid challenge token")
def _(c=client, user=auth_user):
    response = c.post(
        "/api/desktop/device-login",
        json={
            "username": user.username,
            "password": user.password,
            "device_name": "My Laptop",
            "device_id": "device-1",
        },
    )

    assert response.status_code == 400


@test("/api/desktop/device-login issues device token and stores only hash")
def _(c=client, user=auth_user):
    handshake = c.get("/api/desktop/handshake")
    challenge_token = handshake.get_json()["challenge_token"]

    response = c.post(
        "/api/desktop/device-login",
        json={
            "username": user.username,
            "password": user.password,
            "device_name": "My Laptop",
            "device_id": "device-2",
            "challenge_token": challenge_token,
        },
    )

    assert response.status_code == 200
    payload = response.get_json()

    assert payload["device_token"]
    token_row = DeviceToken.get(DeviceToken.device_id == "device-2")
    assert token_row.token_hash
    assert token_row.token_hash != payload["device_token"]


@test("/api/desktop/session restores cookie session from valid device token")
def _(c=client, user=auth_user):
    handshake = c.get("/api/desktop/handshake")
    challenge_token = handshake.get_json()["challenge_token"]

    login = c.post(
        "/api/desktop/device-login",
        json={
            "username": user.username,
            "password": user.password,
            "device_name": "Desktop",
            "device_id": "device-restore",
            "challenge_token": challenge_token,
        },
    )
    device_token = login.get_json()["device_token"]

    restore = c.post("/api/desktop/session", json={"device_token": device_token})
    assert restore.status_code == 200

    protected = c.get("/settings", follow_redirects=False)
    assert protected.status_code == 302
    assert "/settings/profile" in protected.location


@test("/api/desktop/bootstrap returns backend metadata for this instance")
def _(c=client):
    response = c.get("/api/desktop/bootstrap")
    assert response.status_code == 200

    payload = response.get_json()
    assert payload["product"] == "broke"
    assert payload["backend_url"].startswith("http")
    assert payload["handshake_url"].endswith("/api/desktop/handshake")


@test("/desktop/download redirects with bootstrap url for this backend")
def _(c=client):
    response = c.get("/desktop/download", follow_redirects=False)
    assert response.status_code == 302
    assert "bootstrap=" in response.location

    decoded = unquote(response.location)
    assert "/api/desktop/bootstrap" in decoded


@test("/desktop/download serves local installer when configured")
def _(c=client):
    filename = f"broke-desktop-{int(time.time() * 1000000)}.dmg"
    installer_path = data_path("downloads", filename)
    installer_path.parent.mkdir(parents=True, exist_ok=True)
    installer_path.write_bytes(b"desktop-installer-bytes")

    try:
        with patch.dict("os.environ", {"BROKE_DESKTOP_INSTALLER_PATH": str(installer_path)}):
            response = c.get("/desktop/download", follow_redirects=False)

        assert response.status_code == 200
        assert response.data == b"desktop-installer-bytes"
        assert "attachment" in (response.headers.get("Content-Disposition") or "")
    finally:
        if installer_path.exists():
            installer_path.unlink()
