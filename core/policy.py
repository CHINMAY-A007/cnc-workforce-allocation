"""Policy load/save wrappers."""

from __future__ import annotations

from core.config import load_policy, save_policy
from core.db import get_conn


def get_policy(db_path=None):
    return load_policy(get_conn(db_path))


def set_policy(policy, db_path=None, actor="demo", role="ERP Administrator"):
    conn = get_conn(db_path)
    save_policy(conn, policy)
    conn.close()