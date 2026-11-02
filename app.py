from __future__ import annotations

import streamlit as st

from ui.components import sidebar_role_switcher

st.set_page_config(page_title="CNC Workforce Allocation (Demo)", layout="wide")

role = sidebar_role_switcher()

# Page definitions
import pages.home as p_home
import pages.orders as p_orders
import pages.workforce as p_workforce
import pages.allocation as p_allocation
import pages.gantt as p_gantt
import pages.approval as p_approval
import pages.mytasks as p_mytasks
import pages.progress as p_progress
import pages.reports as p_reports
import pages.audit as p_audit
import pages.requirements as p_requirements

# Role-based page visibility
ALL_PAGES = [
    ("Home / Guided Demo", p_home, ["Production Manager", "Engineer/Supervisor", "Worker", "HR/Workforce Admin", "ERP Administrator"]),
    ("Orders and Tasks", p_orders, ["Production Manager", "Engineer/Supervisor", "ERP Administrator"]),
    ("Workforce and Skill Matrix", p_workforce, ["Production Manager", "HR/Workforce Admin", "ERP Administrator"]),
    ("AI Allocation Proposal", p_allocation, ["Production Manager", "Engineer/Supervisor", "ERP Administrator"]),
    ("Schedule Gantt", p_gantt, ["Production Manager", "Engineer/Supervisor", "ERP Administrator"]),
    ("Approval and Reassignment", p_approval, ["Production Manager", "ERP Administrator"]),
    ("My Tasks", p_mytasks, ["Worker", "Engineer/Supervisor", "Production Manager"]),
    ("Live Progress and Alerts", p_progress, ["Production Manager", "Engineer/Supervisor", "ERP Administrator"]),
    ("Reports", p_reports, ["Production Manager", "ERP Administrator"]),
    ("Audit and Settings", p_audit, ["Production Manager", "ERP Administrator"]),
    ("Requirements Coverage and How It Works", p_requirements, ["Production Manager", "Engineer/Supervisor", "Worker", "HR/Workforce Admin", "ERP Administrator"]),
]

visible = [p for p in ALL_PAGES if role in p[2]]
pages = [st.Page(p[1].render, title=p[0], url_path=p[0].lower().replace(" ", "-").replace("/", "")) for p in visible]
nav = st.navigation(pages)
nav.run()