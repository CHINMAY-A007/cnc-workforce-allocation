from __future__ import annotations

import json
import streamlit as st
import pandas as pd

from core.db import DB_PATH, get_conn
from core.tasks import generate_tasks, list_tasks
from core.notes import parse_notes
from ui.components import page_header, presenter_panel


def render():
    page_header("Orders and Tasks", "Read orders from the Simulated ERP, create new orders, and auto-generate tasks from the product routing.")
    presenter_panel("Orders")

    conn = get_conn(DB_PATH)
    orders = [dict(r) for r in conn.execute("SELECT * FROM orders ORDER BY id").fetchall()]
    products = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM products").fetchall()}
    conn.close()

    st.subheader("Orders (Simulated ERP)")
    if orders:
        df = pd.DataFrame(orders)
        df["product"] = df["product_id"].map(lambda x: products.get(x, {}).get("name", x))
        st.dataframe(df[["id", "product", "quantity", "priority", "due_date", "status", "customer_commitment"]], use_container_width=True)
    else:
        st.info("No orders yet. Create one below.")

    st.divider()
    st.subheader("New Order")
    with st.form("new_order"):
        prod = st.selectbox("Product", list(products.keys()), format_func=lambda x: products[x]["name"])
        qty = st.number_input("Quantity", min_value=1, value=10)
        due = st.date_input("Due date")
        prio = st.selectbox("Priority", ["Urgent", "High", "Normal"])
        cust = st.text_input("Customer commitment", "Demo customer")
        notes = st.text_area("Optional free-text notes (keyword-based parser)")
        submitted = st.form_submit_button("Create Order")
    if submitted:
        import uuid
        oid = "ORD-" + uuid.uuid4().hex[:6].upper()
        conn = get_conn(DB_PATH)
        conn.execute("INSERT INTO orders (id,product_id,quantity,priority,due_date,status,customer_commitment,notes,created_by) VALUES (?,?,?,?,?,?,?,?,?)",
                     (oid, prod, int(qty), prio, due.isoformat(), "Released", cust, notes, "demo"))
        conn.commit()
        conn.close()
        st.success(f"Order {oid} created.")
        if notes.strip():
            parsed = parse_notes(notes)
            st.markdown("**Note parser (keyword-based) result:**")
            st.json(parsed)
            st.warning("This parser uses keyword matching only. It catches only the phrasings it knows; unmatched phrases are rejected, never silently applied.")
            # validate against known skills/certs
            from core.notes import KNOWN_SKILLS, KNOWN_CERTS
            invalid = [s for s in parsed["skills"] if s not in KNOWN_SKILLS] + [c for c in parsed["certs"] if c not in KNOWN_CERTS]
            if invalid:
                st.error(f"Rejected unknown requirements: {invalid}")
            if parsed["rejected"]:
                st.info(f"Unmatched phrases (not applied): {parsed['rejected']}")
        # generate tasks
        generate_tasks(oid, DB_PATH)
        st.success("Tasks generated from routing.")

    st.divider()
    st.subheader("Generate Tasks for an Order")
    sel = st.selectbox("Select order", [o["id"] for o in orders] if orders else [])
    if st.button("Generate / Regenerate Tasks"):
        if sel:
            generate_tasks(sel, DB_PATH)
            st.success(f"Tasks generated for {sel}")

    st.divider()
    st.subheader("Tasks")
    to_show = st.selectbox("Show tasks for", ["All"] + [o["id"] for o in orders])
    oid_filter = None if to_show == "All" else to_show
    tasks = list_tasks(oid_filter, DB_PATH)
    if tasks:
        tdf = pd.DataFrame([{
            "id": t.id, "order": t.order_id, "seq": t.seq, "name": t.name,
            "duration_min": t.duration_min, "skill": t.required_skill, "level": t.min_level,
            "role": t.required_role, "work_center": t.work_center_kind, "deps": ", ".join(t.depends_on),
            "quality_gate": "Yes" if t.is_quality_gate else "",
        } for t in tasks])
        st.dataframe(tdf, use_container_width=True)
        st.caption("Dependency flow: each task lists prerequisite task IDs in 'deps'.")
    else:
        st.info("No tasks yet.")