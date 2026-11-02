"""Audit log helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from core.db import get_conn


def log_action(actor, role, action, entity, before=None, after=None, reason=None, version_id=None, db_path=None):
    conn = get_conn(db_path)
    conn.execute(
        "INSERT INTO audit_log (ts,actor,role,action,entity,before_val,after_val,reason,version_id) VALUES (?,?,?,?,?,?,?,?,?)",
        (datetime.now().isoformat(timespec="seconds"), actor, role, action, entity,
         None if before is None else (before if isinstance(before, str) else __import__("json").dumps(before)),
         None if after is None else (after if isinstance(after, str) else __import__("json").dumps(after)),
         reason, version_id),
    )
    conn.commit()
    conn.close()


def recent(limit=50, db_path=None):
    conn = get_conn(db_path)
    rows = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]