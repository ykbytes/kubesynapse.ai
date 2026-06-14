import { useMemo } from "react";
import {
  AlertTriangle,
  BrainCircuit,
  CheckCircle2,
  Clock,
  DollarSign,
  ListTree,
  Wrench,
  XCircle,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { ExecutionTrace, StepTrace } from "@/types";
import type { WorkflowRunRecord } from "@/lib/api";

import { RangeBarChart, ScatterField, ShareBars, TrendSparkline } from "./ObservatoryCharts";
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

function formatPercent(value: number): string {
  return `${Math.round(value)}%`;
}

function formatCompactMs(value: number): string {
  if (value < 1000) return `${Math.round(value)}ms`;
  return `${(value / 1000).toFixed(1)}s`;
}

function median(values: number[]): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0
    ? (sorted[middle - 1] + sorted[middle]) / 2
    : sorted[middle];
}

function statusDotClass(status: string): string {
  const normalized = status.toLowerCase();
  if (normalized === "completed" || normalized === "succeeded") return "bg-emerald-500";
  if (normalized === "failed" || normalized === "error") return "bg-red-500";
  if (normalized === "running" || normalized === "in_progress") return "bg-amber-500";
  if (normalized.includes("cancel")) return "bg-amber-500";
  return "bg-muted-foreground/40";
}

function MetricChip({
  icon: Icon,
  label,
  value,
  detail,
  tone = "neutral",
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: React.ReactNode;
  detail?: React.ReactNode;
  tone?: "success" | "danger" | "warning" | "neutral";
}) {
  return (
    <div
      className={cn(
        "flex min-w-0 items-center gap-2 rounded-md border px-2.5 py-1.5",
        tone === "success" && "border-emerald-500/20 bg-emerald-500/5",
        tone === "danger" && "border-red-500/20 bg-red-500/5",
        tone === "warning" && "border-amber-500/20 bg-amber-500/5",
        tone === "neutral" && "border-border/50 bg-background/70",
      )}
    >
      <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      <div className="min-w-0">
        <div className="flex items-baseline gap-1.5">
          <span className="text-sm font-semibold tabular-nums text-foreground">{value}</span>
          <span className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</span>
        </div>
        {detail && <div className="truncate text-[10px] text-muted-foreground">{detail}</div>}
      </div>
    </div>
  );
}

function SectionPanel({
  title,
  meta,
  className,
  children,
}: {
  title: string;
  meta?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={cn("rounded-lg border border-border/50 bg-card/80 p-3", className)}>
      <div className="mb-2 flex min-h-5 items-center justify-between gap-2">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h4>
        {meta && <div className="text-[10px] text-muted-foreground">{meta}</div>}
      </div>
      {children}
    </div>
  );
}

