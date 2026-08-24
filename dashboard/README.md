# VITHI Executive Overview

Dark React dashboard for Metadata MySQL (`obs_*` tables and views).

## Run

Terminal 1 — API:

```bash
uvicorn application.src.app:app --host 0.0.0.0 --port 8002 --reload
```

Terminal 2 — UI:

```bash
cd dashboard
npm install
npm run dev
```

Open http://127.0.0.1:5174

Vite proxies `/v1` to the API on port 8002. Override with `VITE_API_BASE` if needed.

Only the Overview screen is live. Other nav items are placeholders.
