"""Overview page composer — KPIs, charts, health pillars, incidents, pipelines."""

from __future__ import annotations

from typing import Any, Optional

from application.src.api.schemas import make_kpi
from application.src.services.observability.filters import (
    age_label,
    apply_delta,
    build_run_where,
    chart_bucket_grain,
    delta_pct,
    envelope,
    fetchall,
    fetchone,
    format_duration,
    is_pipeline_operational,
    json_val,
    load_pipeline_activity,
    num,
    parse_range,
    pct,
    sql_time_bucket_expr,
    zero_fill_series,
)
from application.src.services.observability.freshness import (
    freshness_summary,
    load_pipeline_freshness,
)
from application.src.services.observability.incidents import (
    incident_series,
    list_derived_incidents,
)
from application.src.services.observability.quality import dimension_pillar_summary, quality_summary
from application.src.services.observability.schema_diff import schema_health_score
from application.src.services.observability.volume import volume_health_score


def _run_aggregates(conn, from_str: str, to_str: str, **filters) -> dict:
    where, params = build_run_where(
        alias="r",
        from_str=from_str,
        to_str=to_str,
        pipeline_name=filters.get("pipeline_name"),
        pipeline_id=filters.get("pipeline_id"),
        status=filters.get("status"),
        tool=filters.get("tool"),
    )
    return fetchone(
        conn,
        f"""
        SELECT
          COUNT(*) AS total_runs,
          SUM(CASE WHEN LOWER(COALESCE(status,'')) IN ('success','succeeded') THEN 1 ELSE 0 END) AS success_runs,
          SUM(CASE WHEN LOWER(COALESCE(status,'')) IN ('failed','error') THEN 1 ELSE 0 END) AS failed_runs,
          SUM(CASE WHEN LOWER(COALESCE(status,'')) = 'running' THEN 1 ELSE 0 END) AS running_runs,
          SUM(CASE WHEN LOWER(COALESCE(status,'')) = 'cancelled' THEN 1 ELSE 0 END) AS cancelled_runs,
          SUM(
            CASE WHEN LOWER(COALESCE(status,'')) IN
              ('success','succeeded','failed','error','cancelled') THEN 1 ELSE 0 END
          ) AS terminal_runs,
          AVG(duration) AS avg_duration
        FROM obs_pipeline_runs r
        {where}
        """,
        params,
    )


def _count_pipelines(conn, **filters) -> int:
    """Count registered pipelines, optionally filtered by id/name/tool."""
    clauses: list[str] = []
    params: list = []
    if filters.get("pipeline_name"):
        names = [n.strip() for n in str(filters["pipeline_name"]).split(",") if n.strip()]
        if names:
            ph = ",".join(["%s"] * len(names))
            clauses.append(f"pipeline_name IN ({ph})")
            params.extend(names)
    if filters.get("pipeline_id"):
        ids = [i.strip() for i in str(filters["pipeline_id"]).split(",") if i.strip()]
        if ids:
            ph = ",".join(["%s"] * len(ids))
            clauses.append(f"pipeline_id IN ({ph})")
            params.extend(ids)
    if filters.get("tool"):
        tools = [t.strip().lower() for t in str(filters["tool"]).split(",") if t.strip()]
        if tools:
            ph = ",".join(["%s"] * len(tools))
            clauses.append(
                f"(LOWER(COALESCE(etl_tool,'')) IN ({ph})"
                f" OR LOWER(COALESCE(source_tool,'')) IN ({ph})"
                f" OR LOWER(COALESCE(target_tool,'')) IN ({ph}))"
            )
            params.extend(tools)
            params.extend(tools)
            params.extend(tools)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    row = fetchone(conn, f"SELECT COUNT(*) AS n FROM obs_pipelines {where}", params)
    return int(num(row.get("n")))


