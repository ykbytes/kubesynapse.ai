import { useCallback, useEffect, useMemo, useState } from "react";
import { downloadWorkflowRunTraceExport, fetchWorkflowRuns, type WorkflowRunRecord } from "@/lib/api";
import { useConnection } from "@/contexts/ConnectionContext";
import { useTheme } from "@/contexts/ThemeContext";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { History, RefreshCw, CheckCircle2, XCircle, Clock, Loader2, ChevronRight, Download, Timer, Maximize2, Minimize2 } from "lucide-react";
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
  expanded?: boolean;
  onExpandedChange?: (expanded: boolean) => void;
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
  expanded: expandedProp,
  onExpandedChange,
}: RunHistoryPanelProps) {
  const { token, namespace } = useConnection();
  const { theme } = useTheme();
  const [localExpanded, setLocalExpanded] = useState(false);
  const expanded = expandedProp ?? localExpanded;

  useEffect(() => {
    setLocalExpanded(false);
  }, [workflowName]);

  useEffect(() => {
    if (collapsed) setLocalExpanded(false);
  }, [collapsed]);

  useEffect(() => {
    if (!expanded) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onExpandedChange ? onExpandedChange(false) : setLocalExpanded(false);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [expanded, onExpandedChange]);

  const handleToggleExpand = useCallback(() => {
    const next = !expanded;
    onExpandedChange ? onExpandedChange(next) : setLocalExpanded(next);
  }, [expanded, onExpandedChange]);

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
  const panel = (
    <div className={cn(
      "flex flex-col overflow-hidden border-border/70 bg-card text-card-foreground",
      expanded
        ? "fixed inset-x-4 bottom-4 top-16 z-50 rounded-xl border shadow-2xl shadow-black/20"
        : "h-full rounded-none border-0 bg-transparent",
    )}>
      {/* Header */}
      <div className="flex items-center justify-between gap-2 border-b border-border/40 px-3 py-2 shrink-0">
        <div className="flex items-center gap-2">
          <History className="h-3.5 w-3.5 text-primary" />
          <span className="text-xs font-semibold text-foreground">Run History</span>
          {sortedRuns.length > 0 && (
            <Badge variant="outline" className="h-5 px-1.5 text-[10px]">{sortedRuns.length}</Badge>
          )}
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            onClick={handleToggleExpand}
            title={expanded ? "Restore" : "Maximize"}
          >
            {expanded ? <Minimize2 className="h-3 w-3" /> : <Maximize2 className="h-3 w-3" />}
          </Button>
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

      {/* Run list + selected detail — flex row */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* Run list */}
        <div className="w-1/2 min-w-0 border-r border-border/30 flex flex-col">
          <ScrollArea className="flex-1">
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
                const isTerminal = run.phase === "completed" || run.phase === "failed" || run.phase === "cancelled";
                return (
                  <button
                    key={run.id}
                    type="button"
                    onClick={() => setSelectedRunId(run.id)}
                    className={cn(
                      "w-full rounded-lg border px-2.5 py-2 text-left transition-all",
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
                      <span>{run.completed_steps ?? 0}/{run.total_steps ?? "?"} steps</span>
                      {dur != null && (
                        <span className="flex items-center gap-0.5">
                          <Timer className="h-2.5 w-2.5" /> {formatDuration(dur)}
                        </span>
                      )}
                      {run.failed_steps != null && run.failed_steps > 0 && (
                        <span className="text-red-600 dark:text-red-400">{run.failed_steps} failed</span>
                      )}
                      {isTerminal && (
                        <span className="ml-auto">
                          {run.trace_available ? "trace ✓" : run.archived_log_available ? "logs ✓" : ""}
                        </span>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          </ScrollArea>

          {/* Footer */}
          <div className="flex items-center gap-1 border-t border-border/40 px-2 py-2 shrink-0">
            <Button variant="ghost" size="sm" className="h-7 flex-1 rounded-lg text-[10px]" onClick={handleExportHistory} disabled={sortedRuns.length === 0}>
              <Download className="mr-1 h-3 w-3" /> History
            </Button>
            <Button variant="ghost" size="sm" className="h-7 flex-1 rounded-lg text-[10px]" onClick={handleExportSelectedRun} disabled={!selectedRun}>
              <Download className="mr-1 h-3 w-3" /> Run
            </Button>
          </div>
        </div>

        {/* Selected run detail */}
        <div className="w-1/2 min-w-0 flex flex-col">
          {selectedRun ? (
            <>
              <div className="border-b border-border/30 px-3 py-2 shrink-0">
                <div className="flex items-center gap-2">
                  {phaseIcon(selectedRun.phase)}
                  <Badge variant="outline" className={cn("h-[18px] border px-1.5 text-[9px] capitalize", phaseColor(selectedRun.phase))}>
                    {selectedRun.phase}
                  </Badge>
                  <span className="text-xs font-medium text-foreground">
                    Run #{sortedRuns.findIndex((r) => r.id === selectedRun.id) + 1}
                  </span>
                  {selectedRun.run_id && (
                    <span className="text-[9px] font-mono text-muted-foreground truncate ml-auto max-w-[120px]">
                      {selectedRun.run_id.slice(0, 20)}
                    </span>
                  )}
                </div>
              </div>
              <ScrollArea className="flex-1">
                <div className="space-y-2 p-3">
                  {/* Timing */}
                  <div className="rounded-lg border border-border/40 bg-background/60 p-2.5 space-y-1.5">
                    <div className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/60">Timing</div>
                    <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[10px]">
                      <span className="text-muted-foreground">Started</span>
                      <span className="text-right font-mono">{formatTimestampFull(selectedRun.started_at)}</span>
                      <span className="text-muted-foreground">Completed</span>
                      <span className="text-right font-mono">{formatTimestampFull(selectedRun.completed_at) || "—"}</span>
                      <span className="text-muted-foreground">Duration</span>
                      <span className="text-right font-mono">{formatDuration(durationSeconds(selectedRun))}</span>
                    </div>
                  </div>

                  {/* Progress */}
                  <div className="rounded-lg border border-border/40 bg-background/60 p-2.5 space-y-1.5">
                    <div className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/60">Progress</div>
                    <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[10px]">
                      <span className="text-muted-foreground">Steps completed</span>
                      <span className="text-right font-mono">{selectedRun.completed_steps ?? 0}/{selectedRun.total_steps ?? "?"}</span>
                      <span className="text-muted-foreground">Steps failed</span>
                      <span className="text-right font-mono">{selectedRun.failed_steps ?? 0}</span>
                    </div>
                    {(selectedRun.total_steps ?? 0) > 0 && (
                      <div className="h-1 w-full rounded-full bg-muted/50 overflow-hidden">
                        <div
                          className={cn(
                            "h-full rounded-full transition-all",
                            selectedRun.phase === "completed" ? "bg-emerald-500" : selectedRun.phase === "failed" ? "bg-red-500" : "bg-amber-500",
                          )}
                          style={{ width: `${Math.round(((selectedRun.completed_steps ?? 0) / (selectedRun.total_steps ?? 1)) * 100)}%` }}
                        />
                      </div>
                    )}
                  </div>

                  {/* Data availability */}
                  <div className="rounded-lg border border-border/40 bg-background/60 p-2.5 space-y-1.5">
                    <div className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/60">Data</div>
                    <div className="flex flex-wrap gap-1">
                      <DataChip available={selectedRun.trace_available} label="Trace" />
                      <DataChip available={selectedRun.archived_log_available} label="Logs" />
                      <DataChip available={selectedRun.journal_available} label="Journal" />
                    </div>
                    {selectedRun.input_text && (
                      <div className="mt-1">
                        <div className="text-[9px] text-muted-foreground/60 mb-0.5">Input</div>
                        <p className="text-[10px] text-muted-foreground line-clamp-3 leading-relaxed">{selectedRun.input_text}</p>
                      </div>
                    )}
                  </div>
                </div>
              </ScrollArea>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center text-muted-foreground/60">
                <Clock className="h-6 w-6 mx-auto mb-2 opacity-40" />
                <p className="text-[10px]">Select a run to view details</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );

  return expanded ? (
    <>
      <div className={cn(
        "fixed inset-0 z-40 backdrop-blur-sm",
        theme === "light" ? "bg-black/20" : "bg-black/55",
      )} onClick={() => onExpandedChange ? onExpandedChange(false) : setLocalExpanded(false)} aria-hidden="true" />
      {panel}
    </>
  ) : panel;
}

function DataChip({ available, label }: { available: boolean; label: string }) {
  return (
    <span className={cn(
      "inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[9px] leading-none",
      available
        ? "text-emerald-600 dark:text-emerald-400 bg-emerald-500/10 border-emerald-500/20"
        : "text-muted-foreground/60 bg-muted/40 border-border/50",
    )}>
      {available ? <CheckCircle2 className="h-2.5 w-2.5" /> : <XCircle className="h-2.5 w-2.5" />}
      {label}
    </span>
  );
}
