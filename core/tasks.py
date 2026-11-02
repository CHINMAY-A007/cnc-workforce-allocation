"""Task generation from a production order's routing (FR-02) and progress tracking (FR-11)."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.config import SLOTS_PER_HOUR, STATUSES, now_local
from core.db import get_conn

MAX_CHUNK_SLOTS = 8 * SLOTS_PER_HOUR  # a single piece of work never exceeds one 8h shift
MACHINING_KINDS = {"Turning", "Milling", "5Axis"}


LOT_SIZE = 10          # pieces per lot
MIN_PER_ROUTING_UNIT = 4  # demo batch rule: routing minutes x 4 per lot of 10 pieces, plus setup


def _duration_min(op: dict, quantity: int) -> int:
    """Demo batch rule (an assumption, shown on the About page): setup + routing time x 4 per 10-piece lot."""
    lots = max(1, -(-int(quantity) // LOT_SIZE))
    return max(15, int(op["duration_min"]) * MIN_PER_ROUTING_UNIT * lots + int(op.get("setup_min") or 0))


def generate_tasks(order_id: str, db_path=None) -> List[dict]:
    """(Re)build the tasks of one order from its routing, applying note requirements."""
    conn = get_conn(db_path)
    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        conn.close()
        raise ValueError(f"order not found: {order_id}")
    ops = [dict(r) for r in conn.execute("SELECT * FROM routing_ops WHERE product_id=? ORDER BY seq", (order["product_id"],)).fetchall()]
    try:
        reqs = json.loads(order["requirements"] or "{}")
    except Exception:
        reqs = {}
    qty = int(order["quantity"])
    needs_titanium = "Titanium Machining" in (reqs.get("skills") or [])
    cert_needed = (reqs.get("certs") or [None])[0]

    tasks: List[Dict[str, Any]] = []
    for op in ops:
        tid = f"{order_id}-T{op['seq']:02d}"
        t = dict(
            id=tid, order_id=order_id, seq=op["seq"], name=op["operation"],
            duration_min=_duration_min(op, qty), required_skill=op["required_skill"],
            min_level=int(op["min_level"]), required_role=op["required_role"],
            work_center_kind=op["work_center_kind"], multi_person=int(op["multi_person"]),
            is_quality_gate=int(op["is_quality_gate"]),
            depends_on=[f"{order_id}-T{d:02d}" for d in json.loads(op["depends_on"] or "[]")],
            chunk_index=0, chunk_total=1, parent_task_id=None,
            extra_skill=None, extra_min_level=0, required_cert=None,
        )
        if needs_titanium and op["work_center_kind"] in MACHINING_KINDS and op["required_skill"] != "Titanium Machining":
            t["extra_skill"], t["extra_min_level"] = "Titanium Machining", 2
        if cert_needed and op["is_quality_gate"]:
            t["required_cert"] = cert_needed
        tasks.append(t)

    # split anything longer than one shift into chained parts, keep dependencies pointing at the last part
    out: List[Dict[str, Any]] = []
    last_part: Dict[str, str] = {}
    for t in tasks:
        slots = (t["duration_min"] + 14) // 15
        if slots <= MAX_CHUNK_SLOTS:
            out.append(t)
            last_part[t["id"]] = t["id"]
            continue
        n = (slots + MAX_CHUNK_SLOTS - 1) // MAX_CHUNK_SLOTS
        per = (slots + n - 1) // n
        prev = None
        for ci in range(n):
            c = dict(t)
            c.update(id=f"{t['id']}-C{ci+1}", name=f"{t['name']} (part {ci+1} of {n})",
                     duration_min=per * 15, chunk_index=ci, chunk_total=n, parent_task_id=t["id"],
                     depends_on=[prev] if prev else list(t["depends_on"]),
                     is_quality_gate=int(t["is_quality_gate"] and ci == n - 1))
            out.append(c)
            prev = c["id"]
        last_part[t["id"]] = prev
    for t in out:
        t["depends_on"] = [last_part.get(d, d) for d in t["depends_on"]]

    conn.execute("DELETE FROM tasks WHERE order_id=?", (order_id,))
    for t in out:
        conn.execute(
            "INSERT INTO tasks (id,order_id,seq,name,duration_min,required_skill,min_level,required_role,work_center_kind,multi_person,is_quality_gate,depends_on,status,chunk_index,chunk_total,parent_task_id,extra_skill,extra_min_level,required_cert) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (t["id"], t["order_id"], t["seq"], t["name"], t["duration_min"], t["required_skill"], t["min_level"],
             t["required_role"], t["work_center_kind"], t["multi_person"], t["is_quality_gate"], json.dumps(t["depends_on"]),
             "Planned", t["chunk_index"], t["chunk_total"], t["parent_task_id"], t["extra_skill"], t["extra_min_level"], t["required_cert"]),
        )
    conn.commit()
    conn.close()
    return out


def task_row(r) -> dict:
    d = dict(r)
    d["depends_on"] = json.loads(d.get("depends_on") or "[]")
    d["employee_ids"] = json.loads(d["employee_ids"]) if d.get("employee_ids") else []
    d["is_quality_gate"] = bool(d["is_quality_gate"])
    d["locked"] = bool(d["locked"])
    return d


def list_tasks(order_id: Optional[str] = None, db_path=None) -> List[dict]:
    conn = get_conn(db_path)
    if order_id:
        rows = conn.execute("SELECT * FROM tasks WHERE order_id=? ORDER BY seq, chunk_index", (order_id,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM tasks ORDER BY order_id, seq, chunk_index").fetchall()
    conn.close()
    return [task_row(r) for r in rows]


def get_task(tid: str, db_path=None) -> Optional[dict]:
    conn = get_conn(db_path)
    r = conn.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    conn.close()
    return task_row(r) if r else None


def update_task_status(task_id, status, blocker=None, db_path=None):
    """Record progress. Start/finish times are stamped by the server clock."""
    if status not in STATUSES:
        raise ValueError(f"unknown status {status}")
    stamp = now_local().isoformat(timespec="minutes")
    conn = get_conn(db_path)
    cur = conn.execute("SELECT actual_start FROM tasks WHERE id=?", (task_id,)).fetchone()
    if cur is None:
        conn.close()
        raise ValueError("task not found")
    if status == "In Progress":
        conn.execute("UPDATE tasks SET status=?, actual_start=COALESCE(actual_start,?), blocker_reason=NULL WHERE id=?", (status, stamp, task_id))
    elif status == "Completed":
        conn.execute("UPDATE tasks SET status=?, actual_start=COALESCE(actual_start,?), actual_end=?, blocker_reason=NULL WHERE id=?", (status, stamp, stamp, task_id))
    elif status == "Blocked":
        conn.execute("UPDATE tasks SET status=?, blocker_reason=? WHERE id=?", (status, blocker or "Reason not given", task_id))
    else:
        conn.execute("UPDATE tasks SET status=? WHERE id=?", (status, task_id))
    conn.commit()
    conn.close()
