import { useMemo } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip as RTooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import {
  AlertTriangle,
  CheckCircle2,
  TrendingDown,
  TrendingUp,
  Zap,
  XCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { ExecutionTrace, StepTrace } from "@/types";
import type { WorkflowRunRecord } from "@/lib/api";
import {
  formatCurrency,
  formatDuration,
  formatTokens,
} from "./observatory-utils";
import { StepWaterfall } from "./StepWaterfall";

interface AnalyticsViewProps {
  detail: ExecutionTrace | null;
  run: WorkflowRunRecord | null;
  previousRuns?: WorkflowRunRecord[];
  onStepClick?: (step: StepTrace) => void;
}

// Muted, professional chart colors
const CHART_COLORS = {
  input: "#94a3b8",      // slate-400
  cache: "#14b8a6",      // teal-500
  reasoning: "#818cf8",  // indigo-400
  output: "#475569",     // slate-600
  step1: "#818cf8",
  step2: "#38bdf8",
  step3: "#34d399",
  step4: "#fbbf24",
  step5: "#fb7185",
};

function formatPercent(v: number): string {
  return `${Math.round(v)}%`;
}

function formatMs(v: number): string {
  if (v < 1000) return `${Math.round(v)}ms`;
  return `${(v / 1000).toFixed(1)}s`;
}

// Recharts tooltip styled for dark theme
function ChartTooltip({ active, payload, label, formatter }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-border/50 bg-popover px-3 py-2 text-xs shadow-lg">
      {label && <div className="mb-1 font-medium text-foreground">{label}</div>}
      {payload.map((entry: any, i: number) => (
        <div key={i} className="flex items-center gap-2 text-muted-foreground">
          <span className="size-2 rounded-full" style={{ backgroundColor: entry.color || entry.fill }} />
          <span>{entry.name}:</span>
          <span className="font-medium text-foreground tabular-nums">
            {formatter ? formatter(entry.value) : entry.value}
          </span>
        </div>
      ))}
    </div>
  );
}

