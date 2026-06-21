import { useMemo } from "react";
import { Activity } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ExecutionTrace, LLMCallRecord, StepTrace, ToolCallRecord } from "@/types";
import { formatCurrency, formatDuration, formatTokens } from "./observatory-utils";
import { LLMCallRow } from "./LLMCallRow";
import { StepNode } from "./StepNode";

interface ExecutionTimelineViewProps {
  detail: ExecutionTrace | null;
  selectedItemId?: string | null;
  onLLMClick?: (call: LLMCallRecord) => void;
  onToolClick?: (call: ToolCallRecord) => void;
  onStepClick?: (step: StepTrace) => void;
}

interface StatItem {
  label: string;
  value: string;
  sub?: string;
}

export function ExecutionTimelineView({
  detail,
  selectedItemId,
  onLLMClick,
  onToolClick,
  onStepClick,
}: ExecutionTimelineViewProps) {
  const orderedSteps = useMemo(
    () =>
      detail
        ? [...detail.steps].sort((a, b) => (a.step_index ?? 999) - (b.step_index ?? 999))
        : [],
    [detail],
  );

  const executionStartTime = useMemo(() => {
    if (!detail?.started_at) return Date.now();
    return new Date(detail.started_at).getTime();
  }, [detail?.started_at]);

  const stats: StatItem[] = useMemo(() => {
    if (!detail) return [];
    return [
      { label: "Duration", value: formatDuration(detail.duration_ms) },
      {
        label: "Steps",
        value: `${detail.completed_steps ?? 0}/${detail.step_count}`,
        sub: (detail.failed_steps ?? 0) > 0 ? `${detail.failed_steps} failed` : undefined,
      },
      {
        label: "LLM",
        value: String(detail.llm_call_count),
        sub: detail.total_tokens > 0 ? `${formatTokens(detail.total_tokens)} tok` : undefined,
      },
      { label: "Tools", value: String(detail.tool_call_count) },
      { label: "Cost", value: formatCurrency(detail.total_cost_usd) },
    ];
  }, [detail]);

  if (!detail) {
    return (
      <div className="flex h-full flex-col items-center justify-center text-center">
        <Activity className="size-8 text-muted-foreground/20" />
        <p className="mt-3 text-sm text-muted-foreground">
          Select a workflow run to see its execution timeline.
        </p>
      </div>
    );
  }

  if (orderedSteps.length === 0 && detail.llm_calls.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center text-center">
        <Activity className="size-8 text-muted-foreground/20" />
        <p className="mt-3 text-sm text-muted-foreground">
          No execution detail available yet. Trace ingestion may still be in progress.
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Stats strip — minimal, clean */}
      <div className="flex shrink-0 items-center gap-0 border-b border-border/30 px-4">
        {stats.map((stat, idx) => (
          <div
            key={stat.label}
            className={cn(
              "flex items-baseline gap-1.5 px-3 py-2.5",
              idx > 0 && "border-l border-border/20",
              idx === 0 && "pl-0",
            )}
          >
            <span className="text-sm font-semibold tabular-nums text-foreground">
              {stat.value}
            </span>
            <span className="text-xs text-muted-foreground">{stat.label}</span>
            {stat.sub && (
              <span className="text-xs text-muted-foreground/50">{stat.sub}</span>
            )}
          </div>
        ))}
      </div>

      {/* Timeline body */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        <div className="relative px-4 py-5">
          {/* Spine line */}
          <div className="absolute left-[23px] top-8 bottom-8 w-px bg-border/20" />

          <div className="space-y-3">
            {orderedSteps.map((step, idx) => (
              <StepNode
                key={step.id}
                step={step}
                executionStartTime={executionStartTime}
                isLast={idx === orderedSteps.length - 1}
                defaultExpanded={true}
                selectedItemId={selectedItemId}
                onLLMClick={onLLMClick}
                onToolClick={onToolClick}
                onStepClick={onStepClick}
              />
            ))}
          </div>

          {/* Orphan LLM calls */}
          {detail.llm_calls.filter(
            (c) => !c.step_id || !orderedSteps.some((s) => s.id === c.step_id),
          ).length > 0 && (
            <div className="mt-5 space-y-2">
              <span className="text-xs font-medium text-muted-foreground">
                Unassociated LLM Calls
              </span>
              {detail.llm_calls
                .filter((c) => !c.step_id || !orderedSteps.some((s) => s.id === c.step_id))
                .map((call) => (
                  <div key={call.id} className="pl-8">
                    <LLMCallRow
                      call={call}
                      isSelected={selectedItemId === call.id}
                      onClick={onLLMClick}
                    />
                  </div>
                ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
