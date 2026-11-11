"""FastAPI backend for the CNC workforce allocation demo (Simulated ERP, demo data only)."""
from __future__ import annotations

import json
import os
import shutil
import threading
import traceback
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from core import service as S
from core.alerts import list_alerts, mark_all_read, mark_read, unread_count
from core.audit import log_action, recent
from core.config import (PRESETS, STATUSES, WEIGHT_LABELS, fmt_slot, get_policy, now_local, planning_start, resolve_horizon_start,
                         set_policy, today_local, TZ_NAME)
from core.db import DB_PATH, get_conn, init_schema, is_seeded, reset_demo
from core.eligibility import Context, skill_matrix, task_candidates
from core.notes import note_reader_mode, parse_notes
from core.reports import build_report
from core.resources import resource_analysis, material_requirement
from core.requirements import FR_TITLES
from core.tasks import get_task, list_tasks, update_task_status
from data.seed import seed

ROOT = Path(__file__).parent
STATIC = ROOT / "static"
DB = DB_PATH

app = FastAPI(title="CNC Workforce Allocation Demo", docs_url=None, redoc_url=None)

ROLES = ["Production Manager", "Engineer/Supervisor", "Worker", "HR/Workforce Admin", "ERP Administrator"]
PERMS = {
    "plan": {"Production Manager", "Engineer/Supervisor"},
    "decide": {"Production Manager"},                       # approve, reject, edit, lock, replan
    "orders": {"Production Manager", "ERP Administrator"},
    "workforce": {"HR/Workforce Admin", "Production Manager"},
    "policy": {"ERP Administrator", "Production Manager"},
    "progress": {"Production Manager", "Engineer/Supervisor", "Worker"},
    "reset": {"Production Manager", "ERP Administrator"},
}
_selftest = {"state": "idle", "started": None, "results": None, "error": None}
_lock = threading.Lock()


def _ensure_db():
    conn = get_conn(DB)
    init_schema(conn)
    ok = is_seeded(conn)
    conn.close()
    if not ok:
        seed(DB)


@app.on_event("startup")
def startup():
    _ensure_db()


def role_of(request: Request) -> str:
    r = request.headers.get("x-role", "Production Manager")
    return r if r in ROLES else "Production Manager"


def need(request: Request, perm: str) -> str:
    r = role_of(request)
    if r not in PERMS[perm]:
        raise S.ApiError(f"The {r} role cannot do this in the demo. Switch role (top right) to {' or '.join(sorted(PERMS[perm]))}.", 403)
    return r


async def body(request: Request) -> dict:
    try:
        d = await request.json()
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


@app.exception_handler(S.ApiError)
async def api_error(_r, e: S.ApiError):
    return JSONResponse({"error": e.message, **e.extra}, status_code=e.status)


@app.exception_handler(Exception)
async def any_error(_r, e: Exception):
    traceback.print_exc()
    return JSONResponse({"error": "Something went wrong on the server. Nothing was changed. Try again; if it repeats, use Reset demo data on the Home screen.",
                         "detail": f"{type(e).__name__}"}, status_code=500)


app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


# ---------- overview ----------
@app.get("/api/state")
def api_state(request: Request):
    pol = get_policy(DB)
    hs = resolve_horizon_start(pol)
    conn = get_conn(DB)
    n_orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    n_tasks = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    drafts = conn.execute("SELECT COUNT(*) FROM schedule_versions WHERE status='draft'").fetchone()[0]
    appr = conn.execute("SELECT id, approved_at FROM schedule_versions WHERE status='approved' ORDER BY approved_at DESC LIMIT 1").fetchone()
    n_rev = conn.execute("SELECT COUNT(*) FROM schedule_versions WHERE parent_version_id IS NOT NULL").fetchone()[0]
    prog = conn.execute("SELECT COUNT(*) FROM tasks WHERE status IN ('In Progress','Completed')").fetchone()[0]
    conn.close()
    return {"company": pol["company"], "orders": n_orders, "tasks": n_tasks, "drafts": drafts,
            "approved_version": appr["id"] if appr else None, "revisions": n_rev, "progress_updates": prog,
            "latest_version": S.latest_version_id(DB), "unread_alerts": unread_count(DB),
            "horizon_start": hs.isoformat(), "horizon_text": hs.strftime("%a %d %b %Y"), "horizon_days": pol["horizon_days"],
            "today": today_local().isoformat(), "timezone": TZ_NAME, "dates_stale": hs < today_local(),
            "note_reader": note_reader_mode(), "roles": ROLES, "role": role_of(request),
            "presets": {k: {"label": v["label"], "weights": v["weights"]} for k, v in PRESETS.items()},
            "weight_labels": WEIGHT_LABELS, "statuses": STATUSES, "weights": pol["objective_weights"]}


