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
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import { CopyButton } from "./CopyButton";

/* ------------------------------------------------------------------ */
/*  Types & constants                                                  */
/* ------------------------------------------------------------------ */

interface WorkflowLogPanelProps {
  workflow: WorkflowInfo;
  selectedRun?: WorkflowRunRecord | null;
}

type LogSource = "worker" | string;
type FilterMode = "all" | "activity" | "opencode" | "errors";

const MAX_LINES = 400;
const ACTIVITY_KEYWORDS = [
  "tool_call", "response.tool_call", "response.patch", "apply_patch",
  "artifact", "workspace", "approval", "verify", "review", "loop",
  "circuit_breaker", "plan", "file",
];
const OPEN_CODE_KEYWORDS = [
  "opencode", "context_overflow", "structured_output", "session",
  "compaction", "compact", "mcp", "tool_call", "approval", "retry",
  "auth", "verify", "review", "loop", "circuit_breaker", "artifact",
  "journal", "cancel", "iteration",
];
const ERROR_KEYWORDS = [
  "error", "failed", "exception", "traceback", "timeout",
  "denied", "rejected", "context_overflow",
];

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function explainLogError(errorMessage: string, source: LogSource, workflow: WorkflowInfo): string {
  const n = errorMessage.toLowerCase();
  if (source === "worker" && n.includes("404")) {
    if (["running", "queued", "waiting-approval"].includes(workflow.phase ?? "")) {
      return "No live worker pod is streamable right now. The job may still be starting or have exited.";
    }
    return "No live worker pod is available. Step results and workspace files may still exist.";
  }
  return errorMessage;
}

function normalizeLines(raw: string): string[] {
  return raw.split(/\r?\n/).map((l) => l.trimEnd()).filter(Boolean);
}

function matchesKeyword(line: string, keywords: string[]): boolean {
  const lower = line.toLowerCase();
  return keywords.some((k) => lower.includes(k));
}

