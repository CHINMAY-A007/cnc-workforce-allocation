"""Plain dataclasses for the CNC workforce allocation domain."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional


@dataclass
class Employee:
    id: str
    name: str
    role: str
    team: str
    shift: str
    max_daily_hours: float
    overtime_cap_hours: float
    active: bool = True
    leave_dates: List[str] = field(default_factory=list)


@dataclass
class SkillRecord:
    employee_id: str
    skill: str
    level: int


@dataclass
class CertRecord:
    employee_id: str
    cert: str
    expires_on: str  # ISO date


@dataclass
class WorkCenter:
    id: str
    name: str
    kind: str
    capacity: int = 1


@dataclass
class MaintenanceWindow:
    work_center_id: str
    start_slot: int
    end_slot: int
    reason: str


@dataclass
class RoutingOp:
    seq: int
    operation: str
    work_center_kind: str
    duration_min: int
    required_skill: str
    min_level: int
    required_role: str
    multi_person: int = 1
    is_quality_gate: bool = False
    setup_min: int = 0
    depends_on: List[int] = field(default_factory=list)


@dataclass
class Product:
    id: str
    name: str
    material: str
    routing: List[RoutingOp]


@dataclass
class Order:
    id: str
    product_id: str
    quantity: int
    priority: str
    due_date: str  # ISO date
    status: str
    customer_commitment: str
    notes: str = ""
    created_by: str = "demo"


@dataclass
class Task:
    id: str
    order_id: str
    seq: int
    name: str
    duration_min: int
    required_skill: str
    min_level: int
    required_role: str
    work_center_kind: str
    multi_person: int = 1
    is_quality_gate: bool = False
    depends_on: List[str] = field(default_factory=list)
    status: str = "Planned"
    chunk_index: int = 0
    chunk_total: int = 1
    parent_task_id: Optional[str] = None
    planned_start: Optional[int] = None
    planned_end: Optional[int] = None
    employee_ids: Optional[List[str]] = None
    work_center_id: Optional[str] = None
    locked: bool = False
    actual_start: Optional[int] = None
    actual_end: Optional[int] = None
    blocker_reason: Optional[str] = None


@dataclass
class EligibilityResult:
    task_id: str
    candidates: List[Dict[str, Any]] = field(default_factory=list)  # {employee, work_center}
    excluded: List[Dict[str, Any]] = field(default_factory=list)  # {person, reason}


@dataclass
class Assignment:
    task_id: str
    employee_ids: List[str]
    work_center_id: str
    start_slot: int
    end_slot: int
    locked: bool = False
    why: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ScheduleVersion:
    id: str
    created_at: str
    status: str  # draft / approved / superseded
    solver_status: str  # OPTIMAL / FEASIBLE / UNKNOWN / INFEASIBLE
    solver_runtime_sec: float
    objective_value: float
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    notes: str = ""


@dataclass
class AuditEntry:
    ts: str
    actor: str
    role: str
    action: str
    entity: str
    before: Optional[str] = None
    after: Optional[str] = None
    reason: Optional[str] = None
    version_id: Optional[str] = None


@dataclass
class Alert:
    id: str
    ts: str
    kind: str
    severity: str  # info / warning / critical
    message: str
    read: bool = False
    link: Optional[str] = None