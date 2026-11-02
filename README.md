# CNC Workforce Allocation - Client Demo (Simulated ERP)

AI-powered workforce allocation and scheduling for a CNC machining shop.
**Demo data only** - "Sample CNC Works, Bangalore (demo data)". Simulated ERP (local SQLite).

## Run locally (reliable fallback)

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate
pip install -r requirements.txt
python data/seed.py
streamlit run app.py
```

Or with uv:
```bash
uv venv --python 3.11 .venv
uv pip install -r requirements.txt
.venv\Scripts\python data\seed.py
.venv\Scripts\streamlit run app.py
```

Open http://localhost:8501.

Reset demo data: click "Load demo data / Reset demo" on Home, or `python data/seed.py --reset`.

## Deploy to Streamlit Community Cloud (free tier)

1. Push this repo to GitHub (private or public).
2. Go to https://share.streamlit.io, sign in with GitHub.
3. New app -> select repo, branch `main`, main file `app.py`.
4. Python version 3.11. Deploy.
5. Streamlit installs from `requirements.txt` and runs `data/seed.py`? No - the app auto-seeds on first run if `data/demo.db` is missing (see `pages/home.py` `_ensure_db`). The hosted filesystem is ephemeral, so the DB resets on reboot and re-seeds automatically.

### Free-tier limits (state these to the client)
- ~1-2.7 GB RAM per app; app sleeps after inactivity (cold start 30-60s).
- Free accounts: unlimited public apps, but only **one private app**. Private repos may require granting Streamlit's GitHub app access.
- Hosted filesystem is ephemeral: SQLite demo data resets on reboot and re-seeds. Fine for a single presenter demo, not multi-user production.
- No SLA; free tier availability is not guaranteed.

## Tech
Python 3.10/3.11, Streamlit, Google OR-Tools CP-SAT (Apache 2.0), pandas, plotly, SQLite. No paid APIs, no LLM keys.

## Notes
- Order-notes reader is keyword matching only, not language understanding.
- Sidebar role switcher is a demo simulation of permissions, not real auth.
- Machine data is used for scheduling capacity only; the system never controls machines.
- Hard constraints (skills, certs, availability, safety) have no override path.