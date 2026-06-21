import {
  BookOpen,
  Code2,
  FileCode,
  FileText,
  Globe,
  Sparkles,
  Terminal,
  Wrench,
} from "lucide-react";
import type { LLMCallRecord, StepTrace, ToolCallRecord } from "@/types";

export function formatDuration(ms?: number | null): string {
  if (ms == null || !Number.isFinite(ms)) return "--";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const minutes = Math.floor(seconds / 60);
  const rem = Math.round(seconds % 60);
  return `${minutes}m ${rem}s`;
}

export function formatTokens(n?: number | null): string {
  if (n == null || !Number.isFinite(n)) return "--";
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

export function formatCurrency(value?: number | null): string {
  if (value == null || !Number.isFinite(value) || value === 0) return "--";
  return `$${value.toFixed(4)}`;
}

export function getStepLabel(step: StepTrace): string {
  return step.step_index != null
    ? `#${step.step_index + 1} ${step.name}`
    : step.name;
}

export function statusDotColor(status: string): string {
  const s = status.toLowerCase();
  if (s === "completed" || s === "succeeded") return "bg-emerald-500/80";
  if (s === "failed" || s === "error") return "bg-red-500/80";
  if (s === "running" || s === "in_progress") return "bg-amber-500/80 animate-pulse";
  if (s.includes("skip")) return "bg-muted-foreground/30";
  return "bg-slate-400";
}

export function statusBadgeClasses(status: string): string {
  const s = status?.toLowerCase() ?? "unknown";
  if (s === "completed" || s === "succeeded")
    return "border-emerald-500/20 bg-emerald-500/10 text-emerald-400";
  if (s === "failed" || s === "error")
    return "border-destructive/20 bg-destructive/10 text-destructive";
  if (s === "running" || s === "in_progress")
    return "border-amber-500/20 bg-amber-500/10 text-amber-400";
  if (s.includes("cancel"))
    return "border-amber-500/20 bg-amber-500/10 text-amber-400";
  return "border-border/60 bg-background/60 text-muted-foreground";
}

export function getToolIcon(
  toolName: string,
): React.ComponentType<{ className?: string }> {
  const name = toolName.toLowerCase();
  if (name.includes("search") || name.includes("docs")) return BookOpen;
  if (
    name.includes("webfetch") ||
    name.includes("web") ||
    name.includes("http") ||
    name.includes("fetch")
  )
    return Globe;
  if (
    name.includes("apply_patch") ||
    name.includes("edit") ||
    name.includes("write")
  )
    return FileCode;
  if (
    name.includes("bash") ||
    name.includes("shell") ||
    name.includes("exec") ||
    name.includes("command")
  )
    return Terminal;
  if (
    name.includes("read") ||
    name.includes("file") ||
    name.includes("glob") ||
    name.includes("grep")
  )
    return FileText;
  if (name.includes("skill")) return Sparkles;
  if (name.includes("code") || name.includes("python") || name.includes("node"))
    return Code2;
  return Wrench;
}

export function getToolIconColor(toolName: string): string {
  const name = toolName.toLowerCase();
  if (name.includes("search") || name.includes("docs")) return "text-violet-400";
  if (
    name.includes("webfetch") ||
    name.includes("web") ||
    name.includes("http") ||
    name.includes("fetch")
  )
    return "text-sky-400";
  if (
    name.includes("apply_patch") ||
    name.includes("edit") ||
    name.includes("write")
  )
    return "text-amber-400";
  if (
    name.includes("bash") ||
    name.includes("shell") ||
    name.includes("exec") ||
    name.includes("command")
  )
    return "text-emerald-400";
  if (
    name.includes("read") ||
    name.includes("file") ||
    name.includes("glob") ||
    name.includes("grep")
  )
    return "text-cyan-400";
  if (name.includes("skill")) return "text-pink-400";
  if (name.includes("code") || name.includes("python") || name.includes("node"))
    return "text-orange-400";
  return "text-muted-foreground";
}

export function getToolCallSummary(tc: ToolCallRecord): string {
  const name = tc.tool_name.toLowerCase();

  let parsed: Record<string, unknown> | null = null;
  if (
    tc.tool_args &&
    typeof tc.tool_args === "object" &&
    !Array.isArray(tc.tool_args)
  ) {
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
    if (
      (name.includes("webfetch") || name.includes("fetch")) &&
      parsed.url
    )
      return String(parsed.url);
    if (parsed.filePath) return String(parsed.filePath);
    if (parsed.path) return String(parsed.path);
    if (parsed.pattern) return String(parsed.pattern);
    if (parsed.command)
      return String(parsed.command).length > 120
        ? String(parsed.command).slice(0, 120) + "..."
        : String(parsed.command);
    if (parsed.file) return String(parsed.file);
    if (parsed.description) return String(parsed.description);
    if (parsed.prompt)
      return String(parsed.prompt).length > 100
        ? String(parsed.prompt).slice(0, 100) + "..."
        : String(parsed.prompt);
    if (parsed.query) return String(parsed.query);
    const firstStr = Object.values(parsed).find(
      (v) => typeof v === "string" && (v as string).length > 0,
    ) as string | undefined;
    if (firstStr)
      return firstStr.length > 120 ? firstStr.slice(0, 120) + "..." : firstStr;
  }

  const raw =
    tc.args_preview ||
    (tc.tool_args ? JSON.stringify(tc.tool_args) : "");
  if (raw.length > 120) return raw.slice(0, 120) + "...";
  return raw;
}

export function tcLatency(tc: ToolCallRecord): number {
  return tc.latency_ms || tc.duration_ms || 0;
}

export function getToolDetailLabel(toolName: string): string {
  const name = toolName.toLowerCase();
  if (name.includes("skill")) return "Skill";
  if (name.includes("webfetch") || name.includes("fetch")) return "URL";
  if (name.includes("search") || name.includes("docs")) return "Query";
  if (
    name.includes("bash") ||
    name.includes("shell") ||
    name.includes("exec") ||
    name.includes("command")
  )
    return "Command";
  if (
    name.includes("read") ||
    name.includes("glob") ||
    name.includes("grep")
  )
    return "Path";
  if (
    name.includes("apply_patch") ||
    name.includes("edit") ||
    name.includes("write")
  )
    return "File";
  if (name.includes("task")) return "Task";
  return "Input";
}

export interface TokenSegment {
  key: string;
  label: string;
  value: number;
  color: string;
}

export function getLLMTokenSegments(call: LLMCallRecord): TokenSegment[] {
  return [
    {
      key: "input",
      label: "Input",
      value: Math.max(
        (call.prompt_tokens ?? 0) - (call.cache_read_tokens ?? 0),
        0,
      ),
      color: "bg-slate-400",
    },
    {
      key: "cache_read",
      label: "Cache",
      value: call.cache_read_tokens ?? 0,
      color: "bg-teal-500/70",
    },
    {
      key: "reasoning",
      label: "Reasoning",
      value: call.reasoning_tokens ?? 0,
      color: "bg-indigo-400/80",
    },
    {
      key: "output",
      label: "Output",
      value: call.completion_tokens ?? 0,
      color: "bg-slate-600",
    },
  ].filter((s) => s.value > 0);
}

export function getStepTokenSegments(step: StepTrace): TokenSegment[] {
  const input = Math.max(
    (step.llm_calls ?? []).reduce(
      (sum, c) => sum + Math.max((c.prompt_tokens ?? 0) - (c.cache_read_tokens ?? 0), 0),
      0,
    ),
    0,
  );
  const cacheRead = (step.llm_calls ?? []).reduce(
    (sum, c) => sum + (c.cache_read_tokens ?? 0),
    0,
  );
  const reasoning = (step.llm_calls ?? []).reduce(
    (sum, c) => sum + (c.reasoning_tokens ?? 0),
    0,
  );
  const output = (step.llm_calls ?? []).reduce(
    (sum, c) => sum + (c.completion_tokens ?? 0),
    0,
  );
  return [
    { key: "input", label: "Input", value: input, color: "bg-slate-400" },
    { key: "cache_read", label: "Cache", value: cacheRead, color: "bg-teal-500/70" },
    { key: "reasoning", label: "Reasoning", value: reasoning, color: "bg-indigo-400/80" },
    { key: "output", label: "Output", value: output, color: "bg-slate-600" },
  ].filter((s) => s.value > 0);
}
