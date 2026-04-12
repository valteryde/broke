"""Desktop client handshake and device-token authentication endpoints."""

from flask import Blueprint, jsonify, request, send_file, session
from peewee import DoesNotExist
import hashlib
import os
import secrets
import time
import uuid
from urllib.parse import urlencode

from ..utils.app import get_app_codename_from_toml, get_app_version_from_toml
from ..utils.branding import DEFAULT_INSTANCE_LOGO_STATIC, resolve_instance_logo_path
from ..utils.models import (
    DesktopHandshakeToken,
    DeviceToken,
    GlobalSetting,
)
from ..utils.security import authenticate


desktop_bp = Blueprint("desktop", __name__)


HANDSHAKE_TTL_SECONDS = 300
DEVICE_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30
PLATFORM_ENV_SUFFIX = {
    "mac": "MAC",
    "windows": "WINDOWS",
}
PLATFORM_ALIASES = {
    "darwin": "mac",
    "mac": "mac",
    "macos": "mac",
    "osx": "mac",
    "win": "windows",
    "windows": "windows",
}


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _get_or_create_instance_id() -> str:
    key = "desktop_instance_id"
    setting = GlobalSetting.get_or_none(GlobalSetting.key == key)
    if setting:
        return setting.value

    instance_id = str(uuid.uuid4())
    GlobalSetting.create(key=key, value=instance_id)
    return instance_id


def _json_body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {}
    return data


def _backend_url() -> str:
    return request.host_url.rstrip("/")


def _desktop_release_url() -> str:
    return os.environ.get(
        "BROKE_DESKTOP_RELEASE_URL",
        "https://github.com/broke-project/broke-desktop/releases/latest",
    ).strip()


def _normalized_platform(value: str) -> str:
    return PLATFORM_ALIASES.get(str(value or "").strip().lower(), "")


def _request_platform() -> str:
    explicit = _normalized_platform(request.args.get("platform") or "")
    if explicit:
        return explicit

    user_agent = (request.headers.get("User-Agent") or "").lower()
    if "windows" in user_agent:
        return "windows"
    if "macintosh" in user_agent or "mac os x" in user_agent:
        return "mac"
    return ""


def _desktop_platform_value(platform: str, key: str) -> str:
    suffix = PLATFORM_ENV_SUFFIX.get(platform)
    if not suffix:
        return ""
    return os.environ.get(f"BROKE_DESKTOP_INSTALLER_{suffix}_{key}", "").strip()


def _desktop_installer_path() -> str:
    return os.environ.get("BROKE_DESKTOP_INSTALLER_PATH", "").strip()


def _desktop_installer_name(path: str) -> str:
    configured = os.environ.get("BROKE_DESKTOP_INSTALLER_NAME", "").strip()
    if configured:
        return configured
    return os.path.basename(path)


def _desktop_platform_installer_name(platform: str, path: str) -> str:
    configured = _desktop_platform_value(platform, "NAME")
    if configured:
        return configured
    return _desktop_installer_name(path)


@desktop_bp.route("/api/desktop/handshake", methods=["GET"])
def desktop_handshake():
    nonce = (request.args.get("nonce") or "").strip()
    now = int(time.time())

    challenge_token = secrets.token_urlsafe(32)
    DesktopHandshakeToken.create(
        token=challenge_token,
        created_at=now,
        expires_at=now + HANDSHAKE_TTL_SECONDS,
    )

    return jsonify(
        {
            "product": "broke",
            "api_version": "1",
            "instance_id": _get_or_create_instance_id(),
            "version": get_app_version_from_toml(),
            "codename": get_app_codename_from_toml(),
            "auth_methods": ["device_token"],
            "nonce_echo": nonce,
            "challenge_token": challenge_token,
            "challenge_expires_in": HANDSHAKE_TTL_SECONDS,
        }
    )


@desktop_bp.route("/api/desktop/bootstrap", methods=["GET"])
def desktop_bootstrap_payload():
    base = _backend_url()
    logo_path = resolve_instance_logo_path()
    if logo_path:
        v = int(logo_path.stat().st_mtime)
        logo_url = f"{base}/branding/instance-logo?v={v}"
    else:
        logo_url = f"{base}/static/{DEFAULT_INSTANCE_LOGO_STATIC}"
    return jsonify(
        {
            "product": "broke",
            "instance_id": _get_or_create_instance_id(),
            "instance_name": f"Broke ({base})",
            "backend_url": base,
            "logo_url": logo_url,
            "handshake_url": f"{base}/api/desktop/handshake",
            "session_restore_url": f"{base}/api/desktop/session",
            "generated_at": int(time.time()),
        }
    )