function parseLine(line: string): { message: string; level: string | null } {
  try {
    const p = JSON.parse(line) as Record<string, unknown>;
    const message = typeof p.message === "string" ? p.message : typeof p.msg === "string" ? p.msg : line;
    const level = typeof p.level === "string" ? p.level : typeof p.levelname === "string" ? p.levelname : null;
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
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/** Highlight search matches in text */
function HighlightedText({ text, search }: { text: string; search: string }) {
  if (!search.trim()) return <>{text}</>;
  const escaped = search.trim().replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const parts = text.split(new RegExp(`(${escaped})`, "gi"));
  return (
    <>
      {parts.map((part, i) =>
        part.toLowerCase() === search.trim().toLowerCase() ? (
          <mark key={i} className="bg-yellow-400/40 dark:bg-yellow-500/30 text-inherit rounded-sm px-0.5">{part}</mark>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  );
}

function lineTone(message: string, level: string | null): string {
  const nl = (level ?? "").toLowerCase();
  if (nl.includes("error") || matchesKeyword(message, ERROR_KEYWORDS))
    return "border-red-500/30 bg-red-500/8 text-red-700 dark:text-red-300";
  if (nl.includes("warn"))
    return "border-amber-500/30 bg-amber-500/8 text-amber-700 dark:text-amber-300";
  if (matchesKeyword(message, ACTIVITY_KEYWORDS))
    return "border-emerald-500/30 bg-emerald-500/8 text-emerald-700 dark:text-emerald-300";
  if (matchesKeyword(message, OPEN_CODE_KEYWORDS))
    return "border-sky-500/30 bg-sky-500/8 text-sky-700 dark:text-sky-300";
  return "border-border/50 bg-muted/30 text-foreground/80";
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

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
    () => Array.from(new Set(workflow.steps.map((s) => s.agent_ref).filter(Boolean))),
    [workflow.steps],
  );
  const displayWorkflow = useMemo(
    () => (source === "worker" && traceWorkflow ? traceWorkflow : workflow),
    [source, traceWorkflow, workflow],
  );

  /* Reset on workflow change */
  useEffect(() => {
    setSource("worker");
    setLines([]);
    setError("");
    setStreamMeta({});
    setTraceSource("live-worker");
    setTraceWorkflow(null);
  }, [workflow.name, workflow.run_id]);

  /* Load & stream logs */
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
            if (!selectedRunIsCurrent || trace.source !== "live-worker") return;
            setStreaming(true);
            await streamWorkflowLogs({
              signal: controller.signal, token, namespace, workflowName: workflow.name, tail: 50,
              onLine: (l) => { if (active) setLines((c) => appendLines(c, [l])); },
              onStarted: (i) => { if (active) { setStreamMeta({ podName: i.pod_name, jobName: i.job_name }); setStreaming(true); } },
              onError: (e) => { if (active && !controller.signal.aborted) { setError(e.message); setStreaming(false); } },
              onStopped: () => { if (active) setStreaming(false); },
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
          if ((initial.source ?? "live-worker") !== "live-worker") return;
          setStreaming(true);
          await streamWorkflowLogs({
            signal: controller.signal, token, namespace, workflowName: workflow.name, tail: 50,
            onLine: (l) => { if (active) setLines((c) => appendLines(c, [l])); },
            onStarted: (i) => { if (active) { setStreamMeta({ podName: i.pod_name, jobName: i.job_name }); setStreaming(true); } },
            onError: (e) => { if (active && !controller.signal.aborted) { setError(e.message); setStreaming(false); } },
            onStopped: () => { if (active) setStreaming(false); },
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
            signal: controller.signal, token, namespace, agentName: source, tail: 50,
            onLine: (l) => { if (active) setLines((c) => appendLines(c, [l])); },
            onStarted: (i) => { if (active) { setStreamMeta({ podName: i.pod_name }); setStreaming(true); } },
            onError: (e) => { if (active && !controller.signal.aborted) { setError(e.message); setStreaming(false); } },
            onStopped: () => { if (active) setStreaming(false); },
          });
        }
      } catch (err) {
        if (active && !controller.signal.aborted) {
          setError(err instanceof Error ? err.message : String(err));
          setStreaming(false);
        }
      } finally {
        if (active) setLoading(false);
      }
    }

    void loadAndStream();
    return () => { active = false; controller.abort(); };
  }, [namespace, refreshKey, selectedRun?.run_id, source, token, workflow.name, workflow.run_id]);

  /* Filtering */
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
    activity: lines.filter((l) => matchesKeyword(l, ACTIVITY_KEYWORDS)).length,
    errors: lines.filter((l) => matchesKeyword(l, ERROR_KEYWORDS)).length,
  }), [lines]);

  /* Quick filter pills */
  const quickFilters = useMemo(() => {
    const dynamicSteps: string[] = [];
    for (const step of displayWorkflow.steps) {
      const state = displayWorkflow.step_states?.[step.name];
      if (!state) continue;
      if (state.status === "failed" || state.status === "running" || (state.toolCallCount ?? 0) > 0) {
        dynamicSteps.push(step.name);
      }
      if (dynamicSteps.length >= 3) break;
    }
    const vals = Array.from(new Set([displayWorkflow.current_step, ...dynamicSteps].filter((v): v is string => Boolean(v)))).slice(0, 3);
    return [
      ...vals.map((v) => ({ label: v, value: v })),
      { label: "tool_call", value: "tool_call" },
      { label: "artifact", value: "artifact" },
      { label: "approval", value: "approval" },
    ];
  }, [displayWorkflow.current_step, displayWorkflow.step_states, displayWorkflow.steps]);

  const friendlyError = error ? explainLogError(error, source, displayWorkflow) : "";
  const logUnavailable = source === "worker" && (traceSource === "unavailable" || error.includes("404"));

  const handleExportVisible = () => {
    const frag = source === "worker" && selectedRun?.run_id ? selectedRun.run_id : source === "worker" ? "worker" : source;
    downloadTextFile(filteredLines.join("\n"), `${workflow.name}-${frag}-trace.log`);
  };

  return (
    <div className="flex h-full flex-col gap-3">
      {/* Header row */}
      <div className="flex flex-wrap items-center gap-2">
        <TerminalSquare className="h-4 w-4 text-primary" />
        <span className="text-xs font-semibold text-foreground">Trace</span>
        {streaming && <Badge variant="outline" className="border-emerald-500/30 text-[10px] text-emerald-600 dark:text-emerald-300">Live</Badge>}
        {traceSource === "archived" && <Badge variant="outline" className="border-sky-500/30 text-[10px] text-sky-600 dark:text-sky-300">Archived</Badge>}
        <span className="text-[10px] text-muted-foreground">
          {filteredLines.length}/{lines.length} lines
          {searchText.trim() && <> &middot; <span className="text-primary font-medium">{filteredLines.length} matches</span></>}
          {lineStats.errors > 0 && <> &middot; <span className="text-red-600 dark:text-red-400">{lineStats.errors} errors</span></>}
        </span>
        {streamMeta.podName && <span className="text-[10px] text-muted-foreground font-mono">{streamMeta.podName}</span>}
        <div className="ml-auto flex items-center gap-1">
          <Button variant="ghost" size="icon" className="h-7 w-7" disabled={loading} title="Refresh" onClick={() => setRefreshKey((c) => c + 1)}>
            <RefreshCw className={cn("h-3 w-3", loading && "animate-spin")} />
          </Button>
          <Button variant="ghost" size="icon" className="h-7 w-7" disabled={filteredLines.length === 0} title="Export" onClick={handleExportVisible}>
            <Download className="h-3 w-3" />
          </Button>
          <CopyButton value={filteredLines.join("\n")} className="h-7 w-7 rounded-lg" />
        </div>
      </div>

      {/* Controls row: source, filter, search + quick filters */}
      <div className="flex flex-wrap items-end gap-2">
        <Select value={source} onValueChange={setSource}>
          <SelectTrigger className="h-8 w-36 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="worker">Worker</SelectItem>
            {agentOptions.map((a) => <SelectItem key={a} value={a}>Agent: {a}</SelectItem>)}
          </SelectContent>
        </Select>
        <Select value={filterMode} onValueChange={(v) => setFilterMode(v as FilterMode)}>
          <SelectTrigger className="h-8 w-32 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All logs</SelectItem>
            <SelectItem value="activity">Activity</SelectItem>
            <SelectItem value="opencode">OpenCode</SelectItem>
            <SelectItem value="errors">Errors</SelectItem>
          </SelectContent>
        </Select>
        <div className="relative flex-1 min-w-[10rem]">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground" />
          <Input value={searchText} onChange={(e) => setSearchText(e.target.value)} className="h-8 pl-7 text-xs" placeholder="Search logs..." />
        </div>
      </div>

      {/* Quick filter pills */}
      <div className="flex flex-wrap gap-1.5">
        {quickFilters.map((f) => {
          const active = searchText.trim().toLowerCase() === f.value.toLowerCase();
          return (
            <button
              key={f.value}
              type="button"
              onClick={() => setSearchText((c) => (c.trim().toLowerCase() === f.value.toLowerCase() ? "" : f.value))}
              className={cn(
                "rounded-full border px-2.5 py-1 text-[10px] transition-colors",
                active
                  ? "border-primary/35 bg-primary/10 text-foreground"
                  : "border-border/50 bg-background/60 text-muted-foreground hover:border-primary/20 hover:text-foreground",
              )}
            >
              {f.label}
            </button>
          );
        })}
      </div>

      {/* Error banner */}
      {error && (
        <div className={cn(
          "flex items-center gap-2 rounded-xl px-3 py-2 text-xs",
          logUnavailable ? "border border-amber-500/30 bg-amber-500/8 text-amber-700 dark:text-amber-300" : "border border-destructive/30 bg-destructive/8 text-destructive",
        )}>
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          <span>{friendlyError}</span>
        </div>
      )}

      {/* Log output — fills remaining height */}
      <div className="flex-1 min-h-0 rounded-xl border border-border/60 bg-card/50">
        <ScrollArea className="h-full">
          <div className="space-y-1.5 p-2.5 font-mono text-[11px] leading-relaxed">
            {loading && (
              <div className="flex items-center gap-2 py-4 text-muted-foreground">
                <LoaderCircle className="h-4 w-4 animate-spin" /> Loading logs...
              </div>
            )}
            {!loading && filteredLines.length === 0 && (
              <div className="py-4 text-center text-xs text-muted-foreground">
                {traceSource === "archived"
                  ? "No archived lines match the current filter."
                  : logUnavailable
                    ? "No live worker log stream is available for this run."
                    : "No log lines match the current filter."}
              </div>
            )}
            {filteredLines.map((line, i) => {
              const parsed = parseLine(line);
              return (
                <div key={`${i}-${line.slice(0, 32)}`} className={cn("rounded-lg border px-2.5 py-1.5", lineTone(parsed.message, parsed.level))}>
                  {parsed.level && (
                    <span className="mr-2 rounded-full border border-current/20 px-1.5 py-0.5 text-[9px] uppercase tracking-wide opacity-70">
                      {parsed.level}
                    </span>
                  )}
                  <span className="whitespace-pre-wrap break-words">
                    <HighlightedText text={parsed.message} search={searchText} />
                  </span>
                </div>
              );
            })}
          </div>
        </ScrollArea>
      </div>
    </div>
  );
}
