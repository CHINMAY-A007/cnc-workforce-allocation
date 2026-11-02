# Changelog — CNC Workforce Allocation Demo

## Phase 5: Polish (client-ready demo)

This changelog lists every fix made against the 14 audit items (FR-01 … FR-14) raised in the demo audit, plus the presentational polish for the client walkthrough.

## Fixes by audit item

| # | Audit item | Screen | Fix applied | Status |
|---|---|---|---|---|
| FR-01 | Order intake | Orders and Tasks | Order creation form accepts product, quantity, priority, due date, customer commitment and free-text notes; orders land in the simulated ERP (SQLite) with status "Released". | ✅ Fixed |
| FR-02 | Task generation | Orders and Tasks | Creating an order auto-generates jobs/tasks from the product routing (cutting → turning → 5-axis → VMC → deburring → CMM → packing) with dependencies. | ✅ Fixed |
| FR-03 | Workforce profile | Workforce and Skill Matrix | 18 employees across Turning, Milling, 5-Axis, Setup, Quality, Finishing, Dispatch, Supervision; skill matrix heatmap shows levels 0–5 per employee. | ✅ Fixed |
| FR-04 | Eligibility validation | Workforce / Approval | Eligibility endpoint filters by skill level, role match, active status, leave dates and certification expiry (evaluated at horizon start). Expired certs exclude employees from eligible tasks. | ✅ Fixed |
| FR-05 | Capacity checks | AI Allocation Proposal | Solver enforces per-employee shift capacity (8 h/day, 2 h overtime cap, 10 h max day), work-center availability and planned maintenance windows. | ✅ Fixed |
| FR-06 | Allocation optimization | AI Allocation Proposal | OR-Tools CP-SAT solver optimizes on-time delivery, overtime, workload balance, makespan, reassignment and continuity with selectable objective weights. | ✅ Fixed |
| FR-07 | Schedule generation | Schedule Gantt | Solver produces a draft schedule version with per-task start/end slots, work center and employee assignments, renderable in the Gantt (Employee / Work Center view). | ✅ Fixed |
| FR-08 | Constraint handling | AI Allocation Proposal | Hard constraints (skill, role, certification, capacity, maintenance, dependencies) are never violated; the solver reports any violations. | ✅ Fixed |
| FR-09 | Objectives | AI Allocation Proposal | Objective preset (Balanced / Rush mode / Cost saver) plus per-weight sliders for on_time, overtime, balance, makespan, reassignment, continuity. | ✅ Fixed |
| FR-10 | Approval and override | Approval and Reassignment | Manager can reassign a task (reason required), lock/unlock, approve or reject a version; overrides require a reason and are logged to the audit trail. | ✅ Fixed |
| FR-11 | Progress tracking | My Tasks / Live Progress | Worker role view shows assigned tasks with large Start / Complete / Report Issue buttons; status updates persist to the simulated ERP. | ✅ Fixed |
| FR-12 | Replanning | Live Progress and Alerts | Replanning simulator (absence, breakdown, delay, new order, priority_change) proposes a revised plan; locked tasks are never moved. | ✅ Fixed |
| FR-13 | Alerts | Live Progress and Alerts | Alerts fire on schedule generation, reassignment and approval; unread count shown in the header badge and alert list. | ✅ Fixed |
| FR-14 | Reporting | Reports | Utilization by employee, bottleneck work center, and planned vs actual task status are reported. | ✅ Fixed |

## Demo polish (this phase)

- **Home page** rewritten as a client-ready walkthrough:
  - One-line value proposition: "This tool reads your production orders, breaks them into jobs, and automatically picks the right worker for each job."
  - Big "Start the 2-minute demo" button that resets clean seeded data and begins at Step 1.
  - Three benefit cards: AI picks the right worker / Replan in seconds / Full audit trail.
  - 5-step guided bar with current step highlighted, a Next button, and each "Open" button landing on the right tab with data loaded.
- **Presenter notes**: collapsible panel on the home page with the exact click and one-line talking point for each step.
- **Labeling**: all data labeled "Demo data — Sample CNC Works, Bangalore (simulated ERP)".
- **Reset demo**: one click restores clean data; the seeded dataset produces a good first schedule with no manual steps.

## Requirements coverage note

FR-15 (Explanation and audit) covers the audit trail itself — "Why this person?" panel, audit log, policy/weights — and is addressed by the approval/explain screens and the `/api/audit` endpoint. It is the evidence-gated counterpart to the 14 functional audit items above.
