import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import { api, type ChatMessage, type LineageEdge } from "../api/client";

import { ErrorBanner, Loading, PageHeader } from "../components/ui";



const SUGGESTIONS = [

  "What is upstream of this dataset?",

  "What is the blast radius?",

  "Which quality checks are failing?",

];



export function LineagePage({ tenantId }: { tenantId: string }) {

  const [edges, setEdges] = useState<LineageEdge[]>([]);

  const [datasetId, setDatasetId] = useState("");

  const [blast, setBlast] = useState<string[]>([]);

  const [error, setError] = useState<string | null>(null);

  const [loading, setLoading] = useState(true);



  const [sessionId, setSessionId] = useState("");

  const [messages, setMessages] = useState<ChatMessage[]>([]);

  const [draft, setDraft] = useState("");

  const [chatLoading, setChatLoading] = useState(false);

  const [chatError, setChatError] = useState<string | null>(null);

  const [chatDataset, setChatDataset] = useState("");

  const bottomRef = useRef<HTMLDivElement | null>(null);



  const datasets = useMemo(() => {

    const ids = new Set<string>();

    for (const e of edges) {

      ids.add(e.upstream_dataset_id);

      ids.add(e.downstream_dataset_id);

    }

    return Array.from(ids).sort();

  }, [edges]);



  useEffect(() => {

    let cancelled = false;

    (async () => {

      setLoading(true);

      try {

        const res = await api.lineage(tenantId);

        if (!cancelled) setEdges(res.items);

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



  async function loadBlast() {

    if (!datasetId.trim()) return;

    setError(null);

    try {

      const res = await api.blastRadius(tenantId, datasetId.trim());

      setBlast(res.downstream);

    } catch (e) {

      setError(e instanceof Error ? e.message : String(e));

    }

  }



  async function startChat(ds: string) {

    const id = ds.trim();

    if (!id) return;

    setChatDataset(id);

    setDatasetId(id);

    setSessionId("");

    setMessages([]);

    setChatError(null);

    setChatLoading(true);

    try {

      const [session, blastRes] = await Promise.all([

        api.startDqChat(tenantId, id),

        api.blastRadius(tenantId, id).catch(() => ({ downstream: [] as string[] })),

      ]);

      setSessionId(session.session_id);

      setMessages(session.messages);

      setBlast(blastRes.downstream);

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

      const res = await api.sendDqChatMessage(sessionId, message);

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



  if (loading) return <Loading />;



  return (

    <div>

      <PageHeader

        title="Lineage"

        subtitle="Upstream → downstream edges, blast radius, and DQ + Lineage chat grounded in Metadata."

      />

      <ErrorBanner error={error} />



      <div className="split">

        <div>

          <section className="panel">

            <div className="panel-head">

              <h2>Blast radius</h2>

            </div>

            <div className="blast-form">

              <input

                placeholder="dataset_id e.g. ANALYTICS.RAW.ORDERS"

                value={datasetId}

                onChange={(e) => setDatasetId(e.target.value)}

                list="lineage-datasets"

              />

              <datalist id="lineage-datasets">

                {datasets.map((d) => (

                  <option key={d} value={d} />

                ))}

              </datalist>

              <button type="button" onClick={loadBlast}>

                Compute

              </button>

              <button type="button" className="btn-primary" onClick={() => startChat(datasetId)} disabled={!datasetId.trim()}>

                Explain DQ

              </button>

            </div>

            {blast.length > 0 && (

              <ul className="blast-list">

                {blast.map((d) => (

                  <li key={d} className="mono">

                    {d}

                  </li>

                ))}

              </ul>

            )}

            {datasetId && blast.length === 0 && (

              <p className="muted">No downstream assets found for this dataset.</p>

            )}

          </section>



          <section className="panel">

            <div className="panel-head">

              <h2>Edges</h2>

            </div>

            <table>

              <thead>

                <tr>

                  <th>Upstream</th>

                  <th>Downstream</th>

                  <th>Confidence</th>

                  <th>Transform</th>

                  <th></th>

                </tr>

              </thead>

              <tbody>

                {edges.map((e) => (

                  <tr key={`${e.upstream_dataset_id}->${e.downstream_dataset_id}`}>

                    <td className="mono">{e.upstream_dataset_id}</td>

                    <td className="mono">{e.downstream_dataset_id}</td>

                    <td>{e.confidence}</td>

                    <td>{e.transform || "—"}</td>

                    <td>

                      <button

                        type="button"

                        className="btn-link"

                        onClick={() => startChat(e.upstream_dataset_id)}

                      >

                        Explain

                      </button>

                    </td>

                  </tr>

                ))}

                {!edges.length && (

                  <tr>

                    <td colSpan={5} className="empty">

                      No lineage edges yet.

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

              {chatDataset && (

                <p className="muted" style={{ margin: "4px 0 0" }}>

                  <span className="mono">{chatDataset}</span>

                  {sessionId ? <span className="mono"> · session {sessionId.slice(0, 8)}</span> : null}

                </p>

              )}

            </div>

          </div>



          {!chatDataset && (

            <p className="empty">Enter a dataset and click Explain DQ, or Explain on an edge.</p>

          )}

          <ErrorBanner error={chatError} />



          {chatDataset && (

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


