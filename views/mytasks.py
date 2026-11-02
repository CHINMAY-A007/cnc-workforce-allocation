from __future__ import annotations

import json
import streamlit as st
import pandas as pd

from core.db import DB_PATH, get_conn
from core.tasks import update_task_status
from ui.components import page_header, presenter_panel


def render():
    page_header("My Tasks", "Your assigned tasks, shift, due time. Large buttons for mobile use.")
    presenter_panel("MyTasks")

    role = st.session_state.get("role", "Production Manager")
    conn = get_conn(DB_PATH)
    # pick an employee based on role; for Worker view, show all tasks assigned to a selectable employee
    emps = [dict(r) for r in conn.execute("SELECT * FROM employees ORDER BY id").fetchall()]
    conn.close()
    eid = st.selectbox("Employee", [e["id"] for e in emps], format_func=lambda x: next(e["name"] for e in emps if e["id"] == x))
    conn = get_conn(DB_PATH)
    rows = conn.execute("SELECT * FROM tasks").fetchall()
    conn.close()
    filtered = []
    for r in rows:
        try:
            ids = json.loads(r["employee_ids"] or "[]")
        except Exception:
            ids = []
        if eid in ids:
            filtered.append(r)
    rows = filtered
    tasks = [dict(r) for r in rows]
    if not tasks:
        st.info("No tasks assigned.")
        return
    for t in tasks:
        with st.container(border=True):
            st.markdown(f"### {t['name']}")
            st.caption(f"Order {t['order_id']} | {t['duration_min']} min | Status: {t['status']}")
            c1, c2, c3 = st.columns(3)
            if c1.button("Start", key=f"start_{t['id']}"):
                update_task_status(t["id"], "In Progress", actual_start=t.get("planned_start"), db_path=DB_PATH)
                st.rerun()
            if c2.button("Complete", key=f"done_{t['id']}"):
                update_task_status(t["id"], "Completed", actual_end=t.get("planned_end"), db_path=DB_PATH)
                st.rerun()
            if c3.button("Report Issue", key=f"iss_{t['id']}"):
                update_task_status(t["id"], "Blocked", blocker="Reported by worker", db_path=DB_PATH)
                st.rerun()