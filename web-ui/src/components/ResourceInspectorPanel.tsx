import { Activity, FileText, ShieldAlert } from "lucide-react";

interface ResourceInspectorPanelProps {
  title: string;
  selectedName: string;
  status: string;
  summary?: Record<string, unknown> | null;
  spec?: Record<string, unknown> | null;
  details?: Record<string, unknown> | null;
  emptyMessage: string;
  pendingApprovalName?: string;
  approvalReason: string;
  approvalBusy: boolean;
  onApprovalReasonChange: (value: string) => void;
  onApprove: () => void;
  onDeny: () => void;
}

function renderJsonBlock(value: Record<string, unknown> | null | undefined, emptyText: string) {
  if (!value) {
    return <p className="muted-copy">{emptyText}</p>;
  }
  return <pre className="json-block">{JSON.stringify(value, null, 2)}</pre>;
}

export function ResourceInspectorPanel({
  title,
  selectedName,
  status,
  summary,
  spec,
  details,
  emptyMessage,
  pendingApprovalName,
  approvalReason,
  approvalBusy,
  onApprovalReasonChange,
  onApprove,
  onDeny,
}: ResourceInspectorPanelProps) {
  return (
    <aside className="panel panel-inspector">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Control Plane Detail</p>
          <h2>{title}</h2>
        </div>
      </div>

      <section className="inspector-card">
        <div className="card-title-row">
          <Activity size={16} />
          <strong>Selected Resource</strong>
        </div>
        {selectedName ? (
          <dl className="meta-grid">
            <div>
              <dt>Name</dt>
              <dd>{selectedName}</dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd>{status}</dd>
            </div>
          </dl>
        ) : (
          <p className="muted-copy">{emptyMessage}</p>
        )}
      </section>

      <section className="inspector-card">
        <div className="card-title-row">
          <ShieldAlert size={16} />
          <strong>Approval Actions</strong>
        </div>
        {pendingApprovalName ? (
          <>
            <p className="muted-copy">Approval <strong>{pendingApprovalName}</strong> is pending for this resource.</p>
            <textarea
              className="prompt-input compact-input"
              rows={3}
              value={approvalReason}
              onChange={(event) => onApprovalReasonChange(event.target.value)}
              placeholder="Optional reason for the decision"
            />
            <div className="approval-actions">
              <button className="primary-button" type="button" onClick={onApprove} disabled={approvalBusy}>
                {approvalBusy ? "Working..." : "Approve"}
              </button>
              <button className="secondary-button" type="button" onClick={onDeny} disabled={approvalBusy}>
                Deny
              </button>
            </div>
          </>
        ) : (
          <p className="muted-copy">No pending approval on the selected resource.</p>
        )}
      </section>

      <section className="inspector-card">
        <div className="card-title-row">
          <Activity size={16} />
          <strong>Summary</strong>
        </div>
        {renderJsonBlock(summary, "No summary data yet.")}
      </section>

      <section className="inspector-card">
        <div className="card-title-row">
          <FileText size={16} />
          <strong>Spec</strong>
        </div>
        {renderJsonBlock(spec, "No spec selected.")}
      </section>

      <section className="inspector-card">
        <div className="card-title-row">
          <FileText size={16} />
          <strong>Status Detail</strong>
        </div>
        {renderJsonBlock(details, "No status detail yet.")}
      </section>
    </aside>
  );
}