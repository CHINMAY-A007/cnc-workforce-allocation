"""Eligibility (FR-04): who may do a task on a given day, and who is excluded and why.

These are HARD rules. There is no override path anywhere in the app: the solver,
the manual-reassign dropdown and the replanner all call the same functions.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from core.config import is_working_day, load_policy, resolve_horizon_start, shift_slots, SLOTS_PER_HOUR
from core.db import get_conn

# which skill a certificate covers
CERT_SKILL = {
    "CNC Turning Cert": "CNC Turning",
    "Titanium Machining Cert": "Titanium Machining",
    "VMC Operator Cert": "VMC Milling",
    "5-Axis Programming Cert": "5-Axis Programming",
    "CMM Inspection Cert": "CMM Inspection",
    "Setup Technician Cert": "Setup",
    "Deburring Cert": "Deburring",
    "Packing Cert": "Packing",
}
EXPIRING_SOON_DAYS = 14


class Context:
    """Everything the rules need, loaded once."""

    def __init__(self, db_path=None):
        conn = get_conn(db_path)
        self.policy = load_policy(conn)
        self.hs = resolve_horizon_start(self.policy)
        self.emps = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM employees ORDER BY id").fetchall()}
        for e in self.emps.values():
            e["leave"] = set(json.loads(e["leave_dates"] or "[]"))
        self.skills: Dict[str, Dict[str, int]] = {}
        for r in conn.execute("SELECT * FROM skills").fetchall():
            self.skills.setdefault(r["employee_id"], {})[r["skill"]] = r["level"]
        self.certs: Dict[str, List[tuple]] = {}
        for r in conn.execute("SELECT * FROM certs").fetchall():
            self.certs.setdefault(r["employee_id"], []).append((r["cert"], r["expires_on"]))
        self.wcs = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM work_centers ORDER BY id").fetchall()}
        self.maint: Dict[str, List[tuple]] = {}
        for m in conn.execute("SELECT * FROM maintenance").fetchall():
            self.maint.setdefault(m["work_center_id"], []).append((m["start_slot"], m["end_slot"], m["reason"]))
        conn.close()

    def day(self, idx: int) -> date:
        return self.hs + timedelta(days=idx)


def check_employee(e: dict, task: dict, d: date, ctx: Context, absent: Optional[set] = None) -> List[str]:
    """Return the list of reasons this employee cannot do this task on date d (empty = eligible)."""
    reasons: List[str] = []
    eid = e["id"]
    if not e["active"] or (absent and eid in absent):
        reasons.append("marked absent / inactive")
    if e["role"] != task["required_role"]:
        reasons.append(f"wrong role (is {e['role']}, needs {task['required_role']})")
    lvl = ctx.skills.get(eid, {}).get(task["required_skill"], 0)
    if lvl < task["min_level"]:
        reasons.append(f"skill too low: {task['required_skill']} level {lvl}, needs {task['min_level']}")
    if task.get("extra_skill"):
        l2 = ctx.skills.get(eid, {}).get(task["extra_skill"], 0)
        if l2 < int(task.get("extra_min_level") or 1):
            reasons.append(f"missing {task['extra_skill']} (order note), level {l2}, needs {task['extra_min_level']}")
    iso = d.isoformat()
    need_skills = {task["required_skill"]} | ({task["extra_skill"]} if task.get("extra_skill") else set())
    for cert, exp in ctx.certs.get(eid, []):
        if CERT_SKILL.get(cert) in need_skills and exp < iso:
            reasons.append(f"certification expired: {cert} (expired {exp})")
    if task.get("required_cert"):
        held = [exp for c, exp in ctx.certs.get(eid, []) if c == task["required_cert"]]
        if not held:
            reasons.append(f"no {task['required_cert']} (order note: certified person only)")
        elif max(held) < iso:
            reasons.append(f"certification expired: {task['required_cert']} (order note: certified person only)")
    if iso in e["leave"]:
        reasons.append("on leave that day")
    if not is_working_day(d, ctx.policy):
        reasons.append("non-working day")
    s, en = shift_slots(e["shift"], ctx.policy)
    pol = ctx.policy
    window = (en - s) + int(min(float(pol["overtime_cap_hours"]), float(pol["max_daily_hours_cap"]) - float(pol["standard_daily_hours"])) * SLOTS_PER_HOUR)
    if (task["duration_min"] + 14) // 15 > window:
        reasons.append("job is longer than the shift plus allowed overtime")
    return reasons


def task_candidates(task: dict, d: date, ctx: Context, absent: Optional[set] = None, down_wcs: Optional[set] = None) -> Dict[str, Any]:
    cands, excl = [], []
    for eid, e in ctx.emps.items():
        r = check_employee(e, task, d, ctx, absent)
        lvl = ctx.skills.get(eid, {}).get(task["required_skill"], 0)
        if r:
            only_unqualified = all(x.startswith("wrong role") or x.startswith("skill too low") for x in r)
            excl.append({"employee_id": eid, "person": e["name"], "role": e["role"], "reasons": r,
                         "kind": "not_qualified" if only_unqualified else "blocked"})
        else:
            cands.append({"employee_id": eid, "employee_name": e["name"], "role": e["role"], "shift": e["shift"], "skill_level": lvl})
    wcs = [w["id"] for w in ctx.wcs.values() if w["kind"] == task["work_center_kind"] and not (down_wcs and w["id"] in down_wcs)]
    return {"candidates": cands, "excluded": excl, "work_centers": wcs}


def skill_matrix(db_path=None) -> Dict[str, Any]:
    ctx = Context(db_path)
    base = ["CNC Turning", "VMC Milling", "5-Axis Programming", "Titanium Machining", "Setup", "CMM Inspection", "Deburring", "Packing"]
    seen = {s for lv in ctx.skills.values() for s in lv}
    from core.db import get_conn as _gc
    _c = _gc(db_path)
    seen |= {r[0] for r in _c.execute("SELECT DISTINCT required_skill FROM routing_ops").fetchall()}
    _c.close()
    skills = base + sorted(s for s in seen if s not in set(base))
    emps = []
    for eid, e in ctx.emps.items():
        certs = []
        for c, exp in sorted(ctx.certs.get(eid, [])):
            days = (datetime.strptime(exp, "%Y-%m-%d").date() - ctx.hs).days
            state = "expired" if days < 0 else ("expiring soon" if days <= EXPIRING_SOON_DAYS else "valid")
            certs.append({"cert": c, "expires_on": exp, "state": state, "days_left": days})
        emps.append({"id": eid, "name": e["name"], "role": e["role"], "team": e["team"], "shift": e["shift"],
                     "active": bool(e["active"]), "leave_dates": sorted(e["leave"]),
                     "max_daily_hours": e["max_daily_hours"], "overtime_cap_hours": e["overtime_cap_hours"],
                     "levels": {s: ctx.skills.get(eid, {}).get(s, 0) for s in skills}, "certs": certs})
    return {"skills": skills, "employees": emps, "reference_date": ctx.hs.isoformat()}
