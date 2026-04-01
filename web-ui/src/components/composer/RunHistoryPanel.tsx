import { useEffect, useMemo, useState } from "react";
import { fetchWorkflowRuns, type WorkflowRunRecord } from "@/lib/api";
import { useConnection } from "@/contexts/ConnectionContext";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { History, RefreshCw, CheckCircle2, XCircle, Clock, Loader2, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

interface RunHistoryPanelProps {
  workflowName: string;
  collapsed: boolean;
  onToggle: () => void;
}

function phaseIcon(phase: string) {
  switch (phase) {
    case "completed": return <CheckCircle2 className="h-3 w-3 text-emerald-400" />;
    case "failed": return <XCircle className="h-3 w-3 text-red-400" />;
    case "running": return <Loader2 className="h-3 w-3 text-amber-400 animate-spin" />;
    case "cancelled": return <XCircle className="h-3 w-3 text-muted-foreground" />;
    default: return <Clock className="h-3 w-3 text-muted-foreground" />;
  }
}

function phaseColor(phase: string): string {
  switch (phase) {
    case "completed": return "text-emerald-400 bg-emerald-500/10 border-emerald-500/20";
    case "failed": return "text-red-400 bg-red-500/10 border-red-500/20";
    case "running": return "text-amber-400 bg-amber-500/10 border-amber-500/20";
    case "cancelled": return "text-muted-foreground bg-muted/50 border-border";
    default: return "text-muted-foreground bg-muted/50 border-border";
  }
}

function durationSeconds(run: WorkflowRunRecord | null | undefined): number | null {
  if (!run?.started_at || !run?.completed_at) return null;
  const started = new Date(run.started_at).getTime();
  const completed = new Date(run.completed_at).getTime();
  if (Number.isNaN(started) || Number.isNaN(completed)) return null;
  return Math.max(0, Math.round((completed - started) / 1000));
}

function formatDuration(seconds: number | null): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${minutes}m ${remainder}s`;
}

export function RunHistoryPanel({ workflowName, collapsed, onToggle }: RunHistoryPanelProps) {
  const { token, namespace } = useConnection();
  const [runs, setRuns] = useState<WorkflowRunRecord[]>([]);
  const [loading, setLoading] = useState(false);

  const loadRuns = () => {
    if (!workflowName || !token.trim()) return;
    setLoading(true);
    fetchWorkflowRuns(token, namespace, workflowName)
      .then(setRuns)
      .catch(() => setRuns([]))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (!collapsed) loadRuns();
  }, [workflowName, collapsed, token, namespace]);

  const sortedRuns = useMemo(
    () => [...runs].sort((left, right) => new Date(right.created_at ?? 0).getTime() - new Date(left.created_at ?? 0).getTime()),
    [runs],
  );
  const latestRun = sortedRuns[0] ?? null;
  const previousRun = sortedRuns[1] ?? null;
  const comparison = useMemo(() => {
    if (!latestRun) return null;
    const latestCompleted = latestRun.completed_steps ?? 0;
    const latestFailed = latestRun.failed_steps ?? 0;
    const latestDuration = durationSeconds(latestRun);
    const previousCompleted = previousRun?.completed_steps ?? 0;
    const previousFailed = previousRun?.failed_steps ?? 0;
    const previousDuration = durationSeconds(previousRun);
    const completedDelta = previousRun ? latestCompleted - previousCompleted : null;
    const failedDelta = previousRun ? latestFailed - previousFailed : null;

    if (latestRun.phase === "completed" && previousRun?.phase !== "completed") {
      return {
        tone: "border-emerald-500/20 bg-emerald-500/10",
        title: "Latest run recovered to green",
        body: "The newest execution completed successfully after the prior run did not. This is the right moment to compare inputs and preserved steps.",
        latestDuration,
        previousDuration,
        completedDelta,
        failedDelta,
      };
    }
    if (latestRun.phase === "failed" && previousRun?.phase === "completed") {
      return {
        tone: "border-red-500/20 bg-red-500/10",
        title: "Latest run regressed",
        body: "The most recent execution failed after a previously successful run. Review the changed input and failed steps before retrying blindly.",
        latestDuration,
        previousDuration,
        completedDelta,
        failedDelta,
      };
    }
    return {
      tone: "border-border/60 bg-muted/20",
      title: previousRun ? "Compare the latest two runs" : "First run captured",
      body: previousRun
        ? "Use run history to confirm whether failures, duration, or step completion are trending in the right direction."
        : "This workflow now has historical execution context. Future runs will show trend comparisons here.",
      latestDuration,
      previousDuration,
      completedDelta,
      failedDelta,
    };
  }, [latestRun, previousRun]);

  if (collapsed) {
    return (
      <button
        type="button"
        onClick={onToggle}
        className="flex items-center justify-center w-8 border-t border-border/40 bg-muted/10 hover:bg-muted/30 transition-colors cursor-pointer shrink-0"
        title="Show run history"
      >
        <History className="h-3.5 w-3.5 text-muted-foreground" />
      </button>
    );
  }

  return (
    <div className="border-t border-border/40 bg-background shrink-0">
      <div className="flex items-center justify-between px-3 py-1.5">
        <button
          type="button"
          onClick={onToggle}
          className="flex items-center gap-1.5 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider hover:text-foreground cursor-pointer"
        >
          <History className="h-3 w-3" /> Run History
        </button>
        <Button
          variant="ghost"
          size="icon"
          className="h-5 w-5 cursor-pointer"
          onClick={loadRuns}
          disabled={loading}
          title="Refresh"
        >
          <RefreshCw className={cn("h-3 w-3", loading && "animate-spin")} />
        </Button>
      </div>
      {latestRun && comparison && (
        <div className="px-3 pb-2 space-y-2">
          <div className="grid gap-2 sm:grid-cols-3">
            <div className="rounded-lg border border-border/50 bg-card/50 px-2.5 py-2">
              <div className="text-[9px] uppercase tracking-[0.14em] text-muted-foreground">Latest outcome</div>
              <div className="mt-1 flex items-center gap-1.5 text-sm font-medium text-foreground">
                {phaseIcon(latestRun.phase)}
                <span className="capitalize">{latestRun.phase}</span>
              </div>
              <div className="mt-1 text-[10px] text-muted-foreground">
                {latestRun.completed_steps ?? 0}/{latestRun.total_steps ?? "?"} steps · {formatDuration(durationSeconds(latestRun))}
              </div>
            </div>
            <div className="rounded-lg border border-border/50 bg-card/50 px-2.5 py-2">
              <div className="text-[9px] uppercase tracking-[0.14em] text-muted-foreground">Failure delta</div>
              <div className="mt-1 text-sm font-medium text-foreground">
                {comparison.failedDelta == null ? "—" : comparison.failedDelta > 0 ? `+${comparison.failedDelta}` : String(comparison.failedDelta)}
              </div>
              <div className="mt-1 text-[10px] text-muted-foreground">Compared with the previous recorded run.</div>
            </div>
            <div className="rounded-lg border border-border/50 bg-card/50 px-2.5 py-2">
              <div className="text-[9px] uppercase tracking-[0.14em] text-muted-foreground">Duration trend</div>
              <div className="mt-1 text-sm font-medium text-foreground">
                {comparison.previousDuration == null ? formatDuration(comparison.latestDuration) : `${formatDuration(comparison.latestDuration)} vs ${formatDuration(comparison.previousDuration)}`}
              </div>
              <div className="mt-1 text-[10px] text-muted-foreground">Operator view of execution speed across recent runs.</div>
            </div>
          </div>
          <div className={cn("rounded-lg border px-3 py-2", comparison.tone)}>
            <div className="text-[11px] font-medium text-foreground">{comparison.title}</div>
            <div className="mt-1 text-[10px] leading-relaxed text-muted-foreground">{comparison.body}</div>
          </div>
        </div>
      )}
      <div className="max-h-48 overflow-y-auto px-3 pb-2 space-y-1">
        {sortedRuns.length === 0 && !loading && (
          <p className="text-[10px] text-muted-foreground/60 text-center py-2">No runs recorded yet. The first execution will establish comparison history.</p>
        )}
        {sortedRuns.map((run) => (
          <RunRow key={run.id} run={run} />
        ))}
      </div>
    </div>
  );
}

function RunRow({ run }: { run: WorkflowRunRecord }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="rounded-md border bg-card/50 text-[10px]">
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        className="flex w-full items-center gap-2 px-2 py-1 text-left hover:bg-accent/30 transition-colors"
        aria-expanded={expanded}
        aria-label={`Run ${run.run_id?.slice(0, 8) ?? run.id} — ${run.phase}`}
      >
        <span className="transition-transform duration-150" style={{ transform: expanded ? "rotate(90deg)" : "rotate(0deg)" }}>
          <ChevronRight className="h-2.5 w-2.5 text-muted-foreground" />
        </span>
        {phaseIcon(run.phase)}
        <Badge variant="outline" className={cn("text-[9px] h-4 px-1.5 border", phaseColor(run.phase))}>
          {run.phase}
        </Badge>
        {run.run_id && (
          <span className="font-mono text-muted-foreground">{run.run_id.slice(0, 8)}</span>
        )}
        <span className="text-muted-foreground">
          {run.completed_steps ?? 0}/{run.total_steps ?? "?"} steps
        </span>
        {run.triggered_by && (
          <span className="text-muted-foreground/60 truncate max-w-20" title={run.triggered_by}>
            by {run.triggered_by}
          </span>
        )}
        <span className="ml-auto text-muted-foreground/60 font-mono shrink-0">
          {run.created_at ? new Date(run.created_at).toLocaleString() : ""}
        </span>
      </button>
      {expanded && (
        <div className="border-t border-border/30 px-2.5 py-1.5 space-y-1 text-[10px] text-muted-foreground">
          {run.run_id && <div><span className="font-medium">Run ID:</span> <span className="font-mono">{run.run_id}</span></div>}
          {run.started_at && <div><span className="font-medium">Started:</span> {new Date(run.started_at).toLocaleString()}</div>}
          {run.completed_at && <div><span className="font-medium">Completed:</span> {new Date(run.completed_at).toLocaleString()}</div>}
          {run.failed_steps != null && run.failed_steps > 0 && (
            <div><span className="font-medium text-red-400">Failed steps:</span> {run.failed_steps}</div>
          )}
          {run.input_text && (
            <div>
              <span className="font-medium">Input:</span>
              <pre className="mt-0.5 whitespace-pre-wrap break-all bg-muted/30 rounded px-1.5 py-1 max-h-24 overflow-y-auto font-mono">
                {run.input_text.length > 500 ? `${run.input_text.slice(0, 500)}…` : run.input_text}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
