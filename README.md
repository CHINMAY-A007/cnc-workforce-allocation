# CNC Workforce Allocation (client demo)

Simulated ERP demo: an order comes in, the app creates jobs, checks who is allowed to do each one (skills, certificates, leave, hours), proposes a schedule with OR-Tools CP-SAT, and a manager reviews, edits, locks and approves it. Demo data only. Nothing here controls a machine.

## Run
    pip install -r requirements.txt
    uvicorn app:app --port 8000      # open http://localhost:8000
    pytest                           # 14 tests

## Demo in 2 minutes
Open the Home screen. Press **Prepare a ready schedule for me**, then follow the six guided steps (Demo script button, top right). Use **Live Progress** for the absence, breakdown, urgent order and "impossible case" scenarios.

## Notes
- Demo dates are relative to today (next working day, Asia/Kolkata). Override with `DEMO_EPOCH=YYYY-MM-DD`.
- Gemini is OFF by default; the note reader and the result explainer use local rules. To allow AI help set `GEMINI_ENABLED=1` and `GEMINI_API_KEY` (this can cost money; all AI calls share one cap, `GEMINI_MAX_CALLS`, default 25 per server run). The AI only reads order notes and explains validated results; OR-Tools makes every scheduling decision.
- Data lives in SQLite at `CNC_DB_PATH` (default `data/demo.db`). Existing databases are upgraded in place on start (columns are added, nothing is deleted).
- "Reset demo data" asks for confirmation and saves a backup copy first. "Download a backup" exports JSON of the main tables.
- Roles in the top-right switch are a demo of permissions, not real login.