def build_overview_charts(conn, rng: dict, **filters) -> dict:
    grain = chart_bucket_grain(rng)
    bucket_expr = sql_time_bucket_expr("r", grain)
    where, params = build_run_where(
        alias="r",
        from_str=rng["from_str"],
        to_str=rng["to_str"],
        pipeline_name=filters.get("pipeline_name"),
        pipeline_id=filters.get("pipeline_id"),
        status=filters.get("status"),
        tool=filters.get("tool"),
    )
    rows = fetchall(
        conn,
        f"""
        SELECT
          {bucket_expr} AS bucket,
          SUM(CASE WHEN LOWER(COALESCE(status,'')) IN ('success','succeeded') THEN 1 ELSE 0 END) AS success_cnt,
          SUM(CASE WHEN LOWER(COALESCE(status,'')) IN ('failed','error') THEN 1 ELSE 0 END) AS failed_cnt,
          SUM(CASE WHEN LOWER(COALESCE(status,'')) = 'running' THEN 1 ELSE 0 END) AS running_cnt,
          SUM(CASE WHEN LOWER(COALESCE(status,'')) = 'cancelled' THEN 1 ELSE 0 END) AS cancelled_cnt,
          SUM(
            CASE WHEN LOWER(COALESCE(status,'')) IN
              ('success','succeeded','failed','error','cancelled') THEN 1 ELSE 0 END
          ) AS terminal_cnt,
          COUNT(*) AS total_cnt
        FROM obs_pipeline_runs r
        {where}
        GROUP BY bucket
        ORDER BY bucket ASC
        """,
        params,
    )
    raw_labels = [json_val(r.get("bucket")) for r in rows]
    success = [int(num(r.get("success_cnt"))) for r in rows]
    failed = [int(num(r.get("failed_cnt"))) for r in rows]
    running = [int(num(r.get("running_cnt"))) for r in rows]
    cancelled = [int(num(r.get("cancelled_cnt"))) for r in rows]
    rates = [
        round(100.0 * s / t, 1) if t else 0.0
        for s, t in zip(success, [int(num(r.get("terminal_cnt"))) for r in rows])
    ]
    labels, filled = zero_fill_series(
        raw_labels,
        {
            "success": success,
            "failed": failed,
            "running": running,
            "cancelled": cancelled,
            "rates": rates,
        },
        rng,
        grain=grain,
    )
    inc = incident_series(
        conn,
        rng["from_str"],
        rng["to_str"],
        pipeline_name=filters.get("pipeline_name"),
        pipeline_id=filters.get("pipeline_id"),
        grain=grain,
        rng=rng,
    )
    return {
        "labels": labels,
        "bucket_grain": grain,
        "runs_over_time": {
            "success": filled["success"],
            "failed": filled["failed"],
            "running": filled["running"],
            "cancelled": filled["cancelled"],
        },
        "success_rate_over_time": filled["rates"],
        "incidents_over_time": {
            "labels": inc["labels"],
            "critical": inc["critical"],
            "high": inc["high"],
            "medium": inc["medium"],
            # Honest labels: failed/success run counts (not true open/resolved incidents)
            "failed_runs": inc["failed_runs"],
            "success_runs": inc["success_runs"],
            # Back-compat aliases (same series as failed_runs / success_runs)
            "open": inc["failed_runs"],
            "resolved": inc["success_runs"],
        },
        "meta": {
            "incidents_series_note": (
                "critical/high/medium = failed runs by severity; "
                "failed_runs/success_runs = run status counts (not deduped incidents)."
            ),
        },
    }


