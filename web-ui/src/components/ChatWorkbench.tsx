import { LoaderCircle, Send, Sparkles } from "lucide-react";

import type { RuntimeKind, UiMessage } from "../types";

interface ChatWorkbenchProps {
  agentName: string;
  runtimeKind: RuntimeKind;
  prompt: string;
  messages: UiMessage[];
  isSending: boolean;
  tokenReady: boolean;
  streamMode: boolean;
  requireApproval: boolean;
  approvalSupported: boolean;
  gooseMaxTurns: string;
  gooseWorkingDirectory: string;
  gooseSystemPrompt: string;
  emptyMessage: string;
  error: string;
  onPromptChange: (value: string) => void;
  onToggleStreamMode: (value: boolean) => void;
  onToggleRequireApproval: (value: boolean) => void;
  onGooseMaxTurnsChange: (value: string) => void;
  onGooseWorkingDirectoryChange: (value: string) => void;
  onSubmit: () => void;
}

export function ChatWorkbench({
  agentName,
  runtimeKind,
  prompt,
  messages,
  isSending,
  tokenReady,
  streamMode,
  requireApproval,
  approvalSupported,
  gooseMaxTurns,
  gooseWorkingDirectory,
  gooseSystemPrompt,
  emptyMessage,
  error,
  onPromptChange,
  onToggleStreamMode,
  onToggleRequireApproval,
  onGooseMaxTurnsChange,
  onGooseWorkingDirectoryChange,
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

        {runtimeKind === "goose" ? (
          <section className="goose-control-panel">
            <div className="card-title-row">
              <strong>Goose run controls</strong>
              <span className="warning-chip">safe subset</span>
            </div>
            <div className="goose-control-grid">
              <label>
                <span>Max turns</span>
                <input
                  className="compact-input"
                  inputMode="numeric"
                  min="1"
                  placeholder="Use runtime default"
                  type="number"
                  value={gooseMaxTurns}
                  onChange={(event) => onGooseMaxTurnsChange(event.target.value)}
                />
              </label>
              <label>
                <span>Working directory</span>
                <input
                  className="compact-input"
                  placeholder="workspace/subdir"
                  value={gooseWorkingDirectory}
                  onChange={(event) => onGooseWorkingDirectoryChange(event.target.value)}
                />
              </label>
            </div>
            <label className="goose-system-preview">
              <span>Agent system prompt</span>
              <textarea className="prompt-input goose-system-input" readOnly rows={4} value={gooseSystemPrompt} />
            </label>
            <p className="warning-note">
              Goose request-level system overrides stay locked in the UI. Edit the agent definition if you need to change this prompt.
            </p>
          </section>
        ) : null}

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
            {!tokenReady
              ? "Enter a gateway token before sending chat requests."
              : approvalSupported
              ? "The UI sends authenticated requests through the API gateway and keeps the last thread per selected agent."
              : "Goose agents stay chat-first in the UI. Per-run max turns and workspace-relative directories are available here, while approvals and direct tool-routing remain LangGraph-only."}
          </p>
          <button className="primary-button" type="button" onClick={onSubmit} disabled={!agentName || !prompt.trim() || !tokenReady || isSending}>
            {isSending ? <LoaderCircle size={16} className="spin" /> : <Send size={16} />}
            <span>{isSending ? "Working" : "Send"}</span>
          </button>
        </div>
      </div>
    </section>
  );
}