export function AnalyticsView({ detail, run, previousRuns, onStepClick }: AnalyticsViewProps) {
  const durationMs =
    detail?.duration_ms ??
    (run?.started_at && run?.completed_at
      ? new Date(run.completed_at).getTime() - new Date(run.started_at).getTime()
      : null);

  const totalTokens = detail?.total_tokens ?? 0;
  const promptTokens = detail?.prompt_tokens ?? 0;
  const completionTokens = detail?.completion_tokens ?? 0;
  const cacheReadTokens = detail?.cache_read_tokens ?? 0;
  const reasoningTokens = detail?.reasoning_tokens ?? 0;
  const status = detail?.status ?? run?.phase ?? "unknown";

  const orderedSteps = useMemo(
    () =>
      detail
        ? [...detail.steps].sort((a, b) => (a.step_index ?? 999) - (b.step_index ?? 999))
        : [],
    [detail],
  );

  // Token breakdown pie data
  const tokenPieData = useMemo(() => {
    const nonCached = Math.max(promptTokens - cacheReadTokens, 0);
    return [
      { name: "Input", value: nonCached, color: CHART_COLORS.input },
      { name: "Cache", value: cacheReadTokens, color: CHART_COLORS.cache },
      { name: "Reasoning", value: reasoningTokens, color: CHART_COLORS.reasoning },
      { name: "Output", value: completionTokens, color: CHART_COLORS.output },
    ].filter((d) => d.value > 0);
  }, [promptTokens, cacheReadTokens, reasoningTokens, completionTokens]);

  const cacheHitRatio = useMemo(() => {
    const nonCachedInput = Math.max(promptTokens - cacheReadTokens, 0);
    const inputTotal = nonCachedInput + cacheReadTokens;
    if (inputTotal <= 0) return null;
    return cacheReadTokens / inputTotal;
  }, [promptTokens, cacheReadTokens]);

  // Step duration bar chart data
  const stepDurationData = useMemo(() => {
    if (!orderedSteps.length) return [];
    return orderedSteps.map((s) => ({
      name: s.name,
      duration: Math.round(s.latency_ms ?? 0),
      tokens: s.tokens_used ?? 0,
    }));
  }, [orderedSteps]);

  // Model efficiency scatter data
  const modelScatterData = useMemo(() => {
    if (!detail) return [];
    return detail.llm_calls.map((c) => ({
      name: c.model,
      tokens: c.total_tokens || c.prompt_tokens + c.completion_tokens,
      latency: Math.round(c.latency_ms || 0),
      cost: c.estimated_cost_usd || 0,
      reasoning: c.reasoning_tokens || 0,
    }));
  }, [detail]);

  // Run trend area chart data
  const runTrendData = useMemo(() => {
    return (previousRuns ?? []).slice(0, 15).reverse().map((r, i) => ({
      name: r.started_at
        ? new Date(r.started_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false })
        : `#${i + 1}`,
      duration:
        r.started_at && r.completed_at
          ? new Date(r.completed_at).getTime() - new Date(r.started_at).getTime()
          : 0,
      status: r.phase,
    }));
  }, [previousRuns]);

  // Tool usage data
  const toolUsageData = useMemo(() => {
    if (!detail) return [];
    const groups = new Map<string, { count: number; duration: number }>();
    for (const c of detail.tool_calls) {
      const g = groups.get(c.tool_name) ?? { count: 0, duration: 0 };
      g.count += 1;
      g.duration += c.latency_ms || c.duration_ms || 0;
      groups.set(c.tool_name, g);
    }
    return [...groups.entries()]
      .map(([name, g]) => ({ name, count: g.count, duration: Math.round(g.duration) }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 8);
  }, [detail]);

  // Reasoning analysis
  const reasoningAnalysis = useMemo(() => {
    if (!detail) return null;
    const callsWithReasoning = detail.llm_calls.filter(
      (c) => (c.reasoning_tokens ?? 0) > 0 || (c.reasoning_text && c.reasoning_text.trim()),
    );
    const totalReasoningTokens = detail.llm_calls.reduce((s, c) => s + (c.reasoning_tokens ?? 0), 0);
    return {
      callsWithReasoning: callsWithReasoning.length,
      totalCalls: detail.llm_calls.length,
      totalReasoningTokens,
      ratio: totalTokens > 0 ? (totalReasoningTokens / totalTokens) * 100 : 0,
      perCall: callsWithReasoning.map((c) => ({
        model: c.model,
        reasoningTokens: c.reasoning_tokens ?? 0,
        preview: (c.reasoning_text ?? "").slice(0, 100),
      })),
    };
  }, [detail, totalTokens]);

  // Quality flags
  const qualityFlags = useMemo(() => {
    if (!detail) return [];
    const warningCount = detail.events.filter((e) => e.event_type === "WARNING").length;
    const errorCount = detail.events.filter((e) => e.event_type === "ERROR" || e.event_type === "STEP_FAILED").length;
    const failedToolCount = detail.tool_calls.filter((c) => {
      const s = c.status.toLowerCase();
      return s === "failed" || s === "error" || Boolean(c.error_message);
    }).length;
    const missingTokenData = detail.llm_call_count > 0 && detail.total_tokens === 0;
    return [
      warningCount > 0 ? { label: `${warningCount} warning ${warningCount === 1 ? "event" : "events"}`, tone: "warning" as const } : null,
      errorCount > 0 ? { label: `${errorCount} error ${errorCount === 1 ? "event" : "events"}`, tone: "danger" as const } : null,
      failedToolCount > 0 ? { label: `${failedToolCount} tool failures`, tone: "danger" as const } : null,
      missingTokenData ? { label: "Token metrics incomplete", tone: "warning" as const } : null,
      totalTokens > 0 && cacheHitRatio != null && cacheHitRatio < 0.2
        ? { label: `Cache hit ratio low (${formatPercent(cacheHitRatio * 100)})`, tone: "warning" as const }
        : null,
    ].filter((item): item is { label: string; tone: "warning" | "danger" } => item !== null);
  }, [cacheHitRatio, detail, totalTokens]);

  // Signals
  const signals = useMemo(() => {
    const items: { icon: React.ComponentType<{ className?: string }>; message: string; tone: string }[] = [];
    const s = status.toLowerCase();
    const stepCount = detail?.step_count ?? run?.total_steps ?? 0;
    const completedSteps = detail?.completed_steps ?? run?.completed_steps ?? 0;
    const failedSteps = detail?.failed_steps ?? 0;
    if (s === "completed" || s === "succeeded") {
      items.push({ icon: CheckCircle2, message: `All ${stepCount} steps completed successfully`, tone: "text-emerald-500" });
    } else if (s === "failed" || s === "error") {
      items.push({ icon: XCircle, message: `Execution failed — ${failedSteps} step${failedSteps !== 1 ? "s" : ""} with errors`, tone: "text-red-500" });
    } else if (s === "running" || s === "in_progress") {
      items.push({ icon: Zap, message: `Execution in progress — ${completedSteps}/${stepCount} steps done`, tone: "text-amber-500" });
    }
    if (detail && orderedSteps.length > 0 && durationMs && durationMs > 0) {
      const hottest = [...orderedSteps].sort((a, b) => (b.latency_ms ?? 0) - (a.latency_ms ?? 0))[0];
      if (hottest?.latency_ms) {
        const pct = Math.round((hottest.latency_ms / durationMs) * 100);
        if (pct > 20) {
          items.push({ icon: Zap, message: `Hottest step: ${hottest.name} (${pct}% of total, ${formatDuration(hottest.latency_ms)})`, tone: "text-muted-foreground" });
        }
      }
    }
    return items;
  }, [detail, orderedSteps, durationMs, run, status]);

  // Duration trend
  const prevRun = previousRuns && previousRuns.length > 1 ? previousRuns[1] : null;
  const prevDuration = prevRun?.started_at && prevRun?.completed_at
    ? new Date(prevRun.completed_at).getTime() - new Date(prevRun.started_at).getTime()
    : null;
  const durationTrend = useMemo(() => {
    if (durationMs == null || prevDuration == null) return null;
    const diff = durationMs - prevDuration;
    const pct = Math.round((Math.abs(diff) / prevDuration) * 100);
    if (pct < 5) return null;
    return { direction: diff > 0 ? "up" as const : "down" as const, label: `${diff > 0 ? "+" : "-"}${pct}%` };
  }, [durationMs, prevDuration]);

  if (!detail && !run) {
    return (
      <div className="flex h-full flex-col items-center justify-center text-center">
        <Zap className="size-8 text-muted-foreground/20" />
        <p className="mt-3 text-sm text-muted-foreground">Select a workflow run to see analytics.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4 overflow-y-auto p-5">
      {/* Scorecard row */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
        <Scorecard label="Duration" value={formatDuration(durationMs)} trend={durationTrend} />
        <Scorecard
          label="Steps"
          value={`${detail?.completed_steps ?? run?.completed_steps ?? 0}/${detail?.step_count ?? run?.total_steps ?? 0}`}
          sub={(detail?.failed_steps ?? 0) > 0 ? `${detail?.failed_steps} failed` : "all passed"}
          tone={(detail?.failed_steps ?? 0) > 0 ? "danger" : "success"}
        />
        <Scorecard
          label="LLM Calls"
          value={String(detail?.llm_call_count ?? 0)}
          sub={totalTokens > 0 ? `${formatTokens(totalTokens)} tokens` : undefined}
        />
        <Scorecard label="Tool Calls" value={String(detail?.tool_call_count ?? 0)} />
        <Scorecard
          label="Cost"
          value={formatCurrency(detail?.total_cost_usd)}
          sub={detail?.prompt_tokens != null ? `${formatTokens(detail.prompt_tokens)}p / ${formatTokens(detail.completion_tokens)}c` : undefined}
        />
      </div>

      {/* Charts grid */}
      <div className="grid gap-4 lg:grid-cols-2">
        {/* Token Breakdown — Donut chart */}
        {tokenPieData.length > 0 && (
          <Panel title="Token Breakdown" subtitle={`${formatTokens(totalTokens)} total`}>
            <div className="flex items-center gap-4">
              <ResponsiveContainer width="50%" height={180}>
                <PieChart>
                  <Pie
                    data={tokenPieData}
                    dataKey="value"
                    nameKey="name"
                    cx="50%"
                    cy="50%"
                    innerRadius={45}
                    outerRadius={75}
                    paddingAngle={2}
                    stroke="none"
                  >
                    {tokenPieData.map((entry, i) => (
                      <Cell key={i} fill={entry.color} />
                    ))}
                  </Pie>
                  <RTooltip content={<ChartTooltip formatter={(v: number) => formatTokens(v)} />} />
                </PieChart>
              </ResponsiveContainer>
              <div className="flex-1 space-y-2">
                {tokenPieData.map((d) => (
                  <div key={d.name} className="flex items-center gap-2.5">
                    <span className="size-2.5 rounded-full" style={{ backgroundColor: d.color }} />
                    <span className="text-sm text-muted-foreground">{d.name}</span>
                    <span className="ml-auto text-sm font-medium tabular-nums text-foreground">
                      {formatTokens(d.value)}
                    </span>
                  </div>
                ))}
                {cacheHitRatio != null && (
                  <div className="pt-1.5 text-xs text-muted-foreground/60">
                    Cache hit: <span className="font-medium text-foreground">{formatPercent(cacheHitRatio * 100)}</span>
                  </div>
                )}
              </div>
            </div>
          </Panel>
        )}

        {/* Step Durations — Bar chart */}
        {stepDurationData.length > 0 && (
          <Panel title="Step Durations" subtitle={`${orderedSteps.length} steps · ${formatDuration(durationMs)} total`}>
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={stepDurationData} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border) / 0.3)" vertical={false} />
                <XAxis
                  dataKey="name"
                  tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                  tickLine={false}
                  axisLine={false}
                  interval={0}
                  angle={-15}
                  textAnchor="end"
                  height={50}
                />
                <YAxis
                  tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={(v) => formatMs(v)}
                />
                <RTooltip content={<ChartTooltip formatter={(v: number) => formatDuration(v)} />} cursor={{ fill: "hsl(var(--muted) / 0.2)" }} />
                <Bar dataKey="duration" name="Duration" fill={CHART_COLORS.reasoning} radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </Panel>
        )}

        {/* Run Trend — Area chart */}
        {runTrendData.length > 1 && (
          <Panel title="Run Duration Trend" subtitle={`Last ${runTrendData.length} runs`}>
            <ResponsiveContainer width="100%" height={180}>
              <AreaChart data={runTrendData} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="durationGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={CHART_COLORS.reasoning} stopOpacity={0.3} />
                    <stop offset="95%" stopColor={CHART_COLORS.reasoning} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border) / 0.3)" vertical={false} />
                <XAxis
                  dataKey="name"
                  tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                  tickLine={false}
                  axisLine={false}
                />
                <YAxis
                  tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={(v) => formatMs(v)}
                />
                <RTooltip content={<ChartTooltip formatter={(v: number) => formatDuration(v)} />} />
                <Area
                  type="monotone"
                  dataKey="duration"
                  name="Duration"
                  stroke={CHART_COLORS.reasoning}
                  strokeWidth={2}
                  fill="url(#durationGradient)"
                />
              </AreaChart>
            </ResponsiveContainer>
          </Panel>
        )}

        {/* Model Efficiency — Scatter chart */}
        {modelScatterData.length > 0 && (
          <Panel title="Model Efficiency" subtitle="Tokens vs latency, bubble = cost">
            <ResponsiveContainer width="100%" height={180}>
              <ScatterChart margin={{ top: 10, right: 10, left: 0, bottom: 10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border) / 0.3)" />
                <XAxis
                  dataKey="tokens"
                  name="Tokens"
                  tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={(v) => formatTokens(v)}
                />
                <YAxis
                  dataKey="latency"
                  name="Latency"
                  tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={(v) => formatMs(v)}
                />
                <ZAxis dataKey="cost" range={[40, 400]} name="Cost" />
                <RTooltip
                  content={<ChartTooltip formatter={(v: number, name: string) => name === "Latency" ? formatDuration(v) : name === "Cost" ? formatCurrency(v) : formatTokens(v)} />}
                  cursor={{ strokeDasharray: "3 3" }}
                />
                <Scatter data={modelScatterData} fill={CHART_COLORS.reasoning} fillOpacity={0.6} />
              </ScatterChart>
            </ResponsiveContainer>
          </Panel>
        )}

        {/* Tool Usage — Horizontal bar */}
        {toolUsageData.length > 0 && (
          <Panel title="Tool Usage" subtitle={`${toolUsageData.length} tools`}>
            <ResponsiveContainer width="100%" height={Math.max(180, toolUsageData.length * 32)}>
              <BarChart
                data={toolUsageData}
                layout="vertical"
                margin={{ top: 5, right: 10, left: 0, bottom: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border) / 0.3)" horizontal={false} />
                <XAxis
                  type="number"
                  tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                  tickLine={false}
                  axisLine={false}
                />
                <YAxis
                  type="category"
                  dataKey="name"
                  tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                  tickLine={false}
                  axisLine={false}
                  width={100}
                />
                <RTooltip content={<ChartTooltip formatter={(v: number) => `${v} calls`} />} cursor={{ fill: "hsl(var(--muted) / 0.2)" }} />
                <Bar dataKey="count" name="Calls" fill={CHART_COLORS.input} radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </Panel>
        )}
      </div>

      {/* Reasoning Analysis */}
      {reasoningAnalysis && reasoningAnalysis.totalReasoningTokens > 0 && (
        <Panel title="Reasoning Analysis" subtitle={`${reasoningAnalysis.callsWithReasoning}/${reasoningAnalysis.totalCalls} calls used reasoning`}>
          <div className="space-y-4">
            <div className="flex items-center gap-4">
              <div className="flex-1">
                <div className="mb-1.5 flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">Share of total tokens</span>
                  <span className="text-sm font-medium tabular-nums text-foreground">
                    {formatPercent(reasoningAnalysis.ratio)}%
                  </span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-muted/30">
                  <div
                    className="h-full rounded-full bg-indigo-400/70"
                    style={{ width: `${Math.max(reasoningAnalysis.ratio, 2)}%` }}
                  />
                </div>
              </div>
              <div className="text-right">
                <div className="text-lg font-semibold tabular-nums text-foreground">
                  {formatTokens(reasoningAnalysis.totalReasoningTokens)}
                </div>
                <div className="text-xs text-muted-foreground">reasoning tokens</div>
              </div>
            </div>
            <div className="space-y-2">
              {reasoningAnalysis.perCall.map((c, i) => (
                <div key={i} className="flex items-start gap-3 rounded-lg border border-border/30 bg-muted/15 px-3.5 py-2.5">
                  <span className="mt-0.5 size-1.5 shrink-0 rounded-full bg-indigo-400/70" />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-sm font-medium text-foreground">{c.model}</span>
                      <span className="text-xs text-muted-foreground tabular-nums">{formatTokens(c.reasoningTokens)} tok</span>
                    </div>
                    {c.preview && (
                      <p className="mt-0.5 truncate text-xs text-muted-foreground/50 font-mono">
                        {c.preview}
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </Panel>
      )}

      {/* Step Waterfall */}
      {orderedSteps.length > 0 && (
        <Panel title="Step Waterfall" subtitle={`${orderedSteps.length} steps`}>
          <StepWaterfall
            steps={orderedSteps}
            executionStartedAt={detail?.started_at}
            onStepClick={onStepClick}
          />
        </Panel>
      )}

      {/* Quality Flags + Signals */}
      {(qualityFlags.length > 0 || signals.length > 0) && (
        <div className="grid gap-4 lg:grid-cols-2">
          {qualityFlags.length > 0 && (
            <Panel title="Quality Flags">
              <div className="space-y-2">
                {qualityFlags.map((flag) => (
                  <div
                    key={flag.label}
                    className={cn(
                      "flex items-center gap-2.5 rounded-lg border px-3.5 py-2.5 text-sm",
                      flag.tone === "danger"
                        ? "border-red-500/15 bg-red-500/5 text-red-500/80"
                        : "border-amber-500/15 bg-amber-500/5 text-amber-500/80",
                    )}
                  >
                    <AlertTriangle className="size-4 shrink-0" />
                    {flag.label}
                  </div>
                ))}
              </div>
            </Panel>
          )}
          {signals.length > 0 && (
            <Panel title="Signals">
              <div className="space-y-2">
                {signals.map((signal, i) => {
                  const SIcon = signal.icon;
                  return (
                    <div key={i} className={cn("flex items-center gap-2.5 rounded-lg px-3.5 py-2.5 text-sm", signal.tone)}>
                      <SIcon className="size-4 shrink-0" />
                      <span>{signal.message}</span>
                    </div>
                  );
                })}
              </div>
            </Panel>
          )}
        </div>
      )}
    </div>
  );
}

// ─── UI Helpers ──────────────────────────────────────────────────────────────

function Scorecard({
  label,
  value,
  sub,
  trend,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  trend?: { direction: "up" | "down"; label: string } | null;
  tone?: "success" | "danger";
}) {
  return (
    <div className="rounded-xl border border-border/40 bg-card/30 p-3.5">
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">{label}</span>
        {trend && (
          <span className={cn(
            "flex items-center gap-0.5 text-xs font-medium",
            trend.direction === "up" ? "text-red-400" : "text-emerald-400",
          )}>
            {trend.direction === "up" ? <TrendingUp className="size-3" /> : <TrendingDown className="size-3" />}
            {trend.label}
          </span>
        )}
      </div>
      <p className="mt-1.5 text-xl font-semibold tabular-nums text-foreground">{value}</p>
      {sub && (
        <p className={cn(
          "mt-0.5 text-xs",
          tone === "danger" ? "text-red-400/70" : tone === "success" ? "text-emerald-400/70" : "text-muted-foreground/50",
        )}>
          {sub}
        </p>
      )}
    </div>
  );
}

function Panel({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-border/40 bg-card/20 p-4">
      <div className="mb-3">
        <h4 className="text-sm font-medium text-foreground">{title}</h4>
        {subtitle && <span className="text-xs text-muted-foreground/50">{subtitle}</span>}
      </div>
      {children}
    </div>
  );
}
