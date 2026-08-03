import { useEffect, useMemo, useState } from "react";
import { api, type Pipeline, type PipelineDashboard } from "../api/client";
import { ErrorBanner, Loading, PageHeader, Severity, Stat, Status } from "../components/ui";

function formatMs(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)} s`;
  return `${(s / 60).toFixed(1)} min`;
}

function RunBars({ executions }: { executions: PipelineDashboard["executions"] }) {
  const pipelineRuns = useMemo(() => {
    const runs = executions.filter((e) => !e.task_id).slice(0, 24).reverse();
    return runs.length ? runs : executions.slice(0, 24).reverse();
  }, [executions]);

  if (!pipelineRuns.length) return <p className="muted">No run history yet.</p>;

  const maxDur = Math.max(...pipelineRuns.map((e) => e.duration_ms || 1), 1);

  return (
    <div className="run-bars" title="Recent runs (left = older)">
      {pipelineRuns.map((e, idx) => {
        const failed = (e.status || "").toLowerCase().includes("fail");
        const height = Math.max(12, Math.round(((e.duration_ms || maxDur * 0.3) / maxDur) * 72));
        return (
          <div
            key={`${e.execution_id}-${idx}`}
            className={`run-bar ${failed ? "bad" : "ok"}`}
            style={{ height }}
            title={`${e.status} · ${formatMs(e.duration_ms)} · ${e.execution_id}`}
          />
        );
      })}
    </div>
  );
}

export function PipelinesPage({ tenantId }: { tenantId: string }) {
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [dash, setDash] = useState<PipelineDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [dashLoading, setDashLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const p = await api.pipelines(tenantId);
        if (cancelled) return;
        setPipelines(p.items);
        setSelected((prev) => prev || p.items[0]?.pipeline_id || "");
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tenantId]);

  useEffect(() => {
    if (!selected) {
      setDash(null);
      return;
    }
    let cancelled = false;
    (async () => {
      setDashLoading(true);
      setError(null);
      try {
        const d = await api.pipelineDashboard(tenantId, selected);
        if (!cancelled) setDash(d);
      } catch (err) {
        if (!cancelled) {
          setDash(null);
          setError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (!cancelled) setDashLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tenantId, selected]);

  if (loading) return <Loading />;

  const m = dash?.metrics;

  return (
    <div>
      <PageHeader
        title="Pipelines"
        subtitle="Select a pipeline for a full reliability dashboard: success rate, duration, tasks, incidents, and lineage."
      />
      <ErrorBanner error={error} />

      <div className="pipeline-layout">
        <section className="panel pipeline-list">
          <div className="panel-head">
            <h2>All pipelines</h2>
          </div>
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Tool</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {pipelines.map((p) => (
                <tr
                  key={p.pipeline_id}
                  className={selected === p.pipeline_id ? "selected" : ""}
                  onClick={() => setSelected(p.pipeline_id)}
                  style={{ cursor: "pointer" }}
                >
                  <td className="mono">{p.pipeline_id}</td>
                  <td>{p.source_tool}</td>
                  <td>
                    <Status value={p.status || "unknown"} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <div className="pipeline-dash">
          {!selected && <div className="empty">Select a pipeline to open its dashboard.</div>}
          {selected && dashLoading && <Loading />}
          {selected && dash && !dashLoading && (
            <>
              <section className="panel">
                <div className="panel-head">
                  <div>
                    <h2>{dash.pipeline.name}</h2>
                    <p className="muted mono">
                      {dash.pipeline.pipeline_id} · {dash.pipeline.source_tool}
                    </p>
                  </div>
                  <Status value={dash.pipeline.status || "unknown"} />
                </div>
                <div className="stats">
                  <Stat label="Total runs" value={m?.total_runs ?? 0} />
                  <Stat
                    label="Success rate"
                    value={m?.success_rate_pct != null ? `${m.success_rate_pct}%` : "—"}
                    tone={(m?.success_rate_pct ?? 100) >= 90 ? "ok" : (m?.success_rate_pct ?? 0) >= 70 ? "warn" : "bad"}
                  />
                  <Stat label="Failed runs" value={m?.failed ?? 0} tone={m?.failed ? "bad" : "ok"} />
                  <Stat label="Avg duration" value={formatMs(m?.avg_duration_ms)} />
                  <Stat label="Max duration" value={formatMs(m?.max_duration_ms)} />
                  <Stat label="Retries" value={m?.retry_count ?? 0} tone={m?.retry_count ? "warn" : "ok"} />
                  <Stat label="Tasks" value={m?.task_count ?? 0} />
                  <Stat
                    label="Open incidents"
                    value={m?.open_incident_count ?? 0}
                    tone={m?.open_incident_count ? "bad" : "ok"}
                  />
                </div>
                <div className="panel-pad">
                  <h3 className="section-label">Recent run durations</h3>
                  <RunBars executions={dash.executions} />
                </div>
              </section>

              <div className="split">
                <section className="panel">
                  <div className="panel-head">
                    <h2>Task health</h2>
                  </div>
                  <table>
                    <thead>
                      <tr>
                        <th>Task</th>
                        <th>Runs</th>
                        <th>OK</th>
                        <th>Failed</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(dash.task_stats.length ? dash.task_stats : dash.tasks.map((t) => ({ task_id: t.task_id, total: 0, succeeded: 0, failed: 0 }))).map(
                        (t) => (
                          <tr key={t.task_id}>
                            <td className="mono">{t.task_id}</td>
                            <td>{t.total}</td>
                            <td>{t.succeeded}</td>
                            <td>
                              <span className={t.failed ? "pill bad" : "pill ok"}>{t.failed}</span>
                            </td>
                          </tr>
                        ),
                      )}
                      {!dash.tasks.length && !dash.task_stats.length && (
                        <tr>
                          <td colSpan={4} className="empty">
                            No task-level runs yet.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </section>

                <section className="panel">
                  <div className="panel-head">
                    <h2>Related incidents</h2>
                  </div>
                  <table>
                    <thead>
                      <tr>
                        <th>Title</th>
                        <th>Severity</th>
                        <th>Status</th>
                        <th>Blast</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dash.incidents.map((i) => (
                        <tr key={i.incident_key}>
                          <td>{i.title}</td>
                          <td>
                            <Severity value={i.severity} />
                          </td>
                          <td>
                            <Status value={i.status} />
                          </td>
                          <td>{i.blast_radius_count}</td>
                        </tr>
                      ))}
                      {!dash.incidents.length && (
                        <tr>
                          <td colSpan={4} className="empty">
                            No incidents linked to this pipeline.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </section>
              </div>

              <div className="split">
                <section className="panel">
                  <div className="panel-head">
                    <h2>Alerts</h2>
                  </div>
                  <table>
                    <thead>
                      <tr>
                        <th>Title</th>
                        <th>Type</th>
                        <th>Severity</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dash.alerts.map((a) => (
                        <tr key={a.alert_key}>
                          <td>{a.title}</td>
                          <td>{a.monitor_type || "—"}</td>
                          <td>
                            <Severity value={a.severity} />
                          </td>
                        </tr>
                      ))}
                      {!dash.alerts.length && (
                        <tr>
                          <td colSpan={3} className="empty">
                            No alerts for this pipeline.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </section>

                <section className="panel">
                  <div className="panel-head">
                    <h2>Related datasets / lineage</h2>
                  </div>
                  {dash.related_datasets.length ? (
                    <ul className="blast-list">
                      {dash.related_datasets.map((d) => (
                        <li key={d} className="mono">
                          {d}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="empty">No lineage transform links for this pipeline yet.</p>
                  )}
                  {dash.lineage_edges.length > 0 && (
                    <table>
                      <thead>
                        <tr>
                          <th>Upstream</th>
                          <th>Downstream</th>
                        </tr>
                      </thead>
                      <tbody>
                        {dash.lineage_edges.map((e) => (
                          <tr key={`${e.upstream_dataset_id}-${e.downstream_dataset_id}`}>
                            <td className="mono">{e.upstream_dataset_id}</td>
                            <td className="mono">{e.downstream_dataset_id}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </section>
              </div>

              <section className="panel">
                <div className="panel-head">
                  <h2>Execution history</h2>
                </div>
                <table>
                  <thead>
                    <tr>
                      <th>Execution</th>
                      <th>Task</th>
                      <th>Status</th>
                      <th>Attempt</th>
                      <th>Duration</th>
                      <th>Started</th>
                      <th>Error</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {dash.executions.map((e) => (
                      <tr key={`${e.execution_id}-${e.task_id}`}>
                        <td className="mono">{e.execution_id}</td>
                        <td className="mono">{e.task_id || "(pipeline)"}</td>
                        <td>
                          <Status value={e.status} />
                        </td>
                        <td>{e.attempt}</td>
                        <td>{formatMs(e.duration_ms)}</td>
                        <td className="mono muted">{e.started_at || "—"}</td>
                        <td className="error-cell">{e.error_message || "—"}</td>
                        <td>
                          {e.deep_link ? (
                            <a
                              className="btn-link external-link"
                              href={e.deep_link}
                              target="_blank"
                              rel="noreferrer"
                            >
                              {e.deep_link_label || "Open in tool"} ↗
                            </a>
                          ) : (
                            "—"
                          )}
                        </td>
                      </tr>
                    ))}
                    {!dash.executions.length && (
                      <tr>
                        <td colSpan={8} className="empty">
                          No executions yet.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