def build_overview_health(conn, rng: dict) -> dict[str, Any]:
    # Freshness as-of range end when a bounded range is provided
    as_of = rng.get("to") if str(rng.get("preset") or "").lower() != "all" else None
    fresh_rows = load_pipeline_freshness(conn, as_of=as_of)
    fresh_sum = freshness_summary(fresh_rows)
    vol = volume_health_score(
        conn, rng["from_str"], rng["to_str"], rng["prev_from_str"], rng["prev_to_str"]
    )
    sch = schema_health_score(conn)
    dq = quality_summary(conn, from_str=rng["from_str"], to_str=rng["to_str"])
    dq_score = dq.get("quality_score")
    consistency = dimension_pillar_summary(
        conn,
        from_str=rng["from_str"],
        to_str=rng["to_str"],
        dimensions=["accuracy"],
        score_mode="last_run",
    )
    consistency_score = consistency.get("quality_score")
    uniqueness = dimension_pillar_summary(
        conn,
        from_str=rng["from_str"],
        to_str=rng["to_str"],
        dimensions=["uniqueness"],
        score_mode="last_run",
    )
    uniqueness_score = uniqueness.get("quality_score")

    # Stable pillar keys (not UUIDs) — FE contracts depend on these ids
    pillars = [
        {
            "id": "freshness",
            "name": "Freshness",
            "score": fresh_sum.get("fresh_pct"),
            "display": f"{fresh_sum.get('fresh_pct')}%" if fresh_sum.get("fresh_pct") is not None else "N/A",
            "status": (
                "Good"
                if (fresh_sum.get("fresh_pct") or 0) >= 90
                else "Warning"
                if (fresh_sum.get("fresh_pct") or 0) >= 75
                else "Critical"
                if fresh_sum.get("fresh_pct") is not None
                else "N/A"
            ),
            "available": fresh_sum.get("fresh_pct") is not None,
            "change": None,
            "details": {**fresh_sum, "as_of": json_val(as_of) if as_of else "now"},
        },
        {
            "id": "volume",
            "name": "Volume",
            "score": vol.get("score"),
            "display": f"{vol.get('score')}%" if vol.get("score") is not None else "N/A",
            "status": (
                "Good"
                if (vol.get("score") or 0) >= 90
                else "Warning"
                if (vol.get("score") or 0) >= 75
                else "Critical"
                if vol.get("available")
                else "N/A"
            ),
            "available": bool(vol.get("available")),
            "change": None,
            "details": vol,
        },
        {
            "id": "data_quality",
            "name": "Data Quality",
            "score": dq_score,
            "display": f"{dq_score}%" if dq_score is not None else "N/A",
            "status": (
                "Good"
                if (dq_score or 0) >= 90
                else "Warning"
                if (dq_score or 0) >= 75
                else "Critical"
                if dq.get("available")
                else "N/A"
            ),
            "available": bool(dq.get("available")),
            "change": None,
            "details": dq,
        },
        {
            "id": "schema",
            "name": "Schema",
            "score": sch.get("score"),
            "display": f"{sch.get('score')}%" if sch.get("score") is not None else "N/A",
            "status": (
                "Good"
                if (sch.get("score") or 0) >= 90
                else "Warning"
                if (sch.get("score") or 0) >= 75
                else "Critical"
                if sch.get("available")
                else "N/A"
            ),
            "available": bool(sch.get("available")),
            "change": None,
            "details": sch,
        },
        {
            "id": "consistency",
            "name": "Consistency",
            "score": consistency_score,
            "display": f"{consistency_score}%" if consistency_score is not None else "N/A",
            "status": (
                "Good"
                if (consistency_score or 0) >= 90
                else "Warning"
                if (consistency_score or 0) >= 75
                else "Critical"
                if consistency.get("available")
                else "N/A"
            ),
            "available": bool(consistency.get("available")),
            "change": None,
            "details": consistency,
        },
        {
            "id": "uniqueness",
            "name": "Uniqueness",
            "score": uniqueness_score,
            "display": f"{uniqueness_score}%" if uniqueness_score is not None else "N/A",
            "status": (
                "Good"
                if (uniqueness_score or 0) >= 90
                else "Warning"
                if (uniqueness_score or 0) >= 75
                else "Critical"
                if uniqueness.get("available")
                else "N/A"
            ),
            "available": bool(uniqueness.get("available")),
            "change": None,
            "details": uniqueness,
        },
    ]
    return {"pillars": pillars}


