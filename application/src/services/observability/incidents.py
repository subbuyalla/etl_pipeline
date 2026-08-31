"""Derived incidents: one open incident per pipeline with latest run failed."""

from __future__ import annotations

from typing import Any, Optional

from application.src.api.schemas import make_kpi
from application.src.services.observability.filters import (
    age_label,
    apply_delta,
    build_run_where,
    delta_pct,
    envelope,
    fetchall,
    fetchone,
    format_duration,
    json_val,
    num,
    parse_range,
    utc_now,
)


def _severity(error_class: Any, error_message: Any) -> str:
    ec = str(error_class or "").lower()
    msg = str(error_message or "").lower()
    if ec == "compilation" or "compilation error" in msg or "invalid identifier" in msg:
        return "critical"
    if ec == "runtime" or "timeout" in msg:
        return "high"
    return "medium"


def _blast_radius(conn, run_id: Any) -> int:
    if not run_id:
        return 0
    row = fetchone(
        conn,
        """
        SELECT COUNT(*) AS n
        FROM obs_run_assets
        WHERE run_id = %s AND UPPER(COALESCE(asset_role, '')) = 'TARGET'
        """,
        (str(run_id),),
    )
    return int(num(row.get("n")))


def list_derived_incidents(
    conn,
    *,
    from_str: Optional[str] = None,
    to_str: Optional[str] = None,
    pipeline_name: Optional[str] = None,
    pipeline_id: Optional[str] = None,
    include_resolved: bool = True,
) -> list[dict]:
    """
    Open: latest run per pipeline is failed/error.
    Resolved (in range): pipeline had a failure in range and a later success (or latest is success
    but there was a failure in range).
    """
    # Latest run per pipeline
    where_extra = []
    params: list[Any] = []
    if pipeline_name:
        names = [n.strip() for n in pipeline_name.split(",") if n.strip()]
        if names:
            ph = ",".join(["%s"] * len(names))
            where_extra.append(f"p.pipeline_name IN ({ph})")
            params.extend(names)
    if pipeline_id:
        ids = [i.strip() for i in pipeline_id.split(",") if i.strip()]
        if ids:
            ph = ",".join(["%s"] * len(ids))
            where_extra.append(f"p.pipeline_id IN ({ph})")
            params.extend(ids)
    where_sql = ("WHERE " + " AND ".join(where_extra)) if where_extra else ""

    latest_sql = f"""
        SELECT
          p.pipeline_id,
          p.pipeline_name,
          lr.id AS run_id,
          lr.status,
          lr.start_time,
          lr.end_time,
          lr.duration,
          lr.failure_stage,
          lr.failed_node,
          lr.error_class,
          lr.error_message,
          lr.created_at
        FROM obs_pipelines p
        LEFT JOIN obs_pipeline_runs lr
          ON lr.id = (
            SELECT r.id FROM obs_pipeline_runs r
            WHERE r.pipeline_id = p.pipeline_id
            ORDER BY COALESCE(r.end_time, r.start_time, r.created_at) DESC
            LIMIT 1
          )
        {where_sql}
        ORDER BY p.pipeline_name
    """
    latest_rows = fetchall(conn, latest_sql, params)
    now = utc_now()
    open_items = []
    for r in latest_rows:
        st = str(r.get("status") or "").lower()
        if st not in {"failed", "error"}:
            continue
        opened = r.get("end_time") or r.get("start_time") or r.get("created_at")
        sev = _severity(r.get("error_class"), r.get("error_message"))
        blast = _blast_radius(conn, r.get("run_id"))
        incident_id = f"inc:{r.get('pipeline_id')}:open"
        msg = str(r.get("error_message") or "").split("\n")[0][:200]
        open_items.append(
            {
                "incident_id": incident_id,
                "id": incident_id,
                "title": f"{r.get('pipeline_name')} is failing",
                "description": msg or f"Execution failed at stage {r.get('failure_stage') or 'unknown'}",
                "severity": sev,
                "status": "open",
                "root_asset_type": "pipeline",
                "root_asset_id": r.get("pipeline_id"),
                "pipeline_id": r.get("pipeline_id"),
                "pipeline_name": r.get("pipeline_name"),
                "run_id": r.get("run_id"),
                "blast_radius": blast,
                "opened_at": json_val(opened),
                "opened_age": age_label(opened, now),
                "duration": age_label(opened, now),
                "duration_seconds": (
                    int((now - opened).total_seconds())
                    if hasattr(opened, "year")
                    else None
                ),
                "failure_stage": r.get("failure_stage"),
                "failed_node": r.get("failed_node"),
                "error_class": r.get("error_class"),
                "error_message": r.get("error_message"),
            }
        )

    resolved_items: list[dict] = []
    if include_resolved and from_str and to_str:
        # Failures in range whose pipeline latest status is success
        fail_where, fail_params = build_run_where(
            alias="r",
            pipeline_name=pipeline_name,
            pipeline_id=pipeline_id,
            status="failed,error",
            from_str=from_str,
            to_str=to_str,
        )
        fails = fetchall(
            conn,
            f"""
            SELECT r.pipeline_id, r.pipeline_name, r.id AS run_id, r.error_class, r.error_message,
                   r.end_time, r.start_time, r.failure_stage, r.failed_node
            FROM obs_pipeline_runs r
            {fail_where}
            ORDER BY COALESCE(r.end_time, r.start_time) DESC
            """,
            fail_params,
        )
        open_pids = {i["pipeline_id"] for i in open_items}
        seen = set()
        for f in fails:
            pid = f.get("pipeline_id")
            if pid in open_pids or pid in seen:
                continue
            # Check latest is success
            latest = next((x for x in latest_rows if x.get("pipeline_id") == pid), None)
            if not latest:
                continue
            if str(latest.get("status") or "").lower() not in {"success", "succeeded"}:
                continue
            seen.add(pid)
            sev = _severity(f.get("error_class"), f.get("error_message"))
            resolved_items.append(
                {
                    "incident_id": f"inc:{pid}:resolved:{f.get('run_id')}",
                    "id": f"inc:{pid}:resolved:{f.get('run_id')}",
                    "title": f"{f.get('pipeline_name')} recovered",
                    "description": str(f.get("error_message") or "").split("\n")[0][:200],
                    "severity": sev,
                    "status": "resolved",
                    "root_asset_type": "pipeline",
                    "root_asset_id": pid,
                    "pipeline_id": pid,
                    "pipeline_name": f.get("pipeline_name"),
                    "run_id": f.get("run_id"),
                    "blast_radius": _blast_radius(conn, f.get("run_id")),
                    "opened_at": json_val(f.get("end_time") or f.get("start_time")),
                    "opened_age": age_label(f.get("end_time") or f.get("start_time"), now),
                    "duration": None,
                    "resolved_at": json_val(latest.get("end_time") or latest.get("start_time")),
                    "failure_stage": f.get("failure_stage"),
                    "failed_node": f.get("failed_node"),
                    "error_class": f.get("error_class"),
                    "error_message": f.get("error_message"),
                }
            )

    return open_items + resolved_items


