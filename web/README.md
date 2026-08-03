# Reliability UI

React (Vite) dashboard for pipelines, incidents, monitors, datasets, and lineage.

## Run

Terminal 1 — Metadata API:

```bash
cd packages/metadata
pip install -e ".[dev]"
python -m metadata.api
```

Terminal 2 — UI:

```bash
cd web
npm install
npm run dev
```

Open http://127.0.0.1:5173 — default tenant `demo`.

API base URL: `VITE_API_BASE` in `web/.env` (default `http://127.0.0.1:8000`).
