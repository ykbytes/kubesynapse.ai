import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import {
  AlertTriangle,
  AlertCircle,
  Info,
  ArrowUpCircle,
  Bell,
  BellRing,
  CheckCircle2,
  CircleDot,
  Clock,
  Filter,
  Pause,
  Play,
  RefreshCw,
  Search,
  Sparkles,
  TimerReset,
  Zap,
} from "lucide-react";
import type { IncidentInfo } from "../../types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState } from "../shared/EmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

type IncidentSeverity = "critical" | "warning" | "info";
type IncidentStatus =
  | "firing"
  | "acknowledged"
  | "diagnosing"
  | "remediated"
  | "resolved"
  | "closed"
  | "escalated";
type StatusFilter = "" | IncidentStatus;
type SeverityFilter = "" | IncidentSeverity;

const SEVERITY_ICONS: Record<IncidentSeverity, typeof AlertTriangle> = {
  critical: AlertTriangle,
  warning: AlertCircle,
  info: Info,
};

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
  closed: CheckCircle2,
  escalated: ArrowUpCircle,
};

const STATUS_OPTIONS: Array<{ value: StatusFilter; label: string }> = [
  { value: "", label: "All statuses" },
  { value: "firing", label: "Firing" },
  { value: "acknowledged", label: "Acknowledged" },
  { value: "diagnosing", label: "Diagnosing" },
  { value: "remediated", label: "Remediated" },
  { value: "resolved", label: "Resolved" },
  { value: "closed", label: "Closed" },
  { value: "escalated", label: "Escalated" },
];

const SEVERITY_OPTIONS: Array<{ value: SeverityFilter; label: string }> = [
  { value: "", label: "All severities" },
  { value: "critical", label: "Critical" },
  { value: "warning", label: "Warning" },
  { value: "info", label: "Info" },
];

const AUTO_REFRESH_OPTIONS = [
  { value: 0, label: "Off" },
  { value: 15, label: "15s" },
  { value: 30, label: "30s" },
  { value: 60, label: "1m" },
];

interface DashboardProps {
  setSelectedIncident?: (name: string) => void;
  getToken: () => string;
  getNamespace: () => string;
  api: {
    listIncidents: (token: string, ns: string, params?: { status?: string; severity?: string; limit?: number; offset?: number }) => Promise<{ incidents: IncidentInfo[]; total: number }>;
    updateIncidentStatus: (token: string, ns: string, name: string, body: { status?: string; message?: string }) => Promise<IncidentInfo>;
    createIncident?: (token: string, ns: string, body: Partial<IncidentInfo> & { name: string; title: string }) => Promise<IncidentInfo>;
  };
  onFireExampleAlert?: () => void | Promise<void>;
}