def get_incident(conn, incident_id: str) -> dict | None:
    items = list_derived_incidents(conn, include_resolved=True)
    for i in items:
        if i.get("incident_id") == incident_id or i.get("id") == incident_id:
            return i
    # Try open by pipeline id
    if incident_id.startswith("inc:") and ":open" in incident_id:
        pid = incident_id.split(":")[1]
        for i in items:
            if i.get("pipeline_id") == pid and i.get("status") == "open":
                return i
    return None


def incident_series(
    conn,
    from_str: str,
    to_str: str,
    *,
    pipeline_name=None,
    pipeline_id=None,
    grain: str | None = None,
    rng: dict | None = None,
) -> dict:
    """
    Time series of *failed runs by severity* and success/fail run counts.

    Not true open/resolved incident timelines (those are derived per-pipeline latest).
    Keys failed_runs / success_runs are honest; open/resolved kept as aliases.
    """
    from application.src.services.observability.filters import (
        chart_bucket_grain,
        sql_time_bucket_expr,
        zero_fill_series,
    )

    if grain is None and rng is not None:
        grain = chart_bucket_grain(rng)
    grain = grain or "day"
    bucket_expr = sql_time_bucket_expr("r", grain)
    where, params = build_run_where(
        alias="r",
        pipeline_name=pipeline_name,
        pipeline_id=pipeline_id,
        from_str=from_str,
        to_str=to_str,
    )
    # Severity mirrors _severity(): compilation→critical, runtime/timeout→high, else medium
    rows = fetchall(
        conn,
        f"""
        SELECT
          {bucket_expr} AS bucket,
          SUM(CASE WHEN LOWER(COALESCE(r.status,'')) IN ('failed','error')
                    AND (
                      LOWER(COALESCE(r.error_class,'')) = 'compilation'
                      OR LOWER(COALESCE(r.error_message,'')) LIKE '%%compilation%%'
                      OR LOWER(COALESCE(r.error_message,'')) LIKE '%%invalid identifier%%'
                    )
               THEN 1 ELSE 0 END) AS critical_cnt,
          SUM(CASE WHEN LOWER(COALESCE(r.status,'')) IN ('failed','error')
                    AND NOT (
                      LOWER(COALESCE(r.error_class,'')) = 'compilation'
                      OR LOWER(COALESCE(r.error_message,'')) LIKE '%%compilation%%'
                      OR LOWER(COALESCE(r.error_message,'')) LIKE '%%invalid identifier%%'
                    )
                    AND (
                      LOWER(COALESCE(r.error_class,'')) = 'runtime'
                      OR LOWER(COALESCE(r.error_message,'')) LIKE '%%timeout%%'
                    )
               THEN 1 ELSE 0 END) AS high_cnt,
          SUM(CASE WHEN LOWER(COALESCE(r.status,'')) IN ('failed','error')
                    AND NOT (
                      LOWER(COALESCE(r.error_class,'')) = 'compilation'
                      OR LOWER(COALESCE(r.error_message,'')) LIKE '%%compilation%%'
                      OR LOWER(COALESCE(r.error_message,'')) LIKE '%%invalid identifier%%'
                    )
                    AND NOT (
                      LOWER(COALESCE(r.error_class,'')) = 'runtime'
                      OR LOWER(COALESCE(r.error_message,'')) LIKE '%%timeout%%'
                    )
               THEN 1 ELSE 0 END) AS medium_cnt,
          SUM(CASE WHEN LOWER(COALESCE(r.status,'')) IN ('failed','error') THEN 1 ELSE 0 END) AS failed_cnt,
          SUM(CASE WHEN LOWER(COALESCE(r.status,'')) IN ('success','succeeded') THEN 1 ELSE 0 END) AS success_cnt
        FROM obs_pipeline_runs r
        {where}
        GROUP BY bucket
        ORDER BY bucket ASC
        """,
        params,
    )
    raw_labels = [json_val(r.get("bucket")) for r in rows]
    series_map = {
        "critical": [int(num(r.get("critical_cnt"))) for r in rows],
        "high": [int(num(r.get("high_cnt"))) for r in rows],
        "medium": [int(num(r.get("medium_cnt"))) for r in rows],
        "failed_runs": [int(num(r.get("failed_cnt"))) for r in rows],
        "success_runs": [int(num(r.get("success_cnt"))) for r in rows],
    }
    if rng is not None:
        labels, filled = zero_fill_series(raw_labels, series_map, rng, grain=grain)
    else:
        labels, filled = raw_labels, series_map
    return {
        "labels": labels,
        "critical": filled["critical"],
        "high": filled["high"],
        "medium": filled["medium"],
        "low": [0 for _ in labels],
        "failed_runs": filled["failed_runs"],
        "success_runs": filled["success_runs"],
        # Back-compat aliases (honest rename preferred — see failed_runs/success_runs)
        "open": filled["failed_runs"],
        "resolved": filled["success_runs"],
    }


