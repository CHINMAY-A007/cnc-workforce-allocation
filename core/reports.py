"""Reporting helpers."""

from __future__ import annotations

import json
from datetime import datetime

from core.config import resolve_horizon_start
from core.db import get_conn


def utilization_by_employee(db_path=None, version_id=None):
    conn = get_conn(db_path)
    if version_id is None:
        v = conn.execute("SELECT id FROM schedule_versions WHERE status='approved' ORDER BY created_at DESC LIMIT 1").fetchone()
        version_id = v["id"] if v else None
    rows = []
    if version_id:
        for r in conn.execute("SELECT * FROM version_assignments WHERE version_id=?", (version_id,)).fetchall():
            emp_ids = json.loads(r["employee_ids"])
            dur = (r["end_slot"] - r["start_slot"]) * 15 / 60.0
            for e in emp_ids:
                rows.append((e, dur))
    # every employee appears in the report, even with zero scheduled time
    emps = [r["id"] for r in conn.execute("SELECT id FROM employees ORDER BY id").fetchall()]
    conn.close()
    agg = {e: 0.0 for e in emps}
    for e, d in rows:
        agg[e] = agg.get(e, 0.0) + d
    return agg


def version_summary(version_id, db_path=None):
    conn = get_conn(db_path)
    v = conn.execute("SELECT * FROM schedule_versions WHERE id=?", (version_id,)).fetchone()
    assigns = conn.execute("SELECT * FROM version_assignments WHERE version_id=?", (version_id,)).fetchall()
    conn.close()
    return dict(v) if v else None, [dict(a) for a in assigns]


def approved_versions(db_path=None):
    conn = get_conn(db_path)
    rows = conn.execute("SELECT * FROM schedule_versions ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def planned_vs_actual(db_path=None):
    conn = get_conn(db_path)
    rows = conn.execute("SELECT * FROM tasks").fetchall()
    conn.close()
    out = []
    for r in rows:
        out.append({
            "task": r["id"],
            "order": r["order_id"],
            "status": r["status"],
            "planned_start": r["planned_start"],
            "planned_end": r["planned_end"],
            "actual_start": r["actual_start"],
            "actual_end": r["actual_end"],
        })
    return out


def bottleneck_work_center(version_id=None, db_path=None):
    conn = get_conn(db_path)
    if version_id is None:
        v = conn.execute("SELECT id FROM schedule_versions WHERE status='approved' ORDER BY created_at DESC LIMIT 1").fetchone()
        version_id = v["id"] if v else None
    agg = {}
    if version_id:
        for r in conn.execute("SELECT * FROM version_assignments WHERE version_id=?", (version_id,)).fetchall():
            wc = r["work_center_id"]
            dur = (r["end_slot"] - r["start_slot"]) * 15 / 60.0
            agg[wc] = agg.get(wc, 0) + dur
    conn.close()
    if not agg:
        return None
    return max(agg.items(), key=lambda x: x[1])