from __future__ import annotations

import json
import streamlit as st
import pandas as pd

from core.db import DB_PATH, get_conn
from core.policy import get_policy
from core.replan import run_replan, locked_conflicts, snapshot_assignments, build_diff
from core.audit import log_action
from core.alerts import add_alert
from core.tasks import list_tasks
from ui.components import page_header, presenter_panel


def render():
    page_header("Live Progress and Alerts", "Delivery-risk dashboard, alerts, and the replanning simulator.")
    presenter_panel("Progress")

    role = st.session_state.get("role", "Production Manager")
    conn = get_conn(DB_PATH)
    versions = [r["id"] for r in conn.execute("SELECT id FROM schedule_versions ORDER BY created_at DESC").fetchall()]
    conn.close()
    if not versions:
        st.info("No schedule yet.")
        return
    current_vid = versions[0]
    st.caption(f"Current (latest) version: {current_vid}")

    # alerts
    from core.alerts import list_alerts, unread_count
    st.subheader(f"Alerts ({unread_count(DB_PATH)} unread)")
    for a in list_alerts(db_path=DB_PATH)[:20]:
        color = "🔴" if a["severity"] == "critical" else ("🟡" if a["severity"] == "warning" else "🔵")
        st.write(f"{color} {a['ts']} - {a['message']}")

    st.divider()
    st.subheader("Delivery risk")
    conn = get_conn(DB_PATH)
    tasks = [dict(r) for r in conn.execute("SELECT * FROM tasks").fetchall()]
    conn.close()
    st.write(f"Total tasks: {len(tasks)} | Completed: {sum(1 for t in tasks if t['status']=='Completed')} | Blocked: {sum(1 for t in tasks if t['status']=='Blocked')}")

    st.divider()
    st.subheader("Replanning simulator")
    event_type = st.selectbox("Simulate event", ["absence", "breakdown", "delay", "new_order", "priority_change"])
    event = {"type": event_type}
    if event_type == "absence":
        emps = [r["id"] for r in get_conn(DB_PATH).execute("SELECT id FROM employees").fetchall()]
        event["employee_id"] = st.selectbox("Absent employee", emps)
    elif event_type == "breakdown":
        wcs = [r["id"] for r in get_conn(DB_PATH).execute("SELECT id FROM work_centers").fetchall()]
        event["work_center_id"] = st.selectbox("Broken work center", wcs)
    elif event_type == "delay":
        ts = [t["id"] for t in tasks]
        event["task_id"] = st.selectbox("Delayed task", ts)
        event["hours"] = st.number_input("Delay hours", 1, 8, 2)
    elif event_type == "new_order":
        ords = [r["id"] for r in get_conn(DB_PATH).execute("SELECT id FROM orders").fetchall()]
        event["order_id"] = st.selectbox("New urgent order", ords)
    elif event_type == "priority_change":
        ords = [r["id"] for r in get_conn(DB_PATH).execute("SELECT id FROM orders").fetchall()]
        event["order_id"] = st.selectbox("Order", ords)
        event["priority"] = st.selectbox("New priority", ["Urgent", "High", "Normal"])

    # locked conflicts preview
    cf = locked_conflicts(current_vid, event, DB_PATH)
    if cf:
        st.error("Locked assignment conflicts detected:")
        for c in cf:
            st.write(f"- {c['task_id']}: {c['reason']}")
        st.warning("Requires authorized manager unlock/replan decision. No silent change.")

    if st.button("Simulate and propose revised plan", type="primary"):
        policy = get_policy(DB_PATH)
        res = run_replan(current_vid, event, policy, DB_PATH, actor=role, role=role)
        if res.get("requires_unlock"):
            st.error("Conflicts require unlock first.")
        elif res.get("diff") is None and res.get("solver_status") in ("UNKNOWN", "INFEASIBLE", "MODEL_INVALID"):
            st.warning(f"Solver: {res.get('solver_status')}. Zero-eligibility tasks: {res.get('zero_eligibility')}")
        else:
            st.success(f"Revised plan proposed (version {res['new_version_id']}). Solver: {res.get('solver_status')} in {res.get('runtime',0):.2f}s")
            st.session_state.pending_replan = res
            # show diff
            d = res["diff"]
            st.subheader("Before / After diff")
            st.write("Moved assignments:", d["moved"])
            st.write("Shifted tasks:", d["shifted"])
            st.info("Locked items untouched. Approve on Approval page or apply below.")
            if st.button("Approve revised plan"):
                conn = get_conn(DB_PATH)
                conn.execute("UPDATE schedule_versions SET status='approved', approved_by=?, approved_at=? WHERE id=?",
                             (role, __import__("datetime").datetime.now().isoformat(timespec="seconds"), res["new_version_id"]))
                conn.execute("UPDATE schedule_versions SET status='superseded' WHERE status='approved' AND id<>?", (res["new_version_id"],))
                conn.commit()
                conn.close()
                log_action(role, role, "approve_replan", res["new_version_id"], before=current_vid, after=res["new_version_id"], reason=f"replan {event_type}", version_id=res["new_version_id"], db_path=DB_PATH)
                add_alert("replan", "info", f"Revised plan {res['new_version_id']} approved.", link="Schedule Gantt")
                st.success("Approved.")
                st.rerun()

    st.divider()
    st.subheader("Simulate impossible case")
    st.caption("Example: all certified 5-axis staff absent -> zero-eligibility tasks reported, no invented assignment.")
    if st.button("Run impossible case (5-axis staff absent)"):
        policy = get_policy(DB_PATH)
        conn = get_conn(DB_PATH)
        conn.execute("UPDATE employees SET active=0 WHERE id IN ('E07','E08')")
        conn.commit()
        conn.close()
        orders = [r["id"] for r in get_conn(DB_PATH).execute("SELECT id FROM orders").fetchall()]
        from core.solver import solve
        res = solve(DB_PATH, orders, policy, time_limit_sec=5.0)
        # restore
        conn = get_conn(DB_PATH)
        conn.execute("UPDATE employees SET active=1 WHERE id IN ('E07','E08')")
        conn.commit()
        conn.close()
        st.write("Solver status:", res["status"])
        st.write("Zero-eligibility tasks:", res.get("zero_eligibility", []))
        st.info("No assignment invented. Offered options: extend due date, overtime within caps, reschedule maintenance.")