def build_pipeline_monitoring(conn, rng: dict, **filters) -> list[dict]:
    where, params = build_run_where(
        alias="r",
        from_str=rng["from_str"],
        to_str=rng["to_str"],
        pipeline_name=filters.get("pipeline_name"),
        pipeline_id=filters.get("pipeline_id"),
        status=filters.get("status"),
        tool=filters.get("tool"),
    )
    # Aggregate runs in range, then left-join so registered pipelines still appear
    run_agg = f"""
        SELECT
          r.pipeline_id,
          r.pipeline_name,
          MAX(r.tool_name) AS tool_name,
          COUNT(*) AS total_runs,
          SUM(CASE WHEN LOWER(COALESCE(status,'')) IN ('success','succeeded') THEN 1 ELSE 0 END) AS success_runs,
          SUM(CASE WHEN LOWER(COALESCE(status,'')) IN ('failed','error') THEN 1 ELSE 0 END) AS failed_runs,
          SUM(
            CASE WHEN LOWER(COALESCE(status,'')) IN
              ('success','succeeded','failed','error','cancelled') THEN 1 ELSE 0 END
          ) AS terminal_runs,
          AVG(duration) AS avg_duration,
          MAX(COALESCE(end_time, start_time, created_at)) AS last_run_at,
          SUBSTRING_INDEX(
            GROUP_CONCAT(status ORDER BY COALESCE(end_time, start_time, created_at) DESC),
            ',', 1
          ) AS latest_status
        FROM obs_pipeline_runs r
        {where}
        GROUP BY r.pipeline_id, r.pipeline_name
    """
    pipe_where = []
    pipe_params: list = []
    if filters.get("pipeline_name"):
        names = [n.strip() for n in str(filters["pipeline_name"]).split(",") if n.strip()]
        if names:
            ph = ",".join(["%s"] * len(names))
            pipe_where.append(f"p.pipeline_name IN ({ph})")
            pipe_params.extend(names)
    if filters.get("pipeline_id"):
        ids = [i.strip() for i in str(filters["pipeline_id"]).split(",") if i.strip()]
        if ids:
            ph = ",".join(["%s"] * len(ids))
            pipe_where.append(f"p.pipeline_id IN ({ph})")
            pipe_params.extend(ids)
    if filters.get("tool"):
        tools = [t.strip().lower() for t in str(filters["tool"]).split(",") if t.strip()]
        if tools:
            ph = ",".join(["%s"] * len(tools))
            pipe_where.append(
                f"(LOWER(COALESCE(p.etl_tool,'')) IN ({ph})"
                f" OR LOWER(COALESCE(p.source_tool,'')) IN ({ph})"
                f" OR LOWER(COALESCE(p.target_tool,'')) IN ({ph}))"
            )
            pipe_params.extend(tools)
            pipe_params.extend(tools)
            pipe_params.extend(tools)
    pw = ("WHERE " + " AND ".join(pipe_where)) if pipe_where else ""

    rows = fetchall(
        conn,
        f"""
        SELECT
          p.pipeline_id,
          p.pipeline_name,
          p.source_tool,
          p.etl_tool,
          p.target_tool,
          p.is_active,
          a.tool_name,
          COALESCE(a.total_runs, 0) AS total_runs,
          COALESCE(a.success_runs, 0) AS success_runs,
          COALESCE(a.failed_runs, 0) AS failed_runs,
          COALESCE(a.terminal_runs, 0) AS terminal_runs,
          a.avg_duration,
          a.last_run_at,
          a.latest_status
        FROM obs_pipelines p
        LEFT JOIN ({run_agg}) a ON a.pipeline_id = p.pipeline_id
        {pw}
        ORDER BY COALESCE(a.last_run_at, p.updated_at) DESC
        """,
        list(params) + pipe_params,
    )
    # Global last activity (not range-scoped) drives is_active / activity
    activity_map = {
        a["pipeline_id"]: a for a in load_pipeline_activity(conn, persist=False)
    }
    open_inc = {
        i["pipeline_id"]
        for i in list_derived_incidents(conn, include_resolved=False)
        if i.get("status") == "open"
    }
    out = []
    for r in rows:
        pid = r.get("pipeline_id")
        total = num(r.get("total_runs"))
        succ = num(r.get("success_runs"))
        terminal = num(r.get("terminal_runs")) or total
        sr = pct(succ, terminal) if terminal else None
        st = str(r.get("latest_status") or ("N/A" if total == 0 else "unknown")).capitalize()
        if st == "N/a":
            st = "N/A"
        global_act = activity_map.get(pid) or {}
        global_last = global_act.get("last_run_at")
        operational = (
            bool(global_act.get("is_active"))
            if global_act
            else is_pipeline_operational(r.get("last_run_at"), r.get("latest_status"))
        )
        out.append(
            {
                "pipeline_id": pid,
                "pipeline_name": r.get("pipeline_name"),
                "source_tool": r.get("source_tool"),
                "etl_tool": r.get("tool_name") or r.get("etl_tool"),
                "target_tool": r.get("target_tool"),
                "status": st,
                "has_open_incident": pid in open_inc,
                "runs": int(total),
                "total_runs": int(total),
                "success_runs": int(succ),
                "failed_runs": int(num(r.get("failed_runs"))),
                "success_rate": f"{sr}%" if sr is not None else "N/A",
                "success_rate_pct": sr,
                "avg_duration": format_duration(r.get("avg_duration")),
                "avg_duration_seconds": num(r.get("avg_duration")) if r.get("avg_duration") is not None else None,
                "last_run": json_val(r.get("last_run_at")),
                "last_run_age": age_label(r.get("last_run_at")),
                "global_last_run": global_last,
                "is_active": operational,
                "activity": "Active" if operational else "Inactive",
                "is_sync_default": bool(r.get("is_active")),
            }
        )
    return out


