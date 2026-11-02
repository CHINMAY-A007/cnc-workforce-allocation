"""FastAPI backend for the CNC workforce allocation demo."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from core.config import DEFAULT_POLICY
from core.db import DB_PATH, get_conn, init_schema, is_seeded, reset_demo
from data.seed import seed
from core.tasks import generate_tasks, list_tasks, update_task_status
from core.policy import get_policy, set_policy
from core.eligibility import eligible_pairs, skill_matrix
from core.solver import solve, validate_schedule
from core.notes import parse_notes
from core.audit import log_action, recent
from core.alerts import add_alert, list_alerts, unread_count, mark_read
from core.reports import utilization_by_employee, approved_versions, planned_vs_actual, bottleneck_work_center
from core.replan import run_replan, locked_conflicts, snapshot_assignments
from core.requirements import list_requirements, set_status, verify_requirements
from core.models import Task
from core.config import resolve_horizon_start

ROOT = Path(__file__).parent
STATIC = ROOT / "static"
DB = DB_PATH

app = FastAPI(title="CNC Workforce Allocation Demo")


def _ensure_db():
    conn = get_conn(DB)
    init_schema(conn)
    if not is_seeded(conn):
        conn.close()
        seed(DB)
    else:
        conn.close()
    # Evidence-gated requirements coverage: mark each FR verified only when its
    # automated check passes. Runs on every startup so ticks stay current.
    try:
        verify_requirements(DB, route_paths=[r.path for r in app.routes])
    except Exception:
        # Never let requirements verification break the demo.
        pass


@app.on_event("startup")
def startup():
    _ensure_db()


def _role(request: Request) -> str:
    return request.headers.get("x-role", "Production Manager")

MANAGER_ROLES = {"Production Manager", "ERP Administrator"}
MANAGER_ENGINEER_ROLES = {"Production Manager", "Engineer/Supervisor", "ERP Administrator"}
HR_ROLES = {"Production Manager", "HR/Workforce Admin", "ERP Administrator"}

def _require_role(request: Request, allowed: set):
    r = _role(request)
    if r not in allowed:
        raise HTTPException(403, f"{r} not permitted for this action")


# ---------- static frontend ----------
@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


# ---------- orders ----------
@app.get("/api/orders")
def api_orders():
    conn = get_conn(DB)
    orders = [dict(r) for r in conn.execute("SELECT * FROM orders ORDER BY id").fetchall()]
    products = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM products").fetchall()}
    conn.close()
    for o in orders:
        o["product_name"] = products.get(o["product_id"], {}).get("name", o["product_id"])
    return orders


@app.post("/api/orders")
async def api_create_order(request: Request):
    data = await request.json()
    oid = "ORD-" + uuid.uuid4().hex[:6].upper()
    conn = get_conn(DB)
    conn.execute(
        "INSERT INTO orders (id,product_id,quantity,priority,due_date,status,customer_commitment,notes,created_by) VALUES (?,?,?,?,?,?,?,?,?)",
        (oid, data["product_id"], int(data["quantity"]), data["priority"], data["due_date"],
         "Released", data.get("customer_commitment", "Demo customer"), data.get("notes", ""), "demo"),
    )
    conn.commit()
    conn.close()
    parsed = None
    if (data.get("notes") or "").strip():
        parsed = parse_notes(data["notes"])
    generate_tasks(oid, DB)
    return {"order_id": oid, "parsed_notes": parsed}


@app.post("/api/orders/{oid}/tasks")
def api_gen_tasks(oid: str):
    generate_tasks(oid, DB)
    return {"ok": True}


@app.get("/api/tasks")
def api_tasks(order_id: str = None):
    tasks = list_tasks(order_id, DB)
    return [t.__dict__ for t in tasks]


@app.post("/api/tasks/{tid}/status")
async def api_task_status(tid: str, request: Request):
    data = await request.json()
    update_task_status(tid, data["status"], data.get("actual_start"), data.get("actual_end"), data.get("blocker"), DB)
    return {"ok": True}


# ---------- workforce ----------
@app.get("/api/workforce")
def api_workforce():
    conn = get_conn(DB)
    emps = [dict(r) for r in conn.execute("SELECT * FROM employees ORDER BY id").fetchall()]
    conn.close()
    return emps


@app.get("/api/skills")
def api_skills():
    emps, skills, matrix, cert_flags = skill_matrix(DB)
    return {"employees": [dict(e) for e in emps], "skills": skills, "matrix": matrix, "cert_flags": {k: v for k, v in cert_flags.items()}}


@app.get("/api/eligibility/{task_id}")
def api_eligibility(task_id: str):
    conn = get_conn(DB)
    trow = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    conn.close()
    if not trow:
        raise HTTPException(404, "task not found")
    task = Task(
        id=trow["id"], order_id=trow["order_id"], seq=trow["seq"], name=trow["name"],
        duration_min=trow["duration_min"], required_skill=trow["required_skill"],
        min_level=trow["min_level"], required_role=trow["required_role"],
        work_center_kind=trow["work_center_kind"], multi_person=trow["multi_person"],
        is_quality_gate=bool(trow["is_quality_gate"]), depends_on=json.loads(trow["depends_on"] or "[]"),
    )
    policy = get_policy(DB)
    er = eligible_pairs(task, policy, DB)
    return {"candidates": er.candidates, "excluded": er.excluded}


# ---------- products ----------
@app.get("/api/products")
def api_products():
    conn = get_conn(DB)
    prods = [dict(r) for r in conn.execute("SELECT * FROM products").fetchall()]
    conn.close()
    return prods


# ---------- parse notes ----------
@app.get("/api/parse-notes")
def api_parse_notes(text: str = ""):
    return parse_notes(text)


# ---------- solve ----------
@app.post("/api/solve")
async def api_solve(request: Request):
    _require_role(request, MANAGER_ENGINEER_ROLES)
    data = await request.json()
    policy = get_policy(DB)
    if data.get("weights"):
        policy["objective_weights"] = data["weights"]
    orders = data.get("orders", None)
    if orders is None:
        orders = [r["id"] for r in get_conn(DB).execute("SELECT id FROM orders").fetchall()]
    conn = get_conn(DB)
    conn.close()
    result = solve(DB, orders, policy, time_limit_sec=10.0)
    assignments = []
    for a in result["assignments"]:
        assignments.append({
            "task_id": a.task_id, "employee_ids": a.employee_ids,
            "work_center_id": a.work_center_id, "start_slot": a.start_slot,
            "end_slot": a.end_slot, "locked": a.locked, "why": a.why,
        })
    # create draft version if feasible
    new_vid = None
    if result["status"] in ("OPTIMAL", "FEASIBLE"):
        new_vid = "V-" + uuid.uuid4().hex[:8].upper()
        conn = get_conn(DB)
        conn.execute(
            "INSERT INTO schedule_versions (id,created_at,status,solver_status,solver_runtime_sec,objective_value,notes) VALUES (?,?,?,?,?,?,?)",
            (new_vid, datetime.now().isoformat(timespec="seconds"), "draft", result["status"], result["runtime"], result["objective"] or 0.0, "AI proposal"),
        )
        for a in result["assignments"]:
            conn.execute(
                "INSERT INTO version_assignments (version_id,task_id,employee_ids,work_center_id,start_slot,end_slot,locked,why) VALUES (?,?,?,?,?,?,?,?)",
                (new_vid, a.task_id, json.dumps(a.employee_ids), a.work_center_id, a.start_slot, a.end_slot, 1 if a.locked else 0, json.dumps(a.why)),
            )
        for a in result["assignments"]:
            conn.execute("UPDATE tasks SET planned_start=?, planned_end=?, employee_ids=?, work_center_id=?, locked=? WHERE id=?",
                         (a.start_slot, a.end_slot, json.dumps(a.employee_ids), a.work_center_id, 1 if a.locked else 0, a.task_id))
        conn.commit()
        conn.close()
        add_alert("schedule", "info", f"New AI proposal {new_vid} generated.")
        log_action(_role(request), _role(request), "generate_schedule", new_vid, before=None, after={"status": result["status"]}, reason="AI proposal", version_id=new_vid, db_path=DB)
    # validation
    violations = []
    if result["status"] in ("OPTIMAL", "FEASIBLE"):
        tasks = []
        for oid in orders:
            tasks += list_tasks(oid, DB)
        tdicts = [t.__dict__ for t in tasks]
        violations = validate_schedule(result["assignments"], tdicts, policy, DB)
    return {
        "status": result["status"], "runtime": result["runtime"],
        "objective": result["objective"], "assignments": assignments,
        "zero_eligibility": result.get("zero_eligibility", []),
        "violations": violations, "version_id": new_vid,
        "message": result.get("message", ""),
    }


# ---------- schedule ----------
@app.get("/api/schedules")
def api_schedules():
    conn = get_conn(DB)
    rows = [dict(r) for r in conn.execute("SELECT * FROM schedule_versions ORDER BY created_at DESC").fetchall()]
    conn.close()
    return rows


@app.get("/api/schedule/{vid}")
def api_schedule(vid: str):
    conn = get_conn(DB)
    assigns = [dict(r) for r in conn.execute("SELECT * FROM version_assignments WHERE version_id=?", (vid,)).fetchall()]
    conn.close()
    return assigns


# ---------- approval ----------
@app.post("/api/reassign")
async def api_reassign(request: Request):
    _require_role(request, MANAGER_ROLES)
    data = await request.json()
    vid = data["version_id"]; tid = data["task_id"]; new_emp = data["employee_id"]; reason = data.get("reason", "")
    if not reason.strip():
        raise HTTPException(400, "reason required")
    conn = get_conn(DB)
    a = conn.execute("SELECT employee_ids FROM version_assignments WHERE version_id=? AND task_id=?", (vid, tid)).fetchone()
    before = a["employee_ids"] if a else None
    conn.execute("UPDATE version_assignments SET employee_ids=? WHERE version_id=? AND task_id=?", (json.dumps([new_emp]), vid, tid))
    conn.execute("UPDATE tasks SET employee_ids=? WHERE id=?", (json.dumps([new_emp]), tid))
    conn.commit()
    conn.close()
    log_action(_role(request), _role(request), "reassign", tid, before=before, after=[new_emp], reason=reason, version_id=vid, db_path=DB)
    add_alert("reassignment", "warning", f"Task {tid} reassigned: {reason}")
    return {"ok": True}


@app.post("/api/lock")
async def api_lock(request: Request):
    _require_role(request, MANAGER_ROLES)
    data = await request.json()
    vid = data["version_id"]; tid = data["task_id"]
    conn = get_conn(DB)
    conn.execute("UPDATE version_assignments SET locked=1 WHERE version_id=? AND task_id=?", (vid, tid))
    conn.execute("UPDATE tasks SET locked=1 WHERE id=?", (tid,))
    conn.commit()
    conn.close()
    log_action(_role(request), _role(request), "lock", tid, before=False, after=True, reason=data.get("reason", "locked"), version_id=vid, db_path=DB)
    return {"ok": True}


@app.post("/api/unlock")
async def api_unlock(request: Request):
    _require_role(request, MANAGER_ROLES)
    data = await request.json()
    vid = data["version_id"]; tid = data["task_id"]
    conn = get_conn(DB)
    conn.execute("UPDATE version_assignments SET locked=0 WHERE version_id=? AND task_id=?", (vid, tid))
    conn.execute("UPDATE tasks SET locked=0 WHERE id=?", (tid,))
    conn.commit()
    conn.close()
    log_action(role, role, "unlock", tid, before=True, after=False, reason=data.get("reason", "unlocked"), version_id=vid, db_path=DB)
    return {"ok": True}


@app.post("/api/approve")
async def api_approve(request: Request):
    _require_role(request, MANAGER_ROLES)
    data = await request.json()
    vid = data["version_id"]
    role = _role(request)
    conn = get_conn(DB)
    conn.execute("UPDATE schedule_versions SET status='approved', approved_by=?, approved_at=? WHERE id=?",
                 (role, datetime.now().isoformat(timespec="seconds"), vid))
    conn.execute("UPDATE schedule_versions SET status='superseded' WHERE status='approved' AND id<>?", (vid,))
    conn.commit()
    conn.close()
    log_action(role, role, "approve_schedule", vid, before="draft", after="approved", reason="manager approval", version_id=vid, db_path=DB)
    add_alert("approval", "info", f"Schedule {vid} approved.")
    return {"ok": True}


@app.post("/api/reject")
async def api_reject(request: Request):
    _require_role(request, MANAGER_ROLES)
    data = await request.json()
    vid = data["version_id"]; reason = data.get("reason", "rejected")
    conn = get_conn(DB)
    conn.execute("UPDATE schedule_versions SET status='rejected', notes=? WHERE id=?", (reason, vid))
    conn.commit()
    conn.close()
    log_action(_role(request), _role(request), "reject_schedule", vid, before="draft", after="rejected", reason=reason, version_id=vid, db_path=DB)
    return {"ok": True}


# ---------- replan ----------
@app.post("/api/replan")
async def api_replan(request: Request):
    _require_role(request, MANAGER_ROLES)
    data = await request.json()
    event = data["event"]
    policy = get_policy(DB)
    # impossible case: deactivate 5-axis staff
    if event.get("type") == "impossible":
        conn = get_conn(DB)
        conn.execute("UPDATE employees SET active=0 WHERE id IN ('E07','E08')")
        conn.commit()
        conn.close()
        orders = [r["id"] for r in get_conn(DB).execute("SELECT id FROM orders").fetchall()]
        result = solve(DB, orders, policy, time_limit_sec=5.0)
        conn = get_conn(DB)
        conn.execute("UPDATE employees SET active=1 WHERE id IN ('E07','E08')")
        conn.commit()
        conn.close()
        return {"status": result["status"], "zero_eligibility": result.get("zero_eligibility", []),
                "message": "No assignment invented. Options: extend due date, overtime within caps, reschedule maintenance."}
    conn = get_conn(DB)
    versions = [r["id"] for r in conn.execute("SELECT id FROM schedule_versions ORDER BY created_at DESC").fetchall()]
    conn.close()
    current_vid = versions[0] if versions else None
    if not current_vid:
        raise HTTPException(400, "no schedule")
    # locked conflicts
    from core.replan import locked_conflicts
    cf = locked_conflicts(current_vid, event, DB)
    if cf:
        return {"conflicts": cf, "requires_unlock": True}
    res = run_replan(current_vid, event, policy, DB, actor=_role(request), role=_role(request))
    return res


# ---------- reports ----------
@app.get("/api/reports/utilization")
def api_util():
    return utilization_by_employee(DB)


@app.get("/api/reports/bottleneck")
def api_bn():
    bn = bottleneck_work_center(db_path=DB)
    return {"work_center": bn[0] if bn else None, "hours": bn[1] if bn else 0}


@app.get("/api/reports/planned-vs-actual")
def api_pva():
    return planned_vs_actual(DB)


@app.get("/api/audit")
def api_audit():
    return recent(50, DB)


@app.get("/api/alerts")
def api_alerts():
    return {"count": unread_count(DB), "items": list_alerts(DB)}


@app.post("/api/alerts/{aid}/read")
def api_alert_read(aid: int):
    mark_read(aid, DB)
    return {"ok": True}


@app.get("/api/requirements")
def api_reqs():
    return list_requirements(DB)


@app.post("/api/requirements/{fr_id}/status")
async def api_req_status(fr_id: str, request: Request):
    """Save/override the evidence status for a single FR (e.g. from a 'Show me' review)."""
    data = await request.json()
    status = str(data.get("status", "verified")).strip() or "verified"
    evidence = str(data.get("evidence", ""))
    set_status(fr_id, status, evidence, DB)
    log_action(_role(request), _role(request), "requirement_status", fr_id,
               before=None, after={"status": status, "evidence": evidence}, reason="evidence update", db_path=DB)
    return {"ok": True, "fr_id": fr_id, "status": status, "evidence": evidence}


@app.post("/api/requirements/verify")
def api_req_verify(request: Request):
    """Re-run every automated FR check and persist evidence-gated statuses."""
    results = verify_requirements(DB, route_paths=[r.path for r in app.routes])
    log_action(_role(request), _role(request), "requirements_verify", "all",
               before=None, after={k: v["status"] for k, v in results.items()}, reason="re-verified all FRs", db_path=DB)
    return {"ok": True, "results": results}


@app.get("/api/policy")
def api_policy_get():
    return get_policy(DB)


@app.post("/api/policy")
async def api_policy_set(request: Request):
    _require_role(request, HR_ROLES)
    data = await request.json()
    set_policy(data, DB)
    log_action(_role(request), _role(request), "policy_update", "policy", before=None, after=data, reason="settings", db_path=DB)
    return {"ok": True}


@app.post("/api/reset")
def api_reset():
    reset_demo(DB)
    seed(DB)
    return {"ok": True}


# ---------- gantt helper: slot->iso ----------
@app.get("/api/meta")
def api_meta():
    policy = get_policy(DB)
    hs = resolve_horizon_start(policy)
    return {"horizon_start": hs.isoformat(), "slot_minutes": 15}