# ---------- orders & tasks ----------
@app.get("/api/orders")
def api_orders():
    conn = get_conn(DB)
    orders = [dict(r) for r in conn.execute("SELECT * FROM orders ORDER BY created_by='demo' DESC, id").fetchall()]
    prods = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM products").fetchall()}
    counts = {r["order_id"]: r["n"] for r in conn.execute("SELECT order_id, COUNT(*) n FROM tasks GROUP BY order_id").fetchall()}
    conn.close()
    for o in orders:
        o["product_name"] = prods.get(o["product_id"], {}).get("name", o["product_id"])
        o["task_count"] = counts.get(o["id"], 0)
        try:
            o["requirements"] = json.loads(o["requirements"] or "{}")
        except Exception:
            o["requirements"] = {}
    return orders


@app.post("/api/orders")
async def api_create_order(request: Request):
    role = need(request, "orders")
    return S.create_order(DB, role, role, await body(request))


@app.delete("/api/orders/{oid}")
def api_delete_order(oid: str, request: Request):
    role = need(request, "orders")
    S.delete_order(DB, role, role, oid)
    return {"ok": True}


@app.get("/api/products")
def api_products():
    conn = get_conn(DB)
    out = []
    for p in conn.execute("SELECT * FROM products").fetchall():
        ops = [dict(r) for r in conn.execute("SELECT seq, operation, work_center_kind, duration_min, required_skill, min_level, is_quality_gate, depends_on FROM routing_ops WHERE product_id=? ORDER BY seq", (p["id"],)).fetchall()]
        out.append({**dict(p), "routing": ops})
    conn.close()
    return out


@app.get("/api/tasks")
def api_tasks(order_id: str = None):
    ctx = Context(DB)
    out = []
    for t in list_tasks(order_id, DB):
        t["planned_start_text"] = fmt_slot(t["planned_start"], ctx.hs) if t["planned_start"] is not None else None
        t["planned_end_text"] = fmt_slot(t["planned_end"], ctx.hs) if t["planned_end"] is not None else None
        t["employees"] = [ctx.emps[e]["name"] for e in t["employee_ids"] if e in ctx.emps]
        out.append(t)
    return out


@app.get("/api/tasks/worker/{emp_id}")
def api_worker_tasks(emp_id: str):
    ctx = Context(DB)
    if emp_id not in ctx.emps:
        raise S.ApiError("Unknown employee.", 404)
    vid = S.latest_version_id(DB, "approved")
    items = []
    if vid:
        det = S.enrich(DB, vid)
        for a in det["assignments"]:
            if emp_id in a["employee_ids"]:
                conn = get_conn(DB)
                t = dict(conn.execute("SELECT * FROM tasks WHERE id=?", (a["task_id"],)).fetchone())
                conn.close()
                items.append({"task_id": a["task_id"], "task_name": a["task_name"], "order_id": a["order_id"], "start_text": a["start_text"],
                              "end_text": a["end_text"], "work_center": a["work_center_name"], "with": [e["name"] for e in a["employees"] if e["id"] != emp_id],
                              "status": t["status"], "actual_start": t["actual_start"], "actual_end": t["actual_end"], "blocker": t["blocker_reason"],
                              "locked": a["locked"], "priority": a["priority"], "start_slot": a["start_slot"]})
    return {"employee": {"id": emp_id, "name": ctx.emps[emp_id]["name"], "shift": ctx.emps[emp_id]["shift"], "role": ctx.emps[emp_id]["role"]},
            "approved_version": vid, "tasks": items}


