"""
Grafana dashboard generator for ETL Observability.

Uses Grafana HTTP API to upsert a stable dashboard (uid=etl-obs by default)
backed by Metadata MySQL views.
"""

from __future__ import annotations

import os
from typing import Any

import requests

from application.src.store.meta_mysql import ensure_grafana_views, get_connection


DEFAULT_DASHBOARD_UID = "etl-obs"
DEFAULT_DASHBOARD_TITLE = "ETL Observability"
DEFAULT_DATASOURCE_NAME = "ETL Metadata MySQL"


def _grafana_url() -> str:
    return (os.getenv("GRAFANA_URL") or "http://16.113.97.80:3000").rstrip("/")


def _grafana_token() -> str:
    return (os.getenv("GRAFANA_TOKEN") or "").strip()


def _headers() -> dict[str, str]:
    token = _grafana_token()
    if not token:
        raise RuntimeError(
            "GRAFANA_TOKEN is not set. Create a Grafana service-account token "
            "(Editor role) and add GRAFANA_TOKEN to .env"
        )
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _get(path: str) -> Any:
    resp = requests.get(f"{_grafana_url()}{path}", headers=_headers(), timeout=30)
    if resp.status_code >= 400:
        raise RuntimeError(f"Grafana GET {path} failed: {resp.status_code} {resp.text}")
    return resp.json()


def _post(path: str, payload: dict) -> Any:
    resp = requests.post(
        f"{_grafana_url()}{path}",
        headers=_headers(),
        json=payload,
        timeout=60,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Grafana POST {path} failed: {resp.status_code} {resp.text}")
    return resp.json()


def ensure_mysql_datasource() -> dict[str, str]:
    """
    Resolve or create the MySQL datasource pointing at Metadata DB.
    Returns {uid, name, type}.
    """
    forced = (os.getenv("GRAFANA_DATASOURCE_UID") or "").strip()
    sources = _get("/api/datasources")
    if not isinstance(sources, list):
        sources = []

    if forced:
        for ds in sources:
            if str(ds.get("uid") or "") == forced:
                return {
                    "uid": forced,
                    "name": str(ds.get("name") or DEFAULT_DATASOURCE_NAME),
                    "type": str(ds.get("type") or "mysql"),
                }
        raise RuntimeError(f"GRAFANA_DATASOURCE_UID={forced} not found in Grafana")

    for ds in sources:
        if str(ds.get("type") or "").lower() == "mysql":
            return {
                "uid": str(ds.get("uid")),
                "name": str(ds.get("name") or DEFAULT_DATASOURCE_NAME),
                "type": "mysql",
            }

    db_host = (os.getenv("DB_HOST") or "").strip()
    db_port = (os.getenv("DB_PORT") or "3306").strip()
    db_user = (os.getenv("DB_USER") or "").strip()
    db_password = (os.getenv("DB_PASSWORD") or os.getenv("MYSQL_PASSWORD") or "").strip()
    db_name = (os.getenv("DB_NAME") or "metadata").strip()
    if not (db_host and db_user and db_password):
        raise RuntimeError(
            "No MySQL datasource in Grafana and DB_HOST/DB_USER/DB_PASSWORD "
            "missing — cannot auto-create datasource"
        )

    created = _post(
        "/api/datasources",
        {
            "name": DEFAULT_DATASOURCE_NAME,
            "type": "mysql",
            "access": "proxy",
            "url": f"{db_host}:{db_port}",
            "user": db_user,
            "database": db_name,
            "isDefault": False,
            "jsonData": {
                "maxOpenConns": 10,
                "maxIdleConns": 5,
                "connMaxLifetime": 14400,
            },
            "secureJsonData": {"password": db_password},
        },
    )
    uid = str(created.get("datasource", {}).get("uid") or created.get("uid") or "")
    if not uid:
        # re-list
        sources = _get("/api/datasources")
        for ds in sources or []:
            if ds.get("name") == DEFAULT_DATASOURCE_NAME:
                uid = str(ds.get("uid"))
                break
    if not uid:
        raise RuntimeError(f"Datasource created but uid missing: {created}")
    return {"uid": uid, "name": DEFAULT_DATASOURCE_NAME, "type": "mysql"}


def _ds_ref(ds: dict[str, str]) -> dict[str, str]:
    return {"type": ds["type"], "uid": ds["uid"]}


def _stat_panel(
    *,
    panel_id: int,
    title: str,
    sql: str,
    ds: dict[str, str],
    x: int,
    y: int,
    w: int = 6,
    h: int = 4,
    unit: str = "none",
) -> dict[str, Any]:
    return {
        "id": panel_id,
        "type": "stat",
        "title": title,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "datasource": _ds_ref(ds),
        "targets": [
            {
                "refId": "A",
                "datasource": _ds_ref(ds),
                "format": "table",
                "rawQuery": True,
                "rawSql": sql.strip(),
            }
        ],
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": "blue", "value": None},
                        {"color": "green", "value": 0},
                    ],
                },
            },
            "overrides": [],
        },
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "orientation": "auto",
            "textMode": "auto",
            "colorMode": "value",
            "graphMode": "none",
            "justifyMode": "auto",
        },
    }


