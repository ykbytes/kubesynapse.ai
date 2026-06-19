import { cn } from "@/lib/utils";
import type { ToolCallRecord } from "@/types";
import {
  formatDuration,
  getToolCallSummary,
  getToolIcon,
  getToolIconColor,
  tcLatency,
} from "./observatory-utils";

interface ToolCallRowProps {
  call: ToolCallRecord;
  relativeTime?: string;
  isSelected?: boolean;
  onClick?: (call: ToolCallRecord) => void;
}

export function ToolCallRow({ call, relativeTime, isSelected, onClick }: ToolCallRowProps) {
  const Icon = getToolIcon(call.tool_name);
  const iconColor = getToolIconColor(call.tool_name);
  const summary = getToolCallSummary(call);
  const isFailed =
    call.status.toLowerCase() === "failed" || call.status.toLowerCase() === "error";
  const latency = tcLatency(call);

  return (
    <button
      type="button"
      onClick={() => onClick?.(call)}
      className={cn(
        "group flex w-full items-center gap-3 rounded-lg border px-4 py-2.5 text-left transition-all",
        "border-border/40 bg-muted/15 hover:border-border/60 hover:bg-muted/30",
        isSelected && "border-primary/30 bg-primary/5 ring-1 ring-primary/15",
      )}
    >
      <Icon className={cn("size-4 shrink-0", iconColor)} />
      <span className="shrink-0 text-sm font-medium text-foreground">
        {call.tool_name}
      </span>
      {summary && (
        <span
          className="min-w-0 flex-1 truncate text-xs text-muted-foreground/60 font-mono"
          title={summary}
        >
          {summary}
        </span>
      )}
      <div className="flex shrink-0 items-center gap-3 text-xs tabular-nums text-muted-foreground">
        {latency > 0 && <span>{formatDuration(latency)}</span>}
        <span className={cn(isFailed ? "text-red-500/80" : "text-emerald-500/70")}>
          {call.status}
        </span>
        {relativeTime && <span className="text-muted-foreground/40">{relativeTime}</span>}
      </div>
    </button>
  );
}
