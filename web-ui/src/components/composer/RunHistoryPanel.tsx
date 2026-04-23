import { useCallback, useEffect, useMemo, useState } from "react";
import { downloadWorkflowRunTraceExport, fetchWorkflowRuns, type WorkflowRunRecord } from "@/lib/api";
import { useConnection } from "@/contexts/ConnectionContext";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { History, RefreshCw, CheckCircle2, XCircle, Clock, Loader2, ChevronRight, Download } from "lucide-react";
import { cn } from "@/lib/utils";

interface RunHistoryPanelProps {
  workflowName: string;
  collapsed?: boolean;
  onToggle?: () => void;
  collapsible?: boolean;
  onSelectRun?: (run: WorkflowRunRecord | null) => void;
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

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "-";
  return parsed.toLocaleString();
}

function formatRelative(value: string | null | undefined): string {
  if (!value) return "Unknown";
  const parsed = new Date(value).getTime();
  if (Number.isNaN(parsed)) return "Unknown";
  const deltaSeconds = Math.max(0, Math.round((Date.now() - parsed) / 1000));
  if (deltaSeconds < 60) return `${deltaSeconds}s ago`;
  if (deltaSeconds < 3600) return `${Math.floor(deltaSeconds / 60)}m ago`;
  if (deltaSeconds < 86400) return `${Math.floor(deltaSeconds / 3600)}h ago`;
  return `${Math.floor(deltaSeconds / 86400)}d ago`;
}

