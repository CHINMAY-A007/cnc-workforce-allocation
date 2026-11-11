"""Requirements coverage (FR-01..FR-15) with evidence-gated ticks.

A requirement shows "verified" ONLY after the built-in self-test has run its check against a
scratch copy of the demo and the check passed. Otherwise it says "not yet verified".
"""
from __future__ import annotations

FR_TITLES = {
    "FR-01": ("Order intake", "orders"),
    "FR-02": ("Task generation from the routing", "orders"),
    "FR-03": ("Workforce profile and skill matrix", "workforce"),
    "FR-04": ("Eligibility: who qualifies and who is excluded", "workforce"),
    "FR-05": ("Machine capacity and planned downtime", "plan"),
    "FR-06": ("Allocation optimization (solver)", "plan"),
    "FR-07": ("Schedule chart and delivery estimates", "gantt"),
    "FR-08": ("Hard rules never broken", "plan"),
    "FR-09": ("Objectives and presets", "plan"),
    "FR-10": ("Approve, edit, lock, reject", "approval"),
    "FR-11": ("Progress tracking", "mytasks"),
    "FR-12": ("Replanning for surprises", "live"),
    "FR-13": ("Alerts", "live"),
    "FR-14": ("Reports", "reports"),
    "FR-15": ("Explanations and audit trail", "audit"),
    "FR-16": ("Resource availability analysis and shortages", "resources"),
    "FR-17": ("AI recommended actions and material reservation", "resources"),
}
