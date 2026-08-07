import { useMemo, useState, type FormEvent } from "react";
import {
  deleteConnector,
  listConnectors,
  saveConnector,
  type ConnectorInstance,
  type ConnectorKind,
  type ConnectorTool,
} from "../lib/studioStore";

type ToolDef = {
  tool: ConnectorTool;
  kind: ConnectorKind;
  title: string;
  blurb: string;
  fields: { key: string; label: string; type?: string; placeholder?: string; required?: boolean }[];
};

const DATABASE_TOOLS: ToolDef[] = [
  {
    tool: "snowflake",
    kind: "database",
    title: "Snowflake",
    blurb: "Cloud data warehouse — use as SOURCE or TARGET for a pipeline.",
    fields: [
      { key: "account", label: "Account", placeholder: "xy12345.us-east-1", required: true },
      { key: "user", label: "User", required: true },
      { key: "password", label: "Password", type: "password", required: true },
      { key: "warehouse", label: "Warehouse", placeholder: "COMPUTE_WH", required: true },
      { key: "database", label: "Database", placeholder: "ANALYTICS_DB", required: true },
      { key: "schema", label: "Schema", placeholder: "RAW", required: true },
      { key: "role", label: "Role", placeholder: "ACCOUNTADMIN" },
    ],
  },
  {
    tool: "mysql",
    kind: "database",
    title: "MySQL",
    blurb: "Relational database — connect as a source or metadata store.",
    fields: [
      { key: "host", label: "Host", placeholder: "127.0.0.1", required: true },
      { key: "port", label: "Port", placeholder: "3306" },
      { key: "user", label: "User", required: true },
      { key: "password", label: "Password", type: "password", required: true },
      { key: "database", label: "Database", required: true },
    ],
  },
];

const ETL_TOOLS: ToolDef[] = [
  {
    tool: "dbt",
    kind: "etl",
    title: "dbt Cloud",
    blurb: "Run transforms between source and target warehouses.",
    fields: [
      { key: "account_id", label: "Account ID", required: true },
      { key: "project_id", label: "Project / Pipeline ID", required: true },
      { key: "job_id", label: "Job ID (optional)" },
      {
        key: "api_base",
        label: "API base URL",
        placeholder: "https://xxxx.us1.dbt.com/api/v2",
        required: true,
      },
      { key: "api_token", label: "API token", type: "password", required: true },
      { key: "project_name", label: "Project name", placeholder: "analytics" },
    ],
  },
];

function defaultsFor(tool: ToolDef): Record<string, string> {
  const out: Record<string, string> = {};
  for (const f of tool.fields) {
    out[f.key] = f.placeholder && !f.required ? "" : "";
  }
  if (tool.tool === "dbt") {
    out.api_base = "https://cloud.getdbt.com/api/v2";
  }
  if (tool.tool === "mysql") {
    out.port = "3306";
  }
  return out;
}

