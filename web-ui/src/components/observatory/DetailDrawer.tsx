import { useState } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { LLMCallRecord, StepTrace, ToolCallRecord } from "@/types";
import {
  formatCurrency,
  formatDuration,
  formatTokens,
  getLLMTokenSegments,
  getStepLabel,
  getToolDetailLabel,
  statusBadgeClasses,
  tcLatency,
} from "./observatory-utils";

export type DetailItem =
  | { type: "llm"; item: LLMCallRecord }
  | { type: "tool"; item: ToolCallRecord }
  | { type: "step"; item: StepTrace };

interface DetailDrawerProps {
  detail: DetailItem | null;
  onClose: () => void;
}

export function DetailDrawer({ detail: detailItem, onClose }: DetailDrawerProps) {
  if (!detailItem) return null;

  const title =
    detailItem.type === "llm"
      ? detailItem.item.model
      : detailItem.type === "tool"
        ? detailItem.item.tool_name
        : getStepLabel(detailItem.item);

  const typeLabel =
    detailItem.type === "llm" ? "LLM Call" : detailItem.type === "tool" ? "Tool Call" : "Step";

  return (
    <div className="flex h-full w-full flex-col border-l border-border/40 bg-background">
      {/* Header */}
      <div className="flex shrink-0 items-center gap-3 border-b border-border/40 px-5 py-4">
        <div className="min-w-0 flex-1">
          <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {typeLabel}
          </div>
          <h3 className="mt-0.5 truncate text-base font-semibold text-foreground">
            {title}
          </h3>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="flex size-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted/50 hover:text-foreground"
        >
          <X className="size-4" />
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        {detailItem.type === "llm" && <LLMDetail call={detailItem.item} />}
        {detailItem.type === "tool" && <ToolDetail call={detailItem.item} />}
        {detailItem.type === "step" && <StepDetail step={detailItem.item} />}
      </div>
    </div>
  );
}

// ─── LLM Detail ─────────────────────────────────────────────────────────────

