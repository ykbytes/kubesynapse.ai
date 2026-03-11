import { Activity, AlertTriangle, FileText, ShieldAlert, TerminalSquare } from "lucide-react";

import type { GatewayHealth, InvocationSummary, UiActivity } from "../types";

interface InspectorPanelProps {
  health: GatewayHealth | null;
  gatewayError: string;
  workspaceError: string;
  selectedAgentName: string;
  namespace: string;
  tokenPresent: boolean;
  logs: string;
  logsLoading: boolean;
  activity: UiActivity[];
  summary: InvocationSummary | null;
  approvalReason: string;
  approvalBusy: boolean;
  onApprovalReasonChange: (value: string) => void;
  onApprove: () => void;
  onDeny: () => void;
  onLoadLogs: () => void;
}

function renderJsonBlock(value: Record<string, unknown> | null | undefined) {
  if (!value) {
    return <p className="muted-copy">No data yet.</p>;
  }
  return <pre className="json-block">{JSON.stringify(value, null, 2)}</pre>;
}

export function InspectorPanel({
  health,
  gatewayError,
  workspaceError,
  selectedAgentName,
  namespace,
  tokenPresent,
  logs,
  logsLoading,
  activity,
  summary,
  approvalReason,
  approvalBusy,
  onApprovalReasonChange,
  onApprove,
  onDeny,
  onLoadLogs,
}: InspectorPanelProps) {
  return (
    <aside className="panel panel-inspector">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Operational Trace</p>
          <h2>Inspector</h2>
        </div>
      </div>

      <section className="inspector-card">
        <div className="card-title-row">
          <Activity size={16} />
          <strong>Gateway Health</strong>
        </div>
        <dl className="meta-grid">
          <div>
            <dt>Status</dt>
            <dd>{health?.status ?? "loading"}</dd>
          </div>
          <div>
            <dt>Auth</dt>
            <dd>{health?.auth_mode ?? "unknown"}</dd>
          </div>
          <div>
            <dt>Namespace</dt>
            <dd>{namespace}</dd>
          </div>
          <div>
            <dt>Token</dt>
            <dd>{tokenPresent ? "configured" : "missing"}</dd>
          </div>
        </dl>
        {gatewayError ? <p className="error-banner compact-banner">{gatewayError}</p> : null}
        {workspaceError ? <p className="warning-note">{workspaceError}</p> : null}
      </section>

      <section className="inspector-card">
        <div className="card-title-row">
          <ShieldAlert size={16} />
          <strong>Invocation Summary</strong>
        </div>
        {summary ? (
          <>
            <dl className="meta-grid">
              <div>
                <dt>Thread</dt>
                <dd>{summary.threadId}</dd>
              </div>
              <div>
                <dt>Status</dt>
                <dd>{summary.status}</dd>
              </div>
              <div>
                <dt>Policy</dt>
                <dd>{summary.policyName ?? "n/a"}</dd>
              </div>
              <div>
                <dt>Approval</dt>
                <dd>{summary.approvalName ?? "n/a"}</dd>
              </div>
            </dl>
            {summary.warnings.length > 0 ? (
              <div className="warning-list">
                {summary.warnings.map((warning) => (
                  <p key={warning} className="warning-chip">
                    <AlertTriangle size={14} />
                    <span>{warning}</span>
                  </p>
                ))}
              </div>
            ) : (
              <p className="muted-copy">No warnings emitted.</p>
            )}
          </>
        ) : (
          <p className="muted-copy">Run an invocation to inspect thread and tool metadata.</p>
        )}
      </section>

      <section className="inspector-card">
        <div className="card-title-row">
          <ShieldAlert size={16} />
          <strong>Approval Actions</strong>
        </div>
        {summary?.status === "approval_pending" && summary.approvalName ? (
          <>
            <p className="muted-copy">
              Approval <strong>{summary.approvalName}</strong> is pending. Approve to retry the same request with the saved thread.
            </p>
            <textarea
              className="prompt-input compact-input"
              rows={3}
              value={approvalReason}
              onChange={(event) => onApprovalReasonChange(event.target.value)}
              placeholder="Optional reason for the decision"
            />
            <div className="approval-actions">
              <button className="primary-button" type="button" onClick={onApprove} disabled={approvalBusy}>
                {approvalBusy ? "Working..." : "Approve and retry"}
              </button>
              <button className="secondary-button" type="button" onClick={onDeny} disabled={approvalBusy}>
                Deny
              </button>
            </div>
          </>
        ) : selectedAgentName ? (
          <p className="muted-copy">No approval action is pending for the selected agent.</p>
        ) : (
          <p className="muted-copy">Select an agent to review pending approvals.</p>
        )}
      </section>

      <section className="inspector-card">
        <div className="card-title-row">
          <FileText size={16} />
          <strong>Tool Result</strong>
        </div>
        {renderJsonBlock(summary?.toolResult)}
      </section>

      <section className="inspector-card">
        <div className="card-title-row">
          <TerminalSquare size={16} />
          <strong>Sandbox Session</strong>
        </div>
        {renderJsonBlock(summary?.sandboxSession)}
      </section>

      <section className="inspector-card">
        <div className="card-title-row">
          <Activity size={16} />
          <strong>Activity Feed</strong>
        </div>
        <div className="activity-feed">
          {activity.length === 0 ? <p className="muted-copy">No streamed events yet.</p> : null}
          {activity.map((item) => (
            <article key={item.id} className="activity-row">
              <strong>{item.event}</strong>
              <pre>{JSON.stringify(item.payload, null, 2)}</pre>
            </article>
          ))}
        </div>
      </section>

      <section className="inspector-card">
        <div className="card-title-row">
          <TerminalSquare size={16} />
          <strong>Latest Runtime Logs</strong>
        </div>
        <button className="secondary-button" type="button" onClick={onLoadLogs} disabled={logsLoading || !selectedAgentName}>
          {logsLoading ? "Loading logs..." : "Load logs"}
        </button>
        {logs ? <pre className="log-block">{logs}</pre> : <p className="muted-copy">Logs are fetched on demand for the selected agent.</p>}
      </section>
    </aside>
  );
}
