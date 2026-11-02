"""Business operations used by the API: plan, review, approve, replan, report."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from core.alerts import add_alert
from core.audit import log_action
from core.config import SLOTS_PER_DAY, SLOTS_PER_HOUR, fmt_slot, iso_slot, now_local, shift_slots, PRESETS, WEIGHT_LABELS
from core.db import get_conn
from core.eligibility import Context, check_employee, task_candidates
from core.solver import (approved_assignments, delivery_estimates, load_orders, load_tasks, solve, validate_schedule,
                         build_why)
from core.tasks import generate_tasks, list_tasks

FAIL_STATUSES = {"INFEASIBLE", "UNKNOWN", "MODEL_INVALID", "EMPTY", "BAD_DATA"}


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400, extra: Optional[dict] = None):
        super().__init__(message)
        self.message, self.status, self.extra = message, status, extra or {}


# ---------- versions ----------
def _save_version(db, res, label, parent=None, event=None, actor="system") -> str:
    vid = "V-" + uuid.uuid4().hex[:6].upper()
    conn = get_conn(db)
    conn.execute(
        "INSERT INTO schedule_versions (id,created_at,status,solver_status,solver_runtime_sec,objective_value,notes,parent_version_id,label) VALUES (?,?,?,?,?,?,?,?,?)",
        (vid, now_local().isoformat(timespec="seconds"), "draft", res["status"], res["runtime"], res["objective"] or 0.0,
         json.dumps({"event": event, "orders": res.get("orders", [])}), parent, label))
    for a in res["assignments"]:
        conn.execute(
            "INSERT INTO version_assignments (version_id,task_id,employee_ids,work_center_id,start_slot,end_slot,locked,why) VALUES (?,?,?,?,?,?,?,?)",
            (vid, a["task_id"], json.dumps(a["employee_ids"]), a["work_center_id"], a["start_slot"], a["end_slot"], 1 if a.get("locked") else 0, json.dumps(a.get("why", {}))))
    conn.commit()
    conn.close()
    return vid


def get_version(db, vid) -> dict:
    conn = get_conn(db)
    v = conn.execute("SELECT * FROM schedule_versions WHERE id=?", (vid,)).fetchone()
    if not v:
        conn.close()
        raise ApiError("That schedule version does not exist.", 404)
    rows = conn.execute("SELECT * FROM version_assignments WHERE version_id=?", (vid,)).fetchall()
    conn.close()
    v = dict(v)
    try:
        meta = json.loads(v.get("notes") or "{}")
        if not isinstance(meta, dict):
            meta = {"text": str(meta)}
    except Exception:
        meta = {"text": v.get("notes")}
    v["meta"] = meta
    assigns = []
    for r in rows:
        d = dict(r)
        d["employee_ids"] = json.loads(d["employee_ids"])
        d["locked"] = bool(d["locked"])
        d["why"] = json.loads(d["why"] or "{}")
        assigns.append(d)
    return {"version": v, "assignments": assigns}


def latest_version_id(db, status=None) -> Optional[str]:
    conn = get_conn(db)
    q = "SELECT id FROM schedule_versions" + (" WHERE status=?" if status else "") + " ORDER BY created_at DESC, rowid DESC LIMIT 1"
    r = conn.execute(q, (status,) if status else ()).fetchone()
    conn.close()
    return r["id"] if r else None


def enrich(db, vid) -> dict:
    """A version with names, real dates, per-order estimates and a hard-rule re-check."""
    ctx = Context(db)
    data = get_version(db, vid)
    tmap = {t["id"]: t for t in list_tasks(None, db)}
    orders = load_orders(db)
    items = []
    for a in data["assignments"]:
        t = tmap.get(a["task_id"])
        if not t:
            continue
        items.append({
            **a, "task_name": t["name"], "order_id": t["order_id"], "depends_on": t["depends_on"],
            "product": t["order_id"], "status": t["status"], "required_skill": t["required_skill"],
            "employees": [{"id": e, "name": ctx.emps[e]["name"], "team": ctx.emps[e]["team"], "shift": ctx.emps[e]["shift"]} for e in a["employee_ids"]],
            "work_center_name": ctx.wcs[a["work_center_id"]]["name"],
            "start_iso": iso_slot(a["start_slot"], ctx.hs), "end_iso": iso_slot(a["end_slot"], ctx.hs),
            "start_text": fmt_slot(a["start_slot"], ctx.hs), "end_text": fmt_slot(a["end_slot"], ctx.hs),
            "minutes": (a["end_slot"] - a["start_slot"]) * 15, "priority": orders[t["order_id"]]["priority"],
        })
    items.sort(key=lambda x: (x["start_slot"], x["task_id"]))
    tasks_in = [tmap[a["task_id"]] for a in data["assignments"] if a["task_id"] in tmap]
    violations = validate_schedule(data["assignments"], tasks_in, ctx)
    est = delivery_estimates(data["assignments"], tasks_in, orders, ctx)
    return {"version": data["version"], "assignments": items, "orders": est, "violations": violations,
            "horizon_start": ctx.hs.isoformat(), "horizon_days": ctx.policy["horizon_days"]}


# ---------- planning ----------
def plan(db, actor, role, order_ids=None, weights=None, preset=None) -> dict:
    ctx = Context(db)
    orders = load_orders(db)
    if order_ids is None:
        order_ids = [o for o, r in orders.items() if r["status"] not in ("Completed", "Cancelled")]
    if preset:
        if preset not in PRESETS:
            raise ApiError("Unknown preset.")
        weights = PRESETS[preset]["weights"]
    res = solve(db, order_ids, ctx.policy, weights=weights, ctx=ctx)
    out = {"status": res["status"], "message": res.get("message", ""), "runtime": round(res["runtime"], 2),
           "version_id": None, "zero_eligibility": res.get("zero_eligibility", [])}
    if res["status"] in ("OPTIMAL", "FEASIBLE"):
        vid = _save_version(db, res, "AI proposal" + (f" ({PRESETS[preset]['label']})" if preset else ""), actor=actor)
        out["version_id"] = vid
        risky = [o for o in res["orders"] if o["status"] != "on_time"]
        add_alert("schedule", "info", f"New AI proposal {vid} is ready for review.", link="approval", db_path=db)
        for o in risky:
            sev = "critical" if o["status"] == "late" else "warning"
            add_alert("delivery_risk", sev, f"Order {o['order_id']} is {'late' if o['status']=='late' else 'at risk'}: finishes {o['finish_text']}, due {o['due_date']}.", link="plan", db_path=db)
        log_action(actor, role, "generate_schedule", vid, after={"status": res["status"], "weights": weights or "policy default"},
                   reason="AI proposal", version_id=vid, db_path=db)
        detail = enrich(db, vid)
        out.update(detail)
    elif res["status"] == "INFEASIBLE":
        out["diagnosis"] = diagnose(db, order_ids, {"weights": weights})
    return out


def diagnose(db, order_ids, base: dict, absent_days: Optional[dict] = None) -> dict:
    """Honest explanation when no plan exists: proven evidence plus labelled what-if tests."""
    ctx = Context(db)
    apply_event_overlay(ctx, absent_days or {}, {})
    res = solve(db, order_ids, ctx.policy, ctx=ctx, time_limit_sec=4, **{k: v for k, v in (base or {}).items() if v})
    tasks = {t["id"]: t for t in load_tasks(order_ids, db)}
    zero = []
    for z in res.get("zero_eligibility", []):
        t = tasks.get(z["task_id"])
        if t:
            zero.append({"task_id": t["id"], "task_name": t["name"], "order_id": t["order_id"],
                         "needs": f"{t['required_skill']} level {t['min_level']}" + (f" + {t['extra_skill']}" if t.get("extra_skill") else "") + (f", role {t['required_role']}"),
                         "why": _why_nobody(t, ctx)})
    tests = []
    kw = lambda **x: {**{k: v for k, v in (base or {}).items() if v}, **x}
    def run(label, what_if, **x):
        c2 = Context(db)
        apply_event_overlay(c2, absent_days or {}, {})
        if x.pop("_restore", None):
            for eid in x.pop("_who", []):
                c2.emps[eid]["leave"] = set()
        r = solve(db, order_ids, c2.policy, ctx=c2, time_limit_sec=4, **x)
        tests.append({"label": label, "what_if": what_if, "result": r["status"], "fixes": r["status"] in ("OPTIMAL", "FEASIBLE")})
    run("Ignore due dates (test only)", "If every due date were removed", ignore_due=True)
    run("Allow 2 more hours of overtime (test only)", "If the daily overtime cap were raised by 2 hours", extra_overtime_hours=2.0)
    run("Plan over 14 days (test only)", "If the planning window were two weeks instead of one", horizon_days=14)
    remedies, blockers = [], []
    gone = sorted((absent_days or {}).keys())
    if gone:
        for eid in gone:
            r = {"label": f"Bring {ctx.emps[eid]['name']} back (test only)", "what_if": f"If {ctx.emps[eid]['name']} were available again"}
            c2 = Context(db)
            apply_event_overlay(c2, {k: v for k, v in (absent_days or {}).items() if k != eid}, {})
            rr = solve(db, order_ids, c2.policy, ctx=c2, time_limit_sec=4, **{k: v for k, v in (base or {}).items() if v})
            r.update(result=rr["status"], fixes=rr["status"] in ("OPTIMAL", "FEASIBLE"))
            tests.append(r)
            if r["fixes"]:
                remedies.append(f"Mark {ctx.emps[eid]['name']} as available again (the test found a valid plan).")
    for tt in tests:
        if tt["fixes"] and "Bring" not in tt["label"]:
            remedies.append(f"{tt['what_if']}: a valid plan exists. Needs the manager's decision.")
    if zero:
        blockers.append("Hard rule: " + "; ".join(sorted({z['why'] for z in zero})) + ".")
    if not remedies:
        remedies.append("No change inside this app can fix this. The missing skill or certificate has to come from outside, for example by adding a qualified person to the workforce list or re-certifying someone. Due dates and overtime do not create a certified worker.")
    return {"status": res["status"], "message": res.get("message", ""), "zero_eligibility": zero, "relaxation_tests": tests,
            "likely_blocking_constraints": blockers or ["The tests below suggest which limit is binding. These are tests, not proof."],
            "remedies": remedies, "no_assignment_invented": True}


def _why_nobody(t, ctx: Context) -> str:
    day_reasons = {}
    for d in range(ctx.policy["horizon_days"]):
        c = task_candidates(t, ctx.day(d), ctx)
        for ex in c["excluded"]:
            if ex["kind"] == "blocked":
                day_reasons.setdefault(ex["person"], ex["reasons"][0])
    need = f"{t['required_skill']} level {t['min_level']}"
    if t.get("extra_skill"):
        need += f" and {t['extra_skill']}"
    s = f"nobody available this week has {need}"
    if t.get("required_cert"):
        s += f" with a valid {t['required_cert']}"
    return s


# ---------- editing ----------
def _require(policy, action, role):
    need = policy["approval_levels"].get(action, "Production Manager")
    if role not in {need, "Production Manager"}:
        raise ApiError(f"{role} is not allowed to do this. It needs the {need}.", 403)


def candidates_for(db, vid, task_id) -> dict:
    ctx = Context(db)
    data = get_version(db, vid)
    a = next((x for x in data["assignments"] if x["task_id"] == task_id), None)
    if not a:
        raise ApiError("That task is not in this schedule.", 404)
    t = next(t for t in list_tasks(None, db) if t["id"] == task_id)
    day = ctx.day(a["start_slot"] // SLOTS_PER_DAY)
    c = task_candidates(t, day, ctx)
    ok = []
    for cd in c["candidates"]:
        # must also be free at that time and keep the same shift
        free = True
        for o in data["assignments"]:
            if o["task_id"] != task_id and cd["employee_id"] in o["employee_ids"] and o["start_slot"] < a["end_slot"] and o["end_slot"] > a["start_slot"]:
                free = False
        s, e = shift_slots(ctx.emps[cd["employee_id"]]["shift"], ctx.policy)
        offs = a["start_slot"] % SLOTS_PER_DAY
        in_shift = offs >= s and (a["end_slot"] - (a["start_slot"] // SLOTS_PER_DAY) * SLOTS_PER_DAY) <= e + 8
        cd["free_at_that_time"] = free
        cd["in_shift"] = in_shift
        if free and in_shift:
            ok.append(cd)
    return {"task_id": task_id, "valid_candidates": ok, "all_checked": c["candidates"], "excluded": c["excluded"]}


def reassign(db, actor, role, vid, task_id, employee_ids: List[str], reason: str):
    ctx = Context(db)
    _require(ctx.policy, "reassign", role)
    if not (reason or "").strip():
        raise ApiError("Please give a reason. Every change to the plan is recorded.")
    data = get_version(db, vid)
    if data["version"]["status"] != "draft":
        raise ApiError("Only a draft proposal can be edited. Generate or replan to get a new draft.")
    a = next((x for x in data["assignments"] if x["task_id"] == task_id), None)
    if not a:
        raise ApiError("That task is not in this schedule.", 404)
    if a["locked"]:
        raise ApiError("This assignment is locked. Unlock it first, with a reason.")
    t = next(t for t in list_tasks(None, db) if t["id"] == task_id)
    new = sorted(employee_ids)
    trial = [dict(x) for x in data["assignments"]]
    for x in trial:
        if x["task_id"] == task_id:
            x["employee_ids"] = new
    tasks_in = [tt for tt in list_tasks(None, db) if tt["id"] in {x["task_id"] for x in trial}]
    viol = [v for v in validate_schedule(trial, tasks_in, ctx) if t["name"] in v or task_id in v or any(ctx.emps[e]["name"] in v for e in new)]
    if viol:
        raise ApiError("That change breaks a hard rule, so it was not applied: " + viol[0], 422, {"violations": viol})
    conn = get_conn(db)
    conn.execute("UPDATE version_assignments SET employee_ids=? WHERE version_id=? AND task_id=?", (json.dumps(new), vid, task_id))
    conn.commit()
    conn.close()
    ctx2 = Context(db)
    hours = {}
    for x in trial:
        for e in x["employee_ids"]:
            hours[e] = hours.get(e, 0) + (x["end_slot"] - x["start_slot"]) / SLOTS_PER_HOUR
    why = build_why({**a, "employee_ids": new}, t, ctx2, set(), set(), hours, {}, trial)
    why["summary"] = "Chosen by the manager: " + why["summary"] + f" Reason given: {reason.strip()}"
    conn = get_conn(db)
    conn.execute("UPDATE version_assignments SET why=? WHERE version_id=? AND task_id=?", (json.dumps(why), vid, task_id))
    conn.commit()
    conn.close()
    names = lambda ids: ", ".join(ctx.emps[i]["name"] for i in ids)
    log_action(actor, role, "reassign", task_id, before=names(a["employee_ids"]), after=names(new), reason=reason.strip(), version_id=vid, db_path=db)
    add_alert("schedule_change", "warning", f"{t['name']} ({t['order_id']}) moved from {names(a['employee_ids'])} to {names(new)}: {reason.strip()}", link="approval", db_path=db)


def set_lock(db, actor, role, vid, task_id, lock: bool, reason: str = ""):
    ctx = Context(db)
    _require(ctx.policy, "unlock_locked" if not lock else "reassign", role)
    if not lock and not (reason or "").strip():
        raise ApiError("Unlocking needs a reason. It is recorded in the audit log.")
    conn = get_conn(db)
    cur = conn.execute("UPDATE version_assignments SET locked=? WHERE version_id=? AND task_id=?", (1 if lock else 0, vid, task_id))
    if cur.rowcount == 0:
        conn.close()
        raise ApiError("That task is not in this schedule.", 404)
    conn.commit()
    conn.close()
    log_action(actor, role, "lock" if lock else "unlock", task_id, before=not lock, after=lock, reason=reason or "locked by manager", version_id=vid, db_path=db)


def approve(db, actor, role, vid):
    ctx = Context(db)
    _require(ctx.policy, "approve_schedule", role)
    det = enrich(db, vid)
    if det["version"]["status"] != "draft":
        raise ApiError("Only a draft proposal can be approved.")
    if det["violations"]:
        raise ApiError("This plan breaks hard rules and cannot be approved: " + det["violations"][0], 422, {"violations": det["violations"]})
    event = (det["version"]["meta"] or {}).get("event")
    conn = get_conn(db)
    conn.execute("UPDATE schedule_versions SET status='superseded' WHERE status='approved'")
    conn.execute("UPDATE schedule_versions SET status='approved', approved_by=?, approved_at=? WHERE id=?", (role, now_local().isoformat(timespec="seconds"), vid))
    conn.execute("UPDATE tasks SET planned_start=NULL, planned_end=NULL, employee_ids=NULL, work_center_id=NULL, locked=0 WHERE status NOT IN ('Completed','Cancelled')")
    for a in det["assignments"]:
        conn.execute("UPDATE tasks SET planned_start=?, planned_end=?, employee_ids=?, work_center_id=?, locked=?, status=CASE WHEN status='Planned' THEN 'Assigned' ELSE status END WHERE id=?",
                     (a["start_slot"], a["end_slot"], json.dumps(a["employee_ids"]), a["work_center_id"], 1 if a["locked"] else 0, a["task_id"]))
    conn.commit()
    conn.close()
    if event:
        persist_event(db, event, ctx)
    log_action(actor, role, "approve_schedule", vid, before="draft", after="approved", reason="manager approval", version_id=vid, db_path=db)
    add_alert("schedule_change", "info", f"Schedule {vid} approved by {role}. {len(det['assignments'])} assignments are now live.", link="gantt", db_path=db)
    for e in sorted({e["id"] for a in det["assignments"] for e in a["employees"]}):
        n = sum(1 for a in det["assignments"] if e in a["employee_ids"])
        add_alert("assignment", "info", f"{ctx.emps[e]['name']} has {n} assigned task(s) in the approved schedule.", link="mytasks", db_path=db)
    for o in det["orders"]:
        if o["status"] != "on_time":
            add_alert("delivery_risk", "critical" if o["status"] == "late" else "warning",
                      f"Order {o['order_id']} is {'late' if o['status']=='late' else 'at risk'} in the approved plan (finishes {o['finish_text']}, due {o['due_date']}).", link="reports", db_path=db)
    return det


def reject(db, actor, role, vid, reason):
    ctx = Context(db)
    _require(ctx.policy, "approve_schedule", role)
    if not (reason or "").strip():
        raise ApiError("Please give a reason for rejecting.")
    conn = get_conn(db)
    cur = conn.execute("UPDATE schedule_versions SET status='rejected' WHERE id=? AND status='draft'", (vid,))
    if cur.rowcount == 0:
        conn.close()
        raise ApiError("Only a draft proposal can be rejected.")
    conn.commit()
    conn.close()
    log_action(actor, role, "reject_schedule", vid, before="draft", after="rejected", reason=reason.strip(), version_id=vid, db_path=db)


# ---------- replanning ----------
def apply_event_overlay(ctx: Context, absent_days: Dict[str, List[int]], down: Dict[str, List[int]]):
    """Make absences / breakdowns visible to the rules without touching stored data."""
    for eid, days in absent_days.items():
        for d in days:
            ctx.emps[eid]["leave"].add(ctx.day(d).isoformat())
    for wc, days in down.items():
        for d in days:
            ctx.maint.setdefault(wc, []).append((d * SLOTS_PER_DAY, (d + 1) * SLOTS_PER_DAY, "breakdown"))


def persist_event(db, event, ctx: Context):
    conn = get_conn(db)
    t = event.get("type")
    if t == "absence":
        e = conn.execute("SELECT leave_dates FROM employees WHERE id=?", (event["employee_id"],)).fetchone()
        cur = set(json.loads(e["leave_dates"] or "[]"))
        cur |= {ctx.day(d).isoformat() for d in event["days"]}
        conn.execute("UPDATE employees SET leave_dates=? WHERE id=?", (json.dumps(sorted(cur)), event["employee_id"]))
    elif t == "breakdown":
        for d in event["days"]:
            conn.execute("INSERT INTO maintenance (work_center_id,start_slot,end_slot,reason) VALUES (?,?,?,?)",
                         (event["work_center_id"], d * SLOTS_PER_DAY, (d + 1) * SLOTS_PER_DAY, "Breakdown (simulated)"))
    elif t == "delay":
        conn.execute("UPDATE tasks SET duration_min=duration_min+? WHERE id=?", (event["minutes"], event["task_id"]))
    elif t == "priority":
        conn.execute("UPDATE orders SET priority=? WHERE id=?", (event["priority"], event["order_id"]))
    conn.commit()
    conn.close()


def _downstream(tasks, seeds: set) -> set:
    out = set(seeds)
    changed = True
    while changed:
        changed = False
        for t in tasks:
            if t["id"] not in out and any(d in out for d in t["depends_on"]):
                out.add(t["id"])
                changed = True
    return out


def diff_versions(db, old_vid, new_vid) -> dict:
    o, n = enrich(db, old_vid), enrich(db, new_vid)
    om, nm = {a["task_id"]: a for a in o["assignments"]}, {a["task_id"]: a for a in n["assignments"]}
    moved, shifted, same = [], [], 0
    for tid, b in nm.items():
        a = om.get(tid)
        if not a:
            moved.append({"task_id": tid, "task_name": b["task_name"], "order_id": b["order_id"], "kind": "new",
                          "text": f"New: {b['task_name']} ({b['order_id']}) goes to {', '.join(e['name'] for e in b['employees'])}, {b['start_text']}"})
            continue
        if a["employee_ids"] != b["employee_ids"]:
            moved.append({"task_id": tid, "task_name": b["task_name"], "order_id": b["order_id"], "kind": "person",
                          "from": [e["name"] for e in a["employees"]], "to": [e["name"] for e in b["employees"]],
                          "text": f"{b['task_name']} ({b['order_id']}): {', '.join(e['name'] for e in a['employees'])} replaced by {', '.join(e['name'] for e in b['employees'])}"})
        elif a["start_slot"] != b["start_slot"] or a["work_center_id"] != b["work_center_id"]:
            shifted.append({"task_id": tid, "task_name": b["task_name"], "order_id": b["order_id"], "kind": "time",
                            "text": f"{b['task_name']} ({b['order_id']}): {a['start_text']} to {b['start_text']}" + (f", machine {a['work_center_id']} to {b['work_center_id']}" if a["work_center_id"] != b["work_center_id"] else "")})
        else:
            same += 1
    impact = []
    oo = {x["order_id"]: x for x in o["orders"]}
    for x in n["orders"]:
        y = oo.get(x["order_id"])
        if y and (y["finish_slot"] != x["finish_slot"] or y["status"] != x["status"]):
            impact.append({"order_id": x["order_id"], "before": y["finish_text"], "after": x["finish_text"], "before_status": y["status"], "after_status": x["status"]})
    return {"moved": moved, "shifted": shifted, "unchanged": same, "delivery_impact": impact}


def replan(db, actor, role, event: dict) -> dict:
    ctx = Context(db)
    _require(ctx.policy, "reassign", role)
    typ = event.get("type")
    orders = load_orders(db)
    order_ids = [o for o, r in orders.items() if r["status"] not in ("Completed", "Cancelled")]
    if typ == "impossible":
        return impossible_case(db, actor, role)
    base_vid = latest_version_id(db, "approved")
    if not base_vid:
        raise ApiError("There is no approved schedule yet. Generate a schedule and approve it first, then simulate a surprise.", 409)
    base = enrich(db, base_vid)
    tasks = list_tasks(None, db)
    tmap = {t["id"]: t for t in tasks}
    base_asg = {a["task_id"]: a for a in base["assignments"]}
    absent_days: Dict[str, List[int]] = {}
    down: Dict[str, List[int]] = {}
    affected: set = set()
    new_tasks: List[dict] = []
    explain = ""
    ev = dict(event)
    first_day = int(event.get("from_day", 0))
    days = [d for d in range(first_day, first_day + int(event.get("days", 2))) if d < ctx.policy["horizon_days"]]

    if typ == "absence":
        eid = event["employee_id"]
        if eid not in ctx.emps:
            raise ApiError("Unknown employee.")
        absent_days[eid] = days
        ev.update(days=days)
        for tid, a in base_asg.items():
            if eid in a["employee_ids"] and a["start_slot"] // SLOTS_PER_DAY in days:
                affected.add(tid)
        explain = f"{ctx.emps[eid]['name']} is absent on {', '.join(f'{ctx.day(d):%a %d %b}' for d in days)}."
    elif typ == "breakdown":
        wc = event["work_center_id"]
        if wc not in ctx.wcs:
            raise ApiError("Unknown machine.")
        down[wc] = days
        ev.update(days=days)
        for tid, a in base_asg.items():
            if a["work_center_id"] == wc and a["start_slot"] // SLOTS_PER_DAY in days:
                affected.add(tid)
        explain = f"{ctx.wcs[wc]['name']} is out of service on {', '.join(f'{ctx.day(d):%a %d %b}' for d in days)}."
    elif typ == "delay":
        tid = event["task_id"]
        if tid not in tmap:
            raise ApiError("Unknown task.")
        mins = int(event.get("minutes", 120))
        if mins <= 0 or mins > 480:
            raise ApiError("A delay must be between 15 and 480 minutes.")
        ev["minutes"] = mins
        affected.add(tid)
        explain = f"{tmap[tid]['name']} ({tmap[tid]['order_id']}) will take {mins} minutes longer."
    elif typ == "priority":
        oid, pr = event["order_id"], event["priority"]
        if oid not in orders or pr not in ctx.policy["priority_weights"]:
            raise ApiError("Unknown order or priority.")
        affected = {t["id"] for t in tasks if t["order_id"] == oid}
        explain = f"Order {oid} priority changed from {orders[oid]['priority']} to {pr}."
    elif typ == "urgent_order":
        pid = event.get("product_id", "P-ALU-FLANGE")
        due = event.get("due_date") or (ctx.hs + timedelta(days=3)).isoformat()
        oid = create_order(db, actor, role, {"product_id": pid, "quantity": int(event.get("quantity", 10)), "priority": "Urgent",
                                              "due_date": due, "customer_commitment": "Urgent walk-in order (simulated)", "notes": event.get("notes", "")})["order_id"]
        order_ids.append(oid)
        tasks = list_tasks(None, db)
        tmap = {t["id"]: t for t in tasks}
        affected = {t["id"] for t in tasks if t["order_id"] == oid}
        ev["order_id"] = oid
        explain = f"A new urgent order {oid} arrived."
    else:
        raise ApiError("Unknown event type.")

    # tasks tied to a person/machine/priority change (and their followers) may move; locked ones may not
    movable = _downstream(tasks, affected) if typ != "priority" else {t["id"] for t in tasks}
    locked_hit = [tid for tid in (affected if typ in ("absence", "breakdown") else set()) if base_asg.get(tid, {}).get("locked")]
    if locked_hit:
        conflicts = []
        for tid in locked_hit:
            a = base_asg[tid]
            conflicts.append({"task_id": tid, "task_name": a["task_name"], "order_id": a["order_id"], "who": [e["name"] for e in a["employees"]],
                              "when": a["start_text"], "text": f"{a['task_name']} ({a['order_id']}) is locked to {', '.join(e['name'] for e in a['employees'])} on {a['start_text']}, but that is no longer possible."})
        log_action(actor, role, "replan_conflict", ",".join(locked_hit), after=explain, reason="locked assignment affected by event", version_id=base_vid, db_path=db)
        add_alert("conflict", "critical", f"{explain} {len(conflicts)} locked assignment(s) are affected and need a manager decision.", link="live", db_path=db)
        return {"result": "conflict", "event_text": explain, "conflicts": conflicts, "requires_unlock": True,
                "message": "Nothing was changed. Unlock the affected assignment (with a reason) on the Approval screen, then run the simulation again."}

    def run(mode: int):
        # mode 0: only the affected jobs are free; followers keep their person and machine but may move in time
        # mode 1: affected jobs and followers are free; mode 2: everything unlocked is free
        unpin_unlocked = mode == 2
        pinned = {}
        for tid, a in base_asg.items():
            t = tmap.get(tid)
            if not t:
                continue
            done = t["status"] in ("In Progress", "Completed")
            if tid in movable and not (a["locked"] or done):
                if mode == 0 and tid not in affected:
                    pinned[tid] = {"employee_ids": a["employee_ids"], "work_center_id": a["work_center_id"], "start_slot": None, "locked": False}
                continue
            if unpin_unlocked and not (a["locked"] or done):
                continue
            pinned[tid] = {"employee_ids": a["employee_ids"], "work_center_id": a["work_center_id"], "start_slot": a["start_slot"], "locked": a["locked"]}
        c2 = Context(db)
        apply_event_overlay(c2, absent_days, down)
        only = None
        if typ == "delay":
            only = [dict(t, duration_min=t["duration_min"] + ev["minutes"]) if t["id"] == event["task_id"] else t for t in load_tasks(order_ids, db)]
        return solve(db, order_ids, c2.policy, pinned=pinned, ctx=c2, time_limit_sec=8, only_tasks=only, prev_assign={k: v for k, v in base_asg.items()})

    res = run(0)
    widened = False
    for nxt in (1, 2):
        if res["status"] == "INFEASIBLE" and not any(z.get("reason") == "nobody is eligible" for z in res.get("zero_eligibility", [])):
            res = run(nxt)
            widened = True
    if res["status"] not in ("OPTIMAL", "FEASIBLE"):
        diag = diagnose(db, order_ids, {}, absent_days)
        log_action(actor, role, "replan_failed", typ, after=explain, reason=res.get("message", ""), version_id=base_vid, db_path=db)
        return {"result": "no_plan", "event_text": explain, "status": res["status"], "message": res.get("message", ""),
                "zero_eligibility": res.get("zero_eligibility", []), "diagnosis": diag}
    vid = _save_version(db, res, f"Revised plan: {explain}", parent=base_vid, event=ev, actor=actor)
    # restore lock flags from base
    conn = get_conn(db)
    for tid, a in base_asg.items():
        if a["locked"]:
            conn.execute("UPDATE version_assignments SET locked=1 WHERE version_id=? AND task_id=?", (vid, tid))
    conn.commit()
    conn.close()
    d = diff_versions(db, base_vid, vid)
    for lst in (d["moved"], d["shifted"]):
        for m in lst:
            m["cause"] = "affected" if m["task_id"] in affected else ("follows" if m["task_id"] in movable and typ != "priority" else ("priority" if typ == "priority" else "capacity"))
    d["by_cause"] = {k: sum(1 for m in d["moved"] + d["shifted"] if m["cause"] == k) for k in ("affected", "follows", "priority", "capacity")}
    log_action(actor, role, "replan", vid, after={"event": ev, "moved": len(d["moved"]), "shifted": len(d["shifted"])}, reason=explain, version_id=vid, db_path=db)
    add_alert("schedule_change", "warning", f"{explain} A revised plan ({vid}) is waiting for approval.", link="live", db_path=db)
    return {"result": "proposed", "event_text": explain, "version_id": vid, "base_version_id": base_vid, "diff": d, "runtime": round(res["runtime"], 2),
            "widened": widened, "affected_tasks": sorted(affected),
            "detail": enrich(db, vid)}


def impossible_case(db, actor, role) -> dict:
    ctx = Context(db)
    certified = [eid for eid, e in ctx.emps.items() if e["role"] == "5-Axis Programmer/Engineer"]
    absent = {eid: list(range(ctx.policy["horizon_days"])) for eid in certified}
    orders = load_orders(db)
    order_ids = [o for o, r in orders.items() if r["status"] not in ("Completed", "Cancelled")]
    diag = diagnose(db, order_ids, {}, absent)
    log_action(actor, role, "simulate_impossible_case", "5-axis staff", after={"absent": certified}, reason="what-if only, nothing saved", db_path=db)
    add_alert("conflict", "critical", "Simulated case: no certified 5-axis person is available. No assignment was invented.", link="live", db_path=db)
    return {"result": "impossible", "event_text": "What-if: every certified 5-axis person (" + ", ".join(ctx.emps[e]["name"] for e in certified) + ") is absent all week. Nothing was saved.",
            "diagnosis": diag, "absent": certified}


# ---------- orders ----------
def create_order(db, actor, role, data: dict) -> dict:
    from core.notes import parse_notes
    conn = get_conn(db)
    prod = conn.execute("SELECT id FROM products WHERE id=?", (data.get("product_id"),)).fetchone()
    if not prod:
        conn.close()
        raise ApiError("Please choose a product.")
    try:
        qty = int(data.get("quantity"))
        assert 1 <= qty <= 1000
    except Exception:
        conn.close()
        raise ApiError("Quantity must be a whole number from 1 to 1000.")
    if data.get("priority") not in ("Urgent", "High", "Normal"):
        conn.close()
        raise ApiError("Please choose a priority.")
    try:
        due = datetime.strptime(data.get("due_date") or "", "%Y-%m-%d").date()
    except Exception:
        conn.close()
        raise ApiError("Please pick a due date. An order cannot be scheduled without one.")
    ctx = Context(db)
    if due < ctx.hs:
        conn.close()
        raise ApiError(f"The due date is before the plan starts ({ctx.hs:%a %d %b}). Pick a later date.")
    notes = (data.get("notes") or "").strip()
    parsed = parse_notes(notes) if notes else None
    reqs = {"skills": parsed["required_skills"], "certs": parsed["required_certifications"], "notes": parsed["special_notes"]} if parsed else {}
    oid = "ORD-" + uuid.uuid4().hex[:6].upper()
    conn.execute("INSERT INTO orders (id,product_id,quantity,priority,due_date,status,customer_commitment,notes,created_by,requirements) VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (oid, data["product_id"], qty, data["priority"], due.isoformat(), "Released", (data.get("customer_commitment") or "Demo customer")[:80], notes[:500], role, json.dumps(reqs)))
    conn.commit()
    conn.close()
    tasks = generate_tasks(oid, db)
    log_action(actor, role, "create_order", oid, after={"product": data["product_id"], "qty": qty, "due": due.isoformat(), "tasks": len(tasks)}, reason="new order", db_path=db)
    return {"order_id": oid, "task_count": len(tasks), "parsed_notes": parsed}


def delete_order(db, actor, role, oid):
    conn = get_conn(db)
    o = conn.execute("SELECT id FROM orders WHERE id=?", (oid,)).fetchone()
    if not o:
        conn.close()
        raise ApiError("Order not found.", 404)
    used = conn.execute("""SELECT COUNT(*) FROM version_assignments va JOIN tasks t ON t.id=va.task_id JOIN schedule_versions v ON v.id=va.version_id
                           WHERE t.order_id=? AND v.status='approved'""", (oid,)).fetchone()[0]
    if used:
        conn.close()
        raise ApiError("This order is in the approved schedule. Reject or replace the schedule first.", 409)
    conn.execute("DELETE FROM version_assignments WHERE task_id IN (SELECT id FROM tasks WHERE order_id=?)", (oid,))
    conn.execute("DELETE FROM tasks WHERE order_id=?", (oid,))
    conn.execute("DELETE FROM orders WHERE id=?", (oid,))
    conn.commit()
    conn.close()
    log_action(actor, role, "delete_order", oid, reason="removed by user", db_path=db)
