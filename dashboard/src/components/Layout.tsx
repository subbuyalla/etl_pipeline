import type { ReactNode } from "react";

const NAV = [
  { id: "overview", label: "Overview", enabled: true },
  { id: "pipelines", label: "Pipelines", enabled: false },
  { id: "observability", label: "Data Observability", enabled: false },
  { id: "lineage", label: "Lineage", enabled: false },
  { id: "incidents", label: "Incidents", enabled: false },
  { id: "alerts", label: "Alerts", enabled: false },
  { id: "quality", label: "Data Quality", enabled: false },
  { id: "logs", label: "Logs", enabled: false },
  { id: "metrics", label: "Metrics", enabled: false },
  { id: "infra", label: "Infrastructure", enabled: false },
  { id: "cost", label: "Cost", enabled: false },
  { id: "reports", label: "Reports", enabled: false },
  { id: "settings", label: "Settings", enabled: false },
];

type Props = {
  children: ReactNode;
  range: string;
  onRangeChange: (range: string) => void;
  onRefresh: () => void;
  generatedAt?: string;
};

export function Layout({ children, range, onRangeChange, onRefresh, generatedAt }: Props) {
  return (
    <div className="shell">
      <aside className="rail">
        <div className="brand">
          <span className="brand-mark">V</span>
          <div>
            <strong>VITHI</strong>
            <p>Data Observability</p>
          </div>
        </div>
        <nav className="nav">
          {NAV.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`nav-link ${item.enabled ? "active" : "disabled"}`}
              disabled={!item.enabled}
              title={item.enabled ? item.label : "Coming later"}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <div className="rail-footer">
          <div className="user-chip">
            <span className="avatar">S</span>
            <div>
              <strong>Sai</strong>
              <p>Data Team</p>
            </div>
          </div>
          <span className="env-pill">Production</span>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div>
            <h1>Executive Overview</h1>
            {generatedAt ? <p className="muted">Updated {generatedAt.replace("T", " ").replace("+00:00", " UTC")}</p> : null}
          </div>
          <div className="topbar-actions">
            <select value="production" disabled>
              <option>Production</option>
            </select>
            <select value={range} onChange={(e) => onRangeChange(e.target.value)}>
              <option value="24h">Last 24 hours</option>
              <option value="7d">Last 7 days</option>
              <option value="30d">Last 30 days</option>
              <option value="all">All recorded</option>
            </select>
            <button type="button" className="btn" onClick={onRefresh}>
              Refresh
            </button>
          </div>
        </header>
        <main className="main">{children}</main>
      </div>
    </div>
  );
}