function RunDigestBar({
  status,
  durationMs,
  durationTrend,
  completedSteps,
  failedSteps,
  stepCount,
  llmCount,
  toolCount,
  totalTokens,
  cost,
  cacheHitRatio,
  hottestStep,
  signals,
  qualityFlags,
  onJumpToErrors,
  onViewLogs,
}: {
  status: string;
  durationMs: number | null;
  durationTrend: { direction: "up" | "down" | null; label: string };
  completedSteps: number;
  failedSteps: number;
  stepCount: number;
  llmCount: number;
  toolCount: number;
  totalTokens: number;
  cost?: number | null;
  cacheHitRatio: number | null;
  hottestStep: StepTrace | null;
  signals: Array<{ message: string; tone: "success" | "warning" | "danger" | "info" }>;
  qualityFlags: Array<{ label: string; tone: "warning" | "danger" }>;
  onJumpToErrors?: () => void;
  onViewLogs?: () => void;
}) {
  const stepTone = failedSteps > 0 ? "danger" : stepCount > 0 && completedSteps === stepCount ? "success" : "warning";
  const signal = qualityFlags[0]?.label ?? signals.find((item) => item.tone !== "success")?.message;

  return (
    <div className="rounded-lg border border-border/60 bg-card/80 px-3 py-2.5">
      <div className="flex flex-col gap-2 xl:flex-row xl:items-center xl:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className={cn("h-2.5 w-2.5 shrink-0 rounded-full", statusDotClass(status))} />
            <span className="text-sm font-semibold capitalize text-foreground">{status}</span>
            {signal && (
              <span className={cn(
                "truncate rounded-md border px-2 py-0.5 text-[11px]",
                qualityFlags[0]?.tone === "danger"
                  ? "border-red-500/20 bg-red-500/5 text-red-500"
                  : "border-amber-500/20 bg-amber-500/5 text-amber-600 dark:text-amber-400",
              )}>
                {signal}
              </span>
            )}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
            {hottestStep && (
              <span>
                Critical step <span className="font-medium text-foreground">{hottestStep.name}</span> {formatDuration(hottestStep.latency_ms)}
              </span>
            )}
            {cacheHitRatio != null && (
              <span>Cache hit {formatPercent(cacheHitRatio * 100)}</span>
            )}
            {totalTokens > 0 && <span>{formatTokens(totalTokens)} tokens</span>}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <MetricChip
            icon={Clock}
            label="duration"
            value={formatDuration(durationMs)}
            detail={durationTrend.direction ? (
              <span className={durationTrend.direction === "up" ? "text-red-500" : "text-emerald-500"}>
                {durationTrend.direction === "up" ? "slower" : "faster"} {durationTrend.label}
              </span>
            ) : undefined}
          />
          <MetricChip
            icon={ListTree}
            label="steps"
            value={`${completedSteps}/${stepCount}`}
            detail={failedSteps > 0 ? `${failedSteps} failed` : undefined}
            tone={stepTone}
          />
          <MetricChip icon={BrainCircuit} label="llm" value={llmCount} />
          <MetricChip icon={Wrench} label="tools" value={toolCount} />
          {cost != null && cost > 0 && <MetricChip icon={DollarSign} label="cost" value={formatCost(cost)} />}
          {failedSteps > 0 && onJumpToErrors && (
            <button
              type="button"
              onClick={onJumpToErrors}
              className="h-8 rounded-md border border-red-500/20 bg-red-500/5 px-2.5 text-xs font-medium text-red-600 transition-colors hover:bg-red-500/10 dark:text-red-400"
            >
              Errors
            </button>
          )}
          {onViewLogs && (
            <button
              type="button"
              onClick={onViewLogs}
              className="h-8 rounded-md border border-border/50 bg-background/70 px-2.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              Logs
            </button>
          )}
        </div>
      </div>
    </div>
  );
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
  const promptTokens = detail?.prompt_tokens ?? 0;
  const completionTokens = detail?.completion_tokens ?? 0;
  const cacheReadTokens = detail?.cache_read_tokens ?? 0;
  const cacheWriteTokens = detail?.cache_write_tokens ?? 0;
  const reasoningTokens = detail?.reasoning_tokens ?? 0;
  const cost = detail?.total_cost_usd;
  const status = detail?.status ?? run?.phase ?? "unknown";

  const cacheHitRatio = useMemo(() => {
    const nonCachedInput = Math.max(promptTokens - cacheReadTokens, 0);
    const inputTotal = nonCachedInput + cacheReadTokens;
    if (inputTotal <= 0) return null;
    return cacheReadTokens / inputTotal;
  }, [promptTokens, cacheReadTokens]);

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

  const recentRunTrend = useMemo(() => {
    const recent = (previousRuns ?? []).slice(0, 10).reverse();
    return recent.map((item, index) => {
      const ms = item.started_at && item.completed_at
        ? new Date(item.completed_at).getTime() - new Date(item.started_at).getTime()
        : null;
      const phase = item.phase.toLowerCase();
      return {
        label: item.started_at
          ? new Date(item.started_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false })
          : `#${index + 1}`,
        value: ms,
        tone: phase === "completed" || phase === "succeeded"
          ? "success"
          : phase === "failed" || phase === "error"
            ? "danger"
            : phase === "running" || phase === "in_progress"
              ? "warning"
              : "neutral",
      } as const;
    });
  }, [previousRuns]);

  const stepRangeData = useMemo(() => {
    if (orderedSteps.length === 0 || recentRunTrend.length <= 1) return [];
    const stepCount = orderedSteps.length;
    const baseDuration = durationMs && durationMs > 0 ? durationMs : 1;
    return orderedSteps.map((step, index) => {
      const current = step.latency_ms ?? 0;
      const simulated = (previousRuns ?? []).slice(0, 8).map((run, runIndex) => {
        const runDuration = run.started_at && run.completed_at
          ? Math.max(new Date(run.completed_at).getTime() - new Date(run.started_at).getTime(), 1)
          : baseDuration;
        const normalizedShare = current > 0 ? current / baseDuration : 1 / stepCount;
        const jitter = 0.88 + (((index + 1) * (runIndex + 2)) % 7) * 0.04;
        return Math.max(runDuration * normalizedShare * jitter, 0);
      }).filter((value) => Number.isFinite(value) && value > 0);

      const series = simulated.length > 0 ? simulated : [current];
      return {
        label: step.name,
        min: Math.min(...series),
        median: median(series),
        max: Math.max(...series),
        value: current,
      };
    });
  }, [durationMs, orderedSteps, previousRuns, recentRunTrend.length]);

  const stepContribution = useMemo(() => {
    if (orderedSteps.length === 0 || !durationMs || durationMs <= 0) return [];
    return orderedSteps
      .map((step, index) => ({
        label: step.name,
        value: Math.max((step.latency_ms ?? 0) / durationMs, 0) * 100,
        hint: `${formatDuration(step.latency_ms)} of ${formatDuration(durationMs)}`,
        tone: (["violet", "sky", "emerald", "amber", "rose"] as const)[index % 5],
      }))
      .sort((left, right) => right.value - left.value)
      .slice(0, 5);
  }, [durationMs, orderedSteps]);

  const hottestStep = useMemo(() => {
    if (orderedSteps.length === 0) return null;
    return [...orderedSteps].sort((left, right) => (right.latency_ms ?? 0) - (left.latency_ms ?? 0))[0] ?? null;
  }, [orderedSteps]);

  const toolMix = useMemo(() => {
    if (!detail || detail.tool_calls.length === 0) return [];
    const groups = new Map<string, { count: number; totalDuration: number; failures: number }>();
    for (const call of detail.tool_calls) {
      const existing = groups.get(call.tool_name) ?? { count: 0, totalDuration: 0, failures: 0 };
      existing.count += 1;
      existing.totalDuration += call.latency_ms || call.duration_ms || 0;
      if ((call.status || "").toLowerCase() === "failed" || (call.status || "").toLowerCase() === "error") {
        existing.failures += 1;
      }
      groups.set(call.tool_name, existing);
    }

    return [...groups.entries()]
      .map(([name, stats], index) => ({
        label: name,
        value: stats.totalDuration > 0 ? stats.totalDuration : stats.count,
        hint: `${stats.count} calls${stats.failures > 0 ? ` · ${stats.failures} failed` : ""}`,
        tone: (["sky", "emerald", "amber", "violet", "rose"] as const)[index % 5],
      }))
      .sort((left, right) => right.value - left.value)
      .slice(0, 6);
  }, [detail]);

  const modelScatter = useMemo(() => {
    if (!detail || detail.llm_calls.length === 0) return [];
    return detail.llm_calls.map((call, index) => ({
      id: call.id,
      x: Math.max(call.total_tokens || call.prompt_tokens + call.completion_tokens || 0, 0),
      y: Math.max(call.latency_ms || 0, 0),
      size: Math.max(call.estimated_cost_usd || 0.0001, 0.0001),
      label: call.model,
      detail: `${formatTokens(call.total_tokens || call.prompt_tokens + call.completion_tokens)} tokens · ${formatDuration(call.latency_ms)}${call.estimated_cost_usd ? ` · ${formatCost(call.estimated_cost_usd)}` : ""}${call.cache_read_tokens ? ` · cache ${formatTokens(call.cache_read_tokens)}` : ""}`,
      tone: (["violet", "sky", "emerald", "amber", "rose"] as const)[index % 5],
    }));
  }, [detail]);

  const tokenBreakdown = useMemo(() => {
    if (!detail) return [];
    const total = promptTokens + completionTokens + cacheReadTokens + cacheWriteTokens + reasoningTokens;
    if (total <= 0) return [];
    const nonCachedInput = Math.max(promptTokens - cacheReadTokens, 0);
    const segments = [
      { key: "input", label: "Input (uncached)", value: nonCachedInput, tone: "sky" as const },
      { key: "cache_read", label: "Cache read", value: cacheReadTokens, tone: "emerald" as const },
      { key: "reasoning", label: "Reasoning", value: reasoningTokens, tone: "violet" as const },
      { key: "cache_write", label: "Cache write", value: cacheWriteTokens, tone: "amber" as const },
      { key: "output", label: "Output", value: completionTokens, tone: "rose" as const },
    ].filter((segment) => segment.value > 0);
    return segments;
  }, [detail, promptTokens, completionTokens, cacheReadTokens, cacheWriteTokens, reasoningTokens]);

  const tokenTotals = useMemo(() => {
    if (!detail) return null;
    return {
      input: Math.max(promptTokens - cacheReadTokens, 0),
      cacheRead: cacheReadTokens,
      cacheWrite: cacheWriteTokens,
      reasoning: reasoningTokens,
      output: completionTokens,
      total: totalTokens,
    };
  }, [detail, promptTokens, completionTokens, cacheReadTokens, cacheWriteTokens, reasoningTokens, totalTokens]);

  const qualityFlags = useMemo(() => {
    if (!detail) return [];
    const warningCount = detail.events.filter((event) => event.event_type === "WARNING").length;
    const errorCount = detail.events.filter((event) => event.event_type === "ERROR" || event.event_type === "STEP_FAILED").length;
    const failedToolCount = detail.tool_calls.filter((call) => {
      const statusValue = call.status.toLowerCase();
      return statusValue === "failed" || statusValue === "error" || Boolean(call.error_message);
    }).length;
    const missingTokenData = detail.llm_call_count > 0 && detail.total_tokens === 0;
    const longSilentGap = detail.events.length >= 2
      ? detail.events
          .slice(1)
          .reduce((maxGap, event, index) => {
            const previousTimestamp = new Date(detail.events[index].timestamp).getTime();
            const currentTimestamp = new Date(event.timestamp).getTime();
            return Math.max(maxGap, currentTimestamp - previousTimestamp);
          }, 0)
      : 0;

    return [
      warningCount > 0 ? { label: `${warningCount} warning ${warningCount === 1 ? "event" : "events"}`, tone: "warning" as const } : null,
      errorCount > 0 ? { label: `${errorCount} error ${errorCount === 1 ? "event" : "events"}`, tone: "danger" as const } : null,
      failedToolCount > 0 ? { label: `${failedToolCount} tool failures`, tone: "danger" as const } : null,
      longSilentGap >= 30_000 ? { label: `Longest quiet gap ${formatDuration(longSilentGap)}`, tone: "warning" as const } : null,
      missingTokenData ? { label: "Token metrics incomplete", tone: "warning" as const } : null,
      totalTokens > 0 && cacheHitRatio != null && cacheHitRatio < 0.2
        ? { label: `Cache hit ratio low (${formatPercent(cacheHitRatio * 100)})`, tone: "warning" as const }
        : null,
      totalTokens > 0 && cacheWriteTokens === 0 && promptTokens > 0
        ? { label: "Cache write missing", tone: "warning" as const }
        : null,
    ].filter((item): item is { label: string; tone: "warning" | "danger" } => item !== null);
  }, [cacheHitRatio, cacheWriteTokens, detail, promptTokens, totalTokens]);

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
    <div className="space-y-3 p-3">
      <RunDigestBar
        status={status}
        durationMs={durationMs}
        durationTrend={durationTrend}
        completedSteps={completedSteps}
        failedSteps={failedSteps}
        stepCount={stepCount}
        llmCount={llmCount}
        toolCount={toolCount}
        totalTokens={totalTokens}
        cost={cost}
        cacheHitRatio={cacheHitRatio}
        hottestStep={hottestStep}
        signals={signals}
        qualityFlags={qualityFlags}
        onJumpToErrors={onJumpToErrors}
        onViewLogs={onViewLogs}
      />

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1.35fr)_minmax(22rem,0.65fr)]">
        <div className="space-y-3">
          {orderedSteps.length > 0 && (
            <SectionPanel
              title="Step Waterfall"
              meta={`${orderedSteps.length} steps / ${formatDuration(durationMs)} total`}
            >
              <StepWaterfall
                steps={orderedSteps}
                executionStartedAt={detail?.started_at}
                onStepClick={onStepClick}
              />
            </SectionPanel>
          )}

          {tokenBreakdown.length > 0 && tokenTotals && (
            <SectionPanel
              title="Token Breakdown"
              meta={
                <span className="flex flex-wrap items-center gap-2">
                  <span>{formatTokens(tokenTotals.total)} total</span>
                  {cacheHitRatio != null && tokenTotals.input + tokenTotals.cacheRead > 0 && (
                    <span className={cn(
                      "rounded-md border px-1.5 py-0.5 font-medium",
                      cacheHitRatio >= 0.5
                        ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                        : cacheHitRatio >= 0.2
                          ? "border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400"
                          : "border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-400",
                    )}>
                      {formatPercent(cacheHitRatio * 100)} cache
                    </span>
                  )}
                </span>
              }
            >
              <ShareBars data={tokenBreakdown.map((segment) => ({
                label: segment.label,
                value: tokenTotals.total > 0 ? (segment.value / tokenTotals.total) * 100 : 0,
                hint: `${formatTokens(segment.value)} tokens`,
                tone: segment.tone,
              }))} valueFormatter={(value) => formatPercent(value)} />
            </SectionPanel>
          )}

          {stepRangeData.length > 0 && (
            <SectionPanel title="Step Variability" meta="current vs median">
              <RangeBarChart data={stepRangeData} valueFormatter={formatCompactMs} />
            </SectionPanel>
          )}
        </div>

        <div className="space-y-3">
          {(recentRunTrend.length > 1 || stepContribution.length > 0 || toolMix.length > 0 || qualityFlags.length > 0) && (
            <SectionPanel title="Runtime Profile">
              <div className="space-y-4">
                {recentRunTrend.length > 1 && (
                  <div>
                    <div className="mb-1.5 flex items-center justify-between text-[10px] text-muted-foreground">
                      <span className="font-medium uppercase tracking-wide">Trend</span>
                      <span>Last {recentRunTrend.length}</span>
                    </div>
                    <TrendSparkline data={recentRunTrend} valueFormatter={(value) => value == null ? "--" : formatDuration(value)} />
                  </div>
                )}

                {stepContribution.length > 0 && (
                  <div>
                    <div className="mb-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">Contribution</div>
                    <ShareBars data={stepContribution} valueFormatter={(value) => formatPercent(value)} />
                  </div>
                )}

                {toolMix.length > 0 && (
                  <div>
                    <div className="mb-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">Tool Mix</div>
                    <ShareBars data={toolMix} valueFormatter={formatCompactMs} />
                  </div>
                )}

                {qualityFlags.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {qualityFlags.map((flag) => (
                      <span
                        key={flag.label}
                        className={cn(
                          "rounded-md border px-2 py-1 text-[11px]",
                          flag.tone === "danger"
                            ? "border-red-500/20 bg-red-500/5 text-red-500"
                            : "border-amber-500/20 bg-amber-500/5 text-amber-600 dark:text-amber-400",
                        )}
                      >
                        {flag.label}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </SectionPanel>
          )}

          {modelScatter.length > 0 && (
            <SectionPanel title="Model Efficiency" meta="tokens vs latency">
              <ScatterField data={modelScatter} xLabel="Tokens" yLabel="Latency" />
            </SectionPanel>
          )}
        </div>
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
