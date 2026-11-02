from __future__ import annotations

import os
import streamlit as st

from core.db import DB_PATH, get_conn, init_schema, is_seeded, reset_demo
from data.seed import seed
from ui.components import page_header, presenter_panel


def _ensure_db():
    conn = get_conn(DB_PATH)
    init_schema(conn)
    if not is_seeded(conn):
        conn.close()
        seed(DB_PATH)
    else:
        conn.close()


def render():
    _ensure_db()
    page_header("Home / Guided Demo", "A 5-step walkthrough: Add Order, Generate Tasks, Get AI Proposal, Review and Approve, Handle a Surprise.")
    presenter_panel("Home")

    st.markdown("**Sample CNC Works, Bangalore (demo data)** - all company, employee, customer and order data is fictional demo data.")
    st.markdown("**Simulated ERP** - orders and workforce data are stored in a local SQLite database, not a real ERP.")

    steps = [
        ("1. Add Order", "Create a new production order (or use the seeded ones).", "Orders and Tasks"),
        ("2. Generate Tasks", "Tasks are auto-created from the product routing.", "Orders and Tasks"),
        ("3. Get AI Proposal", "Run the solver to get an optimized schedule.", "AI Allocation Proposal"),
        ("4. Review and Approve", "Edit, lock, and approve the schedule.", "Approval and Reassignment"),
        ("5. Handle a Surprise", "Simulate an absence or breakdown and replan.", "Live Progress and Alerts"),
    ]
    for title, desc, page in steps:
        with st.container(border=True):
            c1, c2 = st.columns([4, 1])
            c1.markdown(f"**{title}** - {desc}")
            c2.caption(f"Go to: {page}")

    st.divider()
    c1, c2 = st.columns(2)
    if c1.button("Load demo data / Reset demo", type="primary"):
        reset_demo(DB_PATH)
        seed(DB_PATH)
        st.success("Demo data reset.")
        st.rerun()
    if c2.button("Open Orders and Tasks"):
        st.session_state.nav_target = "Orders and Tasks"
        st.rerun()