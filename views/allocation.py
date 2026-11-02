from __future__ import annotations

import json
import streamlit as st
import pandas as pd

from core.db import DB_PATH, get_conn
from core.policy import get_policy, set_policy
from core.tasks import list_tasks
from core.eligibility import eligible_pairs
from core.solver import solve, validate_schedule
from core.audit import log_action
from core.alerts import add_alert
from ui.components import page_header, presenter_panel


PRESETS = {
    "Balanced": {"on_time": 10.0, "overtime": 3.0, "balance": 2.0, "makespan": 1.0, "reassignment": 2.0, "continuity": 2.0},
    "Rush mode": {"on_time": 20.0, "overtime": 1.0, "balance": 0.5, "makespan": 2.0, "reassignment": 0.5, "continuity": 0.5},
    "Cost saver": {"on_time": 5.0, "overtime": 8.0, "balance": 3.0, "makespan": 1.0, "reassignment": 2.0, "continuity": 2.0},
}


def render():
    page_header("AI Allocation Proposal", "Choose objectives, generate an optimized schedule, and review assignments with reasons.")
    presenter_panel("Allocation")

    role = st.session_state.get("role", "Production Manager")
    policy = get_policy(DB_PATH)

    st.subheader("Objective preset")
    preset = st.selectbox("Preset", list(PRESETS.keys()))
    weights = dict(PRESETS[preset])
    st.caption("Adjust weights (higher = more important).")
    for k in weights:
        weights[k] = st.slider(k, 0.0, 30.0, float(weights[k]), 0.5)
    if st.button("Save weights to policy"):
        policy["objective_weights"] = weights
        set_policy(policy, DB_PATH, actor=role, role=role)
        st.success("Weights saved.")

    st.divider()
    st.subheader("Generate Schedule")
    orders = [r["id"] for r in get_conn(DB_PATH).execute("SELECT id FROM orders").fetchall()]
    selected_orders = st.multiselect("Orders to schedule", orders, default=orders)
    if st.button("Generate Schedule", type="primary"):
        with st.spinner("Solving..."):
            result = solve(DB_PATH, selected_orders, policy, time_limit_sec=10.0)
        st.session_state.last_solve = result
        st.session_state.last_orders = selected_orders
        st.success(f"Solver status: {result['status']} | Solved in {result['runtime']:.2f} seconds")
        if result["status"] in ("OPTIMAL", "FEASIBLE"):
            # validate
            tasks = []
            for oid in selected_orders:
                tasks += list_tasks(oid, DB_PATH)
            # tasks as dicts
            tdicts = [t.__dict__ for t in tasks]
            viols = validate_schedule(result["assignments"], tdicts, policy, DB_PATH)
            if viols:
                st.error("Constraint violations detected: " + "; ".join(viols))
            else:
                st.success("No hard-constraint violations.")
            # create draft version
            import uuid
            from datetime import datetime as _dt
            vid = "V-" + uuid.uuid4().hex[:8].upper()
            conn = get_conn(DB_PATH)
            conn.execute("INSERT INTO schedule_versions (id,created_at,status,solver_status,solver_runtime_sec,objective_value,notes) VALUES (?,?,?,?,?,?,?)",
                         (vid, _dt.now().isoformat(timespec="seconds"), "draft", result["status"], result["runtime"], result["objective"] or 0.0, "AI proposal"))
            for a in result["assignments"]:
                conn.execute("INSERT INTO version_assignments (version_id,task_id,employee_ids,work_center_id,start_slot,end_slot,locked,why) VALUES (?,?,?,?,?,?,?,?)",
                             (vid, a.task_id, json.dumps(a.employee_ids), a.work_center_id, a.start_slot, a.end_slot, 1 if a.locked else 0, json.dumps(a.why)))
            # persist planned
            for a in result["assignments"]:
                conn.execute("UPDATE tasks SET planned_start=?, planned_end=?, employee_ids=?, work_center_id=?, locked=? WHERE id=?",
                             (a.start_slot, a.end_slot, json.dumps(a.employee_ids), a.work_center_id, 1 if a.locked else 0, a.task_id))
            conn.commit()
            conn.close()
            st.session_state.current_version = vid
            add_alert("schedule", "info", f"New AI proposal {vid} generated.", link="Approval and Reassignment")
            log_action(role, role, "generate_schedule", vid, before=None, after={"status": result["status"]}, reason="AI proposal", version_id=vid, db_path=DB_PATH)
        elif result["status"] == "INFEASIBLE":
            st.error("Infeasible: no valid allocation. Zero-eligibility tasks:")
            for z in result.get("zero_eligibility", []):
                st.write("-", z)
            st.info("Likely blocking constraints: run relaxation tests (extend due date, overtime within caps, reschedule maintenance) - offered on Progress page.")
        else:
            st.warning("Solver ran out of time (UNKNOWN). Last approved schedule kept; offer manual planning.")

    # show results
    result = st.session_state.get("last_solve")
    if result and result.get("assignments"):
        st.divider()
        st.subheader("Proposed Assignments")
        rows = []
        for a in result["assignments"]:
            rows.append({
                "task": a.task_id,
                "employees": ", ".join(a.employee_ids),
                "work_center": a.work_center_id,
                "start_slot": a.start_slot,
                "end_slot": a.end_slot,
                "locked": "🔒" if a.locked else "",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True)

        st.subheader("Why this person?")
        tid = st.selectbox("Task", [a.task_id for a in result["assignments"]])
        a = next(x for x in result["assignments"] if x.task_id == tid)
        st.markdown(f"**Employees:** {', '.join(a.employee_ids)}")
        st.markdown(f"**Work center:** {a.work_center_id}")
        st.markdown(f"**Reason data:** {json.dumps(a.why, indent=2)}")
        st.caption("Skill match, availability, workload balance, continuity, and alternatives considered.")

        st.subheader("Conflict panel")
        # eligibility preview for first task
        tasks = list_tasks(None, DB_PATH)
        if tasks:
            t = tasks[0]
            er = eligible_pairs(t, policy, DB_PATH)
            st.write(f"Task {t.id}: {len(er.candidates)} eligible, {len(er.excluded)} excluded.")
            with st.expander("Excluded (why)"):
                for ex in er.excluded[:20]:
                    st.write(f"- {ex['person']}: {', '.join(ex['reasons'])}")