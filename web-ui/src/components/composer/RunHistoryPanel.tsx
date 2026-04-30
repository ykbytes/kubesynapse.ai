import { useCallback, useEffect, useMemo, useState } from "react";
import { downloadWorkflowRunTraceExport, fetchWorkflowRuns, type WorkflowRunRecord } from "@/lib/api";
import { useConnection } from "@/contexts/ConnectionContext";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { History, RefreshCw, CheckCircle2, XCircle, Clock, Loader2, ChevronRight, Download } from "lucide-react";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

export function phaseIcon(phase: string) {
  switch (phase) {
    case "completed": return <CheckCircle2 className="h-3 w-3 text-emerald-600 dark:text-emerald-400" />;
    case "failed": return <XCircle className="h-3 w-3 text-red-600 dark:text-red-400" />;
    case "running": return <Loader2 className="h-3 w-3 text-amber-600 dark:text-amber-400 animate-spin" />;
    case "cancelled": return <XCircle className="h-3 w-3 text-muted-foreground" />;
    default: return <Clock className="h-3 w-3 text-muted-foreground" />;
  }
}

export function phaseColor(phase: string): string {
  switch (phase) {
    case "completed": return "text-emerald-600 dark:text-emerald-400 bg-emerald-500/10 border-emerald-500/25";
    case "failed": return "text-red-600 dark:text-red-400 bg-red-500/10 border-red-500/25";
    case "running": return "text-amber-600 dark:text-amber-400 bg-amber-500/10 border-amber-500/25";
    case "cancelled": return "text-muted-foreground bg-muted/50 border-border";
    default: return "text-muted-foreground bg-muted/50 border-border";
  }
}

export function phaseAccent(phase: string): string {
  switch (phase) {
    case "completed": return "border-l-emerald-500";
    case "failed": return "border-l-red-500";
    case "running": return "border-l-amber-500";
    default: return "border-l-border";
  }
}

export function durationSeconds(run: WorkflowRunRecord | null | undefined): number | null {
  if (!run?.started_at || !run?.completed_at) return null;
  const started = new Date(run.started_at).getTime();
  const completed = new Date(run.completed_at).getTime();
  if (Number.isNaN(started) || Number.isNaN(completed)) return null;
  return Math.max(0, Math.round((completed - started) / 1000));
}

