import { useState, useMemo } from "react";
import { ChevronDown, ChevronRight, Filter } from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { TraceEvent, TraceEventType } from "@/types";

// ─── Color Maps ───────────────────────────────────────────────────────────────

export const EVENT_COLORS: Record<TraceEventType, string> = {
  EXECUTION_STARTED: "bg-emerald-500",
  EXECUTION_COMPLETED: "bg-emerald-500",
  EXECUTION_FAILED: "bg-red-500",
  EXECUTION_CANCELLED: "bg-amber-500",
  STEP_STARTED: "bg-blue-500",
  STEP_COMPLETED: "bg-blue-500",
  STEP_FAILED: "bg-red-500",
  STEP_SKIPPED: "bg-slate-400",
  LLM_CALL_STARTED: "bg-violet-500",
  LLM_CALL_COMPLETED: "bg-violet-500",
  LLM_CALL_FAILED: "bg-red-500",
  LLM_STREAM_CHUNK: "bg-slate-400",
  TOOL_CALL_STARTED: "bg-cyan-500",
  TOOL_CALL_COMPLETED: "bg-cyan-500",
  TOOL_CALL_FAILED: "bg-red-500",
  DECISION: "bg-amber-500",
  BRANCH_TAKEN: "bg-amber-500",
  STATE_SNAPSHOT: "bg-slate-400",
  VARIABLE_SET: "bg-slate-400",
  ERROR: "bg-red-500",
  WARNING: "bg-orange-500",
  PROGRESS: "bg-sky-500",
  TODO_CREATED: "bg-primary",
  TODO_COMPLETED: "bg-emerald-500",
  ARTIFACT_CREATED: "bg-pink-500",
  CUSTOM: "bg-gray-500",
};

export const EVENT_LABEL_COLORS: Record<TraceEventType, string> = {
  EXECUTION_STARTED: "text-emerald-500",
  EXECUTION_COMPLETED: "text-emerald-500",
  EXECUTION_FAILED: "text-red-500",
  EXECUTION_CANCELLED: "text-amber-500",
  STEP_STARTED: "text-blue-500",
  STEP_COMPLETED: "text-blue-500",
  STEP_FAILED: "text-red-500",
  STEP_SKIPPED: "text-slate-400",
  LLM_CALL_STARTED: "text-violet-500",
  LLM_CALL_COMPLETED: "text-violet-500",
  LLM_CALL_FAILED: "text-red-500",
  LLM_STREAM_CHUNK: "text-slate-400",
  TOOL_CALL_STARTED: "text-cyan-500",
  TOOL_CALL_COMPLETED: "text-cyan-500",
  TOOL_CALL_FAILED: "text-red-500",
  DECISION: "text-amber-500",
  BRANCH_TAKEN: "text-amber-500",
  STATE_SNAPSHOT: "text-slate-400",
  VARIABLE_SET: "text-slate-400",
  ERROR: "text-red-500",
  WARNING: "text-orange-500",
  PROGRESS: "text-sky-500",
  TODO_CREATED: "text-primary",
  TODO_COMPLETED: "text-emerald-500",
  ARTIFACT_CREATED: "text-pink-500",
  CUSTOM: "text-gray-500",
};

const SWIMLANE_COLORS: Record<string, string> = {
  execution: "bg-emerald-500/20 border-emerald-500/30",
  step: "bg-blue-500/20 border-blue-500/30",
  llm: "bg-violet-500/20 border-violet-500/30",
  tool: "bg-cyan-500/20 border-cyan-500/30",
  error: "bg-red-500/20 border-red-500/30",
  other: "bg-muted/30 border-border/40",
};

// ─── Types ────────────────────────────────────────────────────────────────────

type SwimCategory = "execution" | "step" | "llm" | "tool" | "error" | "other";

