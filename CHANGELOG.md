# Changelog

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