@app.post("/api/tasks/{tid}/status")
async def api_task_status(tid: str, request: Request):
    role = need(request, "progress")
    d = await body(request)
    status = d.get("status")
    if status not in STATUSES:
        raise S.ApiError("Unknown status.")
    if status == "Blocked" and not (d.get("blocker") or "").strip():
        raise S.ApiError("Please say what is blocking the job.")
    t = get_task(tid, DB)
    if not t:
        raise S.ApiError("Task not found.", 404)
    before = t["status"]
    update_task_status(tid, status, (d.get("blocker") or "").strip() or None, DB)
    log_action(d.get("actor") or role, role, "task_status", tid, before=before, after=status, reason=(d.get("blocker") or "").strip() or "progress update", db_path=DB)
    if status == "Blocked":
        from core.alerts import add_alert
        add_alert("blocked", "warning", f"{t['name']} ({t['order_id']}) is blocked: {(d.get('blocker') or '').strip()}", link="live", db_path=DB)
    return {"ok": True}


# ---------- workforce ----------
@app.get("/api/workforce")
def api_workforce():
    return skill_matrix(DB)


@app.post("/api/employees/{eid}")
async def api_employee_update(eid: str, request: Request):
    role = need(request, "workforce")
    d = await body(request)
    conn = get_conn(DB)
    e = conn.execute("SELECT * FROM employees WHERE id=?", (eid,)).fetchone()
    if not e:
        conn.close()
        raise S.ApiError("Unknown employee.", 404)
    changes = {}
    if "active" in d:
        conn.execute("UPDATE employees SET active=? WHERE id=?", (1 if d["active"] else 0, eid))
        changes["active"] = bool(d["active"])
    if "leave_dates" in d:
        ld = sorted({x for x in d["leave_dates"] if datetime.strptime(x, "%Y-%m-%d")})
        conn.execute("UPDATE employees SET leave_dates=? WHERE id=?", (json.dumps(ld), eid))
        changes["leave_dates"] = ld
    if "skill" in d and "level" in d:
        lvl = int(d["level"])
        if not 0 <= lvl <= 5:
            conn.close()
            raise S.ApiError("Skill level must be 0 to 5.")
        if lvl == 0:
            conn.execute("DELETE FROM skills WHERE employee_id=? AND skill=?", (eid, d["skill"]))
        else:
            conn.execute("INSERT OR REPLACE INTO skills (employee_id,skill,level) VALUES (?,?,?)", (eid, d["skill"], lvl))
        changes["skill"] = {d["skill"]: lvl}
    conn.commit()
    conn.close()
    log_action(role, role, "workforce_update", eid, before=None, after=changes, reason=d.get("reason") or "HR update", db_path=DB)
    return {"ok": True}


