import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import { api, type ChatMessage } from "../api/client";
import { ErrorBanner, PageHeader } from "../components/ui";

const SUGGESTIONS = [
  "What should I look at first?",
  "Which pipelines are failing?",
  "Summarize open incidents",
  "Where are the highest severity issues?",
];

export function ObservabilityPage({ tenantId }: { tenantId: string }) {
  const [sessionId, setSessionId] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    setSessionId("");
    setMessages([]);
    setDraft("");
    setChatError(null);
    setChatLoading(false);
  }, [tenantId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, chatLoading]);

  async function ask(question?: string) {
    const q = (question ?? draft).trim();
    if (chatLoading) return;
    if (!q && sessionId) return;

    setChatError(null);
    setChatLoading(true);
    setDraft("");

    try {
      if (!sessionId) {
        const session = await api.startObservabilityChat(tenantId, q || undefined);
        setSessionId(session.session_id);
        setMessages(session.messages);
      } else {
        const turn = await api.sendObservabilityChatMessage(sessionId, q);
        setMessages(turn.messages);
      }
    } catch (e) {
      setChatError(e instanceof Error ? e.message : String(e));
    } finally {
      setChatLoading(false);
      inputRef.current?.focus();
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void ask(draft);
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void ask(draft);
    }
  }

  function newChat() {
    setSessionId("");
    setMessages([]);
    setChatError(null);
    setDraft("");
    inputRef.current?.focus();
  }

  return (
    <div className="obs-page">
      <PageHeader
        title="Observability assistant"
        subtitle="Tenant-wide reliability Q&A — incidents, pipelines, alerts. Full answers scroll below."
        actions={
          <span className="obs-header-actions">
            <Link className="btn-link" to="/">
              ← Overview
            </Link>
            {sessionId ? (
              <button type="button" className="chip-btn" onClick={newChat} disabled={chatLoading}>
                New chat
              </button>
            ) : null}
          </span>
        }
      />

      <ErrorBanner error={chatError} />

      <section className="panel obs-chat-shell">
        <div className="obs-chat-thread">
          {!messages.length && !chatLoading && (
            <div className="obs-welcome">
              <h2>How can I help?</h2>
              <p className="muted">
                Ask in plain English. Answers appear in this panel — nothing is squeezed next to charts.
              </p>
              <div className="chat-suggestions obs-welcome-chips">
                {SUGGESTIONS.map((s) => (
                  <button key={s} type="button" className="chip-btn" onClick={() => void ask(s)} disabled={chatLoading}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m, idx) => (
            <div key={`${m.created_at}-${idx}`} className={`chat-bubble obs-bubble ${m.role}`}>
              <div className="chat-role">{m.role === "user" ? "You" : "Observability"}</div>
              <div className="chat-content">{m.content}</div>
            </div>
          ))}
          {chatLoading && <div className="muted chat-waiting">Thinking…</div>}
          <div ref={bottomRef} />
        </div>

        <form className="chat-compose obs-compose" onSubmit={onSubmit}>
          <textarea
            ref={inputRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Ask about reliability… (Enter to send, Shift+Enter for newline)"
            disabled={chatLoading}
            rows={2}
            autoFocus
          />
          <button type="submit" disabled={chatLoading || !draft.trim()}>
            {chatLoading ? "…" : "Ask"}
          </button>
        </form>
      </section>
    </div>
  );
}
