"""
Auto-Update Checker and Sidecar Client

Checks GitHub Releases for newer versions of Broke and communicates
with the updater sidecar to pull + restart when requested.
"""

import json
import logging
import os
import threading
import time

import requests
from packaging.version import Version, InvalidVersion

from .models import GlobalSetting

logger = logging.getLogger(__name__)

GITHUB_REPO = "valteryde/broke"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
CHECK_INTERVAL = 6 * 60 * 60  # 6 hours
INITIAL_DELAY = 30  # seconds after startup before first check

UPDATER_URL = os.environ.get("UPDATER_URL", "http://broke-updater:9999")


def _get_current_version():
    """Read current version from pyproject.toml."""
    from .app import get_app_version_from_toml
    return get_app_version_from_toml()


def check_for_update():
    """
    Check GitHub Releases API for a newer version.
    Stores result in GlobalSetting under key 'update_info'.
    Returns the update info dict.
    """
    current_version_str = _get_current_version()

    try:
        current = Version(current_version_str)
    except InvalidVersion:
        logger.warning(f"Could not parse current version: {current_version_str}")
        return None

    try:
        resp = requests.get(
            GITHUB_API_URL,
            headers={"Accept": "application/vnd.github.v3+json"},
            timeout=15,
        )
        resp.raise_for_status()
        release = resp.json()
    except Exception as e:
        logger.warning(f"Failed to check for updates: {e}")
        # Store failure info so UI can show last check time
        info = {
            "available": False,
            "current_version": current_version_str,
            "latest_version": current_version_str,
            "error": str(e),
            "checked_at": int(time.time()),
        }
        _save_update_info(info)
        return info

    # Parse tag name (strip leading 'v' if present)
    tag = release.get("tag_name", "")
    latest_version_str = tag.lstrip("v")

    try:
        latest = Version(latest_version_str)
    except InvalidVersion:
        logger.warning(f"Could not parse latest version tag: {tag}")
        return None

    info = {
        "available": latest > current,
        "current_version": current_version_str,
        "latest_version": latest_version_str,
        "release_url": release.get("html_url", ""),
        "release_notes": release.get("body", ""),
        "published_at": release.get("published_at", ""),
        "checked_at": int(time.time()),
    }

    _save_update_info(info)
    logger.info(
        f"Update check complete: current={current_version_str}, "
        f"latest={latest_version_str}, available={info['available']}"
    )
    return info


def get_update_info():
    """Read cached update info from GlobalSetting. Returns dict or None."""
    try:
        setting = GlobalSetting.get(GlobalSetting.key == "update_info")
        return json.loads(setting.value)
    except GlobalSetting.DoesNotExist:
        return None


def is_auto_check_enabled():
    """Check if automatic update checking is enabled."""
    try:
        setting = GlobalSetting.get(GlobalSetting.key == "update_auto_check")
        return json.loads(setting.value).get("enabled", True)
    except GlobalSetting.DoesNotExist:
        return True  # Enabled by default


def set_auto_check_enabled(enabled):
    """Enable or disable automatic update checking."""
    value = json.dumps({"enabled": enabled})
    try:
        setting = GlobalSetting.get(GlobalSetting.key == "update_auto_check")
        setting.value = value
        setting.save()
    except GlobalSetting.DoesNotExist:
        GlobalSetting.create(key="update_auto_check", value=value)


def apply_update():
    """
    Call the updater sidecar to pull the latest image and restart the server.
    Returns a dict with the result.
    """
    try:
        resp = requests.post(
            f"{UPDATER_URL}/restart",
            json={"image": f"ghcr.io/{GITHUB_REPO}:latest"},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        return {"error": "Cannot reach updater sidecar. Is it running?"}
    except Exception as e:
        return {"error": str(e)}


def get_sidecar_status():
    """Check if the updater sidecar is reachable."""
    try:
        resp = requests.get(f"{UPDATER_URL}/status", timeout=5)
        return resp.json()
    except Exception:
        return {"ok": False, "error": "Sidecar unreachable"}


def _save_update_info(info):
    """Persist update info to GlobalSetting."""
    value = json.dumps(info)
    try:
        setting = GlobalSetting.get(GlobalSetting.key == "update_info")
        setting.value = value
        setting.save()
    except GlobalSetting.DoesNotExist:
        GlobalSetting.create(key="update_info", value=value)


def _background_checker():
    """Background thread that periodically checks for updates."""
    time.sleep(INITIAL_DELAY)
    while True:
        if is_auto_check_enabled():
            try:
                check_for_update()
            except Exception as e:
                logger.error(f"Background update check failed: {e}")
        time.sleep(CHECK_INTERVAL)


def start_update_checker():
    """Start the background update checker thread (called from create_app)."""
    thread = threading.Thread(target=_background_checker, daemon=True, name="update-checker")
    thread.start()
    logger.info("Background update checker started")
