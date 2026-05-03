import { useEffect, useMemo, useRef, useState, useCallback, type ComponentType } from "react";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  BrainCircuit,
  CheckCircle2,
  Download,
  ExternalLink,
  FileText,
  GitCompare,
  ListTree,
  LoaderCircle,
  RefreshCw,
  Search,
  Timer,
  Wrench,
  X,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useConnection } from "@/contexts/ConnectionContext";
import { useWorkspace } from "@/contexts/WorkspaceContext";
import {
  deleteExecution,
  exportExecutionHtml,
  exportExecutionJson,
  fetchExecutionDetail,
  fetchWorkflowRunTrace,
  listExecutions,
  type WorkflowRunTraceResponse,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import type { ExecutionListItem, ExecutionTrace, LLMCallRecord, StepTrace } from "@/types";

import { CopyButton } from "./CopyButton";
import { ExecutionDiffView } from "./observatory/ExecutionDiffView";
import { ExecutionTimeline } from "./observatory/ExecutionTimeline";
import { LLMCallViewer } from "./observatory/LLMCallViewer";
import { StepInspector } from "./observatory/StepInspector";

interface Filters {
  workflow: string;
  agent: string;
  status: string;
  from_date: string;
  to_date: string;
  search: string;
  sort_by: string;
}

type LogFilterMode = "all" | "activity" | "errors" | "tooling";

const DEFAULT_FILTERS: Filters = {
  workflow: "",
  agent: "",
  status: "all",
  from_date: "",
  to_date: "",
  search: "",
  sort_by: "started_at_desc",
};

const EVENT_TONE: Record<string, string> = {
  EXECUTION_STARTED: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  EXECUTION_COMPLETED: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  EXECUTION_FAILED: "border-destructive/30 bg-destructive/10 text-destructive",
  EXECUTION_CANCELLED: "border-amber-500/30 bg-amber-500/10 text-amber-300",
  STEP_STARTED: "border-sky-500/30 bg-sky-500/10 text-sky-300",
  STEP_COMPLETED: "border-sky-500/30 bg-sky-500/10 text-sky-300",
  STEP_FAILED: "border-destructive/30 bg-destructive/10 text-destructive",
  STEP_SKIPPED: "border-border/60 bg-background/60 text-muted-foreground",
  LLM_CALL_STARTED: "border-violet-500/30 bg-violet-500/10 text-violet-300",
  LLM_CALL_COMPLETED: "border-violet-500/30 bg-violet-500/10 text-violet-300",
  LLM_CALL_FAILED: "border-destructive/30 bg-destructive/10 text-destructive",
  TOOL_CALL_STARTED: "border-cyan-500/30 bg-cyan-500/10 text-cyan-300",
  TOOL_CALL_COMPLETED: "border-cyan-500/30 bg-cyan-500/10 text-cyan-300",
  TOOL_CALL_FAILED: "border-destructive/30 bg-destructive/10 text-destructive",
  DECISION: "border-amber-500/30 bg-amber-500/10 text-amber-300",
  BRANCH_TAKEN: "border-amber-500/30 bg-amber-500/10 text-amber-300",
  WARNING: "border-amber-500/30 bg-amber-500/10 text-amber-300",
  ERROR: "border-destructive/30 bg-destructive/10 text-destructive",
  PROGRESS: "border-primary/30 bg-primary/10 text-primary",
  TODO_CREATED: "border-primary/30 bg-primary/10 text-primary",
  TODO_COMPLETED: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  ARTIFACT_CREATED: "border-pink-500/30 bg-pink-500/10 text-pink-300",
  STATE_SNAPSHOT: "border-border/60 bg-background/60 text-muted-foreground",
  VARIABLE_SET: "border-border/60 bg-background/60 text-muted-foreground",
  LLM_STREAM_CHUNK: "border-border/60 bg-background/60 text-muted-foreground",
  CUSTOM: "border-border/60 bg-background/60 text-muted-foreground",
};

const LOG_ACTIVITY_KEYWORDS = [
  "tool_call",
  "response.tool_call",
  "apply_patch",
  "artifact",
  "workspace",
  "approval",
  "verify",
  "review",
  "loop",
  "plan",
  "step",
  "execution",
];

const LOG_ERROR_KEYWORDS = ["error", "failed", "exception", "traceback", "timeout", "denied", "rejected"];
const LOG_TOOLING_KEYWORDS = ["opencode", "mcp", "tool_call", "context_overflow", "session", "compaction", "retry"];

function statusBadgeClasses(status: string | null | undefined): string {
  const s = status?.toLowerCase() ?? "unknown";
  if (s === "completed" || s === "succeeded") return "border-emerald-500/20 bg-emerald-500/10 text-emerald-300";
  if (s === "failed" || s === "error") return "border-destructive/20 bg-destructive/10 text-destructive";
  if (s === "running" || s === "in_progress") return "border-amber-500/20 bg-amber-500/10 text-amber-300";
  if (s.includes("cancel")) return "border-amber-500/20 bg-amber-500/10 text-amber-300";
  return "border-border/60 bg-background/60 text-muted-foreground";
}

function statusDotClasses(status: string | null | undefined): string {
  const s = status?.toLowerCase() ?? "unknown";
  if (s === "completed" || s === "succeeded") return "bg-emerald-500";
  if (s === "failed" || s === "error") return "bg-destructive";
  if (s === "running" || s === "in_progress") return "bg-amber-500 animate-pulse";
  if (s.includes("cancel")) return "bg-amber-500";
  return "bg-muted-foreground/40";
}

function formatDuration(ms?: number | null): string {
  if (ms == null || !Number.isFinite(ms)) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  const minutes = Math.floor(seconds / 60);
  const rem = Math.round(seconds % 60);
  return `${minutes}m ${rem}s`;
}

function formatDateTime(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function formatCompactDate(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatCurrency(value?: number | null): string {
  if (value == null || !Number.isFinite(value)) return "—";
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
    return "border-destructive/30 bg-destructive/8 text-destructive";
  }
  if (normalizedLevel.includes("warn")) {
    return "border-amber-500/30 bg-amber-500/8 text-amber-300";
  }
  if (matchesKeyword(message, LOG_ACTIVITY_KEYWORDS)) {
    return "border-emerald-500/30 bg-emerald-500/8 text-emerald-300";
  }
  if (matchesKeyword(message, LOG_TOOLING_KEYWORDS)) {
    return "border-sky-500/30 bg-sky-500/8 text-sky-300";
  }
  return "border-border/50 bg-background/50 text-foreground/80";
}

function getStepLabel(step: StepTrace): string {
  return step.step_index != null ? `#${step.step_index + 1} ${step.name}` : step.name;
}

function getTriggerType(triggeredBy?: string | null, workflowName?: string): { label: string; className: string } {
  const t = (triggeredBy ?? "").toLowerCase();
  if (t.includes("manual") || t.includes("user") || t.includes("console")) {
    return { label: "manual", className: "border-blue-500/20 bg-blue-500/10 text-blue-300" };
  }
  if (t.includes("schedule") || t.includes("cron") || t.includes("timer")) {
    return { label: "scheduled", className: "border-violet-500/20 bg-violet-500/10 text-violet-300" };
  }
  if (t.includes("event") || t.includes("webhook") || t.includes("trigger")) {
    return { label: "event", className: "border-amber-500/20 bg-amber-500/10 text-amber-300" };
  }
  if (t.includes("invoke") || workflowName?.startsWith("invoke:")) {
    return { label: "invoke", className: "border-cyan-500/20 bg-cyan-500/10 text-cyan-300" };
  }
  if (!triggeredBy && workflowName?.startsWith("invoke:")) {
    return { label: "invoke", className: "border-cyan-500/20 bg-cyan-500/10 text-cyan-300" };
  }
  if (!triggeredBy) {
    return { label: "—", className: "border-border/60 bg-background/60 text-muted-foreground" };
  }
  return { label: triggeredBy, className: "border-border/60 bg-background/60 text-muted-foreground" };
}

function computeTraceability(detail: ExecutionTrace | null) {
  if (!detail) {
    return {
      eventCount: 0,
      completedSteps: 0,
      failedSteps: 0,
      warningEvents: 0,
      errorEvents: 0,
      artifactEvents: 0,
      coverage: 0,
      analysis: "Select an execution to inspect traceability.",
      hotSteps: [] as StepTrace[],
    };
  }

  const completedSteps = detail.steps.filter((step) => ["completed", "succeeded"].includes(step.status.toLowerCase())).length;
  const failedSteps = detail.steps.filter((step) => ["failed", "error"].includes(step.status.toLowerCase())).length;
  const warningEvents = detail.events.filter((event) => event.event_type === "WARNING").length;
  const errorEvents = detail.events.filter((event) => event.event_type === "ERROR" || event.event_type === "STEP_FAILED").length;
  const artifactEvents = detail.events.filter((event) => event.event_type === "ARTIFACT_CREATED").length;
  const coveredSteps = detail.steps.filter(
    (step) => step.llm_calls.length > 0 || step.tool_calls.length > 0 || Boolean(step.input_preview) || Boolean(step.output_preview),
  ).length;
  const coverage = detail.steps.length > 0 ? Math.round((coveredSteps / detail.steps.length) * 100) : 0;
  const hotSteps = [...detail.steps].sort((left, right) => {
    const rightWeight = (right.latency_ms ?? 0) + right.llm_calls.length * 100 + right.tool_calls.length * 50;
    const leftWeight = (left.latency_ms ?? 0) + left.llm_calls.length * 100 + left.tool_calls.length * 50;
    return rightWeight - leftWeight;
  }).slice(0, 3);

  let analysis = "Execution completed without obvious blockers.";
  if (["failed", "error"].includes(detail.status.toLowerCase()) || failedSteps > 0 || errorEvents > 0) {
    analysis = "Execution encountered failures. Inspect failed steps, error events, and worker logs first.";
  } else if (warningEvents > 0) {
    analysis = "Execution completed with warning signals. Review timeline and logs for degraded behavior.";
  } else if (detail.llm_call_count === 0 && detail.tool_call_count === 0 && detail.events.length < 2) {
    analysis = "Trace coverage is thin. Logs and raw event payloads are the best source of execution detail here.";
  }

  return {
    eventCount: detail.events.length,
    completedSteps,
    failedSteps,
    warningEvents,
    errorEvents,
    artifactEvents,
    coverage,
    analysis,
    hotSteps,
  };
}

function deriveRunLogSource(runTrace: WorkflowRunTraceResponse | null): string {
  if (!runTrace) return "unavailable";
  if (runTrace.source === "archived") return "archived";
  if (runTrace.source === "live-worker") return "live-worker";
  return runTrace.source;
}

function canLoadWorkflowRunTrace(detail: ExecutionTrace | null): boolean {
  if (!detail?.run_id) return false;
  if (!detail.workflow_name.trim()) return false;
  return !detail.workflow_name.startsWith("invoke:");
}

function buildRunTraceNotice(runTrace: WorkflowRunTraceResponse | null): string | null {
  if (!runTrace) return null;
  if (runTrace.live_log_error && runTrace.archived_log_available) {
    return `Live worker logs were unavailable; showing archived logs instead. ${runTrace.live_log_error}`;
  }
  if (runTrace.live_log_error) {
    return runTrace.live_log_error;
  }
  if (runTrace.archived_log_truncated) {
    return "Archived logs were truncated before reaching the Observatory.";
  }
  return null;
}

interface ExecutionObservatoryProps {
  selectedExecutionId?: string | null;
  sidebarMode?: boolean;
}

export function ExecutionObservatory({ selectedExecutionId: externalSelectedId, sidebarMode }: ExecutionObservatoryProps) {
  const { token, namespace } = useConnection();
  const { observatoryFocus, clearObservatoryFocus, navigateToResource } = useWorkspace();
  const executionListRequestIdRef = useRef(0);
  const isSidebarMode = sidebarMode === true;

  const [executions, setExecutions] = useState<ExecutionListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const [selectedExecutionId, setSelectedExecutionId] = useState<string | null>(externalSelectedId ?? null);
  const [detail, setDetail] = useState<ExecutionTrace | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [activeTab, setActiveTab] = useState("steps");
  const [selectedStep, setSelectedStep] = useState<StepTrace | null>(null);
  const [stepInspectorOpen, setStepInspectorOpen] = useState(false);
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
  const [focusRequestAt, setFocusRequestAt] = useState<number | null>(null);

  const loadExecutions = useCallback(async () => {
    const requestId = ++executionListRequestIdRef.current;
    setLoading(true);
    try {
      const result = await listExecutions(token, namespace, {
        limit: 200,
      });
      if (requestId !== executionListRequestIdRef.current) return;
      setExecutions(result.items);
    } catch (error) {
      if (requestId !== executionListRequestIdRef.current) return;
      toast.error(error instanceof Error ? error.message : "Failed to load executions");
    } finally {
      if (requestId !== executionListRequestIdRef.current) return;
      setLoading(false);
    }
  }, [namespace, token]);

  useEffect(() => {
    void loadExecutions();
  }, [loadExecutions]);

  useEffect(() => {
    if (!observatoryFocus) return;
    setFilters({
      ...DEFAULT_FILTERS,
      workflow: observatoryFocus.workflowName,
    });
    setExecutions([]);
    setSelectedExecutionId(null);
    setDetail(null);
    setRunTrace(null);
    setRunTraceError("");
    setActiveTab("steps");
    setFocusRequestAt(observatoryFocus.requestedAt);
    void loadExecutions();
  }, [loadExecutions, observatoryFocus]);

  useEffect(() => {
    if (!observatoryFocus || focusRequestAt !== observatoryFocus.requestedAt || loading) return;
    const match = executions.find(
      (execution) =>
        execution.workflow_name === observatoryFocus.workflowName &&
        (!observatoryFocus.runId || execution.run_id === observatoryFocus.runId),
    );
    if (match) {
      setSelectedExecutionId(match.id);
      setActiveTab("steps");
      clearObservatoryFocus();
      setFocusRequestAt(null);
    }
  }, [clearObservatoryFocus, executions, focusRequestAt, loading, observatoryFocus]);

  // Sync with externally-controlled selection (sidebar mode)
  useEffect(() => {
    if (externalSelectedId !== undefined) {
      setSelectedExecutionId(externalSelectedId);
    }
  }, [externalSelectedId]);

  useEffect(() => {
    if (!observatoryFocus || !focusRequestAt) return;
    const timer = window.setInterval(() => {
      void loadExecutions();
    }, 3000);
    return () => {
      window.clearInterval(timer);
    };
  }, [focusRequestAt, loadExecutions, observatoryFocus]);

  useEffect(() => {
    if (!selectedExecutionId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    fetchExecutionDetail(token, selectedExecutionId)
      .then((result) => {
        if (!cancelled) setDetail(result);
      })
      .catch((error) => {
        if (!cancelled) toast.error(error instanceof Error ? error.message : "Failed to load execution detail");
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedExecutionId, token]);

  useEffect(() => {
    if (!detail?.run_id) {
      setRunTrace(null);
      setRunTraceError("");
      setRunTraceLoading(false);
      return;
    }

    if (!canLoadWorkflowRunTrace(detail)) {
      setRunTrace(null);
      setRunTraceError("");
      setRunTraceLoading(false);
      return;
    }

    let cancelled = false;
    setRunTraceLoading(true);
    setRunTraceError("");
    fetchWorkflowRunTrace(token, namespace, detail.workflow_name, detail.run_id, 4000)
      .then((result) => {
        if (!cancelled) setRunTrace(result);
      })
      .catch((error) => {
        if (!cancelled) {
          const message = error instanceof Error ? error.message : "Failed to load workflow run logs";
          setRunTraceError(message);
          setRunTrace(null);
        }
      })
      .finally(() => {
        if (!cancelled) setRunTraceLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [detail?.run_id, detail?.workflow_name, namespace, token]);

  useEffect(() => {
    const isExecutionActive = detail ? ["running", "queued", "pending", "in_progress"].includes(detail.status.toLowerCase()) : false;
    if (!isExecutionActive) return;

    const timer = window.setInterval(() => {
      void loadExecutions();
      if (!selectedExecutionId) return;
      fetchExecutionDetail(token, selectedExecutionId)
        .then((result) => {
          setDetail(result);
        })
        .catch(() => {
          // Keep background polling quiet; explicit refresh and selection already surface errors.
        });
    }, 3000);

    return () => {
      window.clearInterval(timer);
    };
  }, [detail, loadExecutions, selectedExecutionId, token]);

  useEffect(() => {
    if (!compareLeftId && !compareRightId) return;
    let cancelled = false;
    setCompareLoading(true);
    Promise.all([
      compareLeftId ? fetchExecutionDetail(token, compareLeftId).catch(() => null) : Promise.resolve(null),
      compareRightId ? fetchExecutionDetail(token, compareRightId).catch(() => null) : Promise.resolve(null),
    ])
      .then(([left, right]) => {
        if (!cancelled) {
          setCompareLeft(left);
          setCompareRight(right);
        }
      })
      .finally(() => {
        if (!cancelled) setCompareLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [compareLeftId, compareRightId, token]);

  useEffect(() => {
    setSelectedEventId(null);
    setSelectedLogStep("all");
    setLogSearch("");
    setLogFilterMode("activity");
  }, [detail?.id]);

  const traceability = useMemo(() => computeTraceability(detail), [detail]);
  const supportsWorkflowRunLogs = useMemo(() => canLoadWorkflowRunTrace(detail), [detail]);
  const filteredExecutions = useMemo(() => {
    const query = filters.search.trim().toLowerCase();
    const workflowFilter = filters.workflow.trim().toLowerCase();
    const agentFilter = filters.agent.trim().toLowerCase();
    const statusFilter = filters.status === "all" ? "" : filters.status.trim().toLowerCase();
    const fromTime = filters.from_date ? new Date(filters.from_date).getTime() : null;
    const toTime = filters.to_date ? new Date(`${filters.to_date}T23:59:59.999`).getTime() : null;

    const filtered = executions.filter((execution) => {
      const startedAt = execution.started_at ? new Date(execution.started_at).getTime() : null;
      if (workflowFilter && !execution.workflow_name.toLowerCase().includes(workflowFilter)) return false;
      if (agentFilter && !(execution.agent_name ?? "").toLowerCase().includes(agentFilter)) return false;
      if (statusFilter && !execution.status.toLowerCase().includes(statusFilter)) return false;
      if (query) {
        const haystack = [execution.workflow_name, execution.agent_name ?? "", execution.run_id ?? "", execution.id]
          .join(" ")
          .toLowerCase();
        if (!haystack.includes(query)) return false;
      }
      if (fromTime != null && (startedAt == null || startedAt < fromTime)) return false;
      if (toTime != null && (startedAt == null || startedAt > toTime)) return false;
      return true;
    });

    const sorted = [...filtered];
    switch (filters.sort_by) {
      case "started_at_asc":
        sorted.sort((left, right) => (new Date(left.started_at ?? 0).getTime()) - (new Date(right.started_at ?? 0).getTime()));
        break;
      case "duration_desc":
        sorted.sort((left, right) => (right.duration_ms ?? -1) - (left.duration_ms ?? -1));
        break;
      case "duration_asc":
        sorted.sort((left, right) => (left.duration_ms ?? Number.MAX_SAFE_INTEGER) - (right.duration_ms ?? Number.MAX_SAFE_INTEGER));
        break;
      case "started_at_desc":
      default:
        sorted.sort((left, right) => (new Date(right.started_at ?? 0).getTime()) - (new Date(left.started_at ?? 0).getTime()));
        break;
    }
    return sorted;
  }, [executions, filters]);
  const orderedEvents = useMemo(
    () => (detail ? [...detail.events].sort((left, right) => new Date(left.timestamp).getTime() - new Date(right.timestamp).getTime()) : []),
    [detail],
  );
  const orderedSteps = useMemo(
    () => (detail ? [...detail.steps].sort((left, right) => (left.step_index ?? Number.MAX_SAFE_INTEGER) - (right.step_index ?? Number.MAX_SAFE_INTEGER)) : []),
    [detail],
  );
  const normalizedLogLines = useMemo(() => normalizeLines(runTrace?.logs ?? ""), [runTrace?.logs]);

  const filteredLogLines = useMemo(() => {
    const activeStep = selectedLogStep;
    return normalizedLogLines.filter((line) => {
      if (activeStep !== "all" && !line.toLowerCase().includes(activeStep.toLowerCase())) return false;
      if (logFilterMode === "activity" && !matchesKeyword(line, LOG_ACTIVITY_KEYWORDS)) return false;
      if (logFilterMode === "errors" && !matchesKeyword(line, LOG_ERROR_KEYWORDS)) return false;
      if (logFilterMode === "tooling" && !matchesKeyword(line, LOG_TOOLING_KEYWORDS)) return false;
      if (logSearch.trim() && !line.toLowerCase().includes(logSearch.trim().toLowerCase())) return false;
      return true;
    });
  }, [logFilterMode, logSearch, normalizedLogLines, selectedLogStep]);

  const eventGroups = useMemo(() => {
    const counts = new Map<string, number>();
    for (const event of orderedEvents) {
      counts.set(event.event_type, (counts.get(event.event_type) ?? 0) + 1);
    }
    return Array.from(counts.entries()).sort((left, right) => right[1] - left[1]);
  }, [orderedEvents]);

  const logStats = useMemo(
    () => ({
      errors: normalizedLogLines.filter((line) => matchesKeyword(line, LOG_ERROR_KEYWORDS)).length,
      activity: normalizedLogLines.filter((line) => matchesKeyword(line, LOG_ACTIVITY_KEYWORDS)).length,
      tooling: normalizedLogLines.filter((line) => matchesKeyword(line, LOG_TOOLING_KEYWORDS)).length,
    }),
    [normalizedLogLines],
  );
  const runTraceNotice = useMemo(() => buildRunTraceNotice(runTrace), [runTrace]);

  const hasFilters =
    Object.entries(filters).some(([key, value]) => key !== "sort_by" && value !== "") ||
    filters.sort_by !== DEFAULT_FILTERS.sort_by;

  const handleRefresh = () => {
    void loadExecutions();
    if (selectedExecutionId) {
      setDetailLoading(true);
      fetchExecutionDetail(token, selectedExecutionId)
        .then((result) => setDetail(result))
        .catch((error) => toast.error(error instanceof Error ? error.message : "Failed to refresh execution"))
        .finally(() => setDetailLoading(false));
    }
  };

  const handleDelete = async (executionId: string) => {
    if (!confirm("Delete this execution trace? This cannot be undone.")) return;
    try {
      await deleteExecution(token, executionId);
      toast.success("Execution deleted");
      if (selectedExecutionId === executionId) {
        setSelectedExecutionId(null);
        setDetail(null);
        setRunTrace(null);
      }
      void loadExecutions();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Delete failed");
    }
  };

  const handleExportJson = async (executionId: string) => {
    try {
      const text = await exportExecutionJson(token, executionId);
      const blob = new Blob([text], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `execution-${executionId}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
      toast.success("Execution JSON exported");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Export failed");
    }
  };

  const handleExportHtml = async (executionId: string) => {
    try {
      const text = await exportExecutionHtml(token, executionId);
      const blob = new Blob([text], { type: "text/html" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `execution-${executionId}.html`;
      anchor.click();
      URL.revokeObjectURL(url);
      toast.success("Execution HTML report exported");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Export failed");
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col gap-3">
      <div className="flex flex-col gap-3 rounded-[1.75rem] border border-border/70 bg-card/55 p-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
            <Activity className="h-3.5 w-3.5 text-primary" />
            Traceability Surface
          </div>
          <h2 className="mt-1 text-xl font-semibold text-foreground">Execution Observatory</h2>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
            Inspect execution health, step lineage, worker logs, event chronology, LLM/tool behavior, and exported evidence from one place.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" className="h-8 rounded-lg text-xs" onClick={handleRefresh}>
            <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
            Refresh
          </Button>
          {detail && (
            <>
              <Button variant="outline" size="sm" className="h-8 rounded-lg text-xs" onClick={() => void handleExportJson(detail.id)}>
                <Download className="mr-1.5 h-3.5 w-3.5" />
                JSON
              </Button>
              <Button variant="outline" size="sm" className="h-8 rounded-lg text-xs" onClick={() => void handleExportHtml(detail.id)}>
                <FileText className="mr-1.5 h-3.5 w-3.5" />
                HTML Report
              </Button>
            </>
          )}
        </div>
      </div>

      <div className={cn("min-h-0 flex-1 gap-3 overflow-hidden", isSidebarMode ? "flex flex-col" : "grid xl:grid-cols-[340px_minmax(0,1fr)]")}>
        {!isSidebarMode && (
        <div className="flex min-h-0 flex-col gap-3 overflow-hidden">
          <Card className="shrink-0 rounded-[1.75rem] bg-card/55">
            <CardContent className="space-y-2 p-3">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={filters.search}
                  onChange={(event) => setFilters((current) => ({ ...current, search: event.target.value }))}
                  placeholder="Search workflow, agent, or run id"
                  className="h-8 pl-9 text-xs"
                />
              </div>
              <div className="flex items-center gap-2">
                <Select value={filters.sort_by} onValueChange={(value) => setFilters((current) => ({ ...current, sort_by: value }))}>
                  <SelectTrigger className="h-7 text-[11px]">
                    <SelectValue placeholder="Sort" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="started_at_desc">Newest first</SelectItem>
                    <SelectItem value="started_at_asc">Oldest first</SelectItem>
                    <SelectItem value="duration_desc">Longest first</SelectItem>
                    <SelectItem value="duration_asc">Shortest first</SelectItem>
                  </SelectContent>
                </Select>
                <Select value={filters.status} onValueChange={(value) => setFilters((current) => ({ ...current, status: value }))}>
                  <SelectTrigger className="h-7 text-[11px]">
                    <SelectValue placeholder="Status" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All</SelectItem>
                    <SelectItem value="completed">Completed</SelectItem>
                    <SelectItem value="failed">Failed</SelectItem>
                    <SelectItem value="running">Running</SelectItem>
                  </SelectContent>
                </Select>
                {hasFilters && (
                  <Button variant="ghost" size="sm" className="h-7 px-2 text-[11px]" onClick={() => setFilters(DEFAULT_FILTERS)}>
                    <X className="mr-1 h-3 w-3" />
                    Clear
                  </Button>
                )}
              </div>
            </CardContent>
          </Card>

          <Card className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-[1.75rem] bg-card/55">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between gap-2">
                <div>
                  <CardTitle className="text-sm">Recent Executions</CardTitle>
                  <CardDescription>{loading ? "Refreshing execution index..." : `${filteredExecutions.length} shown of ${executions.length}`}</CardDescription>
                </div>
                <Badge variant="outline" className="text-[10px]">{filteredExecutions.length}</Badge>
              </div>
            </CardHeader>
            <CardContent className="min-h-0 flex-1 overflow-hidden p-0">
              <ScrollArea className="h-full">
                <div className="space-y-2 p-3">
                  {loading && executions.length === 0 && [0, 1, 2, 3].map((index) => (
                    <div key={index} className="rounded-2xl border border-border/40 p-3">
                      <Skeleton className="h-4 w-40 rounded" />
                      <Skeleton className="mt-2 h-3 w-28 rounded" />
                      <Skeleton className="mt-3 h-7 w-full rounded-xl" />
                    </div>
                  ))}
                  {!loading && filteredExecutions.length === 0 && (
                    <div className="flex flex-col items-center justify-center py-12 text-center">
                      <Activity className="h-8 w-8 text-muted-foreground/40" />
                      <p className="mt-3 text-sm text-muted-foreground">No executions matched the current filters.</p>
                    </div>
                  )}
                  {filteredExecutions.map((execution) => {
                    const isSelected = execution.id === selectedExecutionId;
                    return (
                      <button
                        key={execution.id}
                        type="button"
                        onClick={() => {
                          setSelectedExecutionId(execution.id);
                          setActiveTab("steps");
                        }}
                        className={cn(
                          "w-full rounded-2xl border p-3 text-left transition-colors",
                          isSelected
                            ? "border-primary/30 bg-primary/8 shadow-sm"
                            : "border-border/50 bg-background/55 hover:border-border hover:bg-accent/30",
                        )}
                      >
                        <div className="flex items-start gap-2">
                          <span className={cn("mt-1 h-2.5 w-2.5 shrink-0 rounded-full", statusDotClasses(execution.status))} />
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <p className="truncate text-sm font-semibold text-foreground">{execution.workflow_name}</p>
                              <Badge variant="outline" className={cn("h-5 border px-2 text-[10px] uppercase", statusBadgeClasses(execution.status))}>
                                {execution.status}
                              </Badge>
                              {(() => { const trigger = getTriggerType(execution.triggered_by, execution.workflow_name); return trigger.label !== "—" ? (
                                <Badge variant="outline" className={cn("h-5 border px-2 text-[10px]", trigger.className)}>
                                  {trigger.label}
                                </Badge>
                              ) : null; })()}
                            </div>
                            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                              <span>{execution.agent_name || "unknown agent"}</span>
                              <span>{formatDuration(execution.duration_ms)}</span>
                              <span>{execution.step_count} steps</span>
                              <span>{execution.total_tokens} tokens</span>
                            </div>
                            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                              <span>{formatCompactDate(execution.started_at)}</span>
                              {execution.run_id && <span className="font-mono text-[10px]">{execution.run_id}</span>}
                            </div>
                            {isSelected && (
                              <div className="mt-3 flex flex-wrap gap-2">
                                <Button variant="outline" size="sm" className="h-7 rounded-lg text-[10px]" onClick={(event) => { event.stopPropagation(); void handleExportJson(execution.id); }}>
                                  JSON
                                </Button>
                                <Button variant="outline" size="sm" className="h-7 rounded-lg text-[10px]" onClick={(event) => { event.stopPropagation(); void handleExportHtml(execution.id); }}>
                                  HTML
                                </Button>
                                <Button variant="outline" size="sm" className="h-7 rounded-lg text-[10px] text-destructive" onClick={(event) => { event.stopPropagation(); void handleDelete(execution.id); }}>
                                  Delete
                                </Button>
                              </div>
                            )}
                          </div>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </ScrollArea>
            </CardContent>
          </Card>
        </div>
        )}

        <div className="flex min-h-0 flex-col gap-3 overflow-hidden">
          {detailLoading && (
            <Card className="flex min-h-0 flex-1 items-center justify-center rounded-[1.75rem] bg-card/55">
              <CardContent className="flex flex-col items-center gap-3 py-16">
                <LoaderCircle className="h-7 w-7 animate-spin text-primary" />
                <p className="text-sm text-muted-foreground">Loading execution detail...</p>
              </CardContent>
            </Card>
          )}

          {!detailLoading && !detail && (
            <Card className="flex min-h-0 flex-1 items-center justify-center rounded-[1.75rem] bg-card/55">
              <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
                <Activity className="h-10 w-10 text-muted-foreground/40" />
                <div>
                  <p className="text-base font-medium text-foreground">Pick an execution to inspect.</p>
                  <p className="mt-1 text-sm text-muted-foreground">The Observatory will show execution health, chronology, logs, LLM/tool activity, and exportable evidence.</p>
                </div>
              </CardContent>
            </Card>
          )}

          {!detailLoading && detail && (
            <>
              <Card className="rounded-[1.75rem] bg-card/55">
                <CardHeader className="pb-3">
                  <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <CardTitle className="text-lg">{detail.workflow_name}</CardTitle>
                        <Badge variant="outline" className={cn("h-5 border px-2 text-[10px] uppercase", statusBadgeClasses(detail.status))}>
                          {detail.status}
                        </Badge>
                        {(() => { const trigger = getTriggerType(detail.triggered_by, detail.workflow_name); return trigger.label !== "\u2014" ? (
                          <Badge variant="outline" className={cn("h-5 border px-2 text-[10px]", trigger.className)}>
                            {trigger.label}
                          </Badge>
                        ) : null; })()}
                        {detail.run_id && <Badge variant="outline" className="font-mono text-[10px]">run {detail.run_id}</Badge>}
                      </div>
                      <CardDescription className="mt-1">
                        {detail.namespace} &middot; {detail.agent_name || "unknown"} &middot; Started {formatDateTime(detail.started_at)}
                      </CardDescription>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button variant="outline" size="sm" className="h-8 rounded-lg text-xs" onClick={() => navigateToResource("workflows", detail.workflow_name)}>
                        <ExternalLink className="mr-1.5 h-3.5 w-3.5" />
                        Workflow
                      </Button>
                      <Button variant="outline" size="sm" className="h-8 rounded-lg text-xs" onClick={() => void handleExportJson(detail.id)}>
                        <Download className="mr-1.5 h-3.5 w-3.5" />
                        JSON
                      </Button>
                      <Button variant="outline" size="sm" className="h-8 rounded-lg text-xs" onClick={() => void handleExportHtml(detail.id)}>
                        <FileText className="mr-1.5 h-3.5 w-3.5" />
                        HTML
                      </Button>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-2xl border border-border/60 bg-background/50 px-4 py-3 text-sm">
                    <span className="flex items-center gap-1.5">
                      <Timer className="h-3.5 w-3.5 text-muted-foreground" />
                      <span className="font-medium text-foreground">{formatDuration(detail.duration_ms)}</span>
                    </span>
                    <span className="flex items-center gap-1.5">
                      <ListTree className="h-3.5 w-3.5 text-muted-foreground" />
                      <span className="font-medium text-foreground">{traceability.completedSteps}/{detail.step_count} steps</span>
                      {traceability.failedSteps > 0 && <span className="text-xs text-destructive">({traceability.failedSteps} failed)</span>}
                    </span>
                    <span className="flex items-center gap-1.5">
                      <BrainCircuit className="h-3.5 w-3.5 text-muted-foreground" />
                      <span className="font-medium text-foreground">{detail.llm_call_count} LLM</span>
                      <span className="text-xs text-muted-foreground">{detail.total_tokens} tok</span>
                    </span>
                    <span className="flex items-center gap-1.5">
                      <Wrench className="h-3.5 w-3.5 text-muted-foreground" />
                      <span className="font-medium text-foreground">{detail.tool_call_count} tools</span>
                    </span>
                    {detail.total_cost_usd != null && detail.total_cost_usd > 0 && (
                      <span className="text-xs text-muted-foreground">{formatCurrency(detail.total_cost_usd)}</span>
                    )}
                  </div>

                  {detail.error_message && (
                    <div className="rounded-2xl border border-destructive/30 bg-destructive/8 p-4">
                      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-destructive">
                        <AlertTriangle className="h-3.5 w-3.5" />
                        Execution Error
                      </div>
                      <pre className="mt-2 whitespace-pre-wrap break-words text-xs text-destructive">{detail.error_message}</pre>
                    </div>
                  )}
                </CardContent>
              </Card>

              <Tabs value={activeTab} onValueChange={setActiveTab} className="min-h-0 flex-1 flex flex-col overflow-hidden">
                <TabsList className="h-auto flex-wrap gap-1 rounded-2xl bg-card/55 p-1 shrink-0">
                  <TabsTrigger value="steps" className="text-xs">Steps</TabsTrigger>
                  <TabsTrigger value="logs" className="text-xs">Logs</TabsTrigger>
                  <TabsTrigger value="insights" className="text-xs">Insights</TabsTrigger>
                  <TabsTrigger value="compare" className="text-xs">Compare</TabsTrigger>
                </TabsList>

                <TabsContent value="steps" className="mt-3 min-h-0 flex-1 overflow-y-auto space-y-3">
                  {/* Analysis summary */}
                  <div className="rounded-2xl border border-border/60 bg-background/50 p-4 text-sm text-foreground">
                    {traceability.analysis}
                    <div className="mt-3 flex flex-wrap gap-2">
                      <AnalysisBadge icon={CheckCircle2} label={`${traceability.completedSteps} completed`} tone="success" />
                      <AnalysisBadge icon={XCircle} label={`${traceability.failedSteps} failed`} tone={traceability.failedSteps > 0 ? "danger" : "neutral"} />
                      <AnalysisBadge icon={AlertTriangle} label={`${traceability.warningEvents} warnings`} tone={traceability.warningEvents > 0 ? "warning" : "neutral"} />
                      <AnalysisBadge icon={FileText} label={`${traceability.artifactEvents} artifacts`} tone="neutral" />
                    </div>
                  </div>

                  {/* Step drilldown */}
                  <Card className="rounded-[1.75rem] bg-card/55">
                    <CardHeader className="pb-3">
                      <CardTitle className="text-sm">Step Drilldown</CardTitle>
                      <CardDescription>Step ordering, durations, failure points, and per-step LLM/tool activity.</CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      {orderedSteps.length === 0 && <p className="text-sm text-muted-foreground">No steps recorded for this execution.</p>}
                      {orderedSteps.map((step) => (
                        <button
                          key={step.id}
                          type="button"
                          onClick={() => {
                            setSelectedStep(step);
                            setStepInspectorOpen(true);
                          }}
                          className="w-full rounded-2xl border border-border/60 bg-background/55 p-4 text-left transition-colors hover:bg-accent/25"
                        >
                          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                            <div className="min-w-0">
                              <div className="flex flex-wrap items-center gap-2">
                                <Badge variant="outline" className={cn("h-5 border px-2 text-[10px] uppercase", statusBadgeClasses(step.status))}>
                                  {step.status}
                                </Badge>
                                <p className="truncate text-sm font-semibold text-foreground">{getStepLabel(step)}</p>
                                {step.step_type && <Badge variant="outline" className="text-[10px]">{step.step_type}</Badge>}
                              </div>
                              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
                                <span>{formatDuration(step.latency_ms)}</span>
                                <span>{step.llm_calls.length} LLM</span>
                                <span>{step.tool_calls.length} tools</span>
                                {step.tokens_used != null && <span>{step.tokens_used} tokens</span>}
                                {step.cost_usd != null && <span>{formatCurrency(step.cost_usd)}</span>}
                              </div>
                            </div>
                            {step.error && (
                              <div className="max-w-xl rounded-xl border border-destructive/20 bg-destructive/8 px-3 py-2 text-xs text-destructive">
                                {step.error}
                              </div>
                            )}
                          </div>
                        </button>
                      ))}
                    </CardContent>
                  </Card>

                  {/* Hot spots */}
                  {traceability.hotSteps.length > 0 && (
                    <Card className="rounded-[1.75rem] bg-card/55">
                      <CardHeader className="pb-3">
                        <CardTitle className="text-sm">Hot Spots</CardTitle>
                        <CardDescription>Longest or busiest steps to inspect first.</CardDescription>
                      </CardHeader>
                      <CardContent className="space-y-3">
                        {traceability.hotSteps.map((step) => (
                          <button
                            key={step.id}
                            type="button"
                            onClick={() => {
                              setSelectedStep(step);
                              setStepInspectorOpen(true);
                            }}
                            className="w-full rounded-2xl border border-border/60 bg-background/60 p-3 text-left transition-colors hover:bg-accent/30"
                          >
                            <div className="flex items-center gap-2">
                              <Badge variant="outline" className={cn("h-5 border px-2 text-[10px] uppercase", statusBadgeClasses(step.status))}>
                                {step.status}
                              </Badge>
                              <span className="truncate text-sm font-medium text-foreground">{getStepLabel(step)}</span>
                            </div>
                            <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                              <span>{formatDuration(step.latency_ms)}</span>
                              <span>{step.llm_calls.length} LLM</span>
                              <span>{step.tool_calls.length} tools</span>
                              {step.step_type && <span>{step.step_type}</span>}
                            </div>
                          </button>
                        ))}
                      </CardContent>
                    </Card>
                  )}

                  {/* Event chronology */}
                  {orderedEvents.length > 0 && (
                    <Card className="rounded-[1.75rem] bg-card/55">
                      <CardHeader className="pb-3">
                        <div className="flex items-center justify-between">
                          <div>
                            <CardTitle className="text-sm">Event Chronology</CardTitle>
                            <CardDescription>{orderedEvents.length} events &middot; {eventGroups.length} types</CardDescription>
                          </div>
                          <div className="flex flex-wrap gap-2">
                            {eventGroups.slice(0, 5).map(([eventType, count]) => (
                              <span key={eventType} className={cn("rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase", EVENT_TONE[eventType] ?? EVENT_TONE.CUSTOM)}>
                                {eventType.replace(/_/g, " ")} {count}
                              </span>
                            ))}
                          </div>
                        </div>
                      </CardHeader>
                      <CardContent>
                        <ExecutionTimeline events={orderedEvents} activeEventId={selectedEventId} onEventClick={(event) => setSelectedEventId(event.id)} />
                      </CardContent>
                    </Card>
                  )}

                  {/* Execution metadata */}
                  <Card className="rounded-[1.75rem] bg-card/55">
                    <CardHeader className="pb-3">
                      <CardTitle className="text-sm">Execution Metadata</CardTitle>
                      <CardDescription>IDs, correlation fields, and log source.</CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-3 text-sm">
                      <MetadataRow label="Execution ID" value={detail.id} mono />
                      <MetadataRow label="Workflow" value={detail.workflow_name} />
                      <MetadataRow label="Run ID" value={detail.run_id ?? "\u2014"} mono />
                      <MetadataRow label="Triggered By" value={detail.triggered_by ?? "\u2014"} />
                      <MetadataRow label="Namespace" value={detail.namespace} />
                      <MetadataRow label="Agent" value={detail.agent_name ?? "\u2014"} />
                      <MetadataRow label="Prompt Tokens" value={detail.prompt_tokens != null ? String(detail.prompt_tokens) : "\u2014"} />
                      <MetadataRow label="Completion Tokens" value={detail.completion_tokens != null ? String(detail.completion_tokens) : "\u2014"} />
                      <MetadataRow label="Log Source" value={deriveRunLogSource(runTrace)} />
                      <MetadataRow label="Trace File" value={detail.trace_file_path ?? "\u2014"} mono />
                    </CardContent>
                  </Card>
                </TabsContent>

                {/* Events tab removed — chronology moved to Steps tab */}

                <TabsContent value="logs" className="mt-3 min-h-0 flex-1 overflow-hidden flex flex-col">
                  <Card className="rounded-[1.75rem] bg-card/55 flex flex-col flex-1 min-h-0 overflow-hidden">
                    <CardHeader className="pb-3">
                      <div className="flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
                        <div>
                          <CardTitle className="text-sm">Worker Logs</CardTitle>
                          <CardDescription>
                            Logs are loaded from the workflow run trace endpoint when a `run_id` is available.
                          </CardDescription>
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                          {runTraceLoading && <Badge variant="outline" className="text-[10px]">Loading logs</Badge>}
                          {!runTraceLoading && runTrace && <Badge variant="outline" className="text-[10px]">{deriveRunLogSource(runTrace)}</Badge>}
                          <CopyButton value={filteredLogLines.join("\n")} className="rounded-lg" />
                        </div>
                      </div>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      <div className="flex flex-wrap items-end gap-2">
                        <Select value={selectedLogStep} onValueChange={setSelectedLogStep}>
                          <SelectTrigger className="h-8 w-48 text-xs">
                            <SelectValue placeholder="Filter logs by step" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="all">All steps</SelectItem>
                            {orderedSteps.filter((s) => s.name || s.id).map((step) => (
                              <SelectItem key={step.id} value={step.name || step.id}>{getStepLabel(step)}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <Select value={logFilterMode} onValueChange={(value) => setLogFilterMode(value as LogFilterMode)}>
                          <SelectTrigger className="h-8 w-36 text-xs">
                            <SelectValue placeholder="Log filter" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="all">All lines</SelectItem>
                            <SelectItem value="activity">Activity</SelectItem>
                            <SelectItem value="errors">Errors</SelectItem>
                            <SelectItem value="tooling">Tooling</SelectItem>
                          </SelectContent>
                        </Select>
                        <div className="relative min-w-[14rem] flex-1">
                          <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                          <Input value={logSearch} onChange={(event) => setLogSearch(event.target.value)} placeholder="Search log lines" className="h-8 pl-9 text-xs" />
                        </div>
                      </div>

                      <div className="flex flex-wrap gap-2">
                        <Badge variant="outline" className="text-[10px]">{filteredLogLines.length}/{normalizedLogLines.length} shown</Badge>
                        <Badge variant="outline" className="text-[10px]">{logStats.activity} activity</Badge>
                        <Badge variant="outline" className="text-[10px]">{logStats.errors} errors</Badge>
                        <Badge variant="outline" className="text-[10px]">{logStats.tooling} tooling</Badge>
                        {runTrace?.pod_name && <Badge variant="outline" className="font-mono text-[10px]">pod {runTrace.pod_name}</Badge>}
                        {runTrace?.worker_job_name && <Badge variant="outline" className="font-mono text-[10px]">job {runTrace.worker_job_name}</Badge>}
                      </div>

                      {(runTraceError || runTraceNotice) && (
                        <div className="rounded-2xl border border-destructive/30 bg-destructive/8 px-3 py-2 text-xs text-destructive">
                          {runTraceError || runTraceNotice}
                        </div>
                      )}

                      {!runTraceError && !runTraceNotice && detail?.run_id && !supportsWorkflowRunLogs && (
                        <div className="rounded-2xl border border-border/60 bg-background/60 px-3 py-2 text-xs text-muted-foreground">
                          This execution is not backed by workflow run history. Worker run logs are unavailable for direct `invoke:*` traces.
                        </div>
                      )}

                      <div className="rounded-2xl border border-border/60 bg-background/50">
                        <ScrollArea className="flex-1 min-h-0">
                          <div className="space-y-1.5 p-3 font-mono text-[11px] leading-relaxed">
                            {!runTraceLoading && filteredLogLines.length === 0 && (
                              <div className="py-12 text-center text-xs text-muted-foreground">
                                {runTrace ? "No log lines match the current filter." : "No worker log stream is available for this execution."}
                              </div>
                            )}
                            {filteredLogLines.map((line, index) => {
                              const parsed = parseLogLine(line);
                              return (
                                <div key={`${index}-${line.slice(0, 24)}`} className={cn("rounded-lg border px-2.5 py-1.5", lineTone(parsed.message, parsed.level))}>
                                  {parsed.level && (
                                    <span className="mr-2 rounded-full border border-current/20 px-1.5 py-0.5 text-[9px] uppercase tracking-wide opacity-70">
                                      {parsed.level}
                                    </span>
                                  )}
                                  <span className="whitespace-pre-wrap break-words">{parsed.message}</span>
                                </div>
                              );
                            })}
                          </div>
                        </ScrollArea>
                      </div>
                    </CardContent>
                  </Card>
                </TabsContent>

                <TabsContent value="insights" className="mt-3 min-h-0 flex-1 overflow-y-auto space-y-3">
                  {/* Aggregate metrics */}
                  <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                    <MetricCard icon={BrainCircuit} label="LLM Calls" value={`${detail.llm_call_count}`} subtitle={`${detail.total_tokens} tokens`} />
                    <MetricCard icon={Wrench} label="Tool Calls" value={`${detail.tool_call_count}`} subtitle={`${traceability.artifactEvents} artifacts`} />
                    <MetricCard icon={BarChart3} label="Trace Coverage" value={`${traceability.coverage}%`} subtitle={`${traceability.eventCount} events`} />
                    <MetricCard icon={Timer} label="Cost" value={formatCurrency(detail.total_cost_usd)} subtitle={detail.prompt_tokens != null ? `${detail.prompt_tokens} prompt / ${detail.completion_tokens ?? 0} completion` : undefined} />
                  </div>

                  {/* LLM calls */}
                  <Card className="rounded-[1.75rem] bg-card/55">
                    <CardHeader className="pb-3">
                      <CardTitle className="text-sm">LLM Calls</CardTitle>
                      <CardDescription>Model usage, token spend, latency, and captured prompt/response previews.</CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      {detail.llm_calls.length === 0 && <p className="text-sm text-muted-foreground">No LLM calls were recorded.</p>}
                      {detail.llm_calls.map((call) => (
                        <button
                          key={call.id}
                          type="button"
                          onClick={() => {
                            setSelectedLLM(call);
                            setLlmViewerOpen(true);
                          }}
                          className="w-full rounded-2xl border border-border/60 bg-background/55 p-4 text-left transition-colors hover:bg-accent/25"
                        >
                          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                            <div className="min-w-0">
                              <div className="flex flex-wrap items-center gap-2">
                                <Badge variant="outline" className="border-violet-500/20 bg-violet-500/10 text-[10px] text-violet-300">LLM</Badge>
                                <p className="truncate text-sm font-semibold text-foreground">{call.model}</p>
                                {call.provider && <Badge variant="outline" className="text-[10px]">{call.provider}</Badge>}
                              </div>
                              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
                                <span>{call.total_tokens} tokens</span>
                                <span>{call.prompt_tokens} prompt</span>
                                <span>{call.completion_tokens} completion</span>
                                <span>{formatDuration(call.latency_ms)}</span>
                                <span>{formatCurrency(call.estimated_cost_usd)}</span>
                              </div>
                            </div>
                            <div className="max-w-xl text-xs text-muted-foreground">
                              <span className="line-clamp-3">{call.response_preview || call.prompt_preview || "No preview available."}</span>
                            </div>
                          </div>
                        </button>
                      ))}
                    </CardContent>
                  </Card>

                  {/* Tool calls */}
                  <Card className="rounded-[1.75rem] bg-card/55">
                    <CardHeader className="pb-3">
                      <CardTitle className="text-sm">Tool Calls</CardTitle>
                      <CardDescription>External actions, arguments, results, and failure surfaces.</CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      {detail.tool_calls.length === 0 && <p className="text-sm text-muted-foreground">No tool calls were recorded.</p>}
                      {detail.tool_calls.map((toolCall) => (
                        <div key={toolCall.id} className="rounded-2xl border border-border/60 bg-background/55 p-4">
                          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                            <div className="min-w-0">
                              <div className="flex flex-wrap items-center gap-2">
                                <Badge variant="outline" className={cn("h-5 border px-2 text-[10px] uppercase", statusBadgeClasses(toolCall.status))}>
                                  {toolCall.status}
                                </Badge>
                                <p className="truncate text-sm font-semibold text-foreground">{toolCall.tool_name}</p>
                              </div>
                              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
                                <span>{formatDuration(toolCall.latency_ms)}</span>
                                <span>{formatDateTime(toolCall.created_at)}</span>
                                {toolCall.step_id && <span className="font-mono">step {toolCall.step_id}</span>}
                              </div>
                            </div>
                            {toolCall.error_message && (
                              <div className="max-w-xl rounded-xl border border-destructive/20 bg-destructive/8 px-3 py-2 text-xs text-destructive">
                                {toolCall.error_message}
                              </div>
                            )}
                          </div>
                          <div className="mt-3 grid gap-3 lg:grid-cols-2">
                            <PreviewPanel title="Args" value={toolCall.args_preview} compact />
                            <PreviewPanel title="Result" value={toolCall.result_preview} compact />
                          </div>
                        </div>
                      ))}
                    </CardContent>
                  </Card>
                </TabsContent>

                <TabsContent value="compare" className="mt-3 min-h-0 flex-1 overflow-y-auto">
                  <Card className="rounded-[1.75rem] bg-card/55">
                    <CardHeader className="pb-3">
                      <CardTitle className="text-sm">Compare Executions</CardTitle>
                      <CardDescription>Contrast latency, step outcomes, and execution shape across two traces.</CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-4">
                      <div className="flex flex-wrap items-center gap-2">
                        <Select value={compareLeftId ?? undefined} onValueChange={(value) => setCompareLeftId(value || null)}>
                          <SelectTrigger className="h-9 w-72 text-xs">
                            <SelectValue placeholder="Left execution" />
                          </SelectTrigger>
                          <SelectContent>
                            {executions.filter((e) => e.id).map((execution) => (
                              <SelectItem key={execution.id} value={execution.id} className="text-xs">
                                {execution.workflow_name} · {execution.status} · {formatCompactDate(execution.started_at)}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <GitCompare className="h-4 w-4 text-muted-foreground" />
                        <Select value={compareRightId ?? undefined} onValueChange={(value) => setCompareRightId(value || null)}>
                          <SelectTrigger className="h-9 w-72 text-xs">
                            <SelectValue placeholder="Right execution" />
                          </SelectTrigger>
                          <SelectContent>
                            {executions.filter((e) => e.id).map((execution) => (
                              <SelectItem key={execution.id} value={execution.id} className="text-xs">
                                {execution.workflow_name} · {execution.status} · {formatCompactDate(execution.started_at)}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>

                      {compareLoading ? (
                        <div className="flex items-center justify-center py-16">
                          <LoaderCircle className="h-6 w-6 animate-spin text-primary" />
                        </div>
                      ) : (
                        <ExecutionDiffView left={compareLeft} right={compareRight} />
                      )}
                    </CardContent>
                  </Card>
                </TabsContent>

                {/* Raw Evidence tab removed — JSON/HTML export buttons in header are sufficient */}
              </Tabs>
            </>
          )}
        </div>
      </div>

      <StepInspector step={selectedStep} open={stepInspectorOpen} onOpenChange={setStepInspectorOpen} />
      <LLMCallViewer llmCall={selectedLLM} open={llmViewerOpen} onOpenChange={setLlmViewerOpen} />
    </div>
  );
}

function MetricCard({
  icon: Icon,
  label,
  value,
  subtitle,
  tone,
}: {
  icon: ComponentType<{ className?: string }>;
  label: string;
  value: string;
  subtitle?: string;
  tone?: string;
}) {
  return (
    <div className={cn("rounded-2xl border border-border/60 bg-background/55 p-4", tone && tone)}>
      <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </div>
      <p className="mt-2 text-base font-semibold text-foreground">{value}</p>
      {subtitle && <p className="mt-1 text-xs text-muted-foreground">{subtitle}</p>}
    </div>
  );
}

function AnalysisBadge({
  icon: Icon,
  label,
  tone,
}: {
  icon: ComponentType<{ className?: string }>;
  label: string;
  tone: "success" | "warning" | "danger" | "neutral";
}) {
  const classes = {
    success: "border-emerald-500/20 bg-emerald-500/10 text-emerald-300",
    warning: "border-amber-500/20 bg-amber-500/10 text-amber-300",
    danger: "border-destructive/20 bg-destructive/10 text-destructive",
    neutral: "border-border/60 bg-background/60 text-muted-foreground",
  }[tone];
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs", classes)}>
      <Icon className="h-3.5 w-3.5" />
      {label}
    </span>
  );
}

function PreviewPanel({ title, value, compact = false }: { title: string; value: string | null | undefined; compact?: boolean }) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h4>
        <CopyButton value={value ?? ""} className="rounded-lg" />
      </div>
      <pre className={cn(
        "overflow-auto rounded-2xl border border-border/60 bg-slate-950 p-3 font-mono text-[11px] leading-relaxed text-slate-100",
        compact ? "max-h-44" : "max-h-72",
      )}>
        {value?.trim() ? value : `No ${title.toLowerCase()} available.`}
      </pre>
    </div>
  );
}

function MetadataRow({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-border/40 pb-2 text-sm last:border-b-0 last:pb-0">
      <span className="text-muted-foreground">{label}</span>
      <span className={cn("text-right text-foreground", mono && "font-mono text-xs")}>{value}</span>
    </div>
  );
}
