"""Work cycles API and pages (time-boxed ticket grouping)."""

from __future__ import annotations

import time
from typing import Any

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from ..utils.models import Project, Ticket, User, WorkCycle
from ..utils.security import protected
from ..utils.ticket_markdown import (
    build_cycle_markdown_document,
    build_ticket_export_payload,
    work_cycle_to_export_dict,
)
from .tickets import populateTickets

work_cycles_bp = Blueprint("work_cycles", __name__)

# Lanes for the “living board” (intake-like statuses roll into backlog; finished rolls into done).
_WORK_CYCLE_LANE_META: list[tuple[str, str, str, str]] = [
    ("backlog", "Backlog", "ph-circle-dashed", "#64748b"),
    ("todo", "Todo", "ph-circle", "#8b5cf6"),
    ("in-progress", "In progress", "ph-circle-half", "#3b82f6"),
    ("in-review", "In review", "ph-circle-notch", "#f59e0b"),
    ("done", "Done", "ph-check-circle", "#22c55e"),
]


def _normalize_lane_status(status: str | None) -> str:
    s = (status or "").strip().lower()
    if s in {"intake", "triage"}:
        return "backlog"
    if s in {"done", "closed", "duplicate"}:
        return "done"
    if s in {"backlog", "todo", "in-progress", "in-review"}:
        return s
    return "backlog"


def _stats_for_cycles(cycle_ids: list[int]) -> dict[int, dict[str, int]]:
    out: dict[int, dict[str, int]] = {
        cid: {"total": 0, "done": 0, "active": 0} for cid in cycle_ids
    }
    if not cycle_ids:
        return out
    q = Ticket.select().where((Ticket.work_cycle_id.in_(cycle_ids)) & (Ticket.active == 1))
    for t in q:
        cid = t.work_cycle_id
        if cid not in out:
            continue
        out[cid]["total"] += 1
        if t.status in {"done", "closed", "duplicate"}:
            out[cid]["done"] += 1
        else:
            out[cid]["active"] += 1
    return out


def _board_lanes(tickets: list[Ticket]) -> list[dict[str, Any]]:
    buckets: dict[str, list[Ticket]] = {k: [] for k, _, _, _ in _WORK_CYCLE_LANE_META}
    for t in tickets:
        buckets[_normalize_lane_status(t.status)].append(t)
    lanes: list[dict[str, Any]] = []
    for key, label, icon, color in _WORK_CYCLE_LANE_META:
        lanes.append(
            {
                "key": key,
                "label": label,
                "icon": icon,
                "color": color,
                "tickets": buckets[key],
            }
        )
    return lanes


def _cycle_dict(c: WorkCycle) -> dict[str, Any]:
    return work_cycle_to_export_dict(c)


@work_cycles_bp.route("/work-cycles")
@protected
def work_cycles_list_view(user: User):
    cycles = list(WorkCycle.select().order_by(WorkCycle.created_at.desc()))
    cids = [c.id for c in cycles]
    cycle_stats = _stats_for_cycles(cids)
    return render_template(
        "work_cycles_list.jinja2",
        user=user,
        page="work_cycles",
        cycles=cycles,
        cycle_stats=cycle_stats,
    )


@work_cycles_bp.route("/work-cycles/<int:cycle_id>")
@protected
def work_cycle_detail_view(user: User, cycle_id: int):
    cycle = WorkCycle.get_or_none(WorkCycle.id == cycle_id)
    if not cycle:
        return redirect(url_for("work_cycles.work_cycles_list_view"))
    tickets = list(
        Ticket.select()
        .where((Ticket.work_cycle_id == cycle_id) & (Ticket.active == 1))
        .order_by(Ticket.created_at.asc())
    )
    populateTickets(tickets, lite=True)
    st = _stats_for_cycles([cycle_id]).get(cycle_id, {"total": 0, "done": 0, "active": 0})
    board_lanes = _board_lanes(tickets)
    return render_template(
        "work_cycle_detail.jinja2",
        user=user,
        page="work_cycles",
        cycle=cycle,
        tickets=tickets,
        board_lanes=board_lanes,
        cycle_stats=st,
    )


@work_cycles_bp.route("/api/work-cycles", methods=["GET"])
@protected
def api_list_work_cycles(user: User):
    q = WorkCycle.select().order_by(WorkCycle.created_at.desc())
    return jsonify({"cycles": [_cycle_dict(c) for c in q]}), 200


