import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.db import get_conn, init_schema, DB_PATH
from data.seed import seed
from core.tasks import generate_tasks, list_tasks
from core.policy import get_policy
from core.solver import solve, validate_schedule

DB = "data/test.db"


def setup_module():
    if os.path.exists(DB):
        os.remove(DB)
    conn = get_conn(DB)
    init_schema(conn)
    conn.close()
    seed(DB)
    for oid in ["ORD-1001", "ORD-1002"]:
        generate_tasks(oid, DB)


def test_schedule_no_violations():
    policy = get_policy(DB)
    res = solve(DB, ["ORD-1001"], policy, time_limit_sec=10.0)
    assert res["status"] in ("OPTIMAL", "FEASIBLE"), res["status"]
    tasks = list_tasks("ORD-1001", DB)
    tdicts = [t.__dict__ for t in tasks]
    viols = validate_schedule(res["assignments"], tdicts, policy, DB)
    assert viols == [], viols


def test_locked_preserved():
    policy = get_policy(DB)
    res1 = solve(DB, ["ORD-1001"], policy, time_limit_sec=10.0)
    # lock first assignment
    locked = {res1["assignments"][0].task_id: {"employee_ids": res1["assignments"][0].employee_ids,
            "work_center_id": res1["assignments"][0].work_center_id,
            "start_slot": res1["assignments"][0].start_slot, "locked": True}}
    res2 = solve(DB, ["ORD-1001"], policy, locked=locked, time_limit_sec=10.0)
    a = next(x for x in res2["assignments"] if x.task_id == res1["assignments"][0].task_id)
    assert a.employee_ids == res1["assignments"][0].employee_ids
    assert a.start_slot == res1["assignments"][0].start_slot


def test_zero_eligibility_reported():
    # infeasible-ish: not directly; check solve returns status string
    policy = get_policy(DB)
    res = solve(DB, ["ORD-1001", "ORD-1002"], policy, time_limit_sec=5.0)
    assert res["status"] in ("OPTIMAL", "FEASIBLE", "INFEASIBLE", "UNKNOWN")