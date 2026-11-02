"""Shared UI helpers: page header, presenter script, role switcher."""

from __future__ import annotations

import streamlit as st


ROLES = ["Production Manager", "Engineer/Supervisor", "Worker", "HR/Workforce Admin", "ERP Administrator"]

PAGE_SCRIPTS = {
    "Home": "1) Load demo data if empty. 2) Walk the 5-step banner top to bottom.",
    "Orders": "Create an urgent order with the titanium note; show task generation and dependency flow.",
    "Workforce": "Show skill matrix heatmap; point out expired certs excluding people.",
    "Allocation": "Pick Balanced preset, Generate Schedule, open Why panel and conflict panel.",
    "Gantt": "Toggle by employee / work center; filter by order.",
    "Approval": "Reassign one task (reason required), lock two, approve.",
    "MyTasks": "Switch to Worker role; show My Tasks large buttons.",
    "Progress": "Simulate absence; approve the before/after diff; then simulate impossible case.",
    "Reports": "Show utilization, overtime, bottleneck, on-time %, planned vs actual.",
    "Audit": "Show audit log and policy weights; switch role to see page hiding.",
    "Requirements": "Walk FR-01..FR-15; ticks only where verified.",
}


def sidebar_role_switcher():
    st.sidebar.markdown("### Demo role switcher")
    st.sidebar.caption(
        "DEMO SIMULATION ONLY - this is not production authentication or real access control. "
        "It simulates permissions for presentation."
    )
    if "role" not in st.session_state:
        st.session_state.role = "Production Manager"
    role = st.sidebar.selectbox("Act as", ROLES, index=ROLES.index(st.session_state.role), key="role_select")
    st.session_state.role = role
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