"""Reports (FR-14): utilization, overtime, bottleneck, on-time %, planned vs actual."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict

from core.config import SLOTS_PER_DAY, SLOTS_PER_HOUR, fmt_slot, now_local, slot_to_dt
from core.db import get_conn
from core.eligibility import Context


def build_report(db, vid=None) -> Dict[str, Any]:
    from core.service import enrich, latest_version_id
    from core.solver import load_orders
    ctx = Context(db)
    basis = "approved"
    if vid is None:
        vid = latest_version_id(db, "approved")
        if vid is None:
            vid = latest_version_id(db)
            basis = "draft"
    if vid is None:
        return {"empty": True, "message": "No schedule yet. Go to Plan and press Generate schedule."}
    det = enrich(db, vid)
    pol = ctx.policy
    std = float(pol["standard_daily_hours"])
    horizon = int(pol["horizon_days"])
    people: Dict[str, dict] = {}
    for eid, e in ctx.emps.items():
        avail_days = [d for d in range(horizon) if ctx.day(d).weekday() in pol["working_weekdays"] and ctx.day(d).isoformat() not in e["leave"] and e["active"]]
        people[eid] = {"id": eid, "name": e["name"], "team": e["team"], "available_hours": round(len(avail_days) * std, 1),
                       "assigned_hours": 0.0, "overtime_hours": 0.0, "_day": {}}
    wc_hours: Dict[str, float] = {w: 0.0 for w in ctx.wcs}
    for a in det["assignments"]:
        h = a["minutes"] / 60
        wc_hours[a["work_center_id"]] += h
        day = a["start_slot"] // SLOTS_PER_DAY
        for e in a["employee_ids"]:
            people[e]["assigned_hours"] += h
            people[e]["_day"][day] = people[e]["_day"].get(day, 0) + h
    for p in people.values():
        p["overtime_hours"] = round(sum(max(0.0, x - std) for x in p["_day"].values()), 2)
        p["assigned_hours"] = round(p["assigned_hours"], 2)
        p["utilization_pct"] = round(100 * p["assigned_hours"] / p["available_hours"], 1) if p["available_hours"] else 0.0
        del p["_day"]
    teams: Dict[str, dict] = {}
    for p in people.values():
        t = teams.setdefault(p["team"], {"team": p["team"], "assigned_hours": 0.0, "available_hours": 0.0, "overtime_hours": 0.0})
        t["assigned_hours"] += p["assigned_hours"]; t["available_hours"] += p["available_hours"]; t["overtime_hours"] += p["overtime_hours"]
    for t in teams.values():
        t["utilization_pct"] = round(100 * t["assigned_hours"] / t["available_hours"], 1) if t["available_hours"] else 0.0
        t["assigned_hours"] = round(t["assigned_hours"], 1); t["overtime_hours"] = round(t["overtime_hours"], 1)
    wc_list = []
    for w, h in wc_hours.items():
        avail = len([d for d in range(horizon) if ctx.day(d).weekday() in pol["working_weekdays"]]) * 16.0
        wc_list.append({"id": w, "name": ctx.wcs[w]["name"], "booked_hours": round(h, 1), "load_pct": round(100 * h / avail, 1) if avail else 0.0})
    wc_list.sort(key=lambda x: -x["booked_hours"])
    bottleneck = wc_list[0] if wc_list and wc_list[0]["booked_hours"] > 0 else None
    on_time = [o for o in det["orders"] if o["status"] != "late"]
    pct = round(100 * len(on_time) / len(det["orders"]), 0) if det["orders"] else 0
    # planned vs actual
    conn = get_conn(db)
    trows = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM tasks").fetchall()}
    conn.close()
    pva, overdue = [], []
    now = now_local().replace(tzinfo=None)
    for a in det["assignments"]:
        t = trows[a["task_id"]]
        ps, pe = slot_to_dt(a["start_slot"], ctx.hs), slot_to_dt(a["end_slot"], ctx.hs)
        row = {"task_id": a["task_id"], "task_name": a["task_name"], "order_id": a["order_id"], "people": ", ".join(e["name"] for e in a["employees"]),
               "planned_start": a["start_text"], "planned_end": a["end_text"], "status": t["status"],
               "actual_start": t["actual_start"], "actual_end": t["actual_end"], "blocker": t["blocker_reason"], "variance_min": None}
        if t["actual_end"]:
            try:
                row["variance_min"] = int((datetime.fromisoformat(t["actual_end"]) - pe).total_seconds() / 60)
            except Exception:
                pass
        pva.append(row)
        if pe < now and t["status"] not in ("Completed", "Cancelled"):
            overdue.append(row)
    return {"empty": False, "version_id": vid, "basis": basis, "people": sorted(people.values(), key=lambda p: -p["utilization_pct"]),
            "teams": sorted(teams.values(), key=lambda t: t["team"]), "work_centers": wc_list, "bottleneck": bottleneck,
            "orders": det["orders"], "on_time_pct": pct, "total_overtime_hours": round(sum(p["overtime_hours"] for p in people.values()), 1),
            "planned_vs_actual": pva, "overdue": overdue, "demo_clock_note": "Actual times come from the server clock when a worker presses Start or Complete."}
