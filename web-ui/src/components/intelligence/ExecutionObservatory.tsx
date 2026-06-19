import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import {
  Activity,
  BarChart3,
  BookOpen,
  Bot,
  Braces,
  BrainCircuit,
  CheckCircle2,
  ChevronRight,
  ClipboardCheck,
  Code2,
  Database,
  Download,
  FileCode,
  FileText,
  FlaskConical,
  Gauge,
  GitCompare,
  Globe,
  Lightbulb,
  LoaderCircle,
  Maximize2,
  Minimize2,
  PlayCircle,
  RefreshCw,
  Rocket,
  Search,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Target,
  Terminal,
  TrendingDown,
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
import { Textarea } from "@/components/ui/textarea";
import { useConnection } from "@/contexts/ConnectionContext";
import { useWorkspace } from "@/contexts/WorkspaceContext";
import {
  applyOptimizationCandidate,
  approveOptimizationCandidate,
  createOptimizationStudy,
  createOptimizationTrial,
  exportOptimizationDataset,
  fetchWorkflowRuns,
  exportExecutionHtml,
  exportExecutionJson,
  fetchAgentManifest,
  fetchExecutionDetail,
  fetchOptimizationComparison,
  fetchOptimizationRoi,
  fetchOptimizationStudy,
  fetchWorkflowManifest,
  fetchWorkflowRunTrace,
  generateOptimizationCandidate,
  invokeAgent,
  listAgents,
  listExecutions,
  promoteOptimizationCandidate,
  runOptimizationCandidate,
  type WorkflowRunRecord,
  type WorkflowRunTraceResponse,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  AgentInfo,
  ExecutionListItem,
  ExecutionTrace,
  InvokeResponse,
  LLMCallRecord,
  OptimizationCandidate,
  OptimizationComparison,
  OptimizationComparisonMetric,
  OptimizationManifestDiffSection,
  OptimizationRoi,
  OptimizationStudy,
  StepTrace,
  ToolCallRecord,
} from "@/types";

import { Highlight, type Language } from "prism-react-renderer";
import { KubeSynapseTheme } from "@/components/docs/shared";

import { CopyButton } from "../shared/CopyButton";
import { AnalyticsView } from "../observatory/AnalyticsView";
import { DetailDrawer, type DetailItem } from "../observatory/DetailDrawer";
import { ExecutionBanner } from "../observatory/ExecutionBanner";
import { ExecutionDiffView } from "../observatory/ExecutionDiffView";
import { ExecutionTimeline } from "../observatory/ExecutionTimeline";
import { ExecutionTimelineView } from "../observatory/ExecutionTimelineView";
import { LLMCallViewer } from "../observatory/LLMCallViewer";
import { RunsRail } from "../observatory/RunsRail";
import { LiveActivityStream, useWorkflowActivities } from "./LiveActivityStream";

// ─── Constants ────────────────────────────────────────────────────────────────

type LogFilterMode = "all" | "activity" | "errors" | "tooling";
type ObservatoryTab = "timeline" | "analytics" | "trace" | "optimise" | "logs" | "compare";
type OptimisationScope = "current" | "last6" | "last20";
type OptimisationRunPhaseKey = "prepare" | "study" | "agent" | "candidate" | "roi";
type OptimisationRunPhaseStatus = "pending" | "running" | "success" | "error";
type OptimisationRunPhase = {
  key: OptimisationRunPhaseKey;
  label: string;
  description: string;
  status: OptimisationRunPhaseStatus;
  detail?: string;
};

const OPTIMISE_PROMPT_MAX_CHARS = 120_000;
const OPTIMISE_RUN_PHASE_BLUEPRINT: Array<Omit<OptimisationRunPhase, "status">> = [
  {
    key: "prepare",
    label: "Prepare dossier",
    description: "Load traces, run stats, source manifests, and the optimization contract.",
  },
  {
    key: "study",
    label: "Persist baseline",
    description: "Create the ROI study and server-side bottleneck intelligence.",
  },
  {
    key: "agent",
    label: "Optimizer analysis",
    description: "Invoke the dedicated optimizer agent with the compact run dossier.",
  },
  {
    key: "candidate",
    label: "Generate candidate",
    description: "Parse copied manifests, suffix resources, and enforce contract gates.",
  },
  {
    key: "roi",
    label: "Refresh ROI",
    description: "Load trial state, proof status, and candidate economics.",
  },
];
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

function formatComparisonMetricValue(metric: OptimizationComparisonMetric, value: number): string {
  if (!Number.isFinite(value)) return "--";
  if (metric.value_kind === "duration_ms") return formatDuration(value);
  if (metric.value_kind === "cost_usd") return formatCurrency(value);
  if (metric.value_kind === "tokens") return compactNumber(value).toLocaleString(undefined, { maximumFractionDigits: 1 });
  if (metric.value_kind === "tool_calls") return compactNumber(value).toLocaleString(undefined, { maximumFractionDigits: 1 });
  return compactNumber(value).toLocaleString(undefined, { maximumFractionDigits: 1 });
}

function comparisonMetricSourceLabel(source?: string): string {
  if (source === "paired_trials") return "Actual from paired trial";
  return "Study rollup";
}

function renderManifestDiffRows(rows: OptimizationManifestDiffSection["diff_rows"]) {
  const hasChanges = rows.some((row) => row.type !== "equal");
  const visibleRows = hasChanges
    ? rows.filter((row, index) => (
        row.type !== "equal" ||
        rows.slice(Math.max(0, index - 2), Math.min(rows.length, index + 3)).some((nearby) => nearby.type !== "equal")
      ))
    : rows.slice(0, 80);

  return visibleRows.map((row, index) => {
    const sourceTone = row.type === "delete" || row.type === "replace" ? "bg-red-500/10 text-red-900 dark:text-red-100" : "bg-background/55";
    const candidateTone = row.type === "insert" || row.type === "replace" ? "bg-emerald-500/10 text-emerald-900 dark:text-emerald-100" : "bg-background/55";
    return (
      <div key={`${row.source_line_no ?? "x"}-${row.candidate_line_no ?? "x"}-${index}`} className="grid min-w-[44rem] grid-cols-2 gap-px text-[10px] leading-4">
        <div className={cn("grid grid-cols-[2.5rem_minmax(0,1fr)] gap-2 border-b border-border/25 px-2 py-0.5 font-mono", sourceTone)}>
          <span className="select-none text-right text-muted-foreground">{row.source_line_no ?? ""}</span>
          <span className="whitespace-pre">{row.source}</span>
        </div>
        <div className={cn("grid grid-cols-[2.5rem_minmax(0,1fr)] gap-2 border-b border-border/25 px-2 py-0.5 font-mono", candidateTone)}>
          <span className="select-none text-right text-muted-foreground">{row.candidate_line_no ?? ""}</span>
          <span className="whitespace-pre">{row.candidate}</span>
        </div>
      </div>
    );
  });
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

/** Extract a short, meaningful summary line from the tool call's args_preview. */
function tcLatency(tc: ToolCallRecord): number {
  return tc.latency_ms || tc.duration_ms || 0;
}

function getToolCallSummary(tc: ToolCallRecord): string {
  const name = tc.tool_name.toLowerCase();

  // Prefer tool_args (JSON object from API), fall back to args_preview (string)
  let parsed: Record<string, unknown> | null = null;
  if (tc.tool_args && typeof tc.tool_args === "object" && !Array.isArray(tc.tool_args)) {
    parsed = tc.tool_args as Record<string, unknown>;
  } else if (tc.args_preview) {
    try {
      const p = JSON.parse(tc.args_preview);
      if (typeof p === "object" && p !== null && !Array.isArray(p)) {
        parsed = p as Record<string, unknown>;
      }
    } catch {
      // not JSON
    }
  }

  if (parsed) {
    if (name.includes("skill") && parsed.name) return String(parsed.name);
    if ((name.includes("webfetch") || name.includes("fetch")) && parsed.url) return String(parsed.url);
    if (parsed.filePath) return String(parsed.filePath);
    if (parsed.path) return String(parsed.path);
    if (parsed.pattern) return String(parsed.pattern);
    if (parsed.command) return String(parsed.command).length > 120 ? String(parsed.command).slice(0, 120) + "..." : String(parsed.command);
    if (parsed.file) return String(parsed.file);
    if (parsed.description) return String(parsed.description);
    if (parsed.prompt) return String(parsed.prompt).length > 100 ? String(parsed.prompt).slice(0, 100) + "..." : String(parsed.prompt);
    if (parsed.query) return String(parsed.query);
    const firstStr = Object.values(parsed).find((v) => typeof v === "string" && (v as string).length > 0) as string | undefined;
    if (firstStr) return firstStr.length > 120 ? firstStr.slice(0, 120) + "..." : firstStr;
  }

  // Fallback to raw string
  const raw = tc.args_preview || (tc.tool_args ? JSON.stringify(tc.tool_args) : "");
  if (raw.length > 120) return raw.slice(0, 120) + "...";
  return raw;
}

/** Get a label for the detail field based on tool type. */
function getToolDetailLabel(toolName: string): string {
  const name = toolName.toLowerCase();
  if (name.includes("skill")) return "Skill";
  if (name.includes("webfetch") || name.includes("fetch")) return "URL";
  if (name.includes("search") || name.includes("docs")) return "Query";
  if (name.includes("bash") || name.includes("shell") || name.includes("exec") || name.includes("command")) return "Command";
  if (name.includes("read") || name.includes("glob") || name.includes("grep")) return "Path";
  if (name.includes("apply_patch") || name.includes("edit") || name.includes("write")) return "File";
  if (name.includes("task")) return "Task";
  return "Input";
}

function CompareToolbar({
  executions,
  compareLeftId,
  compareRightId,
  setCompareLeftId,
  setCompareRightId,
}: {
  executions: ExecutionListItem[];
  compareLeftId: string | null;
  compareRightId: string | null;
  setCompareLeftId: (id: string | null) => void;
  setCompareRightId: (id: string | null) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border/50 bg-card/60 px-3 py-2">
      <div className="min-w-0 flex-1">
        <div className="text-xs font-semibold text-foreground">Compare runs</div>
        <div className="text-[10px] text-muted-foreground">Spot duration, step, token, and tool regressions.</div>
      </div>
      <Select value={compareLeftId ?? undefined} onValueChange={(v) => setCompareLeftId(v || null)}>
        <SelectTrigger className="h-8 w-60 text-xs">
          <SelectValue placeholder="Baseline execution" />
        </SelectTrigger>
        <SelectContent>
          {executions.filter((e) => e.id).map((exec) => (
            <SelectItem key={exec.id} value={exec.id} className="text-xs">
              {exec.status} / {formatCompactDate(exec.started_at)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <GitCompare className="h-4 w-4 text-muted-foreground" />
      <Select value={compareRightId ?? undefined} onValueChange={(v) => setCompareRightId(v || null)}>
        <SelectTrigger className="h-8 w-60 text-xs">
          <SelectValue placeholder="Current execution" />
        </SelectTrigger>
        <SelectContent>
          {executions.filter((e) => e.id).map((exec) => (
            <SelectItem key={exec.id} value={exec.id} className="text-xs">
              {exec.status} / {formatCompactDate(exec.started_at)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {executions.length >= 2 && (
        <Button
          variant="outline"
          size="sm"
          className="h-8 text-[11px]"
          onClick={() => {
            setCompareLeftId(executions[1]?.id ?? null);
            setCompareRightId(executions[0]?.id ?? null);
          }}
        >
          Latest vs previous
        </Button>
      )}
    </div>
  );
}

/**
 * Fix raw control characters inside JSON string values that make JSON.parse fail.
 * Replaces unescaped newlines, carriage returns, tabs etc inside string literals.
 */
function fixJsonControlChars(jsonStr: string): string {
  // Replace control characters that appear inside string values with their JSON escapes.
  // We walk the string tracking whether we're inside a JSON string literal.
  let result = "";
  let inString = false;
  let i = 0;
  while (i < jsonStr.length) {
    const ch = jsonStr[i];
    if (inString) {
      if (ch === "\\") {
        // escape sequence — copy it and the next char
        result += ch;
        i++;
        if (i < jsonStr.length) {
          result += jsonStr[i];
        }
      } else if (ch === '"') {
        // end of string
        result += ch;
        inString = false;
      } else if (ch === "\n") {
        result += "\\n";
      } else if (ch === "\r") {
        result += "\\r";
      } else if (ch === "\t") {
        result += "\\t";
      } else if (ch.charCodeAt(0) < 0x20) {
        // other control char
        result += "\\u" + ch.charCodeAt(0).toString(16).padStart(4, "0");
      } else {
        result += ch;
      }
    } else {
      if (ch === '"') {
        inString = true;
      }
      result += ch;
    }
    i++;
  }
  return result;
}

/** Detect if a string looks like a unified diff (patch). */
function isDiffContent(text: string): boolean {
  if (!text) return false;
  const lines = text.split(/\r?\n/).slice(0, 20);
  let diffMarkers = 0;
  for (const line of lines) {
    if (line.startsWith("+") || line.startsWith("-") || line.startsWith("@@") || line.startsWith("***")) {
      diffMarkers++;
    }
  }
  return diffMarkers >= 3;
}

/** GitHub-style diff/patch syntax highlighting. */
function DiffHighlight({ code }: { code: string }) {
  const lines = code.split(/\r?\n/);
  return (
    <pre className="overflow-x-auto text-[10px] leading-relaxed bg-[oklch(0.11_0.005_264)] rounded-md border border-border/40 px-0 py-2 max-h-60 overflow-y-auto font-mono">
      {lines.map((line, i) => {
        let bg = "";
        let textColor = "text-foreground/80";
        if (line.startsWith("+++") || line.startsWith("---")) {
          bg = "bg-blue-500/10";
          textColor = "text-blue-400";
        } else if (line.startsWith("+")) {
          bg = "bg-green-500/10";
          textColor = "text-green-400";
        } else if (line.startsWith("-")) {
          bg = "bg-red-500/10";
          textColor = "text-red-400";
        } else if (line.startsWith("@@")) {
          bg = "bg-purple-500/10";
          textColor = "text-purple-400";
        } else if (line.startsWith("***")) {
          bg = "bg-amber-500/10";
          textColor = "text-amber-400";
        }
        return (
          <div key={i} className={cn("table-row", bg)}>
            <span className="table-cell select-none pr-3 pl-2 text-right text-[9px] text-muted-foreground/40 w-8">{i + 1}</span>
            <span className={cn("table-cell pr-3 whitespace-pre-wrap break-all", textColor)}>{line}</span>
          </div>
        );
      })}
    </pre>
  );
}

/** Syntax-highlighted JSON block. */
function JsonHighlight({ code }: { code: string }) {
  return (
    <Highlight theme={KubeSynapseTheme} code={code} language={"json" as Language}>
      {({ tokens, getLineProps, getTokenProps }) => (
        <pre className="overflow-x-auto text-[10px] leading-relaxed bg-[oklch(0.11_0.005_264)] rounded-md border border-border/40 px-3 py-2 max-h-60 overflow-y-auto font-mono">
          {tokens.map((line, i) => {
            const lineProps = getLineProps({ line, key: i });
            // strip the className key to avoid React warnings about non-standard props on pre
            const { className: _lc, ...rest } = lineProps;
            return (
              <div key={i} {...rest} className="table-row">
                <span className="table-cell select-none pr-3 text-right text-[9px] text-muted-foreground/40 w-8">{i + 1}</span>
                <span className="table-cell">
                  {line.map((token, key) => (
                    <span key={key} {...getTokenProps({ token, key })} />
                  ))}
                </span>
              </div>
            );
          })}
        </pre>
      )}
    </Highlight>
  );
}

/**
 * Attempt to close truncated JSON by appending missing closing brackets/braces.
 * Counts the balance of {, }, [, ] (respecting string boundaries) and
 * appends the needed closers. Returns the closed (and parseable) string.
 */
function tryCloseAndParseJson(partial: string): string | null {
  let openBraces = 0;
  let openBrackets = 0;
  let inString = false;
  let escaped = false;
  for (const ch of partial) {
    if (escaped) { escaped = false; continue; }
    if (ch === "\\") { escaped = true; continue; }
    if (ch === '"') { inString = !inString; continue; }
    if (inString) continue;
    if (ch === "{") openBraces++;
    if (ch === "}") openBraces--;
    if (ch === "[") openBrackets++;
    if (ch === "]") openBrackets--;
  }
  let closing = "";
  if (inString) closing += '"';
  for (let i = 0; i < Math.max(0, openBraces); i++) closing += "}";
  for (let i = 0; i < Math.max(0, openBrackets); i++) closing += "]";
  if (!closing) return null; // balanced — nothing to close
  try {
    JSON.parse(partial + closing);
    return partial + closing;
  } catch {
    return null;
  }
}

/** Visual key-value card for parsed JSON arguments. */
function ArgsCard({ tc }: { tc: ToolCallRecord }) {
  // Prefer tool_args (JSON object from API), fall back to args_preview (string)
  let parsed: Record<string, unknown> | null = null;

  if (tc.tool_args && typeof tc.tool_args === "object" && !Array.isArray(tc.tool_args)) {
    parsed = tc.tool_args as Record<string, unknown>;
  } else if (tc.args_preview) {
    try {
      const p = JSON.parse(tc.args_preview);
      if (typeof p === "object" && p !== null && !Array.isArray(p)) {
        parsed = p as Record<string, unknown>;
      }
    } catch {
      // not JSON — fall through to raw display
    }
  }

  // Raw string fallback
  const rawArgs = tc.args_preview || (tc.tool_args ? JSON.stringify(tc.tool_args, null, 2) : null);

  if (parsed) {
    const entries = Object.entries(parsed);
    if (entries.length === 0) return null;

    const name = tc.tool_name.toLowerCase();

    return (
      <div className="rounded-md border border-border/40 bg-card/50 overflow-hidden">
        <div className="divide-y divide-border/20">
          {entries.map(([key, value]) => {
            const strVal = value == null ? "null" : typeof value === "string" ? value : JSON.stringify(value, null, 2);
            const isLong = strVal.length > 80;
            const isJsonValue = value != null && typeof value === "object";
            // Detect diff/patch content in relevant fields
            const isDiffField = typeof value === "string" && (
              key === "patchText" || key === "patch" || key === "diff" ||
              ((key === "oldString" || key === "newString" || key === "content") && name.includes("edit"))
            );
            const showAsDiff = isDiffField || (isLong && typeof value === "string" && isDiffContent(strVal));

            const isPrimary =
              (name.includes("skill") && key === "name") ||
              ((name.includes("webfetch") || name.includes("fetch")) && key === "url") ||
              ((name.includes("bash") || name.includes("shell") || name.includes("exec") || name.includes("command")) && key === "command") ||
              ((name.includes("read") || name.includes("glob") || name.includes("grep") || name.includes("apply_patch") || name.includes("edit") || name.includes("write")) && (key === "filePath" || key === "path" || key === "file"));

            return (
              <div key={key} className={cn("px-2.5 py-1.5", isPrimary && "bg-primary/5")}>
                <div className="flex items-start gap-3">
                  <span className={cn(
                    "text-[9px] font-semibold uppercase tracking-wide w-16 shrink-0 pt-0.5",
                    isPrimary ? "text-primary" : "text-muted-foreground/60",
                  )}>{key}</span>
                  <span className="text-[10px] flex-1 min-w-0">
                    {isLong ? (
                      showAsDiff ? (
                        <DiffHighlight code={strVal} />
                      ) : isJsonValue ? (
                        <JsonHighlight code={strVal} />
                      ) : (
                        <pre className="text-[10px] font-mono whitespace-pre-wrap break-all bg-muted/30 rounded px-2 py-1 max-h-28 overflow-y-auto">{strVal}</pre>
                      )
                    ) : (
                      <span className={cn(isPrimary && "text-foreground font-medium font-mono", !isPrimary && "text-foreground/70 font-mono")}>{strVal}</span>
                    )}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  // Fallback: syntax-highlight raw text as JSON
  if (rawArgs) {
    return <JsonHighlight code={rawArgs} />;
  }

  return null;
}

/** Visual result preview with truncation, JSON detection, and diff detection. */
function ResultBlock({ tc }: { tc: ToolCallRecord }) {
  const [expanded, setExpanded] = useState(false);

  // Prefer tool_result (JSON object from API), fall back to result_preview (string)
  let displayText = "";
  let isJson = false;
  let isDiff = false;

  const rawResult = tc.tool_result ?? tc.result_preview ?? null;

  if (rawResult != null) {
    if (typeof rawResult === "string") {
      const trimmed = rawResult.trim();
      // Try parsing as JSON — handle truncated data via auto-closing
      if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
        let parsed: unknown = null;
        // Attempt 1: direct parse
        try { parsed = JSON.parse(trimmed); } catch { /* fall through */ }
        // Attempt 2: fix control chars then parse
        if (parsed == null) {
          try {
            const fixed = fixJsonControlChars(trimmed);
            parsed = JSON.parse(fixed);
          } catch { /* fall through */ }
        }
        // Attempt 3: auto-close truncated JSON then parse
        if (parsed == null) {
          const closed = tryCloseAndParseJson(trimmed);
          if (closed) {
            try { parsed = JSON.parse(closed); } catch { /* fall through */ }
          }
        }
        if (parsed != null && typeof parsed === "object") {
          displayText = JSON.stringify(parsed, null, 2);
          isJson = true;
        } else {
          displayText = trimmed;
        }
      } else {
        // Not JSON-like — show as raw text
        displayText = trimmed;
      }
    } else {
      displayText = JSON.stringify(rawResult, null, 2);
      isJson = true;
    }
  }

  if (!displayText) return null;

  // Detect diff/patch content
  if (!isJson && isDiffContent(displayText)) {
    isDiff = true;
  }

  const lines = displayText.split(/\r?\n/);
  const isLong = displayText.length > 300 || lines.length > 12;

  if (!isLong) {
    if (isDiff) return <DiffHighlight code={displayText} />;
    if (isJson) return <JsonHighlight code={displayText} />;
    return (
      <pre className="px-2.5 py-1.5 bg-muted/40 rounded border border-border/30 text-[10px] font-mono text-foreground/80 whitespace-pre-wrap break-all">{displayText}</pre>
    );
  }

  const preview = lines.slice(0, 8).join("\n");

  return (
    <div>
      {isDiff ? (
        <DiffHighlight code={expanded ? displayText : `${preview}\n…`} />
      ) : isJson ? (
        <JsonHighlight code={expanded ? displayText : `${preview}…`} />
      ) : (
        <pre className="px-2.5 py-1.5 bg-muted/40 rounded border border-border/30 rounded-b-none text-[10px] font-mono text-foreground/80 whitespace-pre-wrap break-all">{expanded ? displayText : `${preview}…`}</pre>
      )}
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="w-full px-2.5 py-1 bg-muted/30 rounded border border-t-0 border-border/30 rounded-t-none text-[10px] text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors font-mono"
      >
        {expanded ? "Collapse" : `Show all ${lines.length} lines · ${(displayText.length / 1024).toFixed(1)} KB`}
      </button>
    </div>
  );
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

type TraceRecordKind = "llm" | "tool" | "event";
type TraceKindFilter = "all" | TraceRecordKind;
type TraceStatusFilter = "all" | "completed" | "failed";

interface TraceRecord {
  id: string;
  kind: TraceRecordKind;
  timestamp: string;
  timeMs: number;
  stepId: string | null;
  step: StepTrace | null;
  stepLabel: string;
  actorLabel: string;
  title: string;
  summary: string;
  status: string;
  durationMs?: number | null;
  tokens?: number | null;
  cost?: number | null;
  model?: string | null;
  toolName?: string | null;
  eventType?: string | null;
  searchText: string;
  llm?: LLMCallRecord;
  tool?: ToolCallRecord;
  event?: ExecutionTrace["events"][number];
}

const ALL_FILTER_VALUE = "__all__";

function payloadText(payload: unknown, ...keys: string[]): string | null {
  if (payload == null) return null;
  if (typeof payload === "string") return payload.trim() || null;
  if (typeof payload !== "object" || Array.isArray(payload)) {
    try {
      return JSON.stringify(payload);
    } catch {
      return null;
    }
  }
  const record = payload as Record<string, unknown>;
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) return value.trim();
    if (typeof value === "number" && Number.isFinite(value)) return String(value);
    if (typeof value === "boolean") return String(value);
  }
  try {
    const compact = JSON.stringify(record);
    return compact.length > 180 ? `${compact.slice(0, 180)}...` : compact;
  } catch {
    return null;
  }
}

function normalizedStatus(status?: string | null): string {
  return (status ?? "unknown").toLowerCase();
}

function isFailedStatus(status?: string | null): boolean {
  const s = normalizedStatus(status);
  return s.includes("fail") || s.includes("error") || s.includes("denied") || s.includes("reject");
}

function eventTitle(eventType: string): string {
  return eventType.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, (ch) => ch.toUpperCase());
}

function summarizeEventPayload(payload: Record<string, unknown>): string {
  const direct = payloadText(payload, "message", "error", "status", "tool_name", "model", "decision", "artifact", "path");
  if (direct) return direct;
  const entries = Object.entries(payload).filter(([, value]) => value !== null && value !== undefined);
  if (entries.length === 0) return "No payload captured";
  return entries.slice(0, 3).map(([key, value]) => {
    const rendered = typeof value === "string" ? value : JSON.stringify(value);
    return `${key}: ${rendered.length > 80 ? `${rendered.slice(0, 80)}...` : rendered}`;
  }).join(" · ");
}

function buildStepIndex(steps: StepTrace[]): Map<string, StepTrace> {
  const index = new Map<string, StepTrace>();
  for (const step of steps) {
    if (step.id) index.set(step.id, step);
    if (step.name) index.set(step.name, step);
  }
  return index;
}

function actorForRecord(detail: ExecutionTrace, step: StepTrace | null, payload?: Record<string, unknown>): string {
  return (
    payloadText(payload ?? {}, "agent_name", "agent", "actor", "runtime_kind") ??
    detail.agent_name ??
    step?.step_type ??
    "agent"
  );
}

function stepLabelForRecord(step: StepTrace | null, stepId?: string | null): string {
  if (step) return getStepLabel(step);
  return stepId ? `Step ${stepId}` : "Execution";
}

function recordTimestamp(value: string | null | undefined, fallback: string | null | undefined): string {
  return value || fallback || "";
}

function buildTraceRecords(detail: ExecutionTrace, orderedSteps: StepTrace[], orderedEvents: ExecutionTrace["events"]): TraceRecord[] {
  const stepIndex = buildStepIndex(orderedSteps);
  const fallbackTimestamp = detail.started_at ?? detail.created_at ?? "";
  const records: TraceRecord[] = [];

  for (const call of detail.llm_calls) {
    const step = call.step_id ? stepIndex.get(call.step_id) ?? null : null;
    const timestamp = recordTimestamp(call.created_at, step?.completed_at ?? step?.started_at ?? fallbackTimestamp);
    const tokens = call.total_tokens || call.prompt_tokens + call.completion_tokens;
    const summary = call.response_preview || call.prompt_preview || "No prompt or response preview captured";
    const actorLabel = actorForRecord(detail, step);
    const stepLabel = stepLabelForRecord(step, call.step_id);
    records.push({
      id: `llm:${call.id}`,
      kind: "llm",
      timestamp,
      timeMs: Date.parse(timestamp),
      stepId: call.step_id ?? null,
      step,
      stepLabel,
      actorLabel,
      title: call.model || "LLM call",
      summary,
      status: "completed",
      durationMs: call.latency_ms,
      tokens,
      cost: call.estimated_cost_usd,
      model: call.model,
      searchText: ["llm", call.model, call.provider, stepLabel, actorLabel, summary].filter(Boolean).join(" "),
      llm: call,
    });
  }

  for (const tool of detail.tool_calls) {
    const step = tool.step_id ? stepIndex.get(tool.step_id) ?? null : null;
    const timestamp = recordTimestamp(tool.created_at ?? tool.started_at, step?.completed_at ?? step?.started_at ?? fallbackTimestamp);
    const summary = getToolCallSummary(tool) || tool.error_message || "No tool input captured";
    const actorLabel = actorForRecord(detail, step);
    const stepLabel = stepLabelForRecord(step, tool.step_id);
    records.push({
      id: `tool:${tool.id}`,
      kind: "tool",
      timestamp,
      timeMs: Date.parse(timestamp),
      stepId: tool.step_id ?? null,
      step,
      stepLabel,
      actorLabel,
      title: tool.tool_name || "Tool call",
      summary,
      status: tool.status,
      durationMs: tcLatency(tool),
      toolName: tool.tool_name,
      searchText: ["tool", tool.tool_name, tool.status, stepLabel, actorLabel, summary, tool.error_message].filter(Boolean).join(" "),
      tool,
    });
  }

  for (const event of orderedEvents) {
    const step = event.step_id ? stepIndex.get(event.step_id) ?? null : null;
    const actorLabel = actorForRecord(detail, step, event.payload);
    const stepLabel = stepLabelForRecord(step, event.step_id);
    const status = payloadText(event.payload, "status", "severity") ?? (event.event_type.includes("FAILED") || event.event_type === "ERROR" ? "failed" : "event");
    const summary = summarizeEventPayload(event.payload);
    records.push({
      id: `event:${event.id}`,
      kind: "event",
      timestamp: event.timestamp,
      timeMs: Date.parse(event.timestamp),
      stepId: event.step_id ?? null,
      step,
      stepLabel,
      actorLabel,
      title: eventTitle(event.event_type),
      summary,
      status,
      eventType: event.event_type,
      searchText: ["event", event.event_type, status, stepLabel, actorLabel, summary].filter(Boolean).join(" "),
      event,
    });
  }

  return records.sort((a, b) => {
    const aTime = Number.isFinite(a.timeMs) ? a.timeMs : Number.MAX_SAFE_INTEGER;
    const bTime = Number.isFinite(b.timeMs) ? b.timeMs : Number.MAX_SAFE_INTEGER;
    if (aTime !== bTime) return aTime - bTime;
    return a.id.localeCompare(b.id);
  });
}

function traceKindClasses(kind: TraceRecordKind): string {
  if (kind === "llm") return "border-violet-500/40 bg-violet-500/8 text-violet-700 dark:text-violet-300";
  if (kind === "tool") return "border-sky-500/40 bg-sky-500/8 text-sky-700 dark:text-sky-300";
  return "border-slate-500/30 bg-slate-500/8 text-slate-700 dark:text-slate-300";
}

function statusTextClasses(status: string): string {
  if (isFailedStatus(status)) return "text-red-500";
  if (normalizedStatus(status).includes("completed") || normalizedStatus(status).includes("success")) return "text-emerald-600 dark:text-emerald-400";
  return "text-muted-foreground";
}

function createOptimiseRunPhases(): OptimisationRunPhase[] {
  return OPTIMISE_RUN_PHASE_BLUEPRINT.map((phase) => ({ ...phase, status: "pending" }));
}

type OptimisationPacket = {
  generated_at: string;
  namespace: string;
  workflow_name: string;
  selected_scope: OptimisationScope;
  selected_agent: string | null;
  objective: string[];
  guardrails: string[];
  current_execution: Record<string, unknown>;
  source_manifests: {
    workflow: Record<string, unknown> | null;
    agent_refs: string[];
    agents: Record<string, Record<string, unknown>>;
    primary_agent: Record<string, unknown> | null;
  };
  deployment_access_model: {
    current_run_mode: string;
    apply_allowed_in_this_run: boolean;
    required_for_apply: string[];
    least_privilege_notes: string[];
  };
  run_intelligence: Record<string, unknown>;
  run_history: Array<Record<string, unknown>>;
  opportunity_map: Array<Record<string, unknown>>;
  step_metrics: Array<Record<string, unknown>>;
  trace_details: Array<Record<string, unknown>>;
};

function optimisationScopeLimit(scope: OptimisationScope): number {
  if (scope === "current") return 1;
  if (scope === "last6") return 6;
  return 20;
}

function compactNumber(value?: number | null): number {
  return value != null && Number.isFinite(value) ? value : 0;
}

function averageNumber(values: number[]): number {
  const usable = values.filter((value) => Number.isFinite(value));
  if (usable.length === 0) return 0;
  return usable.reduce((sum, value) => sum + value, 0) / usable.length;
}

function percentileNumber(values: number[], percentile: number): number {
  const usable = values.filter((value) => Number.isFinite(value)).sort((a, b) => a - b);
  if (usable.length === 0) return 0;
  const index = Math.min(usable.length - 1, Math.max(0, Math.ceil((percentile / 100) * usable.length) - 1));
  return usable[index];
}

function stepMatchesId(step: StepTrace, id?: string | null): boolean {
  return Boolean(id && (step.id === id || step.name === id));
}

function callsForStep<T extends { step_id?: string | null }>(step: StepTrace, calls: T[]): T[] {
  return calls.filter((call) => stepMatchesId(step, call.step_id));
}

function topEntry(items: string[]): { name: string; count: number } | null {
  const counts = new Map<string, number>();
  for (const item of items) {
    if (!item.trim()) continue;
    counts.set(item, (counts.get(item) ?? 0) + 1);
  }
  const entries = Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
  return entries.length > 0 ? { name: entries[0][0], count: entries[0][1] } : null;
}

function maxEventGapMs(events: ExecutionTrace["events"]): number {
  const times = events
    .map((event) => new Date(event.timestamp).getTime())
    .filter((time) => Number.isFinite(time))
    .sort((a, b) => a - b);
  let maxGap = 0;
  for (let index = 1; index < times.length; index += 1) {
    maxGap = Math.max(maxGap, times[index] - times[index - 1]);
  }
  return maxGap;
}

function compactPreview(value?: string | null, max = 480): string | null {
  if (!value) return null;
  const normalized = value.replace(/\s+/g, " ").trim();
  return normalized.length > max ? `${normalized.slice(0, max)}...` : normalized;
}

function isReadyAgent(agent: AgentInfo): boolean {
  return agent.status.toLowerCase() === "ready";
}

function isOptimiserAgentCandidate(agent: AgentInfo): boolean {
  const haystack = `${agent.name} ${agent.model} ${agent.runtime_kind ?? ""}`.toLowerCase();
  return (
    haystack.includes("optimizer") ||
    haystack.includes("optimiser") ||
    haystack.includes("optimization") ||
    haystack.includes("optimisation") ||
    haystack.includes("roi") ||
    haystack.includes("tuner") ||
    haystack.includes("workflow-lab") ||
    haystack.includes("cost-lab")
  );
}

function chooseDefaultOptimiserAgent(agents: AgentInfo[], currentWorkflowAgentName?: string | null): AgentInfo | null {
  const readyAgents = agents.filter(isReadyAgent);
  const orderedAgents = [...readyAgents, ...agents.filter((agent) => !readyAgents.includes(agent))];
  const dedicatedOptimiser =
    readyAgents.find(isOptimiserAgentCandidate) ??
    orderedAgents.find(isOptimiserAgentCandidate);
  if (dedicatedOptimiser) return dedicatedOptimiser;

  const nonWorkflowReadyOpencode = readyAgents.find(
    (agent) => agent.name !== currentWorkflowAgentName && (agent.runtime_kind ?? "opencode") === "opencode",
  );
  if (nonWorkflowReadyOpencode) return nonWorkflowReadyOpencode;

  const nonWorkflowReady = readyAgents.find((agent) => agent.name !== currentWorkflowAgentName);
  if (nonWorkflowReady) return nonWorkflowReady;

  return readyAgents[0] ?? agents[0] ?? null;
}

function extractWorkflowAgentRefs(manifest: Record<string, unknown> | null): string[] {
  const spec = manifest?.spec;
  if (!spec || typeof spec !== "object" || Array.isArray(spec)) return [];
  const steps = (spec as Record<string, unknown>).steps;
  if (!Array.isArray(steps)) return [];
  const refs = new Set<string>();
  for (const item of steps) {
    if (!item || typeof item !== "object" || Array.isArray(item)) continue;
    const ref = (item as Record<string, unknown>).agentRef;
    if (typeof ref === "string" && ref.trim()) refs.add(ref.trim());
  }
  return [...refs];
}

function buildOptimisationStepMetrics(detail: ExecutionTrace, orderedSteps: StepTrace[], orderedEvents: ExecutionTrace["events"]) {
  return orderedSteps.map((step) => {
    const llmCalls = step.llm_calls.length > 0 ? step.llm_calls : callsForStep(step, detail.llm_calls);
    const toolCalls = step.tool_calls.length > 0 ? step.tool_calls : callsForStep(step, detail.tool_calls);
    const eventCount = orderedEvents.filter((event) => stepMatchesId(step, event.step_id)).length;
    const tokens = compactNumber(step.tokens_used) || llmCalls.reduce((sum, call) => sum + compactNumber(call.total_tokens), 0);
    const cost = compactNumber(step.cost_usd) || llmCalls.reduce((sum, call) => sum + compactNumber(call.cost_usd ?? call.estimated_cost_usd), 0);
    const toolNames = Array.from(new Set(toolCalls.map((call) => call.tool_name).filter(Boolean)));
    const models = Array.from(new Set(llmCalls.map((call) => call.model).filter(Boolean)));
    const issues = [
      compactNumber(step.latency_ms) > 60_000 ? "slow_step" : null,
      toolCalls.length > 4 ? "tool_churn" : null,
      tokens > 8000 ? "token_pressure" : null,
      step.error || isFailedStatus(step.status) ? "failure_risk" : null,
    ].filter(Boolean);
    return {
      id: step.id,
      name: step.name,
      label: getStepLabel(step),
      type: step.step_type ?? "agent",
      status: step.status,
      duration_ms: compactNumber(step.latency_ms),
      llm_calls: llmCalls.length,
      tool_calls: toolCalls.length,
      events: eventCount,
      tokens,
      cost_usd: cost > 0 ? Number(cost.toFixed(6)) : 0,
      models,
      tools: toolNames,
      issues,
      input_preview: compactPreview(step.input_preview, 360),
      output_preview: compactPreview(step.output_preview, 360),
    };
  });
}

function buildOptimisationPacket({
  detail,
  orderedSteps,
  orderedEvents,
  executions,
  scopedDetails,
  workflowManifest,
  agentManifests,
  namespace,
  workflowName,
  selectedAgent,
  scope,
}: {
  detail: ExecutionTrace;
  orderedSteps: StepTrace[];
  orderedEvents: ExecutionTrace["events"];
  executions: ExecutionListItem[];
  scopedDetails: ExecutionTrace[];
  workflowManifest: Record<string, unknown> | null;
  agentManifests: Record<string, Record<string, unknown>>;
  namespace: string;
  workflowName: string;
  selectedAgent: string | null;
  scope: OptimisationScope;
}): OptimisationPacket {
  const scopeLimit = optimisationScopeLimit(scope);
  const details = scopedDetails.length > 0 ? scopedDetails.slice(0, scopeLimit) : [detail];
  const stepMetrics = buildOptimisationStepMetrics(detail, orderedSteps, orderedEvents);
  const slowestStep = [...stepMetrics].sort((a, b) => Number(b.duration_ms) - Number(a.duration_ms))[0] ?? null;
  const topTool = topEntry(detail.tool_calls.map((call) => call.tool_name));
  const topModel = topEntry(detail.llm_calls.map((call) => call.model));
  const failedRuns = executions.filter((execution) => isFailedStatus(execution.status)).length;
  const medianDurationMs = (() => {
    const durations = executions.map((execution) => compactNumber(execution.duration_ms)).filter((value) => value > 0).sort((a, b) => a - b);
    if (durations.length === 0) return 0;
    return durations[Math.floor(durations.length / 2)];
  })();
  const eventGapMs = maxEventGapMs(orderedEvents);
  const currentDurationMs = compactNumber(detail.duration_ms);
  const workflowAgentRefs = extractWorkflowAgentRefs(workflowManifest);
  const agentRefs = workflowAgentRefs.length > 0 ? workflowAgentRefs : Object.keys(agentManifests);
  const primaryAgent =
    (detail.agent_name && agentManifests[detail.agent_name]) ||
    agentManifests[agentRefs[0]] ||
    null;
  const opportunityMap = [
    {
      label: "Latency bottleneck",
      signal: slowestStep ? `${slowestStep.label} at ${formatDuration(Number(slowestStep.duration_ms))}` : "No step timing",
      data: slowestStep,
      recommendation: "Inspect whether the slowest step is waiting on tools, repeating planning, or doing work that can move earlier or run in parallel.",
    },
    {
      label: "Token pressure",
      signal: `${detail.total_tokens.toLocaleString()} tokens, ${detail.llm_call_count} LLM calls`,
      data: {
        prompt_tokens: detail.prompt_tokens ?? 0,
        completion_tokens: detail.completion_tokens ?? 0,
        cache_read_tokens: detail.cache_read_tokens ?? 0,
        cache_write_tokens: detail.cache_write_tokens ?? 0,
        reasoning_tokens: detail.reasoning_tokens ?? 0,
        top_model: topModel,
      },
      recommendation: "Find prompt sections that can become persistent instructions, reusable files, cached context, or smaller step-specific prompts.",
    },
    {
      label: "Tool churn",
      signal: `${detail.tool_call_count} tool calls${topTool ? `, top tool ${topTool.name} x${topTool.count}` : ""}`,
      data: { top_tool: topTool, tools: Array.from(new Set(detail.tool_calls.map((call) => call.tool_name))) },
      recommendation: "Collapse repeated reads/writes, batch related lookups, and move deterministic checks out of LLM planning loops.",
    },
    {
      label: "Run variance",
      signal: medianDurationMs > 0 ? `${formatDuration(currentDurationMs)} current vs ${formatDuration(medianDurationMs)} median` : "Not enough history",
      data: { failed_runs: failedRuns, loaded_runs: executions.length, max_event_gap_ms: eventGapMs },
      recommendation: "Compare recent executions for unstable steps, long quiet gaps, or failure-prone handoffs before changing contracts.",
    },
  ];
  const historyDurations = details.map((trace) => compactNumber(trace.duration_ms)).filter((value) => value > 0);
  const historyTokens = details.map((trace) => compactNumber(trace.total_tokens)).filter((value) => value > 0);
  const historyCosts = details.map((trace) => compactNumber(trace.total_cost_usd)).filter((value) => value > 0);
  const historyToolCalls = details.flatMap((trace) => trace.tool_calls);
  const historyLlmCalls = details.flatMap((trace) => trace.llm_calls);
  const historySteps = details.flatMap((trace) => trace.steps.map((step) => ({
    run_id: trace.run_id,
    execution_id: trace.id,
    step_name: step.name,
    step_type: step.step_type ?? "agent",
    status: step.status,
    duration_ms: compactNumber(step.latency_ms),
    tokens: compactNumber(step.tokens_used) || step.llm_calls.reduce((sum, call) => sum + compactNumber(call.total_tokens), 0),
    llm_calls: step.llm_calls.length,
    tool_calls: step.tool_calls.length,
    input_preview: compactPreview(step.input_preview, 240),
    output_preview: compactPreview(step.output_preview, 240),
  })));
  const slowestHistoryStep = [...historySteps].sort((a, b) => b.duration_ms - a.duration_ms)[0] ?? null;
  const repeatedToolGroups = new Map<string, number>();
  for (const call of historyToolCalls) {
    const args = compactPreview(call.args_preview ?? payloadText(call.tool_args ?? {}), 180) ?? "";
    const key = `${call.tool_name}:${args}`;
    repeatedToolGroups.set(key, (repeatedToolGroups.get(key) ?? 0) + 1);
  }
  const repeatedToolArgGroups = Array.from(repeatedToolGroups.values()).filter((count) => count > 1).length;
  const successfulHistoryRuns = details.filter((trace) => !isFailedStatus(trace.status)).length;
  const failedHistoryRuns = details.length - successfulHistoryRuns;

  return {
    generated_at: new Date().toISOString(),
    namespace,
    workflow_name: workflowName,
    selected_scope: scope,
    selected_agent: selectedAgent,
    objective: [
      "Reduce wall-clock time for the selected workflow.",
      "Reduce prompt, completion, cache, and reasoning token use.",
      "Reduce unnecessary tool calls and repeated context loading.",
      "Preserve the workflow contract, output schema, artifacts, and step handoffs.",
    ],
    guardrails: [
      "Do not mutate files, workflow definitions, cluster resources, or credentials in this analysis run.",
      "Return an optimized copy of the Kubernetes manifests, not an in-place patch.",
      "Name optimized resources with an explicit suffix such as -opt or -candidate and preserve labels needed for ownership/audit.",
      "Applying or running optimized manifests requires a separate admin-created deployment-capable agent with least-privilege RBAC.",
      "Call out contract-breaking changes explicitly and provide migration notes.",
      "Prefer lower-risk prompt, context, caching, batching, and routing improvements before structural rewrites.",
    ],
    current_execution: {
      id: detail.id,
      run_id: detail.run_id,
      status: detail.status,
      agent_name: detail.agent_name,
      duration_ms: detail.duration_ms,
      started_at: detail.started_at,
      completed_at: detail.completed_at,
      steps: detail.step_count,
      llm_calls: detail.llm_call_count,
      tool_calls: detail.tool_call_count,
      total_tokens: detail.total_tokens,
      prompt_tokens: detail.prompt_tokens ?? 0,
      completion_tokens: detail.completion_tokens ?? 0,
      cache_read_tokens: detail.cache_read_tokens ?? 0,
      cache_write_tokens: detail.cache_write_tokens ?? 0,
      reasoning_tokens: detail.reasoning_tokens ?? 0,
      total_cost_usd: detail.total_cost_usd ?? null,
      input_preview: compactPreview(detail.input_preview, 600),
      output_preview: compactPreview(detail.output_preview, 600),
      error_message: detail.error_message ?? null,
    },
    source_manifests: {
      workflow: workflowManifest,
      agent_refs: agentRefs,
      agents: agentManifests,
      primary_agent: primaryAgent,
    },
    deployment_access_model: {
      current_run_mode: "analysis_only",
      apply_allowed_in_this_run: false,
      required_for_apply: [
        "Admin-created optimisation/deployment agent",
        "Namespace-scoped get/list/watch/create/patch/delete only for AIAgent and AgentWorkflow resources plus required ConfigMaps/Secrets by name",
        "Explicit approval before kubectl apply, trigger, or cleanup",
        "Audit event linking source execution, candidate manifests, selected agent, and user",
      ],
      least_privilege_notes: [
        "Normal optimisation agents should read traces and manifests only.",
        "Deployment-capable agents should be visually marked as elevated on agent cards.",
        "Candidate resources should be deployed as copies and cleaned up after comparison runs.",
      ],
    },
    run_intelligence: {
      title: "Workflow run intelligence dossier",
      sample: {
        trace_count: details.length,
        successful_runs: successfulHistoryRuns,
        failed_runs: failedHistoryRuns,
        success_rate: details.length > 0 ? Number((successfulHistoryRuns / details.length).toFixed(3)) : 0,
        selected_scope: scope,
      },
      economics: {
        avg_duration_ms: Math.round(averageNumber(historyDurations)),
        p95_duration_ms: Math.round(percentileNumber(historyDurations, 95)),
        avg_tokens: Math.round(averageNumber(historyTokens)),
        p95_tokens: Math.round(percentileNumber(historyTokens, 95)),
        avg_cost_usd: Number(averageNumber(historyCosts).toFixed(6)),
        total_tokens: details.reduce((sum, trace) => sum + compactNumber(trace.total_tokens), 0),
        total_llm_calls: historyLlmCalls.length,
        total_tool_calls: historyToolCalls.length,
        cache_read_tokens: details.reduce((sum, trace) => sum + compactNumber(trace.cache_read_tokens), 0),
        cache_write_tokens: details.reduce((sum, trace) => sum + compactNumber(trace.cache_write_tokens), 0),
      },
      bottlenecks: {
        slowest_step: slowestHistoryStep,
        top_model: topEntry(historyLlmCalls.map((call) => call.model)),
        top_tool: topEntry(historyToolCalls.map((call) => call.tool_name)),
        repeated_tool_argument_groups: repeatedToolArgGroups,
        max_current_event_gap_ms: eventGapMs,
      },
      candidate_contract: {
        source_workflow_is_read_only: true,
        must_create_candidate_copy: true,
        allowed_scope: ["prompt", "model routing", "context trimming", "cache hints", "tool-use instructions", "timeouts", "batching guidance"],
        forbidden_scope: ["in-place workflow edits", "step add/remove/reorder", "step type changes", "secret/env expansion", "privilege expansion"],
        preserve: ["step names", "step order", "step types", "agent handoffs", "output artifacts", "schemas", "workspace paths"],
      },
      manifest_inventory: {
        workflow_loaded: Boolean(workflowManifest),
        agent_refs: agentRefs,
        loaded_agent_manifests: Object.keys(agentManifests),
      },
    },
    run_history: executions.slice(0, scopeLimit).map((execution) => ({
      id: execution.id,
      run_id: execution.run_id,
      status: execution.status,
      agent_name: execution.agent_name,
      started_at: execution.started_at,
      completed_at: execution.completed_at,
      duration_ms: execution.duration_ms,
      step_count: execution.step_count,
      llm_calls: execution.llm_call_count,
      tool_calls: execution.tool_call_count,
      total_tokens: execution.total_tokens,
      cache_read_tokens: execution.cache_read_tokens ?? 0,
      cache_write_tokens: execution.cache_write_tokens ?? 0,
      reasoning_tokens: execution.reasoning_tokens ?? 0,
      total_cost_usd: execution.total_cost_usd ?? null,
    })),
    opportunity_map: opportunityMap,
    step_metrics: stepMetrics,
    trace_details: details.map((trace) => ({
      id: trace.id,
      run_id: trace.run_id,
      status: trace.status,
      duration_ms: trace.duration_ms,
      total_tokens: trace.total_tokens,
      llm_call_count: trace.llm_call_count,
      tool_call_count: trace.tool_call_count,
      event_count: trace.events.length,
      steps: trace.steps.map((step) => ({
        id: step.id,
        name: step.name,
        type: step.step_type,
        status: step.status,
        duration_ms: step.latency_ms,
        tokens: step.tokens_used ?? step.llm_calls.reduce((sum, call) => sum + compactNumber(call.total_tokens), 0),
        llm_calls: step.llm_calls.length,
        tool_calls: step.tool_calls.length,
        input_preview: compactPreview(step.input_preview, 300),
        output_preview: compactPreview(step.output_preview, 300),
      })),
      llm_calls: trace.llm_calls.map((call) => ({
        id: call.id,
        step_id: call.step_id,
        model: call.model,
        provider: call.provider,
        latency_ms: call.latency_ms,
        prompt_tokens: call.prompt_tokens,
        completion_tokens: call.completion_tokens,
        cache_read_tokens: call.cache_read_tokens ?? 0,
        cache_write_tokens: call.cache_write_tokens ?? 0,
        reasoning_tokens: call.reasoning_tokens ?? 0,
        total_tokens: call.total_tokens,
        cost_usd: call.cost_usd ?? call.estimated_cost_usd ?? null,
        prompt_preview: compactPreview(call.prompt_preview, 420),
        response_preview: compactPreview(call.response_preview, 420),
      })),
      tool_calls: trace.tool_calls.map((call) => ({
        id: call.id,
        step_id: call.step_id,
        tool_name: call.tool_name,
        status: call.status,
        latency_ms: call.latency_ms,
        duration_ms: call.duration_ms,
        args_preview: compactPreview(call.args_preview ?? payloadText(call.tool_args ?? {}), 360),
        result_preview: compactPreview(call.result_preview ?? payloadText(call.tool_result), 360),
        error_message: call.error_message ?? null,
      })),
      events: trace.events.slice(0, 80).map((event) => ({
        id: event.id,
        step_id: event.step_id,
        type: event.event_type,
        timestamp: event.timestamp,
        summary: summarizeEventPayload(event.payload),
      })),
    })),
  };
}

function compactStringForOptimizer(value: string, max = 420): string {
  const redacted = value.replace(/\b(sk-[A-Za-z0-9_-]{8,}|Bearer\s+[A-Za-z0-9._-]{12,})\b/g, "[REDACTED]");
  const normalized = redacted.replace(/\s+/g, " ").trim();
  return normalized.length > max ? `${normalized.slice(0, max)}...` : normalized;
}

function compactUnknownForOptimizer(value: unknown, maxString = 420, maxArray = 40, depth = 0): unknown {
  if (value == null) return value;
  if (typeof value === "string") return compactStringForOptimizer(value, maxString);
  if (typeof value === "number" || typeof value === "boolean") return value;
  if (depth > 6) return "[nested payload omitted]";
  if (Array.isArray(value)) {
    return value.slice(0, maxArray).map((item) => compactUnknownForOptimizer(item, maxString, maxArray, depth + 1));
  }
  if (typeof value === "object") {
    const result: Record<string, unknown> = {};
    for (const [key, nested] of Object.entries(value as Record<string, unknown>)) {
      if (/(api[_-]?key|token|secret|password|credential|authorization)/i.test(key)) {
        result[key] = "[REDACTED]";
      } else {
        result[key] = compactUnknownForOptimizer(nested, maxString, maxArray, depth + 1);
      }
    }
    return result;
  }
  return String(value);
}

function compactManifestForOptimizer(manifest: Record<string, unknown> | null): Record<string, unknown> | null {
  if (!manifest) return null;
  const metadata = manifest.metadata && typeof manifest.metadata === "object" && !Array.isArray(manifest.metadata)
    ? manifest.metadata as Record<string, unknown>
    : {};
  const spec = manifest.spec && typeof manifest.spec === "object" && !Array.isArray(manifest.spec)
    ? manifest.spec as Record<string, unknown>
    : {};
  return {
    apiVersion: manifest.apiVersion,
    kind: manifest.kind,
    metadata: compactUnknownForOptimizer(
      {
        name: metadata.name,
        namespace: metadata.namespace,
        labels: metadata.labels,
        annotations: metadata.annotations,
      },
      180,
      20,
    ) as Record<string, unknown>,
    spec: compactUnknownForOptimizer(spec, 700, 30) as Record<string, unknown>,
  };
}

function compactTraceForOptimizer(trace: Record<string, unknown>): Record<string, unknown> {
  return {
    ...(compactUnknownForOptimizer(trace, 260, 24) as Record<string, unknown>),
    steps: Array.isArray(trace.steps)
      ? trace.steps.slice(0, 30).map((step) => compactUnknownForOptimizer(step, 260, 16))
      : [],
    llm_calls: Array.isArray(trace.llm_calls)
      ? trace.llm_calls.slice(0, 40).map((call) => compactUnknownForOptimizer(call, 220, 12))
      : [],
    tool_calls: Array.isArray(trace.tool_calls)
      ? trace.tool_calls.slice(0, 60).map((call) => compactUnknownForOptimizer(call, 220, 12))
      : [],
    events: Array.isArray(trace.events)
      ? trace.events.slice(0, 40).map((event) => compactUnknownForOptimizer(event, 220, 12))
      : [],
  };
}

function buildCompactOptimisationPacket(packet: OptimisationPacket): OptimisationPacket {
  const compactAgents = Object.fromEntries(
    Object.entries(packet.source_manifests.agents).map(([name, manifest]) => [
      name,
      compactManifestForOptimizer(manifest) ?? {},
    ]),
  );
  return {
    ...packet,
    current_execution: compactUnknownForOptimizer(packet.current_execution, 360, 20) as Record<string, unknown>,
    run_intelligence: compactUnknownForOptimizer(packet.run_intelligence, 360, 24) as Record<string, unknown>,
    source_manifests: {
      workflow: compactManifestForOptimizer(packet.source_manifests.workflow),
      agent_refs: packet.source_manifests.agent_refs.slice(0, 20),
      agents: compactAgents,
      primary_agent: compactManifestForOptimizer(packet.source_manifests.primary_agent),
    },
    run_history: packet.run_history.slice(0, 10).map((run) => compactUnknownForOptimizer(run, 220, 12) as Record<string, unknown>),
    opportunity_map: packet.opportunity_map.slice(0, 8).map((item) => compactUnknownForOptimizer(item, 320, 12) as Record<string, unknown>),
    step_metrics: packet.step_metrics.slice(0, 30).map((item) => compactUnknownForOptimizer(item, 260, 16) as Record<string, unknown>),
    trace_details: packet.trace_details.slice(0, 8).map(compactTraceForOptimizer),
  };
}

function buildOptimisationPromptBody(packet: OptimisationPacket, compacted: boolean): string {
  return [
    "You are a senior AI workflow optimisation engineer for KubeSynapse.",
    "",
    "Goal: analyse the provided execution traces and Kubernetes manifests, then propose an optimized copy of the workflow and agent manifests that reduces latency, token spend, tool churn, and failure risk while preserving the workflow contract.",
    "Think like an enterprise workflow ROI engineer: every proposed change must have an evidence source, an expected metric impact, a contract-risk assessment, and a safe trial plan.",
    "",
    "Rules:",
    "- Do not modify files, workflow definitions, cluster resources, credentials, or external systems.",
    "- Treat this as an analysis-only optimisation review.",
    "- Never edit the source workflow in place. Generate a candidate copy of the Kubernetes manifests and explain the diff.",
    "- Use the source workflow and agent names in proposed manifest metadata; the gateway will create suffixed copied resources and rewrite agentRefs safely.",
    "- If a test-run loop is useful, describe the loop and required permissions, but do not run kubectl or apply anything.",
    "- Any apply/run capability must be handled by a separate admin-created agent with least-privilege Kubernetes RBAC and explicit user approval.",
    "- Preserve existing step outputs, artifact paths, schemas, handoff semantics, and security boundaries unless you explicitly mark a breaking change and provide migration steps.",
    "- Do not add, remove, reorder, merge, split, or change the type of workflow steps in v1.",
    "- Prefer prompt/context/tool-use improvements before proposing structural rewrites.",
    "- Preserve the source agents' provider and model exactly in v1; do not route to a different model family.",
    "- Treat the run history as an optimization dataset: compare step duration, token count, LLM calls, tool calls, repeated tool arguments, cache use, retries, quiet gaps, and output quality signals.",
    "- Optimize only changes that can be verified by baseline-vs-candidate trial runs. If quality cannot be machine-verified, require human review.",
    "- Predict both global savings and step-level regression risks. A candidate that wins globally but slows one step must flag that step for review.",
    "- Design the candidate so the ROI Lab can compare actual paired-trial deltas against your expected_metric_delta without manual interpretation.",
    "",
    "Candidate manifest output contract:",
    "- Include a fenced YAML block headed `candidate_manifest_bundle` with AgentWorkflow and relevant AIAgent documents.",
    "- The candidate_manifest_bundle may change prompts, runtime hints, context trimming, caching hints, tool-use instructions, timeouts, and batching guidance.",
    "- The candidate_manifest_bundle must preserve step names, step order, step types, agent handoffs, output artifacts, schemas, and workspace paths.",
    "- Do not introduce new secret, env, envFrom, valueFrom, ServiceAccount, Role, RoleBinding, ClusterRole, ClusterRoleBinding, or external credential references.",
    "- Keep metadata names as the source names in your YAML. The gateway creates suffixed copied resources and rewrites agentRefs.",
    "",
    "Required machine-readable blocks:",
    "- Include a fenced JSON block headed `roi_hypothesis` with keys: expected_metric_delta, confidence, evidence_execution_ids, target_steps, target_tools, quality_gate, rollback_plan.",
    "- expected_metric_delta must use these keys when applicable: duration_saved_percent, tokens_saved_percent, tool_calls_saved_percent, cost_saved_percent.",
    "- Include a Markdown `change_log` table with columns: resource, path, original intent, candidate change, expected impact, contract risk.",
    "",
    "Return Markdown with these sections:",
    "1. Executive recommendation with estimated ROI and confidence.",
    "2. Ranked bottlenecks with evidence from step, LLM, tool, event, and manifest data.",
    "3. roi_hypothesis fenced JSON.",
    "4. change_log table.",
    "5. Prompt edits per step or agent, written as ready-to-review snippets.",
    "6. candidate_manifest_bundle fenced YAML for copied workflow/agent resources.",
    "7. Trial plan: baseline, candidate execution, comparison criteria, quality gate, rollback, cleanup.",
    "8. RBAC and approval requirements for any deployment-capable agent.",
    "",
    compacted ? "Runtime note: Prompt compacted to fit the opencode runtime; raw traces and manifests remain available in the UI inspectors." : "",
    compacted ? "" : "",
    "Workflow run intelligence dossier is included in Trace packet.run_intelligence.",
    "",
    "Trace packet:",
    JSON.stringify(packet, null, 2),
  ].join("\n");
}

function buildRuntimeSafeOptimisationPrompt(packet: OptimisationPacket): string {
  const fullPrompt = buildOptimisationPromptBody(packet, false);
  if (fullPrompt.length <= OPTIMISE_PROMPT_MAX_CHARS) return fullPrompt;

  const compactPrompt = buildOptimisationPromptBody(buildCompactOptimisationPacket(packet), true);
  if (compactPrompt.length <= OPTIMISE_PROMPT_MAX_CHARS) return compactPrompt;

  const marker = "\n\nTrace packet truncated to fit the runtime safety budget.";
  return `${compactPrompt.slice(0, Math.max(0, OPTIMISE_PROMPT_MAX_CHARS - marker.length))}${marker}`;
}

function buildOptimisationPrompt(packet: OptimisationPacket): string {
  return buildRuntimeSafeOptimisationPrompt(packet);
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function extractOptimiserExpectedSavings(response: string | null | undefined): Record<string, unknown> {
  const fallback: Record<string, unknown> = {
    scope: "prompt_model_tool_v1",
    source: "optimizer_agent",
  };
  if (!response) return fallback;

  const fencedBlockPattern = /```(?:json)?\s*([\s\S]*?)```/gi;
  for (const match of response.matchAll(fencedBlockPattern)) {
    const body = match[1]?.trim();
    if (!body || !body.includes("expected_metric_delta")) continue;
    try {
      const parsed = JSON.parse(body) as unknown;
      if (!isPlainObject(parsed)) continue;
      const hypothesis = isPlainObject(parsed.roi_hypothesis) ? parsed.roi_hypothesis : parsed;
      const metricDelta = isPlainObject(hypothesis.expected_metric_delta)
        ? hypothesis.expected_metric_delta
        : {};
      return {
        ...fallback,
        ...metricDelta,
        confidence: hypothesis.confidence,
        target_steps: Array.isArray(hypothesis.target_steps) ? hypothesis.target_steps : [],
        target_tools: Array.isArray(hypothesis.target_tools) ? hypothesis.target_tools : [],
        quality_gate: isPlainObject(hypothesis.quality_gate) ? hypothesis.quality_gate : hypothesis.quality_gate,
        rollback_plan: hypothesis.rollback_plan,
      };
    } catch {
      continue;
    }
  }
  return fallback;
}

function TraceExplorer({
  detail,
  orderedSteps,
  orderedEvents,
  selectedStepId,
  onStepSelect,
  selectedEventId,
  onEventSelect,
  onOpenLLM,
}: {
  detail: ExecutionTrace | null;
  orderedSteps: StepTrace[];
  orderedEvents: ExecutionTrace["events"];
  selectedStepId: string | null;
  onStepSelect: (stepId: string | null) => void;
  selectedEventId: string | null;
  onEventSelect: (eventId: string | null) => void;
  onOpenLLM: (call: LLMCallRecord) => void;
}) {
  const [kindFilter, setKindFilter] = useState<TraceKindFilter>("all");
  const [agentFilter, setAgentFilter] = useState(ALL_FILTER_VALUE);
  const [toolFilter, setToolFilter] = useState(ALL_FILTER_VALUE);
  const [modelFilter, setModelFilter] = useState(ALL_FILTER_VALUE);
  const [statusFilter, setStatusFilter] = useState<TraceStatusFilter>("all");
  const [traceSearch, setTraceSearch] = useState("");
  const [selectedRecordId, setSelectedRecordId] = useState<string | null>(null);

  const traceRecords = useMemo(
    () => (detail ? buildTraceRecords(detail, orderedSteps, orderedEvents) : []),
    [detail, orderedEvents, orderedSteps],
  );

  const agentOptions = useMemo(
    () => Array.from(new Set(traceRecords.map((record) => record.actorLabel).filter(Boolean))).sort(),
    [traceRecords],
  );
  const toolOptions = useMemo(
    () => Array.from(new Set(traceRecords.map((record) => record.toolName).filter(Boolean) as string[])).sort(),
    [traceRecords],
  );
  const modelOptions = useMemo(
    () => Array.from(new Set(traceRecords.map((record) => record.model).filter(Boolean) as string[])).sort(),
    [traceRecords],
  );

  useEffect(() => {
    setSelectedRecordId(null);
    setKindFilter("all");
    setAgentFilter(ALL_FILTER_VALUE);
    setToolFilter(ALL_FILTER_VALUE);
    setModelFilter(ALL_FILTER_VALUE);
    setStatusFilter("all");
    setTraceSearch("");
  }, [detail?.id]);

  const kindCounts = useMemo(() => ({
    all: traceRecords.length,
    llm: traceRecords.filter((record) => record.kind === "llm").length,
    tool: traceRecords.filter((record) => record.kind === "tool").length,
    event: traceRecords.filter((record) => record.kind === "event").length,
  }), [traceRecords]);

  const selectedStep = useMemo(
    () => orderedSteps.find((step) => step.id === selectedStepId) ?? null,
    [orderedSteps, selectedStepId],
  );

  const filteredRecords = useMemo(() => {
    const query = traceSearch.trim().toLowerCase();
    return traceRecords.filter((record) => {
      if (selectedStepId && record.stepId !== selectedStepId) return false;
      if (kindFilter !== "all" && record.kind !== kindFilter) return false;
      if (agentFilter !== ALL_FILTER_VALUE && record.actorLabel !== agentFilter) return false;
      if (toolFilter !== ALL_FILTER_VALUE && record.toolName !== toolFilter) return false;
      if (modelFilter !== ALL_FILTER_VALUE && record.model !== modelFilter) return false;
      if (statusFilter === "failed" && !isFailedStatus(record.status)) return false;
      if (statusFilter === "completed" && !(normalizedStatus(record.status).includes("completed") || normalizedStatus(record.status).includes("success"))) return false;
      if (query && !record.searchText.toLowerCase().includes(query)) return false;
      return true;
    });
  }, [agentFilter, kindFilter, modelFilter, selectedStepId, statusFilter, toolFilter, traceRecords, traceSearch]);

  const activeRecord =
    filteredRecords.find((record) => record.id === selectedRecordId) ??
    (selectedEventId ? filteredRecords.find((record) => record.event?.id === selectedEventId) : undefined) ??
    filteredRecords[0] ??
    null;
  const contextStep = activeRecord?.step ?? selectedStep;
  const contextStepEvents = contextStep ? orderedEvents.filter((event) => event.step_id === contextStep.id || event.step_id === contextStep.name) : [];

  if (!detail) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Execution trace data appears once indexed execution detail is available.
      </div>
    );
  }

  const clearFilters = () => {
    onStepSelect(null);
    setKindFilter("all");
    setAgentFilter(ALL_FILTER_VALUE);
    setToolFilter(ALL_FILTER_VALUE);
    setModelFilter(ALL_FILTER_VALUE);
    setStatusFilter("all");
    setTraceSearch("");
    setSelectedRecordId(null);
    onEventSelect(null);
  };

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <div className="shrink-0 border-b border-border/40 bg-card/30 px-3 py-2">
        <div className="flex flex-wrap items-center gap-2">
          <div className="min-w-[14rem] flex-1">
            <h3 className="text-sm font-semibold text-foreground">Execution Trace</h3>
            <p className="text-[11px] text-muted-foreground">
              {detail.llm_calls.length} LLM calls · {detail.tool_calls.length} tool calls · {orderedEvents.length} events, joined by step and agent.
            </p>
          </div>
          <div className="relative min-w-[14rem] flex-1">
            <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={traceSearch}
              onChange={(event) => setTraceSearch(event.target.value)}
              placeholder="Search model, tool, path, prompt, event"
              className="h-8 pl-7 text-xs"
            />
          </div>
          <Button type="button" variant="outline" size="sm" className="h-8 text-xs" onClick={clearFilters}>
            Clear
          </Button>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-0.5 rounded-md border border-border/50 bg-background p-0.5">
            {(["all", "llm", "tool", "event"] as TraceKindFilter[]).map((kind) => (
              <button
                key={kind}
                type="button"
                onClick={() => setKindFilter(kind)}
                className={cn(
                  "rounded px-2 py-1 text-[10px] font-medium capitalize transition-colors",
                  kindFilter === kind ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
                )}
              >
                {kind === "all" ? "All" : kind} {kindCounts[kind]}
              </button>
            ))}
          </div>
          <Select value={agentFilter} onValueChange={setAgentFilter}>
            <SelectTrigger className="h-8 w-40 text-xs">
              <SelectValue placeholder="All agents" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_FILTER_VALUE}>All agents</SelectItem>
              {agentOptions.map((agent) => <SelectItem key={agent} value={agent}>{agent}</SelectItem>)}
            </SelectContent>
          </Select>
          <Select value={toolFilter} onValueChange={setToolFilter}>
            <SelectTrigger className="h-8 w-40 text-xs">
              <SelectValue placeholder="Filter by tool" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_FILTER_VALUE}>Filter by tool</SelectItem>
              {toolOptions.map((tool) => <SelectItem key={tool} value={tool}>{tool}</SelectItem>)}
            </SelectContent>
          </Select>
          <Select value={modelFilter} onValueChange={setModelFilter}>
            <SelectTrigger className="h-8 w-52 text-xs">
              <SelectValue placeholder="All models" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_FILTER_VALUE}>All models</SelectItem>
              {modelOptions.map((model) => <SelectItem key={model} value={model}>{model}</SelectItem>)}
            </SelectContent>
          </Select>
          <Select value={statusFilter} onValueChange={(value) => setStatusFilter(value as TraceStatusFilter)}>
            <SelectTrigger className="h-8 w-36 text-xs">
              <SelectValue placeholder="All status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All status</SelectItem>
              <SelectItem value="completed">Completed</SelectItem>
              <SelectItem value="failed">Failed/error</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden xl:grid-cols-[12rem_minmax(20rem,1fr)_minmax(24rem,1.1fr)]">
        <div className="min-h-0 border-b border-border/40 xl:border-b-0 xl:border-r">
          <div className="flex items-center justify-between border-b border-border/30 px-3 py-2">
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Agent / step</div>
              <div className="text-xs font-medium text-foreground">{detail.agent_name ?? "workflow agent"}</div>
            </div>
            <Badge variant="outline" className="text-[10px]">{orderedSteps.length}</Badge>
          </div>
          <ScrollArea className="h-full">
            <div className="space-y-1 p-2">
              <button
                type="button"
                onClick={() => onStepSelect(null)}
                className={cn(
                  "w-full rounded-md border px-2.5 py-2 text-left transition-colors",
                  selectedStepId === null ? "border-primary/40 bg-primary/8" : "border-border/40 bg-card/40 hover:bg-accent/30",
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-medium text-foreground">All execution</span>
                  <span className="text-[10px] text-muted-foreground">{traceRecords.length} records</span>
                </div>
                <div className="mt-1 text-[10px] text-muted-foreground">
                  {detail.llm_calls.length} LLM · {detail.tool_calls.length} tools · {orderedEvents.length} events
                </div>
              </button>
              {orderedSteps.map((step) => {
                const isActive = step.id === selectedStepId;
                const stepEvents = orderedEvents.filter((event) => event.step_id === step.id || event.step_id === step.name).length;
                const failed = isFailedStatus(step.status) || step.error;
                return (
                  <button
                    key={step.id}
                    type="button"
                    onClick={() => onStepSelect(step.id)}
                    className={cn(
                      "w-full rounded-md border px-2.5 py-2 text-left transition-colors",
                      isActive ? "border-primary/50 bg-primary/8" : "border-border/40 bg-card/30 hover:bg-accent/30",
                    )}
                  >
                    <div className="flex items-center gap-2">
                      <span className={cn("h-2 w-2 shrink-0 rounded-full", failed ? "bg-red-500" : "bg-sky-500")} />
                      <span className="min-w-0 flex-1 truncate text-xs font-semibold text-foreground">{getStepLabel(step)}</span>
                    </div>
                    <div className="mt-1 truncate text-[10px] text-muted-foreground">
                      {(step.step_type || detail.agent_name || "agent")} · {formatDuration(step.latency_ms)}
                    </div>
                    <div className="mt-1 flex flex-wrap gap-1 text-[9px] text-muted-foreground">
                      <span>{step.llm_calls.length || step.llm_call_count || 0} LLM</span>
                      <span>{step.tool_calls.length || step.tool_call_count || 0} tools</span>
                      <span>{stepEvents} events</span>
                    </div>
                  </button>
                );
              })}
            </div>
          </ScrollArea>
        </div>

        <div className="flex min-h-0 min-w-0 flex-col overflow-hidden border-b border-border/40 xl:border-b-0 xl:border-r">
          <div className="flex shrink-0 items-center justify-between border-b border-border/30 px-3 py-2">
            <div className="text-xs font-semibold text-foreground">Chronology</div>
            <div className="text-[10px] text-muted-foreground">
              {filteredRecords.length} of {traceRecords.length} records
            </div>
          </div>
          <ScrollArea className="min-h-0 min-w-0 flex-1">
            <div className="space-y-1.5 p-2">
              {filteredRecords.length === 0 && (
                <div className="rounded-lg border border-dashed border-border/50 py-12 text-center text-xs text-muted-foreground">
                  No trace records match the current filters.
                </div>
              )}
              {filteredRecords.map((record) => {
                const isActive = activeRecord?.id === record.id;
                const ToolIcon = record.kind === "tool" && record.toolName ? getToolIcon(record.toolName) : null;
                return (
                  <button
                    key={record.id}
                    type="button"
                    onClick={() => {
                      setSelectedRecordId(record.id);
                      onStepSelect(record.step?.id ?? null);
                      onEventSelect(record.event?.id ?? null);
                    }}
                    className={cn(
                      "block w-full min-w-0 overflow-hidden rounded-lg border px-3 py-2 text-left transition-colors",
                      isActive ? "border-primary/50 bg-primary/8" : "border-border/45 bg-card/35 hover:bg-accent/25",
                    )}
                  >
                    <div className="flex min-w-0 items-start gap-2">
                      <Badge variant="outline" className={cn("mt-0.5 h-5 shrink-0 px-1.5 text-[9px] uppercase", traceKindClasses(record.kind))}>
                        {record.kind}
                      </Badge>
                      <div className="min-w-0 flex-1">
                        <div className="flex min-w-0 items-center gap-2">
                          {ToolIcon && <ToolIcon className={cn("h-3.5 w-3.5 shrink-0", getToolIconColor(record.toolName ?? ""))} />}
                          <span className="min-w-0 flex-1 truncate text-xs font-semibold text-foreground">{record.title}</span>
                          <span className={cn("shrink-0 text-[10px] font-medium", statusTextClasses(record.status))}>{record.status}</span>
                        </div>
                        <p className="mt-1 truncate text-[11px] text-muted-foreground">{record.summary}</p>
                        <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1 text-[10px] text-muted-foreground">
                          <span className="shrink-0 tabular-nums">{record.timestamp ? formatCompactDate(record.timestamp) : "--"}</span>
                          <span className="min-w-0 truncate">Agent: {record.actorLabel}</span>
                          <span className="min-w-0 truncate">Step: {record.stepLabel}</span>
                          {record.durationMs != null && record.durationMs > 0 && <span className="shrink-0">{formatDuration(record.durationMs)}</span>}
                          {record.tokens != null && record.tokens > 0 && <span className="shrink-0">{record.tokens.toLocaleString()} tokens</span>}
                          {record.cost != null && record.cost > 0 && <span className="shrink-0">{formatCurrency(record.cost)}</span>}
                        </div>
                      </div>
                      <ChevronRight className={cn("mt-1 h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform", isActive && "rotate-90 text-primary")} />
                    </div>
                  </button>
                );
              })}
            </div>
          </ScrollArea>
        </div>

        <div className="min-h-0 overflow-hidden">
          <div className="border-b border-border/30 px-3 py-2">
            <div className="text-xs font-semibold text-foreground">Inspector</div>
            <div className="text-[10px] text-muted-foreground">Selected call, event, and step context</div>
          </div>
          <ScrollArea className="h-full">
            <div className="space-y-3 p-3">
              {activeRecord ? (
                <div className="rounded-lg border border-border/50 bg-card/40 p-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <Badge variant="outline" className={cn("mb-2 h-5 px-1.5 text-[9px] uppercase", traceKindClasses(activeRecord.kind))}>
                        {activeRecord.kind}
                      </Badge>
                      <h4 className="truncate text-sm font-semibold text-foreground">{activeRecord.title}</h4>
                      <p className="mt-1 text-[11px] text-muted-foreground">{activeRecord.summary}</p>
                    </div>
                    {activeRecord.llm && (
                      <Button type="button" size="sm" variant="outline" className="h-7 text-[10px]" onClick={() => onOpenLLM(activeRecord.llm!)}>
                        Inspect
                      </Button>
                    )}
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-2 text-[10px]">
                    <div className="rounded-md border border-border/40 bg-background/70 p-2">
                      <div className="text-muted-foreground">Agent</div>
                      <div className="mt-0.5 truncate font-medium text-foreground">{activeRecord.actorLabel}</div>
                    </div>
                    <div className="rounded-md border border-border/40 bg-background/70 p-2">
                      <div className="text-muted-foreground">Step</div>
                      <div className="mt-0.5 truncate font-medium text-foreground">{activeRecord.stepLabel}</div>
                    </div>
                    <div className="rounded-md border border-border/40 bg-background/70 p-2">
                      <div className="text-muted-foreground">Time</div>
                      <div className="mt-0.5 truncate font-medium text-foreground">{activeRecord.timestamp ? formatCompactDate(activeRecord.timestamp) : "--"}</div>
                    </div>
                    <div className="rounded-md border border-border/40 bg-background/70 p-2">
                      <div className="text-muted-foreground">Duration</div>
                      <div className="mt-0.5 font-medium text-foreground">{activeRecord.durationMs ? formatDuration(activeRecord.durationMs) : "--"}</div>
                    </div>
                  </div>

                  {activeRecord.llm && (
                    <div className="mt-3 space-y-2">
                      <TokenBar label="Prompt" value={activeRecord.llm.prompt_tokens} max={Math.max(activeRecord.llm.total_tokens, 1)} color="bg-violet-500" />
                      <TokenBar label="Completion" value={activeRecord.llm.completion_tokens} max={Math.max(activeRecord.llm.total_tokens, 1)} color="bg-sky-500" />
                      {activeRecord.llm.prompt_preview && (
                        <pre className="max-h-28 overflow-auto rounded-md border border-border/40 bg-slate-950 p-2 text-[10px] text-slate-100 whitespace-pre-wrap">{activeRecord.llm.prompt_preview}</pre>
                      )}
                      {activeRecord.llm.response_preview && (
                        <pre className="max-h-36 overflow-auto rounded-md border border-border/40 bg-muted/30 p-2 text-[10px] text-foreground/80 whitespace-pre-wrap">{activeRecord.llm.response_preview}</pre>
                      )}
                    </div>
                  )}

                  {activeRecord.tool && (
                    <div className="mt-3 space-y-2">
                      {(activeRecord.tool.tool_args || activeRecord.tool.args_preview) && (
                        <div>
                          <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{getToolDetailLabel(activeRecord.tool.tool_name)}</div>
                          <ArgsCard tc={activeRecord.tool} />
                        </div>
                      )}
                      {(activeRecord.tool.tool_result != null || activeRecord.tool.result_preview) && (
                        <div>
                          <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Result</div>
                          <ResultBlock tc={activeRecord.tool} />
                        </div>
                      )}
                      {activeRecord.tool.error_message && (
                        <pre className="rounded-md border border-red-500/25 bg-red-500/10 p-2 text-[10px] text-red-400 whitespace-pre-wrap">{activeRecord.tool.error_message}</pre>
                      )}
                    </div>
                  )}

                  {activeRecord.event && (
                    <div className="mt-3">
                      <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Event payload</div>
                      <JsonHighlight code={JSON.stringify(activeRecord.event.payload, null, 2)} />
                    </div>
                  )}
                </div>
              ) : (
                <div className="rounded-lg border border-dashed border-border/50 py-12 text-center text-xs text-muted-foreground">
                  Select a trace record to inspect its data.
                </div>
              )}

              {contextStep && (
                <div className="rounded-lg border border-border/50 bg-card/35 p-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <h4 className="truncate text-xs font-semibold text-foreground">{getStepLabel(contextStep)}</h4>
                      <p className="mt-0.5 text-[10px] text-muted-foreground">
                        {contextStep.step_type || detail.agent_name || "agent"} · {formatDuration(contextStep.latency_ms)} · {contextStep.llm_calls.length || contextStep.llm_call_count || 0} LLM · {contextStep.tool_calls.length || contextStep.tool_call_count || 0} tools
                      </p>
                    </div>
                    <Badge variant="outline" className={cn("text-[10px]", statusBadgeClasses(contextStep.status))}>{contextStep.status}</Badge>
                  </div>
                  {contextStep.error && (
                    <pre className="mt-2 rounded-md border border-red-500/25 bg-red-500/10 p-2 text-[10px] text-red-400 whitespace-pre-wrap">{contextStep.error}</pre>
                  )}
                  {contextStep.input_preview && (
                    <div className="mt-2">
                      <div className="mb-1 flex items-center justify-between">
                        <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Input</span>
                        <CopyButton value={contextStep.input_preview} className="h-5 w-5" />
                      </div>
                      <pre className="max-h-28 overflow-auto rounded-md border border-border/40 bg-slate-950 p-2 text-[10px] text-slate-100 whitespace-pre-wrap">{contextStep.input_preview}</pre>
                    </div>
                  )}
                  {contextStep.output_preview && (
                    <div className="mt-2">
                      <div className="mb-1 flex items-center justify-between">
                        <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Output</span>
                        <CopyButton value={contextStep.output_preview} className="h-5 w-5" />
                      </div>
                      <pre className="max-h-28 overflow-auto rounded-md border border-border/40 bg-muted/30 p-2 text-[10px] text-foreground/80 whitespace-pre-wrap">{contextStep.output_preview}</pre>
                    </div>
                  )}
                  {contextStepEvents.length > 0 && (
                    <div className="mt-3">
                      <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Step events</div>
                      <ExecutionTimeline events={contextStepEvents} activeEventId={selectedEventId} onEventClick={(event) => onEventSelect(event.id)} compact />
                    </div>
                  )}
                </div>
              )}
            </div>
          </ScrollArea>
        </div>
      </div>
    </div>
  );
}

function OptimisePanel({
  detail,
  agents,
  agentsLoading,
  selectedAgentName,
  onSelectedAgentChange,
  scope,
  onScopeChange,
  packet,
  prompt,
  detailsLoading,
  manifestLoading,
  manifestError,
  running,
  runPhases,
  result,
  error,
  study,
  candidate,
  roi,
  comparison,
  studyLoading,
  studyError,
  actionLoading,
  applyPreview,
  datasetPreview,
  onRun,
  onApproveCandidate,
  onDryRunApply,
  onRunCandidate,
  onRefreshStudy,
  onRecordTrial,
  onExportDataset,
  onPromoteCandidate,
}: {
  detail: ExecutionTrace | null;
  agents: AgentInfo[];
  agentsLoading: boolean;
  selectedAgentName: string;
  onSelectedAgentChange: (agentName: string) => void;
  scope: OptimisationScope;
  onScopeChange: (scope: OptimisationScope) => void;
  packet: OptimisationPacket | null;
  prompt: string;
  detailsLoading: boolean;
  manifestLoading: boolean;
  manifestError: string;
  running: boolean;
  runPhases: OptimisationRunPhase[];
  result: InvokeResponse | null;
  error: string;
  study: OptimizationStudy | null;
  candidate: OptimizationCandidate | null;
  roi: OptimizationRoi | null;
  comparison: OptimizationComparison | null;
  studyLoading: boolean;
  studyError: string;
  actionLoading: string | null;
  applyPreview: Record<string, unknown> | null;
  datasetPreview: Record<string, unknown> | null;
  onRun: () => void;
  onApproveCandidate: () => void;
  onDryRunApply: () => void;
  onRunCandidate: () => void;
  onRefreshStudy: () => void;
  onRecordTrial: () => void;
  onExportDataset: () => void;
  onPromoteCandidate: () => void;
}) {
  const selectedAgent = agents.find((agent) => agent.name === selectedAgentName) ?? null;
  const selectedAgentLooksOptimiser = selectedAgent ? isOptimiserAgentCandidate(selectedAgent) : false;
  const optimizerAgentRequired = Boolean(selectedAgent && !selectedAgentLooksOptimiser);
  const promptEstimate = Math.ceil(prompt.length / 4);
  const promptWasCompacted = prompt.includes("Prompt compacted to fit the opencode runtime");
  const activeCandidate = candidate ?? study?.candidates?.[study.candidates.length - 1] ?? null;
  const trials = study?.trials ?? [];
  const baselineMetrics = roi?.baseline_metrics ?? study?.baseline_metrics ?? null;
  const candidateMetrics = roi?.candidate_metrics ?? null;
  const deltas = roi?.deltas ?? {};
  const opportunities = study?.opportunities ?? [];
  const intelligence = study?.optimizer_intelligence ?? null;
  const rankedLevers = intelligence?.ranked_levers?.length ? intelligence.ranked_levers : opportunities;
  const stepRollups = intelligence?.step_rollups ?? [];
  const modelRollups = intelligence?.model_rollups ?? [];
  const toolRollups = intelligence?.tool_rollups ?? [];
  const diagnostics = intelligence?.trajectory_diagnostics ?? [];
  const datasetReadiness = intelligence?.dataset_readiness ?? null;
  const proofGate = roi?.proof_gate ?? study?.proof_gate ?? {};
  const validation = activeCandidate?.validation_results ?? {};
  const manifestDiff = activeCandidate?.manifest_diff ?? {};
  const validationErrors = Array.isArray(validation.errors) ? validation.errors.map(String) : [];
  const validationWarnings = Array.isArray(validation.warnings) ? validation.warnings.map(String) : [];
  const comparisonTrials = comparison?.trials ?? [];
  const comparisonSteps = comparison?.steps ?? [];
  const comparisonTools = comparison?.tools ?? [];
  const comparisonScorecard = comparison?.scorecard ?? null;
  const comparisonManifest = comparison?.manifest_diff ?? null;
  const comparisonManifestSections = comparisonManifest?.sections ?? [];
  const [selectedManifestSectionId, setSelectedManifestSectionId] = useState("workflow");
  const selectedManifestSection =
    comparisonManifestSections.find((section) => section.id === selectedManifestSectionId) ??
    comparisonManifestSections[0] ??
    null;
  const proofStatus = roi?.proof_status ?? (activeCandidate ? "pending_trials" : study ? "candidate_needed" : "baseline_needed");
  const isVerified = roi?.verified === true;
  const canApprove = Boolean(activeCandidate && activeCandidate.approval_status !== "approved" && activeCandidate.status !== "rejected");
  const canDryRun = Boolean(activeCandidate && activeCandidate.approval_status === "approved");
  const canRunCandidate = Boolean(activeCandidate && activeCandidate.approval_status === "approved" && activeCandidate.status !== "rejected");
  const canPromote = Boolean(activeCandidate && activeCandidate.approval_status === "approved" && activeCandidate.status !== "promoted" && isVerified);
  const deploymentCapable = selectedAgent?.cluster_access?.deployment_capable === true || selectedAgentLooksOptimiser;
  const accessLevel = selectedAgent?.cluster_access?.level ?? (deploymentCapable ? "elevated" : "standard");
  const accessScope = selectedAgent?.cluster_access?.scope ?? selectedAgent?.namespace ?? "namespace";
  const accessGuard = selectedAgent?.cluster_access?.guard ?? "admin approval, copied candidate manifests only";
  const confidenceLevel = typeof intelligence?.scorecard?.confidence_level === "string"
    ? intelligence.scorecard.confidence_level
    : typeof proofGate.confidence === "object" && proofGate.confidence && !Array.isArray(proofGate.confidence) && typeof (proofGate.confidence as Record<string, unknown>).level === "string"
      ? String((proofGate.confidence as Record<string, unknown>).level)
      : "low";
  const safeTrialTarget = typeof proofGate.minimum_safe_trials === "number" ? proofGate.minimum_safe_trials : 5;
  const topLever = rankedLevers[0] ?? null;
  const topStep = stepRollups[0] ?? null;
  const topModel = modelRollups[0] ?? null;
  const topTool = toolRollups[0] ?? null;
  const datasetSplits = datasetReadiness?.splits ?? {};
  const localModelPath = datasetReadiness?.local_model_path ?? {};
  const candidateResourceNames = activeCandidate?.manifest_bundle.map((manifest) => {
    const metadata = manifest.metadata;
    const name = metadata && typeof metadata === "object" && !Array.isArray(metadata) ? (metadata as Record<string, unknown>).name : null;
    return `${String(manifest.kind ?? "Resource")}/${String(name ?? "unnamed")}`;
  }) ?? [];
  const runDisabled = !selectedAgentName || !packet || running || detailsLoading || manifestLoading || optimizerAgentRequired;

  useEffect(() => {
    if (comparisonManifestSections.length === 0) return;
    if (!comparisonManifestSections.some((section) => section.id === selectedManifestSectionId)) {
      setSelectedManifestSectionId(comparisonManifestSections[0].id);
    }
  }, [comparisonManifestSections, selectedManifestSectionId]);

  const percent = (key: string) => {
    const value = deltas[key];
    return typeof value === "number" && Number.isFinite(value) ? value : 0;
  };
  const deltaLabel = (value: number) => (
    value > 0 ? `${value.toFixed(1)}% saved` : value < 0 ? `${Math.abs(value).toFixed(1)}% regression` : "no change"
  );
  const deltaClassName = (value: number) => cn(
    value > 0 && "text-emerald-600 dark:text-emerald-400",
    value < 0 && "text-red-600 dark:text-red-300",
    value === 0 && "text-muted-foreground",
  );
  const money = (value?: number | null) => (value && value > 0 ? formatCurrency(value) : "--");
  const metricNumber = (value?: number | null) => compactNumber(value).toLocaleString(undefined, { maximumFractionDigits: 1 });
  const fallbackComparisonMetrics: OptimizationComparisonMetric[] = [
    {
      key: "duration_saved_percent",
      label: "Wall-clock",
      baseline_value: baselineMetrics?.duration_per_successful_run_ms ?? baselineMetrics?.avg_duration_ms ?? 0,
      candidate_value: candidateMetrics?.duration_per_successful_run_ms ?? candidateMetrics?.avg_duration_ms ?? 0,
      actual_delta_percent: percent("duration_saved_percent"),
      estimated_delta_percent: undefined,
      value_kind: "duration_ms",
      source: "study_rollup",
      unit: "per successful run",
    },
    {
      key: "tokens_saved_percent",
      label: "Tokens",
      baseline_value: baselineMetrics?.tokens_per_successful_run ?? baselineMetrics?.avg_tokens ?? 0,
      candidate_value: candidateMetrics?.tokens_per_successful_run ?? candidateMetrics?.avg_tokens ?? 0,
      actual_delta_percent: percent("tokens_saved_percent"),
      estimated_delta_percent: undefined,
      value_kind: "tokens",
      source: "study_rollup",
      unit: "per successful run",
    },
    {
      key: "tool_calls_saved_percent",
      label: "Tool calls",
      baseline_value: baselineMetrics?.avg_tool_calls ?? 0,
      candidate_value: candidateMetrics?.avg_tool_calls ?? 0,
      actual_delta_percent: percent("tool_calls_saved_percent"),
      estimated_delta_percent: undefined,
      value_kind: "tool_calls",
      source: "study_rollup",
      unit: "average per run",
    },
    {
      key: "cost_saved_percent",
      label: "Cost",
      baseline_value: baselineMetrics?.cost_per_successful_run ?? baselineMetrics?.avg_cost_usd ?? 0,
      candidate_value: candidateMetrics?.cost_per_successful_run ?? candidateMetrics?.avg_cost_usd ?? 0,
      actual_delta_percent: percent("cost_saved_percent"),
      estimated_delta_percent: undefined,
      value_kind: "cost_usd",
      source: "study_rollup",
      unit: "per successful run",
    },
  ];
  const actualComparisonMetrics = comparisonScorecard?.metrics?.length ? comparisonScorecard.metrics : fallbackComparisonMetrics;
  const hasActualComparison = Boolean(comparisonScorecard && comparisonScorecard.metric_source === "paired_trials");
  const comparisonMetricSource = comparisonMetricSourceLabel(comparisonScorecard?.metric_source);
  const stepRegressions = comparisonSteps.filter((step) => (step.deltas.duration_saved_percent ?? 0) < 0 || (step.deltas.tokens_saved_percent ?? 0) < 0 || (step.deltas.tool_calls_saved_percent ?? 0) < 0);
  const stageItems = [
    { key: "baseline", label: "Baseline", icon: Database, done: Boolean(study), hint: `${baselineMetrics?.sample_count ?? 0} traces` },
    { key: "opportunities", label: "Levers", icon: Target, done: rankedLevers.length > 0, hint: `${rankedLevers.length || (packet?.opportunity_map.length ?? 0)} ranked` },
    { key: "candidate", label: "Candidate", icon: Sparkles, done: Boolean(activeCandidate), hint: activeCandidate?.candidate_workflow_name ?? "copy pending" },
    { key: "trials", label: "Trial Runs", icon: FlaskConical, done: trials.length >= safeTrialTarget, hint: `${trials.length}/${safeTrialTarget} recorded` },
    { key: "roi", label: "Verified ROI", icon: CheckCircle2, done: isVerified, hint: proofStatus.replace(/_/g, " ") },
    { key: "promote", label: "Promote", icon: Rocket, done: activeCandidate?.status === "promoted" || study?.status === "promoted", hint: canPromote ? "ready" : "approval gate" },
  ];

  if (!detail) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Optimization data appears once a traced execution is selected.
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <div className="shrink-0 border-b border-border/40 bg-card/30 px-3 py-2">
        <div className="flex flex-wrap items-center gap-2">
          <div className="min-w-[18rem] flex-1">
            <div className="flex items-center gap-2">
              <TrendingDown className="h-4 w-4 text-primary" />
              <h3 className="text-sm font-semibold text-foreground">Optimization ROI Lab</h3>
              <Badge variant="outline" className={cn("h-5 text-[10px]", isVerified ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300" : "border-sky-500/30 bg-sky-500/8 text-sky-700 dark:text-sky-300")}>
                {proofStatus.replace(/_/g, " ")}
              </Badge>
              <Badge variant="outline" className="h-5 text-[10px]">
                {confidenceLevel} confidence
              </Badge>
            </div>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              {detail.workflow_name} · {formatDuration(detail.duration_ms)} · {detail.total_tokens.toLocaleString()} tokens · {detail.tool_call_count} tools · dataset {datasetReadiness?.state?.replace(/_/g, " ") ?? "not profiled"}
            </p>
          </div>
          <Select value={selectedAgentName || "__none__"} onValueChange={(value) => { if (value !== "__none__") onSelectedAgentChange(value); }}>
            <SelectTrigger className="h-8 w-56 text-xs">
              <SelectValue placeholder={agentsLoading ? "Loading agents" : "Select agent"} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__none__" disabled>{agentsLoading ? "Loading agents" : "Select agent"}</SelectItem>
              {agents.map((agent) => (
                <SelectItem key={`${agent.namespace}/${agent.name}`} value={agent.name}>
                  {agent.name} · {agent.model || agent.runtime_kind || "agent"}{isOptimiserAgentCandidate(agent) ? " · optimizer" : ""}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={scope} onValueChange={(value) => onScopeChange(value as OptimisationScope)}>
            <SelectTrigger className="h-8 w-44 text-xs">
              <SelectValue placeholder="Trace scope" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="current">Current trace</SelectItem>
              <SelectItem value="last6">Last 6 traces</SelectItem>
              <SelectItem value="last20">Last 20 traces</SelectItem>
            </SelectContent>
          </Select>
          <Button type="button" size="sm" variant="outline" className="h-8 gap-1.5 text-xs" disabled={!study || studyLoading} onClick={onRefreshStudy}>
            {studyLoading ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            Refresh
          </Button>
          <Button
            type="button"
            size="sm"
            className="h-8 gap-1.5 text-xs"
            disabled={runDisabled}
            onClick={onRun}
          >
            {running ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
            Run ROI study
          </Button>
        </div>
      </div>

      <ScrollArea className="min-h-0 flex-1">
        <div className="space-y-3 p-3">
          <section className="rounded-lg border border-border/50 bg-card/45 p-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-[18rem]">
                <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                  {isVerified ? "Verified gain" : "Best current lever"}
                </div>
                <div className="mt-1 text-xl font-semibold tracking-tight text-foreground">
                  {isVerified
                    ? comparisonScorecard?.summary ?? `Saved ${percent("tokens_saved_percent").toFixed(1)}% tokens / ${percent("duration_saved_percent").toFixed(1)}% time`
                    : activeCandidate
                      ? comparisonScorecard?.summary ?? "Candidate ready for safe trials"
                      : study
                        ? topLever?.title ?? "Baseline profiled, candidate pending"
                        : "Create a baseline study"}
                </div>
                <p className="mt-1 text-[11px] text-muted-foreground">
                  {comparisonScorecard
                    ? `${comparisonMetricSource}. ${comparisonScorecard.safe_trial_count}/${safeTrialTarget} safe trials; next action: ${comparisonScorecard.next_action.replace(/_/g, " ")}.`
                    : topLever
                      ? `${topLever.recommendation} ${safeTrialTarget} safe trials are required before promotion.`
                      : "A copied manifest bundle must beat baseline metrics and pass safety checks before promotion."}
                </p>
                {topLever && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    <Badge variant="outline" className="h-5 text-[10px]">{topLever.lever?.replace(/_/g, " ") ?? topLever.kind}</Badge>
                    <Badge variant="outline" className="h-5 text-[10px]">{topLever.impact_score ?? 0}/100 impact</Badge>
                    <Badge variant="outline" className="h-5 text-[10px]">{topLever.confidence ?? confidenceLevel} evidence</Badge>
                  </div>
                )}
              </div>
              <div className="grid flex-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
                {actualComparisonMetrics.map((item) => (
                  <div key={item.key} className="rounded-md border border-border/45 bg-background/70 p-2">
                    <div className="text-[10px] font-medium text-muted-foreground">{item.label}</div>
                    <div className="mt-1 flex items-baseline justify-between gap-2">
                      <span className="text-sm font-semibold text-foreground">{formatComparisonMetricValue(item, item.baseline_value)}</span>
                      <span className={cn("text-[10px] font-semibold", deltaClassName(item.actual_delta_percent))}>
                        {hasActualComparison || item.candidate_value > 0 ? deltaLabel(item.actual_delta_percent) : "pending"}
                      </span>
                    </div>
                    <div className="mt-0.5 text-[10px] text-muted-foreground">
                      candidate {item.candidate_value > 0 ? formatComparisonMetricValue(item, item.candidate_value) : "--"}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </section>

          <div className="grid gap-3 xl:grid-cols-[13rem_minmax(0,1.25fr)_minmax(22rem,0.85fr)]">
            <aside className="space-y-3">
              <section className="rounded-lg border border-border/50 bg-card/45 p-2">
                <div className="px-1 pb-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Study stages</div>
                <div className="space-y-1">
                  {stageItems.map((stage) => {
                    const Icon = stage.icon;
                    return (
                      <div key={stage.key} className={cn(
                        "rounded-md border px-2 py-2",
                        stage.done ? "border-primary/30 bg-primary/8" : "border-border/40 bg-background/55",
                      )}>
                        <div className="flex items-center gap-2">
                          <Icon className={cn("h-3.5 w-3.5", stage.done ? "text-primary" : "text-muted-foreground")} />
                          <span className="min-w-0 flex-1 truncate text-xs font-medium text-foreground">{stage.label}</span>
                          {stage.done && <CheckCircle2 className="h-3.5 w-3.5 text-primary" />}
                        </div>
                        <div className="mt-1 truncate text-[10px] text-muted-foreground">{stage.hint}</div>
                      </div>
                    );
                  })}
                </div>
              </section>

              <section className="rounded-lg border border-border/50 bg-card/45 p-2">
                <div className="flex items-center justify-between px-1 pb-2">
                  <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Candidates</span>
                  <Badge variant="outline" className="h-5 text-[10px]">{study?.candidates?.length ?? (activeCandidate ? 1 : 0)}</Badge>
                </div>
                {activeCandidate ? (
                  <div className="rounded-md border border-primary/30 bg-primary/8 p-2">
                    <div className="truncate text-xs font-semibold text-foreground">{activeCandidate.candidate_workflow_name}</div>
                    <div className="mt-1 flex flex-wrap gap-1">
                      <Badge variant="outline" className="h-5 text-[9px]">{activeCandidate.status}</Badge>
                      <Badge variant="outline" className={cn("h-5 text-[9px]", activeCandidate.approval_status === "approved" && "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300")}>
                        {activeCandidate.approval_status}
                      </Badge>
                    </div>
                  </div>
                ) : (
                  <div className="rounded-md border border-dashed border-border/50 p-4 text-center text-[11px] text-muted-foreground">
                    Run a study to create a copied candidate.
                  </div>
                )}
              </section>
            </aside>

            <main className="space-y-3">
              <section className="rounded-lg border border-border/50 bg-card/45 p-3">
                <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-[18rem] flex-1">
                    <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                      <GitCompare className="h-4 w-4 text-primary" />
                      Candidate vs baseline
                    </div>
                    <div className="mt-1 text-lg font-semibold tracking-tight text-foreground">
                      {comparisonScorecard?.summary ?? comparison?.headline.summary ?? (activeCandidate ? "Run the candidate to measure actual ROI" : "Create a candidate to compare against the baseline")}
                    </div>
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      Actual vs estimate: measured savings come from paired trial runs; estimates come from the optimizer hypothesis before candidate execution.
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    <Badge variant="outline" className="h-6 text-[10px]">
                      {comparisonMetricSource}
                    </Badge>
                    <Badge variant="outline" className={cn("h-6 text-[10px]", isVerified && "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300")}>
                      {proofStatus.replace(/_/g, " ")}
                    </Badge>
                    <Badge variant="outline" className="h-6 text-[10px]">
                      {comparisonScorecard?.safe_trial_count ?? roi?.passing_trial_count ?? 0}/{safeTrialTarget} safe trials
                    </Badge>
                    {comparison?.headline.regression_count ? (
                      <Badge variant="outline" className="h-6 border-red-500/30 bg-red-500/10 text-[10px] text-red-600 dark:text-red-300">
                        {comparison.headline.regression_count} regression{comparison.headline.regression_count === 1 ? "" : "s"}
                      </Badge>
                    ) : null}
                  </div>
                </div>

                <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
                  {actualComparisonMetrics.map((item) => {
                    const value = item.actual_delta_percent;
                    const hasCandidateValue = item.candidate_value > 0 || hasActualComparison;
                    return (
                      <div key={item.key} className="rounded-md border border-border/45 bg-background/70 p-2.5">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{item.label}</span>
                          <span className={cn("text-[10px] font-semibold", deltaClassName(value))}>
                            {hasCandidateValue ? deltaLabel(value) : "pending"}
                          </span>
                        </div>
                        <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
                          <div>
                            <div className="text-[10px] text-muted-foreground">Baseline</div>
                            <div className="font-semibold text-foreground">{formatComparisonMetricValue(item, item.baseline_value)}</div>
                          </div>
                          <div>
                            <div className="text-[10px] text-muted-foreground">Candidate</div>
                            <div className="font-semibold text-foreground">{hasCandidateValue ? formatComparisonMetricValue(item, item.candidate_value) : "--"}</div>
                          </div>
                        </div>
                        <div className="mt-2 flex items-center justify-between gap-2 border-t border-border/35 pt-1 text-[10px] text-muted-foreground">
                          <span>{item.source === "paired_trials" ? "paired trial" : item.unit}</span>
                          <span>Estimated by optimizer {typeof item.estimated_delta_percent === "number" ? deltaLabel(item.estimated_delta_percent) : "--"}</span>
                        </div>
                      </div>
                    );
                  })}
                </div>

                <div className="mt-3 grid gap-3 xl:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)]">
                  <div className="rounded-md border border-border/45 bg-background/65 p-2.5">
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <div className="text-xs font-semibold text-foreground">Trial evidence</div>
                      <Badge variant="outline" className="h-5 text-[9px]">{comparisonTrials.length} recorded</Badge>
                    </div>
                    {comparisonTrials.length > 0 ? (
                      <div className="space-y-1.5">
                        {comparisonTrials.slice(-5).reverse().map((trial) => {
                          const candidateRunId = trial.candidate?.run_id ?? (typeof trial.candidate_run?.run_id === "string" ? trial.candidate_run.run_id : "");
                          return (
                            <div key={trial.id} className="rounded border border-border/35 bg-muted/20 px-2 py-1.5">
                              <div className="flex flex-wrap items-center gap-2 text-[10px]">
                                <Badge variant="outline" className="h-5 text-[9px]">{trial.quality_status ?? "needs review"}</Badge>
                                <span className="min-w-0 flex-1 truncate font-medium text-foreground">{candidateRunId || "candidate result pending"}</span>
                                <span className="text-muted-foreground">{formatCompactDate(trial.created_at)}</span>
                              </div>
                              <div className="mt-1 grid gap-1 text-[10px] text-muted-foreground sm:grid-cols-3">
                                <span className={deltaClassName(trial.deltas.duration_saved_percent ?? 0)}>Time {deltaLabel(trial.deltas.duration_saved_percent ?? 0)}</span>
                                <span className={deltaClassName(trial.deltas.tokens_saved_percent ?? 0)}>Tokens {deltaLabel(trial.deltas.tokens_saved_percent ?? 0)}</span>
                                <span className={deltaClassName(trial.deltas.tool_calls_saved_percent ?? 0)}>Tools {deltaLabel(trial.deltas.tool_calls_saved_percent ?? 0)}</span>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <div className="rounded border border-dashed border-border/50 p-4 text-center text-[11px] text-muted-foreground">
                        Approve and run the candidate to populate verified before/after evidence.
                      </div>
                    )}
                  </div>

                  <div className="rounded-md border border-border/45 bg-background/65 p-2.5">
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <div className="text-xs font-semibold text-foreground">Step impact</div>
                      <Badge variant="outline" className="h-5 text-[9px]">{comparisonSteps.length || stepRollups.length} steps</Badge>
                    </div>
                    {(comparisonSteps.length > 0 ? comparisonSteps : []).length > 0 ? (
                      <div className="space-y-1.5">
                        {comparisonSteps.slice(0, 5).map((step) => {
                          const value = step.deltas.duration_saved_percent ?? 0;
                          return (
                            <div key={step.step_name} className="rounded border border-border/35 bg-muted/20 px-2 py-1.5 text-[10px]">
                              <div className="flex items-center justify-between gap-2">
                                <span className="min-w-0 truncate font-medium text-foreground">{step.step_name}</span>
                                <span className={cn("font-semibold", deltaClassName(value))}>{deltaLabel(value)}</span>
                              </div>
                              <div className="mt-1 grid grid-cols-2 gap-2 text-muted-foreground">
                                <span>Base {formatDuration(step.baseline?.avg_duration_ms)} · {metricNumber(step.baseline?.avg_tokens)} tok · {metricNumber(step.baseline?.avg_tool_calls)} tools</span>
                                <span>Candidate {formatDuration(step.candidate?.avg_duration_ms)} · {metricNumber(step.candidate?.avg_tokens)} tok · {metricNumber(step.candidate?.avg_tool_calls)} tools</span>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <div className="rounded border border-dashed border-border/50 p-4 text-center text-[11px] text-muted-foreground">
                        Step deltas appear after a candidate trial is linked to a result trace.
                      </div>
                    )}
                  </div>
                </div>

                {stepRegressions.length > 0 && (
                  <div className="mt-3 rounded-md border border-red-500/25 bg-red-500/10 p-2.5">
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2 text-xs font-semibold text-red-700 dark:text-red-200">
                        <ShieldAlert className="h-3.5 w-3.5" />
                        Regressions to review
                      </div>
                      <Badge variant="outline" className="h-5 border-red-500/30 bg-red-500/10 text-[9px] text-red-700 dark:text-red-200">
                        {stepRegressions.length} step{stepRegressions.length === 1 ? "" : "s"}
                      </Badge>
                    </div>
                    <div className="grid gap-1.5 md:grid-cols-2">
                      {stepRegressions.slice(0, 4).map((step) => (
                        <div key={`regression-${step.step_name}`} className="rounded border border-red-500/25 bg-background/75 px-2 py-1.5 text-[10px]">
                          <div className="flex items-center justify-between gap-2">
                            <span className="min-w-0 truncate font-medium text-foreground">{step.step_name}</span>
                            <span className="font-semibold text-red-600 dark:text-red-300">
                              {deltaLabel(Math.min(step.deltas.duration_saved_percent ?? 0, step.deltas.tokens_saved_percent ?? 0, step.deltas.tool_calls_saved_percent ?? 0))}
                            </span>
                          </div>
                          <div className="mt-1 grid grid-cols-3 gap-1 text-muted-foreground">
                            <span>Time {deltaLabel(step.deltas.duration_saved_percent ?? 0)}</span>
                            <span>Tokens {deltaLabel(step.deltas.tokens_saved_percent ?? 0)}</span>
                            <span>Tools {deltaLabel(step.deltas.tool_calls_saved_percent ?? 0)}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div className="mt-3 grid gap-3 xl:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
                  <div className="rounded-md border border-border/45 bg-background/65 p-2.5">
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <div className="text-xs font-semibold text-foreground">Tool impact</div>
                      <Badge variant="outline" className="h-5 text-[9px]">{comparisonTools.length} tools</Badge>
                    </div>
                    {comparisonTools.length > 0 ? (
                      <div className="space-y-1.5">
                        {comparisonTools.slice(0, 6).map((tool) => {
                          const value = tool.deltas.calls_saved_percent ?? 0;
                          return (
                            <div key={tool.tool_name} className="grid grid-cols-[minmax(0,1fr)_auto] gap-2 rounded border border-border/35 bg-muted/20 px-2 py-1.5 text-[10px]">
                              <div className="min-w-0">
                                <div className="truncate font-medium text-foreground">{tool.tool_name}</div>
                                <div className="truncate text-muted-foreground">
                                  {metricNumber(tool.baseline?.calls_per_run)} to {metricNumber(tool.candidate?.calls_per_run)} calls/run
                                </div>
                              </div>
                              <div className={cn("text-right font-semibold", deltaClassName(value))}>{deltaLabel(value)}</div>
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <div className="rounded border border-dashed border-border/50 p-4 text-center text-[11px] text-muted-foreground">
                        Tool call savings appear after candidate execution.
                      </div>
                    )}
                  </div>

                  <div className="rounded-md border border-border/45 bg-background/65 p-2.5">
                    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <div className="text-xs font-semibold text-foreground">Manifest diff</div>
                        <div className="text-[10px] text-muted-foreground">
                          Split view of original manifests and copied candidate manifests.
                        </div>
                      </div>
                      {comparisonManifest && (
                        <Badge variant="outline" className={cn("h-5 text-[9px]", comparisonManifest.topology_preserved && "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300")}>
                          topology {comparisonManifest.topology_preserved ? "preserved" : "changed"}
                        </Badge>
                      )}
                    </div>
                    {selectedManifestSection ? (
                      <div className="space-y-2">
                        <div className="flex flex-wrap gap-1.5">
                          {comparisonManifestSections.map((section) => (
                            <Button
                              key={section.id}
                              type="button"
                              variant={section.id === selectedManifestSection.id ? "secondary" : "outline"}
                              size="sm"
                              className="h-6 px-2 text-[10px]"
                              onClick={() => setSelectedManifestSectionId(section.id)}
                            >
                              {section.kind}/{section.candidate_name || section.source_name}
                            </Button>
                          ))}
                        </div>
                        <div className="flex flex-wrap gap-1">
                          {selectedManifestSection.highlights.slice(0, 4).map((highlight) => (
                            <Badge key={highlight} variant="outline" className="h-5 max-w-full truncate text-[9px]">{highlight}</Badge>
                          ))}
                        </div>
                        <div className="overflow-hidden rounded-md border border-border/40 bg-background/70">
                          <div className="grid min-w-[44rem] grid-cols-2 gap-px border-b border-border/40 bg-muted/40 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                            <div className="px-2 py-1">Original · {selectedManifestSection.source_name}</div>
                            <div className="px-2 py-1">Candidate · {selectedManifestSection.candidate_name}</div>
                          </div>
                          <div className="max-h-80 overflow-auto">
                            {selectedManifestSection.diff_rows.length > 0
                              ? renderManifestDiffRows(selectedManifestSection.diff_rows)
                              : (
                                  <div className="grid min-w-[44rem] grid-cols-2 gap-px text-[10px] leading-4">
                                    <pre className="overflow-auto bg-slate-950 p-2 text-slate-100 whitespace-pre-wrap">{selectedManifestSection.source_yaml || "No source manifest available."}</pre>
                                    <pre className="overflow-auto bg-slate-950 p-2 text-slate-100 whitespace-pre-wrap">{selectedManifestSection.candidate_yaml || "No candidate manifest available."}</pre>
                                  </div>
                                )}
                          </div>
                        </div>
                        <div className="rounded border border-border/35 bg-muted/20 p-2">
                          <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                            Changed paths · {selectedManifestSection.change_count}
                          </div>
                          <div className="flex max-h-20 flex-wrap gap-1 overflow-auto">
                            {selectedManifestSection.changed_paths.slice(0, 30).map((path) => (
                              <Badge key={path} variant="outline" className="h-5 max-w-full truncate text-[9px]">{path}</Badge>
                            ))}
                          </div>
                        </div>
                      </div>
                    ) : (
                      <div className="rounded border border-dashed border-border/50 p-4 text-center text-[11px] text-muted-foreground">
                        Manifest diff appears after a candidate is generated.
                      </div>
                    )}
                  </div>
                </div>
              </section>

              <section className="rounded-lg border border-border/50 bg-card/45 p-3">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                      <Target className="h-4 w-4 text-primary" />
                      Ranked optimization levers
                    </div>
                    <p className="text-[11px] text-muted-foreground">
                      {study ? `${study.baseline_execution_ids.length} baseline traces` : `${packet?.trace_details.length ?? 0} local traces`} · {confidenceLevel} confidence · ~{promptEstimate.toLocaleString()} optimizer prompt tokens
                    </p>
                  </div>
                  {(detailsLoading || manifestLoading || studyLoading) && <Badge variant="outline" className="gap-1 text-[10px]"><LoaderCircle className="h-3 w-3 animate-spin" /> loading</Badge>}
                </div>
                <div className="grid gap-2 md:grid-cols-2">
                  {(rankedLevers.length > 0 ? rankedLevers : (packet?.opportunity_map ?? []).map((item) => ({
                    kind: String(item.label ?? "signal"),
                    lever: String(item.label ?? "signal"),
                    severity: String(item.severity ?? "medium"),
                    title: String(item.label ?? "Opportunity"),
                    impact_score: 0,
                    confidence: "local",
                    affected_steps: [] as string[],
                    estimated_savings: {},
                    evidence: { signal: item.signal },
                    recommendation: String(item.recommendation ?? ""),
                    dataset_use: "",
                    safe_scope: "local",
                  }))).map((item) => (
                    <div key={`${item.kind}-${item.title}`} className="rounded-md border border-border/45 bg-background/70 p-2.5">
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex min-w-0 items-center gap-2 text-xs font-semibold text-foreground">
                          {item.kind.includes("token") ? <Gauge className="h-3.5 w-3.5 text-violet-500" /> : <TrendingDown className="h-3.5 w-3.5 text-sky-500" />}
                          <span className="truncate">{item.title}</span>
                        </div>
                        <Badge variant="outline" className={cn(
                          "h-5 text-[9px]",
                          item.severity === "high" ? "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300" : "border-border/50",
                        )}>
                          {item.impact_score ? `${item.impact_score}/100` : item.severity}
                        </Badge>
                      </div>
                      <div className="mt-1 line-clamp-2 text-[10px] text-muted-foreground">{item.recommendation}</div>
                      <div className="mt-2 flex flex-wrap gap-1">
                        <Badge variant="outline" className="h-5 text-[9px]">{item.lever?.replace(/_/g, " ") ?? item.kind}</Badge>
                        <Badge variant="outline" className="h-5 text-[9px]">{item.confidence ?? "unknown"} confidence</Badge>
                        {(item.affected_steps ?? []).slice(0, 2).map((step) => (
                          <Badge key={step} variant="outline" className="h-5 max-w-40 truncate text-[9px]">{step}</Badge>
                        ))}
                      </div>
                      <div className="mt-2 truncate text-[10px] text-muted-foreground">
                        {Object.entries(item.evidence ?? {}).slice(0, 3).map(([key, value]) => `${key}: ${String(value ?? "--")}`).join(" · ")}
                      </div>
                    </div>
                  ))}
                </div>
              </section>

              {(stepRollups.length > 0 || modelRollups.length > 0 || toolRollups.length > 0) && (
                <section className="rounded-lg border border-border/50 bg-card/45 p-3">
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                        <Gauge className="h-4 w-4 text-primary" />
                        Execution economics
                      </div>
                      <p className="text-[11px] text-muted-foreground">
                        Cost, latency, model, and tool pressure by step. Use this to choose what the optimizer should touch first.
                      </p>
                    </div>
                    <Badge variant="outline" className="h-5 text-[10px]">
                      {stepRollups.length} steps · {modelRollups.length} models · {toolRollups.length} tools
                    </Badge>
                  </div>
                  <div className="grid gap-2 lg:grid-cols-3">
                    <div className="rounded-md border border-border/45 bg-background/70 p-2.5">
                      <div className="mb-2 flex items-center justify-between gap-2">
                        <span className="text-xs font-semibold text-foreground">Slowest steps</span>
                        {topStep && <span className="text-[10px] text-muted-foreground">{formatDuration(topStep.avg_duration_ms)}</span>}
                      </div>
                      <div className="space-y-1.5">
                        {stepRollups.slice(0, 4).map((step) => (
                          <div key={step.step_name} className="grid grid-cols-[minmax(0,1fr)_auto] gap-2 rounded border border-border/30 bg-muted/20 px-2 py-1.5 text-[10px]">
                            <div className="min-w-0">
                              <div className="truncate font-medium text-foreground">{step.step_name}</div>
                              <div className="truncate text-muted-foreground">{step.dominant_model || step.agent_name || "agent"} · {metricNumber(step.avg_tokens)} tok</div>
                            </div>
                            <div className="text-right text-muted-foreground">
                              <div>{formatDuration(step.avg_duration_ms)}</div>
                              <div>{metricNumber(step.avg_tool_calls)} tools</div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                    <div className="rounded-md border border-border/45 bg-background/70 p-2.5">
                      <div className="mb-2 flex items-center justify-between gap-2">
                        <span className="text-xs font-semibold text-foreground">Model pressure</span>
                        {topModel && <span className="text-[10px] text-muted-foreground">{metricNumber(topModel.tokens)} tok</span>}
                      </div>
                      <div className="space-y-1.5">
                        {modelRollups.slice(0, 4).map((model) => (
                          <div key={model.model} className="rounded border border-border/30 bg-muted/20 px-2 py-1.5 text-[10px]">
                            <div className="flex items-center justify-between gap-2">
                              <span className="min-w-0 truncate font-medium text-foreground">{model.model}</span>
                              <span className="text-muted-foreground">{model.calls ?? 0} calls</span>
                            </div>
                            <div className="mt-1 flex items-center justify-between gap-2 text-muted-foreground">
                              <span>{metricNumber(model.tokens)} tokens</span>
                              <span>{formatDuration(model.avg_latency_ms)}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                    <div className="rounded-md border border-border/45 bg-background/70 p-2.5">
                      <div className="mb-2 flex items-center justify-between gap-2">
                        <span className="text-xs font-semibold text-foreground">Tool pressure</span>
                        {topTool && <span className="text-[10px] text-muted-foreground">{topTool.calls ?? 0} calls</span>}
                      </div>
                      <div className="space-y-1.5">
                        {toolRollups.slice(0, 4).map((tool) => (
                          <div key={tool.tool_name} className="rounded border border-border/30 bg-muted/20 px-2 py-1.5 text-[10px]">
                            <div className="flex items-center justify-between gap-2">
                              <span className="min-w-0 truncate font-medium text-foreground">{tool.tool_name}</span>
                              <span className="text-muted-foreground">{tool.calls ?? 0} calls</span>
                            </div>
                            <div className="mt-1 flex items-center justify-between gap-2 text-muted-foreground">
                              <span>{tool.repeated_arg_groups ?? 0} repeated args</span>
                              <span>{formatDuration(tool.avg_duration_ms)}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                </section>
              )}

              <section className="rounded-lg border border-border/50 bg-card/45 p-3">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                      <Sparkles className="h-4 w-4 text-primary" />
                      Candidate and safety checks
                    </div>
                    <p className="text-[11px] text-muted-foreground">Copied manifests only. Topology, namespace, and secret expansion are checked server-side.</p>
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Button type="button" size="sm" variant="outline" className="h-7 gap-1 text-[10px]" disabled={!canApprove || actionLoading === "approve"} onClick={onApproveCandidate}>
                      {actionLoading === "approve" ? <LoaderCircle className="h-3 w-3 animate-spin" /> : <ClipboardCheck className="h-3 w-3" />}
                      Approve
                    </Button>
                    <Button type="button" size="sm" variant="outline" className="h-7 gap-1 text-[10px]" disabled={!canDryRun || actionLoading === "dry-run"} onClick={onDryRunApply}>
                      {actionLoading === "dry-run" ? <LoaderCircle className="h-3 w-3 animate-spin" /> : <PlayCircle className="h-3 w-3" />}
                      Dry-run apply
                    </Button>
                  </div>
                </div>

                {activeCandidate ? (
                  <div className="grid gap-3 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
                    <div className="space-y-2">
                      <div className="rounded-md border border-border/45 bg-background/70 p-2">
                        <div className="text-[10px] text-muted-foreground">Candidate workflow</div>
                        <div className="mt-0.5 truncate text-xs font-semibold text-foreground">{activeCandidate.candidate_workflow_name}</div>
                      </div>
                      <div className="grid grid-cols-2 gap-2 text-[10px]">
                        <div className="rounded-md border border-border/45 bg-background/70 p-2">
                          <div className="text-muted-foreground">Resources</div>
                          <div className="mt-0.5 font-semibold text-foreground">{candidateResourceNames.length}</div>
                        </div>
                        <div className="rounded-md border border-border/45 bg-background/70 p-2">
                          <div className="text-muted-foreground">Topology</div>
                          <div className="mt-0.5 font-semibold text-foreground">{String((manifestDiff.topology as Record<string, unknown> | undefined)?.preserved ?? validation.topology_preserved ?? "--")}</div>
                        </div>
                      </div>
                      <div className="space-y-1.5">
                        {candidateResourceNames.map((name) => (
                          <div key={name} className="truncate rounded border border-border/35 bg-muted/25 px-2 py-1 text-[10px] text-muted-foreground">{name}</div>
                        ))}
                      </div>
                    </div>
                    <div className="space-y-2">
                      <div className={cn(
                        "rounded-md border p-2",
                        validation.valid === false ? "border-red-500/30 bg-red-500/10" : "border-emerald-500/25 bg-emerald-500/8",
                      )}>
                        <div className="flex items-center gap-2 text-xs font-semibold text-foreground">
                          {validation.valid === false ? <ShieldAlert className="h-3.5 w-3.5 text-red-500" /> : <ShieldCheck className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" />}
                          Contract gate {validation.valid === false ? "failed" : "passed"}
                        </div>
                        <div className="mt-1 text-[10px] text-muted-foreground">{String(validation.hybrid_gate ?? "Approval, safe trials, and preserved outputs are required before promotion.")}</div>
                      </div>
                      {validationErrors.length > 0 && (
                        <div className="rounded-md border border-red-500/25 bg-red-500/10 p-2 text-[10px] text-red-600 dark:text-red-300">
                          {validationErrors.join(" · ")}
                        </div>
                      )}
                      {validationWarnings.length > 0 && (
                        <div className="rounded-md border border-amber-500/25 bg-amber-500/10 p-2 text-[10px] text-amber-700 dark:text-amber-300">
                          {validationWarnings.join(" · ")}
                        </div>
                      )}
                      <div className="rounded-md border border-border/40 bg-background/70 p-2 text-[10px] text-muted-foreground">
                        <div className="font-medium text-foreground">Manifest comparison</div>
                        <div className="mt-1">
                          {comparisonManifestSections.length > 0
                            ? `${comparisonManifestSections.length} resources available in the split diff above. ${comparisonManifest?.topology_preserved ? "Topology is preserved." : "Topology requires review."}`
                            : `Legacy diff summary: ${JSON.stringify(manifestDiff)}`}
                        </div>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="rounded-md border border-dashed border-border/50 p-8 text-center text-xs text-muted-foreground">
                    No candidate yet. Run the ROI study to persist the baseline and generate an isolated manifest copy.
                  </div>
                )}
              </section>

              <section className="rounded-lg border border-border/50 bg-card/45 p-3">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                      <FlaskConical className="h-4 w-4 text-primary" />
                      Trial proof and ROI
                    </div>
                    <p className="text-[11px] text-muted-foreground">Trials separate estimated savings from verified savings and keep quality review explicit.</p>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    <Button type="button" size="sm" className="h-7 gap-1 text-[10px]" disabled={!canRunCandidate || actionLoading === "candidate-run"} onClick={onRunCandidate}>
                      {actionLoading === "candidate-run" ? <LoaderCircle className="h-3 w-3 animate-spin" /> : <PlayCircle className="h-3 w-3" />}
                      Run candidate
                    </Button>
                    <Button type="button" size="sm" variant="outline" className="h-7 gap-1 text-[10px]" disabled={!activeCandidate || actionLoading === "trial"} onClick={onRecordTrial}>
                      {actionLoading === "trial" ? <LoaderCircle className="h-3 w-3 animate-spin" /> : <CheckCircle2 className="h-3 w-3" />}
                      Link result
                    </Button>
                    <Button type="button" size="sm" variant="outline" className="h-7 gap-1 text-[10px]" disabled={!study || actionLoading === "dataset"} onClick={onExportDataset}>
                      {actionLoading === "dataset" ? <LoaderCircle className="h-3 w-3 animate-spin" /> : <Download className="h-3 w-3" />}
                      Dataset
                    </Button>
                    <Button type="button" size="sm" className="h-7 gap-1 text-[10px]" disabled={!canPromote || actionLoading === "promote"} onClick={onPromoteCandidate}>
                      {actionLoading === "promote" ? <LoaderCircle className="h-3 w-3 animate-spin" /> : <Rocket className="h-3 w-3" />}
                      Promote
                    </Button>
                  </div>
                </div>
                <div className="grid gap-2 md:grid-cols-3">
                  <div className="rounded-md border border-border/45 bg-background/70 p-2">
                    <div className="text-[10px] text-muted-foreground">Confidence</div>
                    <div className="mt-0.5 text-sm font-semibold text-foreground">{roi?.passing_trial_count ?? 0}/{safeTrialTarget} safe trials</div>
                    <div className="mt-1 text-[10px] text-muted-foreground">{(roi?.passing_trial_count ?? 0) >= safeTrialTarget ? "promotion sample met" : `${Math.max(safeTrialTarget - (roi?.passing_trial_count ?? 0), 0)} more needed`}</div>
                  </div>
                  <div className="rounded-md border border-border/45 bg-background/70 p-2">
                    <div className="text-[10px] text-muted-foreground">Monthly estimate</div>
                    <div className="mt-0.5 text-sm font-semibold text-foreground">{money(roi?.projected_savings.monthly_cost_saved_usd)}</div>
                    <div className="mt-1 text-[10px] text-muted-foreground">{metricNumber(roi?.projected_savings.monthly_hours_saved)} hours saved</div>
                  </div>
                  <div className="rounded-md border border-border/45 bg-background/70 p-2">
                    <div className="text-[10px] text-muted-foreground">Yearly estimate</div>
                    <div className="mt-0.5 text-sm font-semibold text-foreground">{money(roi?.projected_savings.yearly_cost_saved_usd)}</div>
                    <div className="mt-1 text-[10px] text-muted-foreground">{metricNumber(roi?.projected_savings.yearly_hours_saved)} hours saved</div>
                  </div>
                </div>
                {trials.length > 0 && (
                  <div className="mt-3 space-y-1.5">
                    {trials.slice(-4).reverse().map((trial) => (
                      <div key={trial.id} className="flex flex-wrap items-center gap-2 rounded-md border border-border/35 bg-background/55 px-2 py-1.5 text-[10px]">
                        <Badge variant="outline" className="h-5 text-[9px]">{trial.quality_status}</Badge>
                        <span className="min-w-0 flex-1 truncate text-foreground">{trial.result_execution_id ? `result ${trial.result_execution_id}` : "pending candidate result"}</span>
                        <span className="text-muted-foreground">{formatCompactDate(trial.created_at)}</span>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            </main>

            <aside className="space-y-3">
              <section className="rounded-lg border border-border/50 bg-card/45 p-3">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                    <Activity className="h-4 w-4 text-primary" />
                    Live run pipeline
                  </div>
                  {running && <Badge variant="outline" className="gap-1 text-[10px]"><LoaderCircle className="h-3 w-3 animate-spin" /> running</Badge>}
                </div>
                <div className="space-y-1.5">
                  {runPhases.map((phase) => {
                    const Icon =
                      phase.status === "running" ? LoaderCircle :
                      phase.status === "success" ? CheckCircle2 :
                      phase.status === "error" ? ShieldAlert :
                      Activity;
                    return (
                      <div
                        key={phase.key}
                        className={cn(
                          "rounded-md border p-2",
                          phase.status === "running" && "border-sky-500/30 bg-sky-500/8",
                          phase.status === "success" && "border-emerald-500/25 bg-emerald-500/8",
                          phase.status === "error" && "border-red-500/30 bg-red-500/10",
                          phase.status === "pending" && "border-border/40 bg-background/60",
                        )}
                      >
                        <div className="flex items-center gap-2">
                          <Icon className={cn(
                            "h-3.5 w-3.5 shrink-0",
                            phase.status === "running" && "animate-spin text-sky-500",
                            phase.status === "success" && "text-emerald-600 dark:text-emerald-400",
                            phase.status === "error" && "text-red-500",
                            phase.status === "pending" && "text-muted-foreground",
                          )} />
                          <span className="min-w-0 flex-1 truncate text-xs font-semibold text-foreground">{phase.label}</span>
                          <span className="text-[9px] uppercase tracking-wide text-muted-foreground">{phase.status}</span>
                        </div>
                        <p className="mt-1 line-clamp-2 text-[10px] leading-4 text-muted-foreground">
                          {phase.detail || phase.description}
                        </p>
                      </div>
                    );
                  })}
                </div>
              </section>

              <section className="rounded-lg border border-border/50 bg-card/45 p-3">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                    <Bot className="h-4 w-4 text-primary" />
                    Optimizer agent
                  </div>
                  {selectedAgent && <Badge variant="outline" className="text-[10px]">{selectedAgent.status}</Badge>}
                </div>
                {selectedAgent ? (
                  <div className="grid gap-2 text-[11px]">
                    <div className="rounded-md border border-border/40 bg-background/65 p-2">
                      <div className="text-muted-foreground">Agent</div>
                      <div className="truncate font-medium text-foreground">{selectedAgent.name}</div>
                    </div>
                    <div className="rounded-md border border-border/40 bg-background/65 p-2">
                      <div className="text-muted-foreground">Model</div>
                      <div className="truncate font-medium text-foreground">{selectedAgent.model || "--"}</div>
                    </div>
                    <div className="rounded-md border border-border/40 bg-background/65 p-2">
                      <div className="text-muted-foreground">Runtime</div>
                      <div className="truncate font-medium text-foreground">{selectedAgent.runtime_kind || "opencode"}</div>
                    </div>
                    {!selectedAgentLooksOptimiser && (
                      <div className="rounded-md border border-red-500/25 bg-red-500/10 p-2 text-[10px] leading-4 text-red-600 dark:text-red-300">
                        Cannot run with a workflow agent. Choose a dedicated workflow optimizer agent that is allowed to analyse traces and propose candidate manifests.
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="rounded-md border border-dashed border-border/50 p-4 text-center text-xs text-muted-foreground">
                    Select an optimizer agent.
                  </div>
                )}
                <div className={cn(
                  "mt-2 rounded-md border p-2",
                  deploymentCapable
                    ? "border-amber-500/30 bg-amber-500/8"
                    : "border-border/40 bg-background/65",
                )}>
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 text-xs font-semibold text-foreground">
                      {deploymentCapable ? <ShieldAlert className="h-3.5 w-3.5 text-amber-500" /> : <ShieldCheck className="h-3.5 w-3.5 text-muted-foreground" />}
                      Permission guard
                    </div>
                    <Badge variant="outline" className={cn(
                      "h-5 text-[9px]",
                      deploymentCapable && "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
                    )}>
                      {accessLevel}
                    </Badge>
                  </div>
                  <div className="mt-2 grid grid-cols-2 gap-1.5 text-[10px]">
                    <div className="rounded border border-border/35 bg-background/60 px-2 py-1">
                      <div className="text-muted-foreground">Scope</div>
                      <div className="truncate font-medium text-foreground">{accessScope}</div>
                    </div>
                    <div className="rounded border border-border/35 bg-background/60 px-2 py-1">
                      <div className="text-muted-foreground">Apply/run</div>
                      <div className="truncate font-medium text-foreground">{deploymentCapable ? "approval gated" : "not allowed"}</div>
                    </div>
                  </div>
                  <p className="mt-2 text-[10px] leading-4 text-muted-foreground">
                    {accessGuard}. The gateway applies and runs only copied candidate manifests after admin approval; source workflows are never edited.
                  </p>
                </div>
                {manifestError && (
                  <div className="mt-2 rounded-md border border-red-500/25 bg-red-500/10 px-2 py-1.5 text-[11px] text-red-500">
                    {manifestError}
                  </div>
                )}
              </section>

              {datasetReadiness && (
                <section className="rounded-lg border border-border/50 bg-card/45 p-3">
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                      <Database className="h-4 w-4 text-primary" />
                      Dataset factory
                    </div>
                    <Badge variant="outline" className="text-[10px]">{datasetReadiness.state.replace(/_/g, " ")}</Badge>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-[10px]">
                    <div className="rounded-md border border-border/40 bg-background/65 p-2">
                      <div className="text-muted-foreground">Baseline traces</div>
                      <div className="mt-0.5 text-sm font-semibold text-foreground">{datasetReadiness.baseline_examples ?? 0}</div>
                    </div>
                    <div className="rounded-md border border-border/40 bg-background/65 p-2">
                      <div className="text-muted-foreground">LLM examples</div>
                      <div className="mt-0.5 text-sm font-semibold text-foreground">{datasetReadiness.llm_examples ?? 0}</div>
                    </div>
                    <div className="rounded-md border border-border/40 bg-background/65 p-2">
                      <div className="text-muted-foreground">Replay cases</div>
                      <div className="mt-0.5 text-sm font-semibold text-foreground">{metricNumber(datasetSplits.replay_cases)}</div>
                    </div>
                    <div className="rounded-md border border-border/40 bg-background/65 p-2">
                      <div className="text-muted-foreground">Distillation</div>
                      <div className="mt-0.5 text-sm font-semibold text-foreground">{metricNumber(datasetSplits.distillation_examples)}</div>
                    </div>
                  </div>
                  <div className="mt-2 rounded-md border border-border/40 bg-background/65 p-2 text-[10px]">
                    <div className="font-semibold text-foreground">Local model path</div>
                    <div className="mt-1 text-muted-foreground">
                      {String(localModelPath.suitability ?? "needs_more_examples").replace(/_/g, " ")} · {String(localModelPath.target ?? "tenant-local evaluator or router")}
                    </div>
                  </div>
                </section>
              )}

              {diagnostics.length > 0 && (
                <section className="rounded-lg border border-border/50 bg-card/45 p-3">
                  <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-foreground">
                    <Lightbulb className="h-4 w-4 text-amber-500" />
                    Trajectory diagnostics
                  </div>
                  <div className="space-y-1.5">
                    {diagnostics.slice(0, 4).map((diagnostic) => (
                      <div key={diagnostic.id} className="rounded-md border border-border/40 bg-background/65 p-2">
                        <div className="flex items-center justify-between gap-2">
                          <span className="min-w-0 truncate text-xs font-semibold text-foreground">{diagnostic.title}</span>
                          <Badge variant="outline" className={cn(
                            "h-5 text-[9px]",
                            diagnostic.severity === "high" ? "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300" : "border-border/50",
                          )}>
                            {diagnostic.severity}
                          </Badge>
                        </div>
                        {diagnostic.optimizer_hint && (
                          <p className="mt-1 line-clamp-2 text-[10px] leading-4 text-muted-foreground">{diagnostic.optimizer_hint}</p>
                        )}
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {(error || studyError) && (
                <div className="rounded-lg border border-red-500/25 bg-red-500/10 p-3 text-xs text-red-500">
                  {error || studyError}
                </div>
              )}

              <section className="rounded-lg border border-border/50 bg-card/45 p-3">
                <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-foreground">
                  <Sparkles className="h-4 w-4 text-primary" />
                  Candidate reasoning
                </div>
                {running ? (
                  <div className="flex items-center justify-center gap-2 rounded-md border border-border/40 bg-background/60 py-8 text-xs text-muted-foreground">
                    <LoaderCircle className="h-4 w-4 animate-spin" />
                    Agent analysis running
                  </div>
                ) : result ? (
                  <div className="space-y-2">
                    <div className="grid grid-cols-2 gap-2 text-[10px]">
                      <div className="rounded-md border border-border/40 bg-background/65 p-2">
                        <div className="text-muted-foreground">Thread</div>
                        <div className="truncate font-medium text-foreground">{result.thread_id}</div>
                      </div>
                      <div className="rounded-md border border-border/40 bg-background/65 p-2">
                        <div className="text-muted-foreground">Model</div>
                        <div className="truncate font-medium text-foreground">{result.model}</div>
                      </div>
                    </div>
                    <div className="rounded-md border border-border/40 bg-background/65 p-2 text-[11px] text-muted-foreground">
                      Candidate generated from the selected trace packet. Use the ranked levers and proof gate above for the product decision; keep the full agent response as audit context.
                    </div>
                    <details className="rounded-md border border-border/40 bg-background/65 p-2">
                      <summary className="cursor-pointer text-xs font-medium text-foreground">Full optimizer response</summary>
                      <pre className="mt-2 max-h-64 overflow-auto rounded-md border border-border/30 bg-background/80 p-2 text-[10px] leading-relaxed whitespace-pre-wrap text-foreground/90">{result.response}</pre>
                    </details>
                  </div>
                ) : (
                  <div className="rounded-md border border-dashed border-border/50 p-4 text-center text-xs text-muted-foreground">
                    Run the study to get candidate reasoning.
                  </div>
                )}
              </section>

              <section className="rounded-lg border border-border/50 bg-card/45 p-3">
                <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-foreground">
                  <Database className="h-4 w-4 text-primary" />
                  Inspectors
                </div>
                <div className="space-y-2">
                  {applyPreview && (
                    <details className="rounded-md border border-border/40 bg-background/65 p-2">
                      <summary className="cursor-pointer text-xs font-medium text-foreground">Apply preview</summary>
                      <pre className="mt-2 max-h-48 overflow-auto text-[10px] text-muted-foreground whitespace-pre-wrap">{JSON.stringify(applyPreview, null, 2)}</pre>
                    </details>
                  )}
                  {datasetPreview && (
                    <details className="rounded-md border border-border/40 bg-background/65 p-2" open>
                      <summary className="cursor-pointer text-xs font-medium text-foreground">Redacted dataset</summary>
                      <pre className="mt-2 max-h-48 overflow-auto text-[10px] text-muted-foreground whitespace-pre-wrap">{JSON.stringify(datasetPreview, null, 2)}</pre>
                    </details>
                  )}
                  <details className="rounded-md border border-border/40 bg-background/65 p-2">
                    <summary className="cursor-pointer text-xs font-medium text-foreground">Optimizer packet</summary>
                    <div className="mt-2 flex items-center justify-between text-[10px] text-muted-foreground">
                      <span>{packet?.trace_details.length ?? 0} traces · {Object.keys(packet?.source_manifests.agents ?? {}).length} agents</span>
                      <CopyButton value={prompt} className="h-6 w-6" />
                    </div>
                    {promptWasCompacted && (
                      <div className="mt-2 rounded-md border border-sky-500/25 bg-sky-500/8 px-2 py-1 text-[10px] text-sky-700 dark:text-sky-300">
                        Prompt compacted to fit the opencode runtime; full traces remain available in the execution inspectors.
                      </div>
                    )}
                    <Textarea
                      readOnly
                      value={prompt}
                      className="mt-2 min-h-52 resize-none border-border/60 bg-background/80 font-mono text-[10px] leading-relaxed"
                    />
                  </details>
                </div>
              </section>
            </aside>
          </div>
        </div>
      </ScrollArea>
    </div>
  );
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
  const [selectedLLM, setSelectedLLM] = useState<LLMCallRecord | null>(null);
  const [llmViewerOpen, setLlmViewerOpen] = useState(false);
  const [selectedDetailItem, setSelectedDetailItem] = useState<DetailItem | null>(null);
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
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);
  const [optimiseAgents, setOptimiseAgents] = useState<AgentInfo[]>([]);
  const [optimiseAgentsLoading, setOptimiseAgentsLoading] = useState(false);
  const [optimiseAgentName, setOptimiseAgentName] = useState("");
  const [optimiseScope, setOptimiseScope] = useState<OptimisationScope>("last6");
  const [optimiseDetails, setOptimiseDetails] = useState<ExecutionTrace[]>([]);
  const [optimiseDetailsLoading, setOptimiseDetailsLoading] = useState(false);
  const [optimiseWorkflowManifest, setOptimiseWorkflowManifest] = useState<Record<string, unknown> | null>(null);
  const [optimiseAgentManifests, setOptimiseAgentManifests] = useState<Record<string, Record<string, unknown>>>({});
  const [optimiseManifestLoading, setOptimiseManifestLoading] = useState(false);
  const [optimiseManifestError, setOptimiseManifestError] = useState("");
  const [optimiseRunning, setOptimiseRunning] = useState(false);
  const [optimiseRunPhases, setOptimiseRunPhases] = useState<OptimisationRunPhase[]>(() => createOptimiseRunPhases());
  const [optimiseResult, setOptimiseResult] = useState<InvokeResponse | null>(null);
  const [optimiseError, setOptimiseError] = useState("");
  const [optimiseStudy, setOptimiseStudy] = useState<OptimizationStudy | null>(null);
  const [optimiseCandidate, setOptimiseCandidate] = useState<OptimizationCandidate | null>(null);
  const [optimiseRoi, setOptimiseRoi] = useState<OptimizationRoi | null>(null);
  const [optimiseComparison, setOptimiseComparison] = useState<OptimizationComparison | null>(null);
  const [optimiseStudyLoading, setOptimiseStudyLoading] = useState(false);
  const [optimiseStudyError, setOptimiseStudyError] = useState("");
  const [optimiseActionLoading, setOptimiseActionLoading] = useState<string | null>(null);
  const [optimiseApplyPreview, setOptimiseApplyPreview] = useState<Record<string, unknown> | null>(null);
  const [optimiseDatasetPreview, setOptimiseDatasetPreview] = useState<Record<string, unknown> | null>(null);
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

  // Load selectable optimisation agents
  useEffect(() => {
    let cancelled = false;
    setOptimiseAgentsLoading(true);
    listAgents(token, namespace)
      .then((items) => {
        if (cancelled) return;
        setOptimiseAgents(items);
      })
      .catch((error) => {
        if (cancelled) return;
        setOptimiseAgents([]);
        toast.error(error instanceof Error ? error.message : "Failed to load optimisation agents");
      })
      .finally(() => { if (!cancelled) setOptimiseAgentsLoading(false); });
    return () => { cancelled = true; };
  }, [namespace, token]);

  useEffect(() => {
    const current = optimiseAgents.find((agent) => agent.name === optimiseAgentName) ?? null;
    const preferred = chooseDefaultOptimiserAgent(optimiseAgents, detail?.agent_name);
    if (
      current &&
      (
        current.name !== detail?.agent_name ||
        isOptimiserAgentCandidate(current) ||
        !preferred ||
        preferred.name === current.name
      )
    ) {
      return;
    }
    setOptimiseAgentName(preferred?.name ?? "");
  }, [detail?.agent_name, optimiseAgentName, optimiseAgents]);

  // Load detailed traces for the optimisation scope only when the tab is active.
  useEffect(() => {
    if (!detail) {
      setOptimiseDetails([]);
      setOptimiseDetailsLoading(false);
      return;
    }
    if (activeTab !== "optimise") {
      setOptimiseDetails([detail]);
      setOptimiseDetailsLoading(false);
      return;
    }

    const limit = optimisationScopeLimit(optimiseScope);
    const ids = Array.from(new Set([detail.id, ...executions.map((execution) => execution.id).filter(Boolean)])).slice(0, limit);
    let cancelled = false;
    setOptimiseDetailsLoading(true);
    Promise.all(ids.map((id) => (id === detail.id ? Promise.resolve(detail) : fetchExecutionDetail(token, id).catch(() => null))))
      .then((items) => {
        if (cancelled) return;
        const traces = items.filter((item): item is ExecutionTrace => item !== null);
        setOptimiseDetails(traces.length > 0 ? traces : [detail]);
      })
      .finally(() => { if (!cancelled) setOptimiseDetailsLoading(false); });
    return () => { cancelled = true; };
  }, [activeTab, detail, executions, optimiseScope, token]);

  // Load source Kubernetes manifests for manifest-copy optimisation.
  useEffect(() => {
    if (!selectedWorkflowName || activeTab !== "optimise") {
      return;
    }
    let cancelled = false;
    setOptimiseManifestLoading(true);
    setOptimiseManifestError("");
    (async () => {
      let workflowManifest: Record<string, unknown> | null = null;
      const agentManifests: Record<string, Record<string, unknown>> = {};
      const missingAgents: string[] = [];
      try {
        workflowManifest = await fetchWorkflowManifest(token, namespace, selectedWorkflowName);
      } catch (error) {
        if (!cancelled) setOptimiseManifestError(error instanceof Error ? error.message : "Failed to load workflow manifest");
      }

      const candidateAgents = Array.from(new Set([
        ...extractWorkflowAgentRefs(workflowManifest),
        detail?.agent_name ?? "",
      ].filter((name) => name.trim())));

      for (const agentName of candidateAgents) {
        try {
          agentManifests[agentName] = await fetchAgentManifest(token, namespace, agentName);
        } catch {
          // Some traces expose the workflow name as the actor. Keep the workflow manifest even if one ref is not an AIAgent.
          missingAgents.push(agentName);
        }
      }

      if (!cancelled) {
        setOptimiseWorkflowManifest(workflowManifest);
        setOptimiseAgentManifests(agentManifests);
        if (workflowManifest && Object.keys(agentManifests).length === 0 && candidateAgents.length > 0) {
          setOptimiseManifestError(`Workflow manifest loaded, but no agent manifest matched: ${candidateAgents.join(", ")}`);
        } else if (missingAgents.length > 0) {
          setOptimiseManifestError(`Loaded ${Object.keys(agentManifests).length} agent manifest(s); skipped ${missingAgents.join(", ")}.`);
        }
      }
    })().finally(() => { if (!cancelled) setOptimiseManifestLoading(false); });
    return () => { cancelled = true; };
  }, [activeTab, detail?.agent_name, namespace, selectedWorkflowName, token]);

  // Reset filters on run change
  useEffect(() => {
    setSelectedEventId(null); setSelectedLogStep("all");
    setLogSearch(""); setLogFilterMode("activity");
    setSelectedStepId(null);
    setSelectedDetailItem(null);
    setOptimiseResult(null); setOptimiseError("");
    setOptimiseStudy(null); setOptimiseCandidate(null); setOptimiseRoi(null); setOptimiseComparison(null); setOptimiseStudyError("");
    setOptimiseActionLoading(null); setOptimiseApplyPreview(null); setOptimiseDatasetPreview(null);
    setOptimiseWorkflowManifest(null); setOptimiseAgentManifests({}); setOptimiseManifestError("");
    setOptimiseRunPhases(createOptimiseRunPhases());
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
  const optimisePacket = useMemo(() => {
    if (!detail) return null;
    return buildOptimisationPacket({
      detail,
      orderedSteps,
      orderedEvents,
      executions,
      scopedDetails: optimiseDetails,
      workflowManifest: optimiseWorkflowManifest,
      agentManifests: optimiseAgentManifests,
      namespace,
      workflowName: selectedWorkflowName,
      selectedAgent: optimiseAgentName || null,
      scope: optimiseScope,
    });
  }, [detail, executions, namespace, optimiseAgentManifests, optimiseAgentName, optimiseDetails, optimiseScope, optimiseWorkflowManifest, orderedEvents, orderedSteps, selectedWorkflowName]);
  const optimisePrompt = useMemo(() => (optimisePacket ? buildOptimisationPrompt(optimisePacket) : ""), [optimisePacket]);

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

  const refreshOptimisationStudy = useCallback(async (studyId?: string | null, candidateId?: string | null) => {
    const targetStudyId = studyId ?? optimiseStudy?.id;
    if (!targetStudyId) return;
    setOptimiseStudyLoading(true);
    setOptimiseStudyError("");
    try {
      const nextStudy = await fetchOptimizationStudy(token, targetStudyId);
      const nextCandidate =
        nextStudy.candidates?.find((item) => item.id === (candidateId ?? optimiseCandidate?.id)) ??
        nextStudy.candidates?.[nextStudy.candidates.length - 1] ??
        optimiseCandidate;
      const nextComparison = nextCandidate
        ? await fetchOptimizationComparison(token, targetStudyId, nextCandidate.id)
        : null;
      const nextRoi = nextComparison?.roi ?? await fetchOptimizationRoi(token, targetStudyId, nextCandidate?.id);
      setOptimiseStudy(nextStudy);
      setOptimiseCandidate(nextCandidate ?? null);
      setOptimiseRoi(nextRoi);
      setOptimiseComparison(nextComparison?.comparison ?? null);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to refresh optimization study";
      setOptimiseStudyError(message);
      toast.error(message);
    } finally {
      setOptimiseStudyLoading(false);
    }
  }, [optimiseCandidate, optimiseStudy?.id, token]);

  const updateOptimiseRunPhase = useCallback((
    key: OptimisationRunPhaseKey,
    status: OptimisationRunPhaseStatus,
    detailText?: string,
  ) => {
    setOptimiseRunPhases((phases) => phases.map((phase) => (
      phase.key === key
        ? { ...phase, status, detail: detailText ?? phase.detail }
        : phase
    )));
  }, []);

  const handleRunOptimisation = async () => {
    if (!optimiseAgentName || !optimisePrompt || !detail) return;
    setOptimiseRunPhases(createOptimiseRunPhases());
    updateOptimiseRunPhase("prepare", "running", "Collecting selected runs, manifests, and optimization guardrails.");
    const baselineExecutionIds = Array.from(
      new Set((optimiseDetails.length > 0 ? optimiseDetails : [detail]).map((trace) => trace.id).filter(Boolean)),
    ).slice(0, optimisationScopeLimit(optimiseScope));
    if (baselineExecutionIds.length === 0) {
      const message = "No baseline executions are available for the optimization study";
      setOptimiseError(message);
      updateOptimiseRunPhase("prepare", "error", message);
      toast.error(message);
      return;
    }
    const selectedAgentForRun = optimiseAgents.find((agent) => agent.name === optimiseAgentName) ?? null;
    if (selectedAgentForRun && !isOptimiserAgentCandidate(selectedAgentForRun)) {
      const message = "Cannot run with a workflow agent. Choose a dedicated workflow optimizer agent before starting the ROI study.";
      setOptimiseError(message);
      updateOptimiseRunPhase("prepare", "error", message);
      toast.error(message);
      return;
    }

    setOptimiseRunning(true);
    setOptimiseError("");
    setOptimiseResult(null);
    setOptimiseStudyError("");
    setOptimiseApplyPreview(null);
    setOptimiseDatasetPreview(null);
    try {
      const sourceManifests = optimiseWorkflowManifest
        ? (() => {
            const agentRefs = extractWorkflowAgentRefs(optimiseWorkflowManifest);
            const primaryAgentName =
              (detail.agent_name && optimiseAgentManifests[detail.agent_name] ? detail.agent_name : null) ??
              agentRefs.find((agentRef) => Boolean(optimiseAgentManifests[agentRef])) ??
              null;
            return {
              workflow: optimiseWorkflowManifest,
              agent_refs: agentRefs,
              agents: optimiseAgentManifests,
              primary_agent: primaryAgentName ? optimiseAgentManifests[primaryAgentName] ?? null : null,
            };
          })()
        : undefined;
      updateOptimiseRunPhase(
        "prepare",
        "success",
        `${baselineExecutionIds.length} baseline trace${baselineExecutionIds.length === 1 ? "" : "s"} · ${Object.keys(optimiseAgentManifests).length} agent manifest${Object.keys(optimiseAgentManifests).length === 1 ? "" : "s"} · ~${Math.ceil(optimisePrompt.length / 4).toLocaleString()} prompt tokens.`,
      );

      updateOptimiseRunPhase("study", "running", "Creating the persisted ROI study and server-side run intelligence.");
      let study: OptimizationStudy;
      try {
        study = await createOptimizationStudy(token, {
          namespace,
          workflow_name: selectedWorkflowName || detail.workflow_name,
          optimizer_agent_name: optimiseAgentName,
          baseline_execution_ids: baselineExecutionIds,
          objective: "Reduce token spend, wall-clock time, tool churn, and failure risk while preserving workflow contracts.",
          source_manifests: sourceManifests,
        });
      } catch (error) {
        const message = `Baseline study creation failed: ${error instanceof Error ? error.message : "unknown error"}`;
        updateOptimiseRunPhase("study", "error", message);
        setOptimiseError(message);
        toast.error(message);
        return;
      }
      setOptimiseStudy(study);
      updateOptimiseRunPhase("study", "success", `${study.baseline_execution_ids.length} traces persisted; ${study.opportunities.length} server-ranked levers.`);

      let result: InvokeResponse;
      updateOptimiseRunPhase("agent", "running", `Invoking ${optimiseAgentName} with the compact workflow intelligence dossier.`);
      try {
        result = await invokeAgent(
          token,
          namespace,
          optimiseAgentName,
          {
            prompt: optimisePrompt,
            no_session: true,
            autonomous: false,
            max_turns: 6,
            output_format: "markdown",
          },
          `optimise-${detail.id}-${Date.now()}`,
        );
      } catch (error) {
        const message = `Optimizer agent invocation failed after the baseline study was created: ${error instanceof Error ? error.message : "unknown error"}`;
        updateOptimiseRunPhase("agent", "error", message);
        setOptimiseError(message);
        toast.error(message);
        return;
      }
      setOptimiseResult(result);
      updateOptimiseRunPhase("agent", "success", `Optimizer returned ${(result.response ?? "").length.toLocaleString()} characters of analysis and candidate material.`);

      let candidate: OptimizationCandidate;
      updateOptimiseRunPhase("candidate", "running", "Parsing candidate_manifest_bundle, creating copied resources, and running contract validation.");
      try {
        candidate = await generateOptimizationCandidate(token, study.id, {
          optimizer_output: result.response,
          suffix: `opt-${study.id.slice(-5)}`,
          expected_savings: extractOptimiserExpectedSavings(result.response),
        });
      } catch (error) {
        const message = `Candidate generation failed after optimizer analysis completed: ${error instanceof Error ? error.message : "unknown error"}`;
        updateOptimiseRunPhase("candidate", "error", message);
        setOptimiseError(message);
        toast.error(message);
        return;
      }
      setOptimiseCandidate(candidate);
      updateOptimiseRunPhase("candidate", "success", `${candidate.candidate_workflow_name} created as a copied candidate; ${candidate.manifest_bundle.length} resources passed validation.`);
      updateOptimiseRunPhase("roi", "running", "Refreshing ROI proof state and trial economics.");
      const roi = await fetchOptimizationRoi(token, study.id, candidate.id);
      setOptimiseRoi(roi);
      await refreshOptimisationStudy(study.id, candidate.id);
      const roiSafeTrialTarget = typeof roi.proof_gate.minimum_safe_trials === "number" ? roi.proof_gate.minimum_safe_trials : 5;
      updateOptimiseRunPhase("roi", "success", `${roi.proof_status.replace(/_/g, " ")} · ${roi.passing_trial_count}/${roiSafeTrialTarget} safe trials.`);
      toast.success("Optimization study and candidate created");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Optimization study failed";
      setOptimiseError(message);
      updateOptimiseRunPhase("roi", "error", message);
      toast.error(message);
    } finally {
      setOptimiseRunning(false);
    }
  };

  const handleApproveOptimisationCandidate = async () => {
    if (!optimiseCandidate) return;
    setOptimiseActionLoading("approve");
    setOptimiseStudyError("");
    try {
      const approved = await approveOptimizationCandidate(
        token,
        optimiseCandidate.id,
        "approved",
        "Approved for isolated candidate dry-run and trial execution.",
      );
      setOptimiseCandidate(approved);
      await refreshOptimisationStudy(approved.study_id, approved.id);
      toast.success("Candidate approved");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to approve candidate";
      setOptimiseStudyError(message);
      toast.error(message);
    } finally {
      setOptimiseActionLoading(null);
    }
  };

  const handleDryRunOptimisationApply = async () => {
    if (!optimiseCandidate) return;
    setOptimiseActionLoading("dry-run");
    setOptimiseStudyError("");
    try {
      const preview = await applyOptimizationCandidate(token, optimiseCandidate.id, true);
      setOptimiseApplyPreview(preview);
      toast.success("Candidate dry-run preview ready");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Dry-run apply failed";
      setOptimiseStudyError(message);
      toast.error(message);
    } finally {
      setOptimiseActionLoading(null);
    }
  };

  const handleRunOptimisationCandidate = async () => {
    if (!optimiseCandidate || !optimiseStudy || !detail) return;
    const baselineExecutionId = optimiseStudy.baseline_execution_ids?.[0] ?? detail.id;
    const workflowSpec =
      optimiseWorkflowManifest?.spec && typeof optimiseWorkflowManifest.spec === "object" && !Array.isArray(optimiseWorkflowManifest.spec)
        ? optimiseWorkflowManifest.spec as Record<string, unknown>
        : {};
    const workflowInput = typeof workflowSpec.input === "string" ? workflowSpec.input : null;
    setOptimiseActionLoading("candidate-run");
    setOptimiseStudyError("");
    try {
      const launched = await runOptimizationCandidate(token, optimiseCandidate.id, {
        baseline_execution_id: baselineExecutionId,
        input: workflowInput,
        notes: "Launched from Optimize ROI Lab after admin approval.",
      });
      setOptimiseCandidate(launched.candidate);
      setOptimiseApplyPreview(launched as unknown as Record<string, unknown>);
      await refreshOptimisationStudy(launched.candidate.study_id, launched.candidate.id);
      const runId = typeof launched.candidate_run.run_id === "string" && launched.candidate_run.run_id
        ? ` (${launched.candidate_run.run_id})`
        : "";
      toast.success(`Candidate workflow launched${runId}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to run candidate";
      setOptimiseStudyError(message);
      toast.error(message);
    } finally {
      setOptimiseActionLoading(null);
    }
  };

  const handleRecordOptimisationTrial = async () => {
    if (!optimiseCandidate || !detail) return;
    const baselineExecutionId = optimiseStudy?.baseline_execution_ids?.[0] ?? detail.id;
    const isCandidateExecution = detail.workflow_name === optimiseCandidate.candidate_workflow_name;
    setOptimiseActionLoading("trial");
    setOptimiseStudyError("");
    try {
      await createOptimizationTrial(token, optimiseCandidate.id, {
        baseline_execution_id: baselineExecutionId,
        result_execution_id: isCandidateExecution ? detail.id : null,
        quality_status: isCandidateExecution ? "human_passed" : "needs_review",
        notes: isCandidateExecution
          ? "Selected execution recorded as a reviewed candidate trial."
          : "Trial placeholder recorded. Run/select the copied candidate workflow execution to verify ROI.",
      });
      await refreshOptimisationStudy(optimiseCandidate.study_id, optimiseCandidate.id);
      toast.success(isCandidateExecution ? "Candidate trial recorded" : "Trial placeholder recorded");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to record trial";
      setOptimiseStudyError(message);
      toast.error(message);
    } finally {
      setOptimiseActionLoading(null);
    }
  };

  const handleExportOptimisationDataset = async () => {
    if (!optimiseStudy) return;
    setOptimiseActionLoading("dataset");
    setOptimiseStudyError("");
    try {
      const dataset = await exportOptimizationDataset(token, optimiseStudy.id, true);
      setOptimiseDatasetPreview(dataset);
      const blob = new Blob([JSON.stringify(dataset, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `optimization-dataset-${optimiseStudy.id}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
      toast.success("Redacted optimization dataset exported");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to export dataset";
      setOptimiseStudyError(message);
      toast.error(message);
    } finally {
      setOptimiseActionLoading(null);
    }
  };

  const handlePromoteOptimisationCandidate = async () => {
    if (!optimiseCandidate) return;
    setOptimiseActionLoading("promote");
    setOptimiseStudyError("");
    try {
      await promoteOptimizationCandidate(
        token,
        optimiseCandidate.id,
        "Promoted from ROI Lab after verified safe trials and preserved workflow contracts.",
      );
      await refreshOptimisationStudy(optimiseCandidate.study_id, optimiseCandidate.id);
      toast.success("Optimization candidate promoted");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to promote candidate";
      setOptimiseStudyError(message);
      toast.error(message);
    } finally {
      setOptimiseActionLoading(null);
    }
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
                    <Activity className="mr-1.5 h-3.5 w-3.5" />
                    Timeline
                  </TabsTrigger>
                  <TabsTrigger value="analytics" className="relative h-9 rounded-none border-b-2 border-transparent px-3 text-xs font-medium transition-colors data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none">
                    <BarChart3 className="mr-1.5 h-3.5 w-3.5" />
                    Analytics
                  </TabsTrigger>
                  <TabsTrigger value="trace" className="relative h-9 rounded-none border-b-2 border-transparent px-3 text-xs font-medium transition-colors data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none">
                    <BrainCircuit className="mr-1.5 h-3.5 w-3.5" />
                    Trace
                    {detail && <Badge variant="secondary" className="ml-1.5 h-4 px-1 text-[9px]">{detail.llm_call_count + detail.tool_call_count}</Badge>}
                  </TabsTrigger>
                  <TabsTrigger value="optimise" className="relative h-9 rounded-none border-b-2 border-transparent px-3 text-xs font-medium transition-colors data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none">
                    <TrendingDown className="mr-1.5 h-3.5 w-3.5" />
                    Optimise
                  </TabsTrigger>
                  <TabsTrigger value="logs" className="relative h-9 rounded-none border-b-2 border-transparent px-3 text-xs font-medium transition-colors data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none">
                    <FileText className="mr-1.5 h-3.5 w-3.5" />
                    Logs
                    {logStats.errors > 0 && <Badge variant="destructive" className="ml-1.5 h-4 px-1 text-[9px]">{logStats.errors}</Badge>}
                  </TabsTrigger>
                  <TabsTrigger value="compare" className="relative h-9 rounded-none border-b-2 border-transparent px-3 text-xs font-medium transition-colors data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none">
                    <GitCompare className="mr-1.5 h-3.5 w-3.5" />
                    Compare
                  </TabsTrigger>
                </TabsList>
              </div>

              {/* ═══════ TIMELINE TAB ═══════ */}
              <TabsContent value="timeline" className="mt-0 min-h-0 flex-1 overflow-hidden">
                <div className="grid h-full min-h-0 grid-cols-[minmax(0,1fr)_minmax(320px,0.34fr)] overflow-hidden">
                  <ExecutionTimelineView
                    detail={detail}
                    selectedItemId={selectedDetailItem?.item.id ?? selectedStepId}
                    onStepClick={(step) => {
                      setSelectedStepId(step.id);
                      setSelectedDetailItem({ type: "step", item: step });
                    }}
                    onLLMClick={(call) => {
                      setSelectedLLM(call);
                      setSelectedDetailItem({ type: "llm", item: call });
                    }}
                    onToolClick={(call) => {
                      setSelectedDetailItem({ type: "tool", item: call });
                    }}
                  />
                  {selectedDetailItem ? (
                    <DetailDrawer detail={selectedDetailItem} onClose={() => setSelectedDetailItem(null)} />
                  ) : (
                    <div className="flex min-h-0 flex-col border-l border-border/40 bg-muted/10">
                      <div className="border-b border-border/40 px-5 py-4">
                        <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Inspector</div>
                        <div className="mt-0.5 text-base font-semibold text-foreground">Select an execution item</div>
                      </div>
                      <div className="flex flex-1 items-center justify-center p-6 text-center text-sm text-muted-foreground">
                        Pick a step, LLM call, or tool call in the timeline to inspect reasoning, prompts, outputs, and timing.
                      </div>
                    </div>
                  )}
                </div>
              </TabsContent>

              {/* ═══════ ANALYTICS TAB ═══════ */}
              <TabsContent value="analytics" className="mt-0 min-h-0 flex-1 overflow-y-auto">
                <AnalyticsView
                  detail={detail}
                  run={selectedRun}
                  previousRuns={runs}
                  onStepClick={(step) => {
                    setSelectedStepId(step.id);
                    setSelectedDetailItem({ type: "step", item: step });
                    setActiveTab("timeline");
                  }}
                />
              </TabsContent>

              {/* ═══════ TRACE TAB ═══════ */}
              <TabsContent value="trace" className="mt-0 min-h-0 flex-1 overflow-hidden">
                <TraceExplorer
                  detail={detail}
                  orderedSteps={orderedSteps}
                  orderedEvents={orderedEvents}
                  selectedStepId={selectedStepId}
                  onStepSelect={setSelectedStepId}
                  selectedEventId={selectedEventId}
                  onEventSelect={setSelectedEventId}
                  onOpenLLM={(call) => { setSelectedLLM(call); setLlmViewerOpen(true); }}
                />
              </TabsContent>

              {/* ═══════ OPTIMISE TAB ═══════ */}
              <TabsContent value="optimise" className="mt-0 min-h-0 flex-1 overflow-hidden">
                <OptimisePanel
                  detail={detail}
                  agents={optimiseAgents}
                  agentsLoading={optimiseAgentsLoading}
                  selectedAgentName={optimiseAgentName}
                  onSelectedAgentChange={(agentName) => {
                    setOptimiseAgentName(agentName);
                    setOptimiseResult(null); setOptimiseError("");
                    setOptimiseStudy(null); setOptimiseCandidate(null); setOptimiseRoi(null); setOptimiseComparison(null); setOptimiseStudyError("");
                    setOptimiseApplyPreview(null); setOptimiseDatasetPreview(null);
                    setOptimiseRunPhases(createOptimiseRunPhases());
                  }}
                  scope={optimiseScope}
                  onScopeChange={(scopeValue) => {
                    setOptimiseScope(scopeValue);
                    setOptimiseResult(null); setOptimiseError("");
                    setOptimiseStudy(null); setOptimiseCandidate(null); setOptimiseRoi(null); setOptimiseComparison(null); setOptimiseStudyError("");
                    setOptimiseApplyPreview(null); setOptimiseDatasetPreview(null);
                    setOptimiseRunPhases(createOptimiseRunPhases());
                  }}
                  packet={optimisePacket}
                  prompt={optimisePrompt}
                  detailsLoading={optimiseDetailsLoading}
                  manifestLoading={optimiseManifestLoading}
                  manifestError={optimiseManifestError}
                  running={optimiseRunning}
                  runPhases={optimiseRunPhases}
                  result={optimiseResult}
                  error={optimiseError}
                  study={optimiseStudy}
                  candidate={optimiseCandidate}
                  roi={optimiseRoi}
                  comparison={optimiseComparison}
                  studyLoading={optimiseStudyLoading}
                  studyError={optimiseStudyError}
                  actionLoading={optimiseActionLoading}
                  applyPreview={optimiseApplyPreview}
                  datasetPreview={optimiseDatasetPreview}
                  onRun={() => { void handleRunOptimisation(); }}
                  onApproveCandidate={() => { void handleApproveOptimisationCandidate(); }}
                  onDryRunApply={() => { void handleDryRunOptimisationApply(); }}
                  onRunCandidate={() => { void handleRunOptimisationCandidate(); }}
                  onRefreshStudy={() => { void refreshOptimisationStudy(); }}
                  onRecordTrial={() => { void handleRecordOptimisationTrial(); }}
                  onExportDataset={() => { void handleExportOptimisationDataset(); }}
                  onPromoteCandidate={() => { void handlePromoteOptimisationCandidate(); }}
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

              {/* ═══════ COMPARE TAB ═══════ */}
              <TabsContent value="compare" className="mt-0 min-h-0 flex-1 overflow-y-auto p-3">
                <div className="space-y-3">
                  <CompareToolbar
                    executions={executions}
                    compareLeftId={compareLeftId}
                    compareRightId={compareRightId}
                    setCompareLeftId={setCompareLeftId}
                    setCompareRightId={setCompareRightId}
                  />

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
