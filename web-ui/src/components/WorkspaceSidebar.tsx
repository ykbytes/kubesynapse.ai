import { Bot, FlaskConical, GitBranch, Plus, RefreshCw } from "lucide-react";

import type { WorkspaceView } from "../types";

export interface SidebarResourceItem {
  id: string;
  title: string;
  subtitle: string;
  status: string;
  note?: string;
}

interface WorkspaceSidebarProps {
  activeView: WorkspaceView;
  counts: Record<WorkspaceView, number>;
  items: SidebarResourceItem[];
  selectedId: string;
  loading: boolean;
  emptyMessage: string;
  onViewChange: (view: WorkspaceView) => void;
  onRefresh: () => void;
  onSelect: (id: string) => void;
  onCreateNew: () => void;
}

const VIEW_META: Record<WorkspaceView, { label: string; title: string; icon: typeof Bot }> = {
  agents: { label: "Agents", title: "Runtime Catalog", icon: Bot },
  workflows: { label: "Workflows", title: "Workflow Catalog", icon: GitBranch },
  evals: { label: "Evaluations", title: "Evaluation Catalog", icon: FlaskConical },
};

export function WorkspaceSidebar({
  activeView,
  counts,
  items,
  selectedId,
  loading,
  emptyMessage,
  onViewChange,
  onRefresh,
  onSelect,
  onCreateNew,
}: WorkspaceSidebarProps) {
  const viewMeta = VIEW_META[activeView];
  const EmptyIcon = viewMeta.icon;

  return (
    <aside className="panel panel-sidebar">
      <div className="tab-row">
        {(Object.keys(VIEW_META) as WorkspaceView[]).map((view) => {
          const Icon = VIEW_META[view].icon;
          return (
            <button
              key={view}
              type="button"
              className={`tab-chip ${activeView === view ? "active" : ""}`}
              onClick={() => onViewChange(view)}
            >
              <Icon size={14} />
              <span>{VIEW_META[view].label}</span>
              <strong>{counts[view]}</strong>
            </button>
          );
        })}
      </div>

      <div className="panel-header">
        <div>
          <p className="eyebrow">Workspace Resources</p>
          <h2>{viewMeta.title}</h2>
        </div>
        <div className="header-actions">
          <button className="icon-button" type="button" onClick={onCreateNew}>
            <Plus size={16} />
          </button>
          <button className="icon-button" type="button" onClick={onRefresh} disabled={loading}>
            <RefreshCw size={16} className={loading ? "spin" : ""} />
          </button>
        </div>
      </div>

      <div className="agent-list">
        {items.length === 0 ? (
          <div className="empty-state compact">
            <EmptyIcon size={18} />
            <p>{emptyMessage}</p>
          </div>
        ) : null}

        {items.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`agent-card ${selectedId === item.id ? "selected" : ""}`}
            onClick={() => onSelect(item.id)}
          >
            <div className="agent-card-header">
              <div>
                <strong>{item.title}</strong>
                <span>{item.subtitle}</span>
              </div>
              <span className={`status-pill status-${item.status}`}>{item.status}</span>
            </div>
            {item.note ? <div className="agent-card-footer"><span>{item.note}</span></div> : null}
          </button>
        ))}
      </div>
    </aside>
  );
}
