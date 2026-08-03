import { Link } from "react-router-dom";
import { PageHeader } from "../components/ui";

const ASSISTANTS = [
  {
    id: "observability",
    name: "Observability",
    status: "Live",
    blurb:
      "Tenant-wide reliability overview: pipelines, datasets, open incidents, monitors, alerts — what to fix first. LangGraph + A2A skill: observability.",
    href: "/observability",
    cta: "Open Observability chat",
  },
  {
    id: "incident-rca",
    name: "Incident RCA",
    status: "Live",
    blurb:
      "LangGraph ReAct agent: the model calls Metadata tools, then answers with grounding. A2A skill: incident_rca.",
    href: "/incidents",
    cta: "Open incidents chat",
  },
  {
    id: "dq-lineage",
    name: "Data Quality + Lineage",
    status: "Live",
    blurb:
      "LangGraph ReAct agent for checks, lineage, and blast radius. A2A skill: dq_lineage.",
    href: "/monitors",
    cta: "Open monitors chat",
  },
  {
    id: "orchestrator",
    name: "A2A Orchestrator",
    status: "Live",
    blurb:
      "Agent-to-Agent protocol: POST /a2a/jsonrpc routes to Observability, RCA, and/or DQ. Cards at /.well-known/agent.json.",
    href: "/assistants",
    cta: "See assistants",
  },
];

export function AssistantsPage() {
  return (
    <div>
      <PageHeader
        title="AI Assistants"
        subtitle="LangGraph agents call Metadata tools per question. Observability covers the whole estate; RCA and DQ drill into one asset."
      />
      <div className="assistant-grid">
        {ASSISTANTS.map((a) => (
          <section key={a.id} className="panel assistant-card">
            <div className="panel-head">
              <h2>{a.name}</h2>
              <span className={`pill ${a.status === "Live" ? "ok" : a.status === "Next" ? "warn" : ""}`}>
                {a.status}
              </span>
            </div>
            <div className="panel-pad">
              <p>{a.blurb}</p>
              {a.id !== "orchestrator" ? (
                <Link className="btn-primary" to={a.href}>
                  {a.cta}
                </Link>
              ) : (
                <p className="muted mono" style={{ marginTop: 8 }}>
                  GET /.well-known/agent.json · POST /a2a/jsonrpc
                </p>
              )}
              {a.id === "dq-lineage" && (
                <p className="muted" style={{ marginTop: 12 }}>
                  Also available from <Link to="/lineage">Lineage</Link>.
                </p>
              )}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
