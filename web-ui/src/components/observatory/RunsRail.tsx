import { useMemo } from "react";
import { Activity, ChevronDown } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { WorkflowRunRecord } from "@/lib/api";

interface RunsRailProps {
  runs: WorkflowRunRecord[];
  selectedRunId: string | null;
  onSelectRun: (runId: string | null) => void;
  loading?: boolean;
  workflowName?: string;
}

function statusDot(phase: string): string {
  const s = phase.toLowerCase();
  if (s === "completed" || s === "succeeded") return "bg-emerald-500";
  if (s === "failed" || s === "error") return "bg-red-500";
  if (s === "running" || s === "in_progress") return "bg-amber-500 animate-pulse";
  if (s.includes("cancel")) return "bg-amber-500";
  return "bg-muted-foreground/40";
}

function formatShortTime(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function formatShortDate(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const now = new Date();
  const isToday =
    date.getDate() === now.getDate() &&
    date.getMonth() === now.getMonth() &&
    date.getFullYear() === now.getFullYear();
  if (isToday) return "Today";
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function formatDuration(ms?: number | null): string {
  if (ms == null || !Number.isFinite(ms)) return "";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  const minutes = Math.floor(seconds / 60);
  const rem = Math.round(seconds % 60);
  return `${minutes}m${rem}s`;
}

export function RunsRail({
  runs,
  selectedRunId,
  onSelectRun,
  loading,
  workflowName,
}: RunsRailProps) {
  const groupedByDate = useMemo(() => {
    const groups: { date: string; runs: WorkflowRunRecord[] }[] = [];
    let currentDate = "";
    let currentGroup: WorkflowRunRecord[] = [];

    for (const run of runs) {
      const dateStr = formatShortDate(run.started_at ?? run.created_at);
      if (dateStr !== currentDate) {
        if (currentGroup.length > 0) {
          groups.push({ date: currentDate, runs: currentGroup });
        }
        currentDate = dateStr;
        currentGroup = [run];
      } else {
        currentGroup.push(run);
      }
    }
    if (currentGroup.length > 0) {
      groups.push({ date: currentDate, runs: currentGroup });
    }
    return groups;
  }, [runs]);

  if (!workflowName) {
    return (
      <div className="flex h-full w-16 flex-col items-center justify-center border-r border-border/40 bg-background/30">
        <Activity className="h-4 w-4 text-muted-foreground/30" />
      </div>
    );
  }

  return (
    <TooltipProvider delayDuration={200}>
      <div className="flex h-full w-16 flex-col border-r border-border/40 bg-background/30">
        {/* Header */}
        <div className="flex shrink-0 flex-col items-center gap-0.5 border-b border-border/40 px-1 py-2">
          <Badge variant="outline" className="h-4 px-1 text-[9px] font-medium">
            {runs.length}
          </Badge>
          <span className="text-[9px] text-muted-foreground">runs</span>
        </div>

        {/* Rail body */}
        <ScrollArea className="flex-1 min-h-0">
          <div className="flex flex-col items-center gap-0.5 px-1 py-2">
            {loading && runs.length === 0 && (
              <div className="flex flex-col items-center gap-2 py-4">
                <div className="h-3 w-3 animate-spin rounded-full border-2 border-primary border-t-transparent" />
              </div>
            )}

            {groupedByDate.map((group) => (
              <div key={group.date} className="flex w-full flex-col items-center gap-0.5">
                {/* Date separator */}
                <span className="mt-1 mb-0.5 text-[8px] font-medium uppercase tracking-wider text-muted-foreground/60">
                  {group.date}
                </span>

                {group.runs.map((run) => {
                  const isSelected = run.run_id === selectedRunId;
                  const duration =
                    run.started_at && run.completed_at
                      ? new Date(run.completed_at).getTime() - new Date(run.started_at).getTime()
                      : null;

                  return (
                    <Tooltip key={run.id}>
                      <TooltipTrigger asChild>
                        <button
                          type="button"
                          onClick={() => onSelectRun(run.run_id ?? null)}
                          className={cn(
                            "group relative flex w-full flex-col items-center gap-0.5 rounded-lg px-1 py-1.5 transition-all",
                            isSelected
                              ? "bg-primary/12 ring-1 ring-primary/30"
                              : "hover:bg-accent/40",
                          )}
                        >
                          {/* Status dot */}
                          <span
                            className={cn(
                              "h-2.5 w-2.5 rounded-full transition-transform",
                              statusDot(run.phase),
                              isSelected && "scale-125 ring-2 ring-primary/20 ring-offset-1 ring-offset-background",
                            )}
                          />
                          {/* Time label */}
                          <span className={cn(
                            "text-[9px] tabular-nums leading-none",
                            isSelected ? "font-medium text-foreground" : "text-muted-foreground",
                          )}>
                            {formatShortTime(run.started_at ?? run.created_at)}
                          </span>
                          {/* Duration micro-label */}
                          {duration != null && (
                            <span className="text-[8px] text-muted-foreground/60 leading-none">
                              {formatDuration(duration)}
                            </span>
                          )}
                          {/* Connector line */}
                          <div className="absolute -bottom-0.5 left-1/2 h-1 w-px -translate-x-1/2 bg-border/30" />
                        </button>
                      </TooltipTrigger>
                      <TooltipContent side="right" className="max-w-[220px] space-y-1 text-xs">
                        <div className="flex items-center gap-1.5">
                          <span className={cn("h-2 w-2 rounded-full", statusDot(run.phase))} />
                          <span className="font-semibold capitalize">{run.phase}</span>
                          {duration != null && (
                            <span className="text-muted-foreground">{formatDuration(duration)}</span>
                          )}
                        </div>
                        <div className="text-muted-foreground">
                          {run.completed_steps ?? 0}/{run.total_steps ?? "?"} steps
                          {run.triggered_by && <> &middot; {run.triggered_by}</>}
                        </div>
                        {run.run_id && (
                          <div className="font-mono text-[10px] text-muted-foreground/70 truncate">
                            {run.run_id}
                          </div>
                        )}
                      </TooltipContent>
                    </Tooltip>
                  );
                })}
              </div>
            ))}

            {runs.length > 0 && (
              <div className="mt-2 flex flex-col items-center text-muted-foreground/40">
                <ChevronDown className="h-3 w-3" />
              </div>
            )}
          </div>
        </ScrollArea>
      </div>
    </TooltipProvider>
  );
}
