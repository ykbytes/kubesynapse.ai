import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import {
  Activity,
  AlertTriangle,
  BookOpen,
  Braces,
  BrainCircuit,
  Code2,
  FileCode,
  FileText,
  GitCompare,
  Globe,
  Layers,
  ListTree,
  LoaderCircle,
  Maximize2,
  Minimize2,
  Search,
  Sparkles,
  Terminal,
  WrapText,
  Wrench,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useConnection } from "@/contexts/ConnectionContext";
import { useWorkspace } from "@/contexts/WorkspaceContext";
import {
  fetchWorkflowRuns,
  exportExecutionHtml,
  exportExecutionJson,
  fetchExecutionDetail,
  fetchWorkflowRunTrace,
  listExecutions,
  type WorkflowRunRecord,
  type WorkflowRunTraceResponse,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import type { ExecutionListItem, ExecutionTrace, LLMCallRecord, StepTrace } from "@/types";

import { CopyButton } from "../shared/CopyButton";
import { ExecutionBanner } from "../observatory/ExecutionBanner";
import { ExecutionDiffView } from "../observatory/ExecutionDiffView";
import { ExecutionTimeline } from "../observatory/ExecutionTimeline";
import { LLMCallViewer } from "../observatory/LLMCallViewer";
import { ObservatoryOverview } from "../observatory/ObservatoryOverview";
import { RunsRail } from "../observatory/RunsRail";
import { LiveActivityStream, useWorkflowActivities } from "./LiveActivityStream";

// ─── Constants ────────────────────────────────────────────────────────────────

type LogFilterMode = "all" | "activity" | "errors" | "tooling";
type ObservatoryTab = "overview" | "steps" | "logs" | "models" | "compare";

const LOG_ACTIVITY_KEYWORDS = [
  "tool_call", "response.tool_call", "apply_patch", "artifact", "workspace",
  "approval", "verify", "review", "loop", "plan", "step", "execution",
];
const LOG_ERROR_KEYWORDS = ["error", "failed", "exception", "traceback", "timeout", "denied", "rejected"];
const LOG_TOOLING_KEYWORDS = ["opencode", "mcp", "tool_call", "context_overflow", "session", "compaction", "retry"];

// ─── Helpers ──────────────────────────────────────────────────────────────────

function statusBadgeClasses(status: string | null | undefined): string {
  const s = status?.toLowerCase() ?? "unknown";
  if (s === "completed" || s === "succeeded") return "border-emerald-500/20 bg-emerald-500/10 text-emerald-400";
  if (s === "failed" || s === "error") return "border-destructive/20 bg-destructive/10 text-destructive";
  if (s === "running" || s === "in_progress") return "border-amber-500/20 bg-amber-500/10 text-amber-400";
  if (s.includes("cancel")) return "border-amber-500/20 bg-amber-500/10 text-amber-400";
  return "border-border/60 bg-background/60 text-muted-foreground";
}

function formatDuration(ms?: number | null): string {
  if (ms == null || !Number.isFinite(ms)) return "--";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const minutes = Math.floor(seconds / 60);
  const rem = Math.round(seconds % 60);
  return `${minutes}m ${rem}s`;
}

function formatCompactDate(value?: string | null): string {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function formatCurrency(value?: number | null): string {
  if (value == null || !Number.isFinite(value)) return "--";
  return `$${value.toFixed(4)}`;
}

function normalizeLines(raw: string): string[] {
  return raw.split(/\r?\n/).map((line) => line.trimEnd()).filter(Boolean);
}

function matchesKeyword(line: string, keywords: string[]): boolean {
  const lower = line.toLowerCase();
  return keywords.some((keyword) => lower.includes(keyword));
}

function parseLogLine(line: string): { message: string; level: string | null } {
  try {
    const parsed = JSON.parse(line) as Record<string, unknown>;
    const message = typeof parsed.message === "string" ? parsed.message : typeof parsed.msg === "string" ? parsed.msg : line;
    const level = typeof parsed.level === "string" ? parsed.level : typeof parsed.levelname === "string" ? parsed.levelname : null;
    return { message, level };
  } catch {
    return { message: line, level: null };
  }
}

function lineTone(message: string, level: string | null): string {
  const normalizedLevel = (level ?? "").toLowerCase();
  if (normalizedLevel.includes("error") || matchesKeyword(message, LOG_ERROR_KEYWORDS)) {
    return "border-l-red-500 bg-red-500/5";
  }
  if (normalizedLevel.includes("warn")) {
    return "border-l-amber-500 bg-amber-500/5";
  }
  if (matchesKeyword(message, LOG_ACTIVITY_KEYWORDS)) {
    return "border-l-emerald-500 bg-emerald-500/5";
  }
  if (matchesKeyword(message, LOG_TOOLING_KEYWORDS)) {
    return "border-l-sky-500 bg-sky-500/5";
  }
  return "border-l-transparent bg-transparent";
}

function getStepLabel(step: StepTrace): string {
  return step.step_index != null ? `#${step.step_index + 1} ${step.name}` : step.name;
}

function getToolIcon(toolName: string): React.ComponentType<{ className?: string }> {
  const name = toolName.toLowerCase();
  if (name.includes("search") || name.includes("docs")) return BookOpen;
  if (name.includes("webfetch") || name.includes("web") || name.includes("http") || name.includes("fetch")) return Globe;
  if (name.includes("apply_patch") || name.includes("edit") || name.includes("write")) return FileCode;
  if (name.includes("bash") || name.includes("shell") || name.includes("exec") || name.includes("command")) return Terminal;
  if (name.includes("read") || name.includes("file") || name.includes("glob") || name.includes("grep")) return FileText;
  if (name.includes("skill")) return Sparkles;
  if (name.includes("code") || name.includes("python") || name.includes("node")) return Code2;
  return Wrench;
}

function getToolIconColor(toolName: string): string {
  const name = toolName.toLowerCase();
  if (name.includes("search") || name.includes("docs")) return "text-violet-400";
  if (name.includes("webfetch") || name.includes("web") || name.includes("http") || name.includes("fetch")) return "text-sky-400";
  if (name.includes("apply_patch") || name.includes("edit") || name.includes("write")) return "text-amber-400";
  if (name.includes("bash") || name.includes("shell") || name.includes("exec") || name.includes("command")) return "text-emerald-400";
  if (name.includes("read") || name.includes("file") || name.includes("glob") || name.includes("grep")) return "text-cyan-400";
  if (name.includes("skill")) return "text-pink-400";
  if (name.includes("code") || name.includes("python") || name.includes("node")) return "text-orange-400";
  return "text-muted-foreground";
}

function isDirectInvokeExecution(execution: Pick<ExecutionListItem, "workflow_name" | "triggered_by"> | Pick<ExecutionTrace, "workflow_name" | "triggered_by">): boolean {
  return execution.triggered_by === "direct-invoke" || execution.workflow_name.startsWith("invoke-") || execution.workflow_name.startsWith("invoke:");
}

function canLoadWorkflowRunTrace(detail: ExecutionTrace | null): boolean {
  if (!detail?.run_id) return false;
  if (!detail.workflow_name.trim()) return false;
  return detail.triggered_by !== "direct-invoke" && !detail.workflow_name.startsWith("invoke-") && !detail.workflow_name.startsWith("invoke:");
}

function tryFormatJson(line: string): { isJson: boolean; formatted: string } {
  // Try to detect JSON in the log line (after timestamp/level prefix)
  const jsonStart = line.indexOf("{");
  if (jsonStart === -1) return { isJson: false, formatted: line };
  const candidate = line.slice(jsonStart);
  try {
    const parsed = JSON.parse(candidate);
    const prefix = line.slice(0, jsonStart);
    return { isJson: true, formatted: prefix + JSON.stringify(parsed, null, 2) };
  } catch {
    return { isJson: false, formatted: line };
  }
}

function deriveRunLogSource(runTrace: WorkflowRunTraceResponse | null): string {
  if (!runTrace) return "unavailable";
  if (runTrace.source === "archived") return "archived";
  if (runTrace.source === "live-worker") return "live-worker";
  return runTrace.source;
}

function buildRunTraceNotice(runTrace: WorkflowRunTraceResponse | null): string | null {
  if (!runTrace) return null;
  if (runTrace.live_log_error && runTrace.archived_log_available) {
    return `Live worker logs were unavailable; showing archived logs instead. ${runTrace.live_log_error}`;
  }
  if (runTrace.live_log_error) return runTrace.live_log_error;
  if (runTrace.archived_log_truncated) return "Archived logs were truncated.";
  return null;
}

// ─── Main Component ───────────────────────────────────────────────────────────

interface ExecutionObservatoryProps {
  selectedExecutionId?: string | null;
  sidebarMode?: boolean;
}

export function ExecutionObservatory({ selectedExecutionId: externalSelectedId, sidebarMode }: ExecutionObservatoryProps) {
  const { token, namespace } = useConnection();
  const { observatoryFocus, clearObservatoryFocus, navigateToResource, selectedWorkflowName } = useWorkspace();
  const executionListRequestIdRef = useRef(0);
  const isSidebarMode = sidebarMode === true;

  // ── State ──────────────────────────────────────────────────────────────────
  const [executions, setExecutions] = useState<ExecutionListItem[]>([]);
  const [runLoading, setRunLoading] = useState(false);
  const [runs, setRuns] = useState<WorkflowRunRecord[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedExecutionId, setSelectedExecutionId] = useState<string | null>(externalSelectedId ?? null);
  const [detail, setDetail] = useState<ExecutionTrace | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<ObservatoryTab>("overview");
  const [selectedLLM, setSelectedLLM] = useState<LLMCallRecord | null>(null);
  const [llmViewerOpen, setLlmViewerOpen] = useState(false);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [selectedLogStep, setSelectedLogStep] = useState<string>("all");
  const [logSearch, setLogSearch] = useState("");
  const [logFilterMode, setLogFilterMode] = useState<LogFilterMode>("activity");
  const [runTraceLoading, setRunTraceLoading] = useState(false);
  const [runTrace, setRunTrace] = useState<WorkflowRunTraceResponse | null>(null);
  const [runTraceError, setRunTraceError] = useState("");
  const [compareLeftId, setCompareLeftId] = useState<string | null>(null);
  const [compareRightId, setCompareRightId] = useState<string | null>(null);
  const [compareLeft, setCompareLeft] = useState<ExecutionTrace | null>(null);
  const [compareRight, setCompareRight] = useState<ExecutionTrace | null>(null);
  const [compareLoading, setCompareLoading] = useState(false);
  // Steps tab: inline detail
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);
  // Models tab: tool search/grouping
  const [toolSearch, setToolSearch] = useState("");
  const [toolGroupBy, setToolGroupBy] = useState<"individual" | "tool">("tool");
  // Logs tab: JSON formatting, fullscreen, wrap, live stream
  const [logJsonFormat, setLogJsonFormat] = useState(false);
  const [logFullscreen, setLogFullscreen] = useState(false);
  const [logWrap, setLogWrap] = useState(true);
  const [logLiveMode, setLogLiveMode] = useState(false);

  // ── Live Activity Stream ──────────────────────────────────────────────────
  const isExecutionActive = detail ? ["running", "queued", "pending", "in_progress"].includes(detail.status.toLowerCase()) : false;
  const liveStreamWorkflow = isExecutionActive ? selectedWorkflowName : null;
  const liveActivities = useWorkflowActivities(token, namespace, liveStreamWorkflow ?? null);

  // Auto-enable live mode when execution is active
  useEffect(() => {
    if (isExecutionActive && activeTab === "logs") setLogLiveMode(true);
    if (!isExecutionActive) setLogLiveMode(false);
  }, [isExecutionActive, activeTab]);

  // ── Data Loading ───────────────────────────────────────────────────────────

  const loadExecutions = useCallback(async () => {
    if (!selectedWorkflowName) { setExecutions([]); return; }
    const requestId = ++executionListRequestIdRef.current;
    try {
      const result = await listExecutions(token, namespace, { limit: 200, workflow: selectedWorkflowName, execution_kind: "workflow" });
      if (requestId !== executionListRequestIdRef.current) return;
      setExecutions(result.items.filter((item) => !isDirectInvokeExecution(item)));
    } catch (error) {
      if (requestId !== executionListRequestIdRef.current) return;
      toast.error(error instanceof Error ? error.message : "Failed to load executions");
    }
  }, [namespace, selectedWorkflowName, token]);

  const loadRuns = useCallback(async () => {
    if (!selectedWorkflowName) { setRuns([]); return; }
    setRunLoading(true);
    try {
      const result = await fetchWorkflowRuns(token, namespace, selectedWorkflowName, 50);
      setRuns(result);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to load workflow runs");
      setRuns([]);
    } finally { setRunLoading(false); }
  }, [namespace, selectedWorkflowName, token]);

  // Reset on workflow change
  useEffect(() => {
    if (!selectedWorkflowName) {
      setRuns([]); setExecutions([]); setSelectedRunId(null);
      setSelectedExecutionId(null); setDetail(null); setRunTrace(null); setRunTraceError("");
      return;
    }
    setSelectedRunId(null); setSelectedExecutionId(null); setDetail(null);
    setRunTrace(null); setRunTraceError(""); setActiveTab("overview");
    void loadRuns(); void loadExecutions();
  }, [loadExecutions, loadRuns, selectedWorkflowName]);

  // Observatory focus navigation
  useEffect(() => {
    if (!observatoryFocus) return;
    if (observatoryFocus.workflowName !== selectedWorkflowName) {
      navigateToResource("intelligence", observatoryFocus.workflowName);
      return;
    }
    if (observatoryFocus.runId) setSelectedRunId(observatoryFocus.runId);
    setActiveTab("overview");
    clearObservatoryFocus();
  }, [clearObservatoryFocus, navigateToResource, observatoryFocus, selectedWorkflowName]);

  // Auto-select first run
  useEffect(() => {
    if (!selectedWorkflowName || runs.length === 0) { setSelectedRunId(null); return; }
    setSelectedRunId((current) => (current && runs.some((r) => r.run_id === current) ? current : (runs[0].run_id ?? null)));
  }, [runs, selectedWorkflowName]);

  const selectedRun = useMemo(
    () => runs.find((r) => r.run_id === selectedRunId) ?? runs[0] ?? null,
    [runs, selectedRunId],
  );

  // Load workflow run trace (logs)
  useEffect(() => {
    if (!selectedRun?.run_id || !selectedWorkflowName) {
      setRunTrace(null); setRunTraceError(""); setRunTraceLoading(false); return;
    }
    let cancelled = false;
    setRunTraceLoading(true); setRunTraceError("");
    fetchWorkflowRunTrace(token, namespace, selectedWorkflowName, selectedRun.run_id, 4000)
      .then((result) => { if (!cancelled) setRunTrace(result); })
      .catch((error) => { if (!cancelled) { setRunTrace(null); setRunTraceError(error instanceof Error ? error.message : "Failed to load logs"); } })
      .finally(() => { if (!cancelled) setRunTraceLoading(false); });
    return () => { cancelled = true; };
  }, [namespace, selectedRun?.run_id, selectedWorkflowName, token]);

  // Match execution to run
  useEffect(() => {
    const match = selectedRun?.run_id
      ? executions.find((e) => e.run_id === selectedRun.run_id && e.workflow_name === selectedWorkflowName)
      : null;
    setSelectedExecutionId(match?.id ?? null);
  }, [executions, selectedRun?.run_id, selectedWorkflowName]);

  // Load execution detail
  useEffect(() => {
    if (!selectedExecutionId) { setDetail(null); return; }
    let cancelled = false;
    setDetailLoading(true);
    fetchExecutionDetail(token, selectedExecutionId)
      .then((result) => { if (!cancelled) setDetail(result); })
      .catch((error) => { if (!cancelled) toast.error(error instanceof Error ? error.message : "Failed to load detail"); })
      .finally(() => { if (!cancelled) setDetailLoading(false); });
    return () => { cancelled = true; };
  }, [selectedExecutionId, token]);

  // Auto-refresh for running executions
  useEffect(() => {
    const isActive = detail ? ["running", "queued", "pending", "in_progress"].includes(detail.status.toLowerCase()) : false;
    if (!isActive) return;
    const timer = window.setInterval(() => {
      void loadRuns(); void loadExecutions();
      if (selectedExecutionId) {
        fetchExecutionDetail(token, selectedExecutionId).then(setDetail).catch(() => {});
      }
    }, 3000);
    return () => { window.clearInterval(timer); };
  }, [detail, loadExecutions, loadRuns, selectedExecutionId, token]);

  // Load compare executions
  useEffect(() => {
    if (!compareLeftId && !compareRightId) return;
    let cancelled = false;
    setCompareLoading(true);
    Promise.all([
      compareLeftId ? fetchExecutionDetail(token, compareLeftId).catch(() => null) : Promise.resolve(null),
      compareRightId ? fetchExecutionDetail(token, compareRightId).catch(() => null) : Promise.resolve(null),
    ]).then(([left, right]) => { if (!cancelled) { setCompareLeft(left); setCompareRight(right); } })
      .finally(() => { if (!cancelled) setCompareLoading(false); });
    return () => { cancelled = true; };
  }, [compareLeftId, compareRightId, token]);

  // Reset filters on run change
  useEffect(() => {
    setSelectedEventId(null); setSelectedLogStep("all");
    setLogSearch(""); setLogFilterMode("activity");
    setSelectedStepId(null); setToolSearch("");
  }, [detail?.id, runTrace?.run_id]);

  // ── Computed Values ────────────────────────────────────────────────────────

  const supportsWorkflowRunLogs = useMemo(() => canLoadWorkflowRunTrace(detail), [detail]);
  const orderedEvents = useMemo(
    () => detail ? [...detail.events].sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()) : [],
    [detail],
  );
  const orderedSteps = useMemo(
    () => detail ? [...detail.steps].sort((a, b) => (a.step_index ?? 999) - (b.step_index ?? 999)) : [],
    [detail],
  );
  const normalizedLogLines = useMemo(() => normalizeLines(runTrace?.logs ?? ""), [runTrace?.logs]);
  const filteredLogLines = useMemo(() => {
    return normalizedLogLines.filter((line) => {
      if (selectedLogStep !== "all" && !line.toLowerCase().includes(selectedLogStep.toLowerCase())) return false;
      if (logFilterMode === "activity" && !matchesKeyword(line, LOG_ACTIVITY_KEYWORDS)) return false;
      if (logFilterMode === "errors" && !matchesKeyword(line, LOG_ERROR_KEYWORDS)) return false;
      if (logFilterMode === "tooling" && !matchesKeyword(line, LOG_TOOLING_KEYWORDS)) return false;
      if (logSearch.trim() && !line.toLowerCase().includes(logSearch.trim().toLowerCase())) return false;
      return true;
    });
  }, [logFilterMode, logSearch, normalizedLogLines, selectedLogStep]);
  const logStats = useMemo(() => ({
    errors: normalizedLogLines.filter((l) => matchesKeyword(l, LOG_ERROR_KEYWORDS)).length,
    activity: normalizedLogLines.filter((l) => matchesKeyword(l, LOG_ACTIVITY_KEYWORDS)).length,
    tooling: normalizedLogLines.filter((l) => matchesKeyword(l, LOG_TOOLING_KEYWORDS)).length,
  }), [normalizedLogLines]);
  const runTraceNotice = useMemo(() => buildRunTraceNotice(runTrace), [runTrace]);
  // Steps tab: selected step detail
  const activeStepDetail = useMemo(
    () => orderedSteps.find((s) => s.id === selectedStepId) ?? null,
    [orderedSteps, selectedStepId],
  );

  // Models tab: grouped tool calls
  const toolCallGroups = useMemo(() => {
    if (!detail) return [];
    const groups = new Map<string, { name: string; count: number; totalMs: number; failures: number; calls: typeof detail.tool_calls }>();
    const filtered = toolSearch.trim()
      ? detail.tool_calls.filter((tc) => tc.tool_name.toLowerCase().includes(toolSearch.trim().toLowerCase()))
      : detail.tool_calls;
    for (const call of filtered) {
      const existing = groups.get(call.tool_name);
      if (existing) {
        existing.count++;
        existing.totalMs += call.latency_ms;
        if (call.status.toLowerCase() === "failed" || call.status.toLowerCase() === "error") existing.failures++;
        existing.calls.push(call);
      } else {
        groups.set(call.tool_name, {
          name: call.tool_name,
          count: 1,
          totalMs: call.latency_ms,
          failures: call.status.toLowerCase() === "failed" || call.status.toLowerCase() === "error" ? 1 : 0,
          calls: [call],
        });
      }
    }
    return Array.from(groups.values()).sort((a, b) => b.count - a.count);
  }, [detail, toolSearch]);

  // ── Handlers ───────────────────────────────────────────────────────────────

  const handleRefresh = () => {
    void loadRuns(); void loadExecutions();
    if (selectedExecutionId) {
      setDetailLoading(true);
      fetchExecutionDetail(token, selectedExecutionId)
        .then(setDetail)
        .catch((error) => toast.error(error instanceof Error ? error.message : "Refresh failed"))
        .finally(() => setDetailLoading(false));
    }
  };

  const handleExportJson = async (executionId: string) => {
    try {
      const text = await exportExecutionJson(token, executionId);
      const blob = new Blob([text], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url; anchor.download = `execution-${executionId}.json`; anchor.click();
      URL.revokeObjectURL(url);
      toast.success("JSON exported");
    } catch (error) { toast.error(error instanceof Error ? error.message : "Export failed"); }
  };

  const handleExportHtml = async (executionId: string) => {
    try {
      const text = await exportExecutionHtml(token, executionId);
      const blob = new Blob([text], { type: "text/html" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url; anchor.download = `execution-${executionId}.html`; anchor.click();
      URL.revokeObjectURL(url);
      toast.success("HTML report exported");
    } catch (error) { toast.error(error instanceof Error ? error.message : "Export failed"); }
  };

  // ── Render ─────────────────────────────────────────────────────────────────

  // Empty state: no workflow selected
  if (!selectedWorkflowName) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="flex flex-col items-center gap-3 text-center">
          <Activity className="h-10 w-10 text-muted-foreground/30" />
          <div>
            <p className="text-sm font-medium text-foreground">Select a workflow</p>
            <p className="mt-1 text-xs text-muted-foreground">The shared sidebar drives workflow selection in Intelligence.</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-border/40 bg-background">
      {/* ── Top: Execution Banner (sticky) ── */}
      {(detail || selectedRun) && (
        <ExecutionBanner
          detail={detail}
          run={selectedRun}
          workflowName={selectedWorkflowName}
          namespace={namespace}
          onNavigateToWorkflow={() => navigateToResource("workflows", selectedWorkflowName)}
          onExportJson={detail ? () => void handleExportJson(detail.id) : undefined}
          onExportHtml={detail ? () => void handleExportHtml(detail.id) : undefined}
          onRefresh={handleRefresh}
        />
      )}

      {/* ── Main body: Rail + Content ── */}
      <div className="flex min-h-0 flex-1 overflow-hidden">
        {/* Runs Rail */}
        {!isSidebarMode && (
          <RunsRail
            runs={runs}
            selectedRunId={selectedRunId}
            onSelectRun={(id) => { setSelectedRunId(id); setActiveTab("overview"); }}
            loading={runLoading}
            workflowName={selectedWorkflowName}
          />
        )}

        {/* Content area */}
        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          {/* Loading state */}
          {detailLoading && !detail && (
            <div className="flex flex-1 items-center justify-center">
              <div className="flex flex-col items-center gap-2">
                <LoaderCircle className="h-6 w-6 animate-spin text-primary" />
                <span className="text-xs text-muted-foreground">Loading execution...</span>
              </div>
            </div>
          )}

          {/* No run selected / no detail state */}
          {!detailLoading && !detail && !selectedRun && (
            <div className="flex flex-1 items-center justify-center">
              <div className="flex flex-col items-center gap-3 text-center">
                <Activity className="h-8 w-8 text-muted-foreground/30" />
                <p className="text-sm text-muted-foreground">Select a workflow run from the rail.</p>
              </div>
            </div>
          )}

          {/* Main tabbed content */}
          {(detail || selectedRun) && (
            <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as ObservatoryTab)} className="flex min-h-0 flex-1 flex-col overflow-hidden">
              <div className="shrink-0 border-b border-border/40 px-3">
                <TabsList className="h-9 gap-0 rounded-none border-0 bg-transparent p-0">
                  <TabsTrigger value="overview" className="relative h-9 rounded-none border-b-2 border-transparent px-3 text-xs font-medium transition-colors data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none">
                    <Layers className="mr-1.5 h-3.5 w-3.5" />
                    Overview
                  </TabsTrigger>
                  <TabsTrigger value="steps" className="relative h-9 rounded-none border-b-2 border-transparent px-3 text-xs font-medium transition-colors data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none">
                    <ListTree className="mr-1.5 h-3.5 w-3.5" />
                    Steps
                    {detail && <Badge variant="secondary" className="ml-1.5 h-4 px-1 text-[9px]">{detail.step_count}</Badge>}
                  </TabsTrigger>
                  <TabsTrigger value="logs" className="relative h-9 rounded-none border-b-2 border-transparent px-3 text-xs font-medium transition-colors data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none">
                    <FileText className="mr-1.5 h-3.5 w-3.5" />
                    Logs
                    {logStats.errors > 0 && <Badge variant="destructive" className="ml-1.5 h-4 px-1 text-[9px]">{logStats.errors}</Badge>}
                  </TabsTrigger>
                  <TabsTrigger value="models" className="relative h-9 rounded-none border-b-2 border-transparent px-3 text-xs font-medium transition-colors data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none">
                    <BrainCircuit className="mr-1.5 h-3.5 w-3.5" />
                    Models & Tools
                  </TabsTrigger>
                  <TabsTrigger value="compare" className="relative h-9 rounded-none border-b-2 border-transparent px-3 text-xs font-medium transition-colors data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none">
                    <GitCompare className="mr-1.5 h-3.5 w-3.5" />
                    Compare
                  </TabsTrigger>
                </TabsList>
              </div>

              {/* ═══════ OVERVIEW TAB ═══════ */}
              <TabsContent value="overview" className="mt-0 min-h-0 flex-1 overflow-y-auto">
                <ObservatoryOverview
                  detail={detail}
                  run={selectedRun}
                  previousRuns={runs}
                  onStepClick={(step) => { setSelectedStepId(step.id); setActiveTab("steps"); }}
                  onJumpToErrors={() => { setLogFilterMode("errors"); setActiveTab("logs"); }}
                  onViewLogs={() => setActiveTab("logs")}
                />
              </TabsContent>

              {/* ═══════ STEPS TAB ═══════ */}
              <TabsContent value="steps" className="mt-0 min-h-0 flex-1 overflow-hidden">
                {!detail ? (
                  <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                    Step-level observability appears once indexed execution detail is available.
                  </div>
                ) : (
                  <div className="flex h-full min-h-0">
                    {/* Step list (left) */}
                    <div className="w-64 shrink-0 border-r border-border/40 overflow-hidden flex flex-col">
                      <div className="shrink-0 px-3 py-2 border-b border-border/30">
                        <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                          {orderedSteps.length} Steps
                        </span>
                      </div>
                      <ScrollArea className="flex-1 min-h-0">
                        <div className="space-y-0.5 p-1.5">
                          {orderedSteps.map((step) => {
                            const isActive = step.id === selectedStepId;
                            const isFailed = step.status.toLowerCase() === "failed" || step.status.toLowerCase() === "error";
                            return (
                              <button
                                key={step.id}
                                type="button"
                                onClick={() => setSelectedStepId(step.id)}
                                className={cn(
                                  "w-full rounded-md border-l-[3px] px-2.5 py-2 text-left transition-all",
                                  isActive
                                    ? "border-l-primary bg-primary/8"
                                    : isFailed
                                      ? "border-l-red-500 hover:bg-red-500/5"
                                      : "border-l-transparent hover:bg-accent/30",
                                )}
                              >
                                <div className="flex items-center gap-1.5">
                                  <span className={cn(
                                    "h-1.5 w-1.5 shrink-0 rounded-full",
                                    step.status.toLowerCase() === "completed" || step.status.toLowerCase() === "succeeded"
                                      ? "bg-emerald-500"
                                      : isFailed ? "bg-red-500" : "bg-amber-500",
                                  )} />
                                  <span className="truncate text-xs font-medium text-foreground">{getStepLabel(step)}</span>
                                </div>
                                <div className="mt-1 flex items-center gap-2 pl-3 text-[10px] text-muted-foreground">
                                  <span>{formatDuration(step.latency_ms)}</span>
                                  <span>{step.llm_call_count ?? step.llm_calls.length} LLM</span>
                                  <span>{step.tool_call_count ?? step.tool_calls.length} tools</span>
                                </div>
                              </button>
                            );
                          })}
                        </div>
                      </ScrollArea>
                    </div>

                    {/* Step detail (right) */}
                    <div className="flex-1 min-w-0 overflow-y-auto">
                      {!activeStepDetail ? (
                        <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
                          Select a step from the list to see its detail.
                        </div>
                      ) : (
                        <div className="space-y-4 p-4">
                          {/* Step header */}
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <h4 className="text-sm font-semibold text-foreground">{getStepLabel(activeStepDetail)}</h4>
                              <div className="mt-1 flex items-center gap-3 text-xs text-muted-foreground">
                                <Badge variant="outline" className={cn("text-[10px]", statusBadgeClasses(activeStepDetail.status))}>
                                  {activeStepDetail.status}
                                </Badge>
                                <span>{formatDuration(activeStepDetail.latency_ms)}</span>
                                {activeStepDetail.step_type && <span>{activeStepDetail.step_type}</span>}
                                {activeStepDetail.tokens_used != null && <span>{activeStepDetail.tokens_used} tokens</span>}
                                {activeStepDetail.cost_usd != null && <span>{formatCurrency(activeStepDetail.cost_usd)}</span>}
                              </div>
                            </div>
                          </div>

                          {/* Error */}
                          {activeStepDetail.error && (
                            <div className="rounded-md border border-red-500/20 bg-red-500/5 p-3">
                              <div className="mb-1 flex items-center gap-1.5 text-[10px] font-semibold uppercase text-red-500">
                                <AlertTriangle className="h-3 w-3" /> Error
                              </div>
                              <pre className="whitespace-pre-wrap break-words text-xs text-red-400">{activeStepDetail.error}</pre>
                            </div>
                          )}

                          {/* Input/Output */}
                          {activeStepDetail.input_preview && (
                            <div>
                              <div className="mb-1.5 flex items-center justify-between">
                                <h5 className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Input</h5>
                                <CopyButton value={activeStepDetail.input_preview} className="h-5 w-5" />
                              </div>
                              <pre className="max-h-32 overflow-auto rounded-md border border-border/40 bg-slate-950 p-2.5 text-[11px] leading-relaxed text-slate-100">
                                {activeStepDetail.input_preview}
                              </pre>
                            </div>
                          )}
                          {activeStepDetail.output_preview && (
                            <div>
                              <div className="mb-1.5 flex items-center justify-between">
                                <h5 className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Output</h5>
                                <CopyButton value={activeStepDetail.output_preview} className="h-5 w-5" />
                              </div>
                              <pre className="max-h-32 overflow-auto rounded-md border border-border/40 bg-slate-950 p-2.5 text-[11px] leading-relaxed text-slate-100">
                                {activeStepDetail.output_preview}
                              </pre>
                            </div>
                          )}

                          {/* LLM Calls */}
                          {activeStepDetail.llm_calls.length > 0 && (
                            <div>
                              <h5 className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                                LLM Calls ({activeStepDetail.llm_calls.length})
                              </h5>
                              <div className="space-y-1.5">
                                {activeStepDetail.llm_calls.map((call) => (
                                  <button
                                    key={call.id}
                                    type="button"
                                    onClick={() => { setSelectedLLM(call); setLlmViewerOpen(true); }}
                                    className="w-full rounded-md border border-border/40 bg-card p-2.5 text-left transition-colors hover:bg-accent/30"
                                  >
                                    <div className="flex items-center justify-between">
                                      <span className="text-xs font-medium text-foreground">{call.model}</span>
                                      <span className="text-[10px] text-muted-foreground">
                                        {call.latency_ms > 0 ? formatDuration(call.latency_ms) : <span className="text-muted-foreground/40">--</span>}
                                      </span>
                                    </div>
                                    <div className="mt-1 flex items-center gap-3 text-[10px] text-muted-foreground">
                                      {call.total_tokens > 0 ? (
                                        <span>{call.total_tokens.toLocaleString()} tokens</span>
                                      ) : call.prompt_tokens > 0 || call.completion_tokens > 0 ? (
                                        <span>{(call.prompt_tokens + call.completion_tokens).toLocaleString()} tokens</span>
                                      ) : (
                                        <span className="text-muted-foreground/40">tokens unavailable</span>
                                      )}
                                      {call.estimated_cost_usd != null && call.estimated_cost_usd > 0 && <span>{formatCurrency(call.estimated_cost_usd)}</span>}
                                    </div>
                                    {call.response_preview && (
                                      <p className="mt-1 line-clamp-2 text-[10px] text-muted-foreground/70">{call.response_preview}</p>
                                    )}
                                  </button>
                                ))}
                              </div>
                            </div>
                          )}

                          {/* Tool Calls (table) */}
                          {activeStepDetail.tool_calls.length > 0 && (
                            <div>
                              <h5 className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                                Tool Calls ({activeStepDetail.tool_calls.length})
                              </h5>
                              <div className="rounded-md border border-border/40 overflow-hidden">
                                <table className="w-full text-xs">
                                  <thead>
                                    <tr className="border-b border-border/30 bg-muted/20">
                                      <th className="px-2.5 py-1.5 text-left text-[10px] font-medium text-muted-foreground">Tool</th>
                                      <th className="px-2.5 py-1.5 text-right text-[10px] font-medium text-muted-foreground">Duration</th>
                                      <th className="px-2.5 py-1.5 text-right text-[10px] font-medium text-muted-foreground">Status</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {activeStepDetail.tool_calls.map((tc) => {
                                      const ToolIcon = getToolIcon(tc.tool_name);
                                      return (
                                        <tr key={tc.id} className="border-b border-border/20 last:border-0 hover:bg-accent/20 transition-colors">
                                          <td className="px-2.5 py-1.5">
                                            <div className="flex items-center gap-2">
                                              <ToolIcon className={cn("h-3.5 w-3.5 shrink-0", getToolIconColor(tc.tool_name))} />
                                              <span className="font-medium text-foreground">{tc.tool_name}</span>
                                            </div>
                                          </td>
                                          <td className="px-2.5 py-1.5 text-right tabular-nums text-muted-foreground">
                                            {tc.latency_ms > 0 ? formatDuration(tc.latency_ms) : <span className="text-muted-foreground/40">--</span>}
                                          </td>
                                          <td className="px-2.5 py-1.5 text-right">
                                            <span className={cn(
                                              "text-[10px] font-medium",
                                              tc.status.toLowerCase() === "completed" || tc.status.toLowerCase() === "succeeded"
                                                ? "text-emerald-500" : "text-red-500",
                                            )}>{tc.status}</span>
                                          </td>
                                        </tr>
                                      );
                                    })}
                                  </tbody>
                                </table>
                              </div>
                            </div>
                          )}

                          {/* Event Chronology for this step */}
                          {orderedEvents.filter((e) => e.step_id === activeStepDetail.id).length > 0 && (
                            <div>
                              <h5 className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                                Events ({orderedEvents.filter((e) => e.step_id === activeStepDetail.id).length})
                              </h5>
                              <ExecutionTimeline
                                events={orderedEvents.filter((e) => e.step_id === activeStepDetail.id)}
                                activeEventId={selectedEventId}
                                onEventClick={(e) => setSelectedEventId(e.id)}
                              />
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </TabsContent>

              {/* ═══════ LOGS TAB ═══════ */}
              <TabsContent value="logs" className={cn(
                "mt-0 min-h-0 flex-1 overflow-hidden flex flex-col",
                logFullscreen && "fixed inset-0 z-50 bg-background",
              )}>
                {/* Toolbar */}
                <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border/30 px-3 py-2">
                  {/* Live/Logs mode toggle (only when execution is active) */}
                  {isExecutionActive && (
                    <div className="flex items-center gap-0.5 rounded-md border border-border/40 p-0.5 mr-1">
                      <button
                        type="button"
                        onClick={() => setLogLiveMode(false)}
                        className={cn(
                          "rounded px-2 py-0.5 text-[10px] font-medium transition-colors",
                          !logLiveMode ? "bg-primary/10 text-primary" : "text-muted-foreground hover:text-foreground",
                        )}
                      >
                        Logs
                      </button>
                      <button
                        type="button"
                        onClick={() => setLogLiveMode(true)}
                        className={cn(
                          "rounded px-2 py-0.5 text-[10px] font-medium transition-colors flex items-center gap-1",
                          logLiveMode ? "bg-emerald-500/10 text-emerald-400" : "text-muted-foreground hover:text-foreground",
                        )}
                      >
                        <span className="relative flex h-1.5 w-1.5">
                          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                          <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-500" />
                        </span>
                        Live
                      </button>
                    </div>
                  )}

                  {/* Step filter (only in logs mode) */}
                  {!logLiveMode && (
                    <Select value={selectedLogStep} onValueChange={setSelectedLogStep}>
                      <SelectTrigger className="h-7 w-40 text-[11px]">
                        <SelectValue placeholder="All steps" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All steps</SelectItem>
                        {orderedSteps.filter((s) => s.name || s.id).map((step) => (
                          <SelectItem key={step.id} value={step.name || step.id}>{getStepLabel(step)}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}

                  {/* Category filter (only in logs mode) */}
                  {!logLiveMode && (
                    <div className="flex items-center gap-0.5 rounded-md border border-border/40 p-0.5">
                      {(["all", "activity", "errors", "tooling"] as LogFilterMode[]).map((mode) => (
                        <button
                          key={mode}
                          type="button"
                          onClick={() => setLogFilterMode(mode)}
                          className={cn(
                            "rounded px-2 py-0.5 text-[10px] font-medium transition-colors",
                            logFilterMode === mode
                              ? "bg-primary/10 text-primary"
                              : "text-muted-foreground hover:text-foreground",
                          )}
                        >
                          {mode === "all" ? "All" : mode === "activity" ? `Activity (${logStats.activity})` : mode === "errors" ? `Errors (${logStats.errors})` : `Tooling (${logStats.tooling})`}
                        </button>
                      ))}
                    </div>
                  )}

                  {/* Search (only in logs mode) */}
                  {!logLiveMode && (
                    <div className="relative flex-1 min-w-[10rem]">
                      <Search className="absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground" />
                      <Input value={logSearch} onChange={(e) => setLogSearch(e.target.value)} placeholder="Search logs" className="h-7 pl-7 text-[11px]" />
                    </div>
                  )}

                  {/* Spacer for live mode */}
                  {logLiveMode && <div className="flex-1" />}

                  {/* Action buttons */}
                  <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
                    {!logLiveMode && (
                      <span className="mr-1">{filteredLogLines.length}/{normalizedLogLines.length}</span>
                    )}
                    {!logLiveMode && runTrace && (
                      <Badge variant="outline" className="text-[9px] px-1">{deriveRunLogSource(runTrace)}</Badge>
                    )}

                    {/* JSON format toggle */}
                    {!logLiveMode && (
                      <button
                        type="button"
                        onClick={() => setLogJsonFormat((v) => !v)}
                        title={logJsonFormat ? "Disable JSON formatting" : "Enable JSON formatting"}
                        className={cn(
                          "flex h-6 w-6 items-center justify-center rounded transition-colors",
                          logJsonFormat ? "bg-primary/10 text-primary" : "text-muted-foreground hover:text-foreground hover:bg-muted/50",
                        )}
                      >
                        <Braces className="h-3.5 w-3.5" />
                      </button>
                    )}

                    {/* Wrap toggle */}
                    {!logLiveMode && (
                      <button
                        type="button"
                        onClick={() => setLogWrap((v) => !v)}
                        title={logWrap ? "Disable line wrapping" : "Enable line wrapping"}
                        className={cn(
                          "flex h-6 w-6 items-center justify-center rounded transition-colors",
                          logWrap ? "bg-primary/10 text-primary" : "text-muted-foreground hover:text-foreground hover:bg-muted/50",
                        )}
                      >
                        <WrapText className="h-3.5 w-3.5" />
                      </button>
                    )}

                    {/* Fullscreen toggle */}
                    <button
                      type="button"
                      onClick={() => setLogFullscreen((v) => !v)}
                      title={logFullscreen ? "Exit fullscreen" : "Fullscreen"}
                      className="flex h-6 w-6 items-center justify-center rounded text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
                    >
                      {logFullscreen ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
                    </button>

                    {/* Copy */}
                    {!logLiveMode && (
                      <CopyButton value={filteredLogLines.join("\n")} className="h-5 w-5" />
                    )}
                  </div>
                </div>

                {/* Live Activity Stream mode */}
                {logLiveMode && (
                  <div className="flex-1 min-h-0 overflow-hidden">
                    <LiveActivityStream
                      workflowName={selectedWorkflowName ?? undefined}
                      activities={liveActivities.activities}
                      isConnected={liveActivities.isConnected}
                      isActive={liveActivities.isActive}
                      phase={liveActivities.phase}
                      error={liveActivities.error}
                      onReconnect={liveActivities.reconnect}
                      compact={false}
                    />
                  </div>
                )}

                {/* Static logs mode */}
                {!logLiveMode && (
                  <>
                    {(runTraceError || runTraceNotice) && (
                      <div className="mx-3 mt-2 rounded-md border border-red-500/20 bg-red-500/5 px-3 py-2 text-[11px] text-red-400">
                        {runTraceError || runTraceNotice}
                      </div>
                    )}

                    {!runTraceError && !runTraceNotice && detail?.run_id && !supportsWorkflowRunLogs && (
                      <div className="mx-3 mt-2 rounded-md border border-border/40 bg-muted/20 px-3 py-2 text-[11px] text-muted-foreground">
                        Worker run logs unavailable for direct invoke traces.
                      </div>
                    )}

                    <ScrollArea className="flex-1 min-h-0">
                      <div className={cn("space-y-px p-2 font-mono text-[11px] leading-relaxed", !logWrap && "overflow-x-auto")}>
                        {!runTraceLoading && filteredLogLines.length === 0 && (
                          <div className="py-12 text-center text-xs text-muted-foreground">
                            {runTrace ? "No log lines match the current filter." : "No worker log stream is available."}
                          </div>
                        )}
                        {filteredLogLines.map((line, idx) => {
                          const parsed = parseLogLine(line);
                          const displayMessage = logJsonFormat
                            ? tryFormatJson(parsed.message).formatted
                            : parsed.message;
                          const isJsonLine = logJsonFormat && tryFormatJson(parsed.message).isJson;
                          return (
                            <div key={`${idx}-${line.slice(0, 20)}`} className={cn("border-l-2 px-2.5 py-1", lineTone(parsed.message, parsed.level))}>
                              <span className="mr-2 inline-block w-8 text-right text-[9px] tabular-nums text-muted-foreground/50">{idx + 1}</span>
                              {parsed.level && (
                                <span className="mr-1.5 text-[9px] uppercase text-muted-foreground/60">[{parsed.level}]</span>
                              )}
                              {isJsonLine && (
                                <Badge variant="outline" className="mr-1.5 text-[8px] px-1 py-0 text-violet-400 border-violet-500/20">JSON</Badge>
                              )}
                              <span className={cn(
                                "text-foreground/80",
                                logWrap ? "whitespace-pre-wrap break-words" : "whitespace-pre",
                              )}>
                                {displayMessage}
                              </span>
                            </div>
                          );
                        })}
                      </div>
                    </ScrollArea>
                  </>
                )}
              </TabsContent>

              {/* ═══════ MODELS & TOOLS TAB ═══════ */}
              <TabsContent value="models" className="mt-0 min-h-0 flex-1 overflow-y-auto">
                {!detail ? (
                  <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                    Model and tool insights appear once indexed execution detail is available.
                  </div>
                ) : (
                  <div className="space-y-4 p-4">
                    {/* Token usage bar */}
                    {detail.total_tokens > 0 && (
                      <div className="rounded-lg border border-border/50 bg-card/30 p-3">
                        <h4 className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Token Usage</h4>
                        <div className="space-y-2">
                          <TokenBar label="Prompt" value={detail.prompt_tokens ?? 0} max={detail.total_tokens} color="bg-violet-500" />
                          <TokenBar label="Completion" value={detail.completion_tokens ?? 0} max={detail.total_tokens} color="bg-sky-500" />
                          <TokenBar label="Total" value={detail.total_tokens} max={detail.total_tokens} color="bg-primary" />
                        </div>
                      </div>
                    )}

                    {/* LLM Calls table */}
                    <div className="rounded-lg border border-border/50 bg-card/30 p-3">
                      <div className="mb-2 flex items-center justify-between">
                        <h4 className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                          LLM Calls ({detail.llm_calls.length})
                        </h4>
                      </div>
                      {detail.llm_calls.length === 0 ? (
                        <p className="text-xs text-muted-foreground">No LLM calls recorded.</p>
                      ) : (
                        <div className="rounded-md border border-border/40 overflow-hidden">
                          <table className="w-full text-xs">
                            <thead>
                              <tr className="border-b border-border/30 bg-muted/20">
                                <th className="px-2.5 py-1.5 text-left text-[10px] font-medium text-muted-foreground">#</th>
                                <th className="px-2.5 py-1.5 text-left text-[10px] font-medium text-muted-foreground">Model</th>
                                <th className="px-2.5 py-1.5 text-right text-[10px] font-medium text-muted-foreground">Tokens</th>
                                <th className="px-2.5 py-1.5 text-right text-[10px] font-medium text-muted-foreground">Cost</th>
                                <th className="px-2.5 py-1.5 text-right text-[10px] font-medium text-muted-foreground">Latency</th>
                              </tr>
                            </thead>
                            <tbody>
                              {detail.llm_calls.map((call, idx) => (
                                <tr
                                  key={call.id}
                                  className="border-b border-border/20 last:border-0 cursor-pointer hover:bg-accent/20 transition-colors"
                                  onClick={() => { setSelectedLLM(call); setLlmViewerOpen(true); }}
                                >
                                  <td className="px-2.5 py-1.5 text-muted-foreground">{idx + 1}</td>
                                  <td className="px-2.5 py-1.5 font-medium text-foreground">{call.model}</td>
                                  <td className="px-2.5 py-1.5 text-right tabular-nums text-muted-foreground">
                                    {call.total_tokens > 0
                                      ? call.total_tokens.toLocaleString()
                                      : (call.prompt_tokens + call.completion_tokens) > 0
                                        ? (call.prompt_tokens + call.completion_tokens).toLocaleString()
                                        : <span className="text-muted-foreground/40">--</span>}
                                  </td>
                                  <td className="px-2.5 py-1.5 text-right tabular-nums text-muted-foreground">
                                    {call.estimated_cost_usd != null && call.estimated_cost_usd > 0
                                      ? formatCurrency(call.estimated_cost_usd)
                                      : <span className="text-muted-foreground/40">--</span>}
                                  </td>
                                  <td className="px-2.5 py-1.5 text-right tabular-nums text-muted-foreground">
                                    {call.latency_ms > 0 ? formatDuration(call.latency_ms) : <span className="text-muted-foreground/40">--</span>}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>

                    {/* Tool Calls grouped */}
                    <div className="rounded-lg border border-border/50 bg-card/30 p-3">
                      <div className="mb-2 flex items-center justify-between gap-2">
                        <h4 className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                          Tool Calls ({detail.tool_calls.length})
                        </h4>
                        <div className="flex items-center gap-2">
                          <div className="relative">
                            <Search className="absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground" />
                            <Input value={toolSearch} onChange={(e) => setToolSearch(e.target.value)} placeholder="Filter tools" className="h-6 w-32 pl-6 text-[10px]" />
                          </div>
                          <Select value={toolGroupBy} onValueChange={(v) => setToolGroupBy(v as typeof toolGroupBy)}>
                            <SelectTrigger className="h-6 w-28 text-[10px]">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="tool">Group by tool</SelectItem>
                              <SelectItem value="individual">Individual</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>
                      </div>

                      {toolGroupBy === "tool" ? (
                        <div className="rounded-md border border-border/40 overflow-hidden">
                          <table className="w-full text-xs">
                            <thead>
                              <tr className="border-b border-border/30 bg-muted/20">
                                <th className="px-2.5 py-1.5 text-left text-[10px] font-medium text-muted-foreground">Tool</th>
                                <th className="px-2.5 py-1.5 text-right text-[10px] font-medium text-muted-foreground">Count</th>
                                <th className="px-2.5 py-1.5 text-right text-[10px] font-medium text-muted-foreground">Avg ms</th>
                                <th className="px-2.5 py-1.5 text-right text-[10px] font-medium text-muted-foreground">Failures</th>
                              </tr>
                            </thead>
                            <tbody>
                              {toolCallGroups.map((group) => {
                                const GroupIcon = getToolIcon(group.name);
                                return (
                                  <tr key={group.name} className="border-b border-border/20 last:border-0 hover:bg-accent/20 transition-colors">
                                    <td className="px-2.5 py-1.5">
                                      <div className="flex items-center gap-2">
                                        <GroupIcon className={cn("h-3.5 w-3.5 shrink-0", getToolIconColor(group.name))} />
                                        <span className="font-medium text-foreground">{group.name}</span>
                                      </div>
                                    </td>
                                    <td className="px-2.5 py-1.5 text-right tabular-nums text-muted-foreground">{group.count}</td>
                                    <td className="px-2.5 py-1.5 text-right tabular-nums text-muted-foreground">
                                      {group.totalMs > 0 ? Math.round(group.totalMs / group.count) : <span className="text-muted-foreground/40">--</span>}
                                    </td>
                                    <td className="px-2.5 py-1.5 text-right">
                                      <span className={group.failures > 0 ? "text-red-500 font-medium" : "text-muted-foreground"}>{group.failures}</span>
                                    </td>
                                  </tr>
                                );
                              })}
                              {toolCallGroups.length === 0 && (
                                <tr><td colSpan={4} className="px-2.5 py-4 text-center text-muted-foreground">No tool calls match filter.</td></tr>
                              )}
                            </tbody>
                          </table>
                        </div>
                      ) : (
                        <div className="rounded-md border border-border/40 overflow-hidden max-h-80 overflow-y-auto">
                          <table className="w-full text-xs">
                            <thead className="sticky top-0 bg-muted/80 backdrop-blur-sm">
                              <tr className="border-b border-border/30">
                                <th className="px-2.5 py-1.5 text-left text-[10px] font-medium text-muted-foreground">Tool</th>
                                <th className="px-2.5 py-1.5 text-right text-[10px] font-medium text-muted-foreground">Duration</th>
                                <th className="px-2.5 py-1.5 text-right text-[10px] font-medium text-muted-foreground">Status</th>
                              </tr>
                            </thead>
                            <tbody>
                              {(toolSearch.trim()
                                ? detail.tool_calls.filter((tc) => tc.tool_name.toLowerCase().includes(toolSearch.trim().toLowerCase()))
                                : detail.tool_calls
                              ).map((tc) => {
                                const IndIcon = getToolIcon(tc.tool_name);
                                return (
                                  <tr key={tc.id} className="border-b border-border/20 last:border-0 hover:bg-accent/20 transition-colors">
                                    <td className="px-2.5 py-1.5">
                                      <div className="flex items-center gap-2">
                                        <IndIcon className={cn("h-3.5 w-3.5 shrink-0", getToolIconColor(tc.tool_name))} />
                                        <span className="font-medium text-foreground">{tc.tool_name}</span>
                                      </div>
                                    </td>
                                    <td className="px-2.5 py-1.5 text-right tabular-nums text-muted-foreground">
                                      {tc.latency_ms > 0 ? formatDuration(tc.latency_ms) : <span className="text-muted-foreground/40">--</span>}
                                    </td>
                                    <td className="px-2.5 py-1.5 text-right">
                                      <span className={cn(
                                        "text-[10px] font-medium",
                                        tc.status.toLowerCase() === "completed" || tc.status.toLowerCase() === "succeeded"
                                          ? "text-emerald-500" : "text-red-500",
                                      )}>{tc.status}</span>
                                    </td>
                                  </tr>
                                );
                              })}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </TabsContent>

              {/* ═══════ COMPARE TAB ═══════ */}
              <TabsContent value="compare" className="mt-0 min-h-0 flex-1 overflow-y-auto p-4">
                <div className="space-y-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <Select value={compareLeftId ?? undefined} onValueChange={(v) => setCompareLeftId(v || null)}>
                      <SelectTrigger className="h-8 w-64 text-xs">
                        <SelectValue placeholder="Left execution" />
                      </SelectTrigger>
                      <SelectContent>
                        {executions.filter((e) => e.id).map((exec) => (
                          <SelectItem key={exec.id} value={exec.id} className="text-xs">
                            {exec.workflow_name} &middot; {exec.status} &middot; {formatCompactDate(exec.started_at)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <GitCompare className="h-4 w-4 text-muted-foreground" />
                    <Select value={compareRightId ?? undefined} onValueChange={(v) => setCompareRightId(v || null)}>
                      <SelectTrigger className="h-8 w-64 text-xs">
                        <SelectValue placeholder="Right execution" />
                      </SelectTrigger>
                      <SelectContent>
                        {executions.filter((e) => e.id).map((exec) => (
                          <SelectItem key={exec.id} value={exec.id} className="text-xs">
                            {exec.workflow_name} &middot; {exec.status} &middot; {formatCompactDate(exec.started_at)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    {/* Quick: compare with previous */}
                    {executions.length >= 2 && (
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-8 text-[11px]"
                        onClick={() => {
                          setCompareLeftId(executions[0]?.id ?? null);
                          setCompareRightId(executions[1]?.id ?? null);
                        }}
                      >
                        Compare latest vs. previous
                      </Button>
                    )}
                  </div>

                  {compareLoading ? (
                    <div className="flex items-center justify-center py-16">
                      <LoaderCircle className="h-6 w-6 animate-spin text-primary" />
                    </div>
                  ) : (
                    <ExecutionDiffView left={compareLeft} right={compareRight} />
                  )}
                </div>
              </TabsContent>
            </Tabs>
          )}
        </div>
      </div>

      {/* Drawers/Dialogs */}
      <LLMCallViewer llmCall={selectedLLM} open={llmViewerOpen} onOpenChange={setLlmViewerOpen} />
    </div>
  );
}

// ─── Token Bar Helper ─────────────────────────────────────────────────────────

function TokenBar({ label, value, max, color }: { label: string; value: number; max: number; color: string }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="flex items-center gap-2">
      <span className="w-20 text-[10px] text-muted-foreground">{label}</span>
      <div className="flex-1 h-2 rounded-full bg-muted/30 overflow-hidden">
        <div className={cn("h-full rounded-full transition-all", color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-16 text-right text-[10px] tabular-nums text-muted-foreground">{value.toLocaleString()}</span>
    </div>
  );
}
