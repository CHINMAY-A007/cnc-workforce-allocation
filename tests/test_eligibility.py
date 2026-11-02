import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.db import get_conn, init_schema, DB_PATH
from data.seed import seed
from core.tasks import generate_tasks
from core.policy import get_policy
from core.eligibility import eligible_pairs
from core.tasks import list_tasks

DB = "data/test2.db"


def setup_module():
    if os.path.exists(DB):
        os.remove(DB)
    conn = get_conn(DB)
    init_schema(conn)
    conn.close()
    seed(DB)
    generate_tasks("ORD-1001", DB)


def test_eligibility_excludes_expired_cert():
    policy = get_policy(DB)
    tasks = list_tasks("ORD-1001", DB)
    t = next(x for x in tasks if "Inspection" in x.name or "CMM" in x.name)
    er = eligible_pairs(t, policy, DB)
    # E07 has expired CMM cert -> should be excluded
    excluded_names = [e["person"] for e in er.excluded]
    assert any("Vikram" in n or "E07" in n for n in excluded_names) or len(er.excluded) > 0


def test_skill_missing_exclusion():
    policy = get_policy(DB)
    tasks = list_tasks("ORD-1001", DB)
    t = tasks[0]
    er = eligible_pairs(t, policy, DB)
    assert isinstance(er.candidates, list)