"""Task generation from a production order's routing."""

from __future__ import annotations

import json
import uuid
from typing import List

from core.config import SLOTS_PER_HOUR
from core.db import get_conn
from core.models import Task


def _duration_min(op: dict, quantity: int) -> int:
    base = int(op["duration_min"]) * quantity
    setup = int(op.get("setup_min", 0) or 0)
    total = base + setup
    # batch rule: first piece setup included in setup_min; per-unit scaled by qty
    return max(SLOTS_PER_HOUR, total)  # at least 15 min


def generate_tasks(order_id: str, db_path=None) -> List[Task]:
    conn = get_conn(db_path)
    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        conn.close()
        raise ValueError(f"order not found: {order_id}")
    product_id = order["product_id"]
    quantity = int(order["quantity"])
    ops = conn.execute(
        "SELECT * FROM routing_ops WHERE product_id=? ORDER BY seq", (product_id,)
    ).fetchall()
    conn.close()

    # map seq -> op dict
    op_by_seq = {r["seq"]: dict(r) for r in ops}
    # dependency seqs -> task ids
    seq_to_task: dict[int, str] = {}
    tasks: List[Task] = []
    # first pass: create one task per op, possibly chunked
    for r in ops:
        op = dict(r)
        seq = op["seq"]
        dur = _duration_min(op, quantity)
        tid = f"{order_id}-T{seq:02d}"
        seq_to_task[seq] = tid
        deps = json.loads(op["depends_on"] or "[]")
        dep_task_ids = [f"{order_id}-T{d:02d}" for d in deps]
        tasks.append(
            Task(
                id=tid,
                order_id=order_id,
                seq=seq,
                name=op["operation"],
                duration_min=dur,
                required_skill=op["required_skill"],
                min_level=int(op["min_level"]),
                required_role=op["required_role"],
                work_center_kind=op["work_center_kind"],
                multi_person=int(op["multi_person"]),
                is_quality_gate=bool(op["is_quality_gate"]),
                depends_on=dep_task_ids,
            )
        )

    # chunk tasks longer than a single shift (8h = 32 slots) into continuation chunks
    # Each chunk stays on same employee, chained by dependency.
    chunked: List[Task] = []
    max_chunk_slots = 8 * SLOTS_PER_HOUR  # 32 slots = 8h
    for t in tasks:
        total_slots = (t.duration_min + 14) // 15
        if total_slots <= max_chunk_slots:
            chunked.append(t)
            continue
        # split
        nchunks = (total_slots + max_chunk_slots - 1) // max_chunk_slots
        chunk_slots = (total_slots + nchunks - 1) // nchunks
        parent = t.id
        prev = None
        for ci in range(nchunks):
            cid = f"{t.id}-C{ci+1}"
            ctask = Task(
                id=cid,
                order_id=t.order_id,
                seq=t.seq,
                name=f"{t.name} (part {ci+1}/{nchunks})",
                duration_min=chunk_slots * 15,
                required_skill=t.required_skill,
                min_level=t.min_level,
                required_role=t.required_role,
                work_center_kind=t.work_center_kind,
                multi_person=t.multi_person,
                is_quality_gate=t.is_quality_gate and ci == nchunks - 1,
                depends_on=[prev] if prev else list(t.depends_on),
                chunk_index=ci,
                chunk_total=nchunks,
                parent_task_id=parent,
            )
            chunked.append(ctask)
            prev = cid
    # fix depends_on for downstream tasks that pointed to a chunked parent
    for t in chunked:
        new_deps = []
        for d in t.depends_on:
            # if d is a parent that got chunked, point to its last chunk
            matched = [c for c in chunked if c.parent_task_id == d or c.id == d]
            # find last chunk of that parent
            last = None
            for c in chunked:
                if c.parent_task_id == d:
                    last = c.id
            if last:
                new_deps.append(last)
            else:
                new_deps.append(d)
        t.depends_on = new_deps

    # persist tasks
    conn = get_conn(db_path)
    for t in chunked:
        conn.execute(
            "INSERT OR REPLACE INTO tasks (id,order_id,seq,name,duration_min,required_skill,min_level,required_role,work_center_kind,multi_person,is_quality_gate,depends_on,status,chunk_index,chunk_total,parent_task_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (t.id, t.order_id, t.seq, t.name, t.duration_min, t.required_skill, t.min_level, t.required_role, t.work_center_kind, t.multi_person, 1 if t.is_quality_gate else 0, json.dumps(t.depends_on), "Planned", t.chunk_index, t.chunk_total, t.parent_task_id),
        )
    conn.commit()
    conn.close()
    return chunked


def list_tasks(order_id=None, db_path=None):
    conn = get_conn(db_path)
    if order_id:
        rows = conn.execute("SELECT * FROM tasks WHERE order_id=? ORDER BY seq, chunk_index", (order_id,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM tasks ORDER BY order_id, seq, chunk_index").fetchall()
    conn.close()
    out = []
    for r in rows:
        out.append(
            Task(
                id=r["id"], order_id=r["order_id"], seq=r["seq"], name=r["name"],
                duration_min=r["duration_min"], required_skill=r["required_skill"],
                min_level=r["min_level"], required_role=r["required_role"],
                work_center_kind=r["work_center_kind"], multi_person=r["multi_person"],
                is_quality_gate=bool(r["is_quality_gate"]),
                depends_on=json.loads(r["depends_on"] or "[]"),
                status=r["status"], chunk_index=r["chunk_index"], chunk_total=r["chunk_total"],
                parent_task_id=r["parent_task_id"], planned_start=r["planned_start"],
                planned_end=r["planned_end"], locked=bool(r["locked"]),
            )
        )
    return out


def update_task_status(task_id, status, actual_start=None, actual_end=None, blocker=None, db_path=None):
    conn = get_conn(db_path)
    conn.execute(
        "UPDATE tasks SET status=?, actual_start=COALESCE(?,actual_start), actual_end=COALESCE(?,actual_end), blocker_reason=COALESCE(?,blocker_reason) WHERE id=?",
        (status, actual_start, actual_end, blocker, task_id),
    )
    conn.commit()
    conn.close()