function ToolSection({
  title,
  tools,
  selected,
  onSelect,
}: {
  title: string;
  tools: ToolDef[];
  selected: ConnectorTool | null;
  onSelect: (t: ToolDef) => void;
}) {
  return (
    <div className="section-block">
      <p className="section-label">{title}</p>
      <div className="card-grid">
        {tools.map((t) => (
          <button
            type="button"
            key={t.tool}
            className={`tool-card ${selected === t.tool ? "selected" : ""}`}
            onClick={() => onSelect(t)}
          >
            <span className="tool-badge">{t.kind === "database" ? "Database" : "ETL tool"}</span>
            <h3>{t.title}</h3>
            <p>{t.blurb}</p>
            <span className="btn secondary" style={{ pointerEvents: "none", width: "fit-content" }}>
              Connect
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

export function ConnectorsPage() {
  const [instances, setInstances] = useState(() => listConnectors());
  const [selected, setSelected] = useState<ToolDef | null>(null);
  const [name, setName] = useState("");
  const [form, setForm] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const allTools = useMemo(() => [...DATABASE_TOOLS, ...ETL_TOOLS], []);

  function refresh() {
    setInstances(listConnectors());
  }

  function pickTool(t: ToolDef) {
    setSelected(t);
    setForm(defaultsFor(t));
    setName(`My ${t.title}`);
    setError(null);
    setMessage(null);
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!selected) return;
    setError(null);
    setMessage(null);

    for (const f of selected.fields) {
      if (f.required && !(form[f.key] || "").trim()) {
        setError(`${f.label} is required`);
        return;
      }
    }
    if (!name.trim()) {
      setError("Display name is required");
      return;
    }

    saveConnector({
      kind: selected.kind,
      tool: selected.tool,
      name: name.trim(),
      config: { ...form },
      status: "connected",
    });
    refresh();
    setMessage(`Connected “${name.trim()}” (${selected.title}). You can attach it on Pipelines.`);
    setSelected(null);
    setForm({});
  }

  function remove(c: ConnectorInstance) {
    deleteConnector(c.id);
    refresh();
    setMessage(`Removed “${c.name}”.`);
  }

  const databases = instances.filter((c) => c.kind === "database");
  const etl = instances.filter((c) => c.kind === "etl");

  return (
    <div>
      <header className="page-header">
        <div>
          <h1>Connectors</h1>
          <p>
            First connect your databases and ETL tools. Then attach them to a pipeline as source,
            transform, and target.
          </p>
        </div>
      </header>

      {error && <div className="banner error">{error}</div>}
      {message && <div className="banner ok">{message}</div>}

      <ToolSection
        title="Databases"
        tools={DATABASE_TOOLS}
        selected={selected?.kind === "database" ? selected.tool : null}
        onSelect={pickTool}
      />

      <ToolSection
        title="ETL tools"
        tools={ETL_TOOLS}
        selected={selected?.kind === "etl" ? selected.tool : null}
        onSelect={pickTool}
      />

      {selected && (
        <form className="form-panel" onSubmit={onSubmit}>
          <h2>Connect {selected.title}</h2>
          <p className="muted small">
            Credentials stay in this browser (localStorage) for the studio demo. Production should
            use env / secrets.
          </p>
          <div className="form-grid">
            <div className="field span-2">
              <label htmlFor="conn-name">Display name</label>
              <input
                id="conn-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={`My ${selected.title}`}
              />
            </div>
            {selected.fields.map((f) => (
              <div className="field" key={f.key}>
                <label htmlFor={f.key}>
                  {f.label}
                  {f.required ? " *" : ""}
                </label>
                <input
                  id={f.key}
                  type={f.type || "text"}
                  value={form[f.key] || ""}
                  placeholder={f.placeholder}
                  onChange={(e) => setForm((prev) => ({ ...prev, [f.key]: e.target.value }))}
                  autoComplete={f.type === "password" ? "off" : undefined}
                />
              </div>
            ))}
          </div>
          <div className="btn-row" style={{ marginTop: 18 }}>
            <button type="submit" className="btn">
              Save connection
            </button>
            <button
              type="button"
              className="btn secondary"
              onClick={() => {
                setSelected(null);
                setError(null);
              }}
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      <div className="section-block" style={{ marginTop: 36 }}>
        <p className="section-label">Your connections</p>
        {!instances.length && (
          <div className="empty">No connectors yet. Pick Snowflake, MySQL, or dbt above.</div>
        )}

        {!!databases.length && (
          <>
            <p className="muted small" style={{ marginBottom: 8 }}>
              Databases ({databases.length})
            </p>
            <div className="instance-list">
              {databases.map((c) => (
                <div className="instance-row" key={c.id}>
                  <div>
                    <strong>{c.name}</strong>
                    <span className="muted small">
                      {" "}
                      · {c.tool}
                      {c.config.database ? ` · ${c.config.database}` : ""}
                      {c.config.schema ? `.${c.config.schema}` : ""}
                    </span>
                  </div>
                  <div className="btn-row">
                    <span className={`badge ${c.status === "connected" ? "ok" : "error"}`}>
                      {c.status}
                    </span>
                    <button type="button" className="btn ghost" onClick={() => remove(c)}>
                      Remove
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}

        {!!etl.length && (
          <>
            <p className="muted small" style={{ margin: "16px 0 8px" }}>
              ETL ({etl.length})
            </p>
            <div className="instance-list">
              {etl.map((c) => (
                <div className="instance-row" key={c.id}>
                  <div>
                    <strong>{c.name}</strong>
                    <span className="muted small">
                      {" "}
                      · {c.tool}
                      {c.config.account_id ? ` · account ${c.config.account_id}` : ""}
                    </span>
                  </div>
                  <div className="btn-row">
                    <span className={`badge ${c.status === "connected" ? "ok" : "error"}`}>
                      {c.status}
                    </span>
                    <button type="button" className="btn ghost" onClick={() => remove(c)}>
                      Remove
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      {/* keep tools list referenced for future catalog expansion */}
      <span style={{ display: "none" }}>{allTools.length}</span>
    </div>
  );
}
