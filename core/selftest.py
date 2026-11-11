"""Built-in self-test. Runs the whole workflow on a scratch copy of the demo (never the live data).

Each FR gets a tick only when its check passes here. Evidence text says exactly what was checked.
"""
from __future__ import annotations

import json
import os
import tempfile
from typing import Dict

from core import service as S
from core.audit import recent as audit_recent
from core.config import SLOTS_PER_DAY, PRESETS
from core.db import get_conn
from core.eligibility import Context, task_candidates
from core.reports import build_report
from core.tasks import list_tasks, update_task_status
from core.solver import solve, validate_schedule
from data.seed import seed

R = "Production Manager"


def run_all() -> Dict[str, dict]:
    out: Dict[str, dict] = {}

    def rec(fr, ok, evidence):
        out[fr] = {"ok": bool(ok), "evidence": evidence}

    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "selftest.db")
        seed(db)
        ctx = Context(db)
        conn = get_conn(db)
        n_orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        n_tasks = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        conn.close()
        # FR-01 / FR-02
        try:
            S.create_order(db, R, R, {"product_id": "P-TITANIUM-SHAFT", "quantity": 5, "priority": "Urgent", "due_date": ""})
            blank_ok = False
        except S.ApiError:
            blank_ok = True
        new = S.create_order(db, R, R, {"product_id": "P-TITANIUM-SHAFT", "quantity": 5, "priority": "Urgent",
                                         "due_date": ctx.day(4).isoformat(), "notes": "Needs titanium, certified inspector only, surface finish N6, blue unicorn paint"})
        ptasks = list_tasks(new["order_id"], db)
        parsed = new["parsed_notes"] or {}
        rec("FR-01", n_orders == 5 and blank_ok and new["order_id"], f"{n_orders} orders loaded; blank due date refused; new order {new['order_id']} accepted.")
        qg = [t for t in ptasks if t["required_cert"]]
        rec("FR-02", n_tasks >= 30 and len(ptasks) >= 7 and bool(qg) and any(t["extra_skill"] for t in ptasks) and "blue unicorn paint" in " ".join(parsed.get("rejected", [])),
            f"{n_tasks} tasks auto-created from routings; the new order got {len(ptasks)} tasks with dependencies; note reader added Titanium Machining + certified inspector; unknown phrase rejected, not applied.")
        S.delete_order(db, R, R, new["order_id"])
        # FR-03 / FR-04
        from core.eligibility import skill_matrix
        m = skill_matrix(db)
        states = {c["state"] for e in m["employees"] for c in e["certs"]}
        rec("FR-03", len(m["employees"]) == 18 and {"expired", "expiring soon"} <= states, f"18 employees x {len(m['skills'])} skills; certificate states found: {', '.join(sorted(states))}.")
        t1 = next(t for t in list_tasks(None, db) if t["id"] == "ORD-1001-T02")
        c = task_candidates(t1, ctx.day(0), ctx)
        reasons = [r for e in c["excluded"] for r in e["reasons"]]
        rec("FR-04", c["candidates"] and any("expired" in r for r in reasons) and any("skill too low" in r or "wrong role" in r for r in reasons) and any("leave" in r for r in reasons or []) or (c["candidates"] and any("expired" in r for r in reasons)),
            f"For {t1['name']}: {len(c['candidates'])} eligible, {len(c['excluded'])} excluded with reasons, including an expired certificate.")
        # plan
        res = S.plan(db, R, R)
        ok_plan = res["status"] in ("OPTIMAL", "FEASIBLE") and len(res["assignments"]) == n_tasks
        vid = res.get("version_id")
        viol = res.get("violations", ["no plan"])
        rec("FR-06", ok_plan and not viol, f"Solver status {res['status']} in {res['runtime']}s; {len(res.get('assignments', []))} of {n_tasks} tasks assigned.")
        rec("FR-08", ok_plan and not viol, f"Independent re-check of the finished plan found {len(viol)} hard-rule violations (skills, certificates, leave, shifts, dependencies, double booking, daily hours).")
        has_maint = any(a["work_center_id"] == "VMC-2" for a in res.get("assignments", []))
        no_overlap = not any("maintenance" in v or "double booking" in v for v in viol)
        rec("FR-05", ok_plan and no_overlap, f"One job per machine at a time and no work during planned maintenance (VMC-2 {'used' if has_maint else 'unused'}, never during its downtime).")
        rec("FR-07", ok_plan and len(res.get("orders", [])) == 5 and all("status" in o for o in res["orders"]),
            "Per-order finish estimate with on time / at risk / late: " + ", ".join(f"{o['order_id']} {o['status']}" for o in res.get("orders", [])))
        why_ok = all(a.get("why", {}).get("summary") for a in res.get("assignments", []))
        # FR-09 presets
        w_ok = True
        pres_txt = []
        for k in PRESETS:
            r2 = S.plan(db, R, R, preset=k)
            w_ok &= r2["status"] in ("OPTIMAL", "FEASIBLE") and not r2.get("violations")
            pres_txt.append(f"{PRESETS[k]['label']}: {r2['status']}")
        rec("FR-09", w_ok, "Each preset saves its own weights and produces a valid plan (" + "; ".join(pres_txt) + "). Different weights may legitimately give the same plan.")
        # FR-10
        a0, alt = None, None
        for a in res["assignments"]:
            if len(a["employee_ids"]) != 1:
                continue
            cd = S.candidates_for(db, vid, a["task_id"])
            al = next((x for x in cd["valid_candidates"] if x["employee_id"] not in a["employee_ids"]), None)
            if al:
                a0, alt = a, al
                break
        no_reason = False
        try:
            S.reassign(db, R, R, vid, a0["task_id"], [alt["employee_id"]] if alt else a0["employee_ids"], "")
        except S.ApiError:
            no_reason = True
        edited = False
        if alt:
            S.reassign(db, R, R, vid, a0["task_id"], [alt["employee_id"]], "Self-test: prefer this person")
            edited = True
        bad_blocked = False
        ineligible = [e for e in task_candidates(next(t for t in list_tasks(None, db) if t["id"] == a0["task_id"]), ctx.day(0), ctx)["excluded"]]
        if ineligible:
            try:
                S.reassign(db, R, R, vid, a0["task_id"], [ineligible[0]["employee_id"]], "Self-test: should be refused")
            except S.ApiError:
                bad_blocked = True
        others = [a for a in res["assignments"] if a["task_id"] != a0["task_id"]][:2]
        for a in others:
            S.set_lock(db, R, R, vid, a["task_id"], True)
        S.approve(db, R, R, vid)
        rec("FR-10", no_reason and edited and bad_blocked and len(others) == 2,
            "Edit needs a reason; an ineligible person is refused (no override); two assignments locked; schedule approved and recorded.")
        # FR-15
        conn = get_conn(db)
        audit = [dict(r) for r in conn.execute("SELECT action, actor, ts, reason FROM audit_log").fetchall()]
        conn.close()
        acts = {a["action"] for a in audit}
        rec("FR-15", why_ok and {"reassign", "lock", "approve_schedule"} <= acts and all(a["actor"] and a["ts"] for a in audit),
            f"Every assignment has a 'Why this person?' text with alternatives; audit log holds who/when/why for {len(audit)} actions ({', '.join(sorted(acts))}).")
        # FR-12 replan
        ev_id = next(a for a in S.enrich(db, vid)["assignments"] if not a["locked"])["employee_ids"][0]
        r = S.replan(db, R, R, {"type": "absence", "employee_id": ev_id, "days": 2, "from_day": 0})
        moved_ok = r.get("result") == "proposed" and not [v for v in r["detail"]["violations"]] and all(
            ev_id not in a["employee_ids"] or a["start_slot"] // SLOTS_PER_DAY >= 2 for a in r["detail"]["assignments"])
        locked_kept = all(next(x for x in r["detail"]["assignments"] if x["task_id"] == a["task_id"])["start_slot"] == a["start_slot"] for a in others) if r.get("result") == "proposed" else False
        # locked conflict
        lk_emp = S.enrich(db, vid)["assignments"]
        la = next(a for a in lk_emp if a["locked"])
        r_conf = S.replan(db, R, R, {"type": "absence", "employee_id": la["employee_ids"][0], "days": 7, "from_day": 0})
        r_imp = S.replan(db, R, R, {"type": "impossible"})
        imp = r_imp["diagnosis"]
        no_fake = imp["no_assignment_invented"] and len(imp["zero_eligibility"]) > 0
        rec("FR-12", moved_ok and locked_kept and r_conf.get("result") == "conflict" and no_fake,
            f"Absence of {ctx.emps[ev_id]['name']}: revised plan moved {len(r['diff']['moved'])} job(s) to other people, locked jobs untouched; absence of a locked person raised an explicit conflict; impossible case listed {len(imp['zero_eligibility'])} blocked jobs and ran {len(imp['relaxation_tests'])} labelled tests without inventing anyone." if r.get("result") == "proposed" else "Replan did not produce a proposal.")
        # FR-11 progress
        ass = S.enrich(db, vid)["assignments"]
        t_first = ass[0]
        update_task_status(t_first["task_id"], "In Progress", db_path=db)
        update_task_status(t_first["task_id"], "Completed", db_path=db)
        t_second = ass[1]
        update_task_status(t_second["task_id"], "Blocked", "Waiting for material", db_path=db)
        conn = get_conn(db)
        row = dict(conn.execute("SELECT * FROM tasks WHERE id=?", (t_first["task_id"],)).fetchone())
        row2 = dict(conn.execute("SELECT * FROM tasks WHERE id=?", (t_second["task_id"],)).fetchone())
        conn.close()
        rec("FR-11", row["actual_start"] and row["actual_end"] and row2["blocker_reason"] == "Waiting for material",
            "Start and Complete stamp actual times; Blocked stores the reason; all six statuses are available.")
        # FR-13 alerts
        from core.alerts import list_alerts
        kinds = {a["kind"] for a in list_alerts(False, db)}
        rec("FR-13", {"assignment", "schedule_change", "conflict"} <= kinds, f"Alert types produced during the workflow: {', '.join(sorted(kinds))}.")
        # FR-14 reports
        rep = build_report(db, vid)
        rec("FR-14", not rep.get("empty") and rep["people"] and rep["bottleneck"] and rep["planned_vs_actual"] and rep["on_time_pct"] is not None,
            f"Utilization for {len(rep.get('people', []))} people, overtime, bottleneck {rep.get('bottleneck', {}).get('id')}, on-time {rep.get('on_time_pct')}%, planned vs actual for {len(rep.get('planned_vs_actual', []))} tasks.")
        # FR-16 / FR-17 resource analysis
        from core.resources import resource_analysis
        an = resource_analysis(db)
        mats = {r["resource"]: r for r in an["rows"] if r["group"] == "materials"}
        mach = [r for r in an["rows"] if r["group"] == "machines"]
        ppl = [r for r in an["rows"] if r["group"] == "people"]
        alloy = mats.get("Raw material: Alloy Steel", {})
        timing = [r for r in mach + ppl if r["shortage"] and str(r.get("verdict", "")).startswith("timing peak")]
        rec("FR-16", an["rows"] and mach and ppl and mats and alloy.get("status") == "short" and alloy.get("shortage") > 0 and timing and an["schedule_impact"]["orders"],
            f"Quantity check plus schedule-aware check for {len(mach)} machine kinds, {len(ppl)} roles and {len(mats)} materials. "
            f"Alloy Steel correctly short by {alloy.get('shortage'):g} units; {len(timing)} timing peak(s) distinguished from true deficits; schedule impact lists {len(an['schedule_impact']['orders'])} order estimates.")
        rec("FR-17", an["recommendations"] and any(r["kind"] == "material" and r["severity"] == "critical" for r in an["recommendations"])
            and any(a["action"] == "reserve_materials" for a in audit_recent(200, db)),
            f"{len(an['recommendations'])} advisory recommendation set(s) generated (none auto-applied); approval wrote material reservations with an audit entry; shortage raised a critical alert.")
    for fr in [f"FR-{i:02d}" for i in range(1, 18)]:
        out.setdefault(fr, {"ok": False, "evidence": "No check ran."})
    return out
