"""Requirements evidence helpers."""

from __future__ import annotations

from core.db import get_conn


def list_requirements(db_path=None):
    conn = get_conn(db_path)
    rows = conn.execute("SELECT * FROM requirements_evidence ORDER BY fr_id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_status(fr_id, status, evidence="", db_path=None):
    conn = get_conn(db_path)
    conn.execute("UPDATE requirements_evidence SET status=?, evidence=? WHERE fr_id=?", (status, evidence, fr_id))
    conn.commit()
    conn.close()