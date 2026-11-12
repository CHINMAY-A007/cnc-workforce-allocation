import json

PM = {"x-role": "Production Manager"}
ERP = {"x-role": "ERP Administrator"}
WK = {"x-role": "Worker"}


def plan_and_approve(c):
    p = c.post("/api/plan", json={}, headers=PM).json()
    assert p["status"] in ("OPTIMAL", "FEASIBLE"), p
    r = c.post("/api/approve", json={"version_id": p["version_id"]}, headers=PM)
    assert r.status_code == 200, r.text
    return p["version_id"]


def test_analysis_shape_and_groups(client):
    a = client.get("/api/analysis").json()
    assert a["rows"] and a["scope"]["order_count"] == 6
    groups = {r["group"] for r in a["rows"]}
    assert groups == {"machines", "people", "materials"}
    for r in a["rows"]:
        assert r["shortage"] == max(0, r["required"] - r["available"]) or r["group"] != "materials"
        assert r["status"] in ("short", "sufficient")
    assert a["method"] and a["disclaimer"]


def test_material_shortage_detected(client):
    a = client.get("/api/analysis").json()
    alloy = next(r for r in a["rows"] if r["resource"] == "Raw material: Alloy Steel")
    assert alloy["status"] == "short" and alloy["shortage"] == 10
    assert alloy["verdict"].startswith("true deficit")
    assert any(r["kind"] == "material" and r["severity"] == "critical" for r in a["recommendations"])


def test_timing_peak_distinguished_from_true_deficit(client):
    a = client.get("/api/analysis").json()
    turning = next(r for r in a["rows"] if r["resource"] == "Turning machines")
    assert turning["status"] == "short" and turning["verdict"].startswith("timing peak")
    assert turning["weekly"]["covers"] is True


def test_per_order_scope(client):
    a = client.get("/api/analysis?order_id=ORD-1004").json()
    assert a["scope"]["orders"] == ["ORD-1004"]
    mats = [r for r in a["rows"] if r["group"] == "materials"]
    assert len(mats) == 1 and mats[0]["resource"] == "Raw material: Brass"
    r = client.get("/api/analysis?order_id=NOPE")
    assert r.status_code == 404


def test_recommendations_are_advisory_only(client):
    # analysis must not change any data
    before = client.get("/api/audit").json()
    client.get("/api/analysis")
    after = client.get("/api/audit").json()
    assert len(before) == len(after)


def test_approval_writes_material_reservations(client):
    plan_and_approve(client)
    mats = {m["id"]: m for m in client.get("/api/materials").json()}
    assert mats["Titanium"]["reserved"] == 24  # ORD-1001: 12 pieces x 2 units
    log = json.dumps(client.get("/api/audit").json())
    assert "reserve_materials" in log


def test_material_shortage_alert_at_approval(client):
    plan_and_approve(client)  # reserves alloy; stock 20 < required 30
    al = client.get("/api/alerts").json()
    assert any(a["kind"] == "material_shortage" for a in al["items"])


def test_stock_update_permission_and_audit(client):
    r = client.post("/api/materials/Alloy Steel", json={"on_hand": 500}, headers=WK)
    assert r.status_code == 403
    r = client.post("/api/materials/Alloy Steel", json={"on_hand": 500, "reason": "delivery arrived"}, headers=ERP)
    assert r.status_code == 200
    a = client.get("/api/analysis").json()
    alloy = next(x for x in a["rows"] if x["resource"] == "Raw material: Alloy Steel")
    assert alloy["status"] == "sufficient"


def test_schedule_impact_after_plan(client):
    plan_and_approve(client)
    a = client.get("/api/analysis").json()
    assert a["schedule_impact"]["orders"] and a["schedule_impact"]["version"]


def test_explanation_endpoint_rule_based_when_gemini_off(client):
    r = client.get("/api/analysis/explanation")
    assert r.status_code == 200
    x = r.json()
    assert x["source"] == "rule-based" and x["text"] and x["label"]
    # rule-based writer must speak from the validated results: it names a real shortage
    a = client.get("/api/analysis").json()
    deficits = [row for row in a["rows"] if row["shortage"] and str(row.get("verdict", "")).startswith("true deficit")]
    if deficits:
        assert any(str(d["shortage"]) in x["text"] or f"{d['shortage']:g}" in x["text"] for d in deficits)


def test_explanation_unknown_order_404(client):
    assert client.get("/api/analysis/explanation?order_id=NOPE").status_code == 404


def test_dynamic_order_changes_analysis(client):
    """A new order must change the computed requirements - nothing hard-coded from the spec example."""
    before = client.get("/api/analysis").json()
    bmat = {r["resource"]: r["required"] for r in before["rows"] if r["group"] == "materials"}
    prods = {p["id"]: p for p in client.get("/api/products").json()}
    pid = next(p for p in prods if prods[p]["material"] == "Titanium")
    per_unit = float(prods[pid].get("material_per_unit") or 1)
    due = client.get("/api/state").json()["horizon_start"]
    r = client.post("/api/orders", json={"product_id": pid, "quantity": 6, "priority": "Normal", "due_date": due}, headers=PM)
    assert r.status_code == 200, r.text
    oid = r.json()["order_id"]
    after = client.get("/api/analysis").json()
    amat = {r["resource"]: r["required"] for r in after["rows"] if r["group"] == "materials"}
    assert amat["Raw material: Titanium"] == bmat.get("Raw material: Titanium", 0) + 6 * per_unit
    assert after["scope"]["order_count"] == before["scope"]["order_count"] + 1
    client.delete(f"/api/orders/{oid}", headers=PM)
    restored = client.get("/api/analysis").json()
    rmat = {r["resource"]: r["required"] for r in restored["rows"] if r["group"] == "materials"}
    assert rmat.get("Raw material: Titanium", 0) == bmat.get("Raw material: Titanium", 0)


def test_available_resources_dashboard_section(client):
    a = client.get("/api/analysis").json()
    ar = a["available_resources"]
    assert ar["people"] and ar["machines"]
    for p in ar["people"]:
        assert p["shift"] in ("A", "B") and p["week_hours"] >= 0 and "eligible" in p
    for m in ar["machines"]:
        assert m["status"] in ("up", "down") and m["capacity_hours"] >= 0
    # shortage rows name the affected operation (dashboard spec: affected operation, window, reason)
    short_rows = [r for r in a["rows"] if r["shortage"] and r["group"] in ("machines", "people")]
    assert any(r.get("operation") for r in short_rows)


def test_schedule_impact_other_jobs(client):
    plan_and_approve(client)
    p2 = client.post("/api/plan", json={}, headers=PM).json()  # new draft on top of approved
    assert p2["status"] in ("OPTIMAL", "FEASIBLE")
    a = client.get("/api/analysis").json()
    oj = a["schedule_impact"]["other_jobs"]
    assert oj is not None and oj["changed"] + oj["unchanged"] > 0
    assert "other scheduled jobs" in oj["text"].lower() or "changes" in oj["text"]
