"""Data quality page and summary from obs_check_results (monitors + dbt tests)."""

from __future__ import annotations

import json
from typing import Any, Optional

from application.src.api.schemas import make_kpi
from application.src.services.observability.filters import (
    envelope,
    fetchall,
    json_val,
    num,
    parse_range,
    pct,
    split_csv,
)


def normalize_dataset_id(value: Any) -> str:
    """Uppercase canonical dataset key (DB.SCHEMA.TABLE)."""
    text = str(value or "").strip().upper()
    if not text:
        return ""
    return text


def is_dbt_check(monitor_id: Any) -> bool:
    return str(monitor_id or "").startswith("dbt-run:")


def infer_dimension(*, message: Any = None, test_id: Any = None, monitor_kind: Any = None) -> str | None:
    """Heuristic MC-style dimension from dbt test name or monitor kind."""
    kind = str(monitor_kind or "").lower()
    if kind == "freshness":
        return "timeliness"
    if kind == "volume_drop":
        return "completeness"
    if kind in {"null_check", "null_pct"}:
        return "completeness"
    if kind in {"unique_check", "unique_violation", "duplicate_check", "duplicate_count"}:
        return "uniqueness"
    if kind == "custom_sql":
        return "validity"

    text = f"{message or ''} {test_id or ''}".lower()
    if "not_null" in text or "not null" in text:
        return "completeness"
    if "unique" in text:
        return "uniqueness"
    if "relationship" in text:
        return "accuracy"
    if "accepted_values" in text or "accepted values" in text:
        return "validity"
    if "freshness" in text or "stale" in text:
        return "timeliness"
    if "volume" in text:
        return "completeness"
    return None


def dataset_status_key(*, passed: int, warn: int, failed: int) -> str:
    if failed > 0:
        return "bad"
    if warn > 0:
        return "degraded"
    if passed > 0:
        return "good"
    return "unknown"


def _status_bucket(status: Any) -> str:
    st = str(status or "").lower()
    if st in {"pass", "passed", "success", "ok"}:
        return "passed"
    if st in {"warn", "warning"}:
        return "warn"
    return "failed"


