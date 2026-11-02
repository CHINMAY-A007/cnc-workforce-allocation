# Assumptions — CNC Workforce Allocation Demo

Short list of assumptions made for this demo:

1. **Working calendar** — 7-day horizon, Mon–Sat working, Sunday off. Configurable in policy (`core/config.py`, policy table).
2. **Horizon start** — next Monday from today (configurable).
3. **Shifts** — A: 06:00–14:00, B: 14:00–22:00; standard day 8 h, overtime cap 2 h, max daily 10 h.
4. **Task splitting** — tasks longer than one shift are pre-split into shift-sized chunks chained by dependency, kept on the same employee.
5. **Multi-person tasks** — require all assignees on the same shift.
6. **Eligibility** — skill level, role match, active status, leave dates and certification validity are evaluated at the horizon start date; expired certifications exclude employees from eligible tasks.
7. **Solver** — Google OR-Tools CP-SAT, 10 s time limit; an UNKNOWN result keeps the last approved schedule.
8. **Infeasibility** — reports zero-eligibility tasks plus labeled relaxation hints, not an exact diagnosis.
9. **Authentication** — the role switcher is a demo simulation, not real authentication or authorization.
10. **Data** — all companies, employees, customers and orders are fictional demo data ("Sample CNC Works"); the simulated ERP is local SQLite and is ephemeral on Render (re-seeds on first request).
