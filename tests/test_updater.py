"""Tests for auto-update checker functionality"""

from ward import test
from tests.fixtures import client, auth_client, auth_user, app
from unittest.mock import patch, MagicMock
import json

from app.utils.updater import check_for_update, get_update_info, is_auto_check_enabled, set_auto_check_enabled
from app.utils.models import GlobalSetting


@test("check_for_update detects newer version")
def _():
    """Test that check_for_update correctly identifies a newer version"""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = '[project]\nversion = "99.0.0"\n'
    mock_response.raise_for_status = MagicMock()

    with patch("app.utils.updater.requests.get", return_value=mock_response):
        info = check_for_update()

    assert info is not None
    assert info["available"] is True
    assert info["latest_version"] == "99.0.0"
    assert "checked_at" in info


@test("check_for_update reports no update when on latest")
def _():
    """Test that check_for_update correctly reports no update needed"""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = '[project]\nversion = "0.0.1"\n'
    mock_response.raise_for_status = MagicMock()

    with patch("app.utils.updater.requests.get", return_value=mock_response):
        info = check_for_update()

    assert info is not None
    assert info["available"] is False


@test("check_for_update handles API failure gracefully")
def _():
    """Test graceful handling when GitHub API is unreachable"""
    with patch("app.utils.updater.requests.get", side_effect=ConnectionError("Network unreachable")):
        info = check_for_update()

    assert info is not None
    assert info["available"] is False
    assert "error" in info


@test("get_update_info returns None when no data cached")
def _():
    """Test get_update_info returns None when nothing is cached"""
    # Clear any existing update info
    GlobalSetting.delete().where(GlobalSetting.key == "update_info").execute()
    info = get_update_info()
    assert info is None


@test("get_update_info returns cached data")
def _():
    """Test get_update_info returns previously stored data"""
    test_info = {"available": True, "latest_version": "2.0.0", "checked_at": 1234567890}
    try:
        setting = GlobalSetting.get(GlobalSetting.key == "update_info")
        setting.value = json.dumps(test_info)
        setting.save()
    except GlobalSetting.DoesNotExist:
        GlobalSetting.create(key="update_info", value=json.dumps(test_info))

    info = get_update_info()
    assert info is not None
    assert info["available"] is True
    assert info["latest_version"] == "2.0.0"


@test("auto_check toggle works correctly")
def _():
    """Test enabling and disabling auto-check"""
    set_auto_check_enabled(False)
    assert is_auto_check_enabled() is False

    set_auto_check_enabled(True)
    assert is_auto_check_enabled() is True


@test("/settings/updates GET shows updates page")
def _(c=auth_client):
    """Test updates settings page renders"""
    response = c.get("/settings/updates")
    assert response.status_code in [200, 302]


@test("/api/settings/updates/check POST triggers check")
def _(c=auth_client):
    """Test manual update check endpoint"""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = '[project]\nversion = "0.1.5"\n'
    mock_response.raise_for_status = MagicMock()

    with patch("app.utils.updater.requests.get", return_value=mock_response):
        response = c.post("/api/settings/updates/check")

    assert response.status_code == 200
    data = json.loads(response.data)
    assert "available" in data


@test("/api/settings/updates/toggle POST toggles auto-check")
def _(c=auth_client):
    """Test toggle auto-check endpoint"""
    response = c.post(
        "/api/settings/updates/toggle",
        data=json.dumps({"enabled": False}),
        content_type="application/json",
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["success"] is True
    assert data["enabled"] is False
