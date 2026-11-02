"""Replanning helpers: simulate events and produce before/after diffs."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from core.audit import log_action
from core.config import resolve_horizon_start
from core.db import get_conn
from core.solver import solve, validate_schedule
from core.tasks import list_tasks


def snapshot_assignments(version_id, db_path=None) -> Dict[str, dict]:
    conn = get_conn(db_path)
    out = {}
    for r in conn.execute("SELECT * FROM version_assignments WHERE version_id=?", (version_id,)).fetchall():
        out[r["task_id"]] = {
            "employee_ids": json.loads(r["employee_ids"]),
            "work_center_id": r["work_center_id"],
            "start_slot": r["start_slot"],
            "end_slot": r["end_slot"],
            "locked": bool(r["locked"]),
        }
    conn.close()
    return out


def locked_conflicts(version_id, event, db_path=None) -> List[dict]:
    """Detect locked assignments invalidated by an event."""
    conflicts = []
    snap = snapshot_assignments(version_id, db_path)
    if event["type"] == "absence":
        absent = event["employee_id"]
        for tid, a in snap.items():
            if a["locked"] and absent in a["employee_ids"]:
                conflicts.append({"task_id": tid, "reason": f"locked employee {absent} is absent"})
    if event["type"] == "breakdown":
        wc = event["work_center_id"]
        for tid, a in snap.items():
            if a["locked"] and a["work_center_id"] == wc:
                conflicts.append({"task_id": tid, "reason": f"locked work center {wc} is down"})
    return conflicts


def apply_event_to_policy(event, policy):
    p = json.loads(json.dumps(policy))
    # absence/breakdown handled via locked overrides + solver re-run on affected
    return p


def run_replan(current_version_id, event, policy, db_path=None, actor="Production Manager", role="Production Manager"):
    """Re-run solver for affected work, respecting locks. Returns diff + new draft version id or None."""
    conn = get_conn(db_path)
    tasks = conn.execute("SELECT * FROM tasks").fetchall()
    task_ids = [r["id"] for r in tasks]
    # affected tasks: if absence/breakdown, tasks assigned to that resource; else all
    if event["type"] == "absence":
        eid = event["employee_id"]
        affected = [tid for tid, a in snapshot_assignments(current_version_id, db_path).items()
                    if eid in a["employee_ids"]]
        if not affected:
            affected = task_ids
    elif event["type"] == "breakdown":
        wc = event["work_center_id"]
        affected = [tid for tid, a in snapshot_assignments(current_version_id, db_path).items()
                    if a["work_center_id"] == wc]
        if not affected:
            affected = task_ids
    elif event["type"] == "delay":
        affected = [event["task_id"]]
    elif event["type"] == "new_order":
        from core.tasks import generate_tasks
        generate_tasks(event["order_id"], db_path)
        affected = [r["id"] for r in conn.execute("SELECT id FROM tasks WHERE order_id=?", (event["order_id"],)).fetchall()]
    elif event["type"] == "priority_change":
        conn.execute("UPDATE orders SET priority=? WHERE id=?", (event["priority"], event["order_id"]))
        conn.commit()
        affected = [r["id"] for r in conn.execute("SELECT id FROM tasks WHERE order_id=?", (event["order_id"],)).fetchall()]
    else:
        affected = task_ids

    # locked map from current version
    snap = snapshot_assignments(current_version_id, db_path)
    locked_map = {}
    conflicts = locked_conflicts(current_version_id, event, db_path)
    conflict_ids = {c["task_id"] for c in conflicts}
    for tid, a in snap.items():
        if a["locked"] and tid not in conflict_ids:
            locked_map[tid] = {"employee_ids": a["employee_ids"], "work_center_id": a["work_center_id"],
                               "start_slot": a["start_slot"], "locked": True}
    # if conflicts, do not lock those (require unlock decision)
    conn.close()

    # if conflicts exist, return them without solving
    if conflicts:
        return {"conflicts": conflicts, "diff": None, "new_version_id": None, "requires_unlock": True}

    # determine order_ids affected
    conn = get_conn(db_path)
    affected_orders = set()
    for tid in affected:
        r = conn.execute("SELECT order_id FROM tasks WHERE id=?", (tid,)).fetchone()
        if r:
            affected_orders.add(r["order_id"])
    # also include all orders if affected spans? solve only affected tasks' orders
    if not affected_orders:
        affected_orders = {r["order_id"] for r in conn.execute("SELECT DISTINCT order_id FROM tasks").fetchall()}
    conn.close()

    # solve with locked map
    result = solve(db_path, list(affected_orders), policy, locked=locked_map, time_limit_sec=10.0)

    if result["status"] not in ("OPTIMAL", "FEASIBLE"):
        return {"conflicts": [], "diff": None, "new_version_id": None,
                "solver_status": result["status"], "zero_eligibility": result.get("zero_eligibility", [])}

    # create new draft version
    import uuid
    new_vid = "V-" + uuid.uuid4().hex[:8].upper()
    from datetime import datetime as _dt
    conn = get_conn(db_path)
    conn.execute(
        "INSERT INTO schedule_versions (id,created_at,status,solver_status,solver_runtime_sec,objective_value,notes) VALUES (?,?,?,?,?,?,?)",
        (new_vid, _dt.now().isoformat(timespec="seconds"), "draft", result["status"], result["runtime"], result["objective"] or 0.0, f"replan: {event['type']}"),
    )
    for a in result["assignments"]:
        conn.execute(
            "INSERT INTO version_assignments (version_id,task_id,employee_ids,work_center_id,start_slot,end_slot,locked,why) VALUES (?,?,?,?,?,?,?,?)",
            (new_vid, a.task_id, __import__("json").dumps(a.employee_ids), a.work_center_id, a.start_slot, a.end_slot, 1 if a.locked else 0, __import__("json").dumps(a.why)),
        )
    # persist planned_start/end on tasks for the new version's tasks
    for a in result["assignments"]:
        conn.execute("UPDATE tasks SET planned_start=?, planned_end=?, employee_ids=?, work_center_id=?, locked=? WHERE id=?",
                     (a.start_slot, a.end_slot, __import__("json").dumps(a.employee_ids), a.work_center_id, 1 if a.locked else 0, a.task_id))
    conn.commit()
    conn.close()

    # diff
    diff = build_diff(current_version_id, new_vid, db_path)
    return {"conflicts": [], "diff": diff, "new_version_id": new_vid, "solver_status": result["status"],
            "runtime": result["runtime"], "zero_eligibility": result.get("zero_eligibility", [])}


def build_diff(old_vid, new_vid, db_path=None):
    old = snapshot_assignments(old_vid, db_path)
    new = snapshot_assignments(new_vid, db_path)
    moved = []
    shifted = []
    for tid in set(old) | set(new):
        o = old.get(tid)
        n = new.get(tid)
        if o and n:
            if o["employee_ids"] != n["employee_ids"]:
                moved.append({"task": tid, "from": o["employee_ids"], "to": n["employee_ids"]})
            if o["start_slot"] != n["start_slot"] or o["end_slot"] != n["end_slot"]:
                shifted.append({"task": tid, "old": (o["start_slot"], o["end_slot"]), "new": (n["start_slot"], n["end_slot"])})
        elif o and not n:
            moved.append({"task": tid, "from": o["employee_ids"], "to": None})
        elif n and not o:
            moved.append({"task": tid, "from": None, "to": n["employee_ids"]})
    # delivery impact: compare max end per order
    return {"moved": moved, "shifted": shifted, "old_version": old_vid, "new_version": new_vid}