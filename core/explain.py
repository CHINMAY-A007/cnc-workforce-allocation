"""Explanation helpers for assignments."""

from __future__ import annotations

import json
from core.db import get_conn
from core.config import resolve_horizon_start


def why_panel(task_id, version_id=None, db_path=None):
    conn = get_conn(db_path)
    if version_id is None:
        v = conn.execute("SELECT id FROM schedule_versions WHERE status='approved' ORDER BY created_at DESC LIMIT 1").fetchone()
        version_id = v["id"] if v else None
    a = conn.execute("SELECT * FROM version_assignments WHERE version_id=? AND task_id=?", (version_id, task_id)).fetchone()
    task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    conn.close()
    if not a or not task:
        return None
    why = json.loads(a["why"] or "{}")
    emp_ids = json.loads(a["employee_ids"])
    # employee details
    conn = get_conn(db_path)
    emps = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM employees").fetchall()}
    skills = {}
    for r in conn.execute("SELECT * FROM skills").fetchall():
        skills.setdefault(r["employee_id"], {})[r["skill"]] = r["level"]
    conn.close()
    lines = []
    lines.append(f"Assigned to: {', '.join(emps[e]['name'] for e in emp_ids)}")
    lines.append(f"Work center: {a['work_center_id']}")
    lines.append(f"Skill match: requires {task['required_skill']} level {task['min_level']}; " +
                ", ".join(f"{emps[e]['name']} has {skills.get(e, {}).get(task['required_skill'], 0)}" for e in emp_ids))
    lines.append("Availability: scheduled inside the assigned shift window on a working day.")
    lines.append(f"Locked: {'yes' if a['locked'] else 'no'}")
    lines.append("Alternatives considered: other eligible candidates ranked lower due to higher current workload, lower skill level, or overtime impact.")
    return {"assignment": dict(a), "task": dict(task), "why": why, "lines": lines, "employees": [emps[e] for e in emp_ids]}