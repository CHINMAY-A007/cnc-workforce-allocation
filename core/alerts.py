"""Alert helpers."""

from __future__ import annotations

from datetime import datetime
from typing import List

from core.db import get_conn


def add_alert(kind, severity, message, link=None, db_path=None):
    conn = get_conn(db_path)
    conn.execute(
        "INSERT INTO alerts (ts,kind,severity,message,link) VALUES (?,?,?,?,?)",
        (datetime.now().isoformat(timespec="seconds"), kind, severity, message, link),
    )
    conn.commit()
    conn.close()


def list_alerts(unread_only=False, db_path=None) -> List[dict]:
    conn = get_conn(db_path)
    if unread_only:
        rows = conn.execute("SELECT * FROM alerts WHERE read=0 ORDER BY id DESC").fetchall()
    else:
        rows = conn.execute("SELECT * FROM alerts ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_read(alert_id, db_path=None):
    conn = get_conn(db_path)
    conn.execute("UPDATE alerts SET read=1 WHERE id=?", (alert_id,))
    conn.commit()
    conn.close()


def unread_count(db_path=None) -> int:
    conn = get_conn(db_path)
    n = conn.execute("SELECT COUNT(*) FROM alerts WHERE read=0").fetchone()[0]
    conn.close()
    return n