def build_overview_kpis(conn, rng: dict, **filters) -> list[dict]:
    cur = _run_aggregates(conn, rng["from_str"], rng["to_str"], **filters)
    prev = _run_aggregates(conn, rng["prev_from_str"], rng["prev_to_str"], **filters)
    pipe_n = _count_pipelines(conn, **filters)
    total = num(cur.get("total_runs"))
    success = num(cur.get("success_runs"))
    failed = num(cur.get("failed_runs"))
    terminal = num(cur.get("terminal_runs"))
    rate = pct(success, terminal)  # exclude running from denominator
    avg_dur = num(cur.get("avg_duration")) if cur.get("avg_duration") is not None else None

    prev_total = num(prev.get("total_runs"))
    prev_success = num(prev.get("success_runs"))
    prev_failed = num(prev.get("failed_runs"))
    prev_terminal = num(prev.get("terminal_runs"))
    prev_rate = pct(prev_success, prev_terminal)
    prev_avg = num(prev.get("avg_duration")) if prev.get("avg_duration") is not None else None

    # Active incidents: same scope for value and delta — open incidents whose
    # opened_at falls in the window (global "currently open" filtered by opened_at).
    def _open_in_window(from_str: str, to_str: str) -> int:
        items = list_derived_incidents(
            conn,
            pipeline_name=filters.get("pipeline_name"),
            pipeline_id=filters.get("pipeline_id"),
            include_resolved=False,
        )
        n = 0
        for i in items:
            if i.get("status") != "open":
                continue
            opened = i.get("opened_at")
            if not opened:
                n += 1
                continue
            # Compare as strings YYYY-MM-DD HH:MM:SS
            opened_s = str(opened).replace("T", " ")[:19]
            if from_str <= opened_s <= to_str:
                n += 1
        return n

    # For "currently open" KPI: count all open now (with pipeline filters).
    # Delta compares open-with-opened_at-in-range vs previous equal window.
    open_now = [
        i
        for i in list_derived_incidents(
            conn,
            pipeline_name=filters.get("pipeline_name"),
            pipeline_id=filters.get("pipeline_id"),
            include_resolved=False,
        )
        if i.get("status") == "open"
    ]
    # Prefer range-scoped counts so value/delta share the same definition
    cur_open_n = _open_in_window(rng["from_str"], rng["to_str"])
    prev_open_n = _open_in_window(rng["prev_from_str"], rng["prev_to_str"])
    # When range is "all", opened_at filter is vacuous — use live open count
    if str(rng.get("preset") or "").lower() == "all":
        cur_open_n = len(open_now)
        prev_open_n = cur_open_n

    return [
        make_kpi(
            id="total_pipelines",
            title="Total Pipelines",
            value=pipe_n,
            display=str(pipe_n),
        ),
        make_kpi(
            id="success_rate",
            title="Successful Runs",
            value=rate,
            display=f"{rate}%" if rate is not None else "N/A",
            delta=apply_delta(
                round(rate - prev_rate, 1) if rate is not None and prev_rate is not None else None,
                rng,
            ),
            delta_label="vs previous period",
            available=rate is not None,
            tone="ok" if (rate or 0) >= 80 else "warn",
        ),
        make_kpi(
            id="failed_runs",
            title="Failed Runs",
            value=int(failed),
            display=str(int(failed)),
            delta=apply_delta(delta_pct(failed, prev_failed), rng),
            delta_label="vs previous period",
            tone="bad" if failed else "ok",
        ),
        make_kpi(
            id="avg_duration",
            title="Avg Pipeline Duration",
            value=avg_dur,
            display=format_duration(avg_dur) or "N/A",
            delta=apply_delta(
                delta_pct(avg_dur, prev_avg) if avg_dur is not None else None,
                rng,
            ),
            delta_label="vs previous period",
            available=avg_dur is not None,
        ),
        make_kpi(
            id="active_incidents",
            title="Active Incidents",
            value=cur_open_n,
            display=str(cur_open_n),
            delta=apply_delta(delta_pct(float(cur_open_n), float(prev_open_n)), rng),
            delta_label="vs previous period",
            tone="bad" if cur_open_n else "ok",
        ),
        make_kpi(
            id="total_runs",
            title="Runs",
            value=int(total),
            display=str(int(total)),
            delta=apply_delta(delta_pct(total, prev_total), rng),
            delta_label="vs previous period",
        ),
    ]


