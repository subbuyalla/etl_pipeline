import { useMemo, useState } from "react";
import type { OverviewPayload } from "../api";
import { DurationChart, HBarChart, RunsChart, ThroughputChart } from "../components/charts";
import { KpiCard } from "../components/KpiCard";

type Props = {
  data: OverviewPayload | null;
  loading: boolean;
  error: string | null;
};

export function OverviewPage({ data, loading, error }: Props) {
  const [openId, setOpenId] = useState<string | null>(null);
  const defs = useMemo(() => {
    const map = new Map((data?.kpi_defs || []).map((d) => [d.id, d]));
    return map;
  }, [data]);

  if (loading && !data) return <div className="loading">Loading overview from metadata…</div>;
  if (error && !data) return <div className="error-banner">{error}</div>;
  if (!data) return null;

  const toggle = (id: string) => setOpenId((cur) => (cur === id ? null : id));

  return (
    <div className="overview">
      {error ? <div className="error-banner">{error}</div> : null}

      <section className="kpi-grid">
        {data.kpis.map((kpi) => (
          <KpiCard
            key={kpi.id}
            kpi={kpi}
            def={defs.get(kpi.id)}
            open={openId === kpi.id}
            onToggle={() => toggle(kpi.id)}
            onClose={() => setOpenId(null)}
          />
        ))}
      </section>

      <section className="chart-row">
        <article className="panel">
          <h2>Pipeline Runs Over Time</h2>
          <RunsChart data={data.series.runs_over_time} />
        </article>
        <article className="panel">
          <h2>Pipeline Duration (Avg)</h2>
          <DurationChart data={data.series.duration} />
        </article>
        <article className="panel">
          <h2>Throughput (Rows/sec)</h2>
          <ThroughputChart data={data.series.throughput} />
        </article>
      </section>

      <section className="obs-row">
        {data.observability.map((m) => (
          <button
            key={m.id}
            type="button"
            className={`obs-card ${m.available ? "" : "na"} ${openId === m.id ? "open" : ""}`}
            onClick={() => toggle(m.id)}
          >
            <div className="kpi-head">
              <span>{m.title}</span>
              <span className="info-btn">i</span>
            </div>
            <strong>{m.display}</strong>
            {openId === m.id && defs.get(m.id) ? (
              <div className="kpi-pop">
                <strong>{defs.get(m.id)!.title}</strong>
                <p>{defs.get(m.id)!.meaning}</p>
                <p className="formula">{defs.get(m.id)!.formula}</p>
                <p className="muted">Tables: {defs.get(m.id)!.tables}</p>
              </div>
            ) : null}
          </button>
        ))}
      </section>

      <section className="mid-grid">
        <article className="panel">
          <h2>Active Incidents</h2>
          <ul className="incident-list">
            {data.incidents.map((inc) => (
              <li key={String(inc.run_id)}>
                <span className={`sev ${inc.severity}`}>{inc.severity}</span>
                <div>
                  <strong>{inc.title}</strong>
                  <p>{inc.detail}</p>
                </div>
                <em>{inc.age || ""}</em>
              </li>
            ))}
            {!data.incidents.length ? <li className="empty">No failed runs in this range.</li> : null}
          </ul>
        </article>

        <article className="panel">
          <h2>Lineage & Impact</h2>
          <div className="lineage">
            {data.lineage.map((l) => (
              <div key={l.pipeline_name} className="lineage-flow">
                <span className="node">{l.source}</span>
                <span className="arrow">→</span>
                <span className="node etl">{l.etl}</span>
                <span className="arrow">→</span>
                <span className="node">{l.target}</span>
                <small>{l.pipeline_name}</small>
              </div>
            ))}
          </div>
          <h3>Downstream Impact</h3>
          <ul className="impact-list">
            {data.impact.map((i) => (
              <li key={`${i.pipeline_name}-${i.object_name}`}>
                <span>{i.schema_name}.{i.object_name}</span>
                <span className={`impact ${i.impact.toLowerCase()}`}>{i.impact}</span>
              </li>
            ))}
            {!data.impact.length ? <li className="empty">No downstream assets on unhealthy pipelines.</li> : null}
          </ul>
        </article>

        <article className="panel">
          <h2>System Health</h2>
          <ul className="health-list">
            {data.system_health.map((h) => (
              <li key={h.name}>
                <span>{h.name}</span>
                <span className={`status ${h.status}`}>{h.label}</span>
                <em>{h.success_rate_pct != null ? `${h.success_rate_pct}%` : "—"}</em>
              </li>
            ))}
          </ul>
        </article>
      </section>

      <section className="chart-row">
        <article className="panel">
          <h2>Top Pipelines by Volume</h2>
          <HBarChart data={data.charts.top_volume} nameKey="pipeline_name" valueKey="target_row_count" color="#60a5fa" />
        </article>
        <article className="panel">
          <h2>Failure Rate by Pipeline</h2>
          <HBarChart data={data.charts.failure_rate} nameKey="pipeline_name" valueKey="failure_rate_pct" color="#f87171" />
        </article>
        <article className="panel">
          <h2>Data Freshness (Top Datasets)</h2>
          <ul className="fresh-list">
            {data.freshness_datasets.map((d) => (
              <li key={`${d.pipeline_name}-${d.object_name}`}>
                <span>
                  {d.schema_name}.{d.object_name}
                </span>
                <em>{d.age || d.last_updated_at || "—"}</em>
              </li>
            ))}
            {!data.freshness_datasets.length ? <li className="empty">No TARGET datasets stored.</li> : null}
          </ul>
        </article>
      </section>

      <section className="panel table-panel">
        <h2>Pipeline Runs (Recent)</h2>
        <table>
          <thead>
            <tr>
              <th>Pipeline</th>
              <th>Source → Target</th>
              <th>Status</th>
              <th>Duration</th>
              <th>Records</th>
              <th>Start</th>
              <th>Last run</th>
            </tr>
          </thead>
          <tbody>
            {data.runs.map((r) => (
              <tr key={String(r.run_id)}>
                <td>{r.pipeline_name}</td>
                <td>{r.source_target}</td>
                <td>
                  <span className={`dot ${String(r.status || "").toLowerCase()}`} />
                  {r.status}
                </td>
                <td>{r.duration || "—"}</td>
                <td>{r.rows_read != null ? Number(r.rows_read).toLocaleString() : "—"}</td>
                <td>{r.start_time || "—"}</td>
                <td>{r.last_run || "—"}</td>
              </tr>
            ))}
            {!data.runs.length ? (
              <tr>
                <td colSpan={7} className="empty">
                  No runs in this range.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </section>
    </div>
  );
}
