import { useMemo } from "react";
import { ArrowRightLeft, GitCompare } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ExecutionTrace } from "@/types";

interface ExecutionDiffViewProps {
  left: ExecutionTrace | null;
  right: ExecutionTrace | null;
}

function DiffBadge({ value }: { value: string }) {
  return (
    <span className="inline-flex items-center rounded-full border border-border/60 bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
      {value}
    </span>
  );
}

function DiffRow({ label, leftValue, rightValue }: { label: string; leftValue: React.ReactNode; rightValue: React.ReactNode }) {
  const changed = JSON.stringify(leftValue) !== JSON.stringify(rightValue);
  return (
    <div className={cn("grid grid-cols-[1fr_auto_1fr] items-center gap-3 rounded-xl border px-3 py-2", changed ? "border-amber-500/30 bg-amber-500/5" : "border-border/50 bg-card/55")}>
      <div className="min-w-0 text-right">
        <p className="text-[11px] text-muted-foreground">{label}</p>
        <div className="mt-0.5 text-sm font-medium text-foreground">{leftValue}</div>
      </div>
      <ArrowRightLeft className={cn("h-3.5 w-3.5 shrink-0", changed ? "text-amber-500" : "text-muted-foreground/40")} />
      <div className="min-w-0 text-left">
        <p className="text-[11px] text-muted-foreground">{label}</p>
        <div className="mt-0.5 text-sm font-medium text-foreground">{rightValue}</div>
      </div>
    </div>
  );
}

function StepDiff({ leftSteps, rightSteps }: { leftSteps: ExecutionTrace["steps"]; rightSteps: ExecutionTrace["steps"] }) {
  const rows = useMemo(() => {
    const maxLen = Math.max(leftSteps.length, rightSteps.length);
    const out: { left?: ExecutionTrace["steps"][number]; right?: ExecutionTrace["steps"][number]; status: "same" | "changed" | "added" | "removed" }[] = [];
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
      {rows.map((row, idx) => (
        <div
          key={idx}
          className={cn(
            "grid grid-cols-[1fr_auto_1fr] items-center gap-3 rounded-xl border px-3 py-2",
            row.status === "same" && "border-border/50 bg-card/55",
            row.status === "changed" && "border-amber-500/30 bg-amber-500/5",
            row.status === "added" && "border-emerald-500/30 bg-emerald-500/5",
            row.status === "removed" && "border-red-500/30 bg-red-500/5",
          )}
        >
          <div className="min-w-0 text-right">
            {row.left ? (
              <>
                <p className="text-sm font-medium text-foreground">{row.left.name}</p>
                <p className="text-[11px] text-muted-foreground">{row.left.status} · {row.left.latency_ms ?? 0} ms</p>
              </>
            ) : (
              <span className="text-sm text-muted-foreground/40">—</span>
            )}
          </div>
          <ArrowRightLeft className={cn("h-3.5 w-3.5 shrink-0", row.status === "same" ? "text-muted-foreground/40" : "text-amber-500")} />
          <div className="min-w-0 text-left">
            {row.right ? (
              <>
                <p className="text-sm font-medium text-foreground">{row.right.name}</p>
                <p className="text-[11px] text-muted-foreground">{row.right.status} · {row.right.latency_ms ?? 0} ms</p>
              </>
            ) : (
              <span className="text-sm text-muted-foreground/40">—</span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

export function ExecutionDiffView({ left, right }: ExecutionDiffViewProps) {
  if (!left || !right) {
    return (
      <div className="flex flex-col items-center justify-center rounded-[1.75rem] border border-dashed border-border/70 bg-card/30 py-16">
        <GitCompare className="h-8 w-8 text-muted-foreground/40" />
        <p className="mt-3 text-sm text-muted-foreground">Select two executions to compare.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3 text-center">
        <div>
          <p className="text-sm font-semibold text-foreground">{left.workflow_name}</p>
          <p className="text-[11px] text-muted-foreground">{left.id}</p>
        </div>
        <GitCompare className="h-4 w-4 text-muted-foreground" />
        <div>
          <p className="text-sm font-semibold text-foreground">{right.workflow_name}</p>
          <p className="text-[11px] text-muted-foreground">{right.id}</p>
        </div>
      </div>

      <div className="space-y-2">
        <DiffRow label="Status" leftValue={<DiffBadge value={left.status} />} rightValue={<DiffBadge value={right.status} />} />
        <DiffRow label="Duration" leftValue={`${left.duration_ms ?? 0} ms`} rightValue={`${right.duration_ms ?? 0} ms`} />
        <DiffRow label="Steps" leftValue={left.step_count} rightValue={right.step_count} />
        <DiffRow label="LLM Calls" leftValue={left.llm_call_count} rightValue={right.llm_call_count} />
        <DiffRow label="Tool Calls" leftValue={left.tool_call_count} rightValue={right.tool_call_count} />
        <DiffRow label="Total Tokens" leftValue={left.total_tokens} rightValue={right.total_tokens} />
      </div>

      <StepDiff leftSteps={left.steps} rightSteps={right.steps} />
    </div>
  );
}
