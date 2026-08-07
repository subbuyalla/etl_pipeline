import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { appApi } from "../api/appApi";
import {
  FALLBACK_PIPELINES,
  lineageSummary,
  listConnectors,
  listLocalPipelines,
  newPipelineId,
  saveLocalPipeline,
  type ConnectorInstance,
  type PipelineView,
} from "../lib/studioStore";

function mergePipelines(remote: PipelineView[], local: PipelineView[]): PipelineView[] {
  const byId = new Map<string, PipelineView>();
  for (const p of remote) byId.set(p.pipeline_id, p);
  for (const p of local) {
    const existing = byId.get(p.pipeline_id);
    byId.set(p.pipeline_id, existing ? { ...existing, ...p } : p);
  }
  // Prefer name uniqueness: later entries win for same name from local
  const byName = new Map<string, PipelineView>();
  for (const p of byId.values()) {
    byName.set(p.pipeline_name.toLowerCase(), p);
  }
  return Array.from(byName.values()).sort((a, b) => {
    if (Boolean(a.is_active) !== Boolean(b.is_active)) return a.is_active ? -1 : 1;
    return a.pipeline_name.localeCompare(b.pipeline_name);
  });
}

export function PipelinesPage() {
  const [pipelines, setPipelines] = useState<PipelineView[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [sourceNote, setSourceNote] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const [name, setName] = useState("my_pipeline");
  const [template, setTemplate] = useState<"stock_etl" | "ecommerce_etl" | "custom">("custom");
  const [sourceId, setSourceId] = useState("");
  const [etlId, setEtlId] = useState("");
  const [targetId, setTargetId] = useState("");

  const connectors = useMemo(() => listConnectors(), [showCreate, message]);
  const dbConnectors = connectors.filter((c) => c.kind === "database");
  const etlConnectors = connectors.filter((c) => c.kind === "etl");

  const selected = pipelines.find((p) => p.pipeline_id === selectedId) || null;

  async function load() {
    setLoading(true);
    setError(null);
    const local = listLocalPipelines();
    try {
      const remote = await appApi.listPipelines();
      const merged = mergePipelines(remote.length ? remote : FALLBACK_PIPELINES, local);
      setPipelines(merged);
      setSourceNote(
        remote.length
          ? `Loaded ${remote.length} pipeline(s) from ${appApi.base}`
          : `API returned empty — showing fallback demos + local`,
      );
      setSelectedId((prev) => prev || merged[0]?.pipeline_id || "");
    } catch (e) {
      const merged = mergePipelines(FALLBACK_PIPELINES, local);
      setPipelines(merged);
      setSourceNote(
        `API unreachable (${appApi.base}) — showing demo pipelines. ${
          e instanceof Error ? e.message : String(e)
        }`,
      );
      setSelectedId((prev) => prev || merged[0]?.pipeline_id || "");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function connectorLabel(c: ConnectorInstance): string {
    const schema = c.config.schema || c.config.database || "";
    return `${c.name} (${c.tool}${schema ? "/" + schema : ""})`;
  }

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setMessage(null);

    const src = dbConnectors.find((c) => c.id === sourceId);
    const etl = etlConnectors.find((c) => c.id === etlId);
    const tgt = dbConnectors.find((c) => c.id === targetId);

    if (template === "custom") {
      if (!name.trim()) {
        setError("Pipeline name is required");
        return;
      }
      if (!src || !etl || !tgt) {
        setError("Pick SOURCE (database), ETL (dbt), and TARGET (database) connectors.");
        return;
      }
      const pipeline: PipelineView = {
        pipeline_id: newPipelineId(),
        pipeline_name: name.trim(),
        description: `${src.tool} → ${etl.tool} → ${tgt.tool}`,
        is_active: false,
        source: {
          tool: src.tool,
          schema: src.config.schema || src.config.database,
          connector_id: src.id,
          connector_name: src.name,
        },
        etl: {
          tool: etl.tool,
          connector_id: etl.id,
          connector_name: etl.name,
        },
        target: {
          tool: tgt.tool,
          schema: tgt.config.schema || tgt.config.database,
          connector_id: tgt.id,
          connector_name: tgt.name,
        },
        source_local: true,
      };
      saveLocalPipeline(pipeline);
      setMessage(`Saved local pipeline “${pipeline.pipeline_name}”.`);
      setShowCreate(false);
      await load();
      setSelectedId(pipeline.pipeline_id);
      return;
    }

    // Known templates → try app API, always keep a local attach view
    try {
      const res = await appApi.createPipeline({
        pipeline_name: template,
        make_active: template === "stock_etl",
      });
      const srcC = dbConnectors[0];
      const etlC = etlConnectors[0];
      const tgtC = dbConnectors[1] || dbConnectors[0];
      const pipeline: PipelineView = {
        pipeline_id: String(res.pipeline_id || newPipelineId()),
        pipeline_name: template,
        description:
          template === "stock_etl"
            ? "Snowflake RAW → dbt → STAGING_STAGING"
            : "Snowflake SRC_DATA → dbt → CLEAN_DATA",
        is_active: template === "stock_etl",
        source: {
          tool: "snowflake",
          schema: template === "stock_etl" ? "RAW" : "SRC_DATA",
          connector_id: srcC?.id,
          connector_name: srcC?.name,
        },
        etl: {
          tool: "dbt",
          connector_id: etlC?.id,
          connector_name: etlC?.name,
        },
        target: {
          tool: "snowflake",
          schema: template === "stock_etl" ? "STAGING_STAGING" : "CLEAN_DATA",
          connector_id: tgtC?.id,
          connector_name: tgtC?.name,
        },
      };
      saveLocalPipeline(pipeline);
      setMessage(`Registered “${template}” via API.`);
    } catch (err) {
      const pipeline: PipelineView = {
        pipeline_id: newPipelineId(),
        pipeline_name: template,
        description: "Saved locally (API create failed)",
        is_active: false,
        source: { tool: "snowflake", schema: template === "stock_etl" ? "RAW" : "SRC_DATA" },
        etl: { tool: "dbt" },
        target: {
          tool: "snowflake",
          schema: template === "stock_etl" ? "STAGING_STAGING" : "CLEAN_DATA",
        },
        source_local: true,
      };
      saveLocalPipeline(pipeline);
      setMessage(
        `API create failed — saved “${template}” locally. ${
          err instanceof Error ? err.message : String(err)
        }`,
      );
    }
    setShowCreate(false);
    await load();
  }

  return (
    <div>
      <header className="page-header">
        <div>
          <h1>Pipelines</h1>
          <p>
            Each pipeline attaches a source database, an ETL tool, and a target database.
          </p>
        </div>
        <div className="btn-row">
          <button type="button" className="btn secondary" onClick={() => void load()}>
            Refresh
          </button>
          <button type="button" className="btn" onClick={() => setShowCreate((v) => !v)}>
            {showCreate ? "Close" : "New pipeline"}
          </button>
        </div>
      </header>

      {sourceNote && <div className="banner info">{sourceNote}</div>}
      {error && <div className="banner error">{error}</div>}
      {message && <div className="banner ok">{message}</div>}

      {showCreate && (
        <form className="form-panel" onSubmit={onCreate}>
          <h2>New pipeline</h2>
          <p className="muted small">
            Use a known template (registers in Metadata MySQL) or build a custom attach from your{" "}
            <Link to="/connectors">connectors</Link>.
          </p>
          <div className="form-grid">
            <div className="field">
              <label htmlFor="tpl">Template</label>
              <select
                id="tpl"
                value={template}
                onChange={(e) =>
                  setTemplate(e.target.value as "stock_etl" | "ecommerce_etl" | "custom")
                }
              >
                <option value="custom">Custom (from connectors)</option>
                <option value="stock_etl">stock_etl (RAW → staging)</option>
                <option value="ecommerce_etl">ecommerce_etl (SRC_DATA → CLEAN_DATA)</option>
              </select>
            </div>
            {template === "custom" && (
              <>
                <div className="field">
                  <label htmlFor="pname">Pipeline name</label>
                  <input
                    id="pname"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="orders_etl"
                  />
                </div>
                <div className="field">
                  <label htmlFor="src">SOURCE database</label>
                  <select id="src" value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
                    <option value="">Select…</option>
                    {dbConnectors.map((c) => (
                      <option key={c.id} value={c.id}>
                        {connectorLabel(c)}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="etl">ETL tool</label>
                  <select id="etl" value={etlId} onChange={(e) => setEtlId(e.target.value)}>
                    <option value="">Select…</option>
                    {etlConnectors.map((c) => (
                      <option key={c.id} value={c.id}>
                        {connectorLabel(c)}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="tgt">TARGET database</label>
                  <select id="tgt" value={targetId} onChange={(e) => setTargetId(e.target.value)}>
                    <option value="">Select…</option>
                    {dbConnectors.map((c) => (
                      <option key={c.id} value={c.id}>
                        {connectorLabel(c)}
                      </option>
                    ))}
                  </select>
                </div>
              </>
            )}
          </div>
          {template === "custom" && !dbConnectors.length && (
            <p className="muted small" style={{ marginTop: 12 }}>
              No database connectors yet.{" "}
              <Link to="/connectors">Add Snowflake or MySQL</Link> first.
            </p>
          )}
          {template === "custom" && !etlConnectors.length && (
            <p className="muted small">
              No ETL connectors yet. <Link to="/connectors">Add dbt Cloud</Link> first.
            </p>
          )}
          <div className="btn-row" style={{ marginTop: 16 }}>
            <button type="submit" className="btn">
              Create
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <p className="muted">Loading pipelines…</p>
      ) : (
        <div className="split">
          <div className="pipeline-list">
            {!pipelines.length && (
              <div className="empty">No pipelines. Create one or connect the app API.</div>
            )}
            {pipelines.map((p) => (
              <div
                key={p.pipeline_id}
                className={`pipeline-card ${selectedId === p.pipeline_id ? "selected" : ""}`}
                onClick={() => setSelectedId(p.pipeline_id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") setSelectedId(p.pipeline_id);
                }}
                role="button"
                tabIndex={0}
              >
                <div className="pipeline-card-top">
                  <div>
                    <h3>{p.pipeline_name}</h3>
                    {p.description && <p className="desc">{p.description}</p>}
                  </div>
                  <span className={`badge ${p.is_active ? "active" : "idle"}`}>
                    {p.is_active ? "Active" : "Idle"}
                  </span>
                </div>
                <div className="lineage">
                  <span className="chip">
                    {p.source?.tool || "?"}
                    {p.source?.schema ? `/${p.source.schema}` : ""}
                  </span>
                  <span className="arrow">→</span>
                  <span className="chip">{p.etl?.tool || "?"}</span>
                  <span className="arrow">→</span>
                  <span className="chip">
                    {p.target?.tool || "?"}
                    {p.target?.schema ? `/${p.target.schema}` : ""}
                  </span>
                </div>
              </div>
            ))}
          </div>

          <aside className="panel">
            {!selected ? (
              <p className="muted">Select a pipeline to see connector attach details.</p>
            ) : (
              <>
                <h2>{selected.pipeline_name}</h2>
                <p className="muted small">{lineageSummary(selected)}</p>
                <p className="muted small" style={{ marginTop: 8 }}>
                  ID: {selected.pipeline_id}
                </p>
                <div className="attach-grid" style={{ marginTop: 16 }}>
                  <div className="attach-box">
                    <h4>Source</h4>
                    <strong>
                      {selected.source?.tool}
                      {selected.source?.schema ? ` / ${selected.source.schema}` : ""}
                    </strong>
                    <p className="muted small">
                      {selected.source?.connector_name || "Database connector"}
                    </p>
                  </div>
                  <div className="attach-box">
                    <h4>ETL</h4>
                    <strong>{selected.etl?.tool || "—"}</strong>
                    <p className="muted small">
                      {selected.etl?.connector_name || "ETL tool connector"}
                    </p>
                  </div>
                  <div className="attach-box">
                    <h4>Target</h4>
                    <strong>
                      {selected.target?.tool}
                      {selected.target?.schema ? ` / ${selected.target.schema}` : ""}
                    </strong>
                    <p className="muted small">
                      {selected.target?.connector_name || "Database connector"}
                    </p>
                  </div>
                </div>
              </>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}