def _timeseries_panel(
    *,
    panel_id: int,
    title: str,
    sql: str,
    ds: dict[str, str],
    x: int,
    y: int,
    w: int = 24,
    h: int = 8,
) -> dict[str, Any]:
    return {
        "id": panel_id,
        "type": "timeseries",
        "title": title,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "datasource": _ds_ref(ds),
        "targets": [
            {
                "refId": "A",
                "datasource": _ds_ref(ds),
                "format": "time_series",
                "rawQuery": True,
                "rawSql": sql.strip(),
            }
        ],
        "fieldConfig": {
            "defaults": {
                "unit": "short",
                "custom": {
                    "drawStyle": "line",
                    "lineInterpolation": "smooth",
                    "fillOpacity": 15,
                    "showPoints": "never",
                },
            },
            "overrides": [],
        },
        "options": {
            "legend": {"displayMode": "list", "placement": "bottom"},
            "tooltip": {"mode": "multi"},
        },
    }


def _table_panel(
    *,
    panel_id: int,
    title: str,
    sql: str,
    ds: dict[str, str],
    x: int,
    y: int,
    w: int = 12,
    h: int = 8,
) -> dict[str, Any]:
    return {
        "id": panel_id,
        "type": "table",
        "title": title,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "datasource": _ds_ref(ds),
        "targets": [
            {
                "refId": "A",
                "datasource": _ds_ref(ds),
                "format": "table",
                "rawQuery": True,
                "rawSql": sql.strip(),
            }
        ],
        "options": {"showHeader": True},
    }


def build_dashboard_model(ds: dict[str, str]) -> dict[str, Any]:
    uid = (os.getenv("GRAFANA_DASHBOARD_UID") or DEFAULT_DASHBOARD_UID).strip()
    title = (os.getenv("GRAFANA_DASHBOARD_TITLE") or DEFAULT_DASHBOARD_TITLE).strip()

    panels = [
        _stat_panel(
            panel_id=1,
            title="Total Runs",
            sql="SELECT total_runs FROM vw_kpi_totals",
            ds=ds,
            x=0,
            y=0,
        ),
        _stat_panel(
            panel_id=2,
            title="Success Rate",
            sql="SELECT success_rate_pct FROM vw_kpi_totals",
            ds=ds,
            x=6,
            y=0,
            unit="percent",
        ),
        _stat_panel(
            panel_id=3,
            title="Failed Runs",
            sql="SELECT failed_runs FROM vw_kpi_totals",
            ds=ds,
            x=12,
            y=0,
        ),
        _stat_panel(
            panel_id=4,
            title="Success Runs",
            sql="SELECT success_runs FROM vw_kpi_totals",
            ds=ds,
            x=18,
            y=0,
        ),
        _timeseries_panel(
            panel_id=5,
            title="Daily Trends",
            sql="""
            SELECT
              CAST(metric_date AS DATETIME) AS time,
              total_runs AS Total,
              success_runs AS Success,
              failed_runs AS Failed
            FROM vw_daily_metrics
            WHERE $__timeFilter(metric_date)
            ORDER BY metric_date
            """,
            ds=ds,
            x=0,
            y=4,
        ),
        _table_panel(
            panel_id=6,
            title="Pipeline Health",
            sql="""
            SELECT
              pipeline_name,
              health_status,
              latest_status,
              success_rate_pct,
              failed_count,
              last_end_time,
              error_class,
              failed_node
            FROM vw_pipeline_health
            ORDER BY pipeline_name
            """,
            ds=ds,
            x=0,
            y=12,
            w=12,
            h=9,
        ),
        _table_panel(
            panel_id=7,
            title="Failed Runs",
            sql="""
            SELECT
              pipeline_name,
              run_id,
              end_time,
              failure_stage,
              error_class,
              failed_node,
              error_message
            FROM vw_failed_runs
            ORDER BY COALESCE(end_time, start_time) DESC
            LIMIT 50
            """,
            ds=ds,
            x=12,
            y=12,
            w=12,
            h=9,
        ),
    ]

    return {
        "uid": uid,
        "title": title,
        "timezone": "browser",
        "schemaVersion": 39,
        "version": 1,
        "refresh": "30s",
        "tags": ["etl", "observability"],
        "time": {"from": "now-30d", "to": "now"},
        "panels": panels,
    }


def create_or_update_dashboard() -> dict[str, Any]:
    """
    Ensure MySQL views exist, resolve datasource, upsert Grafana dashboard.
    Returns API-friendly payload including open URL.
    """
    conn = get_connection()
    try:
        ensure_grafana_views(conn)
    finally:
        conn.close()

    ds = ensure_mysql_datasource()
    dashboard = build_dashboard_model(ds)
    uid = dashboard["uid"]

    result = _post(
        "/api/dashboards/db",
        {
            "dashboard": dashboard,
            "overwrite": True,
            "message": "Upserted by Metadata API grafana_service",
        },
    )

    status = result.get("status") or result.get("message") or "ok"
    slug = result.get("slug") or uid
    result_uid = result.get("uid") or uid
    url = f"{_grafana_url()}/d/{result_uid}/{slug}?orgId=1"

    return {
        "ok": True,
        "status": status,
        "uid": result_uid,
        "slug": slug,
        "url": url,
        "datasource": ds,
        "grafana": result,
    }
