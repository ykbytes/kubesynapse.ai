import { useState, useEffect, useCallback } from "react";
import {
  ArrowLeft,
  ArrowUpCircle,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  RefreshCw,
  Sparkles,
  Tag,
  XCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { IncidentTimeline } from "./IncidentTimeline";
import type { IncidentInfo, IncidentTimelineEvent } from "../../types";
import { cn } from "@/lib/utils";

type IncidentStatus =
  | "firing"
  | "acknowledged"
  | "diagnosing"
  | "remediated"
  | "resolved"
  | "closed"
  | "escalated";
type IncidentSeverity = "critical" | "warning" | "info";

const SEVERITY_STRIPE: Record<IncidentSeverity, string> = {
  critical: "bg-red-500",
  warning: "bg-amber-500",
  info: "bg-sky-500",
};

const STATUS_DOT: Record<IncidentStatus, string> = {
  firing: "bg-red-500/80",
  acknowledged: "bg-sky-500/80",
  diagnosing: "bg-amber-500/80",
  remediated: "bg-emerald-500/80",
  resolved: "bg-emerald-500/80",
  closed: "bg-slate-400",
  escalated: "bg-amber-500/80",
};

const STATUS_LABEL: Record<IncidentStatus, string> = {
  firing: "Firing",
  acknowledged: "Acknowledged",
  diagnosing: "Diagnosing",
  remediated: "Remediated",
  resolved: "Resolved",
  closed: "Closed",
  escalated: "Escalated",
};

interface DetailProps {
  name: string;
  onBack: () => void;
  getToken: () => string;
  getNamespace: () => string;
  onOpenWorkflowRun?: (workflowName: string, runId?: string | null) => void;
  api: {
    getIncident: (token: string, ns: string, name: string) => Promise<IncidentInfo>;
    updateIncidentStatus: (
      token: string,
      ns: string,
      name: string,
      body: { status?: string; message?: string },
    ) => Promise<IncidentInfo>;
    escalateIncident: (token: string, ns: string, name: string, message?: string) => Promise<IncidentInfo>;
    getIncidentTimeline: (
      token: string,
      ns: string,
      name: string,
    ) => Promise<{ timeline: IncidentTimelineEvent[] }>;
  };
}

export function IncidentDetail({
  name,
  onBack,
  getToken,
  getNamespace,
  onOpenWorkflowRun,
  api,
}: DetailProps) {
  const [incident, setIncident] = useState<IncidentInfo | null>(null);
  const [timeline, setTimeline] = useState<IncidentTimelineEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const ns = getNamespace();

  const fetchData = useCallback(async () => {
    if (!name) return;
    setLoading(true);
    setError(null);
    try {
      const token = getToken();
      const [inc, tl] = await Promise.all([
        api.getIncident(token, ns, name),
        api.getIncidentTimeline(token, ns, name),
      ]);
      setIncident(inc);
      setTimeline(tl.timeline);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [name, ns, getToken, api]);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  const performAction = async (status: string, message: string) => {
    if (!name || !incident) return;
    setActionLoading(status);
    try {
      const token = getToken();
      const updated =
        status === "escalated"
          ? await api.escalateIncident(token, ns, name, message)
          : await api.updateIncidentStatus(token, ns, name, { status, message });
      setIncident(updated);
      await fetchData();
    } catch (e) {
      setError(String(e));
    } finally {
      setActionLoading(null);
    }
  };

  if (loading && !incident) {
    return (
      <div className="flex items-center justify-center p-12">
        <RefreshCw className="size-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error && !incident) {
    return (
      <div className="space-y-3 p-5">
        <Button variant="ghost" size="sm" onClick={onBack} className="text-xs">
          <ArrowLeft className="size-3.5" /> Back
        </Button>
        <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-6 text-center">
          <p className="text-sm text-red-400">{error}</p>
          <Button variant="outline" size="sm" className="mt-3" onClick={fetchData}>
            Retry
          </Button>
        </div>
      </div>
    );
  }

  if (!incident) {
    return (
      <div className="space-y-3 p-5">
        <Button variant="ghost" size="sm" onClick={onBack} className="text-xs">
          <ArrowLeft className="size-3.5" /> Back
        </Button>
        <p className="text-sm text-muted-foreground">Incident not found.</p>
      </div>
    );
  }

  const status = incident.status as IncidentStatus;
  const severity = incident.severity as IncidentSeverity;

  // Build context-appropriate status actions
  const statusActions: Array<{
    status: IncidentStatus;
    label: string;
    icon: typeof CheckCircle2;
    tone: string;
  }> = [];
  if (status === "firing")
    statusActions.push({ status: "acknowledged", label: "Acknowledge", icon: CircleDot, tone: "sky" });
  if (status === "acknowledged")
    statusActions.push({ status: "diagnosing", label: "Start diagnosis", icon: Sparkles, tone: "amber" });
  if (status === "diagnosing")
    statusActions.push({ status: "remediated", label: "Mark remediated", icon: CheckCircle2, tone: "emerald" });
  if (status === "remediated" || status === "acknowledged")
    statusActions.push({ status: "resolved", label: "Resolve", icon: CheckCircle2, tone: "emerald" });
  if (status === "resolved")
    statusActions.push({ status: "closed", label: "Close", icon: XCircle, tone: "slate" });
  if (!["resolved", "closed"].includes(status))
    statusActions.push({ status: "escalated", label: "Escalate", icon: ArrowUpCircle, tone: "amber" });

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Top bar */}
      <div className="flex shrink-0 items-center gap-3 border-b border-border/30 px-5 py-3">
        <Button variant="ghost" size="sm" onClick={onBack} className="h-7 text-xs">
          <ArrowLeft className="size-3.5" /> Back
        </Button>
        <span className="font-mono text-xs text-muted-foreground/50">{incident.namespace}/{incident.name}</span>
        <div className="ml-auto">
          <Button variant="outline" size="sm" onClick={fetchData} className="h-7 text-xs">
            <RefreshCw className={cn("size-3.5", loading && "animate-spin")} />
            Refresh
          </Button>
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto">
        <div className="mx-auto max-w-4xl space-y-4 p-5">
          {/* Header card */}
          <div className="overflow-hidden rounded-xl border border-border/40 bg-muted/15">
            <div className={cn("h-1 w-full", SEVERITY_STRIPE[severity])} />
            <div className="p-5">
              <div className="flex items-start gap-3">
                <div className="min-w-0 flex-1">
                  <h1 className="text-lg font-semibold text-foreground">{incident.title}</h1>
                  <div className="mt-1.5 flex flex-wrap items-center gap-2">
                    <StatusBadge status={status} escalated={incident.escalated} />
                    <SeverityBadge severity={severity} />
                    <span className="text-xs text-muted-foreground/50">· {incident.source}</span>
                  </div>
                </div>
              </div>

              {incident.description && (
                <p className="mt-3 text-sm leading-relaxed text-foreground/80">
                  {incident.description}
                </p>
              )}

              {/* Actions */}
              {statusActions.length > 0 && (
                <div className="mt-4 flex flex-wrap gap-2">
                  {statusActions.map((action) => (
                    <Button
                      key={action.status}
                      variant="outline"
                      size="sm"
                      className={cn(
                        "h-8 text-xs",
                        action.tone === "sky" && "border-sky-500/20 text-sky-400 hover:bg-sky-500/10",
                        action.tone === "amber" && "border-amber-500/20 text-amber-400 hover:bg-amber-500/10",
                        action.tone === "emerald" && "border-emerald-500/20 text-emerald-400 hover:bg-emerald-500/10",
                        action.tone === "slate" && "text-muted-foreground",
                      )}
                      disabled={actionLoading === action.status}
                      onClick={() => performAction(action.status, `${action.label} via UI`)}
                    >
                      <action.icon className="size-3.5" />
                      {actionLoading === action.status ? "Working..." : action.label}
                    </Button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Workflow run link — prominent */}
          {incident.workflow_ref_name && (
            <div className="rounded-xl border border-border/40 bg-muted/15 p-4">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Workflow Run
                  </span>
                  <div className="mt-1 flex items-center gap-2">
                    <span className="text-sm font-medium text-foreground">
                      {incident.workflow_ref_name}
                    </span>
                    {incident.workflow_run_id && (
                      <span className="font-mono text-xs text-muted-foreground/50">
                        · {incident.workflow_run_id}
                      </span>
                    )}
                  </div>
                </div>
                {onOpenWorkflowRun && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 shrink-0 text-xs"
                    onClick={() =>
                      onOpenWorkflowRun(incident.workflow_ref_name!, incident.workflow_run_id)
                    }
                  >
                    View in Observatory
                    <ChevronRight className="size-3.5" />
                  </Button>
                )}
              </div>
            </div>
          )}

          {/* Two-column layout: timeline + sidebar */}
          <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
            {/* Timeline */}
            <div className="rounded-xl border border-border/40 bg-muted/15 p-4">
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-sm font-medium text-foreground">Timeline</h3>
                <span className="text-xs text-muted-foreground/50">
                  {timeline.length} event{timeline.length === 1 ? "" : "s"}
                </span>
              </div>
              {timeline.length === 0 ? (
                <p className="py-6 text-center text-sm text-muted-foreground/40">
                  No timeline events yet.
                </p>
              ) : (
                <IncidentTimeline events={timeline} />
              )}
            </div>

            {/* Sidebar: details + labels */}
            <div className="space-y-4">
              <div className="rounded-xl border border-border/40 bg-muted/15 p-4">
                <h3 className="mb-3 text-sm font-medium text-foreground">Details</h3>
                <div className="space-y-2.5 text-sm">
                  <DetailRow label="Assigned agent" value={incident.assigned_agent ?? "Unassigned"} />
                  <DetailRow label="Source" value={incident.source} />
                  <DetailRow label="Escalation" value={`${incident.escalation_timeout_minutes} min`} />
                  <DetailRow label="Auto-ack" value={incident.auto_acknowledge ? "Enabled" : "Disabled"} />
                  <DetailRow label="Created" value={formatDate(incident.created_at)} />
                  <DetailRow label="Updated" value={formatDate(incident.updated_at)} />
                  {incident.acknowledged_at && (
                    <DetailRow label="Acknowledged" value={formatDate(incident.acknowledged_at)} />
                  )}
                  {incident.resolved_at && (
                    <DetailRow label="Resolved" value={formatDate(incident.resolved_at)} />
                  )}
                  {incident.escalated_at && (
                    <DetailRow label="Escalated" value={formatDate(incident.escalated_at)} />
                  )}
                </div>
              </div>

              {Object.keys(incident.labels).length > 0 && (
                <div className="rounded-xl border border-border/40 bg-muted/15 p-4">
                  <h3 className="mb-3 flex items-center gap-1.5 text-sm font-medium text-foreground">
                    <Tag className="size-3.5 text-muted-foreground" />
                    Labels
                  </h3>
                  <div className="space-y-1.5">
                    {Object.entries(incident.labels).map(([k, v]) => (
                      <div key={k} className="flex items-baseline gap-2 text-xs">
                        <span className="shrink-0 text-muted-foreground/50">{k}</span>
                        <span className="font-mono text-foreground/70">{v}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {Object.keys(incident.annotations).length > 0 && (
                <div className="rounded-xl border border-border/40 bg-muted/15 p-4">
                  <h3 className="mb-3 flex items-center gap-1.5 text-sm font-medium text-foreground">
                    <Tag className="size-3.5 text-muted-foreground" />
                    Annotations
                  </h3>
                  <div className="space-y-2.5">
                    {Object.entries(incident.annotations).map(([k, v]) => (
                      <div key={k}>
                        <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground/50">
                          {k}
                        </div>
                        <div className="mt-0.5 text-sm text-foreground/80 break-words">{v}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Badges ──────────────────────────────────────────────────────────────────

function StatusBadge({ status, escalated }: { status: IncidentStatus; escalated: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium",
        status === "firing" && "border-red-500/20 bg-red-500/10 text-red-400",
        status === "acknowledged" && "border-sky-500/20 bg-sky-500/10 text-sky-400",
        status === "diagnosing" && "border-amber-500/20 bg-amber-500/10 text-amber-400",
        status === "remediated" && "border-emerald-500/20 bg-emerald-500/10 text-emerald-400",
        status === "resolved" && "border-emerald-500/20 bg-emerald-500/10 text-emerald-400",
        status === "closed" && "border-border/40 bg-muted/20 text-muted-foreground",
        status === "escalated" && "border-amber-500/20 bg-amber-500/10 text-amber-400",
      )}
    >
      <span className={cn("size-1.5 rounded-full", STATUS_DOT[status])} />
      {STATUS_LABEL[status]}
      {escalated && <ArrowUpCircle className="size-3 text-amber-400" />}
    </span>
  );
}

function SeverityBadge({ severity }: { severity: IncidentSeverity }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium capitalize",
        severity === "critical" && "border-red-500/20 bg-red-500/10 text-red-400",
        severity === "warning" && "border-amber-500/20 bg-amber-500/10 text-amber-400",
        severity === "info" && "border-sky-500/20 bg-sky-500/10 text-sky-400",
      )}
    >
      {severity}
    </span>
  );
}

// ─── Detail Row ──────────────────────────────────────────────────────────────

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-2 border-b border-border/20 pb-2 last:border-b-0 last:pb-0">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-right text-sm text-foreground/80">{value}</span>
    </div>
  );
}

function formatDate(ts: string): string {
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}
