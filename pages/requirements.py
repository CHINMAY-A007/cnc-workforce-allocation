from __future__ import annotations

import streamlit as st

from core.db import DB_PATH, get_conn
from core.requirements import list_requirements
from ui.components import page_header, presenter_panel

# Flow diagram as text
FLOW = """
Order -> Tasks (from routing) -> Eligibility (who qualifies / excluded & why)
-> Solver (CP-SAT) -> Manager Approval -> ERP (simulated)
"""


def render():
    page_header("Requirements Coverage and How It Works", "FR-01..FR-15 checklist (ticks only where verified) plus flow diagram.")
    presenter_panel("Requirements")

    st.subheader("Flow")
    st.code(FLOW.strip())

    st.subheader("Coverage (evidence-gated)")
    reqs = list_requirements(DB_PATH)
    for r in reqs:
        tick = "✅" if r["status"] == "verified" else "⬜ not yet verified"
        st.write(f"- **{r['fr_id']}** {r['title']} - {r['screen']} - {tick}")
        if r["evidence"]:
            st.caption(f"Evidence: {r['evidence']}")

    st.subheader("About / How it works")
    st.markdown(
        "Scheduling uses Google OR-Tools CP-SAT (Apache 2.0, free). "
        "The order-notes reader is keyword matching, not language understanding. "
        "The sidebar role switcher is a demo simulation of permissions, not real authentication."
    )