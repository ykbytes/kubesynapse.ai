import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import type { LLMCallRecord } from "@/types";
import {
  formatCurrency,
  formatDuration,
  formatTokens,
  getLLMTokenSegments,
} from "./observatory-utils";

interface LLMCallRowProps {
  call: LLMCallRecord;
  relativeTime?: string;
  isSelected?: boolean;
  onClick?: (call: LLMCallRecord) => void;
}

export function LLMCallRow({ call, relativeTime, isSelected, onClick }: LLMCallRowProps) {
  const [reasoningExpanded, setReasoningExpanded] = useState(false);
  const hasReasoning = Boolean(call.reasoning_text && call.reasoning_text.trim());
  const reasoningLen = call.reasoning_text?.length ?? 0;
  const showReasoningToggle = reasoningLen > 200;
  const segments = getLLMTokenSegments(call);
  const totalSegmentValue = segments.reduce((sum, s) => sum + s.value, 0);

  return (
    <button
      type="button"
      onClick={() => onClick?.(call)}
      className={cn(
        "group w-full rounded-lg border px-4 py-3 text-left transition-all",
        "border-border/40 bg-muted/20 hover:border-border/60 hover:bg-muted/40",
        isSelected && "border-primary/30 bg-primary/5 ring-1 ring-primary/15",
      )}
    >
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <span className="size-1.5 rounded-full bg-indigo-400/70 shrink-0" />
          <span className="truncate text-sm font-medium text-foreground">
            {call.model}
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-3 text-xs text-muted-foreground tabular-nums">
          {call.reasoning_tokens != null && call.reasoning_tokens > 0 && (
            <span className="text-indigo-400/80">{formatTokens(call.reasoning_tokens)} reasoning</span>
          )}
          {call.latency_ms > 0 && <span>{formatDuration(call.latency_ms)}</span>}
          {relativeTime && <span className="text-muted-foreground/50">{relativeTime}</span>}
        </div>
      </div>

      {/* Reasoning — clean, readable block */}
      {hasReasoning && (
        <div
          className="mt-3 rounded-md border border-border/30 bg-muted/30 px-3.5 py-2.5"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="mb-1.5 flex items-center justify-between">
            <span className="text-xs font-medium text-muted-foreground">
              Reasoning
            </span>
            {showReasoningToggle && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setReasoningExpanded((v) => !v);
                }}
                className="flex items-center gap-0.5 text-xs text-muted-foreground/60 transition-colors hover:text-foreground"
              >
                {reasoningExpanded ? (
                  <>Show less <ChevronDown className="size-3 rotate-180" /></>
                ) : (
                  <>Show more <ChevronDown className="size-3" /></>
                )}
              </button>
            )}
          </div>
          <p
            className={cn(
              "text-sm leading-relaxed text-foreground/80 whitespace-pre-wrap break-words",
              !reasoningExpanded && showReasoningToggle && "line-clamp-3",
            )}
          >
            {call.reasoning_text}
          </p>
        </div>
      )}

      {/* Response preview */}
      {call.response_preview && (
        <p className="mt-2 line-clamp-2 text-xs text-muted-foreground/60 leading-relaxed">
          {call.response_preview}
        </p>
      )}

      {/* Token bar + stats */}
      {totalSegmentValue > 0 && (
        <div className="mt-3 flex items-center gap-3">
          <div className="flex h-1 flex-1 overflow-hidden rounded-full bg-muted/40">
            {segments.map((seg) => (
              <div
                key={seg.key}
                className={cn("h-full", seg.color)}
                style={{ width: `${(seg.value / totalSegmentValue) * 100}%` }}
              />
            ))}
          </div>
          <div className="flex shrink-0 items-center gap-2.5 text-xs tabular-nums text-muted-foreground">
            {segments.map((seg) => (
              <span key={seg.key} className="flex items-center gap-1">
                <span className={cn("size-1.5 rounded-full", seg.color)} />
                {formatTokens(seg.value)}
              </span>
            ))}
            {call.estimated_cost_usd != null && call.estimated_cost_usd > 0 && (
              <span className="text-muted-foreground/50">{formatCurrency(call.estimated_cost_usd)}</span>
            )}
          </div>
        </div>
      )}
    </button>
  );
}
