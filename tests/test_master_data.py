"""Manager-editable master data: new materials, machines, people, products.

Proves a genuinely different example (not one of the 5 seeded products) can be
entered through the API and flows through analysis and scheduling dynamically.
"""
PM = {"x-role": "Production Manager"}
HR = {"x-role": "HR/Workforce Admin"}
WK = {"x-role": "Worker"}

GRAPHITE_PRODUCT = {
    "name": "Graphite Electrode",
    "material": "Graphite",
    "material_per_unit": 3,
    "routing": [
        {"operation": "Saw Cutting", "work_center_kind": "Saw", "duration_min": 10, "required_skill": "Saw Cutting", "min_level": 2, "required_role": "Saw Operator"},
        {"operation": "Wire EDM", "work_center_kind": "EDM", "duration_min": 30, "setup_min": 15, "required_skill": "Wire EDM", "min_level": 3, "required_role": "EDM Operator", "depends_on": [1]},
        {"operation": "Final Inspection", "work_center_kind": "Inspection", "duration_min": 12, "required_skill": "CMM Inspection", "min_level": 3, "required_role": "Quality Inspector", "is_quality_gate": True, "depends_on": [2]},
    ],
}


def setup_graphite_example(c):
    """Add a genuinely new example through the API (the copper one is seeded since the
    client walkthrough became standard demo data, so dynamic adds use graphite)."""
    assert c.post("/api/materials", json={"id": "Graphite", "on_hand": 40, "unit": "kg"}, headers=PM).status_code == 200
    assert c.post("/api/work-centers", json={"name": "Band Saw 2", "kind": "Saw"}, headers=PM).status_code == 200
    assert c.post("/api/work-centers", json={"name": "Wire EDM 2", "kind": "EDM"}, headers=PM).status_code == 200
    r = c.post("/api/employees", json={"name": "Anil Kadam", "role": "EDM Operator", "team": "EDM", "shift": "A",
                                       "skills": [{"skill": "Wire EDM", "level": 4}, {"skill": "Saw Cutting", "level": 3}]}, headers=HR)
    assert r.status_code == 200, r.text
    r = c.post("/api/employees", json={"name": "Meena Joshi", "role": "Saw Operator", "team": "EDM", "shift": "A",
                                       "skills": [{"skill": "Saw Cutting", "level": 4}]}, headers=HR)
    assert r.status_code == 200, r.text
    r = c.post("/api/products", json=GRAPHITE_PRODUCT, headers=PM)
    assert r.status_code == 200, r.text
    return r.json()["product_id"]


def test_add_material_machine_employee_product(client):
    pid = setup_graphite_example(client)
    assert pid == "P-GRAPHITE-ELECTRODE"
    mats = {m["id"] for m in client.get("/api/materials").json()}
    assert "Graphite" in mats
    wcs = client.get("/api/work-centers").json()
    assert {"Saw", "EDM"} <= {w["kind"] for w in wcs}
    wf = client.get("/api/workforce").json()
    assert "Wire EDM" in wf["skills"]
    assert any(e["name"] == "Anil Kadam" for e in wf["employees"])
    prods = {p["id"]: p for p in client.get("/api/products").json()}
    assert len(prods[pid]["routing"]) == 3


def test_new_example_analysis_dynamic(client):
    """A new order of the brand-new product changes computed requirements by exactly qty x per-unit."""
    pid = setup_graphite_example(client)
    before = {r["resource"]: r["required"] for r in client.get("/api/analysis").json()["rows"]}
    due = client.get("/api/state").json()["horizon_start"]
    r = client.post("/api/orders", json={"product_id": pid, "quantity": 5, "priority": "High", "due_date": due}, headers=PM)
    assert r.status_code == 200, r.text
    assert r.json()["task_count"] == 3
    after = client.get("/api/analysis").json()["rows"]
    graphite = next(r for r in after if r["resource"] == "Raw material: Graphite")
    assert graphite["required"] == before.get("Raw material: Graphite", 0) + 5 * 3
    assert graphite["status"] == "sufficient"  # 15 needed, 40 on hand
    assert graphite["available"] == 40


def test_new_example_shortage_and_plan(client):
    """A qty that exceeds stock shows the exact shortage, and the plan schedules the new jobs on the new machine/person."""
    pid = setup_graphite_example(client)
    due = client.get("/api/state").json()["horizon_start"]
    r = client.post("/api/orders", json={"product_id": pid, "quantity": 20, "priority": "High", "due_date": due}, headers=PM)
    oid = r.json()["order_id"]
    a = client.get("/api/analysis?order_id=" + oid).json()
    graphite = next(x for x in a["rows"] if x["resource"] == "Raw material: Graphite")
    assert graphite["required"] == 60 and graphite["available"] == 40 and graphite["shortage"] == 20
    people_rows = [x for x in a["rows"] if x["group"] == "people"]
    assert any("EDM" in x["resource"] or "Saw" in x["resource"] for x in people_rows)
    p = client.post("/api/plan", json={}, headers=PM).json()
    assert p["status"] in ("OPTIMAL", "FEASIBLE"), p
    v = client.get(f"/api/version/{p['version_id']}").json()
    my = [a for a in v["assignments"] if a["task_id"].startswith(oid)]
    assert len(my) == 3
    kinds = {a["work_center_id"] for a in my}
    assert any(k.startswith("EDM") for k in kinds) and any(k.startswith("SAW") for k in kinds)


def test_master_data_validation(client):
    assert client.post("/api/materials", json={"id": "Copper", "on_hand": 10}, headers=WK).status_code == 403
    assert client.post("/api/products", json={"name": "X", "material": "NoSuchMaterial", "material_per_unit": 1,
                                              "routing": [{"operation": "Op", "work_center_kind": "Milling", "duration_min": 5,
                                                           "required_skill": "VMC Milling", "min_level": 1, "required_role": "VMC Operator"}]},
                       headers=PM).status_code == 400
    bad = dict(GRAPHITE_PRODUCT, routing=[dict(GRAPHITE_PRODUCT["routing"][1], depends_on=[2])])  # dep on itself/later
    assert client.post("/api/products", json=bad, headers=PM).status_code == 400
    assert client.post("/api/employees", json={"name": "No Shift", "role": "Packer", "shift": "Z"}, headers=HR).status_code == 400
    assert client.post("/api/work-centers", json={"name": "", "kind": "Saw"}, headers=PM).status_code == 400


def test_master_data_audited(client):
    pid = setup_graphite_example(client)
    log = client.get("/api/audit").json()
    actions = [e["action"] for e in (log if isinstance(log, list) else log.get("entries", []))]
    for a in ("material_add", "work_center_add", "employee_add", "product_add"):
        assert a in actions