interface ExecutionTimelineProps {
  events: TraceEvent[];
  activeEventId?: string | null;
  onEventClick?: (event: TraceEvent) => void;
  /** When true, use compact vertical list instead of swimlane (for small event sets) */
  compact?: boolean;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatTime(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString(undefined, { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return ts;
  }
}

function formatRelativeMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  return `${Math.floor(s / 60)}m${Math.round(s % 60)}s`;
}

function categorizeEvent(type: TraceEventType): SwimCategory {
  if (type.startsWith("EXECUTION_")) return "execution";
  if (type.startsWith("STEP_")) return "step";
  if (type.startsWith("LLM_")) return "llm";
  if (type.startsWith("TOOL_")) return "tool";
  if (type === "ERROR" || type === "WARNING") return "error";
  return "other";
}

// ─── Swimlane Timeline ────────────────────────────────────────────────────────

interface SwimlaneData {
  category: SwimCategory;
  label: string;
  events: TraceEvent[];
  startMs: number;
  endMs: number;
}

function buildSwimlanes(events: TraceEvent[], _totalStartMs: number, _totalEndMs: number): SwimlaneData[] {
  // Group by step_id, then within each step by category
  const stepGroups = new Map<string, TraceEvent[]>();
  const noStepEvents: TraceEvent[] = [];

  for (const ev of events) {
    if (ev.step_id) {
      const group = stepGroups.get(ev.step_id);
      if (group) group.push(ev);
      else stepGroups.set(ev.step_id, [ev]);
    } else {
      noStepEvents.push(ev);
    }
  }

  const lanes: SwimlaneData[] = [];

  // Execution-level events lane
  const execEvents = noStepEvents.filter((e) => categorizeEvent(e.event_type) === "execution");
  if (execEvents.length > 0) {
    lanes.push({
      category: "execution",
      label: "Execution",
      events: execEvents,
      startMs: Math.min(...execEvents.map((e) => new Date(e.timestamp).getTime())),
      endMs: Math.max(...execEvents.map((e) => new Date(e.timestamp).getTime())),
    });
  }

  // Per-step lanes
  for (const [stepId, stepEvents] of stepGroups) {
    const sorted = stepEvents.sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());
    const startMs = new Date(sorted[0].timestamp).getTime();
    const endMs = new Date(sorted[sorted.length - 1].timestamp).getTime();
    const hasErrors = sorted.some((e) => e.event_type.includes("FAILED") || e.event_type === "ERROR");

    lanes.push({
      category: hasErrors ? "error" : "step",
      label: stepId.length > 20 ? `${stepId.slice(0, 18)}...` : stepId,
      events: sorted,
      startMs,
      endMs,
    });
  }

  // Other events not tied to steps
  const otherEvents = noStepEvents.filter((e) => categorizeEvent(e.event_type) !== "execution");
  if (otherEvents.length > 0) {
    lanes.push({
      category: "other",
      label: "Other",
      events: otherEvents,
      startMs: Math.min(...otherEvents.map((e) => new Date(e.timestamp).getTime())),
      endMs: Math.max(...otherEvents.map((e) => new Date(e.timestamp).getTime())),
    });
  }

  return lanes;
}

// ─── Main Component ───────────────────────────────────────────────────────────

