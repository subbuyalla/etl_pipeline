import { useState, useRef, useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { useCopilot } from '../context/CopilotContext';
import '../styles/CopilotDrawer.css';

// Lightweight safe Markdown renderer for copilot chat
function renderMarkdown(text) {
  if (!text) return null;

  // Split lines to detect tables, headers, lists, code
  const lines = text.split('\n');
  const elements = [];
  let tableRows = [];
  let inCodeBlock = false;
  let codeBlockLines = [];

  const flushTable = (keyPrefix) => {
    if (tableRows.length === 0) return null;
    const rows = [...tableRows];
    tableRows = [];

    // Parse header and rows
    const headerRow = rows[0];
    const dataRows = rows.slice(1).filter((r) => !r.includes('---'));

    const parseCells = (rowStr) =>
      rowStr
        .split('|')
        .slice(1, -1)
        .map((c) => c.trim());

    const headers = parseCells(headerRow);

    return (
      <div className="table-responsive" key={`table_${keyPrefix}`}>
        <table>
          <thead>
            <tr>
              {headers.map((h, i) => (
                <th key={i}>{formatInline(h)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {dataRows.map((r, ri) => {
              const cells = parseCells(r);
              return (
                <tr key={ri}>
                  {cells.map((c, ci) => (
                    <td key={ci}>{formatInline(c)}</td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    );
  };

  const flushCode = (keyPrefix) => {
    if (codeBlockLines.length === 0) return null;
    const content = codeBlockLines.join('\n');
    codeBlockLines = [];
    return (
      <pre key={`code_${keyPrefix}`}>
        <code>{content}</code>
      </pre>
    );
  };

  const formatInline = (str) => {
    if (!str) return '';
    // Format bold **text** and `code`
    const parts = [];
    let remaining = str;
    let idx = 0;

    // Very simple inline formatter for bold and backticks
    const tokenRegex = /(\*\*.*?\*\*|`.*?`)/g;
    let match;
    let lastIndex = 0;

    while ((match = tokenRegex.exec(str)) !== null) {
      if (match.index > lastIndex) {
        parts.push(str.substring(lastIndex, match.index));
      }
      const token = match[0];
      if (token.startsWith('**') && token.endsWith('**')) {
        parts.push(<strong key={idx++}>{token.slice(2, -2)}</strong>);
      } else if (token.startsWith('`') && token.endsWith('`')) {
        parts.push(<code key={idx++}>{token.slice(1, -1)}</code>);
      }
      lastIndex = match.index + token.length;
    }

    if (lastIndex < str.length) {
      parts.push(str.substring(lastIndex));
    }
    return parts.length > 0 ? parts : str;
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // Code block toggle
    if (line.trim().startsWith('```')) {
      if (inCodeBlock) {
        inCodeBlock = false;
        elements.push(flushCode(i));
      } else {
        inCodeBlock = true;
      }
      continue;
    }

    if (inCodeBlock) {
      codeBlockLines.push(line);
      continue;
    }

    // Tables
    if (line.trim().startsWith('|') && line.trim().endsWith('|')) {
      tableRows.push(line);
      continue;
    } else if (tableRows.length > 0) {
      elements.push(flushTable(i));
    }

    // Headers
    if (line.startsWith('### ')) {
      elements.push(<h3 key={i}>{formatInline(line.replace('### ', ''))}</h3>);
    } else if (line.startsWith('#### ')) {
      elements.push(<h4 key={i}>{formatInline(line.replace('#### ', ''))}</h4>);
    } else if (line.startsWith('> ')) {
      elements.push(<blockquote key={i}>{formatInline(line.replace('> ', ''))}</blockquote>);
    } else if (line.trim().startsWith('- ') || line.trim().startsWith('* ')) {
      elements.push(
        <ul key={i}>
          <li>{formatInline(line.trim().slice(2))}</li>
        </ul>
      );
    } else if (/^\d+\.\s/.test(line.trim())) {
      elements.push(
        <ol key={i}>
          <li>{formatInline(line.trim().replace(/^\d+\.\s/, ''))}</li>
        </ol>
      );
    } else if (line.trim()) {
      elements.push(<p key={i}>{formatInline(line)}</p>);
    }
  }

  if (tableRows.length > 0) {
    elements.push(flushTable('end'));
  }
  if (codeBlockLines.length > 0) {
    elements.push(flushCode('end'));
  }

  return elements;
}

function ThoughtTrace({ trace }) {
  const [expanded, setExpanded] = useState(false);
  if (!trace || trace.length === 0) return null;

  return (
    <div className="copilot-thought-accordion">
      <button
        type="button"
        className="copilot-thought-toggle"
        onClick={() => setExpanded(!expanded)}
      >
        <span className="copilot-thought-title">
          🧠 Autonomous Reasoning ({trace.length} step{trace.length !== 1 ? 's' : ''})
        </span>
        <span className="copilot-thought-icon">{expanded ? '▲' : '▼'}</span>
      </button>

      {expanded && (
        <div className="copilot-thought-steps">
          {trace.map((t, idx) => (
            <div key={idx} className="copilot-thought-step">
              <div className="copilot-step-meta">
                <span className="copilot-agent-badge">{t.agent || 'Agent'}</span>
                {t.tool && <span className="copilot-tool-badge">⚡ {t.tool}</span>}
              </div>
              {t.thought && <div className="copilot-step-thought">{t.thought}</div>}
              {t.observation && <div className="copilot-step-obs">Observed: {t.observation}</div>}
              {t.reflection && <div className="copilot-step-reflect">Reflection: {t.reflection}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ApprovalCard({ approval, onDecision, disabled }) {
  if (!approval) return null;
  return (
    <div className="copilot-approval-card">
      <div className="copilot-approval-header">
        <span className="copilot-approval-badge">⚠️ Human-in-the-Loop Gateway</span>
      </div>
      <div className="copilot-approval-title">{approval.title || 'Approve Operational Mutation?'}</div>
      {approval.summary && <div className="copilot-approval-summary">{approval.summary}</div>}
      <div className="copilot-approval-buttons">
        <button
          type="button"
          className="copilot-btn-approve"
          onClick={() => onDecision(approval.action_id, true)}
          disabled={disabled}
        >
          ✅ Approve Action
        </button>
        <button
          type="button"
          className="copilot-btn-reject"
          onClick={() => onDecision(approval.action_id, false)}
          disabled={disabled}
        >
          ❌ Cancel
        </button>
      </div>
    </div>
  );
}

export default function CopilotDrawer() {
  const location = useLocation();
  const {
    isOpen,
    openCopilot,
    closeCopilot,
    toggleCopilot,
    activeContext,
    setActiveContext,
    messages,
    sendMessage,
    isLoading,
    suggestions,
    executeAction,
    approvePendingAction,
    clearMessages,
  } = useCopilot();

  const [input, setInput] = useState('');
  const chatBodyRef = useRef(null);

  // Sync route into active context automatically
  useEffect(() => {
    setActiveContext((prev) => ({
      ...prev,
      route: location.pathname,
    }));
  }, [location.pathname, setActiveContext]);

  // Scroll to bottom on message updates
  useEffect(() => {
    if (chatBodyRef.current) {
      chatBodyRef.current.scrollTop = chatBodyRef.current.scrollHeight;
    }
  }, [messages, isLoading]);

  const handleSubmit = (e) => {
    e?.preventDefault();
    if (!input.trim() || isLoading) return;
    const query = input;
    setInput('');
    sendMessage(query);
  };

  const handleActionClick = (action) => {
    if (action.query) {
      sendMessage(action.query);
    } else if (action.type && action.payload) {
      executeAction(action.type, action.payload);
    }
  };

  // Human-readable context label
  const getContextLabel = () => {
    const route = location.pathname;
    if (route.includes('data-quality')) return 'Data Quality';
    if (route.includes('incidents')) return 'Incidents';
    if (route.includes('freshness')) return 'Freshness & SLA';
    if (route.includes('volume')) return 'Volume';
    if (route.includes('schema')) return 'Schema Drift';
    if (route.includes('lineage')) return 'Lineage';
    if (route.includes('pipelines')) return 'Pipelines';
    if (route.includes('integrations')) return 'Integrations';
    return 'Overview';
  };

  return (
    <>
      {/* Floating Launcher Button */}
      {!isOpen && (
        <button
          className="copilot-launcher-btn"
          onClick={() => openCopilot()}
          title="Open DataPulse AI Copilot"
        >
          <span className="copilot-launcher-icon">✨</span>
          <span>Copilot</span>
          <span className="copilot-context-dot" title="Connected to active context" />
        </button>
      )}

      {/* Backdrop */}
      <div
        className={`copilot-backdrop ${isOpen ? 'open' : ''}`}
        onClick={closeCopilot}
        aria-hidden="true"
      />

      {/* Slide-out Drawer */}
      <div className={`copilot-drawer ${isOpen ? 'open' : ''}`}>
        {/* Header */}
        <div className="copilot-header">
          <div className="copilot-title-group">
            <div className="copilot-badge-icon">✨</div>
            <div className="copilot-title-text">
              <h3>DataPulse Copilot</h3>
              <span className="copilot-context-pill">
                📍 {getContextLabel()}
                {activeContext.active_pipeline_id ? ` · ${activeContext.active_pipeline_id}` : ''}
              </span>
            </div>
          </div>
          <div className="copilot-header-actions">
            <button
              className="copilot-icon-btn"
              onClick={clearMessages}
              title="Clear chat history"
            >
              🧹
            </button>
            <button
              className="copilot-icon-btn"
              onClick={closeCopilot}
              title="Close Copilot"
            >
              ✕
            </button>
          </div>
        </div>

        {/* Message Thread */}
        <div className="copilot-body" ref={chatBodyRef}>
          {messages.map((msg) => (
            <div key={msg.id} className={`copilot-message ${msg.role}`}>
              <div className="copilot-bubble">
                {/* Autonomous Thought Trace Accordion */}
                {msg.thought_trace && msg.thought_trace.length > 0 && (
                  <ThoughtTrace trace={msg.thought_trace} />
                )}

                <div className="copilot-markdown">{renderMarkdown(msg.content)}</div>

                {/* Human-in-the-Loop Approval Card */}
                {msg.pending_approval && (
                  <ApprovalCard
                    approval={msg.pending_approval}
                    onDecision={approvePendingAction}
                    disabled={isLoading}
                  />
                )}

                {/* Action Buttons / Interactive Chips */}
                {msg.actions && msg.actions.length > 0 && (
                  <div className="copilot-actions-bar">
                    {msg.actions.map((act, idx) => (
                      <button
                        key={idx}
                        className="copilot-action-btn"
                        onClick={() => handleActionClick(act)}
                        disabled={isLoading}
                      >
                        ⚡ {act.label}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <span className="copilot-msg-meta">{msg.timestamp}</span>
            </div>
          ))}

          {/* Typing Indicator */}
          {isLoading && (
            <div className="copilot-message assistant">
              <div className="copilot-bubble copilot-typing">
                <div className="copilot-dot" />
                <div className="copilot-dot" />
                <div className="copilot-dot" />
              </div>
            </div>
          )}
        </div>

        {/* Dynamic Contextual Prompt Suggestions */}
        {suggestions && suggestions.length > 0 && (
          <div className="copilot-suggestions-section">
            <span className="copilot-suggestions-label">Suggested Prompts</span>
            <div className="copilot-suggestions-chips">
              {suggestions.map((sug, idx) => (
                <button
                  key={idx}
                  className="copilot-suggestion-chip"
                  onClick={() => sendMessage(sug)}
                  disabled={isLoading}
                >
                  💬 {sug}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Input Footer */}
        <div className="copilot-footer">
          <form className="copilot-input-box" onSubmit={handleSubmit}>
            <input
              type="text"
              className="copilot-input-field"
              placeholder={`Ask Copilot about ${getContextLabel().toLowerCase()}...`}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={isLoading}
            />
            <button
              type="submit"
              className="copilot-send-btn"
              disabled={!input.trim() || isLoading}
              title="Send message"
            >
              ➤
            </button>
          </form>
        </div>
      </div>
    </>
  );
}
