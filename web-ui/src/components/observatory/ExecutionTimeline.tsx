import { useState, useMemo } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import type { TraceEvent, TraceEventType } from "@/types";

export const EVENT_COLORS: Record<TraceEventType, string> = {
  EXECUTION_STARTED: "bg-emerald-500",
  EXECUTION_COMPLETED: "bg-emerald-500",
  EXECUTION_FAILED: "bg-red-500",
  STEP_STARTED: "bg-blue-500",
  STEP_COMPLETED: "bg-blue-500",
  STEP_FAILED: "bg-red-500",
  LLM_CALL_COMPLETED: "bg-violet-500",
  TOOL_CALL_COMPLETED: "bg-cyan-500",
  DECISION: "bg-amber-500",
  ERROR: "bg-red-500",
  WARNING: "bg-orange-500",
  PROGRESS: "bg-sky-500",
  ARTIFACT_CREATED: "bg-pink-500",
  CUSTOM: "bg-gray-500",
};

export const EVENT_LABEL_COLORS: Record<TraceEventType, string> = {
  EXECUTION_STARTED: "text-emerald-500",
  EXECUTION_COMPLETED: "text-emerald-500",
  EXECUTION_FAILED: "text-red-500",
  STEP_STARTED: "text-blue-500",
  STEP_COMPLETED: "text-blue-500",
  STEP_FAILED: "text-red-500",
  LLM_CALL_COMPLETED: "text-violet-500",
  TOOL_CALL_COMPLETED: "text-cyan-500",
  DECISION: "text-amber-500",
  ERROR: "text-red-500",
  WARNING: "text-orange-500",
  PROGRESS: "text-sky-500",
  ARTIFACT_CREATED: "text-pink-500",
  CUSTOM: "text-gray-500",
};

interface ExecutionTimelineProps {
  events: TraceEvent[];
  activeEventId?: string | null;
  onEventClick?: (event: TraceEvent) => void;
}

function formatTime(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString(undefined, { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return ts;
  }
}

function groupEventsByStep(events: TraceEvent[]): { stepId: string | null; events: TraceEvent[] }[] {
  const groups: { stepId: string | null; events: TraceEvent[] }[] = [];
  let current: TraceEvent[] = [];
  let currentStep: string | null = null;
  for (const ev of events) {
    if (ev.step_id !== currentStep) {
      if (current.length > 0) groups.push({ stepId: currentStep, events: current });
      current = [ev];
      currentStep = ev.step_id ?? null;
    } else {
      current.push(ev);
    }
  }
  if (current.length > 0) groups.push({ stepId: currentStep, events: current });
  return groups;
}

function EventRow({
  event,
  isLast,
  isActive,
  onClick,
}: {
  event: TraceEvent;
  isLast: boolean;
  isActive: boolean;
  onClick?: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const colorClass = EVENT_COLORS[event.event_type] ?? "bg-gray-500";
  const labelColorClass = EVENT_LABEL_COLORS[event.event_type] ?? "text-gray-500";
  const hasPayload = Object.keys(event.payload).length > 0;

  return (
    <div className="relative flex gap-3">
      {/* Connector line */}
      {!isLast && <div className="absolute left-[7px] top-5 bottom-0 w-px bg-border/40" />}

      {/* Dot */}
      <div className="relative z-10 mt-0.5 flex shrink-0 items-center justify-center">
        <span
          className={cn(
            "h-3.5 w-3.5 rounded-full border-2 border-background shadow-sm",
            colorClass,
            isActive && "ring-2 ring-primary ring-offset-1 ring-offset-background",
          )}
          aria-hidden="true"
        />
      </div>

      {/* Content */}
      <div className="min-w-0 flex-1 pb-3">
        <button
          type="button"
          onClick={() => {
            if (hasPayload) setExpanded((e) => !e);
            onClick?.();
          }}
          className="flex w-full items-center gap-2 text-left"
          aria-label={`${event.event_type} at ${formatTime(event.timestamp)}`}
        >
          <span className="text-[11px] tabular-nums text-muted-foreground">{formatTime(event.timestamp)}</span>
          <span className={cn("text-xs font-semibold uppercase tracking-wide", labelColorClass)}>{event.event_type}</span>
          {hasPayload && (
            <span className="ml-auto shrink-0 text-muted-foreground">
              {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            </span>
          )}
        </button>

        {expanded && hasPayload && (
          <div className="mt-1.5 rounded-lg border border-border/40 bg-muted/20">
            <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words p-2.5 text-[11px] leading-relaxed text-muted-foreground">
              {JSON.stringify(event.payload, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}

export function ExecutionTimeline({ events, activeEventId, onEventClick }: ExecutionTimelineProps) {
  const sorted = useMemo(() => {
    return [...events].sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());
  }, [events]);

  const groups = useMemo(() => groupEventsByStep(sorted), [sorted]);

  if (events.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-[1.75rem] border border-dashed border-border/70 bg-card/30 py-12">
        <p className="text-sm text-muted-foreground">No events recorded for this execution.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {groups.map((group, gIdx) => (
        <div key={group.stepId ?? `group-${gIdx}`}>
          {group.stepId && (
            <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground/70">
              Step: {group.stepId}
            </div>
          )}
          <div className="rounded-xl border border-border/50 bg-card/55 p-3">
            {group.events.map((ev, idx) => (
              <EventRow
                key={ev.id}
                event={ev}
                isLast={idx === group.events.length - 1 && gIdx === groups.length - 1}
                isActive={activeEventId === ev.id}
                onClick={() => onEventClick?.(ev)}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
