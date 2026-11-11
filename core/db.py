"""SQLite persistence helpers and schema."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

DB_PATH = os.environ.get("CNC_DB_PATH", str(Path(__file__).resolve().parent.parent / "data" / "demo.db"))


SCHEMA = r"""
CREATE TABLE IF NOT EXISTS policy (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS employees (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    team TEXT NOT NULL,
    shift TEXT NOT NULL,
    max_daily_hours REAL NOT NULL,
    overtime_cap_hours REAL NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    leave_dates TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS skills (
    employee_id TEXT NOT NULL,
    skill TEXT NOT NULL,
    level INTEGER NOT NULL,
    PRIMARY KEY (employee_id, skill),
    FOREIGN KEY (employee_id) REFERENCES employees(id)
);
CREATE TABLE IF NOT EXISTS certs (
    employee_id TEXT NOT NULL,
    cert TEXT NOT NULL,
    expires_on TEXT NOT NULL,
    PRIMARY KEY (employee_id, cert),
    FOREIGN KEY (employee_id) REFERENCES employees(id)
);
CREATE TABLE IF NOT EXISTS work_centers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    capacity INTEGER NOT NULL DEFAULT 1,
    down INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS maintenance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_center_id TEXT NOT NULL,
    start_slot INTEGER NOT NULL,
    end_slot INTEGER NOT NULL,
    reason TEXT NOT NULL,
    FOREIGN KEY (work_center_id) REFERENCES work_centers(id)
);
CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    material TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS materials (
    id TEXT PRIMARY KEY,
    on_hand REAL NOT NULL DEFAULT 0,
    unit TEXT NOT NULL DEFAULT 'units'
);
CREATE TABLE IF NOT EXISTS routing_ops (
    product_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    operation TEXT NOT NULL,
    work_center_kind TEXT NOT NULL,
    duration_min INTEGER NOT NULL,
    setup_min INTEGER NOT NULL DEFAULT 0,
    required_skill TEXT NOT NULL,
    min_level INTEGER NOT NULL,
    required_role TEXT NOT NULL,
    multi_person INTEGER NOT NULL DEFAULT 1,
    is_quality_gate INTEGER NOT NULL DEFAULT 0,
    depends_on TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (product_id, seq),
    FOREIGN KEY (product_id) REFERENCES products(id)
);
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    priority TEXT NOT NULL,
    due_date TEXT NOT NULL,
    status TEXT NOT NULL,
    customer_commitment TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT 'demo',
    requirements TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (product_id) REFERENCES products(id)
);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    name TEXT NOT NULL,
    duration_min INTEGER NOT NULL,
    required_skill TEXT NOT NULL,
    min_level INTEGER NOT NULL,
    required_role TEXT NOT NULL,
    work_center_kind TEXT NOT NULL,
    multi_person INTEGER NOT NULL DEFAULT 1,
    is_quality_gate INTEGER NOT NULL DEFAULT 0,
    depends_on TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'Planned',
    chunk_index INTEGER NOT NULL DEFAULT 0,
    chunk_total INTEGER NOT NULL DEFAULT 1,
    parent_task_id TEXT,
    planned_start INTEGER,
    planned_end INTEGER,
    employee_ids TEXT,
    work_center_id TEXT,
    locked INTEGER NOT NULL DEFAULT 0,
    actual_start INTEGER,
    actual_end INTEGER,
    blocker_reason TEXT,
    extra_skill TEXT,
    extra_min_level INTEGER NOT NULL DEFAULT 0,
    required_cert TEXT,
    FOREIGN KEY (order_id) REFERENCES orders(id)
);
CREATE TABLE IF NOT EXISTS schedule_versions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    solver_status TEXT NOT NULL,
    solver_runtime_sec REAL NOT NULL,
    objective_value REAL NOT NULL,
    approved_by TEXT,
    approved_at TEXT,
    notes TEXT NOT NULL DEFAULT '',
    parent_version_id TEXT,
    label TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS version_assignments (
    version_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    employee_ids TEXT NOT NULL,
    work_center_id TEXT NOT NULL,
    start_slot INTEGER NOT NULL,
    end_slot INTEGER NOT NULL,
    locked INTEGER NOT NULL DEFAULT 0,
    why TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (version_id, task_id),
    FOREIGN KEY (version_id) REFERENCES schedule_versions(id)
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    role TEXT NOT NULL,
    action TEXT NOT NULL,
    entity TEXT NOT NULL,
    before_val TEXT,
    after_val TEXT,
    reason TEXT,
    version_id TEXT
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    read INTEGER NOT NULL DEFAULT 0,
    link TEXT
);
CREATE TABLE IF NOT EXISTS gemini_usage (
    day TEXT PRIMARY KEY,
    calls INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS requirements_evidence (
    fr_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    screen TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'not yet verified',
    evidence TEXT NOT NULL DEFAULT ''
);
"""


def get_conn(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


MIGRATIONS = [
    ("orders", "requirements", "TEXT NOT NULL DEFAULT '{}'"),
    ("tasks", "extra_skill", "TEXT"),
    ("tasks", "extra_min_level", "INTEGER NOT NULL DEFAULT 0"),
    ("tasks", "required_cert", "TEXT"),
    ("schedule_versions", "parent_version_id", "TEXT"),
    ("schedule_versions", "label", "TEXT NOT NULL DEFAULT ''"),
    ("work_centers", "down", "INTEGER NOT NULL DEFAULT 0"),
    ("products", "material_per_unit", "REAL NOT NULL DEFAULT 1"),
]


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for table, col, decl in MIGRATIONS:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if col not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    conn.commit()


def is_seeded(conn: sqlite3.Connection) -> bool:
    try:
        n = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
        return n > 0
    except sqlite3.OperationalError:
        return False


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def reset_demo(db_path: Optional[str] = None) -> None:
    path = db_path or DB_PATH
    if os.path.exists(path):
        os.remove(path)