def build_overview(
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
    tool: Optional[str] = None,
    incident_limit: int = 10,
) -> dict[str, Any]:
    rng = parse_range(preset, start_date, end_date, start_time, end_time)
    filters = dict(
        pipeline_name=pipeline_name,
        pipeline_id=pipeline_id,
        status=status,
        tool=tool,
    )
    kpis = build_overview_kpis(conn, rng, **filters)
    charts = build_overview_charts(conn, rng, **filters)
    health = build_overview_health(conn, rng)
    incidents = [
        i
        for i in list_derived_incidents(
            conn,
            from_str=rng["from_str"],
            to_str=rng["to_str"],
            pipeline_name=pipeline_name,
            pipeline_id=pipeline_id,
            include_resolved=False,
        )
        if i.get("status") == "open"
    ][: max(1, int(incident_limit or 10))]
    pipelines = build_pipeline_monitoring(conn, rng, **filters)
    cur = _run_aggregates(conn, rng["from_str"], rng["to_str"], **filters)

    return envelope(
        rng=rng,
        filters_applied={**filters, "preset": rng.get("preset")},
        kpis=kpis,
        series={
            "runs_over_time": charts["runs_over_time"],
            "success_rate_over_time": charts["success_rate_over_time"],
            "incidents_over_time": charts["incidents_over_time"],
        },
        charts=charts,
        items=pipelines,
        pipelines=pipelines,
        incidents=incidents,
        pillars=health["pillars"],
        health=health["pillars"],
        summary={
            "total_runs": int(num(cur.get("total_runs"))),
            "success_runs": int(num(cur.get("success_runs"))),
            "failed_runs": int(num(cur.get("failed_runs"))),
            "running_runs": int(num(cur.get("running_runs"))),
            "terminal_runs": int(num(cur.get("terminal_runs"))),
            "success_rate_pct": pct(num(cur.get("success_runs")), num(cur.get("terminal_runs"))),
        },
    )


def build_pipelines_list(
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
    tool: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    rng = parse_range(preset, start_date, end_date, start_time, end_time)
    filters = dict(
        pipeline_name=pipeline_name,
        pipeline_id=pipeline_id,
        status=status,
        tool=tool,
    )
    items = build_pipeline_monitoring(conn, rng, **filters)
    kpis = build_overview_kpis(conn, rng, **filters)

    # Filter by latest status if requested
    if status:
        wanted = {s.strip().lower() for s in status.split(",") if s.strip()}
        items = [i for i in items if str(i.get("status") or "").lower() in wanted]

    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 20), 100))
    start = (page - 1) * page_size
    return envelope(
        rng=rng,
        filters_applied={**filters, "preset": rng.get("preset")},
        kpis=kpis,
        items=items[start : start + page_size],
        pipelines=items[start : start + page_size],
        page=page,
        page_size=page_size,
        total=len(items),
    )


