"""Resource availability analysis, shortage detection and recommendations.

Implements the "AI Resource Analysis & Recommendations" spec:
  * quantity check: required vs available eligible quantity per resource
  * schedule-aware check: existing bookings, maintenance and leave reduce what is
    actually free during the required time window
  * diagnostic check: on failure the planner distinguishes a true resource deficit
    from a timing conflict, missing skill, material constraint or unrealistic deadline
  * recommendations are ADVISORY ONLY. Nothing here books people, machines or
    material; the manager approves a schedule, and only then are reservations written.

All numbers come from the demo database (simulated ERP). Sample figures are
illustrative, not a real factory inventory.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from core.config import SLOTS_PER_DAY, SLOTS_PER_HOUR, fmt_slot, shift_slots
from core.db import get_conn
from core.eligibility import Context, check_employee
from core.tasks import list_tasks

# Materials a product consumes, units per piece (illustrative demo values).
DEFAULT_MATERIAL_PER_UNIT = 1.0


# ---------- ASAP demand profile ----------
def _asap_intervals(tasks: List[dict]) -> Dict[str, tuple]:
    """Earliest-possible start/end slot per task, dependencies only, no capacity limits.

    This answers "if every job started as early as possible, how many resources would
    be needed at the busiest moment?" - the quantity side of the shortage check.
    """
    est: Dict[str, int] = {}
    order = sorted(tasks, key=lambda t: (t["seq"], t["chunk_index"]))
    changed = True
    remaining = list(order)
    while remaining and changed:
        changed = False
        for t in list(remaining):
            deps = t["depends_on"]
            if all(d in est for d in deps):
                dur = max(1, (int(t["duration_min"]) + 14) // 15)
                start = max([est[d][1] for d in deps], default=0)
                est[t["id"]] = (start, start + dur)
                remaining.remove(t)
                changed = True
    # cycles should not happen (routing is a DAG); fall back to slot 0 for strays
    for t in remaining:
        dur = max(1, (int(t["duration_min"]) + 14) // 15)
        est[t["id"]] = (0, dur)
    return est


def _peak_usage(tasks: List[dict], est: Dict[str, tuple]):
    """Peak simultaneous demand per machine kind and per role, with its time window."""
    mach: Dict[str, dict] = {}
    role: Dict[str, dict] = {}
    events = []
    for t in tasks:
        s, e = est[t["id"]]
        events.append((s, 1, t))
        events.append((e, -1, t))
    # sweep; end events before start events at the same slot so touching jobs don't overlap
    events.sort(key=lambda x: (x[0], x[1]))
    cur_m: Dict[str, int] = {}
    cur_r: Dict[str, int] = {}
    for slot, delta, t in events:
        cur_m[t["work_center_kind"]] = cur_m.get(t["work_center_kind"], 0) + delta
        cur_r[t["required_role"]] = cur_r.get(t["required_role"], 0) + delta * max(1, int(t["multi_person"]))
        mk = t["work_center_kind"]
        if cur_m[mk] > mach.get(mk, {}).get("peak", 0):
            mach[mk] = {"peak": cur_m[mk], "window": (slot, est[t["id"]][1]), "task": t["name"]}
        rk = t["required_role"]
        if cur_r[rk] > role.get(rk, {}).get("peak", 0):
            role[rk] = {"peak": cur_r[rk], "window": (slot, est[t["id"]][1]), "task": t["name"]}
    return mach, role


def _materials(conn, order_rows) -> List[dict]:
    mats = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM materials ORDER BY id").fetchall()}
    per_unit = {r["id"]: float(r["material_per_unit"] or DEFAULT_MATERIAL_PER_UNIT) for r in conn.execute("SELECT id, material_per_unit FROM products").fetchall()}
    prod_mat = {r["id"]: r["material"] for r in conn.execute("SELECT id, material FROM products").fetchall()}
    out = {}
    for o in order_rows:
        mat = prod_mat.get(o["product_id"])
        if not mat:
            continue
        req = float(o["quantity"]) * per_unit.get(o["product_id"], DEFAULT_MATERIAL_PER_UNIT)
        row = out.setdefault(mat, {"material": mat, "required": 0.0, "orders": []})
        row["required"] += req
        row["orders"].append(o["id"])
    result = []
    for mat, row in sorted(out.items()):
        m = mats.get(mat, {"on_hand": 0.0, "unit": "units"})
        on_hand = float(m["on_hand"])
        short = max(0.0, row["required"] - on_hand)
        result.append({**row, "on_hand": on_hand, "unit": m.get("unit", "units"),
                       "available": on_hand, "shortage": short,
                       "status": "short" if short > 0 else "sufficient"})
    return result


def material_requirement(conn, order_ids: List[str]) -> Dict[str, float]:
    """Units of each material the given orders need."""
    per_unit = {r["id"]: float(r["material_per_unit"] or DEFAULT_MATERIAL_PER_UNIT) for r in conn.execute("SELECT id, material_per_unit FROM products").fetchall()}
    need: Dict[str, float] = {}
    for oid in order_ids:
        o = conn.execute("SELECT product_id, quantity FROM orders WHERE id=?", (oid,)).fetchone()
        if not o:
            continue
        mat = conn.execute("SELECT material FROM products WHERE id=?", (o["product_id"],)).fetchone()
        if not mat:
            continue
        need[mat["material"]] = need.get(mat["material"], 0.0) + float(o["quantity"]) * per_unit.get(o["product_id"], DEFAULT_MATERIAL_PER_UNIT)
    return need


def approved_reserved_materials(db) -> Dict[str, float]:
    """Materials reserved by the currently approved schedule (simulated ERP reservation)."""
    conn = get_conn(db)
    v = conn.execute("SELECT id FROM schedule_versions WHERE status='approved' ORDER BY approved_at DESC LIMIT 1").fetchone()
    if not v:
        conn.close()
        return {}
    rows = conn.execute("""SELECT DISTINCT t.order_id FROM version_assignments va JOIN tasks t ON t.id=va.task_id
                           JOIN orders o ON o.id=t.order_id WHERE va.version_id=? AND o.status NOT IN ('Completed','Cancelled')""", (v["id"],)).fetchall()
    need = material_requirement(conn, [r["order_id"] for r in rows])
    conn.close()
    return need


def _slots_min(minutes: int) -> int:
    return max(1, (int(minutes) + 14) // 15)


def _weekly_capacity(ctx: Context, kind: str, key: str, holders: List[dict]) -> tuple:
    """(demand slots is computed by caller) Available capacity in 15-min slots over the
    planning horizon for one machine kind or one group of people."""
    from core.config import is_working_day
    days = [d for d in range(int(ctx.policy["horizon_days"])) if is_working_day(ctx.day(d), ctx.policy)]
    if kind == "machine":
        shift_hours = sum(e - s for s, e in (shift_slots(s, ctx.policy) for s in ctx.policy["shifts"])) / SLOTS_PER_HOUR
        cap = len(holders) * len(days) * int(shift_hours * SLOTS_PER_HOUR)
        for w in holders:
            for ms, me, _r in ctx.maint.get(w["id"], []):
                cap -= max(0, me - ms)
        return cap
    cap = 0
    for e in holders:
        leave = e["leave"]
        n = sum(1 for d in days if ctx.day(d).isoformat() not in leave)
        daily = min(float(e["max_daily_hours"]) + float(e["overtime_cap_hours"]), float(ctx.policy["max_daily_hours_cap"]))
        cap += n * int(daily * SLOTS_PER_HOUR)
    return cap


# ---------- the analysis ----------
def resource_analysis(db, order_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    ctx = Context(db)
    conn = get_conn(db)
    orders = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM orders").fetchall()}
    open_ids = [o for o, r in orders.items() if r["status"] not in ("Completed", "Cancelled")]
    sel = [o for o in (order_ids or open_ids) if o in orders]
    tasks = [t for t in list_tasks(None, db) if t["order_id"] in sel]
    order_rows = [orders[o] for o in sel]

    # schedule-aware availability: the approved plan's existing bookings
    from core.solver import approved_assignments
    booked = approved_assignments(db)  # task_id -> assignment (current reservations)

    busy_emp: Dict[str, List[tuple]] = {}
    busy_wc: Dict[str, List[tuple]] = {}
    for a in booked.values():
        for e in a["employee_ids"]:
            busy_emp.setdefault(e, []).append((a["start_slot"], a["end_slot"]))
        busy_wc.setdefault(a["work_center_id"], []).append((a["start_slot"], a["end_slot"]))

    rows: List[dict] = []
    recommendations: List[dict] = []
    if tasks:
        est = _asap_intervals(tasks)
        mach_peak, role_peak = _peak_usage(tasks, est)
    else:
        est, mach_peak, role_peak = {}, {}, {}

    # --- machines ---
    kinds = sorted({t["work_center_kind"] for t in tasks} | {w["kind"] for w in ctx.wcs.values()})
    for kind in kinds:
        wcs = [w for w in ctx.wcs.values() if w["kind"] == kind]
        up = [w for w in wcs if not w["down"]]
        peak = mach_peak.get(kind, {}).get("peak", 0)
        if not peak and kind not in mach_peak:
            if not any(t["work_center_kind"] == kind for t in tasks):
                continue
        win = mach_peak.get(kind, {}).get("window")
        # schedule-aware: machines free at the peak window after existing bookings & maintenance
        free_at_peak = []
        if win:
            for w in up:
                taken = any(s < win[1] and e > win[0] for s, e in busy_wc.get(w["id"], []))
                maint = any(ms < win[1] and me > win[0] for ms, me, _r in ctx.maint.get(w["id"], []))
                if not taken and not maint:
                    free_at_peak.append(w["id"])
        required = peak
        available = len(up)
        short = max(0, required - available)
        demand_slots = sum(_slots_min(t["duration_min"]) for t in tasks if t["work_center_kind"] == kind)
        cap_slots = _weekly_capacity(ctx, "machine", kind, up)
        capacity_ok = demand_slots <= cap_slots
        if short and capacity_ok:
            verdict = "timing peak, not a true deficit: the week's machine-hours cover the work, so the planner sequences jobs across days"
        elif short:
            verdict = "true deficit: even using every available machine-hour this week cannot cover the required work"
        else:
            verdict = "enough machines even at the busiest moment"
        reasons = []
        for w in wcs:
            if w["down"]:
                reasons.append(f"{w['id']} is marked down")
            for ms, me, r in ctx.maint.get(w["id"], []):
                reasons.append(f"{w['id']}: {r} ({fmt_slot(ms, ctx.hs)} - {fmt_slot(me, ctx.hs)})")
        row = {"group": "machines", "resource": f"{kind} machines", "required": required,
               "available": available, "shortage": short,
               "status": "short" if short else "sufficient",
               "window": {"start": fmt_slot(win[0], ctx.hs), "end": fmt_slot(win[1], ctx.hs)} if win else None,
               "free_at_peak": free_at_peak,
               "weekly": {"demand_hours": round(demand_slots / SLOTS_PER_HOUR, 1), "capacity_hours": round(cap_slots / SLOTS_PER_HOUR, 1), "covers": capacity_ok},
               "verdict": verdict,
               "detail": f"{len(wcs)} machine(s) of this type exist" + (f"; {len(free_at_peak)} free at the busiest moment after current bookings" if win else ""),
               "reasons": reasons}
        rows.append(row)
        if short:
            ops = sorted({t["name"] for t in tasks if t["work_center_kind"] == kind})
            if capacity_ok:
                recommendations.append({
                    "kind": "machine", "severity": "warning", "resource": row["resource"],
                    "actions": [
                        f"Timing peak, not a true deficit: schedule the {available} available {kind} machine(s); the planner sequences the work across the week ({row['weekly']['demand_hours']:g} h needed vs {row['weekly']['capacity_hours']:g} h available).",
                        "If a specific date is at risk, check whether a compatible machine sits idle in another shift before approving overtime.",
                    ]})
            else:
                recommendations.append({
                    "kind": "machine", "severity": "critical", "resource": row["resource"],
                    "actions": [
                        f"True deficit: {row['weekly']['demand_hours']:g} machine-hours needed vs {row['weekly']['capacity_hours']:g} available this week.",
                        f"Schedule the {available} available {kind} machine(s) first, then check other departments for a compatible idle machine.",
                        f"If internal capacity stays short, evaluate outsourcing the missing operation ({', '.join(ops[:3])}) or revising the deadline. The app does not book this; it is a manager decision.",
                    ]})

    # --- people ---
    roles_needed = sorted({t["required_role"] for t in tasks})
    for role in roles_needed:
        peak = role_peak.get(role, {}).get("peak", 0)
        win = role_peak.get(role, {}).get("window")
        holders = [e for e in ctx.emps.values() if e["role"] == role and e["active"]]
        # eligible = passes the hard rules for the relevant tasks on the peak day
        rel = [t for t in tasks if t["required_role"] == role]
        peak_day = ctx.day(win[0] // SLOTS_PER_DAY) if win else ctx.day(0)
        eligible = []
        for e in holders:
            ok_all = True
            first_reason = ""
            for t in rel:
                r = check_employee(e, t, peak_day, ctx)
                if r:
                    ok_all = False
                    first_reason = r[0]
                    break
            if ok_all:
                # schedule-aware: not already booked at the peak window
                if win and any(s < win[1] and e2 > win[0] for s, e2 in busy_emp.get(e["id"], [])):
                    continue
                eligible.append(e["id"])
        required = peak
        available = len(eligible)
        short = max(0, required - available)
        demand_slots = sum(_slots_min(t["duration_min"]) * max(1, int(t["multi_person"])) for t in rel)
        cap_slots = _weekly_capacity(ctx, "people", role, [e for e in holders if e["id"] in eligible] or holders)
        capacity_ok = demand_slots <= cap_slots
        if short and capacity_ok:
            verdict = "timing peak, not a true deficit: the week's eligible person-hours cover the work"
        elif short:
            verdict = "true deficit: not enough qualified people even across the whole week"
        else:
            verdict = "enough qualified people even at the busiest moment"
        need_skills = sorted({f"{t['required_skill']} L{t['min_level']}" for t in rel})
        excl = []
        for e in holders:
            if e["id"] in eligible:
                continue
            rs = []
            for t in rel:
                rs = check_employee(e, t, peak_day, ctx)
                if rs:
                    break
            why = rs[0] if rs else ("already booked at the busiest moment" if win else "unavailable")
            excl.append(f"{e['name']}: {why}")
        row = {"group": "people", "resource": role, "required": required, "available": available,
               "shortage": short, "status": "short" if short else "sufficient",
               "window": {"start": fmt_slot(win[0], ctx.hs), "end": fmt_slot(win[1], ctx.hs)} if win else None,
               "eligible_names": [ctx.emps[e]["name"] for e in eligible],
               "weekly": {"demand_hours": round(demand_slots / SLOTS_PER_HOUR, 1), "capacity_hours": round(cap_slots / SLOTS_PER_HOUR, 1), "covers": capacity_ok},
               "verdict": verdict,
               "detail": f"{len(holders)} people have this role; needs {', '.join(need_skills)}",
               "reasons": excl}
        rows.append(row)
        if short:
            main_skill = rel[0]["required_skill"] if rel else ""
            min_lvl = max((t["min_level"] for t in rel), default=1)
            cross = []
            for e in ctx.emps.values():
                if e["role"] == role or not e["active"]:
                    continue
                if ctx.skills.get(e["id"], {}).get(main_skill, 0) >= min_lvl:
                    cross.append(f"{e['name']} ({e['role']}, {main_skill} L{ctx.skills[e['id']][main_skill]})")
            actions = [f"Allocate the {available} available qualified {role}(s); the planner only assigns people who pass every rule."]
            if cross:
                actions.append("Search other departments: " + "; ".join(cross[:4]) +
                               " hold verified skills for this work. HR/Workforce Admin could review a temporary reassignment; the app never applies this by itself.")
            else:
                actions.append("Nobody in another team holds the required verified skill, so internal cover is not available.")
            actions.append("If appropriate, consider an approved additional shift or overtime (Settings); hiring or re-certification is the fallback when skill is the gap.")
            if capacity_ok:
                actions.insert(0, f"Timing peak, not a hard shortage: {row['weekly']['demand_hours']:g} person-hours needed vs {row['weekly']['capacity_hours']:g} available from qualified people this week.")
            recommendations.append({"kind": "people", "severity": "warning" if capacity_ok else "critical", "resource": role, "actions": actions})

    # --- materials ---
    mat_rows = _materials(conn, order_rows)
    reserved = approved_reserved_materials(db)
    for m in mat_rows:
        res = float(reserved.get(m["material"], 0.0))
        avail = m["on_hand"] - res
        short = max(0.0, m["required"] - avail)
        rows.append({"group": "materials", "resource": f"Raw material: {m['material']}",
                     "verdict": ("true deficit: stock plus current reservations cannot cover these orders" if max(0.0, m["required"] - (m["on_hand"] - res)) > 0 else "sufficient stock"),
                     "required": m["required"], "available": avail, "on_hand": m["on_hand"],
                     "reserved": res, "shortage": short, "unit": m["unit"],
                     "status": "short" if short > 0 else "sufficient",
                     "detail": f"{m['on_hand']:g} {m['unit']} on hand, {res:g} already reserved by the approved schedule",
                     "reasons": []})
        if short > 0:
            recommendations.append({"kind": "material", "severity": "critical", "resource": m["material"],
                                    "actions": [f"Only {avail:g} of {m['required']:g} {m['unit']} available after existing reservations: {short:g} short.",
                                                "Reserve the available quantity now and raise a purchase request for the missing quantity through the ERP workflow before approving production."]})
        else:
            recommendations.append({"kind": "material", "severity": "info", "resource": m["material"],
                                    "actions": [f"No shortage. Confirm material quality and reserve {m['required']:g} {m['unit']} through the approved ERP workflow (reservation is written when a schedule covering these orders is approved)."]})

    conn.close()

    true_deficits = [r for r in rows if r["shortage"] and str(r.get("verdict", "")).startswith("true deficit")]
    timing_peaks = [r for r in rows if r["shortage"] and not str(r.get("verdict", "")).startswith("true deficit")]
    any_short = bool(true_deficits)
    # schedule impact from the latest schedule (draft preferred, else approved)
    from core.service import latest_version_id, enrich
    impact = {"version": None, "orders": [], "note": ""}
    vid = latest_version_id(db) 
    if vid:
        det = enrich(db, vid)
        impact = {"version": vid, "status": det["version"]["status"],
                  "orders": det["orders"],
                  "note": "Predicted completion per order from the latest " + det["version"]["status"] + " schedule."}
    else:
        impact["note"] = "No schedule yet. Generate one on the AI Allocation Proposal screen to see the recalculated delivery dates."

    return {
        "scope": {"orders": sel, "order_count": len(sel), "task_count": len(tasks)},
        "overall_status": ("Insufficient resources for the current plan" if true_deficits else
                           ("Sufficient, with timing peaks the planner must smooth out" if timing_peaks else "Sufficient resources")),
        "summary": ((f"{len(true_deficits)} true resource deficit(s): " + "; ".join(f"{r['resource']} short by {r['shortage']:g}" for r in true_deficits) +
                     ". These must be addressed or the schedule revised." +
                     (f" Also {len(timing_peaks)} timing peak(s) the planner can smooth out by sequencing." if timing_peaks else "")) if true_deficits else
                    (f"No true deficits. {len(timing_peaks)} resource(s) are short at the busiest moment, but the week's capacity covers the work; "
                     "the planner sequences jobs to handle this." if timing_peaks else
                     "Every required machine, person and material is available for the selected orders.")),
        "rows": rows,
        "recommendations": recommendations,
        "schedule_impact": impact,
        "method": ("Quantity check: required minus available eligible quantity. Schedule-aware check: existing approved bookings, "
                   "maintenance windows, leave and shift rules reduce what is free at the busiest moment. A job is never called feasible "
                   "from total counts alone; the solver still decides the final plan under every hard rule."),
        "disclaimer": "Simulated ERP demo data. Sample figures are illustrative, not a real factory inventory.",
    }
