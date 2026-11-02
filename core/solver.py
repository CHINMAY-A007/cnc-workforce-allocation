"""OR-Tools CP-SAT scheduling solver for the CNC workforce allocation demo."""

from __future__ import annotations

import itertools
import json
import time
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from ortools.sat.python import cp_model

from core.config import (
    SLOTS_PER_HOUR,
    day_start_slot,
    is_working_day,
    resolve_horizon_start,
    shift_slots,
)
from core.db import get_conn
from core.models import Assignment, ScheduleVersion


def _slots(dur_min: int) -> int:
    return max(1, (dur_min + 14) // 15)


def _load_inputs(db_path, order_ids, policy):
    conn = get_conn(db_path)
    tasks = []
    for oid in order_ids:
        rows = conn.execute("SELECT * FROM tasks WHERE order_id=? ORDER BY seq, chunk_index", (oid,)).fetchall()
        for r in rows:
            tasks.append(dict(r))
    # orders
    orders = {}
    for r in conn.execute("SELECT * FROM orders").fetchall():
        orders[r["id"]] = dict(r)
    # products routing not needed (tasks already)
    # work centers
    wcs = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM work_centers").fetchall()}
    # maintenance
    maint = conn.execute("SELECT * FROM maintenance").fetchall()
    maint_by_wc: Dict[str, List[Tuple[int, int]]] = {}
    for m in maint:
        maint_by_wc.setdefault(m["work_center_id"], []).append((m["start_slot"], m["end_slot"]))
    # employees
    emps = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM employees").fetchall()}
    skills = {}
    for r in conn.execute("SELECT * FROM skills").fetchall():
        skills.setdefault(r["employee_id"], {})[r["skill"]] = r["level"]
    certs = {}
    for r in conn.execute("SELECT * FROM certs").fetchall():
        certs.setdefault(r["employee_id"], []).append((r["cert"], r["expires_on"]))
    # previous approved version assignments
    prev_version = conn.execute(
        "SELECT id FROM schedule_versions WHERE status='approved' ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    prev_assign: Dict[str, Dict[str, Any]] = {}
    if prev_version:
        for r in conn.execute("SELECT * FROM version_assignments WHERE version_id=?", (prev_version["id"],)).fetchall():
            prev_assign[r["task_id"]] = dict(r)
    conn.close()
    return tasks, orders, wcs, maint_by_wc, emps, skills, certs, prev_assign


def _is_on_leave(emp, task_date_iso) -> bool:
    import json as _j
    return task_date_iso in set(_j.loads(emp.get("leave_dates") or "[]"))


def _eligible_options(task, policy, emps, skills, certs, wcs, task_date):
    """Return list of options: each (list_employee_ids, work_center_id)."""
    kind = task["work_center_kind"]
    req_skill = task["required_skill"]
    min_level = int(task["min_level"])
    req_role = task["required_role"]
    mp = int(task["multi_person"])
    matching_wcs = [w for w in wcs.values() if w["kind"] == kind]

    # eligible employees
    elig_emps = []
    for eid, e in emps.items():
        if not e["active"]:
            continue
        if e["role"] != req_role:
            continue
        if skills.get(eid, {}).get(req_skill, 0) < min_level:
            continue
        # cert validity: only an expired cert relevant to this task's skill/role blocks
        today = task_date.isoformat()
        blocked = False
        skill_tokens = set(req_skill.lower().split()) | set(req_role.lower().split())
        for cert, exp in certs.get(eid, []):
            if exp < today and any(tok in cert.lower() for tok in skill_tokens if len(tok) > 2):
                blocked = True
                break
        if blocked:
            continue
        # leave
        if _is_on_leave(e, today):
            continue
        # working day
        if not is_working_day(task_date, policy):
            continue
        elig_emps.append(eid)

    options = []
    if mp <= 1:
        for eid in elig_emps:
            for wc in matching_wcs:
                options.append(([eid], wc["id"]))
    else:
        for combo in itertools.combinations(elig_emps, mp):
            for wc in matching_wcs:
                options.append((list(combo), wc["id"]))
    return options, elig_emps


def solve(db_path, order_ids, policy, locked: Optional[Dict[str, Dict[str, Any]]] = None, time_limit_sec: float = 10.0):
    locked = locked or {}
    tasks, orders, wcs, maint_by_wc, emps, skills, certs, prev_assign = _load_inputs(db_path, order_ids, policy)
    horizon_days = int(policy["horizon_days"])
    horizon_slots = horizon_days * 24 * SLOTS_PER_HOUR
    hs = resolve_horizon_start(policy)

    # task date for eligibility: use horizon start (proposed). Cert/leave evaluated at horizon start.
    task_date = hs

    # Build candidate options per task
    task_options: Dict[str, List[Tuple[List[str], str]]] = {}
    zero_elig_tasks = []
    task_has_valid = {t['id']: False for t in tasks}
    for t in tasks:
        opts, elig = _eligible_options(t, policy, emps, skills, certs, wcs, task_date)
        task_options[t["id"]] = opts
        if not opts:
            zero_elig_tasks.append(t["id"])

    # If any task has zero options -> infeasible evidence (but still run solver? no options => infeasible)
    # We'll still attempt; solver will be infeasible.

    model = cp_model.CpModel()

    # interval vars: (task_id, option_index) -> {start, end, presence, size}
    intervals: Dict[Tuple[str, int], Dict[str, Any]] = {}
    # map employee -> list of (interval_var, presence) for no-overlap
    emp_intervals: Dict[str, List[cp_model.IntervalVar]] = {e: [] for e in emps}
    wc_intervals: Dict[str, List[cp_model.IntervalVar]] = {w: [] for w in wcs}

    # day booleans per interval
    interval_days: Dict[Tuple[str, int], List[cp_model.BoolVar]] = {}

    all_interval_keys = []

    for t in tasks:
        tid = t["id"]
        dur_slots = _slots(int(t["duration_min"]))
        opts = task_options[tid]
        # create optional interval per option
        ivars_for_task = []
        for oi, (emp_ids, wc_id) in enumerate(opts):
            key = (tid, oi)
            start = model.NewIntVar(0, horizon_slots - dur_slots, f"start_{tid}_{oi}")
            end = model.NewIntVar(dur_slots, horizon_slots, f"end_{tid}_{oi}")
            pres = model.NewBoolVar(f"pres_{tid}_{oi}")
            iv = model.NewOptionalIntervalVar(start, dur_slots, end, pres, f"iv_{tid}_{oi}")
            intervals[key] = {"start": start, "end": end, "pres": pres, "dur": dur_slots, "emps": emp_ids, "wc": wc_id}
            ivars_for_task.append((key, iv))
            all_interval_keys.append(key)
            # no-overlap accumulation
            for eid in emp_ids:
                emp_intervals[eid].append(iv)
            wc_intervals[wc_id].append(iv)

            # valid starts: restrict to shift windows of all assigned employees on working days
            valid_starts = []
            for d in range(horizon_days):
                day_date = hs + timedelta(days=d)
                if not is_working_day(day_date, policy):
                    continue
                # leave check for all emps
                leave_bad = False
                for eid in emp_ids:
                    if _is_on_leave(emps[eid], day_date.isoformat()):
                        leave_bad = True
                        break
                if leave_bad:
                    continue
                # shift must be same for all? employees may have different shifts; require same shift start/end across all
                shifts = [emps[eid]["shift"] for eid in emp_ids]
                if len(set(shifts)) != 1:
                    continue
                sh, se_shift = shift_slots(shifts[0], policy)
                if sh + dur_slots > se_shift:
                    continue
                # maintenance overlap for wc
                s_slot = day_start_slot(d) + sh
                e_slot = s_slot + dur_slots
                maint_bad = False
                for (ms, me) in maint_by_wc.get(wc_id, []):
                    if not (e_slot <= ms or s_slot >= me):
                        maint_bad = True
                        break
                if maint_bad:
                    continue
                valid_starts.append(s_slot)
            if valid_starts:
                model.AddAllowedAssignments([start], [(s,) for s in valid_starts])
                task_has_valid[tid] = True
            else:
                # no valid start -> force absence
                model.Add(pres == 0)

            # day booleans
            days_bools = []
            for d in range(horizon_days):
                b = model.NewBoolVar(f"day_{tid}_{oi}_{d}")
                days_bools.append(b)
            interval_days[key] = days_bools
            # presence <-> sum day bools
            model.Add(pres == sum(days_bools))
            for d in range(horizon_days):
                b = days_bools[d]
                day_slot = day_start_slot(d) + shift_slots(emps[emp_ids[0]]["shift"], policy)[0]
                # b -> start == day_slot
                model.Add(start == day_slot).OnlyEnforceIf(b)
                # b -> pres
                model.AddImplication(b, pres)

        # exactly one option chosen (if any options)
        if opts:
            model.Add(sum(intervals[(tid, oi)]["pres"] for oi in range(len(opts))) == 1)
        else:
            # no eligible option -> infeasible: add impossible constraint
            model.Add(0 == 1)

        # locked handling
        lk = locked.get(tid)
        if lk:
            # find option matching locked employees + wc + start
            target_oi = None
            for oi, (emp_ids, wc_id) in enumerate(opts):
                if sorted(emp_ids) == sorted(lk["employee_ids"]) and wc_id == lk["work_center_id"]:
                    target_oi = oi
                    break
            if target_oi is not None:
                iv = intervals[(tid, target_oi)]
                model.Add(iv["pres"] == 1)
                model.Add(iv["start"] == int(lk["start_slot"]))
                # end fixed by duration anyway
            # if no matching option, infeasible (conflict) -> solver infeasible

        # precedence
        for dep in (json.loads(t["depends_on"] or "[]")):
            # dep task must end before this starts. Use a big-M over its options.
            # We'll add constraints after all intervals created; handle via post-pass below.
            pass

    # mark tasks with options but no valid start as zero-eligibility
    for t in tasks:
        if task_options[t['id']] and not task_has_valid[t['id']] and t['id'] not in zero_elig_tasks:
            zero_elig_tasks.append(t['id'])

    # no-overlap per employee
    for eid in emps:
        if emp_intervals[eid]:
            model.AddNoOverlap(emp_intervals[eid])
    # no-overlap per work center
    for wid in wcs:
        if wc_intervals[wid]:
            model.AddNoOverlap(wc_intervals[wid])

    # precedence constraints: for each task, for each of its options, and each dep task's options,
    # if both present then dep.end <= this.start. Use AddImplication with presence bools.
    task_by_id = {t["id"]: t for t in tasks}
    for t in tasks:
        tid = t["id"]
        deps = json.loads(t["depends_on"] or "[]")
        for dep_id in deps:
            # for each option of tid and dep
            for oi in range(len(task_options[tid])):
                for oj in range(len(task_options[dep_id])):
                    iv_t = intervals[(tid, oi)]
                    iv_d = intervals[(dep_id, oj)]
                    # if both present: end_dep <= start_t
                    # model: pres_d AND pres_t -> end_d <= start_t
                    # use: end_d - start_t <= 0 + M*(1-pres_d + 1-pres_t)
                    M = horizon_slots
                    model.Add(iv_d["end"] - iv_t["start"] <= M * (2 - iv_d["pres"] - iv_t["pres"]))

    # daily hours / overtime cap per employee
    std_hours = float(policy.get("standard_daily_hours", 8))
    ot_cap = float(policy.get("overtime_cap_hours", 2))
    max_cap = float(policy.get("max_daily_hours_cap", 10))
    cap_hours = min(std_hours + ot_cap, max_cap)
    cap_slots_hours = cap_hours  # in hours; durations converted
    for eid in emps:
        for d in range(horizon_days):
            # sum durations (hours) of intervals involving eid on day d <= cap
            terms = []
            for key in all_interval_keys:
                iv = intervals[key]
                if eid not in iv["emps"]:
                    continue
                dur_h = iv["dur"] / SLOTS_PER_HOUR
                b = interval_days[key][d]
                # contribution = dur_h * b
                # scale to integer: use slots; cap in slots
                terms.append((iv["dur"], b))
            if not terms:
                continue
            # sum dur_slots * b <= cap_slots
            cap_slots = int(cap_hours * SLOTS_PER_HOUR)
            model.Add(sum(dur * b for dur, b in terms) <= cap_slots)

    # objective
    w = policy.get("objective_weights", {})
    ow_on_time = float(w.get("on_time", 10.0))
    ow_ot = float(w.get("overtime", 3.0))
    ow_bal = float(w.get("balance", 2.0))
    ow_mk = float(w.get("makespan", 1.0))
    ow_re = float(w.get("reassignment", 2.0))
    ow_cont = float(w.get("continuity", 2.0))
    prio = policy.get("priority_weights", {"Urgent": 4, "High": 2, "Normal": 1})

    # lateness per order
    order_ids_list = list({t["order_id"] for t in tasks})
    # due slot per order
    def due_slot(oid):
        od = orders[oid]
        dd = od["due_date"]
        from datetime import datetime as _dt
        ddate = _dt.strptime(dd, "%Y-%m-%d").date()
        # slot = (ddate - hs).days * 24*4 + 24*4 - 1 (end of day) but clamp >=0
        delta = (ddate - hs).days
        if delta < 0:
            delta = 0
        return delta * 24 * SLOTS_PER_HOUR + (24 * SLOTS_PER_HOUR - 1)

    lateness_terms = []
    for oid in order_ids_list:
        # delivery end = max end of tasks of that order
        o_tasks = [t for t in tasks if t["order_id"] == oid]
        if not o_tasks:
            continue
        # create an int var for delivery end via max of ends of chosen intervals
        # We'll use max of end vars guarded by presence; use AddMaxEquality over all option ends with presence? 
        # Simpler: delivery_end >= end for each present interval; minimize delivery_end.
        deliv = model.NewIntVar(0, horizon_slots, f"deliv_{oid}")
        for t in o_tasks:
            for oi in range(len(task_options[t["id"]])):
                iv = intervals[(t["id"], oi)]
                # if present, deliv >= end
                model.Add(deliv >= iv["end"]).OnlyEnforceIf(iv["pres"])
        # tardiness
        tard = model.NewIntVar(0, horizon_slots, f"tard_{oid}")
        model.Add(tard >= deliv - due_slot(oid))
        model.Add(tard >= 0)
        weight = prio.get(orders[oid]["priority"], 1)
        lateness_terms.append(ow_on_time * weight * tard)

    # makespan
    makespan = model.NewIntVar(0, horizon_slots, "makespan")
    for key in all_interval_keys:
        iv = intervals[key]
        model.Add(makespan >= iv["end"]).OnlyEnforceIf(iv["pres"])
    mk_term = ow_mk * makespan

    # overtime: sum over employee-days of max(0, hours - std) 
    ot_terms = []
    for eid in emps:
        for d in range(horizon_days):
            # total hours that day
            day_hours_var = None
            # sum dur (slots) * b
            slot_terms = []
            for key in all_interval_keys:
                iv = intervals[key]
                if eid not in iv["emps"]:
                    continue
                b = interval_days[key][d]
                slot_terms.append(iv["dur"] * b)
            if not slot_terms:
                continue
            total_slots_day = model.NewIntVar(0, horizon_slots, f"tot_{eid}_{d}")
            model.Add(total_slots_day == sum(slot_terms))
            std_slots = int(std_hours * SLOTS_PER_HOUR)
            ot = model.NewIntVar(0, horizon_slots, f"ot_{eid}_{d}")
            model.Add(ot >= total_slots_day - std_slots)
            model.Add(ot >= 0)
            ot_terms.append(ot)
    ot_term = ow_ot * sum(ot_terms) if ot_terms else 0

    # balance: max - min assigned hours across employees
    emp_total_slots = []
    for eid in emps:
        ts = []
        for key in all_interval_keys:
            iv = intervals[key]
            if eid not in iv["emps"]:
                continue
            ts.append(iv["dur"] * iv["pres"])
        if ts:
            tot = model.NewIntVar(0, horizon_slots, f"emptot_{eid}")
            model.Add(tot == sum(ts))
            emp_total_slots.append(tot)
        else:
            emp_total_slots.append(model.NewConstant(0))
    if emp_total_slots:
        maxh = model.NewIntVar(0, horizon_slots, "maxh")
        minh = model.NewIntVar(0, horizon_slots, "minh")
        model.AddMaxEquality(maxh, emp_total_slots)
        model.AddMinEquality(minh, emp_total_slots)
        bal_term = ow_bal * (maxh - minh)
    else:
        bal_term = 0

    # reassignment penalty: task assigned to different employee than prev
    re_terms = []
    for t in tasks:
        tid = t["id"]
        prev = prev_assign.get(tid)
        if not prev:
            continue
        prev_emps = set(json.loads(prev["employee_ids"]))
        # for each option, if present and emps != prev_emps -> penalty 1
        for oi in range(len(task_options[tid])):
            iv = intervals[(tid, oi)]
            if set(iv["emps"]) == prev_emps:
                continue
            # penalty bool = pres (since different assignment)
            re_terms.append(ow_re * iv["pres"])
    re_term = sum(re_terms) if re_terms else 0

    # continuity bonus: chunks of same parent on same employee as prev -> reward (negative cost)
    cont_terms = []
    for t in tasks:
        tid = t["id"]
        prev = prev_assign.get(tid)
        if not prev:
            continue
        prev_emps = set(json.loads(prev["employee_ids"]))
        for oi in range(len(task_options[tid])):
            iv = intervals[(tid, oi)]
            if set(iv["emps"]) == prev_emps:
                # reward: subtract
                cont_terms.append(iv["pres"])
    cont_term = -ow_cont * sum(cont_terms) if cont_terms else 0

    objective = sum(lateness_terms) + mk_term + ot_term + bal_term + re_term + cont_term
    model.Minimize(objective)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_sec
    solver.parameters.num_search_workers = 4
    solver.parameters.log_search_progress = False

    t0 = time.time()
    status = solver.Solve(model)
    runtime = time.time() - t0

    status_name = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.UNKNOWN: "UNKNOWN",
        cp_model.MODEL_INVALID: "MODEL_INVALID",
    }.get(status, str(status))

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {
            "status": status_name,
            "runtime": runtime,
            "objective": None,
            "assignments": [],
            "zero_eligibility": zero_elig_tasks,
        }

    # extract assignments
    assignments = []
    for t in tasks:
        tid = t["id"]
        chosen = None
        for oi in range(len(task_options[tid])):
            iv = intervals[(tid, oi)]
            if solver.Value(iv["pres"]) == 1:
                chosen = (oi, iv)
                break
        if chosen is None:
            continue
        oi, iv = chosen
        emps_ids = iv["emps"]
        wc_id = iv["wc"]
        start = int(solver.Value(iv["start"]))
        end = int(solver.Value(iv["end"]))
        # why
        trow = next((t for t in tasks if t['id'] == tid), {})
        why = _why(tid, emps_ids, wc_id, iv, policy, emps, skills, prev_assign, trow.get('required_skill', ''))
        assignments.append(Assignment(
            task_id=tid,
            employee_ids=list(emps_ids),
            work_center_id=wc_id,
            start_slot=start,
            end_slot=end,
            locked=bool(locked.get(tid, {}).get("locked", False)),
            why=why,
        ))

    return {
        "status": status_name,
        "runtime": runtime,
        "objective": float(solver.ObjectiveValue()),
        "assignments": assignments,
        "zero_eligibility": zero_elig_tasks,
    }


def _why(task_id, emp_ids, wc_id, iv, policy, emps, skills, prev_assign, req_skill=''):
    # build a plain-English why dict
    trow = None
    return {
        "employees": [emps[e]["name"] for e in emp_ids],
        "work_center": wc_id,
        "skill_match": {e: skills.get(e, {}).get(req_skill, 0) for e in emp_ids},
        "shift_fit": "within configured shift window",
        "continuity": (task_id in prev_assign and set(json.loads(prev_assign[task_id]["employee_ids"])) == set(emp_ids)),
    }


def validate_schedule(assignments, tasks, policy, db_path=None):
    """Return list of hard-constraint violations (empty = valid)."""
    from core.config import resolve_horizon_start
    violations = []
    # index tasks
    tmap = {t["id"] if isinstance(t, dict) else t.id: t for t in tasks}
    # per employee overlap
    by_emp: dict = {}
    for a in assignments:
        for e in a.employee_ids:
            by_emp.setdefault(e, []).append(a)
    for e, asg in by_emp.items():
        asg_sorted = sorted(asg, key=lambda x: x.start_slot)
        for i in range(len(asg_sorted) - 1):
            if asg_sorted[i].end_slot > asg_sorted[i + 1].start_slot:
                violations.append(f"overlap for employee {e}: {asg_sorted[i].task_id} vs {asg_sorted[i+1].task_id}")
    # per work center overlap
    by_wc: dict = {}
    for a in assignments:
        by_wc.setdefault(a.work_center_id, []).append(a)
    for w, asg in by_wc.items():
        asg_sorted = sorted(asg, key=lambda x: x.start_slot)
        for i in range(len(asg_sorted) - 1):
            if asg_sorted[i].end_slot > asg_sorted[i + 1].start_slot:
                violations.append(f"overlap for work center {w}")
    # dependencies
    amap = {a.task_id: a for a in assignments}
    for t in tasks:
        tid = t["id"] if not isinstance(t, dict) else t["id"]
        deps = t.depends_on if not isinstance(t, dict) else (json.loads(t["depends_on"]) if isinstance(t["depends_on"], str) else t["depends_on"])
        for d in deps:
            if tid in amap and d in amap:
                if amap[d].end_slot > amap[tid].start_slot:
                    violations.append(f"dependency violated: {d} -> {tid}")
    # duration
    for a in assignments:
        t = tmap.get(a.task_id)
        dur = (t.duration_min if not isinstance(t, dict) else t["duration_min"])
        if a.end_slot - a.start_slot != (dur + 14) // 15:
            # allow exact slots
            if a.end_slot - a.start_slot != max(1, (dur + 14) // 15):
                violations.append(f"duration mismatch {a.task_id}")
    return violations