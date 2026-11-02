from __future__ import annotations

import json
import streamlit as st
import pandas as pd

from core.db import DB_PATH, get_conn
from core.audit import recent
from core.policy import get_policy, set_policy
from core.requirements import list_requirements, set_status
from ui.components import page_header, presenter_panel


def render():
    page_header("Audit and Settings", "Audit log, policies, objective weights, integrations (mock).")
    presenter_panel("Audit")

    role = st.session_state.get("role", "Production Manager")
    can_edit = role in ("ERP Administrator", "Production Manager")

    st.subheader("Audit log (recent)")
    st.dataframe(pd.DataFrame(recent(50, DB_PATH)), use_container_width=True)

    st.divider()
    st.subheader("Policy / weights")
    policy = get_policy(DB_PATH)
    st.json(policy)
    if can_edit:
        st.caption("Weights can be edited on AI Allocation Proposal page; policy saved to Simulated ERP.")

    st.divider()
    st.subheader("Integrations (mock)")
    st.info("Simulated ERP connection: local SQLite. No real ERP integration in this demo.")

    st.divider()
    st.subheader("Requirements coverage (evidence-gated)")
    reqs = list_requirements(DB_PATH)
    for r in reqs:
        tick = "✅" if r["status"] == "verified" else "⬜"
        st.write(f"{tick} {r['fr_id']} - {r['title']} ({r['screen']}) - {r['status']}")