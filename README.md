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

## Deploy option 1 - Render (recommended: free, no card)
1. https://render.com -> sign in with GitHub (no card needed for free tier).
2. New -> Web Service -> connect `CHINMAY-A007/cnc-workforce-allocation`
3. Render auto-detects `render.yaml` -> click "Apply"
4. Add env var `GEMINI_API_KEY` = your key (optional)
5. Deploy -> you get `https://cnc-workforce-allocation.onrender.com`

Free-tier limits: service sleeps after 15 min of inactivity (first open after sleep takes ~30s to wake); 512 MB RAM; ephemeral disk (DB resets on reboot and re-seeds on first request).

Note: Hugging Face Docker Spaces now require a PRO subscription, so Render is the best free no-card option.

## Deploy option 2 - Render (free, sleeps after 15 min)
1. https://render.com -> sign in with GitHub (no card).
2. New -> Web Service -> connect `CHINMAY-A007/cnc-workforce-allocation`
3. Render auto-detects `render.yaml` -> Apply.
4. Add env var `GEMINI_API_KEY` (optional).
5. Deploy -> `https://cnc-workforce-allocation.onrender.com`

## Shareable GitHub Pages link (optional landing page)
Enable GitHub Pages on this repo (Settings -> Pages -> Source: main /docs). Then
`https://CHINMAY-A007.github.io/cnc-workforce-allocation/` serves `docs/index.html`, which redirects to your live app. Edit the URL in `docs/index.html` to your HF Space or Render URL before enabling Pages.

## Tech
Python 3.10/3.11, FastAPI, uvicorn, Google OR-Tools CP-SAT, pandas, httpx, SQLite. No paid hosting required.