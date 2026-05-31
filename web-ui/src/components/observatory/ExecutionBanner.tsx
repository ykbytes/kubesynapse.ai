import {
  BrainCircuit,
  Clock,
  DollarSign,
  ExternalLink,
  ListTree,
  Wrench,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { ExecutionTrace } from "@/types";
import type { WorkflowRunRecord } from "@/lib/api";

interface ExecutionBannerProps {
  detail: ExecutionTrace | null;
  run: WorkflowRunRecord | null;
  workflowName: string;
  namespace: string;
  onNavigateToWorkflow?: () => void;
  onExportJson?: () => void;
  onExportHtml?: () => void;
  onRefresh?: () => void;
}

function statusColor(status: string): string {
  const s = status.toLowerCase();
  if (s === "completed" || s === "succeeded") return "bg-emerald-500";
  if (s === "failed" || s === "error") return "bg-red-500";
  if (s === "running" || s === "in_progress") return "bg-amber-500 animate-pulse";
  if (s.includes("cancel")) return "bg-amber-500";
  return "bg-muted-foreground/40";
}

function statusText(status: string): string {
  const s = status.toLowerCase();
  if (s === "completed" || s === "succeeded") return "text-emerald-600 dark:text-emerald-400";
  if (s === "failed" || s === "error") return "text-red-600 dark:text-red-400";
  if (s === "running" || s === "in_progress") return "text-amber-600 dark:text-amber-400";
  return "text-muted-foreground";
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

function formatCost(value?: number | null): string {
  if (value == null || !Number.isFinite(value) || value === 0) return "--";
  return `$${value.toFixed(4)}`;
}

export function ExecutionBanner({
  detail,
  run,
  workflowName,
  namespace,
  onNavigateToWorkflow,
  onExportJson,
  onExportHtml,
  onRefresh: _onRefresh,
}: ExecutionBannerProps) {
  const status = detail?.status ?? run?.phase ?? "unknown";
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
  const runId = detail?.run_id ?? run?.run_id;

  // Step progress as percentage
  const stepProgress = stepCount > 0 ? Math.round((completedSteps / stepCount) * 100) : 0;

  return (
    <div className="flex shrink-0 items-center gap-3 border-b border-border/50 bg-background/80 px-4 py-2.5 backdrop-blur-sm">
      {/* Status indicator + Workflow name */}
      <div className="flex items-center gap-2.5 min-w-0">
        <span className={cn("h-2.5 w-2.5 shrink-0 rounded-full", statusColor(status))} />
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="truncate text-sm font-semibold text-foreground">{workflowName}</h3>
            <span className={cn("text-xs font-medium capitalize", statusText(status))}>{status}</span>
          </div>
          <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
            <span>{namespace}</span>
            {detail?.agent_name && (
              <>
                <span className="text-border">/</span>
                <span>{detail.agent_name}</span>
              </>
            )}
            {runId && (
              <>
                <span className="text-border">/</span>
                <span className="font-mono">{runId}</span>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Divider */}
      <div className="h-8 w-px shrink-0 bg-border/50" />

      {/* KPI strip */}
      <div className="flex items-center gap-4">
        {/* Duration */}
        <div className="flex items-center gap-1.5">
          <Clock className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="text-sm font-medium tabular-nums text-foreground">{formatDuration(durationMs)}</span>
        </div>

        {/* Steps with progress bar */}
        <div className="flex items-center gap-1.5">
          <ListTree className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="text-sm font-medium tabular-nums text-foreground">
            {completedSteps}/{stepCount}
          </span>
          <div className="h-1.5 w-12 overflow-hidden rounded-full bg-muted/50">
            <div
              className={cn(
                "h-full rounded-full transition-all duration-500",
                failedSteps > 0 ? "bg-red-500" : stepProgress === 100 ? "bg-emerald-500" : "bg-amber-500",
              )}
              style={{ width: `${stepProgress}%` }}
            />
          </div>
          {failedSteps > 0 && (
            <span className="text-[10px] font-medium text-red-500">{failedSteps} failed</span>
          )}
        </div>

        {/* LLM */}
        <div className="flex items-center gap-1.5">
          <BrainCircuit className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="text-sm font-medium tabular-nums text-foreground">{llmCount}</span>
          {totalTokens > 0 && (
            <span className="text-[10px] text-muted-foreground">{totalTokens.toLocaleString()} tok</span>
          )}
        </div>

        {/* Tools */}
        <div className="flex items-center gap-1.5">
          <Wrench className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="text-sm font-medium tabular-nums text-foreground">{toolCount}</span>
        </div>

        {/* Cost */}
        {cost != null && cost > 0 && (
          <div className="flex items-center gap-1.5">
            <DollarSign className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="text-sm font-medium tabular-nums text-foreground">{formatCost(cost)}</span>
          </div>
        )}
      </div>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Actions */}
      <div className="flex items-center gap-1.5">
        {onNavigateToWorkflow && (
          <Button variant="ghost" size="sm" className="h-7 px-2 text-[11px]" onClick={onNavigateToWorkflow}>
            <ExternalLink className="mr-1 h-3 w-3" />
            Workflow
          </Button>
        )}
        {detail && onExportJson && (
          <Button variant="ghost" size="sm" className="h-7 px-2 text-[11px]" onClick={onExportJson}>
            JSON
          </Button>
        )}
        {detail && onExportHtml && (
          <Button variant="ghost" size="sm" className="h-7 px-2 text-[11px]" onClick={onExportHtml}>
            HTML
          </Button>
        )}
      </div>
    </div>
  );
}
