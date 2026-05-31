import { useMemo } from "react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { StepTrace } from "@/types";

interface StepWaterfallProps {
  steps: StepTrace[];
  executionStartedAt?: string | null;
  className?: string;
  onStepClick?: (step: StepTrace) => void;
  selectedStepId?: string | null;
}

function statusBarColor(status: string): string {
  const s = status.toLowerCase();
  if (s === "completed" || s === "succeeded") return "bg-emerald-500";
  if (s === "failed" || s === "error") return "bg-red-500";
  if (s === "running" || s === "in_progress") return "bg-amber-500 animate-pulse";
  if (s.includes("skip")) return "bg-muted-foreground/30";
  return "bg-sky-500";
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

interface WaterfallStep {
  step: StepTrace;
  offsetPercent: number;
  widthPercent: number;
}

export function StepWaterfall({
  steps,
  executionStartedAt,
  className,
  onStepClick,
  selectedStepId,
}: StepWaterfallProps) {
  const waterfallData = useMemo((): WaterfallStep[] => {
    if (steps.length === 0) return [];

    // Determine time boundaries
    const execStart = executionStartedAt ? new Date(executionStartedAt).getTime() : null;

    // Find the earliest step start and latest step end
    let minTime = Infinity;
    let maxTime = -Infinity;

    for (const step of steps) {
      if (step.started_at) {
        const start = new Date(step.started_at).getTime();
        if (start < minTime) minTime = start;
        const end = step.completed_at
          ? new Date(step.completed_at).getTime()
          : start + (step.latency_ms ?? 0);
        if (end > maxTime) maxTime = end;
      }
    }

    // If we have an execution start that's earlier, use it
    if (execStart != null && execStart < minTime) {
      minTime = execStart;
    }

    // Fallback: if no timing data, just show equal bars
    if (!Number.isFinite(minTime) || !Number.isFinite(maxTime) || maxTime <= minTime) {
      return steps.map((step) => ({
        step,
        offsetPercent: 0,
        widthPercent: 100 / steps.length,
      }));
    }

    const totalDuration = maxTime - minTime;

    return steps.map((step) => {
      if (!step.started_at) {
        return { step, offsetPercent: 0, widthPercent: 2 }; // Minimal bar for steps with no timing
      }
      const start = new Date(step.started_at).getTime();
      const duration = step.latency_ms ?? (step.completed_at
        ? new Date(step.completed_at).getTime() - start
        : 0);

      const offsetPercent = ((start - minTime) / totalDuration) * 100;
      const widthPercent = Math.max((duration / totalDuration) * 100, 1.5); // Min 1.5% to be visible

      return { step, offsetPercent, widthPercent };
    });
  }, [executionStartedAt, steps]);

  if (steps.length === 0) {
    return (
      <div className={cn("rounded-lg border border-dashed border-border/50 py-6 text-center text-xs text-muted-foreground", className)}>
        No steps recorded
      </div>
    );
  }

  // Total duration for the time axis
  const totalMs = useMemo(() => {
    let max = 0;
    for (const step of steps) {
      if (step.latency_ms != null && step.latency_ms > max) max = step.latency_ms;
      if (step.started_at && step.completed_at) {
        const d = new Date(step.completed_at).getTime() - new Date(step.started_at).getTime();
        if (d > max) max = d;
      }
    }
    // Also check if steps overlap (parallel) — total time is max end - min start
    let minStart = Infinity;
    let maxEnd = -Infinity;
    for (const step of steps) {
      if (step.started_at) {
        const s = new Date(step.started_at).getTime();
        if (s < minStart) minStart = s;
        const e = step.completed_at
          ? new Date(step.completed_at).getTime()
          : s + (step.latency_ms ?? 0);
        if (e > maxEnd) maxEnd = e;
      }
    }
    return Number.isFinite(minStart) && Number.isFinite(maxEnd) ? maxEnd - minStart : max;
  }, [steps]);

  return (
    <TooltipProvider delayDuration={150}>
      <div className={cn("space-y-1", className)}>
        {waterfallData.map(({ step, offsetPercent, widthPercent }) => {
          const isSelected = step.id === selectedStepId;
          const stepLabel = step.step_index != null ? `#${step.step_index + 1} ${step.name}` : step.name;
          const llmCount = step.llm_call_count ?? step.llm_calls.length;
          const toolCount = step.tool_call_count ?? step.tool_calls.length;

          return (
            <Tooltip key={step.id}>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  onClick={() => onStepClick?.(step)}
                  className={cn(
                    "group flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-all",
                    isSelected
                      ? "bg-primary/8 ring-1 ring-primary/25"
                      : "hover:bg-accent/30",
                  )}
                >
                  {/* Step label */}
                  <span className="w-28 shrink-0 truncate text-[11px] font-medium text-foreground">
                    {stepLabel}
                  </span>

                  {/* Waterfall bar */}
                  <div className="relative flex-1 h-5 rounded bg-muted/20">
                    <div
                      className={cn(
                        "absolute top-0.5 bottom-0.5 rounded-sm transition-all",
                        statusBarColor(step.status),
                        isSelected && "ring-1 ring-primary/40",
                      )}
                      style={{
                        left: `${offsetPercent}%`,
                        width: `${widthPercent}%`,
                      }}
                    />
                  </div>

                  {/* Duration label */}
                  <span className="w-14 shrink-0 text-right text-[11px] tabular-nums text-muted-foreground">
                    {formatDuration(step.latency_ms)}
                  </span>
                </button>
              </TooltipTrigger>
              <TooltipContent side="top" className="space-y-1 text-xs">
                <div className="font-semibold">{stepLabel}</div>
                <div className="flex items-center gap-3 text-muted-foreground">
                  <span>{formatDuration(step.latency_ms)}</span>
                  <span>{llmCount} LLM</span>
                  <span>{toolCount} tools</span>
                  <span className="capitalize">{step.status}</span>
                </div>
                {step.error && (
                  <div className="max-w-[240px] truncate text-red-400">{step.error}</div>
                )}
              </TooltipContent>
            </Tooltip>
          );
        })}

        {/* Time axis */}
        {totalMs > 0 && (
          <div className="flex items-center gap-2 pl-[7.5rem] pr-[3.75rem] pt-1">
            <div className="relative flex-1 h-3">
              <div className="absolute inset-x-0 top-1/2 h-px bg-border/40" />
              <span className="absolute left-0 -top-0.5 text-[9px] text-muted-foreground/60">0s</span>
              <span className="absolute left-1/4 -top-0.5 text-[9px] text-muted-foreground/60">
                {formatDuration(totalMs * 0.25)}
              </span>
              <span className="absolute left-1/2 -top-0.5 -translate-x-1/2 text-[9px] text-muted-foreground/60">
                {formatDuration(totalMs * 0.5)}
              </span>
              <span className="absolute left-3/4 -top-0.5 text-[9px] text-muted-foreground/60">
                {formatDuration(totalMs * 0.75)}
              </span>
              <span className="absolute right-0 -top-0.5 text-[9px] text-muted-foreground/60">
                {formatDuration(totalMs)}
              </span>
            </div>
          </div>
        )}
      </div>
    </TooltipProvider>
  );
}
