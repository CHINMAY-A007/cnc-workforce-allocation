"""Shared UI helpers: page header, presenter script, role switcher, styling."""

from __future__ import annotations

import streamlit as st


ROLES = ["Production Manager", "Engineer/Supervisor", "Worker", "HR/Workforce Admin", "ERP Administrator"]

PAGE_SCRIPTS = {
    "Home": "1) Reset demo if needed. 2) Walk the 5 steps top to bottom.",
    "Orders": "Create an urgent order with the titanium note; show task generation.",
    "Workforce": "Show skill matrix heatmap; point out expired certs.",
    "Allocation": "Pick Balanced, Generate Schedule, open Why panel.",
    "Gantt": "Toggle by employee / work center; filter by order.",
    "Approval": "Reassign (reason required), lock two, approve.",
    "MyTasks": "Switch to Worker role; show large buttons.",
    "Progress": "Simulate absence; approve diff; then impossible case.",
    "Reports": "Utilization, bottleneck, planned vs actual.",
    "Audit": "Audit log, weights, requirements coverage.",
    "Requirements": "FR-01..FR-15; ticks only where verified.",
}


def inject_css():
    st.markdown("""
    <style>
    .block-container { padding-top: 1.5rem; padding-bottom: 2rem; max-width: 1200px; }
    h1 { font-size: 1.9rem !important; font-weight: 700 !important; }
    h2 { font-size: 1.35rem !important; font-weight: 600 !important; margin-top: 1.2rem !important; }
    h3 { font-size: 1.15rem !important; font-weight: 600 !important; }
    .stCaption { font-size: 0.95rem !important; color: #57606a !important; }
    .stButton > button { border-radius: 8px; font-weight: 600; }
    .stButton > button[kind="primary"] { background: #1f6feb; }
    div[data-testid="metric-container"] { background: #f6f8fa; border-radius: 10px; padding: 0.6rem 0.8rem; }
    .badge { display:inline-block; padding:2px 8px; border-radius:12px; font-size:0.8rem; font-weight:600; }
    .badge-green { background:#dafbe1; color:#1a7f37; }
    .badge-amber { background:#fff8c5; color:#9a6700; }
    .badge-red { background:#ffebe9; color:#cf222e; }
    .badge-blue { background:#ddf4ff; color:#0969da; }
    .card { background:#ffffff; border:1px solid #d0d7de; border-radius:12px; padding:1rem 1.2rem; margin-bottom:0.8rem; }
    </style>
    """, unsafe_allow_html=True)


def sidebar_role_switcher():
    st.sidebar.markdown("### Demo role switcher")
    st.sidebar.caption("DEMO SIMULATION ONLY - not production authentication or real access control.")
    if "role" not in st.session_state:
        st.session_state.role = "Production Manager"
    role = st.sidebar.selectbox("Act as", ROLES, index=ROLES.index(st.session_state.role), key="role_select")
    st.session_state.role = role
    st.sidebar.divider()
    st.sidebar.markdown("**Sample CNC Works, Bangalore (demo data)**")
    st.sidebar.caption("Simulated ERP (local SQLite).")
    return role


def page_header(title, helper):
    st.title(title)
    st.caption(helper)


def presenter_panel(key):
    with st.expander("Demo script (presenter)", expanded=False):
        st.markdown(PAGE_SCRIPTS.get(key, ""))


def metric_row(items):
    cols = st.columns(len(items))
    for c, (label, value, help_) in zip(cols, items):
        c.metric(label, value, help=help_)


def status_badge(status):
    color = {"Planned": "blue", "Assigned": "blue", "In Progress": "amber",
             "Blocked": "red", "Completed": "green", "Cancelled": "red"}.get(status, "blue")
    cls = {"green": "badge-green", "amber": "badge-amber", "red": "badge-red", "blue": "badge-blue"}[color]
    return f'<span class="badge {cls}">{status}</span>'