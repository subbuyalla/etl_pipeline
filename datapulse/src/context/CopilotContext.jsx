import { createContext, useContext, useState, useEffect, useCallback } from 'react';

const CopilotContext = createContext(null);

export function CopilotProvider({ children }) {
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState([
    {
      id: 'welcome',
      role: 'assistant',
      content: "👋 Hi! I'm **DataPulse Copilot**.\n\nI can help you diagnose pipeline failures, analyze data quality issues, inspect SLAs, and take operational actions.\n\nTry asking a question below or click any of the suggested prompt chips!",
      actions: [
        { label: 'Pipeline Health Summary', query: 'Give me a weekly summary of pipeline health' },
        { label: 'Check Data Quality', query: 'Explain data quality status' },
      ],
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    },
  ]);
  const [isLoading, setIsLoading] = useState(false);
  const [activeContext, setActiveContext] = useState({});
  const [suggestions, setSuggestions] = useState([]);

  // Fetch dynamic suggestions when context changes or drawer opens
  const refreshSuggestions = useCallback(async (ctx) => {
    try {
      const res = await fetch('/api/v1/copilot/suggestions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ context: ctx || activeContext }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.ok && Array.isArray(data.suggestions)) {
          setSuggestions(data.suggestions);
        }
      }
    } catch {
      // Ignore background suggestion failures
    }
  }, [activeContext]);

  useEffect(() => {
    if (isOpen) {
      refreshSuggestions(activeContext);
    }
  }, [isOpen, activeContext, refreshSuggestions]);

  const sendMessage = useCallback(async (text, overrideContext = null) => {
    if (!text || !text.trim()) return;
    const userText = text.trim();
    const effectiveContext = { ...activeContext, ...(overrideContext || {}) };

    const userMsg = {
      id: `user_${Date.now()}`,
      role: 'user',
      content: userText,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    };

    setMessages((prev) => [...prev, userMsg]);
    setIsLoading(true);

    try {
      const res = await fetch('/api/v1/copilot/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: userText,
          context: effectiveContext,
          history: messages.slice(-6).map((m) => ({ role: m.role, content: m.content })),
        }),
      });

      if (!res.ok) {
        throw new Error(`Server returned HTTP ${res.status}`);
      }

      const data = await res.json();
      const assistantMsg = {
        id: `assistant_${Date.now()}`,
        role: 'assistant',
        content: data.response || 'No response generated.',
        intent: data.intent,
        actions: data.actions || [],
        data: data.data,
        thought_trace: data.thought_trace || [],
        pending_approval: data.pending_approval || null,
        session_id: data.session_id || null,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      };

      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id: `err_${Date.now()}`,
          role: 'assistant',
          content: `⚠️ **Error communicating with Copilot:** ${err.message}`,
          isError: true,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  }, [activeContext, messages]);

  const approvePendingAction = useCallback(async (actionId, approved = true) => {
    setIsLoading(true);
    try {
      const res = await fetch('/api/v1/copilot/approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action_id: actionId, approved }),
      });
      const data = await res.json();
      if (data.ok) {
        setMessages((prev) => [
          ...prev,
          {
            id: `approval_${Date.now()}`,
            role: 'assistant',
            content: approved
              ? `✅ **Action Approved & Executed:** ${data.message || 'The operational change has been committed.'}`
              : `❌ **Action Rejected:** The proposed action was cancelled by user.`,
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          },
        ]);
      } else {
        throw new Error(data.error || 'Action approval failed');
      }
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id: `approval_err_${Date.now()}`,
          role: 'assistant',
          content: `❌ **Approval Error:** ${err.message}`,
          isError: true,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const executeAction = useCallback(async (actionType, payload) => {
    setIsLoading(true);
    try {
      const res = await fetch('/api/v1/copilot/action', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action_type: actionType, payload }),
      });
      const data = await res.json();
      if (data.ok) {
        setMessages((prev) => [
          ...prev,
          {
            id: `action_${Date.now()}`,
            role: 'assistant',
            content: `⚡ **Action Executed:** ${data.message || 'Operation completed successfully.'}`,
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          },
        ]);
      } else {
        throw new Error(data.error || 'Action failed');
      }
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id: `action_err_${Date.now()}`,
          role: 'assistant',
          content: `❌ **Action Failed:** ${err.message}`,
          isError: true,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const openCopilot = useCallback((initialPrompt = null, contextData = {}) => {
    if (contextData && Object.keys(contextData).length > 0) {
      setActiveContext((prev) => ({ ...prev, ...contextData }));
    }
    setIsOpen(true);
    if (initialPrompt) {
      // Send immediately
      setTimeout(() => {
        sendMessage(initialPrompt, contextData);
      }, 50);
    }
  }, [sendMessage]);

  const closeCopilot = useCallback(() => setIsOpen(false), []);
  const toggleCopilot = useCallback(() => setIsOpen((prev) => !prev), []);

  const clearMessages = useCallback(() => {
    setMessages([
      {
        id: `welcome_${Date.now()}`,
        role: 'assistant',
        content: "Conversation history cleared. How can I assist you with your pipelines or data today?",
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      },
    ]);
  }, []);

  return (
    <CopilotContext.Provider
      value={{
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
        refreshSuggestions,
        executeAction,
        approvePendingAction,
        clearMessages,
      }}
    >
      {children}
    </CopilotContext.Provider>
  );
}

export function useCopilot() {
  const ctx = useContext(CopilotContext);
  if (!ctx) {
    throw new Error('useCopilot must be used within a CopilotProvider');
  }
  return ctx;
}