def build_pipeline_detail(conn, pipeline_id: str) -> dict[str, Any]:
    """Full pipeline card: source/etl/target ids, name, activity, and last run."""
    from application.src.services.observability.freshness import load_pipeline_freshness
    from application.src.services.observability.lineage import _assets_for_run, _latest_run

    pipe = fetchone(conn, "SELECT * FROM obs_pipelines WHERE pipeline_id = %s", (pipeline_id,))
    if not pipe:
        return {"ok": False, "error": "pipeline_not_found", "pipeline_id": pipeline_id}

    latest = _latest_run(conn, pipeline_id)
    assets = _assets_for_run(conn, latest.get("id"))
    fr = load_pipeline_freshness(conn, pipeline_id=pipeline_id)
    fr0 = fr[0] if fr else {}
    operational = is_pipeline_operational(latest.get("end_time") or latest.get("start_time") or latest.get("created_at"), latest.get("status"))

    last_run = None
    if latest:
        last_run = {
            "run_id": latest.get("id"),
            "status": latest.get("status"),
            "start_time": json_val(latest.get("start_time")),
            "end_time": json_val(latest.get("end_time")),
            "duration_seconds": num(latest.get("duration")) if latest.get("duration") is not None else None,
            "duration": format_duration(latest.get("duration")),
            "tool_name": latest.get("tool_name"),
            "rows_read": latest.get("rows_read"),
            "rows_written": latest.get("rows_written"),
            "error_class": latest.get("error_class"),
            "failed_message": latest.get("failed_message"),
            "failure_stage": latest.get("failure_stage"),
        }

    sources = [
        {
            "asset_role": a.get("asset_role"),
            "database_name": a.get("database_name"),
            "schema_name": a.get("schema_name"),
            "object_name": a.get("object_name"),
            "row_count": a.get("row_count"),
            "last_updated_at": json_val(a.get("last_updated_at")),
        }
        for a in assets
        if str(a.get("asset_role") or "").upper() == "SOURCE"
    ]
    targets = [
        {
            "asset_role": a.get("asset_role"),
            "database_name": a.get("database_name"),
            "schema_name": a.get("schema_name"),
            "object_name": a.get("object_name"),
            "row_count": a.get("row_count"),
            "last_updated_at": json_val(a.get("last_updated_at")),
        }
        for a in assets
        if str(a.get("asset_role") or "").upper() == "TARGET"
    ]

    rng = parse_range("all", None, None, None, None)
    return envelope(
        rng=rng,
        filters_applied={"pipeline_id": pipeline_id},
        items=[],
        pipeline={
            "pipeline_id": pipe.get("pipeline_id"),
            "pipeline_name": pipe.get("pipeline_name"),
            "description": pipe.get("description"),
            "tenant_id": pipe.get("tenant_id"),
            "is_active": operational,
            "activity": "Active" if operational else "Inactive",
            "is_sync_default": bool(pipe.get("is_active")),
            "source": {
                "tool": pipe.get("source_tool"),
                "instance_id": pipe.get("source_instance_id"),
                "schema": pipe.get("source_schema"),
            },
            "etl": {
                "tool": pipe.get("etl_tool"),
                "instance_id": pipe.get("etl_instance_id"),
            },
            "target": {
                "tool": pipe.get("target_tool"),
                "instance_id": pipe.get("target_instance_id"),
                "schema": pipe.get("target_schema"),
            },
            "created_at": json_val(pipe.get("created_at")),
            "updated_at": json_val(pipe.get("updated_at")),
        },
        last_run=last_run,
        source_assets=sources,
        target_assets=targets,
        freshness=fr0,
        summary={
            "pipeline_id": pipe.get("pipeline_id"),
            "pipeline_name": pipe.get("pipeline_name"),
            "activity": "Active" if operational else "Inactive",
            "last_run_status": (last_run or {}).get("status"),
            "last_run_at": (last_run or {}).get("end_time") or (last_run or {}).get("start_time"),
            "source_tool": pipe.get("source_tool"),
            "etl_tool": pipe.get("etl_tool"),
            "target_tool": pipe.get("target_tool"),
        },
    )


def build_pipeline_runs(
    conn,
    pipeline_id: str,
    *,
    preset: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    status: Optional[str] = None,
    tool: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    rng = parse_range(preset or "all", start_date, end_date, start_time, end_time)
    where, params = build_run_where(
        alias="r",
        pipeline_id=pipeline_id,
        status=status,
        tool=tool,
        from_str=None if rng.get("preset") == "all" else rng["from_str"],
        to_str=None if rng.get("preset") == "all" else rng["to_str"],
    )
    count = fetchone(conn, f"SELECT COUNT(*) AS n FROM obs_pipeline_runs r {where}", params)
    total = int(num(count.get("n")))
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 50), 200))
    offset = (page - 1) * page_size
    runs = fetchall(
        conn,
        f"""
        SELECT
          id, pipeline_id, pipeline_name, status, tool_name,
          start_time, end_time, duration, rows_read, rows_written, rows_added,
          failure_stage, failed_node, error_class, error_message,
          execution_mode, triggered_by, created_at
        FROM obs_pipeline_runs r
        {where}
        ORDER BY COALESCE(end_time, start_time, created_at) DESC
        LIMIT %s OFFSET %s
        """,
        list(params) + [page_size, offset],
    )
    items = []
    for r in runs:
        assets = fetchall(
            conn,
            "SELECT asset_role, dataset_id, object_name, row_count, size_bytes FROM obs_run_assets WHERE run_id = %s",
            (str(r["id"]),),
        )
        items.append(
            {
                **{k: json_val(v) for k, v in r.items()},
                "duration_display": format_duration(r.get("duration")),
                "assets": [{k: json_val(v) for k, v in a.items()} for a in assets],
            }
        )
    return envelope(
        rng=rng,
        filters_applied={"pipeline_id": pipeline_id, "status": status, "tool": tool},
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        meta={"pipeline_id": pipeline_id},
    )
