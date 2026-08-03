import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, type ChatMessage, type Incident, type IncidentDetail } from "../api/client";
import { ErrorBanner, Loading, PageHeader, Severity, Status } from "../components/ui";

const SUGGESTIONS = [
  "What failed and why?",
  "What is the blast radius?",
  "What should I fix first?",
];

function truncate(text: string | null | undefined, max = 120) {
  if (!text) return "—";
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

export function IncidentsPage({ tenantId }: { tenantId: string }) {
  const [items, setItems] = useState<Incident[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<string>("");

  const [selected, setSelected] = useState<Incident | null>(null);
  const [detail, setDetail] = useState<IncidentDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string>("");
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
        const res = await api.incidents(tenantId, status || undefined);
        if (!cancelled) setItems(res.items);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tenantId, status]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, chatLoading]);

  useEffect(() => {
    if (!selected) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    (async () => {
      setDetailLoading(true);
      try {
        const res = await api.incident(tenantId, selected.incident_key);
        if (!cancelled) setDetail(res);
      } catch {
        if (!cancelled) setDetail(null);
      } finally {
        if (!cancelled) setDetailLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tenantId, selected]);

  async function startChat(incident: Incident) {
    setSelected(incident);
    setSessionId("");
    setMessages([]);
    setChatError(null);
    setChatLoading(true);
    try {
      const session = await api.startRcaChat(tenantId, incident.incident_key);
      setSessionId(session.session_id);
      setMessages(session.messages);
    } catch (e) {
      setChatError(e instanceof Error ? e.message : String(e));
    } finally {
      setChatLoading(false);
    }
  }

  async function sendMessage(text: string) {
    const message = text.trim();
    if (!message || !sessionId || chatLoading) return;
    setChatError(null);
    setDraft("");
    setChatLoading(true);
    setMessages((prev) => [
      ...prev,
      { role: "user", content: message, created_at: new Date().toISOString(), meta: {} },
    ]);
    try {
      const res = await api.sendRcaChatMessage(sessionId, message);
      setMessages(res.messages);
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

  const errorText =
    detail?.error_message ||
    detail?.latest_failure?.error_message ||
    detail?.summary ||
    selected?.summary ||
    null;
  const deepLink = detail?.latest_failure?.deep_link;
  const deepLinkLabel = detail?.latest_failure?.deep_link_label || "Open in ETL tool";

  if (loading) return <Loading />;

  return (
    <div>
      <PageHeader
        title="Incidents"
        subtitle="Error detail from metadata, then RCA chat. Use the native tool link for full logs."
        actions={
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All statuses</option>
            <option value="open">Open</option>
            <option value="triage">Triage</option>
            <option value="resolved">Resolved</option>
          </select>
        }
      />
      <ErrorBanner error={error} />

      <div className="split">
        <section className="panel">
          <table>
            <thead>
              <tr>
                <th>Title</th>
                <th>Error</th>
                <th>Type</th>
                <th>Severity</th>
                <th>Status</th>
                <th>Root asset</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((i) => (
                <tr
                  key={i.incident_key}
                  className={selected?.incident_key === i.incident_key ? "selected" : ""}
                >
                  <td>
                    <div className="cell-title">{i.title}</div>
                  </td>
                  <td className="error-cell">{truncate(i.error_message || i.summary)}</td>
                  <td>{i.monitor_type || "—"}</td>
                  <td>
                    <Severity value={i.severity} />
                  </td>
                  <td>
                    <Status value={i.status} />
                  </td>
                  <td className="mono">{i.root_asset_id || "—"}</td>
                  <td>
                    <button type="button" className="btn-link" onClick={() => startChat(i)}>
                      Chat RCA
                    </button>
                  </td>
                </tr>
              ))}
              {!items.length && (
                <tr>
                  <td colSpan={7} className="empty">
                    No incidents for this filter.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </section>

        <section className="panel rca-panel chat-panel">
          <div className="panel-head">
            <div>
              <h2>RCA chat</h2>
              {selected && (
                <p className="muted" style={{ margin: "4px 0 0" }}>
                  {selected.title}
                  {sessionId ? (
                    <span className="mono"> · session {sessionId.slice(0, 8)}</span>
                  ) : null}
                </p>
              )}
            </div>
          </div>

          {!selected && (
            <p className="empty">Pick an incident and click Chat RCA. You won’t need to enter IDs.</p>
          )}
          <ErrorBanner error={chatError} />

          {selected && (
            <>
              <div className="error-detail-panel">
                <h3>Error detail</h3>
                {detailLoading ? (
                  <p className="muted">Loading failure context…</p>
                ) : errorText ? (
                  <p className="error-detail-text">{errorText}</p>
                ) : (
                  <p className="muted">No error message stored for this incident yet.</p>
                )}
                {detail?.latest_failure && (
                  <p className="muted mono" style={{ marginTop: 8 }}>
                    {detail.latest_failure.pipeline_id}
                    {detail.latest_failure.task_id ? `.${detail.latest_failure.task_id}` : ""}
                    {detail.latest_failure.started_at ? ` · ${detail.latest_failure.started_at}` : ""}
                  </p>
                )}
                {deepLink && (
                  <a className="btn-link external-link" href={deepLink} target="_blank" rel="noreferrer">
                    {deepLinkLabel} ↗
                  </a>
                )}
                {!deepLink && detail?.latest_failure?.source_tool === "airflow" && (
                  <p className="muted" style={{ marginTop: 8 }}>
                    Set <span className="mono">AIRFLOW_BASE_URL</span> in Metadata API env for deep links.
                  </p>
                )}
              </div>

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
