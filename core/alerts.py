"""Notification centre (FR-13)."""
from __future__ import annotations

from datetime import datetime

from core.config import now_local
from core.db import get_conn


def add_alert(kind, severity, message, link=None, db_path=None):
    conn = get_conn(db_path)
    dup = conn.execute("SELECT id FROM alerts WHERE message=? AND read=0", (message,)).fetchone()
    if not dup:
        conn.execute("INSERT INTO alerts (ts,kind,severity,message,link) VALUES (?,?,?,?,?)",
                     (now_local().isoformat(timespec="seconds"), kind, severity, message, link))
        conn.commit()
    conn.close()


def list_alerts(unread_only=False, db_path=None):
    conn = get_conn(db_path)
    q = "SELECT * FROM alerts" + (" WHERE read=0" if unread_only else "") + " ORDER BY id DESC LIMIT 100"
    rows = conn.execute(q).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_read(alert_id, db_path=None):
    conn = get_conn(db_path)
    conn.execute("UPDATE alerts SET read=1 WHERE id=?", (alert_id,))
    conn.commit()
    conn.close()


def mark_all_read(db_path=None):
    conn = get_conn(db_path)
    conn.execute("UPDATE alerts SET read=1")
    conn.commit()
    conn.close()


def unread_count(db_path=None) -> int:
    conn = get_conn(db_path)
    n = conn.execute("SELECT COUNT(*) FROM alerts WHERE read=0").fetchone()[0]
    conn.close()
    return n
