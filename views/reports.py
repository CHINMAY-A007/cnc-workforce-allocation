from __future__ import annotations

import streamlit as st
import pandas as pd

from core.db import DB_PATH, get_conn
from core.reports import utilization_by_employee, approved_versions, planned_vs_actual, bottleneck_work_center
from core.config import resolve_horizon_start
from ui.components import page_header, presenter_panel


def render():
    page_header("Reports", "Utilization, assigned vs available hours, overdue tasks, workload, overtime, bottlenecks, on-time %, planned vs actual.")
    presenter_panel("Reports")

    conn = get_conn(DB_PATH)
    emps = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM employees").fetchall()}
    conn.close()

    util = utilization_by_employee(DB_PATH)
    st.subheader("Utilization by employee (assigned hours)")
    if util:
        udf = pd.DataFrame([{"employee": emps.get(e, {}).get("name", e), "assigned_hours": h} for e, h in util.items()])
        st.bar_chart(udf.set_index("employee"))
        st.dataframe(udf, use_container_width=True)
    else:
        st.info("No approved schedule yet.")

    st.divider()
    bn = bottleneck_work_center(db_path=DB_PATH)
    st.subheader("Bottleneck (busiest work center)")
    if bn:
        st.write(f"{bn[0]} with {bn[1]:.1f} assigned hours")
    else:
        st.info("No data.")

    st.divider()
    st.subheader("Planned vs Actual")
    pv = planned_vs_actual(DB_PATH)
    st.dataframe(pd.DataFrame(pv), use_container_width=True)

    st.divider()
    st.subheader("Versions")
    st.dataframe(pd.DataFrame(approved_versions(DB_PATH)), use_container_width=True)