import { Bot, RefreshCw, ShieldCheck } from "lucide-react";

import type { AgentInfo } from "../types";

interface AgentSidebarProps {
  agents: AgentInfo[];
  selectedAgentName: string;
  loading: boolean;
  emptyMessage: string;
  onRefresh: () => void;
  onSelect: (agentName: string) => void;
}

export function AgentSidebar({
  agents,
  selectedAgentName,
  loading,
  emptyMessage,
  onRefresh,
  onSelect,
}: AgentSidebarProps) {
  return (
    <aside className="panel panel-sidebar">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Workspace Agents</p>
          <h2>Runtime Catalog</h2>
        </div>
        <button className="icon-button" type="button" onClick={onRefresh} disabled={loading}>
          <RefreshCw size={16} className={loading ? "spin" : ""} />
        </button>
      </div>

      <div className="agent-list">
        {agents.length === 0 ? (
          <div className="empty-state compact">
            <Bot size={18} />
            <p>{emptyMessage}</p>
          </div>
        ) : null}

        {agents.map((agent) => (
          <button
            key={agent.name}
            type="button"
            className={`agent-card ${selectedAgentName === agent.name ? "selected" : ""}`}
            onClick={() => onSelect(agent.name)}
          >
            <div className="agent-card-header">
              <div>
                <strong>{agent.name}</strong>
                <span>{agent.model}</span>
              </div>
              <span className={`status-pill status-${agent.status}`}>{agent.status}</span>
            </div>
            <div className="agent-card-footer">
              <span>{agent.namespace}</span>
              <span className="inline-meta">
                <ShieldCheck size={14} /> singleton
              </span>
            </div>
          </button>
        ))}
      </div>
    </aside>
  );
}
