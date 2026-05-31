import { useMemo } from "react";
import {
  AlertTriangle,
  BrainCircuit,
  CheckCircle2,
  Clock,
  DollarSign,
  ListTree,
  TrendingDown,
  TrendingUp,
  Wrench,
  XCircle,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { ExecutionTrace, StepTrace } from "@/types";
import type { WorkflowRunRecord } from "@/lib/api";

import { StepWaterfall } from "./StepWaterfall";

interface ObservatoryOverviewProps {
  detail: ExecutionTrace | null;
  run: WorkflowRunRecord | null;
  previousRuns?: WorkflowRunRecord[];
  onStepClick?: (step: StepTrace) => void;
  onJumpToErrors?: () => void;
  onViewLogs?: () => void;
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

function formatTokens(n?: number | null): string {
  if (n == null || !Number.isFinite(n)) return "--";
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

function formatCost(value?: number | null): string {
  if (value == null || !Number.isFinite(value) || value === 0) return "--";
  return `$${value.toFixed(4)}`;
}

interface ScorecardItem {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  subtitle?: string;
  trend?: "up" | "down" | null;
  trendLabel?: string;
  tone?: "success" | "danger" | "warning" | "neutral";
}

export function ObservatoryOverview({
  detail,
  run,
  previousRuns,
  onStepClick,
  onJumpToErrors,
  onViewLogs,
}: ObservatoryOverviewProps) {
  const durationMs =
    detail?.duration_ms ??
    (run?.started_at && run?.completed_at
      ? new Date(run.completed_at).getTime() - new Date(run.started_at).getTime()
      : null);

  const stepCount = detail?.step_count ?? run?.total_steps ?? 0;
  const completedSteps = detail?.completed_steps ?? run?.completed_steps ?? 0;
  const failedSteps = detail?.failed_steps ?? 0;
  const llmCount = detail?.llm_call_count ?? 0;
  const toolCount = detail?.tool_call_count ?? 0;
  const totalTokens = detail?.total_tokens ?? 0;
  const cost = detail?.total_cost_usd;
  const status = detail?.status ?? run?.phase ?? "unknown";

  // Compare with previous run for trend indicators
  const prevRun = previousRuns && previousRuns.length > 1 ? previousRuns[1] : null;
  const prevDuration =
    prevRun?.started_at && prevRun?.completed_at
      ? new Date(prevRun.completed_at).getTime() - new Date(prevRun.started_at).getTime()
      : null;

  const durationTrend = useMemo((): { direction: "up" | "down" | null; label: string } => {
    if (durationMs == null || prevDuration == null) return { direction: null, label: "" };
    const diff = durationMs - prevDuration;
    const pct = Math.round((Math.abs(diff) / prevDuration) * 100);
    if (pct < 5) return { direction: null, label: "" };
    return {
      direction: diff > 0 ? "up" : "down",
      label: `${diff > 0 ? "+" : "-"}${pct}%`,
    };
  }, [durationMs, prevDuration]);

  const scorecard: ScorecardItem[] = useMemo(() => [
    {
      icon: Clock,
      label: "Duration",
      value: formatDuration(durationMs),
      trend: durationTrend.direction,
      trendLabel: durationTrend.label,
      tone: "neutral" as const,
    },
    {
      icon: ListTree,
      label: "Steps",
      value: `${completedSteps}/${stepCount}`,
      subtitle: failedSteps > 0 ? `${failedSteps} failed` : stepCount > 0 && completedSteps === stepCount ? "all passed" : undefined,
      tone: failedSteps > 0 ? "danger" as const : completedSteps === stepCount ? "success" as const : "warning" as const,
    },
    {
      icon: BrainCircuit,
      label: "LLM Calls",
      value: String(llmCount),
      subtitle: totalTokens > 0 ? `${formatTokens(totalTokens)} tokens` : undefined,
      tone: "neutral" as const,
    },
    {
      icon: Wrench,
      label: "Tool Calls",
      value: String(toolCount),
      tone: "neutral" as const,
    },
    {
      icon: DollarSign,
      label: "Cost",
      value: formatCost(cost),
      subtitle: detail?.prompt_tokens != null ? `${detail.prompt_tokens}p / ${detail.completion_tokens ?? 0}c` : undefined,
      tone: "neutral" as const,
    },
  ], [completedSteps, cost, detail?.completion_tokens, detail?.prompt_tokens, durationMs, durationTrend, failedSteps, llmCount, stepCount, toolCount, totalTokens]);

  // Signals/verdict
  const signals = useMemo(() => {
    const items: { icon: React.ComponentType<{ className?: string }>; message: string; tone: "success" | "warning" | "danger" | "info" }[] = [];
    const s = status.toLowerCase();

    if (s === "completed" || s === "succeeded") {
      items.push({ icon: CheckCircle2, message: `All ${stepCount} steps completed successfully`, tone: "success" });
    } else if (s === "failed" || s === "error") {
      items.push({ icon: XCircle, message: `Execution failed — ${failedSteps} step${failedSteps !== 1 ? "s" : ""} with errors`, tone: "danger" });
    } else if (s === "running" || s === "in_progress") {
      items.push({ icon: Zap, message: `Execution in progress — ${completedSteps}/${stepCount} steps done`, tone: "info" });
    }

    // Hottest step
    if (detail && detail.steps.length > 0) {
      const sorted = [...detail.steps].sort((a, b) => (b.latency_ms ?? 0) - (a.latency_ms ?? 0));
      const hottest = sorted[0];
      if (hottest && hottest.latency_ms != null && durationMs != null && durationMs > 0) {
        const pct = Math.round((hottest.latency_ms / durationMs) * 100);
        if (pct > 20) {
          items.push({
            icon: Zap,
            message: `Hottest step: ${hottest.name} (${pct}% of total time, ${formatDuration(hottest.latency_ms)})`,
            tone: "info",
          });
        }
      }
    }

    // Warnings
    if (detail) {
      const warningEvents = detail.events.filter((e) => e.event_type === "WARNING").length;
      const errorEvents = detail.events.filter((e) => e.event_type === "ERROR" || e.event_type === "STEP_FAILED").length;
      if (warningEvents > 0) {
        items.push({ icon: AlertTriangle, message: `${warningEvents} warning event${warningEvents !== 1 ? "s" : ""} during execution`, tone: "warning" });
      }
      if (errorEvents > 0 && s !== "failed") {
        items.push({ icon: AlertTriangle, message: `${errorEvents} error event${errorEvents !== 1 ? "s" : ""} recorded`, tone: "danger" });
      }
    }

    return items;
  }, [completedSteps, detail, durationMs, failedSteps, status, stepCount]);

  const orderedSteps = useMemo(
    () => detail ? [...detail.steps].sort((a, b) => (a.step_index ?? 999) - (b.step_index ?? 999)) : [],
    [detail],
  );

  // Empty state
  if (!detail && !run) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center">
        <Clock className="h-8 w-8 text-muted-foreground/30" />
        <p className="mt-3 text-sm text-muted-foreground">Select a workflow run to see its overview.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4 p-4">
      {/* Scorecard */}
      <div className="grid grid-cols-2 gap-2.5 md:grid-cols-3 lg:grid-cols-5">
        {scorecard.map((item) => {
          const Icon = item.icon;
          return (
            <div
              key={item.label}
              className={cn(
                "rounded-lg border p-3 transition-colors",
                item.tone === "success" && "border-emerald-500/20 bg-emerald-500/5",
                item.tone === "danger" && "border-red-500/20 bg-red-500/5",
                item.tone === "warning" && "border-amber-500/20 bg-amber-500/5",
                item.tone === "neutral" && "border-border/50 bg-card",
              )}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                  <Icon className="h-3 w-3" />
                  {item.label}
                </div>
                {item.trend && (
                  <span className={cn(
                    "flex items-center gap-0.5 text-[10px] font-medium",
                    item.trend === "up" ? "text-red-400" : "text-emerald-400",
                  )}>
                    {item.trend === "up" ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
                    {item.trendLabel}
                  </span>
                )}
              </div>
              <p className="mt-1.5 text-lg font-semibold tabular-nums text-foreground">{item.value}</p>
              {item.subtitle && (
                <p className="mt-0.5 text-[11px] text-muted-foreground">{item.subtitle}</p>
              )}
            </div>
          );
        })}
      </div>

      {/* Step Waterfall */}
      {orderedSteps.length > 0 && (
        <div className="rounded-lg border border-border/50 bg-card p-3">
          <div className="mb-2 flex items-center justify-between">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Step Waterfall</h4>
            <span className="text-[10px] text-muted-foreground">{orderedSteps.length} steps &middot; {formatDuration(durationMs)} total</span>
          </div>
          <StepWaterfall
            steps={orderedSteps}
            executionStartedAt={detail?.started_at}
            onStepClick={onStepClick}
          />
        </div>
      )}

      {/* Signals & Verdict */}
      {signals.length > 0 && (
        <div className="rounded-lg border border-border/50 bg-card p-3">
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Signals</h4>
          <div className="space-y-1.5">
            {signals.map((signal, idx) => {
              const SIcon = signal.icon;
              return (
                <div
                  key={idx}
                  className={cn(
                    "flex items-center gap-2 rounded-md px-2.5 py-1.5 text-xs",
                    signal.tone === "success" && "text-emerald-600 dark:text-emerald-400",
                    signal.tone === "danger" && "text-red-600 dark:text-red-400",
                    signal.tone === "warning" && "text-amber-600 dark:text-amber-400",
                    signal.tone === "info" && "text-sky-600 dark:text-sky-400",
                  )}
                >
                  <SIcon className="h-3.5 w-3.5 shrink-0" />
                  <span>{signal.message}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Quick Actions */}
      <div className="flex flex-wrap items-center gap-2">
        {failedSteps > 0 && onJumpToErrors && (
          <button
            type="button"
            onClick={onJumpToErrors}
            className="rounded-md border border-red-500/20 bg-red-500/5 px-3 py-1.5 text-xs font-medium text-red-600 transition-colors hover:bg-red-500/10 dark:text-red-400"
          >
            Jump to errors
          </button>
        )}
        {onViewLogs && (
          <button
            type="button"
            onClick={onViewLogs}
            className="rounded-md border border-border/50 bg-card px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            View raw logs
          </button>
        )}
      </div>

      {/* No detail notice */}
      {!detail && run && (
        <div className="rounded-lg border border-border/50 bg-muted/20 p-3 text-xs text-muted-foreground">
          Indexed execution detail has not been captured for this workflow run yet. The waterfall and model/tool analysis will appear once trace ingestion completes.
        </div>
      )}
    </div>
  );
}
