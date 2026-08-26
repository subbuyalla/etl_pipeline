# ETL Observability API

FastAPI backend service powering the ETL Observability Dashboard.

---

## Features

* **Overview & KPIs**: Health scores, success rates, active pipelines, and recent failure trends (`/api/v1/overview/*`).
* **Pipelines & Runs**: Detailed run logs, durations, and error classification (`/api/v1/pipelines/*`).
* **Lineage**: Upstream/downstream pipeline asset mapping (`/api/v1/lineage/*`).
* **Incidents & RCA**: Root cause analysis and failed run drill-downs (`/api/v1/incidents/*`).
* **Data Quality & Metrics**: Freshness SLAs, volume trends, and schema drift (`/api/v1/observability/*`, `/api/v1/metrics`).

---

## Project Structure

```text
├── .env                              # Environment configuration (DB credentials)
├── requirements.txt                  # Python dependencies
├── pyproject.toml                    # Modern project metadata & Vercel entrypoint
├── app.py                            # Primary FastAPI entrypoint (app:app)
└── application/
    └── src/
        ├── app.py                    # App configuration & CORS
        ├── api/
        │   ├── observability_router.py   # All REST endpoints (/api/v1/*)
        │   └── schemas.py                # Pydantic schemas & response models
        ├── services/
        │   └── observability/        # Query services (filters, overview, incidents, etc.)
        └── store/
            └── meta_mysql.py         # MySQL connection & SQL views/tables
```

---

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

Create a `.env` file with your MySQL database credentials:

```env
DB_HOST=your-mysql-host
DB_USER=your-mysql-user
DB_PASSWORD=your-mysql-password
DB_NAME=metadata
DB_PORT=3306
```

### 3. Run the API

```bash
uvicorn app:app --reload --port 8000
```

* **API Docs (Swagger UI)**: [http://localhost:8000/docs](http://localhost:8000/docs)
* **API Root**: [http://localhost:8000/](http://localhost:8000/)
* **Health Check**: [http://localhost:8000/health](http://localhost:8000/health)