@desktop_bp.route("/desktop/download", methods=["GET"])
def desktop_download():
    platform = _request_platform()
    platform_installer_url = _desktop_platform_value(platform, "URL")
    if platform_installer_url:
        return "", 302, {"Location": platform_installer_url}

    platform_installer_path = _desktop_platform_value(platform, "PATH")
    if platform_installer_path and os.path.isfile(platform_installer_path):
        return send_file(
            platform_installer_path,
            as_attachment=True,
            download_name=_desktop_platform_installer_name(platform, platform_installer_path),
            mimetype="application/octet-stream",
        )

    installer_path = _desktop_installer_path()
    if installer_path and os.path.isfile(installer_path):
        return send_file(
            installer_path,
            as_attachment=True,
            download_name=_desktop_installer_name(installer_path),
            mimetype="application/octet-stream",
        )

    base = _backend_url()
    release_url = _desktop_release_url()
    bootstrap_url = f"{base}/api/desktop/bootstrap"
    qs = urlencode({"backend": base, "bootstrap": bootstrap_url})
    return "", 302, {"Location": f"{release_url}?{qs}"}


@desktop_bp.route("/api/desktop/device-login", methods=["POST"])
def desktop_device_login():
    data = _json_body()

    username = str(data.get("username") or "").strip()
    password = str(data.get("password") or "")
    device_name = str(data.get("device_name") or "").strip()
    device_id = str(data.get("device_id") or "").strip()
    challenge_token = str(data.get("challenge_token") or "").strip()

    if not username or not password or not device_name or not device_id:
        return jsonify({"error": "Missing required fields"}), 400

    if not challenge_token:
        return jsonify({"error": "challenge_token is required"}), 400

    now = int(time.time())
    challenge = DesktopHandshakeToken.get_or_none(DesktopHandshakeToken.token == challenge_token)
    if not challenge or challenge.used == 1 or challenge.expires_at < now:
        return jsonify({"error": "Invalid or expired challenge token"}), 400

    user = authenticate(username, password)
    if not user:
        return jsonify({"error": "Invalid username or password"}), 401

    challenge.used = 1
    challenge.save()

    raw_device_token = secrets.token_urlsafe(48)
    token_hash = _sha256(raw_device_token)

    DeviceToken.create(
        user=user.username,
        device_id=device_id,
        device_name=device_name,
        token_hash=token_hash,
        created_at=now,
        expires_at=now + DEVICE_TOKEN_TTL_SECONDS,
        last_used=now,
    )

    return jsonify(
        {
            "device_token": raw_device_token,
            "expires_at": now + DEVICE_TOKEN_TTL_SECONDS,
            "user": user.username,
        }
    )


@desktop_bp.route("/api/desktop/session", methods=["POST"])
def desktop_restore_session():
    data = _json_body()
    raw_device_token = str(data.get("device_token") or "").strip()
    if not raw_device_token:
        return jsonify({"error": "device_token is required"}), 400

    now = int(time.time())
    token_hash = _sha256(raw_device_token)

    token = DeviceToken.get_or_none(
        (DeviceToken.token_hash == token_hash)
        & (DeviceToken.revoked == 0)
    )
    if not token or token.expires_at < now:
        return jsonify({"error": "Invalid or expired device token"}), 401

    session["user_id"] = token.user.username
    token.last_used = now
    token.save()

    return jsonify({"success": True, "user": token.user.username}), 200


@desktop_bp.route("/api/desktop/device-revoke", methods=["POST"])
def desktop_revoke_device_token():
    data = _json_body()
    raw_device_token = str(data.get("device_token") or "").strip()
    if not raw_device_token:
        return jsonify({"error": "device_token is required"}), 400

    token_hash = _sha256(raw_device_token)
    try:
        token = DeviceToken.get(DeviceToken.token_hash == token_hash)
    except DoesNotExist:
        return jsonify({"error": "Device token not found"}), 404

    token.revoked = 1
    token.save()
    return jsonify({"success": True}), 200
