import { useMemo } from "react";
import { ArrowDown, ArrowRightLeft, ArrowUp, GitCompare, Minus, TrendingDown, TrendingUp } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { ExecutionTrace, StepTrace } from "@/types";

interface ExecutionDiffViewProps {
  left: ExecutionTrace | null;
  right: ExecutionTrace | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatDuration(ms?: number | null): string {
  if (ms == null || !Number.isFinite(ms)) return "--";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const minutes = Math.floor(seconds / 60);
  const rem = Math.round(seconds % 60);
  return `${minutes}m ${rem}s`;
}

function pctChange(oldVal: number, newVal: number): number | null {
  if (oldVal === 0 && newVal === 0) return null;
  if (oldVal === 0) return 100;
  return Math.round(((newVal - oldVal) / oldVal) * 100);
}

type DeltaDirection = "up" | "down" | "same";

function deltaDirection(oldVal: number, newVal: number): DeltaDirection {
  if (newVal > oldVal) return "up";
  if (newVal < oldVal) return "down";
  return "same";
}

function isRegression(_metric: "duration" | "tokens" | "errors", direction: DeltaDirection): boolean {
  // For duration and tokens, "up" is a regression (worse). For errors, "up" is regression.
  return direction === "up";
}

function isImprovement(_metric: "duration" | "tokens" | "errors", direction: DeltaDirection): boolean {
  return direction === "down";
}

// ── Delta Badge ──────────────────────────────────────────────────────────────

function DeltaIndicator({ oldVal, newVal, metric, unit = "" }: { oldVal: number; newVal: number; metric: "duration" | "tokens" | "errors"; unit?: string }) {
  const pct = pctChange(oldVal, newVal);
  const dir = deltaDirection(oldVal, newVal);
  if (pct === null || dir === "same") {
    return <span className="inline-flex items-center gap-0.5 text-[10px] text-muted-foreground"><Minus className="h-2.5 w-2.5" /> no change</span>;
  }
  const regress = isRegression(metric, dir);
  const improve = isImprovement(metric, dir);
  return (
    <span className={cn(
      "inline-flex items-center gap-0.5 text-[10px] font-medium",
      regress && "text-red-400",
      improve && "text-emerald-400",
      !regress && !improve && "text-muted-foreground",
    )}>
      {dir === "up" ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
      {Math.abs(pct)}%{unit && ` ${unit}`}
      {regress && <span className="ml-1 text-[9px] uppercase tracking-wide">regression</span>}
      {improve && <span className="ml-1 text-[9px] uppercase tracking-wide">improved</span>}
    </span>
  );
}

// ── Diff Row ─────────────────────────────────────────────────────────────────

function DiffBadge({ value }: { value: string }) {
  return (
    <span className="inline-flex items-center rounded-full border border-border/60 bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
      {value}
    </span>
  );
}

function DiffRow({ label, leftValue, rightValue, delta }: { label: string; leftValue: React.ReactNode; rightValue: React.ReactNode; delta?: React.ReactNode }) {
  const changed = JSON.stringify(leftValue) !== JSON.stringify(rightValue);
  return (
    <div className={cn("grid grid-cols-[1fr_auto_1fr] items-center gap-3 rounded-lg border px-3 py-2", changed ? "border-amber-500/30 bg-amber-500/5" : "border-border/50 bg-card")}>
      <div className="min-w-0 text-right">
        <p className="text-[11px] text-muted-foreground">{label}</p>
        <div className="mt-0.5 text-sm font-medium text-foreground">{leftValue}</div>
      </div>
      <div className="flex flex-col items-center gap-0.5">
        <ArrowRightLeft className={cn("h-3.5 w-3.5 shrink-0", changed ? "text-amber-500" : "text-muted-foreground/40")} />
        {delta && <div className="mt-0.5">{delta}</div>}
      </div>
      <div className="min-w-0 text-left">
        <p className="text-[11px] text-muted-foreground">{label}</p>
        <div className="mt-0.5 text-sm font-medium text-foreground">{rightValue}</div>
      </div>
    </div>
  );
}

// ── Step Comparison with Duration Delta ──────────────────────────────────────

function StepDiff({ leftSteps, rightSteps }: { leftSteps: StepTrace[]; rightSteps: StepTrace[] }) {
  const rows = useMemo(() => {
    const maxLen = Math.max(leftSteps.length, rightSteps.length);
    const out: { left?: StepTrace; right?: StepTrace; status: "same" | "changed" | "added" | "removed" }[] = [];
    for (let i = 0; i < maxLen; i++) {
      const l = leftSteps[i];
      const r = rightSteps[i];
      if (l && r) {
        const changed = l.status !== r.status || l.latency_ms !== r.latency_ms || l.error !== r.error;
        out.push({ left: l, right: r, status: changed ? "changed" : "same" });
      } else if (l && !r) {
        out.push({ left: l, status: "removed" });
      } else if (!l && r) {
        out.push({ right: r, status: "added" });
      }
    }
    return out;
  }, [leftSteps, rightSteps]);

  return (
    <div className="space-y-2">
      <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Step Comparison</h4>
      <div className="space-y-1">
        {rows.map((row, idx) => {
          const leftMs = row.left?.latency_ms ?? 0;
          const rightMs = row.right?.latency_ms ?? 0;
          const dir = deltaDirection(leftMs, rightMs);
          return (
            <div
              key={idx}
              className={cn(
                "grid grid-cols-[1fr_auto_1fr] items-center gap-3 rounded-lg border px-3 py-2",
                row.status === "same" && "border-border/50 bg-card",
                row.status === "changed" && "border-amber-500/30 bg-amber-500/5",
                row.status === "added" && "border-emerald-500/30 bg-emerald-500/5",
                row.status === "removed" && "border-red-500/30 bg-red-500/5",
              )}
            >
              <div className="min-w-0 text-right">
                {row.left ? (
                  <>
                    <p className="text-sm font-medium text-foreground">{row.left.name}</p>
                    <p className="text-[11px] text-muted-foreground">
                      <Badge variant="outline" className={cn("text-[9px] mr-1", row.left.status === "completed" ? "border-emerald-500/20 text-emerald-400" : row.left.status === "failed" ? "border-red-500/20 text-red-400" : "")}>
                        {row.left.status}
                      </Badge>
                      {formatDuration(row.left.latency_ms)}
                    </p>
                  </>
                ) : (
                  <span className="text-sm text-muted-foreground/40">—</span>
                )}
              </div>
              <div className="flex flex-col items-center gap-0.5">
                {row.status === "changed" && dir !== "same" && (
                  <span className={cn("text-[9px] font-medium", dir === "up" ? "text-red-400" : "text-emerald-400")}>
                    {dir === "up" ? <ArrowUp className="h-3 w-3 inline" /> : <ArrowDown className="h-3 w-3 inline" />}
                    {pctChange(leftMs, rightMs) != null && `${Math.abs(pctChange(leftMs, rightMs)!)}%`}
                  </span>
                )}
                {row.status === "added" && <Badge variant="outline" className="text-[8px] border-emerald-500/30 text-emerald-400">NEW</Badge>}
                {row.status === "removed" && <Badge variant="outline" className="text-[8px] border-red-500/30 text-red-400">DEL</Badge>}
                {row.status === "same" && <Minus className="h-3 w-3 text-muted-foreground/30" />}
              </div>
              <div className="min-w-0 text-left">
                {row.right ? (
                  <>
                    <p className="text-sm font-medium text-foreground">{row.right.name}</p>
                    <p className="text-[11px] text-muted-foreground">
                      <Badge variant="outline" className={cn("text-[9px] mr-1", row.right.status === "completed" ? "border-emerald-500/20 text-emerald-400" : row.right.status === "failed" ? "border-red-500/20 text-red-400" : "")}>
                        {row.right.status}
                      </Badge>
                      {formatDuration(row.right.latency_ms)}
                    </p>
                  </>
                ) : (
                  <span className="text-sm text-muted-foreground/40">—</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Side-by-Side Mini Waterfall ──────────────────────────────────────────────

function MiniWaterfallBar({ step, maxMs }: { step: StepTrace; maxMs: number }) {
  const widthPct = maxMs > 0 ? Math.max(2, ((step.latency_ms ?? 0) / maxMs) * 100) : 2;
  const s = step.status.toLowerCase();
  const barColor = s === "completed" || s === "succeeded" ? "bg-emerald-500" : s === "failed" || s === "error" ? "bg-red-500" : "bg-sky-500";
  return (
    <div className="flex items-center gap-2">
      <span className="w-20 truncate text-right text-[10px] text-muted-foreground">{step.name}</span>
      <div className="flex-1 h-3 rounded-sm bg-muted/20 overflow-hidden">
        <div className={cn("h-full rounded-sm", barColor)} style={{ width: `${widthPct}%` }} />
      </div>
      <span className="w-14 text-[9px] text-muted-foreground tabular-nums">{formatDuration(step.latency_ms)}</span>
    </div>
  );
}

function CompareWaterfall({ leftSteps, rightSteps }: { leftSteps: StepTrace[]; rightSteps: StepTrace[] }) {
  const maxMs = useMemo(() => {
    const allMs = [...leftSteps, ...rightSteps].map((s) => s.latency_ms ?? 0);
    return Math.max(...allMs, 1);
  }, [leftSteps, rightSteps]);

  return (
    <div className="space-y-2">
      <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Waterfall Comparison</h4>
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-1">
          <p className="text-[10px] font-medium text-muted-foreground mb-1">Left (baseline)</p>
          {leftSteps.map((step) => (
            <MiniWaterfallBar key={step.id} step={step} maxMs={maxMs} />
          ))}
        </div>
        <div className="space-y-1">
          <p className="text-[10px] font-medium text-muted-foreground mb-1">Right (current)</p>
          {rightSteps.map((step) => (
            <MiniWaterfallBar key={step.id} step={step} maxMs={maxMs} />
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Summary Card ─────────────────────────────────────────────────────────────

function DiffSummaryCard({ left, right }: { left: ExecutionTrace; right: ExecutionTrace }) {
  const durationDir = deltaDirection(left.duration_ms ?? 0, right.duration_ms ?? 0);
  const tokenDir = deltaDirection(left.total_tokens, right.total_tokens);
  const leftErrors = left.steps.filter((s) => s.status.toLowerCase() === "failed" || s.status.toLowerCase() === "error").length;
  const rightErrors = right.steps.filter((s) => s.status.toLowerCase() === "failed" || s.status.toLowerCase() === "error").length;
  const errDir = deltaDirection(leftErrors, rightErrors);

  const hasRegression = isRegression("duration", durationDir) || isRegression("tokens", tokenDir) || isRegression("errors", errDir);
  const hasImprovement = isImprovement("duration", durationDir) || isImprovement("tokens", tokenDir) || isImprovement("errors", errDir);

  return (
    <div className={cn(
      "rounded-lg border px-4 py-3",
      hasRegression && !hasImprovement && "border-red-500/30 bg-red-500/5",
      hasImprovement && !hasRegression && "border-emerald-500/30 bg-emerald-500/5",
      hasRegression && hasImprovement && "border-amber-500/30 bg-amber-500/5",
      !hasRegression && !hasImprovement && "border-border/50 bg-card",
    )}>
      <div className="flex items-center gap-2 mb-2">
        {hasRegression && <TrendingUp className="h-4 w-4 text-red-400" />}
        {hasImprovement && !hasRegression && <TrendingDown className="h-4 w-4 text-emerald-400" />}
        <span className="text-xs font-semibold text-foreground">
          {hasRegression && hasImprovement && "Mixed: regressions and improvements detected"}
          {hasRegression && !hasImprovement && "Regression detected"}
          {!hasRegression && hasImprovement && "Improvement detected"}
          {!hasRegression && !hasImprovement && "No significant change"}
        </span>
      </div>
      <div className="flex flex-wrap gap-4 text-[11px]">
        <div>
          <span className="text-muted-foreground mr-1">Duration:</span>
          <DeltaIndicator oldVal={left.duration_ms ?? 0} newVal={right.duration_ms ?? 0} metric="duration" />
        </div>
        <div>
          <span className="text-muted-foreground mr-1">Tokens:</span>
          <DeltaIndicator oldVal={left.total_tokens} newVal={right.total_tokens} metric="tokens" />
        </div>
        <div>
          <span className="text-muted-foreground mr-1">Errors:</span>
          <DeltaIndicator oldVal={leftErrors} newVal={rightErrors} metric="errors" />
        </div>
      </div>
    </div>
  );
}

// ── Main Component ───────────────────────────────────────────────────────────

export function ExecutionDiffView({ left, right }: ExecutionDiffViewProps) {
  if (!left || !right) {
    return (
      <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border/70 bg-card/50 py-16">
        <GitCompare className="h-8 w-8 text-muted-foreground/40" />
        <p className="mt-3 text-sm text-muted-foreground">Select two executions to compare.</p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3 text-center">
        <div>
          <p className="text-sm font-semibold text-foreground">{left.workflow_name}</p>
          <p className="text-[11px] text-muted-foreground truncate">{left.id}</p>
        </div>
        <GitCompare className="h-4 w-4 text-muted-foreground" />
        <div>
          <p className="text-sm font-semibold text-foreground">{right.workflow_name}</p>
          <p className="text-[11px] text-muted-foreground truncate">{right.id}</p>
        </div>
      </div>

      {/* Summary card with regression/improvement indicators */}
      <DiffSummaryCard left={left} right={right} />

      {/* Metric diff rows with inline delta */}
      <div className="space-y-2">
        <DiffRow
          label="Status"
          leftValue={<DiffBadge value={left.status} />}
          rightValue={<DiffBadge value={right.status} />}
        />
        <DiffRow
          label="Duration"
          leftValue={formatDuration(left.duration_ms)}
          rightValue={formatDuration(right.duration_ms)}
          delta={<DeltaIndicator oldVal={left.duration_ms ?? 0} newVal={right.duration_ms ?? 0} metric="duration" />}
        />
        <DiffRow
          label="Steps"
          leftValue={left.step_count}
          rightValue={right.step_count}
        />
        <DiffRow
          label="LLM Calls"
          leftValue={left.llm_call_count}
          rightValue={right.llm_call_count}
        />
        <DiffRow
          label="Tool Calls"
          leftValue={left.tool_call_count}
          rightValue={right.tool_call_count}
        />
        <DiffRow
          label="Total Tokens"
          leftValue={left.total_tokens.toLocaleString()}
          rightValue={right.total_tokens.toLocaleString()}
          delta={<DeltaIndicator oldVal={left.total_tokens} newVal={right.total_tokens} metric="tokens" />}
        />
      </div>

      {/* Side-by-side waterfall */}
      {(left.steps.length > 0 || right.steps.length > 0) && (
        <CompareWaterfall leftSteps={left.steps} rightSteps={right.steps} />
      )}

      {/* Step-by-step diff */}
      <StepDiff leftSteps={left.steps} rightSteps={right.steps} />
    </div>
  );
}