@app.get("/api/eligibility/{task_id}")
def api_eligibility(task_id: str, day: int = None):
    t = get_task(task_id, DB)
    if not t:
        raise S.ApiError("Task not found.", 404)
    ctx = Context(DB)
    if day is None:
        day = (t["planned_start"] // 96) if t.get("planned_start") is not None else 0
    c = task_candidates(t, ctx.day(day), ctx)
    return {"task": {"id": t["id"], "name": t["name"], "order_id": t["order_id"], "required_skill": t["required_skill"], "min_level": t["min_level"],
                     "required_role": t["required_role"], "extra_skill": t.get("extra_skill"), "required_cert": t.get("required_cert")},
            "day_text": ctx.day(day).strftime("%a %d %b"), **c}


@app.get("/api/parse-notes")
def api_parse_notes(text: str = ""):
    return parse_notes(text[:500])


# ---------- resource analysis (AI Resource Analysis & Recommendations) ----------
@app.get("/api/analysis")
def api_analysis(order_id: str = None):
    ids = [order_id] if order_id else None
    if order_id:
        conn = get_conn(DB)
        ok = conn.execute("SELECT 1 FROM orders WHERE id=?", (order_id,)).fetchone()
        conn.close()
        if not ok:
            raise S.ApiError("Unknown order.", 404)
    return resource_analysis(DB, ids)


@app.get("/api/analysis/explanation")
def api_analysis_explanation(order_id: str = None):
    """Plain-language explanation of the validated analysis (Gemini when enabled, rules otherwise).
    A separate endpoint so viewing the dashboard never burns an AI call; the manager asks for it."""
    ids = [order_id] if order_id else None
    if order_id:
        conn = get_conn(DB)
        ok = conn.execute("SELECT 1 FROM orders WHERE id=?", (order_id,)).fetchone()
        conn.close()
        if not ok:
            raise S.ApiError("Unknown order.", 404)
    from core.ai_explain import explain_analysis
    return explain_analysis(resource_analysis(DB, ids))


@app.get("/api/materials")
def api_materials():
    conn = get_conn(DB)
    rows = [dict(r) for r in conn.execute("SELECT * FROM materials ORDER BY id").fetchall()]
    conn.close()
    from core.resources import approved_reserved_materials
    reserved = approved_reserved_materials(DB)
    for r in rows:
        r["reserved"] = float(reserved.get(r["id"], 0.0))
        r["available"] = r["on_hand"] - r["reserved"]
    return rows


@app.post("/api/materials/{mid}")
async def api_material_update(mid: str, request: Request):
    role = need(request, "policy")
    d = await body(request)
    conn = get_conn(DB)
    m = conn.execute("SELECT * FROM materials WHERE id=?", (mid,)).fetchone()
    if not m:
        conn.close()
        raise S.ApiError("Unknown material.", 404)
    try:
        qty = float(d.get("on_hand"))
        assert 0 <= qty <= 100000
    except Exception:
        conn.close()
        raise S.ApiError("Stock on hand must be a number from 0 to 100000.")
    conn.execute("UPDATE materials SET on_hand=? WHERE id=?", (qty, mid))
    conn.commit()
    conn.close()
    log_action(role, role, "material_stock_update", mid, before=m["on_hand"], after=qty, reason=d.get("reason") or "ERP stock update", db_path=DB)
    return {"ok": True}


# ---------- planning ----------
@app.post("/api/plan")
async def api_plan(request: Request):
    role = need(request, "plan")
    d = await body(request)
    w = d.get("weights")
    if w:
        w = {k: float(v) for k, v in w.items() if k in WEIGHT_LABELS}
    return S.plan(DB, role, role, order_ids=d.get("orders"), weights=w, preset=d.get("preset"))


@app.get("/api/versions")
def api_versions():
    conn = get_conn(DB)
    rows = [dict(r) for r in conn.execute("SELECT id, created_at, status, solver_status, label, approved_by, approved_at, parent_version_id FROM schedule_versions ORDER BY created_at DESC, rowid DESC").fetchall()]
    conn.close()
    return rows


@app.get("/api/version/{vid}")
def api_version(vid: str):
    return S.enrich(DB, vid)


@app.get("/api/version/{vid}/candidates/{task_id}")
def api_candidates(vid: str, task_id: str):
    return S.candidates_for(DB, vid, task_id)


@app.post("/api/reassign")
async def api_reassign(request: Request):
    role = need(request, "decide")
    d = await body(request)
    S.reassign(DB, role, role, d.get("version_id"), d.get("task_id"), d.get("employee_ids") or [], d.get("reason", ""))
    return S.enrich(DB, d["version_id"])


@app.post("/api/lock")
async def api_lock(request: Request):
    role = need(request, "decide")
    d = await body(request)
    S.set_lock(DB, role, role, d.get("version_id"), d.get("task_id"), True, d.get("reason", ""))
    return {"ok": True}


@app.post("/api/unlock")
async def api_unlock(request: Request):
    role = need(request, "decide")
    d = await body(request)
    S.set_lock(DB, role, role, d.get("version_id"), d.get("task_id"), False, d.get("reason", ""))
    return {"ok": True}


@app.post("/api/approve")
async def api_approve(request: Request):
    role = need(request, "decide")
    d = await body(request)
    S.approve(DB, role, role, d.get("version_id"))
    return {"ok": True, "version_id": d.get("version_id")}


@app.post("/api/reject")
async def api_reject(request: Request):
    role = need(request, "decide")
    d = await body(request)
    S.reject(DB, role, role, d.get("version_id"), d.get("reason", ""))
    return {"ok": True}


@app.post("/api/replan")
async def api_replan(request: Request):
    role = need(request, "decide")
    d = await body(request)
    return S.replan(DB, role, role, d.get("event") or {})


# ---------- reports, audit, alerts ----------
@app.get("/api/reports")
def api_reports():
    return build_report(DB)


@app.get("/api/audit")
def api_audit():
    return recent(200, DB)


@app.get("/api/alerts")
def api_alerts():
    return {"count": unread_count(DB), "items": list_alerts(False, DB)}


@app.post("/api/alerts/{aid}/read")
def api_alert_read(aid: int):
    mark_read(aid, DB)
    return {"ok": True}


@app.post("/api/alerts/read-all")
def api_alert_read_all():
    mark_all_read(DB)
    return {"ok": True}


# ---------- requirements ----------
@app.get("/api/requirements")
def api_reqs():
    conn = get_conn(DB)
    rows = [dict(r) for r in conn.execute("SELECT * FROM requirements_evidence ORDER BY fr_id").fetchall()]
    conn.close()
    return {"items": rows, "selftest": {k: _selftest[k] for k in ("state", "started", "error")}}


def _run_selftest():
    from core.selftest import run_all
    try:
        res = run_all()
        conn = get_conn(DB)
        for fr, r in res.items():
            conn.execute("UPDATE requirements_evidence SET status=?, evidence=? WHERE fr_id=?",
                         ("verified" if r["ok"] else "check failed", r["evidence"], fr))
        conn.commit()
        conn.close()
        _selftest.update(state="done", results=res, error=None)
    except Exception as e:  # never break the demo
        traceback.print_exc()
        _selftest.update(state="error", error=f"{type(e).__name__}: {e}")


@app.post("/api/requirements/verify")
def api_req_verify(request: Request):
    with _lock:
        if _selftest["state"] == "running":
            return {"state": "running"}
        _selftest.update(state="running", started=now_local().isoformat(timespec="seconds"), error=None)
    threading.Thread(target=_run_selftest, daemon=True).start()
    return {"state": "running"}


# ---------- settings ----------
@app.get("/api/policy")
def api_policy_get():
    return get_policy(DB)


@app.post("/api/policy")
async def api_policy_set(request: Request):
    role = need(request, "policy")
    d = await body(request)
    cur = get_policy(DB)
    new = {}
    if "objective_weights" in d:
        w = d["objective_weights"]
        new["objective_weights"] = {k: max(0.0, float(w[k])) for k in WEIGHT_LABELS if k in w}
    if "overtime_cap_hours" in d:
        v = float(d["overtime_cap_hours"])
        if not 0 <= v <= 4:
            raise S.ApiError("Overtime cap must be between 0 and 4 hours.")
        new["overtime_cap_hours"] = v
    if "working_weekdays" in d:
        wd = sorted({int(x) for x in d["working_weekdays"] if 0 <= int(x) <= 6})
        if not wd:
            raise S.ApiError("Pick at least one working day.")
        new["working_weekdays"] = wd
    if "shifts" in d:
        for k, v in d["shifts"].items():
            datetime.strptime(v["start"], "%H:%M"); datetime.strptime(v["end"], "%H:%M")
        new["shifts"] = d["shifts"]
    if not new:
        raise S.ApiError("Nothing to change.")
    set_policy(new, DB)
    log_action(role, role, "policy_update", "policy", before={k: cur.get(k) for k in new}, after=new, reason=d.get("reason") or "settings change", db_path=DB)
    return {"ok": True}


@app.get("/api/export")
def api_export():
    conn = get_conn(DB)
    out = {}
    for t in ("policy", "employees", "skills", "certs", "work_centers", "maintenance", "materials", "products", "routing_ops", "orders", "tasks",
              "schedule_versions", "version_assignments", "audit_log", "alerts"):
        out[t] = [dict(r) for r in conn.execute(f"SELECT * FROM {t}").fetchall()]
    conn.close()
    return JSONResponse(out, headers={"Content-Disposition": f"attachment; filename=cnc-demo-backup-{now_local():%Y%m%d-%H%M}.json"})


@app.post("/api/reset")
async def api_reset(request: Request):
    role = need(request, "reset")
    d = await body(request)
    if d.get("confirm") != "RESET":
        raise S.ApiError("Reset needs an explicit confirmation. Nothing was changed.")
    backups = Path(DB).parent / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    stamp = now_local().strftime("%Y%m%d-%H%M%S")
    if Path(DB).exists():
        shutil.copy(DB, backups / f"demo-{stamp}.db")
    reset_demo(DB)
    seed(DB)
    log_action(role, role, "reset_demo", "demo data", reason=f"reset with backup demo-{stamp}.db", db_path=DB)
    return {"ok": True, "backup": f"demo-{stamp}.db"}


@app.get("/api/meta")
def api_meta():
    pol = get_policy(DB)
    return {"horizon_start": resolve_horizon_start(pol).isoformat(), "slot_minutes": 15}
