# CNC Workforce Allocation - Client Demo (Simulated ERP)

Lightweight web app (FastAPI + HTML/JS) for AI-powered workforce allocation and scheduling in a CNC shop.
**Demo data only** - "Sample CNC Works, Bangalore (demo data)". Simulated ERP (local SQLite).

## Run locally

```powershell
cd C:\dev\cnc-workforce-alloc
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python data\seed.py
uvicorn app:app --host 127.0.0.1 --port 8000
```
Open http://localhost:8000

Reset demo data: `python data\seed.py --reset` (or use the Reset button in the UI).

## LLM note reader (optional)
Set `GEMINI_API_KEY` in a `.env` file or environment variable to enable Gemini-assisted note parsing.
Without a key, the keyword parser is used. All output is validated against known skills/certs.

## Deploy (free, lightweight)
**Render (free tier, no card):**
1. Push to GitHub.
2. Render -> New Web Service -> connect repo.
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn app:app --host 0.0.0.0 --port $PORT`
5. Add env var `GEMINI_API_KEY` (optional).
6. Deploy.

Free-tier limits: service sleeps after 15 min of inactivity (cold start ~30s); 512 MB RAM; ephemeral disk (DB resets on reboot and re-seeds on first request).

## Tech
Python 3.10/3.11, FastAPI, uvicorn, Google OR-Tools CP-SAT, pandas, httpx, SQLite. No paid hosting required.