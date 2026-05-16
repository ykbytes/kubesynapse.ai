import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowRight,
  CheckCircle2,
  Database,
  Layers,
  RefreshCw,
  Server,
  ShieldCheck,
  XCircle,
  AlertTriangle,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useConnection } from "@/contexts/ConnectionContext";
import { fetchSystemHealth, type SystemHealth } from "@/lib/api";
import { toast } from "sonner";
import { EmptyState } from "../shared/EmptyState";

function StatusIcon({ status }: { status: string }) {
  if (status === "ok" || status === "healthy") return <CheckCircle2 className="h-4 w-4 text-emerald-400" />;
  if (status === "error" || status === "degraded") return <XCircle className="h-4 w-4 text-red-400" />;
  if (status === "configured") return <CheckCircle2 className="h-4 w-4 text-blue-400" />;
  if (status === "not_configured") return <AlertTriangle className="h-4 w-4 text-amber-400" />;
  return <Activity className="h-4 w-4 text-muted-foreground" />;
}

function statusBadgeVariant(status: string): "default" | "secondary" | "destructive" | "outline" {
  if (status === "ok" || status === "healthy" || status === "configured") return "default";
  if (status === "error" || status === "degraded") return "destructive";
  return "secondary";
}

const CHECK_ICONS: Record<string, typeof Server> = {
  database: Database,
  kubernetes: Server,
  resources: Layers,
  nats: Activity,
  qdrant: Database,
};