function LLMDetail({ call }: { call: LLMCallRecord }) {
  const segments = getLLMTokenSegments(call);
  const totalSeg = segments.reduce((s, x) => s + x.value, 0);

  return (
    <div className="space-y-5 p-5">
      {/* Meta */}
      <div className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
        {call.latency_ms > 0 && <span>{formatDuration(call.latency_ms)}</span>}
        <span className="tabular-nums">
          {call.total_tokens > 0
            ? `${call.total_tokens.toLocaleString()} tokens`
            : `${call.prompt_tokens + call.completion_tokens} tokens`}
        </span>
        {call.estimated_cost_usd != null && call.estimated_cost_usd > 0 && (
          <span>{formatCurrency(call.estimated_cost_usd)}</span>
        )}
        {call.provider && <span className="text-muted-foreground/50">· {call.provider}</span>}
        {call.finish_reason && (
          <span className="rounded-md border border-border/40 px-2 py-0.5 text-xs text-muted-foreground">
            {call.finish_reason}
          </span>
        )}
      </div>

      {/* Reasoning */}
      {call.reasoning_text && call.reasoning_text.trim() && (
        <Section title="Reasoning">
          <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-border/30 bg-muted/20 p-4 text-sm leading-relaxed text-foreground/80 font-mono">
            {call.reasoning_text}
          </pre>
        </Section>
      )}

      {/* Prompt */}
      {call.prompt_preview && (
        <Section title="Prompt">
          <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-border/30 bg-muted/20 p-4 text-sm leading-relaxed text-foreground/80 font-mono">
            {call.prompt_preview}
          </pre>
        </Section>
      )}

      {/* Response */}
      {call.response_preview && (
        <Section title="Response">
          <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-border/30 bg-muted/20 p-4 text-sm leading-relaxed text-foreground/80 font-mono">
            {call.response_preview}
          </pre>
        </Section>
      )}

      {/* Token breakdown */}
      {totalSeg > 0 && (
        <Section title="Token Breakdown">
          <div className="space-y-3">
            <div className="flex h-2 overflow-hidden rounded-full bg-muted/30">
              {segments.map((seg) => (
                <div
                  key={seg.key}
                  className={cn("h-full", seg.color)}
                  style={{ width: `${(seg.value / totalSeg) * 100}%` }}
                />
              ))}
            </div>
            <div className="grid grid-cols-2 gap-2">
              {segments.map((seg) => (
                <div
                  key={seg.key}
                  className="flex items-center gap-2.5 rounded-lg border border-border/30 px-3 py-2"
                >
                  <span className={cn("size-2.5 rounded-full", seg.color)} />
                  <span className="text-xs text-muted-foreground">{seg.label}</span>
                  <span className="ml-auto text-sm font-medium tabular-nums text-foreground">
                    {formatTokens(seg.value)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </Section>
      )}

      <div className="pt-2 text-xs text-muted-foreground/30 font-mono">ID: {call.id}</div>
    </div>
  );
}

// ─── Tool Detail ────────────────────────────────────────────────────────────

function ToolDetail({ call }: { call: ToolCallRecord }) {
  const latency = tcLatency(call);
  const isFailed = call.status.toLowerCase() === "failed" || call.status.toLowerCase() === "error";
  const detailLabel = getToolDetailLabel(call.tool_name);

  return (
    <div className="space-y-5 p-5">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span
          className={cn(
            "rounded-lg border px-2.5 py-0.5 text-xs font-medium",
            isFailed
              ? "border-red-500/15 bg-red-500/5 text-red-500/80"
              : "border-emerald-500/15 bg-emerald-500/5 text-emerald-500/80",
          )}
        >
          {call.status}
        </span>
        {latency > 0 && <span className="text-muted-foreground">{formatDuration(latency)}</span>}
      </div>

      {call.error_message && (
        <Section title="Error">
          <pre className="whitespace-pre-wrap break-words rounded-lg border border-red-500/15 bg-red-500/5 p-4 text-sm text-red-400/80 font-mono">
            {call.error_message}
          </pre>
        </Section>
      )}

      {(call.tool_args || call.args_preview) && (
        <Section title={detailLabel}>
          <ToolArgsCard call={call} />
        </Section>
      )}

      {(call.tool_result != null || call.result_preview) && (
        <Section title="Result">
          <ToolResultBlock call={call} />
        </Section>
      )}

      <div className="pt-2 text-xs text-muted-foreground/30 font-mono">ID: {call.id}</div>
    </div>
  );
}

function ToolArgsCard({ call }: { call: ToolCallRecord }) {
  let parsed: Record<string, unknown> | null = null;
  if (call.tool_args && typeof call.tool_args === "object" && !Array.isArray(call.tool_args)) {
    parsed = call.tool_args as Record<string, unknown>;
  } else if (call.args_preview) {
    try {
      const p = JSON.parse(call.args_preview);
      if (typeof p === "object" && p !== null && !Array.isArray(p)) {
        parsed = p as Record<string, unknown>;
      }
    } catch {
      // not JSON
    }
  }

  if (parsed) {
    const entries = Object.entries(parsed);
    if (entries.length === 0) return null;
    return (
      <div className="overflow-hidden rounded-lg border border-border/30 divide-y divide-border/20">
        {entries.map(([key, value]) => {
          const strVal =
            value == null ? "null" : typeof value === "string" ? value : JSON.stringify(value, null, 2);
          return (
            <div key={key} className="px-3.5 py-2.5">
              <div className="flex items-start gap-3">
                <span className="w-24 shrink-0 pt-0.5 text-xs font-medium uppercase tracking-wide text-muted-foreground/50">
                  {key}
                </span>
                <span className="min-w-0 flex-1 text-sm font-mono">
                  <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-all text-foreground/80">
                    {strVal}
                  </pre>
                </span>
              </div>
            </div>
          );
        })}
      </div>
    );
  }

  const raw = call.args_preview || (call.tool_args ? JSON.stringify(call.tool_args, null, 2) : null);
  if (raw) {
    return (
      <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-border/30 bg-muted/20 p-4 text-sm text-foreground/80 font-mono">
        {raw}
      </pre>
    );
  }
  return null;
}

function ToolResultBlock({ call }: { call: ToolCallRecord }) {
  const raw = call.tool_result ?? call.result_preview ?? null;
  if (raw == null) return null;
  const text = typeof raw === "string" ? raw : JSON.stringify(raw, null, 2);
  const isLong = text.length > 300;
  const [expanded, setExpanded] = useState(!isLong);
  const lines = text.split(/\r?\n/);

  return (
    <div>
      <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-border/30 bg-muted/20 p-4 text-sm text-foreground/80 font-mono">
        {expanded ? text : lines.slice(0, 8).join("\n") + (isLong ? "\n…" : "")}
      </pre>
      {isLong && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="mt-2 w-full rounded-lg border border-border/30 bg-muted/10 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted/30 hover:text-foreground"
        >
          {expanded ? "Collapse" : `Show all ${lines.length} lines`}
        </button>
      )}
    </div>
  );
}

// ─── Step Detail ────────────────────────────────────────────────────────────

function StepDetail({ step }: { step: StepTrace }) {
  return (
    <div className="space-y-5 p-5">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span
          className={cn(
            "rounded-lg border px-2.5 py-0.5 text-xs font-medium",
            statusBadgeClasses(step.status),
          )}
        >
          {step.status}
        </span>
        {step.latency_ms != null && (
          <span className="text-muted-foreground">{formatDuration(step.latency_ms)}</span>
        )}
        {step.tokens_used != null && step.tokens_used > 0 && (
          <span className="text-muted-foreground tabular-nums">{formatTokens(step.tokens_used)} tokens</span>
        )}
        {step.cost_usd != null && step.cost_usd > 0 && (
          <span className="text-muted-foreground">{formatCurrency(step.cost_usd)}</span>
        )}
      </div>

      {step.error && (
        <Section title="Error">
          <pre className="whitespace-pre-wrap break-words rounded-lg border border-red-500/15 bg-red-500/5 p-4 text-sm text-red-400/80 font-mono">
            {step.error}
          </pre>
        </Section>
      )}

      {step.input_preview && (
        <Section title="Input">
          <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-border/30 bg-muted/20 p-4 text-sm leading-relaxed text-foreground/80 font-mono">
            {step.input_preview}
          </pre>
        </Section>
      )}

      {step.output_preview && (
        <Section title="Output">
          <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-border/30 bg-muted/20 p-4 text-sm leading-relaxed text-foreground/80 font-mono">
            {step.output_preview}
          </pre>
        </Section>
      )}

      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <span>{step.llm_call_count ?? step.llm_calls.length} LLM calls</span>
        <span className="text-muted-foreground/30">·</span>
        <span>{step.tool_call_count ?? step.tool_calls.length} tool calls</span>
      </div>

      <div className="pt-2 text-xs text-muted-foreground/30 font-mono">ID: {step.id}</div>
    </div>
  );
}

// ─── Section ────────────────────────────────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <h4 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {title}
      </h4>
      {children}
    </div>
  );
}
