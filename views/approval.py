from __future__ import annotations

import json
import streamlit as st
import pandas as pd

from core.db import DB_PATH, get_conn
from core.policy import get_policy
from core.eligibility import eligible_pairs
from core.tasks import list_tasks
from core.audit import log_action
from core.alerts import add_alert
from ui.components import page_header, presenter_panel


def render():
    page_header("Approval and Reassignment", "Review, edit (valid candidates only), lock, approve, or reject. Overrides require a reason.")
    presenter_panel("Approval")

    role = st.session_state.get("role", "Production Manager")
    can_approve = role in ("Production Manager", "ERP Administrator")
    conn = get_conn(DB_PATH)
    versions = [r["id"] for r in conn.execute("SELECT id FROM schedule_versions ORDER BY created_at DESC").fetchall()]
    conn.close()
    if not versions:
        st.info("No schedule yet.")
        return
    vid = st.selectbox("Version", versions)
    conn = get_conn(DB_PATH)
    assigns = [dict(r) for r in conn.execute("SELECT * FROM version_assignments WHERE version_id=?", (vid,)).fetchall()]
    tasks = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM tasks").fetchall()}
    emps = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM employees").fetchall()}
    conn.close()

    policy = get_policy(DB_PATH)
    st.dataframe(pd.DataFrame([{
        "task": a["task_id"], "employees": a["employee_ids"], "wc": a["work_center_id"],
        "start": a["start_slot"], "end": a["end_slot"], "locked": "🔒" if a["locked"] else "",
    } for a in assigns]), use_container_width=True)

    st.subheader("Edit an assignment")
    tid = st.selectbox("Task to edit", [a["task_id"] for a in assigns])
    a = next(x for x in assigns if x["task_id"] == tid)
    t = tasks.get(tid, {})
    task_obj = None
    # build a minimal task-like object for eligibility
    from core.models import Task
    task_obj = Task(id=tid, order_id=t.get("order_id", ""), seq=t.get("seq", 0), name=t.get("name", ""),
                    duration_min=t.get("duration_min", 60), required_skill=t.get("required_skill", ""),
                    min_level=t.get("min_level", 1), required_role=t.get("required_role", ""),
                    work_center_kind=t.get("work_center_kind", ""))
    er = eligible_pairs(task_obj, policy, DB_PATH)
    cand_labels = [f"{c['employee_id']} - {next(e['name'] for e in emps.values() if e['id']==c['employee_id'])}" for c in er.candidates]
    # unique employees
    uniq_emps = sorted(set(c["employee_id"] for c in er.candidates))
    new_emp = st.selectbox("Reassign to (valid candidates only)", uniq_emps,
                           format_func=lambda x: emps[x]["name"])
    reason = st.text_input("Reason for override (required)")
    c1, c2, c3 = st.columns(3)
    if c1.button("Apply reassignment"):
        if not reason.strip():
            st.error("Reason is required for overrides.")
        else:
            conn = get_conn(DB_PATH)
            conn.execute("UPDATE version_assignments SET employee_ids=? WHERE version_id=? AND task_id=?",
                         (json.dumps([new_emp]), vid, tid))
            conn.execute("UPDATE tasks SET employee_ids=? WHERE id=?", (json.dumps([new_emp]), tid))
            conn.commit()
            conn.close()
            log_action(role, role, "reassign", tid, before=a["employee_ids"], after=[new_emp], reason=reason, version_id=vid, db_path=DB_PATH)
            add_alert("reassignment", "warning", f"Task {tid} reassigned to {emps[new_emp]['name']}: {reason}", link="Approval and Reassignment")
            st.success("Reassigned.")
            st.rerun()
    if c2.button("Lock"):
        conn = get_conn(DB_PATH)
        conn.execute("UPDATE version_assignments SET locked=1 WHERE version_id=? AND task_id=?", (vid, tid))
        conn.execute("UPDATE tasks SET locked=1 WHERE id=?", (tid,))
        conn.commit()
        conn.close()
        log_action(role, role, "lock", tid, before=False, after=True, reason=reason or "locked", version_id=vid, db_path=DB_PATH)
        st.success("Locked 🔒")
        st.rerun()
    if c3.button("Unlock"):
        if role != "Production Manager":
            st.error("Only Production Manager can unlock.")
        else:
            conn = get_conn(DB_PATH)
            conn.execute("UPDATE version_assignments SET locked=0 WHERE version_id=? AND task_id=?", (vid, tid))
            conn.execute("UPDATE tasks SET locked=0 WHERE id=?", (tid,))
            conn.commit()
            conn.close()
            log_action(role, role, "unlock", tid, before=True, after=False, reason=reason or "unlocked", version_id=vid, db_path=DB_PATH)
            st.success("Unlocked.")
            st.rerun()

    st.divider()
    st.subheader("Approve / Reject version")
    if can_approve:
        c1, c2 = st.columns(2)
        if c1.button("Approve version", type="primary"):
            conn = get_conn(DB_PATH)
            conn.execute("UPDATE schedule_versions SET status='approved', approved_by=?, approved_at=? WHERE id=?",
                         (role, __import__("datetime").datetime.now().isoformat(timespec="seconds"), vid))
            # supersede older approved
            conn.execute("UPDATE schedule_versions SET status='superseded' WHERE status='approved' AND id<>?", (vid,))
            conn.commit()
            conn.close()
            log_action(role, role, "approve_schedule", vid, before="draft", after="approved", reason="manager approval", version_id=vid, db_path=DB_PATH)
            add_alert("approval", "info", f"Schedule {vid} approved.", link="Schedule Gantt")
            st.success("Approved.")
        if c2.button("Reject version"):
            rreason = st.text_input("Rejection reason", key="rej_reason")
            if rreason:
                conn = get_conn(DB_PATH)
                conn.execute("UPDATE schedule_versions SET status='rejected', notes=? WHERE id=?", (rreason, vid))
                conn.commit()
                conn.close()
                log_action(role, role, "reject_schedule", vid, before="draft", after="rejected", reason=rreason, version_id=vid, db_path=DB_PATH)
                st.warning("Rejected.")
    else:
        st.info("Switch to Production Manager to approve/reject.")