export function HealthDashboard() {
  const { token, namespace } = useConnection();
  const [data, setData] = useState<SystemHealth | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!token.trim()) return;
    setLoading(true);
    setError("");
    try {
      const result = await fetchSystemHealth(token, namespace);
      setData(result);
    } catch {
      setError("The gateway responded, but the platform health check could not be completed.");
      toast.error("Failed to load system health");
    } finally {
      setLoading(false);
    }
  }, [token, namespace]);

  useEffect(() => { void load(); }, [load]);

  const checkEntries = useMemo(() => Object.entries(data?.checks ?? {}), [data]);
  const checkSummary = useMemo(() => {
    const meaningfulChecks = checkEntries.filter(([key]) => key !== "resources");
    const healthy = meaningfulChecks.filter(([, check]) => {
      const status = String((check as Record<string, unknown>).status ?? "unknown");
      return status === "ok" || status === "healthy" || status === "configured";
    }).length;
    const unhealthy = meaningfulChecks.length - healthy;
    const notConfigured = meaningfulChecks.filter(([, check]) => String((check as Record<string, unknown>).status ?? "") === "not_configured").length;
    return { total: meaningfulChecks.length, healthy, unhealthy, notConfigured };
  }, [checkEntries]);
  const resourceCheck = useMemo(() => {
    const raw = data?.checks?.resources as Record<string, unknown> | undefined;
    if (!raw) return null;
    const agents = (raw.agents as Record<string, unknown> | undefined)?.total as number | undefined;
    const workflows = (raw.workflows as Record<string, unknown> | undefined)?.total as number | undefined;
    const policies = (raw.policies as Record<string, unknown> | undefined)?.total as number | undefined;
    return {
      agents: agents ?? 0,
      workflows: workflows ?? 0,
      policies: policies ?? 0,
      total: (agents ?? 0) + (workflows ?? 0) + (policies ?? 0),
    };
  }, [data]);
  const postureNotes = useMemo(() => {
    if (!data) return [] as { tone: "success" | "warning" | "error"; title: string; body: string }[];

    const notes: { tone: "success" | "warning" | "error"; title: string; body: string }[] = [];
    if (data.status === "error" || data.status === "degraded") {
      notes.push({
        tone: "error",
        title: "Platform attention required",
        body: "One or more subsystems are degraded. Review the failing checks below before expanding usage or blaming runtime behavior.",
      });
    }
    if (checkSummary.notConfigured > 0) {
      notes.push({
        tone: "warning",
        title: "Configuration gaps detected",
        body: "Some subsystems are reachable but not fully configured. Resolve those before calling the platform production-ready.",
      });
    }
    if ((resourceCheck?.total ?? 0) === 0) {
      notes.push({
        tone: "warning",
        title: "No managed resources yet",
        body: "The control plane is reachable, but there are no provisioned agents, workflows, or policies in this namespace.",
      });
    }
    if (notes.length === 0) {
      notes.push({
        tone: "success",
        title: "Operational baseline looks good",
        body: "Connectivity, auth posture, and subsystem checks are in a healthy state for continued validation and demos.",
      });
    }
    return notes;
  }, [checkSummary.notConfigured, data, resourceCheck]);

  if (!token.trim()) {
    return (
      <EmptyState
        icon={ShieldCheck}
        title="Connect to inspect platform health"
        description="Health checks require a gateway token and namespace context before the console can query subsystem status."
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-foreground">System Health</h3>
          <p className="text-xs text-muted-foreground">
            {data ? `Last checked: ${new Date(data.timestamp).toLocaleTimeString()}` : "Not checked yet"}
          </p>
        </div>
        <Button size="sm" variant="outline" onClick={() => void load()} disabled={loading} aria-label="Refresh system health status">
          <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      {error && (
        <div className="rounded-2xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {data && (
        <div className="grid gap-3 lg:grid-cols-4">
          <Card className="border-border/70 bg-card/80">
            <CardContent className="flex items-center gap-3 py-4">
              <StatusIcon status={data.status} />
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">Platform</div>
                <div className="text-lg font-semibold capitalize text-foreground">{data.status}</div>
              </div>
            </CardContent>
          </Card>
          <Card className="border-border/70 bg-card/80">
            <CardContent className="py-4">
              <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">Subsystems</div>
              <div className="mt-1 text-lg font-semibold text-foreground">{checkSummary.healthy}/{checkSummary.total || 0}</div>
              <p className="mt-1 text-xs text-muted-foreground">Healthy checks across the active control-plane dependencies.</p>
            </CardContent>
          </Card>
          <Card className="border-border/70 bg-card/80">
            <CardContent className="py-4">
              <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">Resources</div>
              <div className="mt-1 text-lg font-semibold text-foreground">{resourceCheck?.total ?? 0}</div>
              <p className="mt-1 text-xs text-muted-foreground">Agents, workflows, and policies tracked in this namespace.</p>
            </CardContent>
          </Card>
          <Card className="border-border/70 bg-card/80">
            <CardContent className="py-4">
              <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">Auth posture</div>
              <div className="mt-1 text-lg font-semibold capitalize text-foreground">{data.auth_mode}</div>
              <p className="mt-1 text-xs text-muted-foreground">Namespace {data.namespace} is being checked through the current gateway auth path.</p>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Overall status */}
      {data && (
        <Card>
          <CardContent className="flex items-center gap-3 py-4">
            <StatusIcon status={data.status} />
            <div className="flex-1">
              <span className="font-medium text-sm text-foreground capitalize">{data.status}</span>
              <p className="text-xs text-muted-foreground">
                Namespace: {data.namespace} · Auth: {data.auth_mode}
              </p>
            </div>
            <Badge variant={statusBadgeVariant(data.status)} className="capitalize">
              {data.status}
            </Badge>
          </CardContent>
        </Card>
      )}

      {data && (
        <div className="grid gap-3 lg:grid-cols-2">
          {postureNotes.map((note) => (
            <div
              key={note.title}
              className={
                note.tone === "success"
                  ? "rounded-2xl border border-emerald-500/20 bg-emerald-500/10 px-4 py-3"
                  : note.tone === "error"
                    ? "rounded-2xl border border-red-500/20 bg-red-500/10 px-4 py-3"
                    : "rounded-2xl border border-amber-500/20 bg-amber-500/10 px-4 py-3"
              }
            >
              <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                {note.tone === "success" ? <CheckCircle2 className="h-4 w-4 text-emerald-400" /> : note.tone === "error" ? <AlertTriangle className="h-4 w-4 text-red-400" /> : <AlertTriangle className="h-4 w-4 text-amber-400" />}
                {note.title}
              </div>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{note.body}</p>
            </div>
          ))}
        </div>
      )}

      {/* Subsystem checks */}
      {loading && !data ? (
        <div className="grid gap-3 md:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Card key={i}>
              <CardHeader className="pb-2">
                <div className="flex items-center gap-2">
                  <Skeleton className="h-4 w-4 rounded" />
                  <Skeleton className="h-4 w-24 rounded" />
                  <Skeleton className="ml-auto h-5 w-16 rounded-full" />
                </div>
              </CardHeader>
              <CardContent className="space-y-2">
                <Skeleton className="h-3 w-full rounded" />
                <Skeleton className="h-3 w-2/3 rounded" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : data ? (
        <div className="grid gap-3 md:grid-cols-2">
          {Object.entries(data.checks).map(([key, check]: [string, Record<string, unknown>]) => {
            const Icon = CHECK_ICONS[key] || Activity;
            const status = (check.status as string) ?? "unknown";
            return (
              <Card key={key}>
                <CardHeader className="pb-2">
                  <CardTitle className="text-xs font-medium text-muted-foreground flex items-center gap-2">
                    <Icon className="h-3.5 w-3.5" />
                    <span className="capitalize">{key}</span>
                    <Badge variant={statusBadgeVariant(status)} className="ml-auto text-[10px] capitalize">
                      {status}
                    </Badge>
                  </CardTitle>
                </CardHeader>
                <CardContent className="text-xs space-y-1">
                  {typeof check.message === "string" && (
                    <p className="text-destructive truncate" title={check.message}>
                      {check.message}
                    </p>
                  )}
                  {typeof check.url === "string" && (
                    <p className="text-muted-foreground font-mono truncate">{check.url}</p>
                  )}
                  {/* Resource counts */}
                  {key === "resources" && typeof check.agents === "object" && check.agents !== null && (
                    <div className="flex flex-wrap gap-2 mt-1">
                      <span>Agents: <strong>{(check.agents as Record<string, unknown>).total as number}</strong></span>
                      <span>Workflows: <strong>{(check.workflows as Record<string, unknown>).total as number}</strong></span>
                      <span>Policies: <strong>{(check.policies as Record<string, unknown>).total as number}</strong></span>
                    </div>
                  )}
                  {key === "resources" && typeof check.agents === "object" && check.agents !== null && (
                    <div className="flex flex-wrap gap-1 mt-1">
                      {Object.entries(
                        (check.agents as Record<string, unknown>).by_phase as Record<string, number>,
                      ).map(([phase, count]) => (
                        <Badge key={phase} variant="outline" className="text-[10px]">
                          {phase}: {count}
                        </Badge>
                      ))}
                    </div>
                  )}
                  {key !== "resources" && status !== "ok" && status !== "healthy" && status !== "configured" && (
                    <Button variant="ghost" size="sm" className="mt-2 h-6 px-0 text-[11px] text-primary hover:bg-transparent hover:text-primary/90">
                      Review and remediate
                      <ArrowRight className="ml-1 h-3 w-3" />
                    </Button>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      ) : (
        <EmptyState
          icon={Activity}
          title="Run the first health check"
          description="Query the gateway to validate connectivity, auth posture, and subsystem readiness for this namespace."
          action={{ label: "Check now", onClick: () => void load() }}
        />
      )}
    </div>
  );
}
