type Props = {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
};

export function PageHeader({ title, subtitle, actions }: Props) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        {subtitle ? <p>{subtitle}</p> : null}
      </div>
      {actions ? <div className="page-actions">{actions}</div> : null}
    </header>
  );
}

export function Stat({ label, value, tone }: { label: string; value: string | number; tone?: "ok" | "warn" | "bad" }) {
  return (
    <div className={`stat ${tone ?? ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function Severity({ value }: { value: string }) {
  const v = value.toLowerCase();
  const tone = v === "high" || v === "critical" ? "bad" : v === "medium" || v === "warning" ? "warn" : "ok";
  return <span className={`pill ${tone}`}>{value}</span>;
}

export function Status({ value }: { value: string }) {
  const v = (value || "unknown").toLowerCase();
  const tone =
    v.includes("fail") || v === "open" || v === "anomalous"
      ? "bad"
      : v.includes("success") || v === "resolved" || v === "succeeded"
        ? "ok"
        : "warn";
  return <span className={`pill ${tone}`}>{value || "—"}</span>;
}

export function ErrorBanner({ error }: { error: string | null }) {
  if (!error) return null;
  return <div className="error-banner">{error}</div>;
}

export function Loading() {
  return <div className="loading">Loading metadata…</div>;
}
