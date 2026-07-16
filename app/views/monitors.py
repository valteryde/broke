"""HTTP(S) uptime monitors — pages and CRUD API."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from flask import Blueprint, abort, jsonify, redirect, render_template, request, url_for

from ..utils.features import FEATURE_MONITORS, is_feature_enabled
from ..utils.models import Monitor, MonitorCheck, Project, User, active_projects_ordered
from ..utils.monitors import (
    DEFAULT_EXPECTED_STATUS,
    DEFAULT_INTERVAL_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    clamp_interval,
    clamp_timeout,
    monitor_stats,
    validate_monitor_url,
)
from ..utils.security import protected

monitors_bp = Blueprint("monitors", __name__)


def _feature_guard():
    if not is_feature_enabled(FEATURE_MONITORS):
        abort(404)


def _monitor_dict(m: Monitor, *, include_stats: bool = True) -> dict[str, Any]:
    project_id = m.project_id if hasattr(m, "project_id") else str(m.project)
    data: dict[str, Any] = {
        "id": m.id,
        "project": project_id,
        "name": m.name,
        "url": m.url,
        "interval_seconds": m.interval_seconds,
        "timeout_seconds": m.timeout_seconds,
        "expected_status": m.expected_status,
        "enabled": bool(m.enabled),
        "status": m.status,
        "last_checked_at": m.last_checked_at,
        "last_status_change_at": m.last_status_change_at,
        "last_error": m.last_error,
        "last_response_ms": m.last_response_ms,
        "created_at": m.created_at,
    }
    if include_stats:
        data.update(monitor_stats(m))
    return data


def _resolve_project(project_raw: Any) -> tuple[Project | None, str | None]:
    project_id = str(project_raw or "").strip()
    if not project_id:
        return None, "project is required"
    prow = Project.get_or_none(Project.id == project_id)
    if not prow:
        return None, "Unknown project"
    if prow.archived == 1:
        return None, "Cannot attach a monitor to an archived project"
    return prow, None


def _fmt_ts(ts: int | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _board_rows(monitors: list[Monitor], project_names: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for m in monitors:
        stats = monitor_stats(m)
        project_id = m.project_id if hasattr(m, "project_id") else str(m.project)
        rows.append(
            {
                "monitor": m,
                "project_name": project_names.get(project_id, project_id),
                **stats,
            }
        )
    return rows


@monitors_bp.route("/monitors")
@protected
def monitors_list_view(user: User):
    _feature_guard()
    monitors = list(Monitor.select().order_by(Monitor.created_at.desc()))
    projects = list(active_projects_ordered())
    project_names = {p.id: p.name for p in Project.select()}
    return render_template(
        "monitors_list.jinja2",
        user=user,
        page="monitors",
        board_rows=_board_rows(monitors, project_names),
        projects=projects,
        project_names=project_names,
    )


@monitors_bp.route("/monitors/<int:monitor_id>")
@protected
def monitor_detail_view(user: User, monitor_id: int):
    _feature_guard()
    monitor = Monitor.get_or_none(Monitor.id == monitor_id)
    if not monitor:
        return redirect(url_for("monitors.monitors_list_view"))
    projects = list(active_projects_ordered())
    current = Project.get_or_none(Project.id == monitor.project_id)
    if current and current not in projects:
        projects = [current] + projects
    stats = monitor_stats(monitor)
    return render_template(
        "monitor_detail.jinja2",
        user=user,
        page="monitors",
        monitor=monitor,
        projects=projects,
        last_checked_display=_fmt_ts(monitor.last_checked_at),
        last_change_display=_fmt_ts(monitor.last_status_change_at),
        **stats,
    )


@monitors_bp.route("/api/monitors", methods=["GET"])
@protected
def api_list_monitors(user: User):
    _feature_guard()
    q = Monitor.select().order_by(Monitor.created_at.desc())
    return jsonify({"monitors": [_monitor_dict(m) for m in q]}), 200


@monitors_bp.route("/api/monitors", methods=["POST"])
@protected
def api_create_monitor(user: User):
    _feature_guard()
    data = request.get_json(silent=True) or {}
    name = str(data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    url = str(data.get("url") or "").strip()
    url_err = validate_monitor_url(url)
    if url_err:
        return jsonify({"error": url_err}), 400

    project, err = _resolve_project(data.get("project"))
    if err:
        return jsonify({"error": err}), 400

    try:
        expected_status = int(data.get("expected_status", DEFAULT_EXPECTED_STATUS))
    except (TypeError, ValueError):
        return jsonify({"error": "expected_status must be an integer"}), 400
    if expected_status < 100 or expected_status > 599:
        return jsonify({"error": "expected_status must be between 100 and 599"}), 400

    enabled_raw = data.get("enabled", True)
    enabled = 1 if enabled_raw in (True, 1, "1", "true", "True") else 0

    monitor = Monitor.create(
        project=project,
        name=name,
        url=url,
        interval_seconds=clamp_interval(data.get("interval_seconds", DEFAULT_INTERVAL_SECONDS)),
        timeout_seconds=clamp_timeout(data.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)),
        expected_status=expected_status,
        enabled=enabled,
        status="unknown",
        created_at=int(time.time()),
    )
    return jsonify({"monitor": _monitor_dict(monitor)}), 201


@monitors_bp.route("/api/monitors/<int:monitor_id>", methods=["GET"])
@protected
def api_get_monitor(user: User, monitor_id: int):
    _feature_guard()
    monitor = Monitor.get_or_none(Monitor.id == monitor_id)
    if not monitor:
        return jsonify({"error": "Monitor not found"}), 404
    return jsonify({"monitor": _monitor_dict(monitor)}), 200


@monitors_bp.route("/api/monitors/<int:monitor_id>", methods=["PATCH"])
@protected
def api_patch_monitor(user: User, monitor_id: int):
    _feature_guard()
    monitor = Monitor.get_or_none(Monitor.id == monitor_id)
    if not monitor:
        return jsonify({"error": "Monitor not found"}), 404

    data = request.get_json(silent=True) or {}

    if "name" in data:
        name = str(data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name cannot be empty"}), 400
        monitor.name = name

    if "url" in data:
        url = str(data.get("url") or "").strip()
        url_err = validate_monitor_url(url)
        if url_err:
            return jsonify({"error": url_err}), 400
        monitor.url = url

    if "project" in data:
        project, err = _resolve_project(data.get("project"))
        if err:
            return jsonify({"error": err}), 400
        monitor.project = project

    if "interval_seconds" in data:
        monitor.interval_seconds = clamp_interval(data.get("interval_seconds"))

    if "timeout_seconds" in data:
        monitor.timeout_seconds = clamp_timeout(data.get("timeout_seconds"))

    if "expected_status" in data:
        try:
            expected_status = int(data.get("expected_status"))
        except (TypeError, ValueError):
            return jsonify({"error": "expected_status must be an integer"}), 400
        if expected_status < 100 or expected_status > 599:
            return jsonify({"error": "expected_status must be between 100 and 599"}), 400
        monitor.expected_status = expected_status

    if "enabled" in data:
        enabled_raw = data.get("enabled")
        monitor.enabled = 1 if enabled_raw in (True, 1, "1", "true", "True") else 0

    monitor.save()
    return jsonify({"monitor": _monitor_dict(monitor)}), 200


@monitors_bp.route("/api/monitors/<int:monitor_id>", methods=["DELETE"])
@protected
def api_delete_monitor(user: User, monitor_id: int):
    _feature_guard()
    monitor = Monitor.get_or_none(Monitor.id == monitor_id)
    if not monitor:
        return jsonify({"error": "Monitor not found"}), 404
    MonitorCheck.delete().where(MonitorCheck.monitor == monitor).execute()
    monitor.delete_instance()
    return jsonify({"ok": True}), 200
