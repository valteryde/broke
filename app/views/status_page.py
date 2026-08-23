"""Public Status Page Views and API Endpoints."""

import json
import time

from flask import Blueprint, jsonify, render_template, request
from peewee import DoesNotExist, IntegrityError

from ..utils.models import GlobalSetting, Monitor, StatusSubscriber
from ..utils.monitors import monitor_stats

status_bp = Blueprint("status", __name__)


def get_status_page_settings() -> dict:
    try:
        setting = GlobalSetting.get(GlobalSetting.key == "status_page_settings")
        return json.loads(setting.value)
    except (DoesNotExist, json.JSONDecodeError):
        return {
            "title": "System Status",
            "maintenance_message": "",
            "is_maintenance_active": False,
        }


@status_bp.route("/status")
def status_page_view():
    """Render the public status page."""
    settings = get_status_page_settings()
    # Fetch public monitors
    monitors = list(
        Monitor.select()
        .where((Monitor.public == 1) & (Monitor.enabled == 1))
        .order_by(Monitor.name)
    )

    # Check overall status
    all_operational = True
    board_rows = []
    for m in monitors:
        if m.status != "up":
            all_operational = False
        board_rows.append({"monitor": m, **monitor_stats(m)})

    return render_template(
        "status_page.jinja2",
        settings=settings,
        board_rows=board_rows,
        all_operational=all_operational,
    )


@status_bp.route("/api/status/subscribe", methods=["POST"])
def api_status_subscribe():
    """Subscribe to public monitor alerts."""
    data = request.get_json(silent=True) or {}
    email = str(data.get("email") or "").strip()

    if not email or "@" not in email:
        return jsonify({"error": "A valid email is required"}), 400

    try:
        StatusSubscriber.create(email=email, created_at=int(time.time()))
    except IntegrityError:
        # Already subscribed, that's fine
        pass

    return jsonify({"success": True}), 201
