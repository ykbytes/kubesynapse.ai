import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  CheckCircle2,
  Database,
  Layers,
  RefreshCw,
  Server,
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

  const load = useCallback(async () => {
    if (!token.trim()) return;
    setLoading(true);
    try {
      const result = await fetchSystemHealth(token, namespace);
      setData(result);
    } catch (err) {
      toast.error("Failed to load system health");
    } finally {
      setLoading(false);
    }
  }, [token, namespace]);

  useEffect(() => { void load(); }, [load]);

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
                      <span>Evals: <strong>{(check.evals as Record<string, unknown>).total as number}</strong></span>
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
                </CardContent>
              </Card>
            );
          })}
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-border/50 bg-background/50 py-10 text-center animate-fade-in">
          <Activity className="h-6 w-6 text-muted-foreground/60" />
          <p className="text-sm text-muted-foreground">Click <strong>Refresh</strong> to check system health</p>
          <Button size="sm" variant="outline" onClick={() => void load()}>
            <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
            Check now
          </Button>
        </div>
      )}
    </div>
  );
}
