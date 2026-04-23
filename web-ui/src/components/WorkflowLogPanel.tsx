import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Download, LoaderCircle, RefreshCw, Search, TerminalSquare } from "lucide-react";

import { useConnection } from "@/contexts/ConnectionContext";
import {
  fetchAgentLogs,
  fetchWorkflowLogs,
  fetchWorkflowRunTrace,
  streamAgentLogs,
  streamWorkflowLogs,
  type WorkflowRunRecord,
} from "@/lib/api";
import type { WorkflowInfo } from "@/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import { CopyButton } from "./CopyButton";

interface WorkflowLogPanelProps {
  workflow: WorkflowInfo;
  selectedRun?: WorkflowRunRecord | null;
}

type LogSource = "worker" | string;
type FilterMode = "all" | "activity" | "opencode" | "errors";

const MAX_LINES = 400;
const ACTIVITY_KEYWORDS = [
  "tool_call",
  "response.tool_call",
  "response.patch",
  "apply_patch",
  "artifact",
  "workspace",
  "approval",
  "verify",
  "review",
  "loop",
  "circuit_breaker",
  "plan",
  "file",
];
const OPEN_CODE_KEYWORDS = [
  "opencode",
  "context_overflow",
  "structured_output",
  "session",
  "compaction",
  "compact",
  "mcp",
  "tool_call",
  "approval",
  "retry",
  "auth",
  "verify",
  "review",
  "loop",
  "circuit_breaker",
  "artifact",
  "journal",
  "cancel",
  "iteration",
];
const ERROR_KEYWORDS = [
  "error",
  "failed",
  "exception",
  "traceback",
  "timeout",
  "denied",
  "rejected",
  "context_overflow",
];

function explainLogError(errorMessage: string, source: LogSource, workflow: WorkflowInfo): string {
  const normalized = errorMessage.toLowerCase();
  if (source === "worker" && normalized.includes("404")) {
    if (workflow.phase === "running" || workflow.phase === "queued" || workflow.phase === "waiting-approval") {
      return "No live workflow worker pod is streamable right now. The job may still be starting, may already have exited, or the run may have rolled to a new worker pod.";
    }
    return "No live workflow worker pod is available for this run. Step results and workspace files can still exist even when logs are no longer streamable.";
  }
  return errorMessage;
}

function normalizeLines(raw: string): string[] {
  return raw
    .split(/\r?\n/)
    .map((line) => line.trimEnd())
    .filter(Boolean);
}

function matchesKeyword(line: string, keywords: string[]): boolean {
  const lower = line.toLowerCase();
  return keywords.some((keyword) => lower.includes(keyword));
}

function parseLine(line: string): { message: string; level: string | null } {
  try {
    const parsed = JSON.parse(line) as Record<string, unknown>;
    const message = typeof parsed.message === "string"
      ? parsed.message
      : typeof parsed.msg === "string"
        ? parsed.msg
        : line;
    const level = typeof parsed.level === "string"
      ? parsed.level
      : typeof parsed.levelname === "string"
        ? parsed.levelname
        : null;
    return { message, level };
  } catch {
    return { message: line, level: null };
  }
}

function appendLines(current: string[], incoming: string[]): string[] {
  if (incoming.length === 0) return current;
  const next = [...current, ...incoming];
  return next.length > MAX_LINES ? next.slice(next.length - MAX_LINES) : next;
}

function downloadTextFile(text: string, filename: string) {
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}

function lineTone(message: string, level: string | null): string {
  const normalizedLevel = (level ?? "").toLowerCase();
  if (normalizedLevel.includes("error") || matchesKeyword(message, ERROR_KEYWORDS)) {
    return "border-red-500/20 bg-red-500/5 text-red-200";
  }
  if (normalizedLevel.includes("warn")) {
    return "border-amber-500/20 bg-amber-500/5 text-amber-100";
  }
  if (matchesKeyword(message, ACTIVITY_KEYWORDS)) {
    return "border-emerald-500/20 bg-emerald-500/5 text-emerald-200";
  }
  if (matchesKeyword(message, OPEN_CODE_KEYWORDS)) {
    return "border-sky-500/20 bg-sky-500/5 text-sky-200";
  }
  return "border-border/50 bg-background/40 text-muted-foreground";
}

