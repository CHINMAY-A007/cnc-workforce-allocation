from __future__ import annotations

import json
from datetime import timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from core.config import resolve_horizon_start
from core.db import DB_PATH, get_conn
from core.models import Assignment
from ui.components import page_header, presenter_panel


def _slot_to_dt(slot, hs):
    day = slot // (24 * 4)
    minute = (slot % (24 * 4)) * 15
    d = hs + timedelta(days=day)
    hh, mm = divmod(minute, 60)
    return pd.Timestamp(d.year, d.month, d.day, hh, mm)


def render():
    page_header("Schedule Gantt", "Gantt chart by employee or work center, with filters.")
    presenter_panel("Gantt")

    conn = get_conn(DB_PATH)
    versions = [r["id"] for r in conn.execute("SELECT id FROM schedule_versions ORDER BY created_at DESC").fetchall()]
    conn.close()
    if not versions:
        st.info("No schedule yet. Generate one on AI Allocation Proposal.")
        return
    vid = st.selectbox("Version", versions)
    view = st.radio("View by", ["Employee", "Work Center"], horizontal=True)
    conn = get_conn(DB_PATH)
    assigns = [dict(r) for r in conn.execute("SELECT * FROM version_assignments WHERE version_id=?", (vid,)).fetchall()]
    tasks = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM tasks").fetchall()}
    emps = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM employees").fetchall()}
    conn.close()

    hs = resolve_horizon_start(__import__("core.policy", fromlist=["get_policy"]).get_policy(DB_PATH))
    rows = []
    for a in assigns:
        emp_ids = json.loads(a["employee_ids"])
        label = (", ".join(emps[e]["name"] for e in emp_ids)) if view == "Employee" else a["work_center_id"]
        t = tasks.get(a["task_id"], {})
        rows.append({
            "Task": a["task_id"] + (" 🔒" if a["locked"] else ""),
            "Resource": label,
            "Start": _slot_to_dt(a["start_slot"], hs),
            "Finish": _slot_to_dt(a["end_slot"], hs),
            "Order": t.get("order_id", ""),
            "Locked": bool(a["locked"]),
        })
    if not rows:
        st.info("No assignments.")
        return
    df = pd.DataFrame(rows)
    # filters
    order_f = st.multiselect("Filter by order", sorted(df["Order"].unique()))
    if order_f:
        df = df[df["Order"].isin(order_f)]
    res_f = st.multiselect("Filter by resource", sorted(df["Resource"].unique()))
    if res_f:
        df = df[df["Resource"].isin(res_f)]

    fig = px.timeline(df, x_start="Start", x_end="Finish", y="Resource", color="Order", text="Task")
    fig.update_yaxes(autorange="reversed")
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Assignments table")
    st.dataframe(df, use_container_width=True)