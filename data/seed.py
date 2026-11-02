"""Seed the demo SQLite database with fictional CNC shop data.

Run:  python data/seed.py   (creates data/demo.db)
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import timedelta

from core.config import DEFAULT_POLICY, save_policy, planning_start
from core.db import DB_PATH, get_conn, init_schema, reset_demo
from core.tasks import generate_tasks

SKILLS = [
    "CNC Turning",
    "VMC Milling",
    "5-Axis Programming",
    "Setup",
    "CMM Inspection",
    "Deburring",
    "Packing",
    "Titanium Machining",
]

ROLES = [
    "CNC Turning Operator",
    "VMC Operator",
    "5-Axis Programmer/Engineer",
    "Setup Technician",
    "Quality Inspector",
    "Finishing Worker",
    "Packer",
    "Shift Supervisor",
]

# (id, name, role, team, shift, max_daily, ot_cap, active, leave_dates)
EMPLOYEES = [
    ("E01", "Aarav Sharma", "CNC Turning Operator", "Turning", "A", 8, 2, True, []),
    ("E02", "Priya Nair", "CNC Turning Operator", "Turning", "A", 8, 2, True, [1]),
    ("E03", "Rohan Iyer", "CNC Turning Operator", "Turning", "B", 8, 2, True, []),
    ("E04", "Kavya Reddy", "VMC Operator", "Milling", "A", 8, 2, True, []),
    ("E05", "Arjun Mehta", "VMC Operator", "Milling", "B", 8, 2, True, []),
    ("E06", "Neha Gupta", "VMC Operator", "Milling", "A", 8, 1, True, []),
    ("E07", "Vikram Singh", "5-Axis Programmer/Engineer", "Engineering", "A", 8, 2, True, []),
    ("E08", "Ananya Bose", "5-Axis Programmer/Engineer", "Engineering", "A", 8, 2, True, []),
    ("E09", "Suresh Patil", "Setup Technician", "Setup", "A", 8, 2, True, []),
    ("E10", "Divya Krishnan", "Setup Technician", "Setup", "B", 8, 2, True, []),
    ("E11", "Manish Joshi", "Quality Inspector", "Quality", "A", 8, 1, True, []),
    ("E12", "Pooja Verma", "Quality Inspector", "Quality", "B", 8, 1, True, []),
    ("E13", "Rahul Desai", "Finishing Worker", "Finishing", "A", 8, 2, True, []),
    ("E14", "Sneha Kulkarni", "Finishing Worker", "Finishing", "B", 8, 2, True, []),
    ("E15", "Karan Malhotra", "Packer", "Dispatch", "A", 8, 2, True, []),
    ("E16", "Isha Kapoor", "Packer", "Dispatch", "B", 8, 2, True, []),
    ("E17", "Deepak Rao", "Shift Supervisor", "Supervision", "A", 8, 0, True, []),
    ("E18", "Meera Shah", "Shift Supervisor", "Supervision", "B", 8, 0, True, []),
]

# skill levels: dict employee -> {skill: level}
SKILL_LEVELS = {
    "E01": {"CNC Turning": 4, "Setup": 2, "Deburring": 2},
    "E02": {"CNC Turning": 5, "Titanium Machining": 3, "Setup": 2},
    "E03": {"CNC Turning": 3, "Deburring": 3},
    "E04": {"VMC Milling": 4, "Setup": 2, "Deburring": 1},
    "E05": {"VMC Milling": 5, "Titanium Machining": 2, "Setup": 2},
    "E06": {"VMC Milling": 3, "Packing": 2},
    "E07": {"5-Axis Programming": 5, "Setup": 4, "VMC Milling": 3, "Titanium Machining": 4},
    "E08": {"5-Axis Programming": 4, "Setup": 3, "VMC Milling": 2},
    "E09": {"Setup": 5, "CNC Turning": 2, "VMC Milling": 2},
    "E10": {"Setup": 4, "Deburring": 3, "Packing": 2},
    "E11": {"CMM Inspection": 5, "Deburring": 1},
    "E12": {"CMM Inspection": 4, "Packing": 2},
    "E13": {"Deburring": 5, "Packing": 2},
    "E14": {"Deburring": 4, "Packing": 3},
    "E15": {"Packing": 5},
    "E16": {"Packing": 4, "Deburring": 2},
    "E17": {"Setup": 3, "CNC Turning": 2, "VMC Milling": 2},
    "E18": {"Setup": 3, "Packing": 2},
}

# certs: employee -> list (cert, expires_on)
WORK_CENTERS = [
    ("TC-1", "CNC Turning Center 1", "Turning"),
    ("TC-2", "CNC Turning Center 2", "Turning"),
    ("VMC-1", "Vertical Machining Center 1", "Milling"),
    ("VMC-2", "Vertical Machining Center 2", "Milling"),
    ("5AX-1", "5-Axis Machining Center", "5Axis"),
    ("FIN-1", "Deburr and Finishing Bench", "Finishing"),
    ("QC-1", "CMM Inspection Station", "Inspection"),
    ("PK-1", "Packing and Dispatch Bay", "Packing"),
]

# maintenance: (wc, start_slot, end_slot, reason) using day2 (index 1) 4 hours
MAINTENANCE = [
    ("VMC-2", 1 * 24 * 4 + (8 * 4), 1 * 24 * 4 + (12 * 4), "Planned maintenance 4h"),
]

PRODUCTS = [
    ("P-TITANIUM-SHAFT", "Aerospace Titanium Shaft", "Titanium", [
        (1, "Material Cutting", "Turning", 10, 3, "CNC Turning", 3, "CNC Turning Operator", 1, False, []),
        (2, "CNC Turning", "Turning", 25, 5, "CNC Turning", 3, "CNC Turning Operator", 1, False, [1]),
        (3, "5-Axis Milling", "5Axis", 40, 8, "5-Axis Programming", 4, "5-Axis Programmer/Engineer", 2, False, [2]),
        (4, "VMC Milling", "Milling", 20, 4, "VMC Milling", 3, "VMC Operator", 1, False, [2]),
        (5, "Deburring", "Finishing", 15, 2, "Deburring", 3, "Finishing Worker", 1, False, [3, 4]),
        (6, "CMM Inspection", "Inspection", 20, 3, "CMM Inspection", 4, "Quality Inspector", 1, True, [5]),
        (7, "Packing", "Packing", 10, 2, "Packing", 2, "Packer", 1, False, [6]),
    ]),
    ("P-ALU-FLANGE", "Aluminium Flange", "Aluminium", [
        (1, "Material Cutting", "Turning", 8, 2, "CNC Turning", 2, "CNC Turning Operator", 1, False, []),
        (2, "CNC Turning", "Turning", 18, 4, "CNC Turning", 3, "CNC Turning Operator", 1, False, [1]),
        (3, "VMC Milling", "Milling", 15, 3, "VMC Milling", 3, "VMC Operator", 1, False, [2]),
        (4, "Deburring", "Finishing", 10, 2, "Deburring", 2, "Finishing Worker", 1, False, [3]),
        (5, "CMM Inspection", "Inspection", 15, 2, "CMM Inspection", 3, "Quality Inspector", 1, True, [4]),
        (6, "Packing", "Packing", 8, 2, "Packing", 2, "Packer", 1, False, [5]),
    ]),
    ("P-SS-BRACKET", "Stainless Steel Bracket", "Stainless Steel", [
        (1, "Material Cutting", "Turning", 10, 2, "CNC Turning", 2, "CNC Turning Operator", 1, False, []),
        (2, "VMC Milling", "Milling", 25, 5, "VMC Milling", 3, "VMC Operator", 1, False, [1]),
        (3, "Deburring", "Finishing", 12, 2, "Deburring", 3, "Finishing Worker", 1, False, [2]),
        (4, "CMM Inspection", "Inspection", 18, 3, "CMM Inspection", 4, "Quality Inspector", 1, True, [3]),
        (5, "Packing", "Packing", 8, 2, "Packing", 2, "Packer", 1, False, [4]),
    ]),
    ("P-BRASS-VALVE", "Brass Valve Body", "Brass", [
        (1, "Material Cutting", "Turning", 6, 2, "CNC Turning", 2, "CNC Turning Operator", 1, False, []),
        (2, "CNC Turning", "Turning", 16, 3, "CNC Turning", 3, "CNC Turning Operator", 1, False, [1]),
        (3, "VMC Milling", "Milling", 12, 3, "VMC Milling", 2, "VMC Operator", 1, False, [2]),
        (4, "Deburring", "Finishing", 8, 1, "Deburring", 2, "Finishing Worker", 1, False, [3]),
        (5, "CMM Inspection", "Inspection", 12, 2, "CMM Inspection", 3, "Quality Inspector", 1, True, [4]),
        (6, "Packing", "Packing", 6, 1, "Packing", 2, "Packer", 1, False, [5]),
    ]),
    ("P-ALLOY-GEAR", "Alloy Gear Blank", "Alloy Steel", [
        (1, "Material Cutting", "Turning", 12, 3, "CNC Turning", 3, "CNC Turning Operator", 1, False, []),
        (2, "CNC Turning", "Turning", 22, 5, "CNC Turning", 4, "CNC Turning Operator", 1, False, [1]),
        (3, "VMC Milling", "Milling", 20, 4, "VMC Milling", 3, "VMC Operator", 1, False, [2]),
        (4, "Deburring", "Finishing", 10, 2, "Deburring", 2, "Finishing Worker", 1, False, [3]),
        (5, "CMM Inspection", "Inspection", 15, 3, "CMM Inspection", 4, "Quality Inspector", 1, True, [4]),
        (6, "Packing", "Packing", 8, 2, "Packing", 2, "Packer", 1, False, [5]),
    ]),
]

# (id, product, qty, priority, due offset in days from the first planning day, status, customer)
ORDERS = [
    ("ORD-1001", "P-TITANIUM-SHAFT", 12, "Urgent", 3, "Released", "Aero customer commitment"),
    ("ORD-1002", "P-ALU-FLANGE", 40, "High", 4, "Released", "Automotive batch"),
    ("ORD-1003", "P-SS-BRACKET", 25, "Normal", 5, "Released", "General engineering"),
    ("ORD-1004", "P-BRASS-VALVE", 60, "Normal", 2, "Released", "Valve OEM"),
    ("ORD-1005", "P-ALLOY-GEAR", 15, "High", 6, "Released", "Gearbox supplier"),
]

# certificate expiry as days from the first planning day (negative = already expired)
CERT_OFFSETS = {
    "E02": [("Titanium Machining Cert", 240), ("CNC Turning Cert", 58)],
    "E05": [("VMC Operator Cert", 12)],
    "E07": [("5-Axis Programming Cert", 150), ("CMM Inspection Cert", -180)],
    "E08": [("5-Axis Programming Cert", 58)],
    "E11": [("CMM Inspection Cert", 4)],
    "E12": [("CMM Inspection Cert", 115)],
    "E01": [("CNC Turning Cert", -45)],
    "E09": [("Setup Technician Cert", 90)],
    "E10": [("Setup Technician Cert", -30)],
    "E13": [("Deburring Cert", 180)],
    "E15": [("Packing Cert", 300)],
}


def _working_day(d, policy):
    while d.weekday() not in policy["working_weekdays"]:
        d += timedelta(days=1)
    return d


def seed(db_path=None, start=None):
    """Create demo data. All dates are relative to the first planning day, so the demo is
    always realistic whenever it is loaded (never in the past)."""
    conn = get_conn(db_path)
    init_schema(conn)
    policy = json.loads(json.dumps(DEFAULT_POLICY))
    hs = start or planning_start(policy)
    policy["horizon_start"] = hs.isoformat()
    save_policy(conn, policy)
    for e in EMPLOYEES:
        leave = [(hs + timedelta(days=int(x))).isoformat() for x in e[8]]
        conn.execute(
            "INSERT OR REPLACE INTO employees (id,name,role,team,shift,max_daily_hours,overtime_cap_hours,active,leave_dates) VALUES (?,?,?,?,?,?,?,?,?)",
            (e[0], e[1], e[2], e[3], e[4], e[5], e[6], 1 if e[7] else 0, json.dumps(leave)))
    for eid, levels in SKILL_LEVELS.items():
        for skill, lvl in levels.items():
            conn.execute("INSERT OR REPLACE INTO skills (employee_id,skill,level) VALUES (?,?,?)", (eid, skill, lvl))
    for eid, clist in CERT_OFFSETS.items():
        for cert, off in clist:
            conn.execute("INSERT OR REPLACE INTO certs (employee_id,cert,expires_on) VALUES (?,?,?)",
                         (eid, cert, (hs + timedelta(days=off)).isoformat()))
    for wc in WORK_CENTERS:
        conn.execute("INSERT OR REPLACE INTO work_centers (id,name,kind,capacity) VALUES (?,?,?,1)", wc)
    for m in MAINTENANCE:
        conn.execute("INSERT INTO maintenance (work_center_id,start_slot,end_slot,reason) VALUES (?,?,?,?)", m)
    for pid, pname, material, ops in PRODUCTS:
        conn.execute("INSERT OR REPLACE INTO products (id,name,material) VALUES (?,?,?)", (pid, pname, material))
        for op in ops:
            seq, opname, kind, dur, setup, skill, level, role, mp, qg, deps = op
            conn.execute(
                "INSERT OR REPLACE INTO routing_ops (product_id,seq,operation,work_center_kind,duration_min,setup_min,required_skill,min_level,required_role,multi_person,is_quality_gate,depends_on) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (pid, seq, opname, kind, dur, setup, skill, level, role, mp, 1 if qg else 0, json.dumps(deps)))
    for o in ORDERS:
        conn.execute(
            "INSERT OR REPLACE INTO orders (id,product_id,quantity,priority,due_date,status,customer_commitment,notes,created_by) VALUES (?,?,?,?,?,?,?,?,?)",
            (o[0], o[1], o[2], o[3], (hs + timedelta(days=o[4])).isoformat(), o[5], o[6], "", "demo"))
    conn.commit()
    for o in ORDERS:
        generate_tasks(o[0], db_path)
    from core.requirements import FR_TITLES
    for fr, (title, screen) in FR_TITLES.items():
        conn.execute("INSERT OR REPLACE INTO requirements_evidence (fr_id,title,screen,status,evidence) VALUES (?,?,?,?,?)",
                     (fr, title, screen, "not yet verified", ""))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    if "--reset" in sys.argv:
        reset_demo(DB_PATH)
    seed(DB_PATH)
    print("Seeded", DB_PATH)
