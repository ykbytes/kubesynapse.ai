import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import type { LLMCallRecord, StepTrace, ToolCallRecord } from "@/types";
import {
  formatDuration,
  formatTokens,
  getStepLabel,
  getStepTokenSegments,
  statusDotColor,
} from "./observatory-utils";
import { LLMCallRow } from "./LLMCallRow";
import { ToolCallRow } from "./ToolCallRow";

interface StepNodeProps {
  step: StepTrace;
  executionStartTime: number;
  isLast?: boolean;
  defaultExpanded?: boolean;
  selectedItemId?: string | null;
  onLLMClick?: (call: LLMCallRecord) => void;
  onToolClick?: (call: ToolCallRecord) => void;
  onStepClick?: (step: StepTrace) => void;
}

function relTime(ts: string | undefined | null, base: number): string {
  if (!ts) return "";
  const diff = new Date(ts).getTime() - base;
  if (diff < 1000) return "+0s";
  if (diff < 60000) return `+${(diff / 1000).toFixed(1)}s`;
  const m = Math.floor(diff / 60000);
  const s = Math.round((diff % 60000) / 1000);
  return `+${m}m${s}s`;
}

export function StepNode({
  step,
  executionStartTime,
  isLast,
  defaultExpanded = true,
  selectedItemId,
  onLLMClick,
  onToolClick,
  onStepClick,
}: StepNodeProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const label = getStepLabel(step);
  const dotColor = statusDotColor(step.status);
  const llmCount = step.llm_call_count ?? step.llm_calls.length;
  const toolCount = step.tool_call_count ?? step.tool_calls.length;
  const totalTokens = step.tokens_used ?? 0;
  const segments = getStepTokenSegments(step);
  const segmentTotal = segments.reduce((sum, s) => sum + s.value, 0);
  const isFailed = step.status.toLowerCase() === "failed" || step.status.toLowerCase() === "error";
  const stepRel = relTime(step.started_at, executionStartTime);

  return (
    <div className="relative pl-8">
      {/* Spine dot */}
      <div className="absolute left-[11px] top-4 z-10">
        <span className={cn("block size-2.5 rounded-full ring-4 ring-background", dotColor)} />
      </div>
      {!isLast && (
        <div className="absolute left-[12px] top-8 bottom-0 w-px bg-border/25" />
      )}

      {/* Step card */}
      <div
        className={cn(
          "overflow-hidden rounded-xl border transition-all",
          isFailed ? "border-red-500/15" : "border-border/40",
          expanded ? "bg-card/30" : "bg-card/20 hover:bg-card/30",
        )}
      >
        {/* Header */}
        <button
          type="button"
          onClick={() => {
            setExpanded((v) => !v);
            onStepClick?.(step);
          }}
          className="flex w-full items-center gap-3 px-4 py-3 text-left"
        >
          <ChevronDown
            className={cn(
              "size-4 shrink-0 text-muted-foreground transition-transform",
              !expanded && "-rotate-90",
            )}
          />
          <span className="flex-1 truncate text-sm font-medium text-foreground">
            {label}
          </span>
          {/* Meta — minimal, muted */}
          <div className="flex shrink-0 items-center gap-3 text-xs text-muted-foreground tabular-nums">
            {llmCount > 0 && <span>{llmCount} LLM</span>}
            {toolCount > 0 && <span>{toolCount} tools</span>}
            {totalTokens > 0 && <span>{formatTokens(totalTokens)} tok</span>}
            <span>{formatDuration(step.latency_ms)}</span>
            {stepRel && <span className="text-muted-foreground/40">{stepRel}</span>}
          </div>
        </button>

        {/* Token bar */}
        {segmentTotal > 0 && (
          <div className="px-4 pb-2">
            <div className="flex h-0.5 overflow-hidden rounded-full bg-muted/30">
              {segments.map((seg) => (
                <div
                  key={seg.key}
                  className={cn("h-full", seg.color)}
                  style={{ width: `${(seg.value / segmentTotal) * 100}%` }}
                />
              ))}
            </div>
          </div>
        )}

        {/* Expanded content */}
        {expanded && (
          <div className="space-y-2 px-4 pb-4 pt-2">
            {step.error && (
              <div className="rounded-lg border border-red-500/15 bg-red-500/5 px-3.5 py-2.5">
                <span className="text-xs font-medium text-red-500/80">Error</span>
                <pre className="mt-1 whitespace-pre-wrap break-words text-xs text-red-400/80 font-mono">
                  {step.error}
                </pre>
              </div>
            )}

            {step.llm_calls.map((call) => (
              <LLMCallRow
                key={call.id}
                call={call}
                relativeTime={relTime(call.created_at, executionStartTime)}
                isSelected={selectedItemId === call.id}
                onClick={onLLMClick}
              />
            ))}

            {step.tool_calls.map((tc) => (
              <ToolCallRow
                key={tc.id}
                call={tc}
                relativeTime={relTime(tc.created_at || tc.started_at, executionStartTime)}
                isSelected={selectedItemId === tc.id}
                onClick={onToolClick}
              />
            ))}

            {llmCount === 0 && toolCount === 0 && !step.error && (
              <div className="py-3 text-center text-xs text-muted-foreground/40">
                No LLM or tool calls recorded for this step.
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