export function IncidentDashboard({
  setSelectedIncident,
  getToken,
  getNamespace,
  api,
  onFireExampleAlert,
}: DashboardProps) {
  const [incidents, setIncidents] = useState<IncidentInfo[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("");
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>("");
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [autoRefresh, setAutoRefresh] = useState(0);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [exampleFiring, setExampleFiring] = useState(false);
  const refreshIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const ns = getNamespace();

  const fetchIncidents = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const token = getToken();
      const params: { status?: string; severity?: string; limit?: number } = { limit: 100 };
      if (statusFilter) params.status = statusFilter;
      if (severityFilter) params.severity = severityFilter;
      const result = await api.listIncidents(token, ns, params);
      setIncidents(result.incidents);
      setTotal(result.total);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [ns, statusFilter, severityFilter, getToken, api]);

  useEffect(() => {
    fetchIncidents();
  }, [fetchIncidents]);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 200);
    return () => clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    if (refreshIntervalRef.current) {
      clearInterval(refreshIntervalRef.current);
      refreshIntervalRef.current = null;
    }
    if (autoRefresh > 0) {
      refreshIntervalRef.current = setInterval(() => {
        void fetchIncidents();
      }, autoRefresh * 1000);
    }
    return () => {
      if (refreshIntervalRef.current) {
        clearInterval(refreshIntervalRef.current);
        refreshIntervalRef.current = null;
      }
    };
  }, [autoRefresh, fetchIncidents]);

  const fastAction = async (name: string, status: IncidentStatus, message: string) => {
    setActionLoading(`${name}-${status}`);
    try {
      await api.updateIncidentStatus(getToken(), ns, name, { status, message });
      await fetchIncidents();
    } catch (e) {
      setError(String(e));
    } finally {
      setActionLoading(null);
    }
  };

  const fireExample = async () => {
    if (!onFireExampleAlert) return;
    setExampleFiring(true);
    try {
      await onFireExampleAlert();
      await fetchIncidents();
    } catch (e) {
      setError(String(e));
    } finally {
      setExampleFiring(false);
    }
  };

  const stats = useMemo(() => {
    const firing = incidents.filter((i) => i.status === "firing").length;
    const escalated = incidents.filter((i) => i.escalated).length;
    const acknowledged = incidents.filter((i) => i.status === "acknowledged" || i.status === "diagnosing").length;
    const resolved = incidents.filter((i) => i.status === "resolved" || i.status === "remediated" || i.status === "closed").length;
    return { firing, escalated, acknowledged, resolved };
  }, [incidents]);

  const filtered = useMemo(() => {
    if (!debouncedSearch.trim()) return incidents;
    const q = debouncedSearch.toLowerCase();
    return incidents.filter(
      (i) =>
        i.title.toLowerCase().includes(q) ||
        i.name.toLowerCase().includes(q) ||
        i.namespace.toLowerCase().includes(q) ||
        (i.assigned_agent ?? "").toLowerCase().includes(q),
    );
  }, [incidents, debouncedSearch]);

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-primary/25 bg-primary/12 text-primary shadow-inner animate-icon-float">
            <BellRing className="h-5 w-5" aria-hidden="true" />
          </div>
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-foreground">Incidents</h1>
            <p className="text-sm text-muted-foreground">
              Track firing alerts, escalations, and remediation in one console.
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {onFireExampleAlert && (
            <Button
              variant="outline"
              size="sm"
              onClick={fireExample}
              disabled={exampleFiring}
              className="hover-lift"
              aria-label="Fire example alertmanager alert"
            >
              <Zap className={cn("h-3.5 w-3.5", exampleFiring && "animate-pulse")} />
              {exampleFiring ? "Firing..." : "Fire example alert"}
            </Button>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={fetchIncidents}
            className="hover-lift"
            aria-label="Refresh incidents"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
            Refresh
          </Button>
          <AutoRefreshControl value={autoRefresh} onChange={setAutoRefresh} />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard
          label="Firing"
          value={stats.firing}
          tone="destructive"
          icon={AlertTriangle}
          loading={loading && incidents.length === 0}
        />
        <StatCard
          label="Escalated"
          value={stats.escalated}
          tone="warning"
          icon={ArrowUpCircle}
          loading={loading && incidents.length === 0}
        />
        <StatCard
          label="In progress"
          value={stats.acknowledged}
          tone="info"
          icon={Sparkles}
          loading={loading && incidents.length === 0}
        />
        <StatCard
          label="Resolved"
          value={stats.resolved}
          tone="success"
          icon={CheckCircle2}
          loading={loading && incidents.length === 0}
        />
      </div>

      {error && (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/8 p-3 text-sm text-destructive animate-scale-in"
        >
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <p className="break-words">{error}</p>
        </div>
      )}

      <Card className="animate-slide-up">
        <CardContent className="flex flex-col gap-3 p-4 md:flex-row md:items-center">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search incidents by title, name, namespace, or agent..."
              aria-label="Search incidents"
              className="h-9 w-full rounded-[calc(var(--radius-md)-1px)] border border-border/70 bg-background/72 pl-8 pr-3 text-sm text-foreground placeholder:text-muted-foreground/70 focus:border-primary/45 focus:outline-none focus:ring-2 focus:ring-ring/40"
            />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
              <Filter className="h-3 w-3" /> Filters
            </span>
            <SelectPill value={statusFilter} onChange={setStatusFilter} options={STATUS_OPTIONS} ariaLabel="Status filter" />
            <SelectPill value={severityFilter} onChange={setSeverityFilter} options={SEVERITY_OPTIONS} ariaLabel="Severity filter" />
            {(statusFilter || severityFilter || search) && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setStatusFilter("");
                  setSeverityFilter("");
                  setSearch("");
                }}
                aria-label="Clear filters"
              >
                <TimerReset className="h-3.5 w-3.5" />
                Clear
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {loading && incidents.length === 0 ? (
        <IncidentTableSkeleton />
      ) : error ? (
        <Card>
          <CardContent className="p-6">
            <EmptyState
              icon={AlertCircle}
              title="Could not load incidents"
              description="Retry to fetch the latest state, or check the gateway logs."
              action={{ label: "Retry", onClick: fetchIncidents }}
            />
          </CardContent>
        </Card>
      ) : filtered.length === 0 ? (
        <Card>
          <CardContent className="p-2">
            <EmptyState
              icon={Bell}
              title={incidents.length === 0 ? "No incidents" : "No matching incidents"}
              description={
                incidents.length === 0
                  ? "All clear. Configure an Alertmanager webhook to ingest alerts or fire an example to see this surface in action."
                  : `No incidents match "${debouncedSearch}". Adjust your filters and try again.`
              }
              action={
                incidents.length === 0 && onFireExampleAlert
                  ? { label: exampleFiring ? "Firing..." : "Fire example alert", onClick: fireExample }
                  : undefined
              }
            />
          </CardContent>
        </Card>
      ) : (
        <Card className="overflow-hidden animate-slide-up">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px]">
              <thead>
                <tr className="border-b border-border/60 bg-secondary/40 text-left text-[11px] uppercase tracking-[0.08em] text-muted-foreground">
                  <th className="px-4 py-2.5 font-medium">Incident</th>
                  <th className="px-4 py-2.5 font-medium">Status</th>
                  <th className="px-4 py-2.5 font-medium">Severity</th>
                  <th className="px-4 py-2.5 font-medium">Agent</th>
                  <th className="px-4 py-2.5 font-medium">Age</th>
                  <th className="px-4 py-2.5 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/50">
                {filtered.map((inc) => (
                  <IncidentRow
                    key={inc.id}
                    incident={inc}
                    onSelect={setSelectedIncident}
                    actionLoading={actionLoading}
                    onAction={fastAction}
                  />
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between border-t border-border/60 bg-secondary/30 px-4 py-2 text-xs text-muted-foreground">
            <span>{filtered.length} shown · {total} total</span>
            <span className="inline-flex items-center gap-1">
              <Clock className="h-3 w-3" />
              Updated {loading ? "syncing..." : "just now"}
            </span>
          </div>
        </Card>
      )}
    </div>
  );
}

function IncidentRow({
  incident: inc,
  onSelect,
  actionLoading,
  onAction,
}: {
  incident: IncidentInfo;
  onSelect?: (name: string) => void;
  actionLoading: string | null;
  onAction: (name: string, status: IncidentStatus, message: string) => Promise<void>;
}) {
  const SevIcon = SEVERITY_ICONS[inc.severity] ?? AlertCircle;
  const StatusIcon = STATUS_ICON[inc.status] ?? CircleDot;
  return (
    <tr
      className="group cursor-pointer bg-card/40 transition-colors hover:bg-accent/45 focus-within:bg-accent/45"
      onClick={() => onSelect?.(inc.name)}
      onKeyDown={(e) => {
        if (e.key === "Enter") onSelect?.(inc.name);
      }}
      tabIndex={0}
      aria-label={`Open incident ${inc.title}`}
    >
      <td className="px-4 py-3 align-middle">
        <div className="flex items-start gap-3">
          <span
            className={cn(
              "mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border shadow-inner",
              SEVERITY_BADGE[inc.severity],
            )}
            aria-hidden="true"
          >
            <SevIcon className="h-3.5 w-3.5" />
          </span>
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-foreground">{inc.title}</p>
            <p className="truncate text-xs text-muted-foreground">
              {inc.namespace}/{inc.name}
              {inc.workflow_run_id && <span className="ml-2 text-info-foreground">· run {inc.workflow_run_id.slice(0, 8)}</span>}
            </p>
          </div>
        </div>
      </td>
      <td className="px-4 py-3 align-middle">
        <Badge variant="outline" className={cn("gap-1", STATUS_BADGE[inc.status])}>
          <StatusIcon className="h-3 w-3" />
          {inc.status}
          {inc.escalated && <ArrowUpCircle className="h-3 w-3 text-warning-foreground" />}
        </Badge>
      </td>
      <td className="px-4 py-3 align-middle">
        <Badge variant="outline" className={SEVERITY_BADGE[inc.severity]}>
          {inc.severity}
        </Badge>
      </td>
      <td className="px-4 py-3 align-middle text-sm text-muted-foreground">
        {inc.assigned_agent ? (
          <span className="inline-flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-primary" aria-hidden="true" />
            {inc.assigned_agent}
          </span>
        ) : (
          <span className="text-muted-foreground/70">unassigned</span>
        )}
      </td>
      <td className="px-4 py-3 align-middle text-sm text-muted-foreground">{timeAgo(inc.created_at)}</td>
      <td className="px-4 py-3 align-middle text-right">
        <div className="flex justify-end gap-1.5" onClick={(e) => e.stopPropagation()}>
          {inc.status === "firing" && (
            <Button
              variant="ghost"
              size="sm"
              disabled={actionLoading === `${inc.name}-acknowledged`}
              onClick={() => onAction(inc.name, "acknowledged", "Acknowledged via dashboard")}
              className="text-info-foreground hover:bg-info/15"
            >
              {actionLoading === `${inc.name}-acknowledged` ? "..." : "Ack"}
            </Button>
          )}
          {inc.status === "acknowledged" && (
            <Button
              variant="ghost"
              size="sm"
              disabled={actionLoading === `${inc.name}-resolved`}
              onClick={() => onAction(inc.name, "resolved", "Resolved via dashboard")}
              className="text-success-foreground hover:bg-success/15"
            >
              {actionLoading === `${inc.name}-resolved` ? "..." : "Resolve"}
            </Button>
          )}
          {!["resolved", "closed"].includes(inc.status) && inc.status !== "acknowledged" && inc.status !== "firing" && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onSelect?.(inc.name)}
              className="text-muted-foreground"
            >
              Open
            </Button>
          )}
        </div>
      </td>
    </tr>
  );
}

