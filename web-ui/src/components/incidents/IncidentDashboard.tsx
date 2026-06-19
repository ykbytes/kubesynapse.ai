import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import {
  ArrowUpCircle,
  Bell,
  ChevronRight,
  Clock,
  RefreshCw,
  Search,
  Zap,
} from "lucide-react";
import type { IncidentInfo } from "../../types";
import { Button } from "@/components/ui/button";
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

const SEVERITY_STRIPE: Record<IncidentSeverity, string> = {
  critical: "bg-red-500",
  warning: "bg-amber-500",
  info: "bg-sky-500",
};

const SEVERITY_DOT: Record<IncidentSeverity, string> = {
  critical: "bg-red-500/80",
  warning: "bg-amber-500/80",
  info: "bg-sky-500/80",
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

interface DashboardProps {
  setSelectedIncident?: (name: string) => void;
  getToken: () => string;
  getNamespace: () => string;
  onOpenWorkflowRun?: (workflowName: string, runId?: string | null) => void;
  api: {
    listIncidents: (
      token: string,
      ns: string,
      params?: { status?: string; severity?: string; limit?: number; offset?: number },
    ) => Promise<{ incidents: IncidentInfo[]; total: number }>;
    updateIncidentStatus: (
      token: string,
      ns: string,
      name: string,
      body: { status?: string; message?: string },
    ) => Promise<IncidentInfo>;
    createIncident?: (
      token: string,
      ns: string,
      body: Partial<IncidentInfo> & { name: string; title: string },
    ) => Promise<IncidentInfo>;
  };
  onFireExampleAlert?: () => void | Promise<void>;
}

export function IncidentDashboard({
  setSelectedIncident,
  getToken,
  getNamespace,
  onOpenWorkflowRun,
  api,
  onFireExampleAlert,
}: DashboardProps) {
  const [incidents, setIncidents] = useState<IncidentInfo[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [severityFilter, setSeverityFilter] = useState<string>("");
  const [search, setSearch] = useState("");
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
    void fetchIncidents();
  }, [fetchIncidents]);

  useEffect(() => {
    if (refreshIntervalRef.current) clearInterval(refreshIntervalRef.current);
    if (autoRefresh > 0) {
      refreshIntervalRef.current = setInterval(() => void fetchIncidents(), autoRefresh * 1000);
    }
    return () => {
      if (refreshIntervalRef.current) clearInterval(refreshIntervalRef.current);
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
    const acknowledged = incidents.filter(
      (i) => i.status === "acknowledged" || i.status === "diagnosing",
    ).length;
    const resolved = incidents.filter(
      (i) => i.status === "resolved" || i.status === "remediated" || i.status === "closed",
    ).length;
    return { firing, escalated, acknowledged, resolved };
  }, [incidents]);

  const filtered = useMemo(() => {
    if (!search.trim()) return incidents;
    const q = search.toLowerCase();
    return incidents.filter(
      (i) =>
        i.title.toLowerCase().includes(q) ||
        i.name.toLowerCase().includes(q) ||
        i.namespace.toLowerCase().includes(q) ||
        (i.assigned_agent ?? "").toLowerCase().includes(q),
    );
  }, [incidents, search]);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between border-b border-border/30 px-5 py-3">
        <div>
          <h2 className="text-base font-semibold text-foreground">Incidents</h2>
          <p className="text-xs text-muted-foreground">
            Track firing alerts, escalations, and remediation
          </p>
        </div>
        <div className="flex items-center gap-2">
          {onFireExampleAlert && (
            <Button
              variant="outline"
              size="sm"
              onClick={fireExample}
              disabled={exampleFiring}
              className="h-7 text-xs"
            >
              <Zap className={cn("size-3.5", exampleFiring && "animate-pulse")} />
              {exampleFiring ? "Firing..." : "Fire example"}
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={fetchIncidents} className="h-7 text-xs">
            <RefreshCw className={cn("size-3.5", loading && "animate-spin")} />
            Refresh
          </Button>
        </div>
      </div>

      {/* Stats strip */}
      <div className="flex shrink-0 items-center gap-0 border-b border-border/30 px-5">
        <StatPill label="Firing" value={stats.firing} dotClass="bg-red-500/80" />
        <StatPill label="Escalated" value={stats.escalated} dotClass="bg-amber-500/80" />
        <StatPill label="In Progress" value={stats.acknowledged} dotClass="bg-sky-500/80" />
        <StatPill label="Resolved" value={stats.resolved} dotClass="bg-emerald-500/80" />
      </div>

      {/* Filter bar */}
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border/30 px-5 py-2.5">
        <div className="relative flex-1 min-w-[12rem]">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search incidents..."
            className="h-8 w-full rounded-lg border border-border/50 bg-muted/20 pl-8 pr-3 text-sm text-foreground placeholder:text-muted-foreground/60 focus:border-primary/40 focus:outline-none focus:ring-1 focus:ring-primary/20"
          />
        </div>
        <FilterDropdown
          value={statusFilter}
          onChange={setStatusFilter}
          options={[
            { value: "", label: "All statuses" },
            { value: "firing", label: "Firing" },
            { value: "acknowledged", label: "Acknowledged" },
            { value: "diagnosing", label: "Diagnosing" },
            { value: "remediated", label: "Remediated" },
            { value: "resolved", label: "Resolved" },
            { value: "closed", label: "Closed" },
            { value: "escalated", label: "Escalated" },
          ]}
        />
        <FilterDropdown
          value={severityFilter}
          onChange={setSeverityFilter}
          options={[
            { value: "", label: "All severities" },
            { value: "critical", label: "Critical" },
            { value: "warning", label: "Warning" },
            { value: "info", label: "Info" },
          ]}
        />
        <FilterDropdown
          value={String(autoRefresh)}
          onChange={(v) => setAutoRefresh(Number(v))}
          options={[
            { value: "0", label: "No refresh" },
            { value: "15", label: "Every 15s" },
            { value: "30", label: "Every 30s" },
            { value: "60", label: "Every 1m" },
          ]}
        />
        {(statusFilter || severityFilter || search) && (
          <Button
            variant="ghost"
            size="sm"
            className="h-8 text-xs text-muted-foreground"
            onClick={() => {
              setStatusFilter("");
              setSeverityFilter("");
              setSearch("");
            }}
          >
            Clear
          </Button>
        )}
      </div>

      {/* Error banner */}
      {error && (
        <div className="shrink-0 mx-5 mt-3 rounded-lg border border-red-500/20 bg-red-500/5 px-3 py-2 text-sm text-red-400">
          {error}
        </div>
      )}

      {/* Incident list */}
      <div className="flex-1 min-h-0 overflow-y-auto px-5 py-3">
        {loading && incidents.length === 0 ? (
          <div className="space-y-2">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="rounded-xl border border-border/30 p-4">
                <Skeleton className="h-4 w-1/2" />
                <Skeleton className="mt-2 h-3 w-3/4" />
                <Skeleton className="mt-3 h-5 w-32" />
              </div>
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <Bell className="size-8 text-muted-foreground/20" />
            <p className="mt-3 text-sm font-medium text-foreground">
              {incidents.length === 0 ? "No incidents" : "No matching incidents"}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {incidents.length === 0
                ? "All clear. Fire an example alert to see this in action."
                : "Adjust your filters and try again."}
            </p>
            {incidents.length === 0 && onFireExampleAlert && (
              <Button
                variant="outline"
                size="sm"
                className="mt-3"
                onClick={fireExample}
                disabled={exampleFiring}
              >
                <Zap className="size-3.5" />
                {exampleFiring ? "Firing..." : "Fire example alert"}
              </Button>
            )}
          </div>
        ) : (
          <div className="space-y-2">
            {filtered.map((inc) => (
              <IncidentCard
                key={inc.id}
                incident={inc}
                onSelect={setSelectedIncident}
                onAction={fastAction}
                onOpenWorkflowRun={onOpenWorkflowRun}
                actionLoading={actionLoading}
              />
            ))}
            <div className="pt-2 text-center text-xs text-muted-foreground/50">
              {filtered.length} shown · {total} total
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Incident Card ───────────────────────────────────────────────────────────

function IncidentCard({
  incident: inc,
  onSelect,
  onAction,
  onOpenWorkflowRun,
  actionLoading,
}: {
  incident: IncidentInfo;
  onSelect?: (name: string) => void;
  onAction: (name: string, status: IncidentStatus, message: string) => Promise<void>;
  onOpenWorkflowRun?: (workflowName: string, runId?: string | null) => void;
  actionLoading: string | null;
}) {
  const sev = inc.severity as IncidentSeverity;
  const status = inc.status as IncidentStatus;

  const handleWorkflowClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (inc.workflow_ref_name && onOpenWorkflowRun) {
      onOpenWorkflowRun(inc.workflow_ref_name, inc.workflow_run_id);
    }
  };

  // Key labels to show inline
  const labelEntries = Object.entries(inc.labels).filter(
    ([k]) => !["fingerprint", "alertname", "severity"].includes(k),
  );

  return (
    <div
      onClick={() => onSelect?.(inc.name)}
      className="group cursor-pointer overflow-hidden rounded-xl border border-border/40 bg-muted/15 transition-all hover:border-border/60 hover:bg-muted/25"
    >
      <div className="flex">
        {/* Severity stripe */}
        <div className={cn("w-1 shrink-0", SEVERITY_STRIPE[sev])} />

        <div className="min-w-0 flex-1 p-4">
          {/* Title + status row */}
          <div className="flex items-start gap-3">
            <div className="min-w-0 flex-1">
              <h3 className="truncate text-sm font-medium text-foreground">
                {inc.title}
              </h3>
              <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground/70 leading-relaxed">
                {inc.description || "No description provided."}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              <StatusBadge status={status} escalated={inc.escalated} />
              <SeverityBadge severity={sev} />
            </div>
          </div>

          {/* Labels */}
          {labelEntries.length > 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
              {labelEntries.slice(0, 4).map(([k, v]) => (
                <span key={k}>
                  <span className="text-muted-foreground/50">{k}:</span>{" "}
                  <span className="text-foreground/70 font-mono text-[11px]">{v}</span>
                </span>
              ))}
            </div>
          )}

          {/* Workflow link + agent + time + action */}
          <div className="mt-2.5 flex flex-wrap items-center gap-3">
            {/* Workflow run link */}
            {inc.workflow_ref_name && (
              <button
                type="button"
                onClick={handleWorkflowClick}
                className="inline-flex items-center gap-1 rounded-md border border-border/40 bg-muted/20 px-2 py-0.5 text-[11px] text-foreground/70 transition-colors hover:border-primary/30 hover:text-primary"
              >
                <ChevronRight className="size-3" />
                {inc.workflow_ref_name}
                {inc.workflow_run_id && (
                  <span className="text-muted-foreground/50 font-mono">
                    · {inc.workflow_run_id.slice(0, 16)}
                  </span>
                )}
              </button>
            )}

            {/* Source */}
            <span className="inline-flex items-center gap-1 text-xs text-muted-foreground/50">
              <span className="size-1.5 rounded-full bg-muted-foreground/30" />
              {inc.source}
            </span>

            {/* Agent */}
            {inc.assigned_agent && (
              <span className="text-xs text-muted-foreground/50">
                {inc.assigned_agent}
              </span>
            )}

            {/* Time */}
            <span className="inline-flex items-center gap-0.5 text-xs text-muted-foreground/40 tabular-nums">
              <Clock className="size-3" />
              {timeAgo(inc.created_at)}
            </span>

            {/* Quick action */}
            <div className="ml-auto" onClick={(e) => e.stopPropagation()}>
              {status === "firing" && (
                <Button
                  variant="outline"
                  size="sm"
                  className="h-6 px-2 text-[11px]"
                  disabled={actionLoading === `${inc.name}-acknowledged`}
                  onClick={() => onAction(inc.name, "acknowledged", "Acknowledged via dashboard")}
                >
                  {actionLoading === `${inc.name}-acknowledged` ? "..." : "Ack"}
                </Button>
              )}
              {(status === "acknowledged" || status === "diagnosing" || status === "remediated") && (
                <Button
                  variant="outline"
                  size="sm"
                  className="h-6 px-2 text-[11px]"
                  disabled={actionLoading === `${inc.name}-resolved`}
                  onClick={() => onAction(inc.name, "resolved", "Resolved via dashboard")}
                >
                  {actionLoading === `${inc.name}-resolved` ? "..." : "Resolve"}
                </Button>
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
      <span className={cn("size-1.5 rounded-full", SEVERITY_DOT[severity])} />
      {severity}
    </span>
  );
}

// ─── Stat Pill ───────────────────────────────────────────────────────────────

function StatPill({ label, value, dotClass }: { label: string; value: number; dotClass: string }) {
  return (
    <div className="flex items-center gap-2 px-3 py-2 border-l border-border/20 first:border-l-0">
      <span className={cn("size-2 rounded-full", dotClass)} />
      <span className="text-sm font-semibold tabular-nums text-foreground">{value}</span>
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
  );
}

// ─── Filter Dropdown ─────────────────────────────────────────────────────────

function FilterDropdown({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (v: string) => void;
  options: Array<{ value: string; label: string }>;
}) {
  const [open, setOpen] = useState(false);
  const selected = options.find((o) => o.value === value);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border/50 bg-muted/20 px-3 text-xs text-foreground transition-colors hover:bg-muted/40"
      >
        {selected?.label ?? "Select"}
        <ChevronRight className={cn("size-3 transition-transform", open && "rotate-90")} />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-50 mt-1 min-w-[10rem] rounded-lg border border-border/50 bg-popover p-1 shadow-lg">
            {options.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => {
                  onChange(opt.value);
                  setOpen(false);
                }}
                className={cn(
                  "block w-full rounded-md px-2.5 py-1.5 text-left text-xs transition-colors",
                  opt.value === value
                    ? "bg-primary/10 text-primary"
                    : "text-foreground hover:bg-muted/40",
                )}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function timeAgo(ts: string): string {
  try {
    const diff = Date.now() - new Date(ts).getTime();
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
