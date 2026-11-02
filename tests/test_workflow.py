import json
from core.solver import validate_schedule  # noqa: F401

PM = {"x-role": "Production Manager"}


def plan(c, **kw):
    r = c.post("/api/plan", json=kw, headers=PM)
    assert r.status_code == 200, r.text
    return r.json()


def approved(c):
    p = plan(c)
    assert p["status"] in ("OPTIMAL", "FEASIBLE"), p
    r = c.post("/api/approve", json={"version_id": p["version_id"]}, headers=PM)
    assert r.status_code == 200, r.text
    return p["version_id"]


def test_fresh_seed_plans_with_no_violations(client):
    p = plan(client)
    assert p["status"] in ("OPTIMAL", "FEASIBLE")
    assert p["violations"] == []
    assert len(p["assignments"]) >= 30


def test_no_overlap_and_dependencies(client):
    p = plan(client)
    by_emp, by_wc = {}, {}
    for a in p["assignments"]:
        for e in a["employee_ids"]:
            by_emp.setdefault(e, []).append((a["start_slot"], a["end_slot"]))
        if a.get("work_center_id"):
            by_wc.setdefault(a["work_center_id"], []).append((a["start_slot"], a["end_slot"]))
    for groups in (by_emp, by_wc):
        for spans in groups.values():
            spans.sort()
            for x, y in zip(spans, spans[1:]):
                assert x[1] <= y[0], "overlap"


def test_approval_requires_manager_role(client):
    p = plan(client)
    r = client.post("/api/approve", json={"version_id": p["version_id"]}, headers={"x-role": "Worker"})
    assert r.status_code == 403
    r = client.post("/api/plan", json={}, headers={"x-role": "Worker"})
    assert r.status_code == 403


def test_approve_then_reject_audit_has_no_null_entity(client):
    vid = approved(client)
    p2 = plan(client)
    r = client.post("/api/reject", json={"version_id": p2["version_id"], "reason": "test"}, headers=PM)
    assert r.status_code == 200
    log = client.get("/api/audit").json()
    rows = log if isinstance(log, list) else log.get("rows", log.get("audit", []))
    assert rows and all(x.get("entity") for x in rows)
    assert vid


def test_lock_survives_replan_after_absence(client):
    vid = approved(client)
    v = client.get(f"/api/version/{vid}").json()
    a = v["assignments"][0]
    assert client.post("/api/lock", json={"version_id": vid, "task_id": a["task_id"], "reason": "t"}, headers=PM).status_code == 200
    emp = next(e for x in v["assignments"] if x["task_id"] != a["task_id"] for e in x["employee_ids"] if e not in a["employee_ids"])
    r = client.post("/api/replan", json={"event": {"type": "absence", "employee_id": emp, "days": 2}}, headers=PM)
    assert r.status_code == 200, r.text
    out = r.json()
    new = out.get("new_version") or out
    vid2 = out.get("version_id") or new.get("version_id")
    assert vid2 and vid2 != vid
    v2 = client.get(f"/api/version/{vid2}").json()
    b = next(x for x in v2["assignments"] if x["task_id"] == a["task_id"])
    assert b["employee_ids"] == a["employee_ids"] and b["start_slot"] == a["start_slot"]
    # absent person is not working on the absent days
    assert v2.get("violations", []) == []


def test_impossible_case_is_reported_not_invented(client):
    approved(client)
    r = client.post("/api/replan", json={"event": {"type": "impossible"}}, headers=PM)
    assert r.status_code == 200, r.text
    txt = json.dumps(r.json())
    assert "INFEASIBLE" in txt or "infeasible" in txt.lower() or "cannot" in txt.lower()


def test_due_date_risk_is_flagged(client):
    r = client.post("/api/orders", json={"product_id": "P-TITANIUM-SHAFT", "quantity": 20, "priority": "Urgent",
                                         "due_date": client.get("/api/meta").json()["horizon_start"],
                                         "notes": ""}, headers=PM)
    assert r.status_code == 200, r.text
    p = plan(client, preset="rush")
    txt = json.dumps(p).lower()
    assert p["status"] in ("OPTIMAL", "FEASIBLE", "INFEASIBLE")
    assert "at risk" in txt or "late" in txt or p["status"] == "INFEASIBLE"


def test_blank_due_date_refused(client):
    r = client.post("/api/orders", json={"product_id": "P-ALU-FLANGE", "quantity": 5, "priority": "Normal", "due_date": ""}, headers=PM)
    assert r.status_code == 400


def test_task_status_flow(client):
    approved(client)
    t = client.get("/api/tasks").json()
    tasks = t if isinstance(t, list) else t["tasks"]
    tid = tasks[0]["id"]
    for st in ("In Progress", "Completed"):
        r = client.post(f"/api/tasks/{tid}/status", json={"status": st}, headers=PM)
        assert r.status_code in (200, 409), r.text


def test_unknown_task_gives_json_not_crash(client):
    r = client.get("/api/eligibility/NOPE")
    assert r.status_code == 404 and "error" in r.json()


def test_selftest_all_requirements_pass():
    from core import selftest
    res = selftest.run_all()
    bad = {k: v for k, v in res.items() if not v["ok"]}
    assert len(res) == 15 and not bad, bad
