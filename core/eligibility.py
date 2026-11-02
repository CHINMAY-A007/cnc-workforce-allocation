"""Eligibility validation: who can do a task and why others are excluded."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Dict, List, Tuple

from core.config import is_working_day, resolve_horizon_start, shift_slots
from core.db import get_conn
from core.models import EligibilityResult


def _date_of_slot(slot: int, policy) -> date:
    hs = resolve_horizon_start(policy)
    day_idx = slot // (24 * 4)
    return hs + timedelta(days=day_idx)


def _cert_valid(emp_id, task_date, required_skill, required_role, conn) -> Tuple[bool, str]:
    rows = conn.execute("SELECT cert, expires_on FROM certs WHERE employee_id=?", (emp_id,)).fetchall()
    today = task_date.isoformat()
    skill_tokens = set(required_skill.lower().split()) | set(required_role.lower().split())
    for r in rows:
        if r["expires_on"] < today:
            cname = r["cert"].lower()
            if any(tok in cname for tok in skill_tokens if len(tok) > 2):
                return False, f"expired certification: {r['cert']} (expired {r['expires_on']})"
    return True, ""


def eligible_pairs(task, policy, db_path=None, task_date=None) -> EligibilityResult:
    conn = get_conn(db_path)
    res = EligibilityResult(task_id=task.id)
    if task_date is None:
        task_date = resolve_horizon_start(policy)
    # work centers of matching kind
    wcs = conn.execute(
        "SELECT * FROM work_centers WHERE kind=?", (task.work_center_kind,)
    ).fetchall()
    employees = conn.execute("SELECT * FROM employees WHERE active=1").fetchall()
    skills_map = {}
    for s in conn.execute("SELECT * FROM skills").fetchall():
        skills_map.setdefault(s["employee_id"], {})[s["skill"]] = s["level"]
    leave_map = {}
    for e in employees:
        leave_map[e["id"]] = set(json.loads(e["leave_dates"] or "[]"))

    for e in employees:
        eid = e["id"]
        reasons = []
        # skill
        lvl = skills_map.get(eid, {}).get(task.required_skill, 0)
        if lvl < task.min_level:
            reasons.append(f"missing skill {task.required_skill} (has {lvl}, needs {task.min_level})")
        # role
        if e["role"] != task.required_role and task.required_role not in ("Any",):
            # allow supervisors to cover? keep strict: role must match
            if e["role"] != task.required_role:
                reasons.append(f"role mismatch (is {e['role']}, needs {task.required_role})")
        # leave
        if task_date.isoformat() in leave_map.get(eid, set()):
            reasons.append("on leave on task date")
        # shift working day
        if not is_working_day(task_date, policy):
            reasons.append("non-working day")
        # cert validity
        ok, creason = _cert_valid(eid, task_date, task.required_skill, task.required_role, conn)
        if not ok:
            reasons.append(creason)
        # shift availability: task must fit in a shift window at least partially
        ss, se = shift_slots(e["shift"], policy)
        if se - ss < 1:
            reasons.append("no shift capacity")

        if reasons:
            res.excluded.append({"person": e["name"], "employee_id": eid, "reasons": reasons})
            continue

        # multi-person: same person can fill one slot; capacity per employee is 1 concurrent
        for wc in wcs:
            res.candidates.append({"employee_id": eid, "employee_name": e["name"], "work_center_id": wc["id"], "skill_level": lvl})
    conn.close()
    return res


def skill_matrix(db_path=None):
    conn = get_conn(db_path)
    emps = conn.execute("SELECT * FROM employees ORDER BY id").fetchall()
    skills = [r[0] for r in conn.execute("SELECT DISTINCT skill FROM skills ORDER BY skill").fetchall()]
    # all known skills
    all_skills = sorted(set(SKILLS) if False else skills)
    # ensure full skill list
    all_skills = sorted(set(skills) | set(
        ["CNC Turning", "VMC Milling", "5-Axis Programming", "Setup", "CMM Inspection", "Deburring", "Packing", "Titanium Machining"]
    ))
    matrix = {}
    for e in emps:
        matrix[e["id"]] = {s: 0 for s in all_skills}
    for s in conn.execute("SELECT * FROM skills").fetchall():
        if s["skill"] in matrix[s["employee_id"]]:
            matrix[s["employee_id"]][s["skill"]] = s["level"]
    cert_flags = {}
    for c in conn.execute("SELECT * FROM certs").fetchall():
        cert_flags.setdefault(c["employee_id"], []).append((c["cert"], c["expires_on"]))
    conn.close()
    return emps, all_skills, matrix, cert_flags


SKILLS = [
    "CNC Turning", "VMC Milling", "5-Axis Programming", "Setup",
    "CMM Inspection", "Deburring", "Packing", "Titanium Machining",
]