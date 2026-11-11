# Changelog

## Resource analysis and recommendations
- New Resource Analysis screen: required vs available for machines, people and raw materials, with exact shortage quantities, the time window where each shortage bites, and per-resource verdicts that separate true deficits from timing peaks the planner can smooth out.
- Raw-material inventory (simulated ERP): stock on hand per material, units-per-piece per product, reservations written when a schedule is approved after availability is revalidated at approval time, shortage alerts, and a stock-update action for the manager/ERP admin (audited).
- AI recommended actions per shortage (schedule available machines, search other departments for verified skills, additional shift/overtime, outsourcing, material reservation/purchase). Advisory only: nothing is auto-applied, recommendations stay separate from approved allocations, and every manager decision is recorded.
- Shortage diagnostics now classify missing skill vs material constraint alongside the existing due-date/overtime/horizon what-if tests.
- Requirements checklist extended to FR-16/FR-17 with self-test evidence; 25 automated tests.

## Repair and guided demo
- Fresh seed now produces a valid schedule (it was INFEASIBLE). Demo dates are relative to the next working day.
- New scheduler: people and machines never overlap, maintenance is respected, certificates and leave are checked per day, jobs can use more than one person, daily and overtime limits hold. An independent check re-validates every plan.
- Approve no longer crashes (audit entity was NULL). Unknown job ids return a clean JSON 404.
- Replanning for absence, breakdown, delay, priority change and urgent order. Only affected jobs and their followers move. Followers keep person and machine. Locked jobs are never changed silently, and a locked job that becomes impossible asks for an unlock.
- Impossible cases return the blocking reason and labelled what-if tests, never an invented assignment.
- Gemini is off by default (needs GEMINI_ENABLED=1 and a key, capped by GEMINI_MAX_CALLS). The public parse-notes endpoint no longer calls it.
- Role checks on the API, reset needs typed confirmation and saves a backup, JSON export.
- New interface: guided demo on Home, demo script drawer, plain-language labels, Gantt chart, approval screen with reasons, My Tasks, live simulator, reports, audit, requirements self-test. Icons are drawn with CSS so they render on any device.
- Removed dead Streamlit code. Added 16 tests.