@work_cycles_bp.route("/api/work-cycles", methods=["POST"])
@protected
def api_create_work_cycle(user: User):
    data = request.get_json(silent=True) or {}
    name = str(data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    goal = str(data.get("goal") or "").strip() or None
    project_raw = data.get("project")
    project = None
    if project_raw is not None and str(project_raw).strip():
        project = str(project_raw).strip()
        if not Project.get_or_none(Project.id == project):
            return jsonify({"error": "Unknown project"}), 400

    starts_at = data.get("starts_at")
    ends_at = data.get("ends_at")
    starts_i = int(starts_at) if starts_at is not None and str(starts_at).strip() != "" else None
    ends_i = int(ends_at) if ends_at is not None and str(ends_at).strip() != "" else None

    cycle = WorkCycle.create(
        name=name,
        goal=goal,
        project=project,
        starts_at=starts_i,
        ends_at=ends_i,
        created_at=int(time.time()),
    )
    return jsonify({"cycle": _cycle_dict(cycle)}), 201


@work_cycles_bp.route("/api/work-cycles/<int:cycle_id>", methods=["GET"])
@protected
def api_get_work_cycle(user: User, cycle_id: int):
    cycle = WorkCycle.get_or_none(WorkCycle.id == cycle_id)
    if not cycle:
        return jsonify({"error": "Work cycle not found"}), 404
    ticket_ids = [
        t.id
        for t in Ticket.select(Ticket.id).where(
            (Ticket.work_cycle_id == cycle_id) & (Ticket.active == 1)
        )
    ]
    return jsonify({"cycle": _cycle_dict(cycle), "ticket_ids": ticket_ids}), 200


@work_cycles_bp.route("/api/work-cycles/<int:cycle_id>", methods=["PATCH"])
@protected
def api_patch_work_cycle(user: User, cycle_id: int):
    cycle = WorkCycle.get_or_none(WorkCycle.id == cycle_id)
    if not cycle:
        return jsonify({"error": "Work cycle not found"}), 404

    data = request.get_json(silent=True) or {}

    if "name" in data:
        name = str(data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name cannot be empty"}), 400
        cycle.name = name

    if "goal" in data:
        g = data.get("goal")
        cycle.goal = str(g).strip() if g is not None and str(g).strip() else None

    if "starts_at" in data:
        s = data.get("starts_at")
        cycle.starts_at = int(s) if s is not None and str(s).strip() != "" else None

    if "ends_at" in data:
        e = data.get("ends_at")
        cycle.ends_at = int(e) if e is not None and str(e).strip() != "" else None

    if "project" in data:
        p = data.get("project")
        new_project = None
        if p is not None and str(p).strip():
            new_project = str(p).strip()
            if not Project.get_or_none(Project.id == new_project):
                return jsonify({"error": "Unknown project"}), 400
        if new_project != cycle.project:
            cycle.project = new_project

    cycle.save()
    return jsonify({"cycle": _cycle_dict(cycle)}), 200


@work_cycles_bp.route("/api/work-cycles/<int:cycle_id>/tickets", methods=["POST"])
@protected
def api_work_cycle_modify_tickets(user: User, cycle_id: int):
    """Add or remove tickets on a sprint by id (any project)."""
    cycle = WorkCycle.get_or_none(WorkCycle.id == cycle_id)
    if not cycle:
        return jsonify({"error": "Work cycle not found"}), 404

    data = request.get_json(silent=True) or {}
    add_ids = data.get("add") or data.get("ticket_ids")
    remove_ids = data.get("remove")

    added = 0
    removed = 0

    if add_ids is not None:
        if not isinstance(add_ids, list):
            return jsonify({"error": "add must be a list of ticket ids"}), 400
        for raw in add_ids:
            tid = str(raw or "").strip()
            if not tid:
                continue
            t = Ticket.get_or_none((Ticket.id == tid) & (Ticket.active == 1))
            if not t:
                continue
            t.work_cycle_id = cycle_id
            t.save()
            added += 1

    if remove_ids is not None:
        if not isinstance(remove_ids, list):
            return jsonify({"error": "remove must be a list of ticket ids"}), 400
        for raw in remove_ids:
            tid = str(raw or "").strip()
            if not tid:
                continue
            t = Ticket.get_or_none(Ticket.id == tid)
            if t and t.work_cycle_id == cycle_id:
                t.work_cycle_id = None
                t.save()
                removed += 1

    return jsonify({"added": added, "removed": removed}), 200


@work_cycles_bp.route("/api/work-cycles/<int:cycle_id>", methods=["DELETE"])
@protected
def api_delete_work_cycle(user: User, cycle_id: int):
    cycle = WorkCycle.get_or_none(WorkCycle.id == cycle_id)
    if not cycle:
        return jsonify({"error": "Work cycle not found"}), 404

    Ticket.update(work_cycle_id=None).where(Ticket.work_cycle_id == cycle_id).execute()
    cycle.delete_instance()
    return jsonify({"success": True}), 200


@work_cycles_bp.route("/api/work-cycles/<int:cycle_id>/export", methods=["GET"])
@protected
def api_export_work_cycle(user: User, cycle_id: int):
    cycle = WorkCycle.get_or_none(WorkCycle.id == cycle_id)
    if not cycle:
        return jsonify({"error": "Work cycle not found"}), 404

    tickets = list(
        Ticket.select()
        .where((Ticket.work_cycle_id == cycle_id) & (Ticket.active == 1))
        .order_by(Ticket.created_at.asc())
    )
    payloads = []
    for t in tickets:
        p = build_ticket_export_payload(t.id)
        if p:
            payloads.append(p)

    export_format = str(request.args.get("format", "markdown")).strip().lower()
    if export_format in {"json", "application/json"}:
        return (
            jsonify(
                {
                    "cycle": _cycle_dict(cycle),
                    "tickets": payloads,
                }
            ),
            200,
        )

    if export_format not in {"md", "markdown", "text/markdown"}:
        return jsonify({"error": "Unsupported export format"}), 400

    base = request.url_root or "/"
    content = build_cycle_markdown_document(cycle, payloads, base)
    return content, 200, {"Content-Type": "text/markdown; charset=utf-8"}