export function ExecutionTimeline({ events, activeEventId, onEventClick, compact }: ExecutionTimelineProps) {
  const [expandedEventId, setExpandedEventId] = useState<string | null>(null);
  const [filterTypes, setFilterTypes] = useState<Set<SwimCategory>>(new Set(["execution", "step", "llm", "tool", "error", "other"]));

  const sorted = useMemo(
    () => [...events].sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()),
    [events],
  );

  const timeRange = useMemo(() => {
    if (sorted.length === 0) return { startMs: 0, endMs: 0, totalMs: 0 };
    const startMs = new Date(sorted[0].timestamp).getTime();
    const endMs = new Date(sorted[sorted.length - 1].timestamp).getTime();
    return { startMs, endMs, totalMs: Math.max(endMs - startMs, 1) };
  }, [sorted]);

  const swimlanes = useMemo(
    () => buildSwimlanes(sorted, timeRange.startMs, timeRange.endMs),
    [sorted, timeRange.startMs, timeRange.endMs],
  );

  const filteredLanes = useMemo(
    () => swimlanes.filter((lane) => filterTypes.has(lane.category)),
    [swimlanes, filterTypes],
  );

  const eventTypeCounts = useMemo(() => {
    const counts: Record<SwimCategory, number> = { execution: 0, step: 0, llm: 0, tool: 0, error: 0, other: 0 };
    for (const ev of sorted) {
      counts[categorizeEvent(ev.event_type)]++;
    }
    return counts;
  }, [sorted]);

  if (events.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border/50 py-8">
        <p className="text-xs text-muted-foreground">No events recorded for this execution.</p>
      </div>
    );
  }

  // Compact mode: simple vertical list (used in Steps tab for per-step events)
  if (compact || events.length <= 8) {
    return (
      <div className="space-y-0.5">
        {sorted.map((ev, idx) => {
          const colorClass = EVENT_COLORS[ev.event_type] ?? "bg-gray-500";
          const labelColor = EVENT_LABEL_COLORS[ev.event_type] ?? "text-gray-500";
          const isActive = activeEventId === ev.id;
          const isExpanded = expandedEventId === ev.id;
          const hasPayload = Object.keys(ev.payload).length > 0;

          return (
            <div key={ev.id} className="relative flex gap-2.5">
              {idx < sorted.length - 1 && (
                <div className="absolute left-[5px] top-4 bottom-0 w-px bg-border/30" />
              )}
              <span className={cn("relative z-10 mt-1 h-2.5 w-2.5 shrink-0 rounded-full", colorClass, isActive && "ring-2 ring-primary ring-offset-1 ring-offset-background")} />
              <div className="min-w-0 flex-1 pb-2">
                <button
                  type="button"
                  onClick={() => {
                    if (hasPayload) setExpandedEventId(isExpanded ? null : ev.id);
                    onEventClick?.(ev);
                  }}
                  className="flex w-full items-center gap-2 text-left"
                >
                  <span className="text-[10px] tabular-nums text-muted-foreground">{formatTime(ev.timestamp)}</span>
                  <span className={cn("text-[10px] font-semibold uppercase", labelColor)}>{ev.event_type.replace(/_/g, " ")}</span>
                  {hasPayload && (
                    <span className="ml-auto text-muted-foreground/60">
                      {isExpanded ? <ChevronDown className="h-2.5 w-2.5" /> : <ChevronRight className="h-2.5 w-2.5" />}
                    </span>
                  )}
                </button>
                {isExpanded && hasPayload && (
                  <pre className="mt-1 max-h-32 overflow-auto rounded-md border border-border/30 bg-muted/20 p-2 text-[10px] text-muted-foreground">
                    {JSON.stringify(ev.payload, null, 2)}
                  </pre>
                )}
              </div>
            </div>
          );
        })}
      </div>
    );
  }

  // Full swimlane mode
  return (
    <TooltipProvider delayDuration={100}>
      <div className="space-y-3">
        {/* Filter bar */}
        <div className="flex items-center gap-1.5">
          <Filter className="h-3 w-3 text-muted-foreground" />
          {(["execution", "step", "llm", "tool", "error", "other"] as SwimCategory[]).map((cat) => {
            const active = filterTypes.has(cat);
            const count = eventTypeCounts[cat];
            if (count === 0) return null;
            return (
              <button
                key={cat}
                type="button"
                onClick={() => {
                  setFilterTypes((prev) => {
                    const next = new Set(prev);
                    if (next.has(cat)) next.delete(cat);
                    else next.add(cat);
                    return next;
                  });
                }}
                className={cn(
                  "rounded-md border px-2 py-0.5 text-[10px] font-medium transition-colors",
                  active
                    ? SWIMLANE_COLORS[cat]
                    : "border-transparent bg-muted/20 text-muted-foreground/50",
                )}
              >
                {cat} ({count})
              </button>
            );
          })}
          <span className="ml-auto text-[10px] text-muted-foreground">
            {timeRange.totalMs > 0 ? formatRelativeMs(timeRange.totalMs) : ""} total
          </span>
        </div>

        {/* Swimlane chart */}
        <div className="space-y-1">
          {filteredLanes.map((lane, laneIdx) => (
            <div key={`${lane.category}-${laneIdx}`} className="flex items-center gap-2">
              {/* Lane label */}
              <span className="w-20 shrink-0 truncate text-[10px] font-medium text-muted-foreground text-right">
                {lane.label}
              </span>

              {/* Lane bar */}
              <div className="relative flex-1 h-6 rounded-md bg-muted/10 border border-border/20">
                {/* Duration bar */}
                {timeRange.totalMs > 0 && (
                  <div
                    className={cn("absolute top-0.5 bottom-0.5 rounded-sm border", SWIMLANE_COLORS[lane.category])}
                    style={{
                      left: `${((lane.startMs - timeRange.startMs) / timeRange.totalMs) * 100}%`,
                      width: `${Math.max(((lane.endMs - lane.startMs) / timeRange.totalMs) * 100, 1)}%`,
                    }}
                  />
                )}

                {/* Event markers */}
                {lane.events.map((ev) => {
                  const posPercent = timeRange.totalMs > 0
                    ? ((new Date(ev.timestamp).getTime() - timeRange.startMs) / timeRange.totalMs) * 100
                    : 50;
                  const isActive = activeEventId === ev.id;
                  const dotColor = EVENT_COLORS[ev.event_type] ?? "bg-gray-500";

                  return (
                    <Tooltip key={ev.id}>
                      <TooltipTrigger asChild>
                        <button
                          type="button"
                          onClick={() => onEventClick?.(ev)}
                          className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2"
                          style={{ left: `${posPercent}%` }}
                        >
                          <span className={cn(
                            "block h-2 w-2 rounded-full transition-transform",
                            dotColor,
                            isActive && "scale-150 ring-2 ring-primary ring-offset-1 ring-offset-background",
                          )} />
                        </button>
                      </TooltipTrigger>
                      <TooltipContent side="top" className="max-w-[240px] space-y-0.5 text-[11px]">
                        <div className="font-semibold">{ev.event_type.replace(/_/g, " ")}</div>
                        <div className="text-muted-foreground">{formatTime(ev.timestamp)}</div>
                        {ev.step_id && <div className="font-mono text-[10px] text-muted-foreground/70">step: {ev.step_id}</div>}
                        {Object.keys(ev.payload).length > 0 && (
                          <div className="text-[10px] text-muted-foreground/60">Click to inspect payload</div>
                        )}
                      </TooltipContent>
                    </Tooltip>
                  );
                })}
              </div>

              {/* Lane event count */}
              <span className="w-6 shrink-0 text-right text-[9px] tabular-nums text-muted-foreground/60">
                {lane.events.length}
              </span>
            </div>
          ))}
        </div>

        {/* Time axis */}
        {timeRange.totalMs > 0 && (
          <div className="flex items-center gap-2 pl-[5.5rem] pr-8">
            <div className="relative flex-1 h-4">
              <div className="absolute inset-x-0 top-1/2 h-px bg-border/30" />
              <span className="absolute left-0 top-0 text-[9px] text-muted-foreground/50">0</span>
              <span className="absolute left-1/4 top-0 -translate-x-1/2 text-[9px] text-muted-foreground/50">
                {formatRelativeMs(timeRange.totalMs * 0.25)}
              </span>
              <span className="absolute left-1/2 top-0 -translate-x-1/2 text-[9px] text-muted-foreground/50">
                {formatRelativeMs(timeRange.totalMs * 0.5)}
              </span>
              <span className="absolute left-3/4 top-0 -translate-x-1/2 text-[9px] text-muted-foreground/50">
                {formatRelativeMs(timeRange.totalMs * 0.75)}
              </span>
              <span className="absolute right-0 top-0 text-[9px] text-muted-foreground/50">
                {formatRelativeMs(timeRange.totalMs)}
              </span>
            </div>
          </div>
        )}

        {/* Selected event detail */}
        {activeEventId && (() => {
          const activeEvent = sorted.find((e) => e.id === activeEventId);
          if (!activeEvent || Object.keys(activeEvent.payload).length === 0) return null;
          return (
            <div className="rounded-md border border-border/40 bg-muted/10 p-2.5">
              <div className="mb-1.5 flex items-center gap-2">
                <span className={cn("h-2 w-2 rounded-full", EVENT_COLORS[activeEvent.event_type] ?? "bg-gray-500")} />
                <span className="text-[11px] font-semibold uppercase tracking-wide text-foreground">
                  {activeEvent.event_type.replace(/_/g, " ")}
                </span>
                <span className="text-[10px] text-muted-foreground">{formatTime(activeEvent.timestamp)}</span>
              </div>
              <pre className="max-h-40 overflow-auto rounded-md bg-slate-950 p-2 text-[10px] leading-relaxed text-slate-100">
                {JSON.stringify(activeEvent.payload, null, 2)}
              </pre>
            </div>
          );
        })()}
      </div>
    </TooltipProvider>
  );
}