def _parse_observed(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        return json.loads(raw) if isinstance(raw, str) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _row_dataset_id(row: dict) -> str:
    obs = _parse_observed(row.get("observed_json"))
    return normalize_dataset_id(obs.get("dataset_id") or obs.get("relation_name"))


def _row_dimension(row: dict) -> str | None:
    obs = _parse_observed(row.get("observed_json"))
    if obs.get("dimension"):
        return str(obs["dimension"])
    if row.get("monitor_dimension"):
        return str(row["monitor_dimension"])
    return infer_dimension(
        message=row.get("message"),
        test_id=obs.get("test_id"),
        monitor_kind=obs.get("monitor_kind") or row.get("monitor_kind"),
    )


def _row_tags(row: dict) -> list[str]:
    obs = _parse_observed(row.get("observed_json"))
    raw = obs.get("tags") or obs.get("tags_json") or []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = [t.strip() for t in raw.split(",") if t.strip()]
    if not raw and row.get("monitor_tags_json"):
        try:
            mt = json.loads(row["monitor_tags_json"])
            if isinstance(mt, list):
                raw = mt
        except (json.JSONDecodeError, TypeError):
            pass
    return [str(t) for t in raw if t]


def _check_where(
    *,
    from_str: str | None,
    to_str: str | None,
    pipeline_name: Optional[str] = None,
    pipeline_id: Optional[str] = None,
    source: Optional[str] = None,
    dataset_id: Optional[str] = None,
    tag: Optional[str] = None,
    dimension: Optional[str] = None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    if from_str:
        clauses.append("c.checked_at >= %s")
        params.append(from_str)
    if to_str:
        clauses.append("c.checked_at <= %s")
        params.append(to_str)

    names = split_csv(pipeline_name)
    if names:
        ph = ",".join(["%s"] * len(names))
        clauses.append(f"p.pipeline_name IN ({ph})")
        params.extend(names)

    ids = split_csv(pipeline_id)
    if ids:
        ph = ",".join(["%s"] * len(ids))
        clauses.append(f"c.pipeline_id IN ({ph})")
        params.extend(ids)

    src = (source or "all").lower()
    if src == "dbt":
        clauses.append("c.monitor_id LIKE 'dbt-run:%%'")
    elif src == "monitor":
        clauses.append("c.monitor_id NOT LIKE 'dbt-run:%%'")

    ds = normalize_dataset_id(dataset_id)
    if ds:
        clauses.append(
            "(UPPER(JSON_UNQUOTE(JSON_EXTRACT(c.observed_json, '$.dataset_id'))) = %s "
            "OR UPPER(JSON_UNQUOTE(JSON_EXTRACT(c.observed_json, '$.relation_name'))) = %s)"
        )
        params.extend([ds, ds])

    dim = (dimension or "").strip().lower()
    if dim:
        clauses.append(
            "(LOWER(JSON_UNQUOTE(JSON_EXTRACT(c.observed_json, '$.dimension'))) = %s "
            "OR LOWER(m.dimension) = %s)"
        )
        params.extend([dim, dim])

    tag_val = (tag or "").strip()
    if tag_val:
        clauses.append(
            "(JSON_SEARCH(c.observed_json, 'one', %s, NULL, '$.tags') IS NOT NULL "
            "OR JSON_SEARCH(m.tags_json, 'one', %s) IS NOT NULL "
            "OR c.observed_json LIKE %s OR m.tags_json LIKE %s)"
        )
        like = f"%{tag_val}%"
        params.extend([tag_val, tag_val, like, like])

    if not clauses:
        return "", []
    return "WHERE " + " AND ".join(clauses), params


def _fetch_check_rows(
    conn,
    *,
    from_str: str | None = None,
    to_str: str | None = None,
    pipeline_name: Optional[str] = None,
    pipeline_id: Optional[str] = None,
    source: Optional[str] = None,
    dataset_id: Optional[str] = None,
    tag: Optional[str] = None,
    dimension: Optional[str] = None,
    limit: int = 5000,
) -> list[dict]:
    where, params = _check_where(
        from_str=from_str,
        to_str=to_str,
        pipeline_name=pipeline_name,
        pipeline_id=pipeline_id,
        source=source,
        dataset_id=dataset_id,
        tag=tag,
        dimension=dimension,
    )
    return fetchall(
        conn,
        f"""
        SELECT c.status, c.severity, c.message, c.observed_json, c.monitor_id,
               c.pipeline_id, c.check_id, c.checked_at, p.pipeline_name,
               m.dimension AS monitor_dimension, m.tags_json AS monitor_tags_json,
               m.monitor_kind, m.monitor_type
        FROM obs_check_results c
        LEFT JOIN obs_pipelines p ON p.pipeline_id = c.pipeline_id
        LEFT JOIN obs_monitors m ON m.monitor_id = c.monitor_id
        {where}
        ORDER BY c.checked_at DESC
        LIMIT {int(limit)}
        """,
        params,
    )


def _dedupe_last_run(rows: list[dict], *, source: str = "all") -> list[dict]:
    """Keep latest-run dbt checks and latest result per operational monitor."""
    if not rows:
        return []

    src = (source or "all").lower()
    dbt_rows = [r for r in rows if is_dbt_check(r.get("monitor_id"))]
    mon_rows = [r for r in rows if not is_dbt_check(r.get("monitor_id"))]

    out: list[dict] = []

    if src in {"all", "dbt"} and dbt_rows:
        latest_by_pipe: dict[str, tuple[str, Any]] = {}
        for r in dbt_rows:
            pid = str(r.get("pipeline_id") or "")
            mid = str(r.get("monitor_id") or "")
            checked = r.get("checked_at")
            prev = latest_by_pipe.get(pid)
            if prev is None or (checked and checked > prev[1]):
                latest_by_pipe[pid] = (mid, checked)
        keep_mids = {v[0] for v in latest_by_pipe.values()}
        out.extend(r for r in dbt_rows if str(r.get("monitor_id") or "") in keep_mids)

    if src in {"all", "monitor"} and mon_rows:
        latest_by_mon: dict[str, tuple[dict, Any]] = {}
        for r in mon_rows:
            mid = str(r.get("monitor_id") or "")
            checked = r.get("checked_at")
            prev = latest_by_mon.get(mid)
            if prev is None or (checked and checked > prev[1]):
                latest_by_mon[mid] = (r, checked)
        out.extend(v[0] for v in latest_by_mon.values())

    return out


def _dedupe_time_window(rows: list[dict], *, source: str = "all") -> list[dict]:
    """In a time window, keep all dbt checks but only the latest result per monitor/rule."""
    if not rows:
        return []

    src = (source or "all").lower()
    dbt_rows = [r for r in rows if is_dbt_check(r.get("monitor_id"))]
    mon_rows = [r for r in rows if not is_dbt_check(r.get("monitor_id"))]
    out: list[dict] = []

    if src in {"all", "dbt"}:
        out.extend(dbt_rows)

    if src in {"all", "monitor"} and mon_rows:
        latest_by_mon: dict[str, tuple[dict, Any]] = {}
        for r in mon_rows:
            mid = str(r.get("monitor_id") or "")
            checked = r.get("checked_at")
            prev = latest_by_mon.get(mid)
            if prev is None or (checked and checked > prev[1]):
                latest_by_mon[mid] = (r, checked)
        out.extend(v[0] for v in latest_by_mon.values())

    return out


def _summarize_rows(rows: list[dict]) -> dict[str, Any]:
    if not rows:
        return {
            "available": False,
            "checks_run": 0,
            "passed": 0,
            "warn": 0,
            "failed": 0,
            "quality_score": None,
            "pass_rate_pct": None,
            "dbt_checks": 0,
            "monitor_checks": 0,
            "status_key": "unknown",
        }

    passed = warn = failed = 0
    dbt_checks = monitor_checks = 0
    dimensions: dict[str, dict[str, int]] = {}

    for r in rows:
        bucket = _status_bucket(r.get("status"))
        mid = str(r.get("monitor_id") or "")
        if is_dbt_check(mid):
            dbt_checks += 1
        else:
            monitor_checks += 1
        if bucket == "passed":
            passed += 1
        elif bucket == "warn":
            warn += 1
        else:
            failed += 1

        dim = _row_dimension(r) or "other"
        slot = dimensions.setdefault(dim, {"passed": 0, "warn": 0, "failed": 0})
        slot[bucket if bucket != "passed" else "passed"] += 1

    total = passed + warn + failed
    score = pct(passed, total)
    return {
        "available": True,
        "checks_run": total,
        "passed": passed,
        "warn": warn,
        "failed": failed,
        "quality_score": score,
        "pass_rate_pct": score,
        "dbt_checks": dbt_checks,
        "monitor_checks": monitor_checks,
        "status_key": dataset_status_key(passed=passed, warn=warn, failed=failed),
        "by_dimension": dimensions,
    }


def quality_summary(
    conn,
    *,
    from_str: str | None = None,
    to_str: str | None = None,
    pipeline_name: Optional[str] = None,
    pipeline_id: Optional[str] = None,
    score_mode: str = "time_window",
    source: str = "all",
    dataset_id: Optional[str] = None,
    tag: Optional[str] = None,
    dimension: Optional[str] = None,
) -> dict[str, Any]:
    rows = _fetch_check_rows(
        conn,
        from_str=from_str,
        to_str=to_str,
        pipeline_name=pipeline_name,
        pipeline_id=pipeline_id,
        source=source,
        dataset_id=dataset_id,
        tag=tag,
        dimension=dimension,
    )
    if score_mode == "last_run":
        rows = _dedupe_last_run(rows, source=source)
    else:
        rows = _dedupe_time_window(rows, source=source)
    summary = _summarize_rows(rows)
    summary["score_mode"] = score_mode
    summary["source"] = source
    if dataset_id:
        summary["dataset_id"] = normalize_dataset_id(dataset_id)
    return summary


def quality_summary_by_dataset(
    conn,
    *,
    pipeline_name: Optional[str] = None,
    pipeline_id: Optional[str] = None,
    dataset_id: Optional[str] = None,
    score_mode: str = "last_run",
    tag: Optional[str] = None,
    dimension: Optional[str] = None,
) -> dict[str, Any]:
    """Per-dataset DQ from latest-run dbt checks grouped by relation_name/dataset_id."""
    rows = _fetch_check_rows(
        conn,
        pipeline_name=pipeline_name,
        pipeline_id=pipeline_id,
        source="dbt",
        tag=tag,
        dimension=dimension,
        limit=10000,
    )
    if score_mode == "last_run":
        rows = _dedupe_last_run(rows, source="dbt")

    by_ds: dict[str, list[dict]] = {}
    for r in rows:
        ds = _row_dataset_id(r)
        if not ds:
            continue
        by_ds.setdefault(ds, []).append(r)

    target = normalize_dataset_id(dataset_id) if dataset_id else None
    datasets: list[dict[str, Any]] = []
    for ds, ds_rows in sorted(by_ds.items()):
        if target and ds != target:
            continue
        summary = _summarize_rows(ds_rows)
        alerting = [
            {
                "check_id": r.get("check_id"),
                "status": _status_bucket(r.get("status")),
                "message": r.get("message"),
                "test_id": _parse_observed(r.get("observed_json")).get("test_id"),
                "dimension": _row_dimension(r),
            }
            for r in ds_rows
            if _status_bucket(r.get("status")) in {"warn", "failed"}
        ]
        datasets.append(
            {
                "dataset_id": ds,
                **summary,
                "alerting_checks": alerting,
            }
        )

    if target:
        if not datasets:
            return {
                "available": False,
                "dataset_id": target,
                "checks_run": 0,
                "passed": 0,
                "warn": 0,
                "failed": 0,
                "quality_score": None,
                "status_key": "unknown",
                "alerting_checks": [],
            }
        return datasets[0]

    return {"available": bool(datasets), "datasets": datasets, "total": len(datasets)}


def dataset_dq_map(
    conn,
    *,
    pipeline_id: str,
    dataset_ids: list[str] | None = None,
    score_mode: str = "last_run",
) -> dict[str, dict[str, Any]]:
    """Batch per-dataset DQ for lineage / asset enrichment."""
    result = quality_summary_by_dataset(
        conn,
        pipeline_id=pipeline_id,
        score_mode=score_mode,
    )
    rows = result.get("datasets") or []
    wanted = {normalize_dataset_id(d) for d in (dataset_ids or []) if d}
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        ds = str(row.get("dataset_id") or "")
        if not ds:
            continue
        if wanted and ds not in wanted:
            continue
        score = row.get("quality_score")
        status = row.get("status_key") or "unknown"
        failed = int(row.get("failed") or 0)
        warn = int(row.get("warn") or 0)
        if status == "good":
            display = "OK"
        elif status == "degraded":
            display = f"{warn} warning(s)"
        elif status == "bad":
            display = f"{failed} failed test(s)"
        else:
            display = "N/A"
        out[ds] = {
            **row,
            "data_quality_display": display,
        }
    return out


def dimension_pillar_summary(
    conn,
    *,
    from_str: str | None = None,
    to_str: str | None = None,
    pipeline_name: Optional[str] = None,
    pipeline_id: Optional[str] = None,
    dimensions: list[str],
    score_mode: str = "last_run",
    source: str = "all",
) -> dict[str, Any]:
    """Aggregate DQ score for checks matching one or more MC-style dimensions."""
    dims = {d.strip().lower() for d in dimensions if d and str(d).strip()}
    rows = _fetch_check_rows(
        conn,
        from_str=from_str,
        to_str=to_str,
        pipeline_name=pipeline_name,
        pipeline_id=pipeline_id,
        source=source,
        limit=10000,
    )
    if score_mode == "last_run":
        rows = _dedupe_last_run(rows, source=source)
    else:
        rows = _dedupe_time_window(rows, source=source)
    filtered = [r for r in rows if (_row_dimension(r) or "").lower() in dims]
    summary = _summarize_rows(filtered)
    summary["dimensions"] = sorted(dims)
    return summary


def quality_score_over_time(
    conn,
    *,
    from_str: str | None,
    to_str: str | None,
    pipeline_name: Optional[str] = None,
    pipeline_id: Optional[str] = None,
    source: str = "all",
) -> list[dict[str, Any]]:
    """Daily DQ pass rate from obs_dq_daily_rollups (fallback: aggregate check_results)."""
    clauses = ["bucket_date IS NOT NULL"]
    params: list[Any] = []
    if from_str:
        clauses.append("bucket_date >= DATE(%s)")
        params.append(from_str)
    if to_str:
        clauses.append("bucket_date <= DATE(%s)")
        params.append(to_str)
    ids = split_csv(pipeline_id)
    if ids:
        ph = ",".join(["%s"] * len(ids))
        clauses.append(f"pipeline_id IN ({ph})")
        params.extend(ids)
    src = (source or "all").lower()
    if src in {"dbt", "monitor"}:
        clauses.append("source_type = %s")
        params.append(src)
    where = "WHERE " + " AND ".join(clauses)

    rows = fetchall(
        conn,
        f"""
        SELECT bucket_date,
               SUM(passed) AS passed,
               SUM(warn) AS warn,
               SUM(failed) AS failed,
               SUM(total) AS total
        FROM obs_dq_daily_rollups
        {where}
        GROUP BY bucket_date
        ORDER BY bucket_date ASC
        LIMIT 366
        """,
        params,
    )
    if rows:
        series: list[dict[str, Any]] = []
        for r in rows:
            passed = int(num(r.get("passed")))
            total = int(num(r.get("total")))
            series.append(
                {
                    "date": json_val(r.get("bucket_date")),
                    "passed": passed,
                    "warn": int(num(r.get("warn"))),
                    "failed": int(num(r.get("failed"))),
                    "total": total,
                    "quality_score": pct(passed, total),
                }
            )
        return series

    check_rows = _fetch_check_rows(
        conn,
        from_str=from_str,
        to_str=to_str,
        pipeline_name=pipeline_name,
        pipeline_id=pipeline_id,
        source=source,
        limit=20000,
    )
    by_day: dict[str, dict[str, int]] = {}
    for r in check_rows:
        day = str(json_val(r.get("checked_at")) or "")[:10]
        if not day:
            continue
        slot = by_day.setdefault(day, {"passed": 0, "warn": 0, "failed": 0})
        bucket = _status_bucket(r.get("status"))
        slot[bucket if bucket != "passed" else "passed"] += 1
    return [
        {
            "date": day,
            "passed": v["passed"],
            "warn": v["warn"],
            "failed": v["failed"],
            "total": v["passed"] + v["warn"] + v["failed"],
            "quality_score": pct(v["passed"], v["passed"] + v["warn"] + v["failed"]),
        }
        for day, v in sorted(by_day.items())
    ]


def failed_test_count_by_pipeline(conn, pipeline_ids: list[str]) -> dict[str, int]:
    if not pipeline_ids:
        return {}
    ph = ",".join(["%s"] * len(pipeline_ids))
    rows = fetchall(
        conn,
        f"""
        SELECT c.pipeline_id, COUNT(*) AS n
        FROM obs_check_results c
        WHERE c.pipeline_id IN ({ph})
          AND LOWER(COALESCE(c.status, '')) NOT IN ('pass', 'passed', 'success', 'ok', 'warn', 'warning')
          AND c.monitor_id LIKE 'dbt-run:%%'
        GROUP BY c.pipeline_id
        """,
        pipeline_ids,
    )
    return {str(r["pipeline_id"]): int(num(r.get("n"))) for r in rows}


def build_quality_page(
    conn,
    *,
    preset: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    pipeline_name: Optional[str] = None,
    pipeline_id: Optional[str] = None,
    score_mode: str = "time_window",
    source: str = "all",
    dataset_id: Optional[str] = None,
    tag: Optional[str] = None,
    dimension: Optional[str] = None,
) -> dict[str, Any]:
    rng = parse_range(preset, start_date, end_date, start_time, end_time)
    ds_norm = normalize_dataset_id(dataset_id) if dataset_id else None

    if ds_norm:
        summary = quality_summary_by_dataset(
            conn,
            pipeline_name=pipeline_name,
            pipeline_id=pipeline_id,
            dataset_id=ds_norm,
            score_mode="last_run" if score_mode == "time_window" else score_mode,
            tag=tag,
            dimension=dimension,
        )
    else:
        summary = quality_summary(
            conn,
            from_str=rng.get("from_str"),
            to_str=rng.get("to_str"),
            pipeline_name=pipeline_name,
            pipeline_id=pipeline_id,
            score_mode=score_mode,
            source=source,
            tag=tag,
            dimension=dimension,
        )

    where, params = _check_where(
        from_str=rng.get("from_str"),
        to_str=rng.get("to_str"),
        pipeline_name=pipeline_name,
        pipeline_id=pipeline_id,
        source=source,
        dataset_id=ds_norm,
        tag=tag,
        dimension=dimension,
    )
    rows = fetchall(
        conn,
        f"""
        SELECT c.check_id, c.monitor_id, c.pipeline_id, c.status, c.severity,
               c.message, c.observed_json, c.checked_at, p.pipeline_name,
               m.dimension AS monitor_dimension, m.tags_json AS monitor_tags_json,
               m.monitor_kind, m.monitor_type
        FROM obs_check_results c
        LEFT JOIN obs_pipelines p ON p.pipeline_id = c.pipeline_id
        LEFT JOIN obs_monitors m ON m.monitor_id = c.monitor_id
        {where}
        ORDER BY c.checked_at DESC
        LIMIT 500
        """,
        params,
    )
    if score_mode == "last_run":
        rows = _dedupe_last_run(rows, source=source)
    else:
        rows = _dedupe_time_window(rows, source=source)

    items: list[dict] = []
    for r in rows:
        obs = _parse_observed(r.get("observed_json"))
        st = str(r.get("status") or "").lower()
        items.append(
            {
                "check_id": r.get("check_id"),
                "test_id": obs.get("test_id") or r.get("check_id"),
                "monitor_id": r.get("monitor_id"),
                "pipeline_id": r.get("pipeline_id"),
                "pipeline_name": r.get("pipeline_name"),
                "dataset_id": _row_dataset_id(r) or None,
                "relation_name": obs.get("relation_name"),
                "column_name": obs.get("column_name"),
                "status": st,
                "status_display": st.title(),
                "severity": r.get("severity"),
                "message": r.get("message"),
                "checked_at": json_val(r.get("checked_at")),
                "dimension": _row_dimension(r),
                "tags": _row_tags(r),
                "monitor_type": r.get("monitor_type") or obs.get("check_type"),
                "source": obs.get("source") or (
                    "dbt_run_results" if is_dbt_check(r.get("monitor_id")) else "monitor"
                ),
                "expected_value": obs.get("expected_value"),
                "actual_value": obs.get("actual_value"),
                "failure_count": obs.get("failure_count"),
            }
        )

    trend = quality_score_over_time(
        conn,
        from_str=rng.get("from_str"),
        to_str=rng.get("to_str"),
        pipeline_name=pipeline_name,
        pipeline_id=pipeline_id,
        source=source,
    )

    available = bool(summary.get("available"))
    score = summary.get("quality_score")
    kpis = [
        make_kpi(
            id="quality_status",
            title="Quality Status",
            value=score,
            display=f"{score}%" if score is not None else ("N/A" if not available else "—"),
            tone="ok" if (score or 0) >= 90 else "warn" if (score or 0) >= 75 else "bad" if available else "neutral",
            available=available,
        ),
        make_kpi(
            id="checks_run",
            title="Checks Run",
            value=summary.get("checks_run"),
            display=str(summary.get("checks_run") or 0),
            available=available,
        ),
        make_kpi(
            id="passed",
            title="Passed",
            value=summary.get("passed"),
            display=str(summary.get("passed") or 0),
            tone="ok",
            available=available,
        ),
        make_kpi(
            id="warning",
            title="Warning",
            value=summary.get("warn"),
            display=str(summary.get("warn") or 0),
            tone="warn" if summary.get("warn") else "ok",
            available=available,
        ),
        make_kpi(
            id="failed",
            title="Failed",
            value=summary.get("failed"),
            display=str(summary.get("failed") or 0),
            tone="bad" if summary.get("failed") else "ok",
            available=available,
        ),
    ]

    return envelope(
        rng=rng,
        filters_applied={
            "pipeline_name": pipeline_name,
            "pipeline_id": pipeline_id,
            "preset": rng.get("preset"),
            "score_mode": score_mode,
            "source": source,
            "dataset_id": ds_norm,
            "tag": tag,
            "dimension": dimension,
        },
        kpis=kpis,
        series={"quality_score_over_time": trend},
        charts={
            "checks_by_status": {
                "passed": summary.get("passed") or 0,
                "warning": summary.get("warn") or 0,
                "failed": summary.get("failed") or 0,
                "total": summary.get("checks_run") or 0,
            },
            "by_dimension": summary.get("by_dimension") or {},
        },
        items=items,
        meta={
            "available": available,
            "dbt_checks": summary.get("dbt_checks"),
            "monitor_checks": summary.get("monitor_checks"),
            "status_key": summary.get("status_key"),
            "alerting_checks": summary.get("alerting_checks") or [
                i for i in items if i.get("status") in {"warn", "fail", "failed", "error"}
            ],
        },
        summary=summary,
    )