function runNarrative(run: WorkflowRunRecord, baseline: WorkflowRunRecord | null): { title: string; body: string; tone: string } {
  const completedSteps = run.completed_steps ?? 0;
  const failedSteps = run.failed_steps ?? 0;
  const totalSteps = run.total_steps ?? 0;

  if (run.phase === "completed") {
    return {
      title: "The selected run landed cleanly",
      body: baseline && baseline.phase !== "completed"
        ? "This execution recovered from a previously unhealthy state. Compare the input and preserved steps before promoting the definition changes further."
        : `Completed ${completedSteps} of ${totalSteps || completedSteps} steps with no terminal failure. Use this as the clean baseline when comparing later regressions.`,
      tone: "border-emerald-500/20 bg-emerald-500/10",
    };
  }

  if (run.phase === "failed") {
    return {
      title: "This run needs triage before another full replay",
      body: baseline && baseline.phase === "completed"
        ? "A healthy execution regressed into failure. Compare the changed input, runtime source, and failure count before retrying the whole workflow."
        : `The run ended with ${failedSteps} failed step${failedSteps === 1 ? "" : "s"}. Use the trace panel to isolate whether the break was approval-related, agent-runtime specific, or data-contract related.`,
      tone: "border-red-500/20 bg-red-500/10",
    };
  }

  if (run.phase === "running") {
    return {
      title: "This run is still in motion",
      body: `The workflow has completed ${completedSteps} step${completedSteps === 1 ? "" : "s"} so far. Keep the trace cockpit open and watch for approval waits, retries, or runtime drift.`,
      tone: "border-amber-500/20 bg-amber-500/10",
    };
  }

  if (run.phase === "cancelled") {
    return {
      title: "The run was intentionally interrupted",
      body: "Treat this as an operator decision point rather than a clean failure. The input and partial progress can still help when deciding what to retry or redesign.",
      tone: "border-orange-500/20 bg-orange-500/10",
    };
  }

  return {
    title: "This run is available as context",
    body: "Use the metadata and input snapshot below to compare execution posture across runs and spot drift in the workflow definition over time.",
    tone: "border-border/60 bg-muted/20",
  };
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

export function RunHistoryPanel({ workflowName, collapsed = false, onToggle, collapsible = true, onSelectRun }: RunHistoryPanelProps) {
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
    () => [...runs].sort((left, right) => new Date(right.created_at ?? 0).getTime() - new Date(left.created_at ?? 0).getTime()),
    [runs],
  );

  useEffect(() => {
    if (sortedRuns.length === 0) {
      setSelectedRunId(null);
      return;
    }
    setSelectedRunId((current) => (current && sortedRuns.some((run) => run.id === current) ? current : sortedRuns[0].id));
  }, [sortedRuns]);

  const latestRun = sortedRuns[0] ?? null;
  const previousRun = sortedRuns[1] ?? null;
  const selectedRun = sortedRuns.find((run) => run.id === selectedRunId) ?? latestRun;
  const selectedIndex = selectedRun ? sortedRuns.findIndex((run) => run.id === selectedRun.id) : -1;
  const comparisonRun = selectedIndex >= 0 ? sortedRuns[selectedIndex + 1] ?? null : previousRun;

  useEffect(() => {
    onSelectRun?.(selectedRun ?? null);
  }, [onSelectRun, selectedRun]);

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

  const aggregate = useMemo(() => {
    const durations = sortedRuns
      .map((run) => durationSeconds(run))
      .filter((value): value is number => value != null);
    const completedRuns = sortedRuns.filter((run) => run.phase === "completed").length;
    const failedRuns = sortedRuns.filter((run) => run.phase === "failed").length;
    return {
      totalRuns: sortedRuns.length,
      completedRuns,
      failedRuns,
      successRate: sortedRuns.length > 0 ? Math.round((completedRuns / sortedRuns.length) * 100) : 0,
      averageDuration: durations.length > 0 ? Math.round(durations.reduce((sum, value) => sum + value, 0) / durations.length) : null,
    };
  }, [sortedRuns]);

  const selectedNarrative = selectedRun ? runNarrative(selectedRun, comparisonRun) : null;

  const handleExportHistory = useCallback(() => {
    downloadJsonFile(
      {
        workflowName,
        exportedAt: new Date().toISOString(),
        selectedRunId,
        runs: sortedRuns,
      },
      `${workflowName}-run-history.json`,
    );
  }, [selectedRunId, sortedRuns, workflowName]);

  const handleExportSelectedRun = useCallback(() => {
    if (!selectedRun) return;
    if (selectedRun.run_id && token.trim()) {
      void downloadWorkflowRunTraceExport(token, namespace, workflowName, selectedRun.run_id).catch(() => {
        downloadJsonFile(
          {
            workflowName,
            exportedAt: new Date().toISOString(),
            run: selectedRun,
          },
          `${workflowName}-${selectedRun.run_id}.json`,
        );
      });
      return;
    }
    downloadJsonFile(
      {
        workflowName,
        exportedAt: new Date().toISOString(),
        run: selectedRun,
      },
      `${workflowName}-${selectedRun.run_id ?? `run-${selectedRun.id}`}.json`,
    );
  }, [namespace, selectedRun, token, workflowName]);

  if (collapsible && collapsed) {
    return (
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-3 rounded-2xl border border-border/60 bg-background/80 px-4 py-3 text-left transition-colors hover:bg-muted/30"
        title="Show run history"
      >
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-2xl border border-primary/20 bg-primary/10 text-primary">
            <History className="h-4 w-4" />
          </div>
          <div>
            <div className="text-xs font-semibold text-foreground">Run history and trace workspace</div>
            <div className="text-[11px] text-muted-foreground">Expand recent runs, compare outcomes, and inspect execution inputs.</div>
          </div>
        </div>
        <ChevronRight className="h-4 w-4 text-muted-foreground" />
      </button>
    );
  }

  return (
    <div className="rounded-[1.75rem] border border-border/60 bg-[linear-gradient(135deg,rgba(59,130,246,0.08),transparent_58%),linear-gradient(180deg,rgba(255,255,255,0.03),transparent)] p-4 shadow-[0_24px_80px_-48px_rgba(0,0,0,0.65)]">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <History className="h-4 w-4 text-primary" />
            Run history workspace
          </div>
          <p className="text-xs leading-relaxed text-muted-foreground">Compare executions, inspect the selected run, and export the run ledger without leaving the workflow page.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {collapsible && onToggle && (
            <Button
              variant="ghost"
              size="sm"
              className="h-8 rounded-xl text-xs"
              onClick={onToggle}
            >
              Collapse
            </Button>
          )}
          <Button
            variant="outline"
            size="sm"
            className="h-8 rounded-xl text-xs"
            onClick={handleExportHistory}
            disabled={sortedRuns.length === 0}
          >
            <Download className="mr-1.5 h-3.5 w-3.5" />
            Export history
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-8 rounded-xl text-xs"
            onClick={loadRuns}
            disabled={loading}
            title="Refresh"
          >
            <RefreshCw className={cn("mr-1.5 h-3.5 w-3.5", loading && "animate-spin")} />
            Refresh
          </Button>
        </div>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-2xl border border-border/60 bg-background/65 px-4 py-3">
          <div className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">Runs captured</div>
          <div className="mt-1 text-2xl font-semibold text-foreground">{aggregate.totalRuns}</div>
          <div className="mt-1 text-xs text-muted-foreground">Completed {aggregate.completedRuns} · failed {aggregate.failedRuns}</div>
        </div>
        <div className="rounded-2xl border border-border/60 bg-background/65 px-4 py-3">
          <div className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">Success rate</div>
          <div className="mt-1 text-2xl font-semibold text-foreground">{aggregate.successRate}%</div>
          <div className="mt-1 text-xs text-muted-foreground">Health trend across the recorded history.</div>
        </div>
        <div className="rounded-2xl border border-border/60 bg-background/65 px-4 py-3">
          <div className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">Average duration</div>
          <div className="mt-1 text-2xl font-semibold text-foreground">{formatDuration(aggregate.averageDuration)}</div>
          <div className="mt-1 text-xs text-muted-foreground">Based on runs with both start and completion timestamps.</div>
        </div>
        <div className="rounded-2xl border border-border/60 bg-background/65 px-4 py-3">
          <div className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">Latest posture</div>
          <div className="mt-1 flex items-center gap-2 text-sm font-medium text-foreground">
            {latestRun ? phaseIcon(latestRun.phase) : <Clock className="h-4 w-4 text-muted-foreground" />}
            <span className="capitalize">{latestRun?.phase ?? "No runs"}</span>
          </div>
          <div className="mt-1 text-xs text-muted-foreground">{latestRun ? formatRelative(latestRun.created_at) : "Run the workflow to create the first baseline."}</div>
        </div>
      </div>

      {latestRun && comparison && (
        <div className="mt-4 space-y-3">
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-2xl border border-border/60 bg-background/65 px-4 py-3">
              <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">Latest outcome</div>
              <div className="mt-1 flex items-center gap-1.5 text-sm font-medium text-foreground">
                {phaseIcon(latestRun.phase)}
                <span className="capitalize">{latestRun.phase}</span>
              </div>
              <div className="mt-1 text-[11px] text-muted-foreground">
                {latestRun.completed_steps ?? 0}/{latestRun.total_steps ?? "?"} steps · {formatDuration(durationSeconds(latestRun))}
              </div>
            </div>
            <div className="rounded-2xl border border-border/60 bg-background/65 px-4 py-3">
              <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">Failure delta</div>
              <div className="mt-1 text-sm font-medium text-foreground">
                {comparison.failedDelta == null ? "-" : comparison.failedDelta > 0 ? `+${comparison.failedDelta}` : String(comparison.failedDelta)}
              </div>
              <div className="mt-1 text-[11px] text-muted-foreground">Compared with the previous recorded run.</div>
            </div>
            <div className="rounded-2xl border border-border/60 bg-background/65 px-4 py-3">
              <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">Duration trend</div>
              <div className="mt-1 text-sm font-medium text-foreground">
                {comparison.previousDuration == null ? formatDuration(comparison.latestDuration) : `${formatDuration(comparison.latestDuration)} vs ${formatDuration(comparison.previousDuration)}`}
              </div>
              <div className="mt-1 text-[11px] text-muted-foreground">Operator view of execution speed across recent runs.</div>
            </div>
          </div>
          <div className={cn("rounded-2xl border px-4 py-3", comparison.tone)}>
            <div className="text-sm font-medium text-foreground">{comparison.title}</div>
            <div className="mt-1 text-xs leading-relaxed text-muted-foreground">{comparison.body}</div>
          </div>
        </div>
      )}

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(18rem,0.92fr)_minmax(0,1.08fr)]">
        <div className="rounded-[1.25rem] border border-border/60 bg-background/60 p-3">
          <div className="flex items-center justify-between gap-3 px-1 pb-3">
            <div>
              <div className="text-xs font-semibold text-foreground">Run navigator</div>
              <div className="text-[11px] text-muted-foreground">Select any recorded execution to inspect its metadata and input payload.</div>
            </div>
            {loading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
          </div>
          <ScrollArea className="h-[28rem] pr-2">
            <div className="space-y-2">
              {sortedRuns.length === 0 && !loading && (
                <div className="rounded-2xl border border-dashed border-border/60 bg-background/40 px-4 py-5 text-center text-xs text-muted-foreground">
                  No runs recorded yet. The first execution will establish comparison history.
                </div>
              )}
              {sortedRuns.map((run, index) => {
                const isSelected = selectedRun?.id === run.id;
                return (
                  <button
                    key={run.id}
                    type="button"
                    onClick={() => setSelectedRunId(run.id)}
                    className={cn(
                      "w-full rounded-2xl border px-4 py-3 text-left transition-all",
                      isSelected
                        ? "border-primary/35 bg-primary/10 shadow-[0_14px_40px_-28px_rgba(59,130,246,0.75)]"
                        : "border-border/60 bg-background/55 hover:border-primary/20 hover:bg-background/80",
                    )}
                  >
                    <div className="flex items-center gap-2">
                      {phaseIcon(run.phase)}
                      <Badge variant="outline" className={cn("h-5 border px-2 text-[10px] capitalize", phaseColor(run.phase))}>
                        {run.phase}
                      </Badge>
                      <span className="text-xs font-medium text-foreground">Run {index + 1}</span>
                      <span className="ml-auto text-[10px] text-muted-foreground">{formatRelative(run.created_at)}</span>
                    </div>
                    <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                      {run.run_id && <span className="font-mono text-foreground/80">{run.run_id.slice(0, 12)}</span>}
                      <span>{run.completed_steps ?? 0}/{run.total_steps ?? "?"} steps</span>
                      <span>{formatDuration(durationSeconds(run))}</span>
                      {run.archived_log_available && (
                        <Badge variant="outline" className="h-5 border-emerald-500/20 bg-emerald-500/10 px-2 text-[10px] text-emerald-300">
                          archived trace
                        </Badge>
                      )}
                      {!run.archived_log_available && run.trace_available && (
                        <Badge variant="outline" className="h-5 border-sky-500/20 bg-sky-500/10 px-2 text-[10px] text-sky-300">
                          trace ready
                        </Badge>
                      )}
                    </div>
                    {run.triggered_by && (
                      <div className="mt-2 truncate text-[11px] text-muted-foreground" title={run.triggered_by}>
                        Triggered by {run.triggered_by}
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
          </ScrollArea>
        </div>

        <div className="space-y-4">
          {selectedRun ? (
            <>
              <div className="rounded-[1.25rem] border border-border/60 bg-background/60 p-4">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div className="space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="outline" className={cn("border px-2 text-[10px] capitalize", phaseColor(selectedRun.phase))}>
                        {selectedRun.phase}
                      </Badge>
                      <span className="text-sm font-semibold text-foreground">Selected run</span>
                      {selectedRun.run_id && <span className="font-mono text-[11px] text-muted-foreground">{selectedRun.run_id}</span>}
                      {selectedRun.archived_log_available && (
                        <Badge variant="outline" className="border-emerald-500/20 bg-emerald-500/10 text-[10px] text-emerald-300">
                          archived trace available
                        </Badge>
                      )}
                      {!selectedRun.archived_log_available && selectedRun.trace_available && (
                        <Badge variant="outline" className="border-sky-500/20 bg-sky-500/10 text-[10px] text-sky-300">
                          run trace available
                        </Badge>
                      )}
                    </div>
                    <p className="text-xs leading-relaxed text-muted-foreground">{selectedNarrative?.body}</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-8 rounded-xl text-xs"
                      onClick={handleExportSelectedRun}
                    >
                      <Download className="mr-1.5 h-3.5 w-3.5" />
                      Export run
                    </Button>
                  </div>
                </div>

                <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  <div className="rounded-2xl border border-border/60 bg-background/65 px-3 py-3">
                    <div className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">Created</div>
                    <div className="mt-1 text-xs font-medium text-foreground">{formatTimestamp(selectedRun.created_at)}</div>
                  </div>
                  <div className="rounded-2xl border border-border/60 bg-background/65 px-3 py-3">
                    <div className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">Started</div>
                    <div className="mt-1 text-xs font-medium text-foreground">{formatTimestamp(selectedRun.started_at)}</div>
                  </div>
                  <div className="rounded-2xl border border-border/60 bg-background/65 px-3 py-3">
                    <div className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">Completed</div>
                    <div className="mt-1 text-xs font-medium text-foreground">{formatTimestamp(selectedRun.completed_at)}</div>
                  </div>
                  <div className="rounded-2xl border border-border/60 bg-background/65 px-3 py-3">
                    <div className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">Duration</div>
                    <div className="mt-1 text-xs font-medium text-foreground">{formatDuration(durationSeconds(selectedRun))}</div>
                  </div>
                </div>

                <div className="mt-4 grid gap-3 md:grid-cols-2">
                  <div className="rounded-2xl border border-border/60 bg-background/65 px-4 py-3">
                    <div className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">Run outcome</div>
                    <div className="mt-2 flex items-center gap-2 text-sm font-medium text-foreground">
                      {phaseIcon(selectedRun.phase)}
                      <span className="capitalize">{selectedRun.phase}</span>
                    </div>
                    <div className="mt-2 text-xs text-muted-foreground">
                      Completed {selectedRun.completed_steps ?? 0} of {selectedRun.total_steps ?? "?"} steps
                      {selectedRun.failed_steps != null ? ` · ${selectedRun.failed_steps} failed` : ""}
                    </div>
                    {selectedRun.triggered_by && (
                      <div className="mt-2 text-xs text-muted-foreground">Triggered by {selectedRun.triggered_by}</div>
                    )}
                  </div>
                  <div className={cn("rounded-2xl border px-4 py-3", selectedNarrative?.tone ?? "border-border/60 bg-muted/20")}>
                    <div className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">Operator brief</div>
                    <div className="mt-2 text-sm font-medium text-foreground">{selectedNarrative?.title ?? "Run context"}</div>
                    <div className="mt-1 text-xs leading-relaxed text-muted-foreground">{selectedNarrative?.body ?? "Use this run as the comparison anchor for later executions."}</div>
                  </div>
                </div>

                <div className="mt-4 rounded-2xl border border-border/60 bg-background/65 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-xs font-semibold text-foreground">Execution input</div>
                      <div className="text-[11px] text-muted-foreground">The exact input captured for this workflow execution.</div>
                    </div>
                    {comparisonRun && (
                      <div className="text-[11px] text-muted-foreground">Comparing against {comparisonRun.phase} from {formatRelative(comparisonRun.created_at)}</div>
                    )}
                  </div>
                  <div className="mt-3 rounded-2xl border border-border/60 bg-background/75 p-3">
                    {selectedRun.input_text ? (
                      <ScrollArea className="h-40 pr-3">
                        <pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-muted-foreground">{selectedRun.input_text}</pre>
                      </ScrollArea>
                    ) : (
                      <div className="text-xs text-muted-foreground">No input snapshot was stored for this run.</div>
                    )}
                  </div>
                </div>
              </div>

              <div className="grid gap-3 md:grid-cols-2">
                <div className="rounded-2xl border border-border/60 bg-background/60 px-4 py-3">
                  <div className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">Comparison baseline</div>
                  <div className="mt-1 text-sm font-medium text-foreground">{comparisonRun ? `Run ${selectedIndex + 2}` : "No older run available"}</div>
                  <div className="mt-2 text-xs text-muted-foreground">
                    {comparisonRun
                      ? `${comparisonRun.completed_steps ?? 0}/${comparisonRun.total_steps ?? "?"} steps · ${formatDuration(durationSeconds(comparisonRun))} · ${comparisonRun.phase}`
                      : "Record another execution to unlock side-by-side historical comparisons."}
                  </div>
                </div>
                <div className="rounded-2xl border border-border/60 bg-background/60 px-4 py-3">
                  <div className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">Trace workflow</div>
                  <div className="mt-1 text-sm font-medium text-foreground">Use the trace cockpit alongside this selection</div>
                  <div className="mt-2 text-xs leading-relaxed text-muted-foreground">The adjacent trace panel is the fastest way to inspect approvals, tool calls, runtime errors, and exported log evidence while this selected run is your comparison anchor.</div>
                </div>
              </div>
            </>
          ) : (
            <div className="rounded-[1.25rem] border border-dashed border-border/60 bg-background/40 px-5 py-8 text-center text-sm text-muted-foreground">
              Run the workflow to establish the first historical record.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
