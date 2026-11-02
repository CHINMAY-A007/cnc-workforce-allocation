from __future__ import annotations

import json
from datetime import date

import pandas as pd
import plotly.express as px
import streamlit as st

from core.db import DB_PATH, get_conn
from core.eligibility import skill_matrix
from ui.components import page_header, presenter_panel


def render():
    page_header("Workforce and Skill Matrix", "Workforce master, skill matrix heatmap, and certification expiry flags. Editable by HR / Workforce Admin role.")
    presenter_panel("Workforce")

    role = st.session_state.get("role", "Production Manager")
    editable = role == "HR/Workforce Admin"

    conn = get_conn(DB_PATH)
    emps = [dict(r) for r in conn.execute("SELECT * FROM employees ORDER BY id").fetchall()]
    conn.close()

    st.subheader("Workforce Master")
    edf = pd.DataFrame(emps)
    st.dataframe(edf, use_container_width=True)

    st.divider()
    st.subheader("Skill Matrix (employees x skills)")
    emps2, skills, matrix, cert_flags = skill_matrix(DB_PATH)
    rows = []
    for e in emps2:
        for s in skills:
            rows.append({"employee": e["name"], "skill": s, "level": matrix[e["id"]][s]})
    mdf = pd.DataFrame(rows)
    pivot = mdf.pivot(index="employee", columns="skill", values="level").fillna(0)
    fig = px.imshow(pivot, text_auto=True, aspect="auto", color_continuous_scale="Blues",
                    title="Skill levels (0 = none, 5 = expert)")
    st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("Certification Expiry Flags")
    today = date.today().isoformat()
    cert_rows = []
    conn = get_conn(DB_PATH)
    for c in conn.execute("SELECT * FROM certs").fetchall():
        exp = c["expires_on"]
        status = "VALID"
        if exp < today:
            status = "EXPIRED"
        elif exp <= (date.fromisoformat(today).replace(day=28) if False else date.fromisoformat(today)).isoformat():
            pass
        # expiring within 30 days
        from datetime import date as _d, timedelta
        if exp >= today and exp <= (_d.fromisoformat(today) + timedelta(days=30)).isoformat():
            status = "EXPIRING SOON"
        emp = conn.execute("SELECT name FROM employees WHERE id=?", (c["employee_id"],)).fetchone()
        cert_rows.append({"employee": emp["name"] if emp else c["employee_id"], "cert": c["cert"],
                          "expires": exp, "status": status})
    conn.close()
    cdf = pd.DataFrame(cert_rows)
    st.dataframe(cdf, use_container_width=True)

    if editable:
        st.divider()
        st.subheader("Edit Workforce (HR role)")
        st.caption("HR can update skills/leave. Demo: edits are written to the Simulated ERP (SQLite).")
        with st.form("edit_skill"):
            eid = st.selectbox("Employee", [e["id"] for e in emps], format_func=lambda x: next(e["name"] for e in emps if e["id"] == x))
            skill = st.selectbox("Skill", skills)
            level = st.slider("Level", 0, 5, 3)
            if st.form_submit_button("Save skill level"):
                c = get_conn(DB_PATH)
                c.execute("INSERT OR REPLACE INTO skills (employee_id,skill,level) VALUES (?,?,?)", (eid, skill, level))
                c.commit()
                c.close()
                st.success("Saved.")
                st.rerun()
    else:
        st.info("Switch role to 'HR/Workforce Admin' to edit workforce data.")