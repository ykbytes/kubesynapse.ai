import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import {
  Activity,
  BarChart3,
  Braces,
  FileText,
  Layers,
  LoaderCircle,
  Maximize2,
  Minimize2,
  Search,
  WrapText,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
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
import type { ExecutionListItem, ExecutionTrace, StepTrace } from "@/types";

import { CopyButton } from "../shared/CopyButton";
import { ExecutionBanner } from "../observatory/ExecutionBanner";
import { ExecutionTimelineView } from "../observatory/ExecutionTimelineView";
import { AnalyticsView } from "../observatory/AnalyticsView";
import { DetailDrawer, type DetailItem } from "../observatory/DetailDrawer";
import { RunsRail } from "../observatory/RunsRail";
import { LiveActivityStream, useWorkflowActivities } from "./LiveActivityStream";

// ─── Constants ────────────────────────────────────────────────────────────────

type LogFilterMode = "all" | "activity" | "errors" | "tooling";
type ObservatoryTab = "timeline" | "analytics" | "logs";

const LOG_ACTIVITY_KEYWORDS = [
  "tool_call", "response.tool_call", "apply_patch", "artifact", "workspace",
  "approval", "verify", "review", "loop", "plan", "step", "execution",
];
const LOG_ERROR_KEYWORDS = ["error", "failed", "exception", "traceback", "timeout", "denied", "rejected"];
const LOG_TOOLING_KEYWORDS = ["opencode", "mcp", "tool_call", "context_overflow", "session", "compaction", "retry"];

// ─── Helpers ──────────────────────────────────────────────────────────────────

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
  const [activeTab, setActiveTab] = useState<ObservatoryTab>("timeline");
  const [detailDrawerItem, setDetailDrawerItem] = useState<DetailItem | null>(null);
  const [selectedLogStep, setSelectedLogStep] = useState<string>("all");
  const [logSearch, setLogSearch] = useState("");
  const [logFilterMode, setLogFilterMode] = useState<LogFilterMode>("activity");
  const [runTraceLoading, setRunTraceLoading] = useState(false);
  const [runTrace, setRunTrace] = useState<WorkflowRunTraceResponse | null>(null);
  const [runTraceError, setRunTraceError] = useState("");
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
    setRunTrace(null); setRunTraceError(""); setActiveTab("timeline");
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
    setActiveTab("timeline");
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

  // Reset filters on run change
  useEffect(() => {
    setSelectedLogStep("all");
    setLogSearch(""); setLogFilterMode("activity");
    setDetailDrawerItem(null);
  }, [detail?.id, runTrace?.run_id]);

  // ── Computed Values ────────────────────────────────────────────────────────

  const supportsWorkflowRunLogs = useMemo(() => canLoadWorkflowRunTrace(detail), [detail]);
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
            onSelectRun={(id) => { setSelectedRunId(id); setActiveTab("timeline"); }}
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
                  <TabsTrigger value="timeline" className="relative h-9 rounded-none border-b-2 border-transparent px-3 text-xs font-medium transition-colors data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none">
                    <Layers className="mr-1.5 h-3.5 w-3.5" />
                    Timeline
                  </TabsTrigger>
                  <TabsTrigger value="analytics" className="relative h-9 rounded-none border-b-2 border-transparent px-3 text-xs font-medium transition-colors data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none">
                    <BarChart3 className="mr-1.5 h-3.5 w-3.5" />
                    Analytics
                  </TabsTrigger>
                  <TabsTrigger value="logs" className="relative h-9 rounded-none border-b-2 border-transparent px-3 text-xs font-medium transition-colors data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none">
                    <FileText className="mr-1.5 h-3.5 w-3.5" />
                    Logs
                    {logStats.errors > 0 && <Badge variant="destructive" className="ml-1.5 h-4 px-1 text-[9px]">{logStats.errors}</Badge>}
                  </TabsTrigger>
                </TabsList>
              </div>

              {/* ═══════ TIMELINE TAB ═══════ */}
              <TabsContent value="timeline" className="mt-0 min-h-0 flex-1 overflow-hidden flex">
                <div className="flex-1 min-w-0 overflow-hidden">
                  <ExecutionTimelineView
                    detail={detail}
                    onLLMClick={(call) => setDetailDrawerItem({ type: "llm", item: call })}
                    onToolClick={(call) => setDetailDrawerItem({ type: "tool", item: call })}
                    onStepClick={(step) => setDetailDrawerItem({ type: "step", item: step })}
                  />
                </div>
                {/* Detail Drawer — right-side panel, no overlay */}
                {detailDrawerItem && (
                  <div className="w-[460px] shrink-0 overflow-hidden">
                    <DetailDrawer
                      detail={detailDrawerItem}
                      onClose={() => setDetailDrawerItem(null)}
                    />
                  </div>
                )}
              </TabsContent>

              {/* ═══════ ANALYTICS TAB ═══════ */}
              <TabsContent value="analytics" className="mt-0 min-h-0 flex-1 overflow-y-auto">
                <AnalyticsView
                  detail={detail}
                  run={selectedRun}
                  previousRuns={runs}
                />
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
                  {!logLiveMode && detail && (
                    <Select value={selectedLogStep} onValueChange={setSelectedLogStep}>
                      <SelectTrigger className="h-7 w-40 text-[11px]">
                        <SelectValue placeholder="All steps" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All steps</SelectItem>
                        {detail.steps.filter((s) => s.name || s.id).map((step) => (
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
            </Tabs>
          )}
        </div>
      </div>
    </div>
  );
}

