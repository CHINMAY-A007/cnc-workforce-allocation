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
    assert a["rows"] and a["scope"]["order_count"] == 5
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
