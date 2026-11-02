"""Configuration and policy constants for the CNC workforce allocation demo.

All department rules, shifts, working days, weights and limits come from here
(or from the policy table in SQLite). Nothing is hard-coded in business logic.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any, Dict, List

SLOT_MINUTES = 15
SLOTS_PER_HOUR = 60 // SLOT_MINUTES

# Default policy (proposed assumption 1: 7-day horizon, Mon-Sat working, Sun off).
DEFAULT_POLICY: Dict[str, Any] = {
    "company": "Sample CNC Works, Bangalore (demo data)",
    "horizon_days": 7,
    "horizon_start": None,  # resolved at runtime to next Monday
    "working_weekdays": [0, 1, 2, 3, 4, 5],  # Mon=0..Sun=6 ; Sunday off
    "shifts": {
        "A": {"start": "06:00", "end": "14:00"},
        "B": {"start": "14:00", "end": "22:00"},
    },
    "standard_daily_hours": 8,
    "overtime_cap_hours": 2,
    "max_daily_hours_cap": 10,
    "priority_weights": {"Urgent": 4, "High": 2, "Normal": 1},
    "objective_weights": {
        "on_time": 10.0,
        "overtime": 3.0,
        "balance": 2.0,
        "makespan": 1.0,
        "reassignment": 2.0,
        "continuity": 2.0,
    },
    "approval_levels": {
        "reassign": "Production Manager",
        "approve_schedule": "Production Manager",
        "unlock_locked": "Production Manager",
    },
    "replanning": {
        "affected_only": True,
        "never_change_locked": True,
    },
}


def next_monday(d: date | None = None) -> date:
    d = d or date.today()
    days_ahead = (0 - d.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return d + timedelta(days=days_ahead)


def resolve_horizon_start(policy: Dict[str, Any]) -> date:
    if policy.get("horizon_start"):
        return datetime.strptime(policy["horizon_start"], "%Y-%m-%d").date()
    return next_monday()


def shift_slots(shift: str, policy: Dict[str, Any]) -> tuple[int, int]:
    """Return (start_slot, end_slot) within a single day for a shift."""
    s = policy["shifts"][shift]
    sh, sm = (int(x) for x in s["start"].split(":"))
    eh, em = (int(x) for x in s["end"].split(":"))
    return sh * SLOTS_PER_HOUR + sm // SLOT_MINUTES, eh * SLOTS_PER_HOUR + em // SLOT_MINUTES


def load_policy(conn: sqlite3.Connection) -> Dict[str, Any]:
    cur = conn.execute("SELECT key, value FROM policy")
    out = dict(DEFAULT_POLICY)
    for key, value in cur.fetchall():
        try:
            out[key] = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            out[key] = value
    if "objective_weights" not in out:
        out["objective_weights"] = DEFAULT_POLICY["objective_weights"]
    if "shifts" not in out:
        out["shifts"] = DEFAULT_POLICY["shifts"]
    if "working_weekdays" not in out:
        out["working_weekdays"] = DEFAULT_POLICY["working_weekdays"]
    return out


def save_policy(conn: sqlite3.Connection, policy: Dict[str, Any]) -> None:
    for key, value in policy.items():
        conn.execute(
            "INSERT INTO policy (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )
    conn.commit()


def is_working_day(d: date, policy: Dict[str, Any]) -> bool:
    return d.weekday() in policy["working_weekdays"]


def slots_for_day(policy: Dict[str, Any]) -> int:
    return 24 * SLOTS_PER_HOUR


def day_start_slot(day_index: int) -> int:
    return day_index * 24 * SLOTS_PER_HOUR


def parse_time(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)