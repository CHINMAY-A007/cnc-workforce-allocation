"""Configuration, policy defaults and calendar helpers for the CNC workforce demo.

Everything a presenter might want to change lives here or in the policy table
(editable on the Settings screen): working days, shifts, overtime caps, objective
weights, and the demo date logic.

Demo dates: the plan always starts on a real, upcoming working day (never in the
past). Set DEMO_EPOCH=YYYY-MM-DD to pin the first planning day, and DEMO_TZ to
change the time zone (default Asia/Kolkata).
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

SLOT_MINUTES = 15
SLOTS_PER_HOUR = 60 // SLOT_MINUTES
SLOTS_PER_DAY = 24 * SLOTS_PER_HOUR
TZ_NAME = os.environ.get("DEMO_TZ", "Asia/Kolkata")
TZ = ZoneInfo(TZ_NAME)

DEFAULT_POLICY: Dict[str, Any] = {
    "company": "Sample CNC Works, Bangalore (demo data)",
    "horizon_days": 7,
    "horizon_start": None,  # set when demo data is created
    "working_weekdays": [0, 1, 2, 3, 4, 5],  # Mon=0 .. Sun=6 ; Sunday off (demo assumption)
    "shifts": {
        "A": {"start": "06:00", "end": "14:00"},
        "B": {"start": "14:00", "end": "22:00"},
    },
    "standard_daily_hours": 8,
    "overtime_cap_hours": 2,
    "max_daily_hours_cap": 10,
    "priority_weights": {"Urgent": 4, "High": 2, "Normal": 1},
    "objective_weights": {
        "on_time": 10.0, "overtime": 3.0, "balance": 2.0,
        "makespan": 1.0, "reassignment": 2.0, "continuity": 2.0,
    },
    "approval_levels": {
        "reassign": "Production Manager",
        "approve_schedule": "Production Manager",
        "unlock_locked": "Production Manager",
    },
    "replanning": {"affected_only": True, "never_change_locked": True},
}

PRESETS = {
    "balanced": {"label": "Balanced", "weights": {"on_time": 10, "overtime": 3, "balance": 2, "makespan": 1, "reassignment": 2, "continuity": 2}},
    "rush": {"label": "Rush mode", "weights": {"on_time": 30, "overtime": 1, "balance": 0.5, "makespan": 3, "reassignment": 1, "continuity": 0.5}},
    "cost": {"label": "Cost saver", "weights": {"on_time": 6, "overtime": 12, "balance": 3, "makespan": 0.5, "reassignment": 2, "continuity": 2}},
}

WEIGHT_LABELS = {
    "on_time": "On-time delivery",
    "overtime": "Less overtime",
    "balance": "Balanced workload",
    "makespan": "Finish everything early",
    "reassignment": "Fewer changes to the plan",
    "continuity": "Same person continues a job",
}

STATUSES = ["Planned", "Assigned", "In Progress", "Blocked", "Completed", "Cancelled"]


# ---------- dates ----------
def now_local() -> datetime:
    return datetime.now(TZ)


def today_local() -> date:
    return now_local().date()


def planning_start(policy: Dict[str, Any] | None = None) -> date:
    """First planning day: DEMO_EPOCH if set, else the next working day after today."""
    env = os.environ.get("DEMO_EPOCH")
    if env:
        return datetime.strptime(env, "%Y-%m-%d").date()
    wd = (policy or DEFAULT_POLICY)["working_weekdays"]
    d = today_local() + timedelta(days=1)
    for _ in range(8):
        if d.weekday() in wd:
            return d
        d += timedelta(days=1)
    return d


def resolve_horizon_start(policy: Dict[str, Any]) -> date:
    if policy.get("horizon_start"):
        return datetime.strptime(policy["horizon_start"], "%Y-%m-%d").date()
    return planning_start(policy)


def slot_to_dt(slot: int, hs: date) -> datetime:
    return datetime.combine(hs, datetime.min.time()) + timedelta(minutes=SLOT_MINUTES * int(slot))


def fmt_slot(slot: int | None, hs: date) -> str:
    if slot is None:
        return ""
    return slot_to_dt(slot, hs).strftime("%a %d %b, %H:%M")


def iso_slot(slot: int, hs: date) -> str:
    return slot_to_dt(slot, hs).isoformat(timespec="minutes")


# ---------- policy ----------
def shift_slots(shift: str, policy: Dict[str, Any]) -> tuple[int, int]:
    s = policy["shifts"][shift]
    sh, sm = (int(x) for x in s["start"].split(":"))
    eh, em = (int(x) for x in s["end"].split(":"))
    return sh * SLOTS_PER_HOUR + sm // SLOT_MINUTES, eh * SLOTS_PER_HOUR + em // SLOT_MINUTES


def load_policy(conn: sqlite3.Connection) -> Dict[str, Any]:
    out = json.loads(json.dumps(DEFAULT_POLICY))
    for key, value in conn.execute("SELECT key, value FROM policy").fetchall():
        try:
            out[key] = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            out[key] = value
    return out


def save_policy(conn: sqlite3.Connection, policy: Dict[str, Any]) -> None:
    for key, value in policy.items():
        conn.execute(
            "INSERT INTO policy (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )
    conn.commit()


def is_working_day(d: date, policy: Dict[str, Any]) -> bool:
    return d.weekday() in policy["working_weekdays"]


def get_policy(db_path=None) -> Dict[str, Any]:
    from core.db import get_conn
    conn = get_conn(db_path)
    try:
        return load_policy(conn)
    finally:
        conn.close()


def set_policy(data: Dict[str, Any], db_path=None) -> None:
    from core.db import get_conn
    conn = get_conn(db_path)
    try:
        save_policy(conn, data)
    finally:
        conn.close()
