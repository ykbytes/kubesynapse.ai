import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import {
  Activity,
  BookOpen,
  Bot,
  Braces,
  BrainCircuit,
  ChevronRight,
  Code2,
  FileCode,
  FileText,
  Gauge,
  GitCompare,
  Globe,
  Lightbulb,
  Layers,
  LoaderCircle,
  Maximize2,
  Minimize2,
  Search,
  Send,
  ShieldAlert,
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
  fetchWorkflowRuns,
  exportExecutionHtml,
  exportExecutionJson,
  fetchAgentManifest,
  fetchExecutionDetail,
  fetchWorkflowManifest,
  fetchWorkflowRunTrace,
  invokeAgent,
  listAgents,
  listExecutions,
  type WorkflowRunRecord,
  type WorkflowRunTraceResponse,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import type { AgentInfo, ExecutionListItem, ExecutionTrace, InvokeResponse, LLMCallRecord, StepTrace, ToolCallRecord } from "@/types";

import { Highlight, type Language } from "prism-react-renderer";
import { KubeSynapseTheme } from "@/components/docs/shared";

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
type ObservatoryTab = "overview" | "trace" | "optimise" | "logs" | "compare";
type OptimisationScope = "current" | "last6" | "last20";

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
  const agentRefs = Object.keys(agentManifests);
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

function buildOptimisationPrompt(packet: OptimisationPacket): string {
  return [
    "You are a senior AI workflow optimisation engineer for KubeSynapse.",
    "",
    "Goal: analyse the provided execution traces and Kubernetes manifests, then propose an optimized copy of the workflow and agent manifests that reduces latency, token spend, tool churn, and failure risk while preserving the workflow contract.",
    "",
    "Rules:",
    "- Do not modify files, workflow definitions, cluster resources, credentials, or external systems.",
    "- Treat this as an analysis-only optimisation review.",
    "- Generate candidate manifests as copies with new names, labels, and clear diff notes. Do not propose in-place mutation as the default.",
    "- If a test-run loop is useful, describe the loop and required permissions, but do not run kubectl or apply anything.",
    "- Any apply/run capability must be handled by a separate admin-created agent with least-privilege Kubernetes RBAC and explicit user approval.",
    "- Preserve existing step outputs, artifact paths, schemas, handoff semantics, and security boundaries unless you explicitly mark a breaking change and provide migration steps.",
    "- Prefer prompt/context/model/tool-use improvements before proposing structural rewrites.",
    "",
    "Return Markdown with these sections:",
    "1. Executive recommendation with expected savings.",
    "2. Ranked bottlenecks with evidence from step, LLM, tool, and event data.",
    "3. Prompt edits per step or agent, written as ready-to-review snippets.",
    "4. Optimized Kubernetes manifests for copied workflow/agent resources.",
    "5. Proposed run loop: baseline, candidate execution, comparison criteria, rollback and cleanup.",
    "6. RBAC and approval requirements for any deployment-capable agent.",
    "",
    "Trace packet:",
    JSON.stringify(packet, null, 2),
  ].join("\n");
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

      <div className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden xl:grid-cols-[13rem_minmax(22rem,0.78fr)_minmax(30rem,1.22fr)]">
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

        <div className="min-h-0 overflow-hidden border-b border-border/40 xl:border-b-0 xl:border-r">
          <div className="flex items-center justify-between border-b border-border/30 px-3 py-2">
            <div className="text-xs font-semibold text-foreground">Chronology</div>
            <div className="text-[10px] text-muted-foreground">
              {filteredRecords.length} of {traceRecords.length} records
            </div>
          </div>
          <ScrollArea className="h-full">
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
                      "w-full rounded-lg border px-3 py-2 text-left transition-colors",
                      isActive ? "border-primary/50 bg-primary/8" : "border-border/45 bg-card/35 hover:bg-accent/25",
                    )}
                  >
                    <div className="flex items-start gap-2">
                      <Badge variant="outline" className={cn("mt-0.5 h-5 px-1.5 text-[9px] uppercase", traceKindClasses(record.kind))}>
                        {record.kind}
                      </Badge>
                      <div className="min-w-0 flex-1">
                        <div className="flex min-w-0 items-center gap-2">
                          {ToolIcon && <ToolIcon className={cn("h-3.5 w-3.5 shrink-0", getToolIconColor(record.toolName ?? ""))} />}
                          <span className="truncate text-xs font-semibold text-foreground">{record.title}</span>
                          <span className={cn("shrink-0 text-[10px] font-medium", statusTextClasses(record.status))}>{record.status}</span>
                        </div>
                        <p className="mt-1 line-clamp-1 text-[11px] text-muted-foreground">{record.summary}</p>
                        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-muted-foreground">
                          <span className="tabular-nums">{record.timestamp ? formatCompactDate(record.timestamp) : "--"}</span>
                          <span className="truncate">Agent: {record.actorLabel}</span>
                          <span className="truncate">Step: {record.stepLabel}</span>
                          {record.durationMs != null && record.durationMs > 0 && <span>{formatDuration(record.durationMs)}</span>}
                          {record.tokens != null && record.tokens > 0 && <span>{record.tokens.toLocaleString()} tokens</span>}
                          {record.cost != null && record.cost > 0 && <span>{formatCurrency(record.cost)}</span>}
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
  result,
  error,
  onRun,
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
  result: InvokeResponse | null;
  error: string;
  onRun: () => void;
}) {
  const selectedAgent = agents.find((agent) => agent.name === selectedAgentName) ?? null;
  const stepMetrics = (packet?.step_metrics ?? []) as Array<Record<string, unknown>>;
  const opportunityMap = (packet?.opportunity_map ?? []) as Array<Record<string, unknown>>;
  const slowestSteps = [...stepMetrics]
    .sort((a, b) => compactNumber(b.duration_ms as number | null) - compactNumber(a.duration_ms as number | null))
    .slice(0, 5);
  const tokenHeavySteps = [...stepMetrics]
    .sort((a, b) => compactNumber(b.tokens as number | null) - compactNumber(a.tokens as number | null))
    .slice(0, 5);
  const promptEstimate = Math.ceil(prompt.length / 4);

  if (!detail) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Optimisation data appears once a traced execution is selected.
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <div className="shrink-0 border-b border-border/40 bg-card/30 px-3 py-2">
        <div className="flex flex-wrap items-center gap-2">
          <div className="min-w-[16rem] flex-1">
            <h3 className="text-sm font-semibold text-foreground">Workflow optimisation</h3>
            <p className="text-[11px] text-muted-foreground">
              {detail.workflow_name} · {formatDuration(detail.duration_ms)} · {detail.total_tokens.toLocaleString()} tokens · {detail.tool_call_count} tools
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
                  {agent.name} · {agent.model || agent.runtime_kind || "agent"}
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
          <Button
            type="button"
            size="sm"
            className="h-8 gap-1.5 text-xs"
            disabled={!selectedAgentName || !packet || running || detailsLoading || manifestLoading}
            onClick={onRun}
          >
            {running ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
            Run optimisation
          </Button>
        </div>
      </div>

      <ScrollArea className="min-h-0 flex-1">
        <div className="grid gap-3 p-3 xl:grid-cols-[minmax(0,0.9fr)_minmax(28rem,1.1fr)]">
          <div className="space-y-3">
            <section className="rounded-lg border border-border/50 bg-card/45 p-3">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                    <Target className="h-4 w-4 text-primary" />
                    Opportunity map
                  </div>
                  <p className="text-[11px] text-muted-foreground">
                    {packet?.trace_details.length ?? 0} detailed traces · {packet?.run_history.length ?? 0} run summaries · ~{promptEstimate.toLocaleString()} prompt tokens
                  </p>
                </div>
                {(detailsLoading || manifestLoading) && <Badge variant="outline" className="gap-1 text-[10px]"><LoaderCircle className="h-3 w-3 animate-spin" /> loading context</Badge>}
              </div>
              <div className="grid gap-2 md:grid-cols-2">
                {opportunityMap.map((item) => (
                  <div key={String(item.label)} className="rounded-md border border-border/45 bg-background/70 p-2.5">
                    <div className="flex items-center gap-2 text-xs font-semibold text-foreground">
                      {String(item.label) === "Token pressure" ? <Gauge className="h-3.5 w-3.5 text-violet-400" /> : <TrendingDown className="h-3.5 w-3.5 text-emerald-400" />}
                      {String(item.label)}
                    </div>
                    <div className="mt-1 text-[11px] font-medium text-foreground">{String(item.signal ?? "--")}</div>
                    <div className="mt-1 line-clamp-2 text-[10px] text-muted-foreground">{String(item.recommendation ?? "")}</div>
                  </div>
                ))}
              </div>
            </section>

            <section className="rounded-lg border border-border/50 bg-card/45 p-3">
              <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-foreground">
                <Sparkles className="h-4 w-4 text-primary" />
                Step candidates
              </div>
              <div className="grid gap-3 lg:grid-cols-2">
                <div>
                  <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Slowest path</div>
                  <div className="space-y-1.5">
                    {slowestSteps.map((step) => (
                      <div key={String(step.id)} className="rounded-md border border-border/40 bg-background/60 p-2">
                        <div className="flex items-center justify-between gap-2 text-xs">
                          <span className="truncate font-medium text-foreground">{String(step.label)}</span>
                          <span className="tabular-nums text-muted-foreground">{formatDuration(compactNumber(step.duration_ms as number | null))}</span>
                        </div>
                        <div className="mt-1 flex flex-wrap gap-1 text-[10px] text-muted-foreground">
                          <span>{compactNumber(step.llm_calls as number | null)} LLM</span>
                          <span>{compactNumber(step.tool_calls as number | null)} tools</span>
                          <span>{compactNumber(step.events as number | null)} events</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
                <div>
                  <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Token pressure</div>
                  <div className="space-y-1.5">
                    {tokenHeavySteps.map((step) => (
                      <div key={String(step.id)} className="rounded-md border border-border/40 bg-background/60 p-2">
                        <div className="flex items-center justify-between gap-2 text-xs">
                          <span className="truncate font-medium text-foreground">{String(step.label)}</span>
                          <span className="tabular-nums text-muted-foreground">{compactNumber(step.tokens as number | null).toLocaleString()} tokens</span>
                        </div>
                        <div className="mt-1 truncate text-[10px] text-muted-foreground">
                          {Array.isArray(step.models) && step.models.length > 0 ? step.models.join(", ") : "model unknown"}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </section>

            <section className="rounded-lg border border-border/50 bg-card/45 p-3">
              <div className="mb-2 flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                  <Bot className="h-4 w-4 text-primary" />
                  Optimisation agent
                </div>
                {selectedAgent && <Badge variant="outline" className="text-[10px]">{selectedAgent.status}</Badge>}
              </div>
              {selectedAgent ? (
                <div className="grid gap-2 text-[11px] sm:grid-cols-3">
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
                </div>
              ) : (
                <div className="rounded-md border border-dashed border-border/50 p-4 text-center text-xs text-muted-foreground">
                  Select an agent before running the optimisation review.
                </div>
              )}
            </section>

            <section className="rounded-lg border border-amber-500/25 bg-amber-500/5 p-3">
              <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-foreground">
                <ShieldAlert className="h-4 w-4 text-amber-400" />
                Deployment access model
              </div>
              <div className="grid gap-2 text-[11px] sm:grid-cols-2">
                <div className="rounded-md border border-border/40 bg-background/65 p-2">
                  <div className="text-muted-foreground">Current optimiser run</div>
                  <div className="mt-0.5 font-medium text-foreground">Analysis only</div>
                </div>
                <div className="rounded-md border border-border/40 bg-background/65 p-2">
                  <div className="text-muted-foreground">Source manifests</div>
                  <div className="mt-0.5 font-medium text-foreground">
                    {packet?.source_manifests.workflow ? "Workflow" : "Workflow missing"} · {Object.keys(packet?.source_manifests.agents ?? {}).length} agent manifest(s)
                  </div>
                </div>
              </div>
              <p className="mt-2 text-[11px] leading-5 text-muted-foreground">
                Applying candidate manifests or running the comparison loop must use a separate admin-created deployment agent with least-privilege Kubernetes RBAC and explicit approval.
              </p>
              {manifestError && (
                <div className="mt-2 rounded-md border border-red-500/25 bg-red-500/10 px-2 py-1.5 text-[11px] text-red-400">
                  {manifestError}
                </div>
              )}
            </section>
          </div>

          <div className="space-y-3">
            <section className="rounded-lg border border-border/50 bg-card/45 p-3">
              <div className="mb-2 flex items-center justify-between gap-2">
                <div>
                  <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                    <Lightbulb className="h-4 w-4 text-amber-400" />
                    Agent brief
                  </div>
                  <p className="text-[11px] text-muted-foreground">Analysis-only packet sent to the selected agent.</p>
                </div>
                <CopyButton value={prompt} className="h-7 w-7" />
              </div>
              <Textarea
                readOnly
                value={prompt}
                className="min-h-[320px] resize-none border-border/60 bg-background/80 font-mono text-[10px] leading-relaxed"
              />
            </section>

            {error && (
              <div className="rounded-lg border border-red-500/25 bg-red-500/10 p-3 text-xs text-red-400">
                {error}
              </div>
            )}

            <section className="rounded-lg border border-border/50 bg-card/45 p-3">
              <div className="mb-2 flex items-center justify-between gap-2">
                <div className="text-sm font-semibold text-foreground">Optimisation result</div>
                {result && <Badge variant="outline" className="text-[10px]">{result.status}</Badge>}
              </div>
              {running ? (
                <div className="flex items-center justify-center gap-2 rounded-md border border-border/40 bg-background/60 py-12 text-xs text-muted-foreground">
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                  Agent analysis running
                </div>
              ) : result ? (
                <div className="space-y-2">
                  <div className="grid gap-2 text-[10px] sm:grid-cols-3">
                    <div className="rounded-md border border-border/40 bg-background/65 p-2">
                      <div className="text-muted-foreground">Thread</div>
                      <div className="truncate font-medium text-foreground">{result.thread_id}</div>
                    </div>
                    <div className="rounded-md border border-border/40 bg-background/65 p-2">
                      <div className="text-muted-foreground">Model</div>
                      <div className="truncate font-medium text-foreground">{result.model}</div>
                    </div>
                    <div className="rounded-md border border-border/40 bg-background/65 p-2">
                      <div className="text-muted-foreground">Agent</div>
                      <div className="truncate font-medium text-foreground">{result.agent_name}</div>
                    </div>
                  </div>
                  <pre className="max-h-[520px] overflow-auto rounded-md border border-border/40 bg-background/80 p-3 text-xs leading-relaxed whitespace-pre-wrap text-foreground/90">{result.response}</pre>
                </div>
              ) : (
                <div className="rounded-md border border-dashed border-border/50 p-6 text-center text-xs text-muted-foreground">
                  No optimisation run has been started for this execution.
                </div>
              )}
            </section>
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
  const [optimiseResult, setOptimiseResult] = useState<InvokeResponse | null>(null);
  const [optimiseError, setOptimiseError] = useState("");
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
    if (optimiseAgentName && optimiseAgents.some((agent) => agent.name === optimiseAgentName)) return;
    const preferred =
      optimiseAgents.find((agent) => agent.name === detail?.agent_name) ??
      optimiseAgents.find((agent) => agent.status.toLowerCase() === "ready" && (agent.runtime_kind ?? "opencode") === "opencode") ??
      optimiseAgents.find((agent) => agent.status.toLowerCase() === "ready") ??
      optimiseAgents[0] ??
      null;
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
    setOptimiseResult(null); setOptimiseError("");
    setOptimiseWorkflowManifest(null); setOptimiseAgentManifests({}); setOptimiseManifestError("");
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

  const handleRunOptimisation = async () => {
    if (!optimiseAgentName || !optimisePrompt || !detail) return;
    setOptimiseRunning(true);
    setOptimiseError("");
    setOptimiseResult(null);
    try {
      const result = await invokeAgent(
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
      setOptimiseResult(result);
      toast.success("Optimisation analysis completed");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Optimisation analysis failed";
      setOptimiseError(message);
      toast.error(message);
    } finally {
      setOptimiseRunning(false);
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

              {/* ═══════ OVERVIEW TAB ═══════ */}
              <TabsContent value="overview" className="mt-0 min-h-0 flex-1 overflow-y-auto">
                <ObservatoryOverview
                  detail={detail}
                  run={selectedRun}
                  previousRuns={runs}
                  onStepClick={(step) => { setSelectedStepId(step.id); setActiveTab("trace"); }}
                  onJumpToErrors={() => { setLogFilterMode("errors"); setActiveTab("logs"); }}
                  onViewLogs={() => setActiveTab("logs")}
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
                  onSelectedAgentChange={(agentName) => { setOptimiseAgentName(agentName); setOptimiseResult(null); setOptimiseError(""); }}
                  scope={optimiseScope}
                  onScopeChange={(scopeValue) => { setOptimiseScope(scopeValue); setOptimiseResult(null); setOptimiseError(""); }}
                  packet={optimisePacket}
                  prompt={optimisePrompt}
                  detailsLoading={optimiseDetailsLoading}
                  manifestLoading={optimiseManifestLoading}
                  manifestError={optimiseManifestError}
                  running={optimiseRunning}
                  result={optimiseResult}
                  error={optimiseError}
                  onRun={() => { void handleRunOptimisation(); }}
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
