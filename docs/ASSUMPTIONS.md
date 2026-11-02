# Assumptions

1. Working calendar: 7-day horizon, Mon-Sat working, Sun off. Configurable in policy (core/config.py + policy table).
2. Python 3.11+ target, also runs on 3.10 (CI matrix).
3. Tasks longer than one shift are pre-split into shift-sized chunks chained by dependency, kept on the same employee.
4. Multi-person tasks require all assignees on the same shift.
5. Eligibility/cert validity evaluated at horizon start date.
6. Horizon start = next Monday from today.
7. Note parser vocabulary is limited to known terms; unknown phrases rejected.
8. Solver: 4 workers, 10s time limit; UNKNOWN keeps last approved schedule.
9. Infeasibility reports zero-eligibility tasks + labeled relaxation hints (not exact diagnosis).
10. Streamlit Community Cloud free tier limits apply (see README).