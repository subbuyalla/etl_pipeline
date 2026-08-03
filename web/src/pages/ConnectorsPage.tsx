import { useEffect, useMemo, useState, type FormEvent } from "react";
import {
  api,
  type ConnectorCatalogItem,
  type ConnectorIngestResult,
  type ConnectorInstance,
} from "../api/client";
import { ErrorBanner, Loading, PageHeader, Status } from "../components/ui";

type FormState = Record<string, string>;

function schemaDefaults(spec: ConnectorCatalogItem | undefined): FormState {
  const out: FormState = {};
  if (!spec) return out;
  const props = (spec.config_schema?.properties || {}) as Record<string, { default?: unknown }>;
  Object.entries(props).forEach(([k, v]) => {
    if (v.default != null) out[k] = String(v.default);
  });
  if (!out.input_mode) out.input_mode = (spec.input_modes || ["live"])[0] || "live";
  return out;
}

function configToForm(config: Record<string, unknown>, spec: ConnectorCatalogItem | undefined): FormState {
  const base = schemaDefaults(spec);
  Object.entries(config || {}).forEach(([k, v]) => {
    if (v != null) base[k] = String(v);
  });
  return base;
}

export function ConnectorsPage({ tenantId }: { tenantId: string }) {
  const [catalog, setCatalog] = useState<ConnectorCatalogItem[]>([]);
  const [instances, setInstances] = useState<ConnectorInstance[]>([]);
  const [selectedTool, setSelectedTool] = useState("snowflake");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [name, setName] = useState("My Snowflake");
  const [form, setForm] = useState<FormState>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvResult, setCsvResult] = useState<ConnectorIngestResult | null>(null);
  const [showCsv, setShowCsv] = useState(false);

  const spec = useMemo(
    () => catalog.find((c) => c.tool_id === selectedTool),
    [catalog, selectedTool],
  );

  async function refresh() {
    const [cat, inst] = await Promise.all([api.connectorCatalog(), api.connectorInstances(tenantId)]);
    setCatalog(cat.items);
    setInstances(inst.items);
    if (cat.items[0] && !cat.items.find((c) => c.tool_id === selectedTool)) {
      setSelectedTool(cat.items[0].tool_id);
    }
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        await refresh();
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId]);

  useEffect(() => {
    if (editingId) return;
    setForm(schemaDefaults(spec));
    setName(spec ? `My ${spec.display_name}` : "My connector");
  }, [spec, editingId]);

  const fields = useMemo(() => {
    const props = (spec?.config_schema?.properties || {}) as Record<
      string,
      { title?: string; description?: string; enum?: string[]; type?: string; default?: unknown }
    >;
    return Object.entries(props);
  }, [spec]);

  function setField(key: string, value: string) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function startNew() {
    setEditingId(null);
    setError(null);
    setMessage(null);
    setForm(schemaDefaults(spec));
    setName(spec ? `My ${spec.display_name}` : "My connector");
  }

  function selectInstance(inst: ConnectorInstance) {
    const toolSpec = catalog.find((c) => c.tool_id === inst.tool_id);
    setEditingId(inst.instance_id);
    setSelectedTool(inst.tool_id);
    setName(inst.name);
    setForm(configToForm(inst.config as Record<string, unknown>, toolSpec));
    setError(null);
    setMessage(`Editing ${inst.instance_id}`);
  }

  function buildSecretsRef(): Record<string, string> {
    const secrets_ref: Record<string, string> = {};
    for (const sf of spec?.secret_fields || []) {
      const envKey = form[`${sf}_env`];
      if (envKey) secrets_ref[`${sf}_env`] = envKey;
    }
    return secrets_ref;
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!spec) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    const secrets_ref = buildSecretsRef();
    try {
      if (editingId) {
        const updated = await api.updateConnectorInstance(editingId, {
          tenant_id: tenantId,
          name,
          config: { ...form },
          secrets_ref,
        });
        setMessage(`Updated ${updated.instance_id}`);
      } else {
        const created = await api.createConnectorInstance({
          tenant_id: tenantId,
          tool_id: selectedTool,
          name,
          config: { ...form },
          secrets_ref,
        });
        setEditingId(created.instance_id);
        setMessage(`Created ${created.instance_id}`);
      }
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onDelete() {
    if (!editingId) return;
    if (!window.confirm(`Delete connection ${editingId}?`)) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await api.deleteConnectorInstance(tenantId, editingId);
      setMessage(`Deleted ${editingId}`);
      startNew();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onTest(instanceId: string) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const res = await api.testConnectorInstance(tenantId, instanceId);
      setMessage(
        res.result.ok ? `Test OK: ${res.result.message}` : `Test failed: ${res.result.message}`,
      );
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onSync(instanceId: string) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const res = await api.syncConnectorInstance(tenantId, instanceId);
      setMessage(
        `Sync ${res.run_id}: envelopes=${res.envelopes} ingested=${res.ingested} duplicates=${res.duplicates}`,
      );
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onCsv(e: FormEvent) {
    e.preventDefault();
    if (!csvFile) {
      setError("Choose a CSV file first.");
      return;
    }
    setBusy(true);
    setError(null);
    setCsvResult(null);
    try {
      const res = await api.ingestConnectorCsv(selectedTool, tenantId, csvFile);
      setCsvResult(res);
      setMessage(`CSV ingest: ${res.ingested} ingested`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <Loading />;

  return (
    <div>
      <PageHeader
        title="Connectors"
        subtitle="Select a connection on the right to edit it on the left. Create, update, delete, test, and sync."
      />
      <ErrorBanner error={error} />
      {message && <div className="info-banner">{message}</div>}

      <div className="connector-catalog">
        {catalog.map((c) => (
          <button
            key={c.tool_id}
            type="button"
            className={`catalog-card ${selectedTool === c.tool_id && !editingId ? "active" : ""}`}
            onClick={() => {
              setSelectedTool(c.tool_id);
              if (!editingId || instances.find((i) => i.instance_id === editingId)?.tool_id !== c.tool_id) {
                startNew();
                setSelectedTool(c.tool_id);
              }
            }}
          >
            <strong>{c.display_name}</strong>
            <span className="muted">{c.description}</span>
            <span className="mono muted">{(c.input_modes || []).join(" · ")}</span>
          </button>
        ))}
      </div>

      <div className="split">
        <section className="panel">
          <div className="panel-head">
            <h2>{editingId ? "Edit connection" : "Add connection"}</h2>
            <button type="button" className="btn-link" onClick={startNew}>
              New
            </button>
          </div>
          {editingId && (
            <p className="panel-pad muted mono" style={{ paddingBottom: 0 }}>
              {editingId}
            </p>
          )}
          <form className="panel-pad connector-form" onSubmit={onSubmit}>
            <label>
              <span>Display name</span>
              <input value={name} onChange={(e) => setName(e.target.value)} required />
            </label>
            <label>
              <span>Tenant</span>
              <input value={tenantId} disabled />
            </label>
            {fields.map(([key, meta]) => (
              <label key={key}>
                <span>{meta.title || key}</span>
                {meta.enum ? (
                  <select value={form[key] || ""} onChange={(e) => setField(key, e.target.value)}>
                    {meta.enum.map((opt) => (
                      <option key={opt} value={opt}>
                        {opt}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    value={form[key] || ""}
                    onChange={(e) => setField(key, e.target.value)}
                    placeholder={meta.description || ""}
                  />
                )}
                {meta.description && <small className="muted">{meta.description}</small>}
              </label>
            ))}
            <p className="muted">
              Secrets stay in env vars (e.g. <span className="mono">SNOWFLAKE_PASSWORD</span>).
            </p>
            <div className="row-actions">
              <button type="submit" disabled={busy}>
                {busy ? "Saving…" : editingId ? "Update" : "Create connection"}
              </button>
              {editingId && (
                <button type="button" className="btn-danger" disabled={busy} onClick={onDelete}>
                  Delete
                </button>
              )}
            </div>
          </form>

          <div className="panel-pad">
            <button type="button" className="btn-link" onClick={() => setShowCsv((v) => !v)}>
              {showCsv ? "Hide" : "Show"} CSV upload (advanced / offline)
            </button>
          </div>
          {showCsv && (
            <form className="panel-pad connector-form" onSubmit={onCsv}>
              <label>
                <span>CSV for {selectedTool}</span>
                <input type="file" accept=".csv,text/csv" onChange={(e) => setCsvFile(e.target.files?.[0] ?? null)} />
              </label>
              <button type="submit" disabled={busy || !csvFile}>
                Ingest CSV
              </button>
              {csvResult && (
                <p className="muted">
                  envelopes={csvResult.envelopes} ingested={csvResult.ingested} duplicates={csvResult.duplicates}
                </p>
              )}
            </form>
          )}
        </section>

        <section className="panel">
          <div className="panel-head">
            <h2>Your connections</h2>
          </div>
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Tool</th>
                <th>Status</th>
                <th>Last sync</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {instances.map((i) => (
                <tr
                  key={i.instance_id}
                  className={editingId === i.instance_id ? "selected" : ""}
                  style={{ cursor: "pointer" }}
                  onClick={() => selectInstance(i)}
                >
                  <td>
                    <div className="cell-title">{i.name}</div>
                    <div className="mono muted">{i.instance_id}</div>
                    {i.last_error ? <div className="muted">{i.last_error}</div> : null}
                  </td>
                  <td className="mono">{i.tool_id}</td>
                  <td>
                    <Status value={i.status} />
                  </td>
                  <td className="mono muted">{i.last_sync_at || "—"}</td>
                  <td className="row-actions" onClick={(e) => e.stopPropagation()}>
                    <button type="button" className="btn-link" disabled={busy} onClick={() => onTest(i.instance_id)}>
                      Test
                    </button>
                    <button type="button" className="btn-link" disabled={busy} onClick={() => onSync(i.instance_id)}>
                      Sync
                    </button>
                  </td>
                </tr>
              ))}
              {!instances.length && (
                <tr>
                  <td colSpan={5} className="empty">
                    No connections yet — create one from the form.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </section>
      </div>
    </div>
  );
}
