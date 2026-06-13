import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowUpRight,
  CheckCircle2,
  Clock,
  Download,
  LoaderCircle,
  RefreshCw,
  Search,
  Timer,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useConnection } from "@/contexts/ConnectionContext";
import { useWorkspace } from "@/contexts/WorkspaceContext";
import {
  downloadWorkflowRunTraceExport,
  fetchWorkflowRuns,
  type WorkflowRunRecord,
} from "@/lib/api";
import type { WorkflowInfo } from "../../types";
import { cn } from "@/lib/utils";
import {
  durationSeconds,
  formatDuration,
  formatRelative,
  formatTimestampFull,
  phaseColor,
  phaseIcon,
} from "../composer/RunHistoryPanel";

interface WorkflowHistoryViewProps {
  workflow: WorkflowInfo;
  selectedHistoryRun: WorkflowRunRecord | null;
  setSelectedHistoryRun: (run: WorkflowRunRecord | null) => void;
  isActive: boolean;
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

function DataPill({ available, label }: { available?: boolean | null; label: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[10px]",
        available
          ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-600 dark:text-emerald-300"
          : "border-border/60 bg-muted/35 text-muted-foreground",
      )}
    >
      {available ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
      {label}
    </span>
  );
}

export function WorkflowHistoryView({
  workflow,
  selectedHistoryRun,
  setSelectedHistoryRun,
  isActive,
}: WorkflowHistoryViewProps) {
  const { token, namespace } = useConnection();
  const { openObservatoryForWorkflowRun } = useWorkspace();
  const [runs, setRuns] = useState<WorkflowRunRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState("");

  const loadRuns = useCallback(() => {
    if (!workflow.name || !token.trim()) {
      setRuns([]);
      setSelectedHistoryRun(null);
      return;
    }
    setLoading(true);
    fetchWorkflowRuns(token, namespace, workflow.name)
      .then((records) => setRuns(records))
      .catch(() => setRuns([]))
      .finally(() => setLoading(false));
  }, [namespace, setSelectedHistoryRun, token, workflow.name]);

  useEffect(() => {
    loadRuns();
  }, [loadRuns]);

  const sortedRuns = useMemo(
    () => [...runs].sort((a, b) => new Date(b.created_at ?? 0).getTime() - new Date(a.created_at ?? 0).getTime()),
    [runs],
  );

  const filteredRuns = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return sortedRuns;
    return sortedRuns.filter((run) =>
      [
        run.run_id,
        run.phase,
        run.triggered_by,
        run.input_text,
        run.created_at,
      ].some((value) => String(value ?? "").toLowerCase().includes(needle)),
    );
  }, [query, sortedRuns]);

  useEffect(() => {
    if (sortedRuns.length === 0) {
      setSelectedHistoryRun(null);
      return;
    }
    if (selectedHistoryRun && sortedRuns.some((run) => run.id === selectedHistoryRun.id)) return;
    setSelectedHistoryRun(sortedRuns[0]);
  }, [selectedHistoryRun, setSelectedHistoryRun, sortedRuns]);

  const selectedRun = selectedHistoryRun && sortedRuns.some((run) => run.id === selectedHistoryRun.id)
    ? selectedHistoryRun
    : sortedRuns[0] ?? null;

  const handleOpenObservatory = useCallback(() => {
    openObservatoryForWorkflowRun(workflow.name, selectedRun?.run_id ?? null);
  }, [openObservatoryForWorkflowRun, selectedRun?.run_id, workflow.name]);

  const handleExportHistory = useCallback(() => {
    downloadJsonFile({ workflowName: workflow.name, exportedAt: new Date().toISOString(), runs: sortedRuns }, `${workflow.name}-run-history.json`);
  }, [sortedRuns, workflow.name]);

  const handleExportSelectedRun = useCallback(() => {
    if (!selectedRun) return;
    if (selectedRun.run_id && token.trim()) {
      void downloadWorkflowRunTraceExport(token, namespace, workflow.name, selectedRun.run_id).catch(() => {
        downloadJsonFile({ workflowName: workflow.name, exportedAt: new Date().toISOString(), run: selectedRun }, `${workflow.name}-${selectedRun.run_id}.json`);
      });
      return;
    }
    downloadJsonFile({ workflowName: workflow.name, exportedAt: new Date().toISOString(), run: selectedRun }, `${workflow.name}-${selectedRun.run_id ?? `run-${selectedRun.id}`}.json`);
  }, [namespace, selectedRun, token, workflow.name]);

  const duration = durationSeconds(selectedRun);
  const completedSteps = selectedRun?.completed_steps ?? 0;
  const totalSteps = selectedRun?.total_steps ?? 0;
  const progressPct = totalSteps > 0 ? Math.round((completedSteps / totalSteps) * 100) : 0;

  return (
    <div className="grid min-h-[34rem] gap-0 overflow-hidden rounded-lg border border-border/70 bg-card/60 lg:grid-cols-[minmax(20rem,24rem)_minmax(0,1fr)]">
      <aside className="flex min-h-0 flex-col border-b border-border/60 bg-muted/15 lg:border-b-0 lg:border-r">
        <div className="flex items-center justify-between gap-3 border-b border-border/60 px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold text-foreground">Runs</h2>
            <p className="text-xs text-muted-foreground">
              {sortedRuns.length} execution{sortedRuns.length === 1 ? "" : "s"}
              {isActive ? " · live updates available" : ""}
            </p>
          </div>
          <Button type="button" variant="ghost" size="icon" className="h-8 w-8" onClick={loadRuns} disabled={loading} title="Refresh runs">
            <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
          </Button>
        </div>

        <div className="border-b border-border/60 p-3">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              className="h-9 pl-8 text-sm"
              placeholder="Search runs..."
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>
        </div>

        <ScrollArea className="min-h-0 flex-1">
          <div className="space-y-1 p-2">
            {loading && sortedRuns.length === 0 && (
              <div className="flex items-center justify-center gap-2 py-10 text-xs text-muted-foreground">
                <LoaderCircle className="h-4 w-4 animate-spin" />
                Loading runs...
              </div>
            )}
            {!loading && filteredRuns.length === 0 && (
              <div className="rounded-lg border border-dashed border-border/60 px-3 py-8 text-center text-xs text-muted-foreground">
                {sortedRuns.length === 0 ? "No runs have been recorded yet." : "No runs match your search."}
              </div>
            )}
            {filteredRuns.map((run) => {
              const isSelected = selectedRun?.id === run.id;
              const runDuration = durationSeconds(run);
              return (
                <button
                  key={run.id}
                  type="button"
                  onClick={() => setSelectedHistoryRun(run)}
                  className={cn(
                    "w-full rounded-md border px-3 py-2.5 text-left transition-colors",
                    isSelected
                      ? "border-primary/35 bg-primary/10 shadow-[inset_3px_0_0_hsl(var(--primary))]"
                      : "border-transparent hover:border-border/60 hover:bg-background/65",
                  )}
                >
                  <div className="flex min-w-0 items-center gap-2">
                    {phaseIcon(run.phase)}
                    <span className="min-w-0 truncate text-sm font-medium text-foreground">
                      Run {sortedRuns.length - sortedRuns.findIndex((candidate) => candidate.id === run.id)}
                    </span>
                    <Badge variant="outline" className={cn("ml-auto h-5 border px-2 text-[10px] capitalize", phaseColor(run.phase))}>
                      {run.phase}
                    </Badge>
                  </div>
                  <div className="mt-2 flex items-center gap-3 text-xs text-muted-foreground">
                    <span>{run.completed_steps ?? 0}/{run.total_steps ?? "?"} steps</span>
                    {runDuration != null && (
                      <span className="flex items-center gap-1">
                        <Timer className="h-3 w-3" />
                        {formatDuration(runDuration)}
                      </span>
                    )}
                    <span className="ml-auto">{formatRelative(run.created_at)}</span>
                  </div>
                  {run.run_id && (
                    <div className="mt-1 truncate font-mono text-[10px] text-muted-foreground/80">
                      {run.run_id}
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        </ScrollArea>

        <div className="flex items-center gap-2 border-t border-border/60 p-3">
          <Button variant="outline" size="sm" className="h-8 flex-1 rounded-md text-xs" onClick={handleExportHistory} disabled={sortedRuns.length === 0}>
            <Download className="mr-1.5 h-3.5 w-3.5" />
            History
          </Button>
          <Button variant="outline" size="sm" className="h-8 flex-1 rounded-md text-xs" onClick={handleExportSelectedRun} disabled={!selectedRun}>
            <Download className="mr-1.5 h-3.5 w-3.5" />
            Run
          </Button>
        </div>
      </aside>

      <section className="min-h-0 bg-background/45">
        {selectedRun ? (
          <div className="flex h-full min-h-0 flex-col">
            <div className="border-b border-border/60 px-5 py-4">
              <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
                <div className="min-w-0 space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    {phaseIcon(selectedRun.phase)}
                    <Badge variant="outline" className={cn("h-6 border px-2.5 text-xs capitalize", phaseColor(selectedRun.phase))}>
                      {selectedRun.phase}
                    </Badge>
                    {selectedRun.run_id && (
                      <span className="max-w-full truncate font-mono text-xs text-muted-foreground xl:max-w-[34rem]">
                        {selectedRun.run_id}
                      </span>
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
                    <span>Created {formatTimestampFull(selectedRun.created_at)}</span>
                    <span>Started {formatTimestampFull(selectedRun.started_at)}</span>
                    {selectedRun.completed_at && <span>Completed {formatTimestampFull(selectedRun.completed_at)}</span>}
                    {selectedRun.triggered_by && <span>Triggered by {selectedRun.triggered_by}</span>}
                  </div>
                </div>
                <Button type="button" variant="outline" size="sm" className="h-9 shrink-0 rounded-md text-xs" onClick={handleOpenObservatory}>
                  <ArrowUpRight className="mr-1.5 h-3.5 w-3.5" />
                  Open Observatory
                </Button>
              </div>
            </div>

            <ScrollArea className="min-h-0 flex-1">
              <div className="space-y-4 p-5">
                <div className="grid gap-3 md:grid-cols-3">
                  <div className="rounded-md border border-border/60 bg-card/70 p-3">
                    <div className="text-xs text-muted-foreground">Progress</div>
                    <div className="mt-1 text-xl font-semibold text-foreground">{completedSteps}/{totalSteps || "?"}</div>
                    <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-muted">
                      <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${progressPct}%` }} />
                    </div>
                  </div>
                  <div className="rounded-md border border-border/60 bg-card/70 p-3">
                    <div className="text-xs text-muted-foreground">Duration</div>
                    <div className="mt-1 flex items-center gap-2 text-xl font-semibold text-foreground">
                      <Clock className="h-4 w-4 text-muted-foreground" />
                      {formatDuration(duration)}
                    </div>
                  </div>
                  <div className="rounded-md border border-border/60 bg-card/70 p-3">
                    <div className="text-xs text-muted-foreground">Run data</div>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      <DataPill available={selectedRun.trace_available} label="Trace" />
                      <DataPill available={selectedRun.archived_log_available} label="Logs" />
                      <DataPill available={selectedRun.journal_available} label="Journal" />
                    </div>
                  </div>
                </div>

                {selectedRun.input_text && (
                  <div className="rounded-md border border-border/60 bg-card/70 p-4">
                    <h3 className="text-sm font-semibold text-foreground">Run input</h3>
                    <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">
                      {selectedRun.input_text}
                    </p>
                  </div>
                )}

                <div className="rounded-md border border-border/60 bg-card/70 p-4">
                  <h3 className="text-sm font-semibold text-foreground">Deep trace</h3>
                  <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                    Use Observatory for replay, step timing, LLM and tool-call inspection, logs, and run-to-run comparison.
                  </p>
                  <Button type="button" variant="outline" size="sm" className="mt-3 h-8 rounded-md text-xs" onClick={handleOpenObservatory}>
                    <ArrowUpRight className="mr-1.5 h-3.5 w-3.5" />
                    Open Observatory
                  </Button>
                </div>
              </div>
            </ScrollArea>
          </div>
        ) : (
          <div className="flex min-h-[28rem] items-center justify-center p-8 text-center">
            <div>
              <Clock className="mx-auto h-8 w-8 text-muted-foreground/60" />
              <h3 className="mt-3 text-sm font-semibold text-foreground">No run selected</h3>
              <p className="mt-1 text-sm text-muted-foreground">
                Run this workflow once to capture execution history.
              </p>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
