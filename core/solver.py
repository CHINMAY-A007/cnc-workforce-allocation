"""OR-Tools CP-SAT scheduling engine.

The solver is the ONLY thing that decides who does what and when. It never calls an AI
service. Every (people, machine) option it may pick has already passed the hard
eligibility rules in core/eligibility.py, and the independent `validate_schedule`
below re-checks the finished plan from scratch.

Time is counted in 15-minute slots from the first planning day at 00:00.
"""
from __future__ import annotations

import itertools
import json
import time
from datetime import timedelta
from typing import Any, Dict, List, Optional

from ortools.sat.python import cp_model

from core.config import SLOTS_PER_DAY, SLOTS_PER_HOUR, fmt_slot, shift_slots
from core.db import get_conn
from core.eligibility import Context, check_employee, task_candidates


def _slots(dur_min: int) -> int:
    return max(1, (int(dur_min) + 14) // 15)


def _ot_slots(policy) -> int:
    room = min(float(policy["overtime_cap_hours"]), float(policy["max_daily_hours_cap"]) - float(policy["standard_daily_hours"]))
    return max(0, int(room * SLOTS_PER_HOUR))


def load_tasks(order_ids: List[str], db_path=None) -> List[dict]:
    from core.tasks import task_row
    conn = get_conn(db_path)
    out = []
    for oid in order_ids:
        for r in conn.execute("SELECT * FROM tasks WHERE order_id=? ORDER BY seq, chunk_index", (oid,)).fetchall():
            out.append(task_row(r))
    conn.close()
    return out


def load_orders(db_path=None) -> Dict[str, dict]:
    conn = get_conn(db_path)
    o = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM orders").fetchall()}
    conn.close()
    return o


def approved_assignments(db_path=None) -> Dict[str, dict]:
    conn = get_conn(db_path)
    v = conn.execute("SELECT id FROM schedule_versions WHERE status='approved' ORDER BY approved_at DESC, created_at DESC LIMIT 1").fetchone()
    out = {}
    if v:
        for r in conn.execute("SELECT * FROM version_assignments WHERE version_id=?", (v["id"],)).fetchall():
            d = dict(r)
            d["employee_ids"] = json.loads(d["employee_ids"])
            out[d["task_id"]] = d
    conn.close()
    return out


def check_orders(order_ids: List[str], orders: Dict[str, dict]) -> List[str]:
    """Friendly data problems that must be fixed before solving (never a 500)."""
    from datetime import datetime
    problems = []
    for oid in order_ids:
        o = orders.get(oid)
        if not o:
            problems.append(f"Order {oid} does not exist.")
            continue
        try:
            datetime.strptime(o["due_date"] or "", "%Y-%m-%d")
        except Exception:
            problems.append(f"Order {oid} has no valid due date. Edit or remove it on the Orders screen.")
    return problems


def solve(db_path, order_ids: List[str], policy: Optional[dict] = None, *, weights: Optional[dict] = None,
          pinned: Optional[Dict[str, dict]] = None, absent: Optional[set] = None, down_wcs: Optional[set] = None,
          time_limit_sec: float = 10.0, ignore_due: bool = False, extra_overtime_hours: float = 0.0,
          horizon_days: Optional[int] = None, ctx: Optional[Context] = None,
          prev_assign: Optional[Dict[str, dict]] = None, only_tasks: Optional[List[dict]] = None) -> Dict[str, Any]:
    ctx = ctx or Context(db_path)
    policy = dict(policy or ctx.policy)
    if extra_overtime_hours:
        policy["overtime_cap_hours"] = float(policy["overtime_cap_hours"]) + extra_overtime_hours
        policy["max_daily_hours_cap"] = float(policy["max_daily_hours_cap"]) + extra_overtime_hours
    ctx.policy = policy
    pinned = pinned or {}
    absent = absent or set()
    down_wcs = down_wcs or set()
    orders = load_orders(db_path)
    tasks = only_tasks if only_tasks is not None else load_tasks(order_ids, db_path)
    if not tasks:
        return {"status": "EMPTY", "message": "There are no jobs to schedule yet. Add an order first; jobs are created automatically.",
                "runtime": 0.0, "objective": None, "assignments": [], "zero_eligibility": [], "orders": []}
    problems = check_orders(sorted({t["order_id"] for t in tasks}), orders)
    if problems:
        return {"status": "BAD_DATA", "message": " ".join(problems), "runtime": 0.0, "objective": None,
                "assignments": [], "zero_eligibility": [], "orders": []}
    prev_assign = approved_assignments(db_path) if prev_assign is None else prev_assign

    H_days = int(horizon_days or policy["horizon_days"])
    H = H_days * SLOTS_PER_DAY
    hs = ctx.hs
    ot = _ot_slots(policy)
    std_slots = int(float(policy["standard_daily_hours"]) * SLOTS_PER_HOUR)
    cap_slots = std_slots + ot
    by_id = {t["id"]: t for t in tasks}

    model = cp_model.CpModel()
    opts: Dict[str, List[dict]] = {}
    zero: List[dict] = []
    wc_iv: Dict[str, list] = {w: [] for w in ctx.wcs}
    emp_iv: Dict[str, list] = {e: [] for e in ctx.emps}
    emp_day: Dict[tuple, list] = {}   # (emp, day) -> [(dur, boolvar)]
    emp_total: Dict[str, list] = {e: [] for e in ctx.emps}
    tstart, tend = {}, {}

    for t in tasks:
        tid = t["id"]
        dur = _slots(t["duration_min"])
        mp = max(1, int(t["multi_person"]))
        wcs = [w["id"] for w in ctx.wcs.values() if w["kind"] == t["work_center_kind"] and w["id"] not in down_wcs]
        # employees eligible on each day
        elig_by_day = []
        for d in range(H_days):
            day = ctx.day(d)
            elig_by_day.append({eid for eid, e in ctx.emps.items() if not check_employee(e, t, day, ctx, absent)})
        ever = set().union(*elig_by_day) if elig_by_day else set()
        combos = [list(c) for c in itertools.combinations(sorted(ever), mp)] if len(ever) >= mp else []
        olist = []
        for emps_ in combos:
            if len({ctx.emps[e]["shift"] for e in emps_}) != 1:
                continue
            ss, se = shift_slots(ctx.emps[emps_[0]]["shift"], policy)
            for wc in wcs:
                days = []
                for d in range(H_days):
                    if not all(e in elig_by_day[d] for e in emps_):
                        continue
                    lo, hi = d * SLOTS_PER_DAY + ss, d * SLOTS_PER_DAY + se + ot
                    if hi - lo < dur:
                        continue
                    days.append((d, lo, hi))
                if days:
                    olist.append({"emps": emps_, "wc": wc, "days": days})
        pin = pinned.get(tid)
        if pin:
            match = [o for o in olist if sorted(o["emps"]) == sorted(pin["employee_ids"]) and o["wc"] == pin["work_center_id"]]
            if pin.get("start_slot") is not None:
                pd = int(pin["start_slot"]) // SLOTS_PER_DAY
                match = [o for o in match if any(dd[0] == pd for dd in o["days"])]
            if not match:
                zero.append({"task_id": tid, "reason": "pinned assignment is no longer valid"})
                return {"status": "INFEASIBLE", "message": f"Locked or unchanged assignment for {t['name']} ({tid}) is no longer valid.",
                        "runtime": 0.0, "objective": None, "assignments": [], "zero_eligibility": zero, "orders": []}
            olist = match
        if not olist:
            zero.append({"task_id": tid, "reason": "nobody is eligible"})
            opts[tid] = []
            continue
        for oi, o in enumerate(olist):
            start = model.NewIntVar(0, H - dur, f"s_{tid}_{oi}")
            end = model.NewIntVar(dur, H, f"e_{tid}_{oi}")
            xs = []
            for (d, lo, hi) in o["days"]:
                x = model.NewBoolVar(f"x_{tid}_{oi}_{d}")
                model.Add(start >= lo).OnlyEnforceIf(x)
                model.Add(start <= hi - dur).OnlyEnforceIf(x)
                xs.append((d, x))
                for e in o["emps"]:
                    emp_day.setdefault((e, d), []).append((dur, x))
            pres = model.NewBoolVar(f"p_{tid}_{oi}")
            model.Add(sum(x for _, x in xs) == pres)
            model.Add(end == start + dur)
            iv = model.NewOptionalIntervalVar(start, dur, end, pres, f"iv_{tid}_{oi}")
            o.update(start=start, end=end, pres=pres, iv=iv, dur=dur)
            for e in o["emps"]:
                emp_iv[e].append(iv)
                emp_total[e].append((dur, pres))
            wc_iv[o["wc"]].append(iv)
            if pin and pin.get("start_slot") is not None:
                model.Add(start == int(pin["start_slot"]))
        opts[tid] = olist
        model.Add(sum(o["pres"] for o in olist) == 1)
        tstart[tid] = model.NewIntVar(0, H, f"ts_{tid}")
        tend[tid] = model.NewIntVar(0, H, f"te_{tid}")
        for o in olist:
            model.Add(tstart[tid] == o["start"]).OnlyEnforceIf(o["pres"])
            model.Add(tend[tid] == o["end"]).OnlyEnforceIf(o["pres"])

    if zero:
        return {"status": "INFEASIBLE", "message": "Some jobs have nobody eligible.",
                "runtime": 0.0, "objective": None, "assignments": [], "zero_eligibility": zero, "orders": []}

    for e, ivs in emp_iv.items():
        if ivs:
            model.AddNoOverlap(ivs)
    for w, ivs in wc_iv.items():
        fixed = []
        for (ms, me, _r) in ctx.maint.get(w, []):
            if me > ms:
                fixed.append(model.NewIntervalVar(ms, me - ms, me, f"m_{w}_{ms}"))
        if ivs or fixed:
            model.AddNoOverlap(ivs + fixed)
    for t in tasks:
        for dep in t["depends_on"]:
            if dep in tend and t["id"] in tstart:
                model.Add(tend[dep] <= tstart[t["id"]])

    ot_terms = []
    for (e, d), lst in emp_day.items():
        load = sum(dur * x for dur, x in lst)
        model.Add(load <= min(cap_slots, int(float(ctx.emps[e]["max_daily_hours"] + ctx.emps[e]["overtime_cap_hours"]) * SLOTS_PER_HOUR)))
        v = model.NewIntVar(0, cap_slots, f"ot_{e}_{d}")
        model.Add(v >= load - min(std_slots, int(ctx.emps[e]["max_daily_hours"] * SLOTS_PER_HOUR)))
        ot_terms.append(v)

    w = dict(policy["objective_weights"])
    if weights:
        w.update(weights)
    sc = lambda k, dflt: int(round(float(w.get(k, dflt)) * 10))
    prio = policy["priority_weights"]
    terms = []
    # lateness, priority weighted
    due_info = {}
    for oid in sorted({t["order_id"] for t in tasks}):
        from datetime import datetime
        dd = datetime.strptime(orders[oid]["due_date"], "%Y-%m-%d").date()
        due_end = ((dd - hs).days + 1) * SLOTS_PER_DAY
        due_info[oid] = (dd, due_end)
        deliv = model.NewIntVar(0, H, f"dv_{oid}")
        for t in tasks:
            if t["order_id"] == oid:
                model.Add(deliv >= tend[t["id"]])
        if not ignore_due:
            tard = model.NewIntVar(0, H, f"td_{oid}")
            model.Add(tard >= deliv - max(0, due_end))
            terms.append(sc("on_time", 10) * int(prio.get(orders[oid]["priority"], 1)) * tard)
    mk = model.NewIntVar(0, H, "mk")
    for tid in tend:
        model.Add(mk >= tend[tid])
    terms.append(sc("makespan", 1) * mk)
    if ot_terms:
        terms.append(sc("overtime", 3) * sum(ot_terms))
    # balance inside each team
    teams: Dict[str, list] = {}
    for eid, e in ctx.emps.items():
        if e["active"] and eid not in absent:
            teams.setdefault(e["team"], []).append(eid)
    for team, members in teams.items():
        vs = []
        for eid in members:
            tot = model.NewIntVar(0, H, f"tot_{eid}")
            model.Add(tot == sum(dur * p for dur, p in emp_total[eid]))
            vs.append(tot)
        if len(vs) >= 2:
            mx, mn = model.NewIntVar(0, H, f"mx_{team}"), model.NewIntVar(0, H, f"mn_{team}")
            model.AddMaxEquality(mx, vs)
            model.AddMinEquality(mn, vs)
            terms.append(sc("balance", 2) * (mx - mn))
    # reassignment vs last approved plan
    for t in tasks:
        pv = prev_assign.get(t["id"])
        if pv:
            for o in opts[t["id"]]:
                if sorted(o["emps"]) != sorted(pv["employee_ids"]):
                    terms.append(sc("reassignment", 2) * 10 * o["pres"])
    # continuity: parts of the same job stay with the same people
    parts: Dict[str, list] = {}
    for t in tasks:
        if t.get("parent_task_id"):
            parts.setdefault(t["parent_task_id"], []).append(t)
    for _p, plist in parts.items():
        plist.sort(key=lambda x: x["chunk_index"])
        for a, b in zip(plist, plist[1:]):
            for eid in ctx.emps:
                ua = [o["pres"] for o in opts[a["id"]] if eid in o["emps"]]
                ub = [o["pres"] for o in opts[b["id"]] if eid in o["emps"]]
                if not ua and not ub:
                    continue
                dv = model.NewIntVar(0, 1, f"cd_{a['id']}_{eid}")
                model.Add(dv >= sum(ua) - sum(ub))
                model.Add(dv >= sum(ub) - sum(ua))
                terms.append(sc("continuity", 2) * 10 * dv)
    model.Minimize(sum(terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_sec)
    solver.parameters.num_search_workers = 4
    solver.parameters.random_seed = 7
    t0 = time.time()
    status = solver.Solve(model)
    runtime = time.time() - t0
    name = {cp_model.OPTIMAL: "OPTIMAL", cp_model.FEASIBLE: "FEASIBLE", cp_model.INFEASIBLE: "INFEASIBLE",
            cp_model.UNKNOWN: "UNKNOWN", cp_model.MODEL_INVALID: "MODEL_INVALID"}.get(status, str(status))
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        msg = {"UNKNOWN": "The scheduler ran out of time before proving a plan. Your last approved schedule is unchanged. You can plan manually or try again.",
               "INFEASIBLE": "No plan can satisfy every hard rule within the planning week."}.get(name, "The scheduler could not build a plan.")
        return {"status": name, "message": msg, "runtime": runtime, "objective": None, "assignments": [], "zero_eligibility": [], "orders": []}

    assigns = []
    for t in tasks:
        for o in opts[t["id"]]:
            if solver.Value(o["pres"]):
                s = int(solver.Value(o["start"]))
                assigns.append({"task_id": t["id"], "employee_ids": list(o["emps"]), "work_center_id": o["wc"],
                                "start_slot": s, "end_slot": s + o["dur"], "locked": bool(pinned.get(t["id"], {}).get("locked"))})
                break
    hours = {}
    for a in assigns:
        for e in a["employee_ids"]:
            hours[e] = hours.get(e, 0) + (a["end_slot"] - a["start_slot"]) / SLOTS_PER_HOUR
    for a in assigns:
        a["why"] = build_why(a, by_id[a["task_id"]], ctx, absent, down_wcs, hours, prev_assign, assigns)
    res = {"status": name, "message": "", "runtime": runtime, "objective": float(solver.ObjectiveValue()),
           "assignments": assigns, "zero_eligibility": [], "orders": delivery_estimates(assigns, tasks, orders, ctx)}
    return res


def delivery_estimates(assigns, tasks, orders, ctx) -> List[dict]:
    from datetime import datetime
    amap = {a["task_id"]: a for a in assigns}
    out = []
    for oid in sorted({t["order_id"] for t in tasks}):
        ends = [amap[t["id"]]["end_slot"] for t in tasks if t["order_id"] == oid and t["id"] in amap]
        if not ends:
            continue
        fin = max(ends)
        dd = datetime.strptime(orders[oid]["due_date"], "%Y-%m-%d").date()
        due_end = ((dd - ctx.hs).days + 1) * SLOTS_PER_DAY
        due_day_start = (dd - ctx.hs).days * SLOTS_PER_DAY
        if fin > due_end:
            badge = "late"
        elif fin > due_day_start:
            badge = "at_risk"
        else:
            badge = "on_time"
        out.append({"order_id": oid, "finish_slot": fin, "finish_text": fmt_slot(fin, ctx.hs), "due_date": orders[oid]["due_date"],
                    "status": badge, "hours_late": round(max(0, fin - due_end) / SLOTS_PER_HOUR, 1),
                    "priority": orders[oid]["priority"]})
    return out


def build_why(a, task, ctx: Context, absent, down_wcs, hours, prev_assign, all_assigns) -> dict:
    """Plain-English 'Why this person?' (FR-15)."""
    day = ctx.day(a["start_slot"] // SLOTS_PER_DAY)
    cand = task_candidates(task, day, ctx, absent, down_wcs)
    chosen = [ctx.emps[e] for e in a["employee_ids"]]
    lv = {e: ctx.skills.get(e, {}).get(task["required_skill"], 0) for e in a["employee_ids"]}
    best = max([c["skill_level"] for c in cand["candidates"]] or [0])
    alts = []
    for c in cand["candidates"]:
        if c["employee_id"] in a["employee_ids"]:
            continue
        mylv = min(lv.values()) if lv else 0
        h = round(hours.get(c["employee_id"], 0), 1)
        if c["skill_level"] < mylv:
            why = f"skill level {c['skill_level']} is lower than {mylv}"
        elif c["shift"] != chosen[0]["shift"]:
            why = f"works Shift {c['shift']}; the plan needed Shift {chosen[0]['shift']} to keep the job moving"
        else:
            why = f"equally qualified, but already booked {h} h this week, so the plan balanced the load"
        alts.append({"person": c["employee_name"], "skill_level": c["skill_level"], "shift": c["shift"], "why_not": why})
    pv = prev_assign.get(task["id"])
    cont = bool(pv and sorted(pv["employee_ids"]) == sorted(a["employee_ids"]))
    names = " and ".join(e["name"] for e in chosen)
    when = fmt_slot(a["start_slot"], ctx.hs)
    summary = (f"{names} meet every rule for {task['name']}: {task['required_skill']} level {min(lv.values())} (needs {task['min_level']}), "
               f"right role, certificates valid, on shift, not on leave. Scheduled {when} on {a['work_center_id']}.")
    if len(cand["candidates"]) > len(chosen):
        summary += f" {len(alts)} other qualified {'person was' if len(alts)==1 else 'people were'} considered."
    return {"summary": summary, "employees": [e["name"] for e in chosen], "skill_level": lv, "needs_level": task["min_level"],
            "shift_fit": f"Shift {chosen[0]['shift']}, inside the shift window", "hours_this_week": {e["name"]: round(hours.get(e["id"], 0), 1) for e in chosen},
            "continuity": cont, "alternatives": alts[:6], "work_center": a["work_center_id"]}


def validate_schedule(assigns: List[dict], tasks: List[dict], ctx: Context, absent=None, down_wcs=None) -> List[str]:
    """Independent re-check of every hard rule. Empty list = valid."""
    pol = ctx.policy
    v: List[str] = []
    tmap = {t["id"]: t for t in tasks}
    amap = {a["task_id"]: a for a in assigns}
    ot = _ot_slots(pol)
    for a in assigns:
        t = tmap.get(a["task_id"])
        if not t:
            continue
        d = a["start_slot"] // SLOTS_PER_DAY
        if (a["end_slot"] - 1) // SLOTS_PER_DAY != d:
            v.append(f"{t['name']} ({t['order_id']}) runs past midnight")
        day = ctx.day(d)
        if len(a["employee_ids"]) != int(t["multi_person"]):
            v.append(f"{t['name']} ({t['order_id']}) needs {t['multi_person']} person(s)")
        for e in a["employee_ids"]:
            r = check_employee(ctx.emps[e], t, day, ctx, absent)
            if r:
                v.append(f"{ctx.emps[e]['name']} cannot do {t['name']} ({t['order_id']}): {r[0]}")
            ss, se = shift_slots(ctx.emps[e]["shift"], pol)
            if a["start_slot"] % SLOTS_PER_DAY < ss or a["end_slot"] - d * SLOTS_PER_DAY > se + ot:
                v.append(f"{ctx.emps[e]['name']} is scheduled outside shift on {t['name']} ({t['order_id']})")
        if down_wcs and a["work_center_id"] in down_wcs:
            v.append(f"{a['work_center_id']} is out of service")
        if ctx.wcs[a["work_center_id"]]["kind"] != t["work_center_kind"]:
            v.append(f"wrong machine type for {t['name']} ({t['order_id']})")
        for (ms, me, _r) in ctx.maint.get(a["work_center_id"], []):
            if a["start_slot"] < me and a["end_slot"] > ms:
                v.append(f"{a['work_center_id']} is in maintenance during {t['name']} ({t['order_id']})")
        if a["end_slot"] - a["start_slot"] != _slots(t["duration_min"]):
            v.append(f"duration mismatch on {t['name']} ({t['order_id']})")
        for dep in t["depends_on"]:
            if dep in amap and amap[dep]["end_slot"] > a["start_slot"]:
                v.append(f"{t['name']} ({t['order_id']}) starts before a job it depends on has finished")
    for key, label in (("employee_ids", "person"), ("work_center_id", "machine")):
        by = {}
        for a in assigns:
            for k in (a[key] if key == "employee_ids" else [a[key]]):
                by.setdefault(k, []).append(a)
        for k, lst in by.items():
            lst.sort(key=lambda x: x["start_slot"])
            for x, y in zip(lst, lst[1:]):
                if x["end_slot"] > y["start_slot"]:
                    v.append(f"double booking: {label} {k} on {x['task_id']} and {y['task_id']}")
    load: Dict[tuple, int] = {}
    cap = int((float(pol["standard_daily_hours"]) + min(float(pol["overtime_cap_hours"]), float(pol["max_daily_hours_cap"]) - float(pol["standard_daily_hours"]))) * SLOTS_PER_HOUR)
    for a in assigns:
        for e in a["employee_ids"]:
            k = (e, a["start_slot"] // SLOTS_PER_DAY)
            load[k] = load.get(k, 0) + a["end_slot"] - a["start_slot"]
    for (e, d), s in load.items():
        if s > cap:
            v.append(f"{ctx.emps[e]['name']} is over the daily hours limit on {ctx.day(d):%a %d %b}")
    return v
