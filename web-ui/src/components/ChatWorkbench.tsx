import { LoaderCircle, Send, Sparkles } from "lucide-react";

import type { UiMessage } from "../types";

interface ChatWorkbenchProps {
  agentName: string;
  prompt: string;
  messages: UiMessage[];
  isSending: boolean;
  streamMode: boolean;
  requireApproval: boolean;
  approvalSupported: boolean;
  emptyMessage: string;
  error: string;
  onPromptChange: (value: string) => void;
  onToggleStreamMode: (value: boolean) => void;
  onToggleRequireApproval: (value: boolean) => void;
  onSubmit: () => void;
}

export function ChatWorkbench({
  agentName,
  prompt,
  messages,
  isSending,
  streamMode,
  requireApproval,
  approvalSupported,
  emptyMessage,
  error,
  onPromptChange,
  onToggleStreamMode,
  onToggleRequireApproval,
  onSubmit,
}: ChatWorkbenchProps) {
  return (
    <section className="panel panel-chat">
      <div className="panel-header panel-header-chat">
        <div>
          <p className="eyebrow">Conversation Surface</p>
          <h2>{agentName ? `${agentName} Console` : "Choose an agent"}</h2>
        </div>
        <span className={`mode-pill ${streamMode ? "live" : "sync"}`}>{streamMode ? "streaming" : "single-shot"}</span>
      </div>

      <div className="message-stack">
        {messages.length === 0 ? (
          <div className="empty-state">
            <Sparkles size={22} />
            <p>{emptyMessage}</p>
          </div>
        ) : null}

        {messages.map((message) => (
          <article key={message.id} className={`message-bubble role-${message.role}`}>
            <header>
              <span>{message.role}</span>
              <small>{message.status ?? "complete"}</small>
            </header>
            <pre>{message.content || (message.status === "streaming" ? "Waiting for model output..." : "")}</pre>
          </article>
        ))}
      </div>

      <div className="composer-shell">
        <div className="toggle-row">
          <label className="toggle-chip">
            <input
              checked={streamMode}
              type="checkbox"
              onChange={(event) => onToggleStreamMode(event.target.checked)}
            />
            <span>Stream responses</span>
          </label>
          <label className="toggle-chip">
            <input
              checked={requireApproval}
              disabled={!approvalSupported}
              type="checkbox"
              onChange={(event) => onToggleRequireApproval(event.target.checked)}
            />
            <span>{approvalSupported ? "Require approval" : "Require approval (LangGraph only)"}</span>
          </label>
        </div>

        <textarea
          className="prompt-input"
          placeholder="Ask the agent to plan, invoke tools, or reason over retrieved context..."
          value={prompt}
          onChange={(event) => onPromptChange(event.target.value)}
          rows={5}
        />

        {error ? <p className="error-banner">{error}</p> : null}

        <div className="composer-actions">
          <p className="hint-text">
            {approvalSupported
              ? "The UI sends authenticated requests through the API gateway and keeps the last thread per selected agent."
              : "Goose agents currently run in chat-first mode. Approval and direct tool-routing remain on the LangGraph runtime."}
          </p>
          <button className="primary-button" type="button" onClick={onSubmit} disabled={!agentName || !prompt.trim() || isSending}>
            {isSending ? <LoaderCircle size={16} className="spin" /> : <Send size={16} />}
            <span>{isSending ? "Working" : "Send"}</span>
          </button>
        </div>
      </div>
    </section>
  );
}