export function WorkflowLogPanel({ workflow, selectedRun = null }: WorkflowLogPanelProps) {
  const { token, namespace } = useConnection();
  const [source, setSource] = useState<LogSource>("worker");
  const [filterMode, setFilterMode] = useState<FilterMode>("activity");
  const [searchText, setSearchText] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const [lines, setLines] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string>("");
  const [streamMeta, setStreamMeta] = useState<{ podName?: string; jobName?: string }>({});
  const [traceSource, setTraceSource] = useState<string>("live-worker");
  const [traceWorkflow, setTraceWorkflow] = useState<WorkflowInfo | null>(null);
  const agentOptions = useMemo(
    () => Array.from(new Set(workflow.steps.map((step) => step.agent_ref).filter(Boolean))),
    [workflow.steps],
  );
  const displayWorkflow = useMemo(
    () => (source === "worker" && traceWorkflow ? traceWorkflow : workflow),
    [source, traceWorkflow, workflow],
  );

  useEffect(() => {
    setSource("worker");
    setLines([]);
    setError("");
    setStreamMeta({});
    setTraceSource("live-worker");
    setTraceWorkflow(null);
  }, [workflow.name, workflow.run_id]);

  useEffect(() => {
    if (!token || !namespace || !workflow.name) return undefined;

    const controller = new AbortController();
    let active = true;

    async function loadAndStream() {
      setLoading(true);
      setStreaming(false);
      setError("");
      setLines([]);
      setStreamMeta({});
      setTraceWorkflow(null);
      setTraceSource(source === "worker" ? "live-worker" : "live-agent");
      try {
        if (source === "worker") {
          if (selectedRun?.run_id) {
            const trace = await fetchWorkflowRunTrace(token, namespace, workflow.name, selectedRun.run_id, 4000);
            if (!active) return;
            setTraceWorkflow(trace.workflow);
            setTraceSource(trace.source);
            setLines(normalizeLines(trace.logs));
            setStreamMeta({ podName: trace.pod_name, jobName: trace.worker_job_name });
            if (!trace.logs && trace.source === "unavailable") {
              setError(trace.live_log_error || "No archived or live logs are available for this run.");
            }
            setLoading(false);

            const selectedRunIsCurrent = selectedRun.run_id === (workflow.run_id ?? null);
            if (!selectedRunIsCurrent || trace.source !== "live-worker") {
              return;
            }

            setStreaming(true);
            await streamWorkflowLogs({
              signal: controller.signal,
              token,
              namespace,
              workflowName: workflow.name,
              tail: 50,
              onLine: (line) => {
                if (!active) return;
                setLines((current) => appendLines(current, [line]));
              },
              onStarted: (info) => {
                if (!active) return;
                setStreamMeta({ podName: info.pod_name, jobName: info.job_name });
                setStreaming(true);
              },
              onError: (streamError) => {
                if (!active || controller.signal.aborted) return;
                setError(streamError.message);
                setStreaming(false);
              },
              onStopped: () => {
                if (!active) return;
                setStreaming(false);
              },
            });
            return;
          }

          const initial = await fetchWorkflowLogs(token, namespace, workflow.name, 200);
          if (!active) return;
          setTraceSource(initial.source ?? "live-worker");
          setLines(normalizeLines(initial.logs));
          setStreamMeta({ podName: initial.pod_name, jobName: initial.job_name });
          if (!initial.logs && (initial.source ?? "unavailable") === "unavailable") {
            setError("No archived or live logs are available for this run.");
          }
          setLoading(false);
          if ((initial.source ?? "live-worker") !== "live-worker") {
            return;
          }

          setStreaming(true);
          await streamWorkflowLogs({
            signal: controller.signal,
            token,
            namespace,
            workflowName: workflow.name,
            tail: 50,
            onLine: (line) => {
              if (!active) return;
              setLines((current) => appendLines(current, [line]));
            },
            onStarted: (info) => {
              if (!active) return;
              setStreamMeta({ podName: info.pod_name, jobName: info.job_name });
              setStreaming(true);
            },
            onError: (streamError) => {
              if (!active || controller.signal.aborted) return;
              setError(streamError.message);
              setStreaming(false);
            },
            onStopped: () => {
              if (!active) return;
              setStreaming(false);
            },
          });
        } else {
          const initial = await fetchAgentLogs(token, namespace, source, 200);
          if (!active) return;
          setTraceSource("live-agent");
          setLines(normalizeLines(initial.logs));
          setStreamMeta({ podName: initial.pod_name });
          setLoading(false);
          setStreaming(true);
          await streamAgentLogs({
            signal: controller.signal,
            token,
            namespace,
            agentName: source,
            tail: 50,
            onLine: (line) => {
              if (!active) return;
              setLines((current) => appendLines(current, [line]));
            },
            onStarted: (info) => {
              if (!active) return;
              setStreamMeta({ podName: info.pod_name });
              setStreaming(true);
            },
            onError: (streamError) => {
              if (!active || controller.signal.aborted) return;
              setError(streamError.message);
              setStreaming(false);
            },
            onStopped: () => {
              if (!active) return;
              setStreaming(false);
            },
          });
        }
      } catch (loadError) {
        if (!active || controller.signal.aborted) return;
        setError(loadError instanceof Error ? loadError.message : String(loadError));
        setStreaming(false);
      } finally {
        if (active) setLoading(false);
      }
    }

    void loadAndStream();
    return () => {
      active = false;
      controller.abort();
    };
  }, [namespace, refreshKey, selectedRun?.run_id, source, token, workflow.name, workflow.run_id]);

  const filteredLines = useMemo(() => {
    return lines.filter((line) => {
      if (filterMode === "activity" && !matchesKeyword(line, ACTIVITY_KEYWORDS)) return false;
      if (filterMode === "opencode" && !matchesKeyword(line, OPEN_CODE_KEYWORDS)) return false;
      if (filterMode === "errors" && !matchesKeyword(line, ERROR_KEYWORDS)) return false;
      if (searchText.trim() && !line.toLowerCase().includes(searchText.trim().toLowerCase())) return false;
      return true;
    });
  }, [filterMode, lines, searchText]);

  const lineStats = useMemo(() => ({
    activity: lines.filter((line) => matchesKeyword(line, ACTIVITY_KEYWORDS)).length,
    opencode: lines.filter((line) => matchesKeyword(line, OPEN_CODE_KEYWORDS)).length,
    errors: lines.filter((line) => matchesKeyword(line, ERROR_KEYWORDS)).length,
  }), [lines]);

  const focusLabel = displayWorkflow.current_step || (source === "worker" ? "Run-scoped worker trace" : `${source} runtime`);
  const quickFilters = useMemo(() => {
    const dynamicSteps: string[] = [];
    for (const step of displayWorkflow.steps) {
      const state = displayWorkflow.step_states?.[step.name];
      if (!state) continue;
      if (
        state.status === "failed" ||
        state.status === "running" ||
        (state.toolCallCount ?? 0) > 0 ||
        (state.artifactCount ?? 0) > 0 ||
        (state.warnings?.length ?? 0) > 0
      ) {
        dynamicSteps.push(step.name);
      }
      if (dynamicSteps.length >= 4) break;
    }

    const values = Array.from(new Set([displayWorkflow.current_step, ...dynamicSteps].filter((value): value is string => Boolean(value)))).slice(0, 4);
    return [
      ...values.map((value) => ({ label: value, value })),
      { label: "tool_call", value: "tool_call" },
      { label: "artifact", value: "artifact" },
      { label: "approval", value: "approval" },
      { label: "verify", value: "verify" },
    ];
  }, [displayWorkflow.current_step, displayWorkflow.step_states, displayWorkflow.steps]);

  const friendlyError = error ? explainLogError(error, source, displayWorkflow) : "";
  const logUnavailable = source === "worker" && (traceSource === "unavailable" || error.includes("404"));

  const title = source === "worker"
    ? selectedRun?.run_id
      ? selectedRun.run_id === workflow.run_id
        ? "selected run trace"
        : "historical run trace"
      : "worker orchestration"
    : `${source} runtime`;

  const visibleSignalSummary = useMemo(() => {
    const errorCount = filteredLines.filter((line) => matchesKeyword(line, ERROR_KEYWORDS)).length;
    const activityCount = filteredLines.filter((line) => matchesKeyword(line, ACTIVITY_KEYWORDS)).length;
    return `${errorCount} error${errorCount === 1 ? "" : "s"} · ${activityCount} activity signal${activityCount === 1 ? "" : "s"}`;
  }, [filteredLines]);

  const handleExportVisible = () => {
    const runFragment = source === "worker" && selectedRun?.run_id ? selectedRun.run_id : source === "worker" ? "worker" : source;
    downloadTextFile(
      filteredLines.join("\n"),
      `${workflow.name}-${runFragment}-trace.log`,
    );
  };

  return (
    <Card className="overflow-hidden border-border/70 bg-card/95 shadow-none">
      <CardHeader className="pb-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <TerminalSquare className="h-4 w-4 text-primary" />
              <CardTitle className="text-sm">Trace cockpit</CardTitle>
              <Badge variant="outline" className="text-[10px] capitalize">
                {title}
              </Badge>
              {source === "worker" && selectedRun?.run_id && (
                <Badge variant="outline" className="text-[10px] font-mono">
                  {selectedRun.run_id.slice(0, 18)}
                </Badge>
              )}
              {source === "worker" && traceSource === "archived" && (
                <Badge variant="outline" className="border-sky-500/30 text-[10px] text-sky-300">
                  Archived snapshot
                </Badge>
              )}
              {streaming && (
                <Badge variant="outline" className="border-emerald-500/30 text-[10px] text-emerald-300">
                  Live stream
                </Badge>
              )}
            </div>
            <p className="text-xs leading-relaxed text-muted-foreground">Search the runtime trail, pivot by step or keyword, and export the currently visible log evidence.</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-8 rounded-xl text-xs"
              disabled={loading}
              title="Reload logs"
              onClick={() => setRefreshKey((current) => current + 1)}
            >
              <RefreshCw className={cn("mr-1.5 h-3.5 w-3.5", loading && "animate-spin")} />
              Refresh
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-8 rounded-xl text-xs"
              disabled={filteredLines.length === 0}
              onClick={handleExportVisible}
            >
              <Download className="mr-1.5 h-3.5 w-3.5" />
              Export visible
            </Button>
            <CopyButton value={filteredLines.join("\n")} className="h-8 w-8 rounded-xl border border-border/60 bg-background/70" />
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-2xl border border-border/60 bg-background/65 px-4 py-3">
            <div className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">Stream posture</div>
            <div className="mt-1 text-sm font-semibold text-foreground">{streaming ? "Streaming" : loading ? "Loading" : "Snapshot"}</div>
            <div className="mt-1 text-xs text-muted-foreground">
              {source === "worker"
                ? traceSource === "archived"
                  ? "Archived worker trace from the selected run"
                  : "Workflow worker log source"
                : `Agent runtime: ${source}`}
            </div>
          </div>
          <div className="rounded-2xl border border-border/60 bg-background/65 px-4 py-3">
            <div className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">Current focus</div>
            <div className="mt-1 text-sm font-semibold text-foreground">{focusLabel}</div>
            <div className="mt-1 text-xs text-muted-foreground">Use quick filters below to pin the trace around the active step.</div>
          </div>
          <div className="rounded-2xl border border-border/60 bg-background/65 px-4 py-3">
            <div className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">Signal mix</div>
            <div className="mt-1 text-sm font-semibold text-foreground">{visibleSignalSummary}</div>
            <div className="mt-1 text-xs text-muted-foreground">Activity {lineStats.activity} · OpenCode {lineStats.opencode} · Errors {lineStats.errors}</div>
          </div>
          <div className="rounded-2xl border border-border/60 bg-background/65 px-4 py-3">
            <div className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">Buffer</div>
            <div className="mt-1 text-sm font-semibold text-foreground">{filteredLines.length} visible</div>
            <div className="mt-1 text-xs text-muted-foreground">{lines.length} total lines kept in the local buffer.</div>
          </div>
        </div>

        <div className="rounded-2xl border border-border/60 bg-background/60 p-3">
          <div className="flex flex-wrap gap-2">
            {quickFilters.map((filter) => {
              const active = searchText.trim().toLowerCase() === filter.value.toLowerCase();
              return (
                <button
                  key={`${filter.label}-${filter.value}`}
                  type="button"
                  onClick={() => setSearchText((current) => (current.trim().toLowerCase() === filter.value.toLowerCase() ? "" : filter.value))}
                  className={cn(
                    "rounded-full border px-3 py-1.5 text-[11px] transition-colors",
                    active
                      ? "border-primary/35 bg-primary/10 text-foreground"
                      : "border-border/60 bg-background/70 text-muted-foreground hover:border-primary/20 hover:text-foreground",
                  )}
                >
                  {filter.label}
                </button>
              );
            })}
          </div>
        </div>

        <div className="grid gap-3 md:grid-cols-[1fr_1fr_1.3fr]">
          <div className="space-y-1.5">
            <Label className="text-xs">Source</Label>
            <Select value={source} onValueChange={setSource}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="worker">Workflow worker</SelectItem>
                {agentOptions.map((agentName) => (
                  <SelectItem key={agentName} value={agentName}>
                    Agent: {agentName}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs">Filter</Label>
            <Select value={filterMode} onValueChange={(value) => setFilterMode(value as FilterMode)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All logs</SelectItem>
                <SelectItem value="activity">Activity only</SelectItem>
                <SelectItem value="opencode">OpenCode-focused</SelectItem>
                <SelectItem value="errors">Errors only</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs">Search</Label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={searchText}
                onChange={(event) => setSearchText(event.target.value)}
                className="pl-7"
                placeholder="timeout, tool_call, artifact, approval..."
              />
            </div>
          </div>
        </div>

        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
            {source === "worker" && selectedRun?.run_id && <span>Run: {selectedRun.run_id}</span>}
            {streamMeta.jobName && <span>Job: {streamMeta.jobName}</span>}
            {streamMeta.podName && <span>Pod: {streamMeta.podName}</span>}
            <span>Visible lines: {filteredLines.length}</span>
            <span>Total buffered: {lines.length}</span>
            <Badge variant="outline" className="text-[10px]">activity {lineStats.activity}</Badge>
            <Badge variant="outline" className="text-[10px]">opencode {lineStats.opencode}</Badge>
            <Badge variant="outline" className="text-[10px]">errors {lineStats.errors}</Badge>
          </div>
          <div className="flex items-center gap-2 self-end sm:self-auto">
            <span className="text-[11px] text-muted-foreground">
              {streaming ? "Live stream" : traceSource === "archived" ? "Archived snapshot" : "Snapshot"}
            </span>
          </div>
        </div>

        {error && (
          <div className={`flex items-center gap-2 rounded-xl px-3 py-2 text-xs ${logUnavailable ? "border border-amber-500/30 bg-amber-500/5 text-amber-300" : "border border-destructive/30 bg-destructive/5 text-destructive"}`}>
            <AlertTriangle className="h-4 w-4 shrink-0" />
            <span>{friendlyError}</span>
          </div>
        )}

        <div className="rounded-2xl border border-border/60 bg-background/70">
          <ScrollArea className="h-[30rem]">
            <div className="space-y-2 p-3 font-mono text-[11px] leading-relaxed">
              {loading && (
                <div className="flex items-center gap-2 text-muted-foreground">
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                  Loading logs...
                </div>
              )}
              {!loading && filteredLines.length === 0 && (
                <div className="text-muted-foreground">
                  {traceSource === "archived"
                    ? "No archived log lines match the current filter."
                    : logUnavailable
                      ? "No live workflow worker log stream is available for this run."
                      : "No log lines match the current filter."}
                </div>
              )}
              {filteredLines.map((line, index) => {
                const parsed = parseLine(line);
                return (
                  <div key={`${index}-${line.slice(0, 32)}`} className={cn("rounded-xl border px-3 py-2", lineTone(parsed.message, parsed.level))}>
                    <div className="flex flex-wrap items-center gap-2">
                      {parsed.level && (
                        <span className="rounded-full border border-current/20 px-1.5 py-0.5 text-[9px] uppercase tracking-[0.16em] opacity-75">
                          {parsed.level}
                        </span>
                      )}
                      <span className="text-[10px] opacity-70">#{index + 1}</span>
                    </div>
                    <div className="mt-1 whitespace-pre-wrap break-words">{line}</div>
                  </div>
                );
              })}
            </div>
          </ScrollArea>
        </div>
      </CardContent>
    </Card>
  );
}