function SelectPill<T extends string>({
  value,
  onChange,
  options,
  ariaLabel,
}: {
  value: T;
  onChange: (v: T) => void;
  options: Array<{ value: T; label: string }>;
  ariaLabel: string;
}) {
  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className="inline-flex h-9 items-center gap-0.5 rounded-[calc(var(--radius-md)-1px)] border border-border/70 bg-background/72 p-0.5"
    >
      {options.map((opt) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value || "all"}
            type="button"
            onClick={() => onChange(opt.value)}
            className={cn(
              "inline-flex h-7 items-center rounded-[calc(var(--radius-sm))] px-2.5 text-[11px] font-medium transition-colors",
              active
                ? "bg-primary/15 text-primary shadow-sm"
                : "text-muted-foreground hover:bg-accent/70 hover:text-accent-foreground",
            )}
            aria-pressed={active}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

function AutoRefreshControl({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <div
      role="group"
      aria-label="Auto refresh"
      className="inline-flex h-9 items-center gap-0.5 rounded-[calc(var(--radius-md)-1px)] border border-border/70 bg-background/72 p-0.5"
    >
      {AUTO_REFRESH_OPTIONS.map((opt) => {
        const isActive = value === opt.value;
        return (
          <button
            key={opt.value}
            type="button"
            onClick={() => onChange(opt.value)}
            className={cn(
              "inline-flex h-7 items-center gap-1 rounded-[calc(var(--radius-sm))] px-2.5 text-[11px] font-medium transition-colors",
              isActive
                ? "bg-primary/15 text-primary shadow-sm"
                : "text-muted-foreground hover:bg-accent/70 hover:text-accent-foreground",
            )}
            aria-pressed={isActive}
            aria-label={opt.value === 0 ? "Auto refresh off" : `Auto refresh every ${opt.label}`}
          >
            {isActive && opt.value > 0 ? <Pause className="h-3 w-3" /> : <Play className="h-3 w-3" />}
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

function StatCard({
  label,
  value,
  tone,
  icon: Icon,
  loading,
}: {
  label: string;
  value: number;
  tone: "destructive" | "warning" | "info" | "success";
  icon: typeof AlertTriangle;
  loading?: boolean;
}) {
  const toneClass: Record<typeof tone, string> = {
    destructive: "border-destructive/25 bg-destructive/8 text-destructive",
    warning: "border-warning/25 bg-warning/8 text-warning-foreground",
    info: "border-info/25 bg-info/8 text-info-foreground",
    success: "border-success/25 bg-success/8 text-success-foreground",
  } as const;
  return (
    <Card className="hover-lift animate-slide-up" role="group" aria-label={`${label}: ${value}`}>
      <CardContent className="flex items-center justify-between p-4">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">{label}</p>
          {loading ? (
            <Skeleton className="mt-1 h-7 w-12" />
          ) : (
            <p className="mt-0.5 text-2xl font-semibold tabular-nums text-foreground">{value}</p>
          )}
        </div>
        <span
          className={cn("inline-flex h-9 w-9 items-center justify-center rounded-xl border shadow-inner", toneClass[tone])}
          aria-hidden="true"
        >
          <Icon className="h-4 w-4" />
        </span>
      </CardContent>
    </Card>
  );
}

function IncidentTableSkeleton() {
  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} className="flex items-center gap-3 border-b border-border/40 pb-3 last:border-b-0 last:pb-0">
            <Skeleton className="h-7 w-7 rounded-lg" />
            <div className="flex-1 space-y-1.5">
              <Skeleton className="h-3.5 w-1/2" />
              <Skeleton className="h-3 w-1/3" />
            </div>
            <Skeleton className="h-5 w-20 rounded-full" />
            <Skeleton className="h-5 w-16 rounded-full" />
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function timeAgo(ts: string): string {
  try {
    const now = Date.now();
    const then = new Date(ts).getTime();
    const diff = now - then;
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
  } catch {
    return ts;
  }
}
