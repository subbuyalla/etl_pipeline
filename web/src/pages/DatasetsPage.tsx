import { useEffect, useRef, useState, type FormEvent } from "react";

import { api, type ChatMessage, type Dataset } from "../api/client";

import { ErrorBanner, Loading, PageHeader } from "../components/ui";



const SUGGESTIONS = [

  "Which checks failed?",

  "What is the blast radius?",

  "What should I fix first?",

];



export function DatasetsPage({ tenantId }: { tenantId: string }) {

  const [items, setItems] = useState<Dataset[]>([]);

  const [error, setError] = useState<string | null>(null);

  const [loading, setLoading] = useState(true);



  const [selected, setSelected] = useState<string>("");

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

        const res = await api.datasets(tenantId);

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

  }, [tenantId]);



  useEffect(() => {

    bottomRef.current?.scrollIntoView({ behavior: "smooth" });

  }, [messages, chatLoading]);



  async function startChat(datasetId: string) {

    setSelected(datasetId);

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

        title="Datasets"

        subtitle="Catalog of tables and assets. Open Explain DQ to analyze quality checks and lineage blast radius."

      />

      <ErrorBanner error={error} />



      <div className="split">

        <section className="panel">

          <table>

            <thead>

              <tr>

                <th>Dataset</th>

                <th>Platform</th>

                <th>Rows</th>

                <th>Last updated</th>

                <th></th>

              </tr>

            </thead>

            <tbody>

              {items.map((d) => (

                <tr key={d.dataset_id} className={selected === d.dataset_id ? "selected" : ""}>

                  <td className="mono">{d.dataset_id}</td>

                  <td>{d.platform}</td>

                  <td>{d.row_count ?? "—"}</td>

                  <td className="mono">{d.last_updated_at || "—"}</td>

                  <td>

                    <button type="button" className="btn-link" onClick={() => startChat(d.dataset_id)}>

                      Explain DQ

                    </button>

                  </td>

                </tr>

              ))}

              {!items.length && (

                <tr>

                  <td colSpan={5} className="empty">

                    No datasets yet.

                  </td>

                </tr>

              )}

            </tbody>

          </table>

        </section>



        <section className="panel rca-panel chat-panel">

          <div className="panel-head">

            <div>

              <h2>DQ + Lineage chat</h2>

              {selected && (

                <p className="muted" style={{ margin: "4px 0 0" }}>

                  <span className="mono">{selected}</span>

                  {sessionId ? <span className="mono"> · session {sessionId.slice(0, 8)}</span> : null}

                </p>

              )}

            </div>

          </div>



          {!selected && <p className="empty">Pick a dataset and click Explain DQ.</p>}

          <ErrorBanner error={chatError} />



          {selected && (

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


