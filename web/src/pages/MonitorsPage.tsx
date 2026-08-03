import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { api, type ChatMessage, type CheckResult, type MetricPoint, type Monitor } from "../api/client";
import { BarChart, Sparkline } from "../components/Charts";
import { ErrorBanner, Loading, PageHeader, Status } from "../components/ui";

const SUGGESTIONS = [
  "Which checks failed?",
  "What is the blast radius?",
  "What should I fix first?",
];

function metricSeries(metrics: MetricPoint[], name: string, assetId?: string) {
  return metrics
    .filter(
      (m) =>
        m.name === name &&
        Number.isFinite(Number(m.value)) &&
        (!assetId || m.asset_id === assetId),
    )
    .slice()
    .sort((a, b) => String(a.recorded_at || "").localeCompare(String(b.recorded_at || "")))
    .map((m) => ({
      label: (m.recorded_at || "").slice(5, 16),
      value: Number(m.value),
    }));
}

export function MonitorsPage({ tenantId }: { tenantId: string }) {
  const [items, setItems] = useState<Monitor[]>([]);
  const [checks, setChecks] = useState<CheckResult[]>([]);
  const [metrics, setMetrics] = useState<MetricPoint[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedAsset, setSelectedAsset] = useState<string>("");
  const [sessionId, setSessionId] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const [monRes, checkRes, metRes] = await Promise.all([
          api.monitors(tenantId),
          api.checkResults(tenantId).catch(() => ({ items: [] as CheckResult[] })),
          api.metrics(tenantId, { limit: 300 }).catch(() => ({ items: [] as MetricPoint[] })),
        ]);
        if (!cancelled) {
          setItems(monRes.items);
          setChecks(checkRes.items);
          setMetrics(metRes.items);
        }
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
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, chatLoading]);

  const checkStatusBars = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const c of checks) {
      const s = (c.status || "unknown").toLowerCase();
      counts[s] = (counts[s] || 0) + 1;
    }
    return Object.entries(counts).map(([label, value]) => ({ label, value }));
  }, [checks]);

  const volumeSeries = useMemo(
    () => metricSeries(metrics, "row_count", selectedAsset || undefined).slice(-24),
    [metrics, selectedAsset],
  );
  const freshnessSeries = useMemo(
    () => metricSeries(metrics, "freshness_lag_hours", selectedAsset || undefined).slice(-24),
    [metrics, selectedAsset],
  );

  async function startChat(datasetId: string) {
    setSelectedAsset(datasetId);
    setSessionId("");
    setMessages([]);
    setChatError(null);
    setChatLoading(true);
    try {
      const session = await api.startDqChat(tenantId, datasetId);
      setSessionId(session.session_id);
      setMessages(session.messages);
    } catch (e) {
      setChatError(e instanceof Error ? e.message : String(e));
    } finally {
      setChatLoading(false);
    }
  }

  async function sendMessage(text: string) {
    const msg = text.trim();
    if (!sessionId || !msg || chatLoading) return;
    setDraft("");
    setChatLoading(true);
    setChatError(null);
    try {
      const turn = await api.sendDqChatMessage(sessionId, msg);
      setMessages(turn.messages);
    } catch (e) {
      setChatError(e instanceof Error ? e.message : String(e));
    } finally {
      setChatLoading(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void sendMessage(draft);
  }

  if (loading) return <Loading />;

  return (
    <div>
      <PageHeader
        title="Monitors"
        subtitle="Freshness, volume, schema checks with trend charts. Explain DQ uses agentic Metadata tool calls."
      />
      <ErrorBanner error={error} />

      <div className="chart-grid">
        <section className="panel chart-panel">
          <div className="panel-head">
            <h2>Check status mix</h2>
          </div>
          <BarChart points={checkStatusBars} />
        </section>
        <section className="panel chart-panel">
          <div className="panel-head">
            <h2>Row count {selectedAsset ? `(${selectedAsset})` : "(all)"}</h2>
          </div>
          <Sparkline points={volumeSeries} />
        </section>
        <section className="panel chart-panel">
          <div className="panel-head">
            <h2>Freshness lag {selectedAsset ? `(${selectedAsset})` : "(all)"}</h2>
          </div>
          <Sparkline points={freshnessSeries} stroke="var(--warn, #b54708)" />
        </section>
      </div>

      <div className="split">
        <div>
          <section className="panel">
            <table>
              <thead>
                <tr>
                  <th>Type</th>
                  <th>Asset</th>
                  <th>Asset type</th>
                  <th>Enabled</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {items.map((m) => (
                  <tr key={m.monitor_key} className={selectedAsset === m.asset_id ? "selected" : ""}>
                    <td>
                      <Status value={m.monitor_type} />
                    </td>
                    <td className="mono">{m.asset_id}</td>
                    <td>{m.asset_type}</td>
                    <td>{m.enabled ? "yes" : "no"}</td>
                    <td>
                      {m.asset_type === "dataset" ? (
                        <button type="button" className="btn-link" onClick={() => startChat(m.asset_id)}>
                          Explain DQ
                        </button>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                  </tr>
                ))}
                {!items.length && (
                  <tr>
                    <td colSpan={5} className="empty">
                      No monitors yet. Freshness/volume/schema events create them automatically.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </section>

          <section className="panel">
            <div className="panel-head">
              <h2>Recent check results</h2>
            </div>
            <table>
              <thead>
                <tr>
                  <th>Type</th>
                  <th>Asset</th>
                  <th>Status</th>
                  <th>Metric</th>
                  <th>Baseline</th>
                  <th>When</th>
                </tr>
              </thead>
              <tbody>
                {checks.map((c) => (
                  <tr key={c.id}>
                    <td>
                      <Status value={c.monitor_type} />
                    </td>
                    <td className="mono">{c.asset_id}</td>
                    <td>
                      <Status value={c.status} />
                    </td>
                    <td>{c.metric_value ?? "—"}</td>
                    <td>{c.baseline_value ?? "—"}</td>
                    <td className="mono muted">{c.checked_at?.slice(0, 19) ?? "—"}</td>
                  </tr>
                ))}
                {!checks.length && (
                  <tr>
                    <td colSpan={6} className="empty">
                      No check results yet. Re-ingest after Metadata restart to populate.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </section>
        </div>

        <section className="panel rca-panel chat-panel">
          <div className="panel-head">
            <div>
              <h2>DQ + Lineage chat</h2>
              {selectedAsset && (
                <p className="muted" style={{ margin: "4px 0 0" }}>
                  <span className="mono">{selectedAsset}</span>
                  {sessionId ? <span className="mono"> · session {sessionId.slice(0, 8)}</span> : null}
                </p>
              )}
            </div>
          </div>

          {!selectedAsset && (
            <p className="empty">
              Pick a dataset monitor and click Explain DQ. Tenant and dataset are bound automatically.
            </p>
          )}
          <ErrorBanner error={chatError} />

          {selectedAsset && (
            <>
              <div className="chat-thread">
                {messages.map((m, idx) => (
                  <div key={`${m.created_at}-${idx}`} className={`chat-bubble ${m.role}`}>
                    <div className="chat-role">{m.role === "user" ? "You" : "Assistant"}</div>
                    <div className="chat-content">{m.content}</div>
                  </div>
                ))}
                {chatLoading && <div className="muted chat-waiting">Thinking…</div>}
                <div ref={bottomRef} />
              </div>

              {sessionId && (
                <div className="chat-suggestions">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      type="button"
                      className="chip-btn"
                      onClick={() => sendMessage(s)}
                      disabled={chatLoading}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              )}

              <form className="chat-compose" onSubmit={onSubmit}>
                <input
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  placeholder={sessionId ? "Ask a follow-up…" : "Starting chat…"}
                  disabled={!sessionId || chatLoading}
                />
                <button type="submit" disabled={!sessionId || chatLoading || !draft.trim()}>
                  Send
                </button>
              </form>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
