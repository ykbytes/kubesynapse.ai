import { LoaderCircle, Send, Sparkles } from "lucide-react";

import type { AgentDiscoveryPeer, RuntimeKind, UiMessage } from "../types";

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
  a2aTargetAgent: string;
  a2aTargetNamespace: string;
  a2aTimeoutSeconds: string;
  discoveryPeers: AgentDiscoveryPeer[];
  discoveryLoading: boolean;
  discoveryError: string;
  gooseMaxTurns: string;
  gooseWorkingDirectory: string;
  gooseSystemPrompt: string;
  emptyMessage: string;
  error: string;
  onPromptChange: (value: string) => void;
  onToggleStreamMode: (value: boolean) => void;
  onToggleRequireApproval: (value: boolean) => void;
  onA2ATargetAgentChange: (value: string) => void;
  onA2ATargetNamespaceChange: (value: string) => void;
  onA2ATimeoutSecondsChange: (value: string) => void;
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
  a2aTargetAgent,
  a2aTargetNamespace,
  a2aTimeoutSeconds,
  discoveryPeers,
  discoveryLoading,
  discoveryError,
  gooseMaxTurns,
  gooseWorkingDirectory,
  gooseSystemPrompt,
  emptyMessage,
  error,
  onPromptChange,
  onToggleStreamMode,
  onToggleRequireApproval,
  onA2ATargetAgentChange,
  onA2ATargetNamespaceChange,
  onA2ATimeoutSecondsChange,
  onGooseMaxTurnsChange,
  onGooseWorkingDirectoryChange,
  onSubmit,
}: ChatWorkbenchProps) {
  const reachablePeers = discoveryPeers.filter((peer) => peer.reachable);
  const activePeerValue = a2aTargetAgent && a2aTargetNamespace ? `${a2aTargetNamespace}/${a2aTargetAgent}` : "";
  const a2aMode = Boolean(a2aTargetAgent && a2aTargetNamespace);

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

        {runtimeKind === "langgraph" ? (
          <section className="a2a-control-panel">
            <div className="card-title-row">
              <strong>Explicit A2A route</strong>
              <span className="warning-chip">{reachablePeers.length} reachable</span>
            </div>
            <label>
              <span>Discoverable peer</span>
              <select
                value={reachablePeers.some((peer) => `${peer.namespace}/${peer.name}` === activePeerValue) ? activePeerValue : ""}
                onChange={(event) => {
                  const nextValue = event.target.value;
                  if (!nextValue) {
                    onA2ATargetNamespaceChange("");
                    onA2ATargetAgentChange("");
                    return;
                  }
                  const separatorIndex = nextValue.indexOf("/");
                  onA2ATargetNamespaceChange(nextValue.slice(0, separatorIndex));
                  onA2ATargetAgentChange(nextValue.slice(separatorIndex + 1));
                }}
              >
                <option value="">Direct reply from selected agent</option>
                {reachablePeers.map((peer) => {
                  const value = `${peer.namespace}/${peer.name}`;
                  return (
                    <option key={value} value={value}>
                      {value} · {peer.runtime_kind ?? "runtime"} · {peer.model ?? "model"}
                    </option>
                  );
                })}
              </select>
            </label>
            <div className="a2a-control-grid">
              <label>
                <span>Target namespace</span>
                <input
                  className="compact-input"
                  placeholder="team-b"
                  value={a2aTargetNamespace}
                  onChange={(event) => onA2ATargetNamespaceChange(event.target.value)}
                />
              </label>
              <label>
                <span>Target agent</span>
                <input
                  className="compact-input"
                  placeholder="reviewer"
                  value={a2aTargetAgent}
                  onChange={(event) => onA2ATargetAgentChange(event.target.value)}
                />
              </label>
              <label>
                <span>Timeout seconds</span>
                <input
                  className="compact-input"
                  inputMode="decimal"
                  min="1"
                  placeholder="Use policy default"
                  type="number"
                  value={a2aTimeoutSeconds}
                  onChange={(event) => onA2ATimeoutSecondsChange(event.target.value)}
                />
              </label>
            </div>
            {discoveryLoading ? <p className="muted-copy">Loading discoverable peers...</p> : null}
            {discoveryError ? <p className="error-banner compact-banner">{discoveryError}</p> : null}
            {!discoveryLoading && !discoveryError && reachablePeers.length > 0 ? (
              <p className="hint-text">Discovery is derived from the caller policy allowlist and the callee inbound allowlist.</p>
            ) : null}
            {!discoveryLoading && !discoveryError && reachablePeers.length === 0 ? (
              <p className="warning-note">No reachable peers are configured right now. You can still enter a target manually for testing.</p>
            ) : null}
          </section>
        ) : null}

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
              : a2aMode
                ? "This request will route through the selected agent and explicitly invoke the configured A2A target."
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
