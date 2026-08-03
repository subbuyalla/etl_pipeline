import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  api,
  type Alert,
  type CheckResult,
  type Dataset,
  type Incident,
  type MetricPoint,
  type Pipeline,
} from "../api/client";
import { BarChart, Donut, Sparkline } from "../components/Charts";
import { ErrorBanner, Loading, PageHeader, Severity, Stat, Status } from "../components/ui";

function seriesByName(metrics: MetricPoint[], name: string): { label?: string; value: number }[] {
  return metrics
    .filter((m) => m.name === name && Number.isFinite(Number(m.value)))
    .slice()
    .sort((a, b) => String(a.recorded_at || "").localeCompare(String(b.recorded_at || "")))
    .map((m) => ({
      label: (m.recorded_at || "").slice(5, 16),
      value: Number(m.value),
    }));
}

export function OverviewPage({ tenantId }: { tenantId: string }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [metrics, setMetrics] = useState<MetricPoint[]>([]);
  const [failingChecks, setFailingChecks] = useState(0);
  const [apiOk, setApiOk] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const health = await api.health();
        if (!cancelled) setApiOk(health.status === "ok");
        const [p, d, i, a, met, checks] = await Promise.all([
          api.pipelines(tenantId),
          api.datasets(tenantId),
          api.incidents(tenantId),
          api.alerts(tenantId),
          api.metrics(tenantId, { limit: 300 }).catch(() => ({ items: [] as MetricPoint[] })),
          api.checkResults(tenantId).catch(() => ({ items: [] as CheckResult[] })),
        ]);
        if (cancelled) return;
        setPipelines(p.items);
        setDatasets(d.items);
        setIncidents(i.items);
        setAlerts(a.items);
        setMetrics(met.items);
        setFailingChecks(
          checks.items.filter((c) =>
            ["anomalous", "failed", "breach", "error"].includes((c.status || "").toLowerCase()),
          ).length,
        );
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

  const openIncidents = incidents.filter((i) => i.status === "open").length;
  const failedPipelines = pipelines.filter((p) => (p.status || "").includes("fail")).length;
  const rowCountSeries = useMemo(() => seriesByName(metrics, "row_count").slice(-24), [metrics]);
  const lagSeries = useMemo(() => seriesByName(metrics, "freshness_lag_hours").slice(-24), [metrics]);
  const severityBars = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const i of incidents) {
      const s = (i.severity || "unknown").toLowerCase();
      counts[s] = (counts[s] || 0) + 1;
    }
    return Object.entries(counts).map(([label, value]) => ({ label, value }));
  }, [incidents]);
  const incidentDonut = useMemo(() => {
    const open = incidents.filter((i) => i.status === "open").length;
    const resolved = incidents.filter((i) => i.status !== "open").length;
    return [
      { label: "open", value: open, color: "var(--bad, #b42318)" },
      { label: "other", value: resolved, color: "var(--ok, #067647)" },
    ];
  }, [incidents]);

  if (loading) return <Loading />;

  return (
    <div>
      <PageHeader
        title="Reliability overview"
        subtitle="KPIs and recent incidents. For questions, open the Observability assistant."
        actions={
          <span className="obs-header-actions">
            <Link className="btn-primary" to="/observability">
              Ask Observability
            </Link>
            <span className={`pill ${apiOk ? "ok" : "bad"}`}>API {apiOk ? "online" : "down"}</span>
          </span>
        }
      />
      <ErrorBanner error={error} />
      <div className="stats">
        <Stat label="Pipelines" value={pipelines.length} />
        <Stat label="Datasets" value={datasets.length} />
        <Stat label="Open incidents" value={openIncidents} tone={openIncidents ? "bad" : "ok"} />
        <Stat label="Failing checks" value={failingChecks} tone={failingChecks ? "bad" : "ok"} />
        <Stat label="Alerts" value={alerts.length} tone={alerts.length ? "warn" : "ok"} />
        <Stat label="Failed pipelines" value={failedPipelines} tone={failedPipelines ? "bad" : "ok"} />
      </div>

      <div className="chart-grid">
        <section className="panel chart-panel">
          <div className="panel-head">
            <h2>Row count trend</h2>
            <span className="muted">{rowCountSeries.length} pts</span>
          </div>
          <Sparkline points={rowCountSeries} />
        </section>
        <section className="panel chart-panel">
          <div className="panel-head">
            <h2>Freshness lag (hours)</h2>
            <span className="muted">{lagSeries.length} pts</span>
          </div>
          <Sparkline points={lagSeries} stroke="var(--warn, #b54708)" />
        </section>
        <section className="panel chart-panel">
          <div className="panel-head">
            <h2>Incidents by severity</h2>
          </div>
          <BarChart points={severityBars} />
        </section>
        <section className="panel chart-panel">
          <div className="panel-head">
            <h2>Incident status</h2>
          </div>
          <Donut segments={incidentDonut} />
        </section>
      </div>

      <section className="panel">
        <div className="panel-head">
          <h2>Recent incidents</h2>
          <Link to="/incidents">View all</Link>
        </div>
        <table>
          <thead>
            <tr>
              <th>Title</th>
              <th>Severity</th>
              <th>Status</th>
              <th>Blast radius</th>
              <th>Asset</th>
            </tr>
          </thead>
          <tbody>
            {incidents.slice(0, 8).map((i) => (
              <tr key={i.incident_key}>
                <td>{i.title}</td>
                <td>
                  <Severity value={i.severity} />
                </td>
                <td>
                  <Status value={i.status} />
                </td>
                <td>{i.blast_radius_count}</td>
                <td className="mono">{i.root_asset_id || "—"}</td>
              </tr>
            ))}
            {!incidents.length && (
              <tr>
                <td colSpan={5} className="empty">
                  No incidents yet. Run the digital twin to seed data.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}