export function formatDuration(seconds: number | null): string {
  if (seconds == null) return "\u2014";
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${minutes}m ${remainder}s`;
}

export function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "-";
  return parsed.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function formatTimestampFull(value: string | null | undefined): string {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "-";
  return parsed.toLocaleString();
}

export function formatRelative(value: string | null | undefined): string {
  if (!value) return "Unknown";
  const parsed = new Date(value).getTime();
  if (Number.isNaN(parsed)) return "Unknown";
  const deltaSeconds = Math.max(0, Math.round((Date.now() - parsed) / 1000));
  if (deltaSeconds < 60) return `${deltaSeconds}s ago`;
  if (deltaSeconds < 3600) return `${Math.floor(deltaSeconds / 60)}m ago`;
  if (deltaSeconds < 86400) return `${Math.floor(deltaSeconds / 3600)}h ago`;
  return `${Math.floor(deltaSeconds / 86400)}d ago`;
}

function downloadJsonFile(payload: unknown, filename: string) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}

/* ------------------------------------------------------------------ */
/*  Props                                                              */
/* ------------------------------------------------------------------ */

interface RunHistoryPanelProps {
  workflowName: string;
  collapsed?: boolean;
  onToggle?: () => void;
  collapsible?: boolean;
  onSelectRun?: (run: WorkflowRunRecord | null) => void;
}

/* ------------------------------------------------------------------ */
/*  Component — slim sidebar run list                                  */
/* ------------------------------------------------------------------ */

export function RunHistoryPanel({
  workflowName,
  collapsed = false,
  onToggle,
  collapsible = true,
  onSelectRun,
}: RunHistoryPanelProps) {
  const { token, namespace } = useConnection();
  const [runs, setRuns] = useState<WorkflowRunRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);

  const loadRuns = useCallback(() => {
    if (!workflowName || !token.trim()) return;
    setLoading(true);
    fetchWorkflowRuns(token, namespace, workflowName)
      .then(setRuns)
      .catch(() => setRuns([]))
      .finally(() => setLoading(false));
  }, [namespace, token, workflowName]);

  useEffect(() => {
    if (!collapsible || !collapsed) loadRuns();
  }, [collapsed, collapsible, loadRuns]);

  const sortedRuns = useMemo(
    () => [...runs].sort((a, b) => new Date(b.created_at ?? 0).getTime() - new Date(a.created_at ?? 0).getTime()),
    [runs],
  );

  useEffect(() => {
    if (sortedRuns.length === 0) { setSelectedRunId(null); return; }
    setSelectedRunId((cur) => (cur && sortedRuns.some((r) => r.id === cur) ? cur : sortedRuns[0].id));
  }, [sortedRuns]);

  const selectedRun = sortedRuns.find((r) => r.id === selectedRunId) ?? sortedRuns[0] ?? null;

  useEffect(() => { onSelectRun?.(selectedRun); }, [onSelectRun, selectedRun]);

  const handleExportHistory = useCallback(() => {
    downloadJsonFile({ workflowName, exportedAt: new Date().toISOString(), runs: sortedRuns }, `${workflowName}-run-history.json`);
  }, [sortedRuns, workflowName]);

  const handleExportSelectedRun = useCallback(() => {
    if (!selectedRun) return;
    if (selectedRun.run_id && token.trim()) {
      void downloadWorkflowRunTraceExport(token, namespace, workflowName, selectedRun.run_id).catch(() => {
        downloadJsonFile({ workflowName, exportedAt: new Date().toISOString(), run: selectedRun }, `${workflowName}-${selectedRun.run_id}.json`);
      });
      return;
    }
    downloadJsonFile({ workflowName, exportedAt: new Date().toISOString(), run: selectedRun }, `${workflowName}-${selectedRun.run_id ?? `run-${selectedRun.id}`}.json`);
  }, [namespace, selectedRun, token, workflowName]);

  /* Collapsed / collapsible toggle */
  if (collapsible && collapsed) {
    return (
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-3 rounded-xl border border-border/60 bg-background/80 px-4 py-3 text-left transition-colors hover:bg-muted/30"
        title="Show run history"
      >
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary">
            <History className="h-4 w-4" />
          </div>
          <div>
            <div className="text-xs font-semibold text-foreground">Run history</div>
            <div className="text-[11px] text-muted-foreground">Expand to browse past executions.</div>
          </div>
        </div>
        <ChevronRight className="h-4 w-4 text-muted-foreground" />
      </button>
    );
  }

  /* Full sidebar */
  return (
    <div className="flex h-full flex-col rounded-xl border border-border/60 bg-background/70">
      {/* Header */}
      <div className="flex items-center justify-between gap-2 border-b border-border/40 px-3 py-2.5">
        <div className="flex items-center gap-2">
          <History className="h-3.5 w-3.5 text-primary" />
          <span className="text-xs font-semibold text-foreground">Runs</span>
          {sortedRuns.length > 0 && (
            <Badge variant="outline" className="h-5 px-1.5 text-[10px]">{sortedRuns.length}</Badge>
          )}
        </div>
        <div className="flex items-center gap-1">
          {collapsible && onToggle && (
            <Button variant="ghost" size="icon" className="h-6 w-6" onClick={onToggle} title="Collapse">
              <ChevronRight className="h-3 w-3" />
            </Button>
          )}
          <Button variant="ghost" size="icon" className="h-6 w-6" onClick={loadRuns} disabled={loading} title="Refresh">
            <RefreshCw className={cn("h-3 w-3", loading && "animate-spin")} />
          </Button>
        </div>
      </div>

      {/* Run list */}
      <ScrollArea className="flex-1 min-h-0">
        <div className="space-y-1 p-2">
          {sortedRuns.length === 0 && !loading && (
            <div className="rounded-xl border border-dashed border-border/50 px-3 py-4 text-center text-[11px] text-muted-foreground">
              No runs recorded yet.
            </div>
          )}
          {loading && sortedRuns.length === 0 && (
            <div className="flex items-center justify-center gap-2 py-6 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading...
            </div>
          )}
          {sortedRuns.map((run, index) => {
            const isSelected = selectedRun?.id === run.id;
            const dur = durationSeconds(run);
            return (
              <button
                key={run.id}
                type="button"
                onClick={() => setSelectedRunId(run.id)}
                className={cn(
                  "w-full rounded-xl border px-3 py-2.5 text-left transition-all",
                  isSelected
                    ? "border-primary/30 bg-primary/10"
                    : "border-transparent bg-transparent hover:border-border/40 hover:bg-muted/20",
                )}
              >
                <div className="flex items-center gap-1.5">
                  {phaseIcon(run.phase)}
                  <Badge variant="outline" className={cn("h-[18px] border px-1.5 text-[9px] capitalize leading-none", phaseColor(run.phase))}>
                    {run.phase}
                  </Badge>
                  <span className="text-[11px] font-medium text-foreground">Run {sortedRuns.length - index}</span>
                  <span className="ml-auto text-[10px] text-muted-foreground">{formatRelative(run.created_at)}</span>
                </div>
                <div className="mt-1.5 flex items-center gap-2 text-[10px] text-muted-foreground">
                  {run.run_id && <span className="font-mono truncate max-w-[7rem]">{run.run_id.slice(0, 14)}</span>}
                  <span>{run.completed_steps ?? 0}/{run.total_steps ?? "?"} steps</span>
                  {dur != null && <span>{formatDuration(dur)}</span>}
                </div>
              </button>
            );
          })}
        </div>
      </ScrollArea>

      {/* Footer */}
      <div className="flex items-center gap-1 border-t border-border/40 px-2 py-2">
        <Button variant="ghost" size="sm" className="h-7 flex-1 rounded-lg text-[10px]" onClick={handleExportHistory} disabled={sortedRuns.length === 0}>
          <Download className="mr-1 h-3 w-3" /> History
        </Button>
        <Button variant="ghost" size="sm" className="h-7 flex-1 rounded-lg text-[10px]" onClick={handleExportSelectedRun} disabled={!selectedRun}>
          <Download className="mr-1 h-3 w-3" /> Run
        </Button>
      </div>
    </div>
  );
}