def build_incidents_page(
    conn,
    *,
    preset: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    pipeline_name: Optional[str] = None,
    pipeline_id: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    rng = parse_range(preset, start_date, end_date, start_time, end_time)
    all_items = list_derived_incidents(
        conn,
        from_str=rng["from_str"],
        to_str=rng["to_str"],
        pipeline_name=pipeline_name,
        pipeline_id=pipeline_id,
        include_resolved=True,
    )
    prev_items = list_derived_incidents(
        conn,
        from_str=rng["prev_from_str"],
        to_str=rng["prev_to_str"],
        pipeline_name=pipeline_name,
        pipeline_id=pipeline_id,
        include_resolved=True,
    )

    def count_status(items: list[dict], key: str) -> int:
        return sum(1 for i in items if i.get("status") == key)

    def count_sev(items: list[dict], sev: str) -> int:
        return sum(1 for i in items if i.get("status") == "open" and i.get("severity") == sev)

    open_n = count_status(all_items, "open")
    resolved_n = count_status(all_items, "resolved")
    critical_n = count_sev(all_items, "critical")
    # triage not stored yet — always 0 with available true (stable)
    triage_n = 0

    prev_open = count_status(prev_items, "open")
    prev_resolved = count_status(prev_items, "resolved")
    prev_critical = count_sev(prev_items, "critical")

    status_filter = (status or "").strip().lower()
    items = all_items
    if status_filter:
        wanted = {s.strip() for s in status_filter.split(",") if s.strip()}
        items = [i for i in items if i.get("status") in wanted]

    # Prefer open first
    items = sorted(
        items,
        key=lambda i: (0 if i.get("status") == "open" else 1, i.get("opened_at") or ""),
        reverse=False,
    )
    open_first = [i for i in items if i.get("status") == "open"] + [
        i for i in items if i.get("status") != "open"
    ]
    items = open_first

    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 20), 100))
    start = (page - 1) * page_size
    page_items = items[start : start + page_size]

    series = incident_series(
        conn, rng["from_str"], rng["to_str"],
        pipeline_name=pipeline_name, pipeline_id=pipeline_id,
        rng=rng,
    )
    by_sev = {
        "critical": critical_n,
        "high": count_sev(all_items, "high"),
        "medium": count_sev(all_items, "medium"),
        "low": count_sev(all_items, "low"),
    }

    kpis = [
        make_kpi(
            id="open",
            title="Open Incidents",
            value=open_n,
            display=str(open_n),
            delta=apply_delta(delta_pct(float(open_n), float(prev_open)), rng),
            delta_label="vs previous period",
            tone="bad" if open_n else "ok",
        ),
        make_kpi(
            id="triage",
            title="In Triage",
            value=triage_n,
            display=str(triage_n),
            tone="neutral",
        ),
        make_kpi(
            id="critical",
            title="Critical",
            value=critical_n,
            display=str(critical_n),
            delta=apply_delta(delta_pct(float(critical_n), float(prev_critical)), rng),
            delta_label="vs previous period",
            tone="bad" if critical_n else "ok",
        ),
        make_kpi(
            id="resolved",
            title="Resolved",
            value=resolved_n,
            display=str(resolved_n),
            delta=apply_delta(delta_pct(float(resolved_n), float(prev_resolved)), rng),
            delta_label="vs previous period",
            tone="ok",
        ),
    ]

    return envelope(
        rng=rng,
        filters_applied={
            "pipeline_name": pipeline_name,
            "pipeline_id": pipeline_id,
            "status": status,
            "preset": rng.get("preset"),
        },
        kpis=kpis,
        series={
            "incidents_over_time": {
                "labels": series["labels"],
                "critical": series["critical"],
                "high": series["high"],
                "medium": series["medium"],
                "failed_runs": series["failed_runs"],
                "success_runs": series["success_runs"],
                "open": series["failed_runs"],
                "resolved": series["success_runs"],
            }
        },
        charts={
            "by_severity": [
                {"severity": k, "count": v, "pct": round(100 * v / open_n, 1) if open_n else 0}
                for k, v in by_sev.items()
            ]
        },
        items=page_items,
        incidents=page_items,
        page=page,
        page_size=page_size,
        total=len(items),
        summary={"open": open_n, "triage": triage_n, "critical": critical_n, "resolved": resolved_n},
        meta={
            "formula": (
                "Open incident = pipeline whose latest run failed (deduped by pipeline_id). "
                "Resolved = failure in range then later success. "
                "Chart series failed_runs/success_runs are run-status counts (not incident timelines)."
            )
        },
    )
