import { useState, useEffect, useCallback } from "react";
import {
  Activity,
  ArrowLeft,
  ArrowUpCircle,
  Bell,
  CheckCircle2,
  ExternalLink,
  Info,
  RefreshCw,
  XCircle,
  AlertTriangle,
  AlertCircle,
  CircleDot,
  Sparkles,
  Tag,
  Clock,
  Hash,
  Bot,
  ShieldCheck,
  GitBranch,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "../shared/EmptyState";
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

const SEVERITY_BADGE: Record<IncidentSeverity, string> = {
  critical: "border-destructive/35 bg-destructive/12 text-destructive",
  warning: "border-warning/35 bg-warning/12 text-warning-foreground",
  info: "border-info/35 bg-info/12 text-info-foreground",
};

const STATUS_BADGE: Record<IncidentStatus, string> = {
  firing: "border-destructive/35 bg-destructive/12 text-destructive",
  acknowledged: "border-info/35 bg-info/12 text-info-foreground",
  diagnosing: "border-warning/35 bg-warning/12 text-warning-foreground",
  remediated: "border-success/35 bg-success/12 text-success-foreground",
  resolved: "border-success/35 bg-success/12 text-success-foreground",
  closed: "border-border/70 bg-secondary/82 text-muted-foreground",
  escalated: "border-warning/40 bg-warning/15 text-warning-foreground",
};

const STATUS_ICON: Record<IncidentStatus, typeof AlertTriangle> = {
  firing: AlertTriangle,
  acknowledged: CircleDot,
  diagnosing: Sparkles,
  remediated: CheckCircle2,
  resolved: CheckCircle2,
  closed: XCircle,
  escalated: ArrowUpCircle,
};

const SEVERITY_ICON: Record<IncidentSeverity, typeof AlertTriangle> = {
  critical: AlertTriangle,
  warning: AlertCircle,
  info: Info,
};

interface DetailProps {
  name: string;
  onBack: () => void;
  getToken: () => string;
  getNamespace: () => string;
  api: {
    getIncident: (token: string, ns: string, name: string) => Promise<IncidentInfo>;
    updateIncidentStatus: (token: string, ns: string, name: string, body: { status?: string; message?: string }) => Promise<IncidentInfo>;
    escalateIncident: (token: string, ns: string, name: string, message?: string) => Promise<IncidentInfo>;
    getIncidentTimeline: (token: string, ns: string, name: string) => Promise<{ timeline: IncidentTimelineEvent[] }>;
  };
}

export function IncidentDetail({ name, onBack, getToken, getNamespace, api }: DetailProps) {
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
    fetchData();
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
    } catch (e) {
      setError(String(e));
    } finally {
      setActionLoading(null);
    }
  };

  if (loading && !incident) {
    return (
      <div className="flex items-center justify-center p-12">
        <RefreshCw className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error && !incident) {
    return (
      <div className="space-y-3 p-6">
        <Button variant="ghost" size="sm" onClick={onBack} className="hover-lift">
          <ArrowLeft className="h-3.5 w-3.5" /> Back to Incidents
        </Button>
        <Card>
          <CardContent className="p-6">
            <EmptyState
              icon={AlertCircle}
              title="Could not load incident"
              description={error}
              action={{ label: "Retry", onClick: fetchData }}
            />
          </CardContent>
        </Card>
      </div>
    );
  }

  if (!incident) {
    return (
      <div className="space-y-3 p-6">
        <Button variant="ghost" size="sm" onClick={onBack} className="hover-lift">
          <ArrowLeft className="h-3.5 w-3.5" /> Back to Incidents
        </Button>
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">Incident not found.</CardContent>
        </Card>
      </div>
    );
  }

  const statusActions: Array<{ status: IncidentStatus; label: string; icon: typeof Bell; tone: string }> = [];
  if (incident.status === "firing") {
    statusActions.push({ status: "acknowledged", label: "Acknowledge", icon: CircleDot, tone: "info" });
  }
  if (incident.status === "acknowledged") {
    statusActions.push({ status: "diagnosing", label: "Start diagnosis", icon: Sparkles, tone: "warning" });
  }
  if (incident.status === "diagnosing") {
    statusActions.push({ status: "remediated", label: "Mark remediated", icon: CheckCircle2, tone: "success" });
  }
  if (incident.status === "remediated" || incident.status === "acknowledged") {
    statusActions.push({ status: "resolved", label: "Resolve", icon: CheckCircle2, tone: "success" });
  }
  if (incident.status === "resolved") {
    statusActions.push({ status: "closed", label: "Close", icon: XCircle, tone: "muted" });
  }
  if (!["resolved", "closed"].includes(incident.status)) {
    statusActions.push({ status: "escalated", label: "Escalate", icon: ArrowUpCircle, tone: "warning" });
  }

  const StatusIcon = STATUS_ICON[incident.status as IncidentStatus] ?? CircleDot;
  const SevIcon = SEVERITY_ICON[incident.severity as IncidentSeverity] ?? AlertCircle;

  return (
    <div className="space-y-6 p-6">
      <Button variant="ghost" size="sm" onClick={onBack} className="hover-lift">
        <ArrowLeft className="h-3.5 w-3.5" /> Back to Incidents
      </Button>

      <Card className="overflow-hidden animate-slide-up">
        <div
          className={cn(
            "h-1.5 w-full",
            incident.severity === "critical" && "bg-destructive/70",
            incident.severity === "warning" && "bg-warning/70",
            incident.severity === "info" && "bg-info/70",
          )}
          aria-hidden="true"
        />
        <CardContent className="space-y-4 p-5 md:p-6">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="flex min-w-0 items-start gap-3">
              <span
                className={cn(
                  "inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border shadow-inner",
                  SEVERITY_BADGE[incident.severity as IncidentSeverity],
                )}
                aria-hidden="true"
              >
                <SevIcon className="h-5 w-5" />
              </span>
              <div className="min-w-0">
                <h1 className="break-words text-2xl font-semibold tracking-tight text-foreground">
                  {incident.title}
                </h1>
                <p className="mt-1 break-words text-sm text-muted-foreground">
                  <span className="font-mono text-xs">{incident.namespace}/{incident.name}</span>
                  <span className="mx-2">·</span>
                  Source: <span className="text-foreground/85">{incident.source}</span>
                  {incident.escalated && (
                    <span className="ml-2 inline-flex items-center gap-1 text-warning-foreground">
                      <ArrowUpCircle className="h-3.5 w-3.5" /> escalated
                    </span>
                  )}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Badge variant="outline" className={cn("gap-1", STATUS_BADGE[incident.status as IncidentStatus])}>
                <StatusIcon className="h-3 w-3" />
                {incident.status}
              </Badge>
              <Badge variant="outline" className={SEVERITY_BADGE[incident.severity as IncidentSeverity]}>
                {incident.severity}
              </Badge>
              <Button variant="outline" size="icon" onClick={fetchData} aria-label="Refresh incident" className="hover-lift">
                <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
              </Button>
            </div>
          </div>

          {incident.description && (
            <div className="rounded-lg border border-border/60 bg-secondary/40 p-3 text-sm leading-6 text-foreground/90">
              {incident.description}
            </div>
          )}

          {statusActions.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {statusActions.map((action) => (
                <Button
                  key={action.status}
                  variant="outline"
                  size="sm"
                  onClick={() => performAction(action.status, `${action.label} via UI`)}
                  disabled={actionLoading === action.status}
                  className={cn(
                    "hover-lift",
                    action.tone === "info" && "text-info-foreground hover:bg-info/12",
                    action.tone === "warning" && "text-warning-foreground hover:bg-warning/12",
                    action.tone === "success" && "text-success-foreground hover:bg-success/12",
                    action.tone === "muted" && "text-muted-foreground",
                  )}
                >
                  <action.icon className="h-3.5 w-3.5" />
                  {actionLoading === action.status ? "Working..." : action.label}
                </Button>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card className="animate-slide-up">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <Activity className="h-4 w-4 text-primary" />
                Timeline
              </CardTitle>
              <Badge variant="outline" className="border-border/60 bg-secondary/70 text-muted-foreground">
                {timeline.length} event{timeline.length === 1 ? "" : "s"}
              </Badge>
            </CardHeader>
            <CardContent>
              {timeline.length === 0 ? (
                <p className="text-sm text-muted-foreground">No timeline events yet.</p>
              ) : (
                <IncidentTimeline events={timeline} />
              )}
            </CardContent>
          </Card>

          {Object.keys(incident.annotations).length > 0 && (
            <Card className="animate-slide-up">
              <CardHeader className="pb-3">
                <CardTitle className="flex items-center gap-2 text-base">
                  <Tag className="h-4 w-4 text-info-foreground" />
                  Annotations
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                {Object.entries(incident.annotations).map(([k, v]) => (
                  <div key={k} className="flex flex-col gap-0.5 border-b border-border/40 pb-2 last:border-b-0 last:pb-0">
                    <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">{k}</span>
                    <span className="break-words text-foreground/90">{v}</span>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}
        </div>

        <div className="space-y-4">
          <Card className="animate-slide-up">
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <Info className="h-4 w-4 text-primary" />
                Details
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2.5 text-sm">
              <DetailRow icon={Bot} label="Assigned agent" value={incident.assigned_agent ?? "Unassigned"} />
              <DetailRow icon={Clock} label="Escalation timeout" value={`${incident.escalation_timeout_minutes} min`} />
              <DetailRow
                icon={ShieldCheck}
                label="Auto-acknowledge"
                value={incident.auto_acknowledge ? "Enabled" : "Disabled"}
              />
              <DetailRow icon={Hash} label="Created" value={formatDate(incident.created_at)} />
              <DetailRow icon={Hash} label="Updated" value={formatDate(incident.updated_at)} />
              {incident.acknowledged_at && (
                <DetailRow icon={CircleDot} label="Acknowledged" value={formatDate(incident.acknowledged_at)} />
              )}
              {incident.resolved_at && (
                <DetailRow icon={CheckCircle2} label="Resolved" value={formatDate(incident.resolved_at)} />
              )}
              {incident.escalated_at && (
                <DetailRow icon={ArrowUpCircle} label="Escalated" value={formatDate(incident.escalated_at)} />
              )}
              {incident.workflow_run_id && (
                <div className="flex items-start justify-between gap-2 rounded-lg border border-info/25 bg-info/8 p-2.5">
                  <div className="min-w-0">
                    <p className="text-[11px] font-medium uppercase tracking-[0.08em] text-info-foreground">Workflow run</p>
                    <a
                      href={`/observatory/${incident.workflow_run_id}`}
                      className="mt-0.5 inline-flex items-center gap-1 break-all text-sm font-medium text-info-foreground hover:underline"
                    >
                      {incident.workflow_run_id}
                      <ExternalLink className="h-3 w-3 shrink-0" />
                    </a>
                  </div>
                  <GitBranch className="mt-1 h-4 w-4 shrink-0 text-info-foreground" aria-hidden="true" />
                </div>
              )}
            </CardContent>
          </Card>

          {Object.keys(incident.labels).length > 0 && (
            <Card className="animate-slide-up">
              <CardHeader className="pb-3">
                <CardTitle className="flex items-center gap-2 text-base">
                  <Tag className="h-4 w-4 text-info-foreground" />
                  Labels
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(incident.labels).map(([k, v]) => (
                    <Badge
                      key={k}
                      variant="outline"
                      className="border-border/60 bg-secondary/70 text-foreground/85"
                    >
                      <span className="text-muted-foreground">{k}</span>
                      <span className="mx-1 text-muted-foreground/60">=</span>
                      <span className="font-mono text-[10px]">{v}</span>
                    </Badge>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

function DetailRow({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Info;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-border/40 pb-2 last:border-b-0 last:pb-0">
      <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
        <Icon className="h-3 w-3" />
        {label}
      </span>
      <span className="text-right text-sm text-foreground/90">{value}</span>
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
