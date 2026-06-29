import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Bot,
  BrainCircuit,
  CheckCircle2,
  CircleDot,
  Clock3,
  FileJson,
  Filter,
  Wrench,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { OptimizerTrace, OptimizerTraceEvent } from "@/types";

type TraceFilter = "all" | "reasoning" | "tools" | "decisions" | "errors";

interface OptimizerTracePanelProps {
  trace?: OptimizerTrace | null;
  audit?: Record<string, unknown>;
  visibleResponse?: string | null;
  candidateName?: string | null;
}

const FILTERS: Array<{ value: TraceFilter; label: string }> = [
  { value: "all", label: "All activity" },
  { value: "reasoning", label: "Reasoning summaries" },
  { value: "tools", label: "Tools" },
  { value: "decisions", label: "Decisions" },
  { value: "errors", label: "Errors" },
];

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function strings(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(String).filter(Boolean);
  if (typeof value === "string" && value.trim()) return [value.trim()];
  return [];
}

function display(value: unknown, fallback = "--"): string {
  if (typeof value === "string" && value.trim()) return value;
  if (typeof value === "number" && Number.isFinite(value)) return value.toLocaleString();
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (Array.isArray(value) && value.length > 0) return value.map(String).join(", ");
  return fallback;
}

function formatDuration(durationMs: number | null | undefined): string {
  if (!durationMs || durationMs < 1) return "--";
  if (durationMs < 1000) return `${Math.round(durationMs)}ms`;
  if (durationMs < 60_000) return `${(durationMs / 1000).toFixed(durationMs < 10_000 ? 1 : 0)}s`;
  const minutes = Math.floor(durationMs / 60_000);
  const seconds = Math.round((durationMs % 60_000) / 1000);
  return `${minutes}m ${seconds}s`;
}

function formatTime(value: string): string {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function eventIcon(kind: OptimizerTraceEvent["kind"]) {
  if (kind === "reasoning") return BrainCircuit;
  if (kind === "tool") return Wrench;
  if (kind === "error" || kind === "warning") return AlertTriangle;
  if (kind === "completion") return CheckCircle2;
  if (kind === "response") return FileJson;
  return CircleDot;
}

function eventTone(kind: OptimizerTraceEvent["kind"]): string {
  if (kind === "reasoning") return "border-violet-500/35 bg-violet-500/8 text-violet-700 dark:text-violet-300";
  if (kind === "tool") return "border-sky-500/35 bg-sky-500/8 text-sky-700 dark:text-sky-300";
  if (kind === "error") return "border-red-500/35 bg-red-500/8 text-red-700 dark:text-red-300";
  if (kind === "warning") return "border-amber-500/35 bg-amber-500/8 text-amber-700 dark:text-amber-300";
  if (kind === "completion") return "border-emerald-500/35 bg-emerald-500/8 text-emerald-700 dark:text-emerald-300";
  return "border-border/60 bg-muted/25 text-foreground";
}

function matchesFilter(event: OptimizerTraceEvent, filter: TraceFilter): boolean {
  if (filter === "all") return true;
  if (filter === "reasoning") return event.kind === "reasoning";
  if (filter === "tools") return event.kind === "tool";
  if (filter === "errors") return event.kind === "error" || event.kind === "warning";
  return event.kind === "status" || event.kind === "response" || event.kind === "completion";
}

function legacyTrace(
  audit: Record<string, unknown>,
  visibleResponse: string,
  candidateName: string,
): OptimizerTrace | null {
  if (Object.keys(audit).length === 0 && !visibleResponse) return null;
  const topology = record(audit.topology_decision);
  const decision = record(audit.decision_record);
  const resourcesRecord = record(audit.resources_used);
  const skills = strings(audit.skills_used).length > 0
    ? strings(audit.skills_used)
    : strings(audit.skills_requested);
  const resources = Object.entries(resourcesRecord)
    .filter(([, value]) => value !== null && value !== undefined && value !== "")
    .map(([key, value]) => `${key.replace(/_/g, " ")}: ${display(value)}`);
  const events: OptimizerTraceEvent[] = [];
  if (Object.keys(topology).length > 0) {
    events.push({
      id: "legacy-topology",
      sequence: 1,
      timestamp: "",
      kind: "reasoning",
      title: "Topology decision",
      summary: display(topology.reason, display(topology.decision, "Topology decision recorded.")),
      payload: topology,
    });
  }
  if (Object.keys(decision).length > 0) {
    events.push({
      id: "legacy-decision",
      sequence: events.length + 1,
      timestamp: "",
      kind: "completion",
      title: "Candidate strategy",
      summary: display(decision.candidate_strategy, "Structured optimizer decision recorded."),
      payload: decision,
    });
  }
  if (visibleResponse) {
    events.push({
      id: "legacy-response",
      sequence: events.length + 1,
      timestamp: "",
      kind: "response",
      title: "Visible optimizer response",
      summary: "The final optimizer response was persisted for this candidate.",
    });
  }
  return {
    agent_name: display(resourcesRecord.optimizer_agent, "workflow-optimizer"),
    model: null,
    status: display(record(audit.candidate_generation).status, "legacy audit"),
    fallback: false,
    final_response: visibleResponse,
    events,
    tool_calls: [],
    artifacts: [],
    skills,
    resources,
    summary: {
      event_count: events.length,
      tool_count: 0,
      reasoning_event_count: events.filter((event) => event.kind === "reasoning").length,
      error_count: 0,
    },
    request_id: candidateName ? `legacy-${candidateName}` : "legacy-candidate-audit",
  };
}

export function OptimizerTracePanel({
  trace,
  audit = {},
  visibleResponse = "",
  candidateName = "",
}: OptimizerTracePanelProps) {
  const effectiveTrace = useMemo(
    () => trace ?? legacyTrace(audit, visibleResponse ?? "", candidateName ?? ""),
    [audit, candidateName, trace, visibleResponse],
  );
  const [filter, setFilter] = useState<TraceFilter>("all");
  const filteredEvents = useMemo(
    () => (effectiveTrace?.events ?? []).filter((event) => matchesFilter(event, filter)),
    [effectiveTrace?.events, filter],
  );
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const selectedEvent =
    filteredEvents.find((event) => event.id === selectedEventId) ??
    filteredEvents[0] ??
    null;

  useEffect(() => {
    if (!filteredEvents.some((event) => event.id === selectedEventId)) {
      setSelectedEventId(filteredEvents[0]?.id ?? null);
    }
  }, [filteredEvents, selectedEventId]);

  if (!effectiveTrace) {
    return (
      <section className="rounded-lg border border-dashed border-border/60 bg-card/40 p-8 text-center">
        <BrainCircuit className="mx-auto h-6 w-6 text-muted-foreground" />
        <div className="mt-2 text-sm font-semibold text-foreground">No optimizer trace is attached</div>
        <p className="mx-auto mt-1 max-w-lg text-[11px] leading-5 text-muted-foreground">
          Run an ROI study or select a newer candidate. Legacy candidates remain usable, but may only include their final response.
        </p>
      </section>
    );
  }

  const skills = effectiveTrace.skills ?? [];
  const resources = effectiveTrace.resources ?? [];
  const finalResponse = effectiveTrace.final_response || visibleResponse || "";
  const statusTone = effectiveTrace.status === "failed"
    ? "border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300"
    : effectiveTrace.fallback
      ? "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300"
      : "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300";

  return (
    <section className="overflow-hidden rounded-lg border border-border/60 bg-card/55">
      <header className="border-b border-border/50 px-3 py-2.5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
              <BrainCircuit className="h-4 w-4 text-primary" />
              Optimizer trace
              <Badge variant="outline" className={cn("h-5 text-[9px]", statusTone)}>
                {effectiveTrace.fallback ? "fallback" : display(effectiveTrace.status, "recorded")}
              </Badge>
            </div>
            <p className="mt-0.5 text-[10px] leading-4 text-muted-foreground">
              Observable execution only: runtime-emitted reasoning summaries, tools, decisions, and output. Hidden chain-of-thought is not exposed.
            </p>
          </div>
          <div className="text-right text-[10px] text-muted-foreground">
            <div className="font-medium text-foreground">{display(effectiveTrace.agent_name, "optimizer")}</div>
            <div>{display(effectiveTrace.thread_id ?? effectiveTrace.request_id, "persisted candidate trace")}</div>
          </div>
        </div>

        <div className="mt-2 grid grid-cols-2 gap-px overflow-hidden rounded-md border border-border/45 bg-border/45 sm:grid-cols-3 xl:grid-cols-6">
          {[
            ["Duration", formatDuration(effectiveTrace.duration_ms)],
            ["Model", display(effectiveTrace.model, "--")],
            ["Events", effectiveTrace.summary.event_count],
            ["Tools", effectiveTrace.summary.tool_count],
            ["Reasoning", effectiveTrace.summary.reasoning_event_count],
            ["Skills", skills.length],
          ].map(([label, value]) => (
            <div key={String(label)} className="min-w-0 bg-background/85 px-2 py-1.5">
              <div className="text-[9px] uppercase tracking-wide text-muted-foreground">{label}</div>
              <div className="mt-0.5 truncate text-[11px] font-semibold text-foreground">{value}</div>
            </div>
          ))}
        </div>
      </header>

      <div className="border-b border-border/45 px-3 py-2">
        <div className="flex items-center gap-1 overflow-x-auto">
          <Filter className="mr-1 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          {FILTERS.map((item) => {
            const count = (effectiveTrace.events ?? []).filter((event) => matchesFilter(event, item.value)).length;
            return (
              <Button
                key={item.value}
                type="button"
                size="sm"
                variant={filter === item.value ? "secondary" : "ghost"}
                className="h-7 shrink-0 gap-1 px-2 text-[10px]"
                onClick={() => setFilter(item.value)}
              >
                {item.label}
                <span className="text-muted-foreground">{count}</span>
              </Button>
            );
          })}
        </div>
      </div>

      <div className="grid min-h-[30rem] lg:grid-cols-[minmax(18rem,0.72fr)_minmax(28rem,1.28fr)]">
        <div className="border-b border-border/50 lg:border-b-0 lg:border-r">
          <div className="flex items-center justify-between border-b border-border/40 px-3 py-2">
            <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Trace chronology</div>
            <div className="text-[10px] text-muted-foreground">{filteredEvents.length} events</div>
          </div>
          <div className="max-h-[36rem] overflow-y-auto p-2">
            {filteredEvents.length > 0 ? (
              <div className="space-y-1">
                {filteredEvents.map((event) => {
                  const Icon = eventIcon(event.kind);
                  const selected = selectedEvent?.id === event.id;
                  return (
                    <button
                      key={event.id}
                      type="button"
                      className={cn(
                        "grid w-full grid-cols-[1.5rem_minmax(0,1fr)_auto] gap-2 rounded-md border px-2 py-2 text-left transition-colors",
                        selected ? "border-primary/45 bg-primary/8" : "border-transparent hover:border-border/60 hover:bg-muted/25",
                      )}
                      onClick={() => setSelectedEventId(event.id)}
                    >
                      <span className={cn("mt-0.5 flex h-6 w-6 items-center justify-center rounded border", eventTone(event.kind))}>
                        <Icon className="h-3.5 w-3.5" />
                      </span>
                      <span className="min-w-0">
                        <span className="flex items-center gap-1.5">
                          <span className="truncate text-[11px] font-semibold text-foreground">{event.title}</span>
                          <span className="text-[9px] uppercase text-muted-foreground">{event.kind}</span>
                        </span>
                        <span className="mt-0.5 block line-clamp-2 text-[10px] leading-4 text-muted-foreground">{event.summary || "No summary emitted."}</span>
                      </span>
                      <span className="pt-0.5 text-[9px] tabular-nums text-muted-foreground">{formatTime(event.timestamp)}</span>
                    </button>
                  );
                })}
              </div>
            ) : (
              <div className="p-8 text-center text-[11px] text-muted-foreground">No events match this filter.</div>
            )}
          </div>
        </div>

        <div>
          <div className="flex items-center justify-between border-b border-border/40 px-3 py-2">
            <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Event inspector</div>
            {selectedEvent && <Badge variant="outline" className="h-5 text-[9px]">{selectedEvent.kind}</Badge>}
          </div>
          <div className="max-h-[36rem] overflow-y-auto p-3">
            {selectedEvent ? (
              <div className="space-y-3">
                <div>
                  <h3 className="text-base font-semibold text-foreground">{selectedEvent.title}</h3>
                  <p className="mt-1 text-xs leading-5 text-muted-foreground">{selectedEvent.summary || "No summary was emitted for this event."}</p>
                </div>
                <div className="grid gap-2 sm:grid-cols-3">
                  <div className="rounded-md border border-border/40 bg-background/70 p-2">
                    <div className="text-[9px] uppercase tracking-wide text-muted-foreground">Sequence</div>
                    <div className="mt-1 text-xs font-semibold text-foreground">#{selectedEvent.sequence}</div>
                  </div>
                  <div className="rounded-md border border-border/40 bg-background/70 p-2">
                    <div className="text-[9px] uppercase tracking-wide text-muted-foreground">Time</div>
                    <div className="mt-1 text-xs font-semibold text-foreground">{formatTime(selectedEvent.timestamp)}</div>
                  </div>
                  <div className="rounded-md border border-border/40 bg-background/70 p-2">
                    <div className="text-[9px] uppercase tracking-wide text-muted-foreground">Source</div>
                    <div className="mt-1 truncate text-xs font-semibold text-foreground">{display(effectiveTrace.agent_name, "optimizer")}</div>
                  </div>
                </div>
                {selectedEvent.kind === "reasoning" && (
                  <div className="rounded-md border border-violet-500/25 bg-violet-500/8 p-2 text-[10px] leading-4 text-violet-800 dark:text-violet-200">
                    This is an observable runtime reasoning summary, not hidden model chain-of-thought.
                  </div>
                )}
                {selectedEvent.payload !== undefined && (
                  <details className="rounded-md border border-border/45 bg-background/70 p-2" open>
                    <summary className="cursor-pointer list-none text-[11px] font-semibold text-foreground">Event payload</summary>
                    <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded bg-zinc-950 p-2 font-mono text-[10px] leading-4 text-zinc-100">
                      {JSON.stringify(selectedEvent.payload, null, 2)}
                    </pre>
                  </details>
                )}
              </div>
            ) : (
              <div className="flex min-h-64 items-center justify-center text-center text-[11px] text-muted-foreground">
                Select an event to inspect its details.
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="grid border-t border-border/50 lg:grid-cols-2">
        <details className="border-b border-border/45 p-3 lg:border-b-0 lg:border-r">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-2 text-xs font-semibold text-foreground">
            <span className="flex items-center gap-2"><Bot className="h-3.5 w-3.5 text-primary" />Skills & resources</span>
            <span className="text-[10px] font-normal text-muted-foreground">{skills.length} skills · {resources.length} resources</span>
          </summary>
          <div className="mt-2 space-y-2">
            <div className="flex flex-wrap gap-1">
              {skills.length > 0
                ? skills.map((skill) => <Badge key={skill} variant="outline" className="h-5 text-[9px]">{skill}</Badge>)
                : <span className="text-[10px] text-muted-foreground">No explicit skill usage was reported.</span>}
            </div>
            {resources.length > 0 && (
              <div className="grid gap-1 sm:grid-cols-2">
                {resources.map((resource) => (
                  <div key={resource} className="truncate rounded border border-border/35 bg-muted/20 px-2 py-1 text-[10px] text-foreground">
                    {resource}
                  </div>
                ))}
              </div>
            )}
          </div>
        </details>

        <details className="p-3">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-2 text-xs font-semibold text-foreground">
            <span className="flex items-center gap-2"><FileJson className="h-3.5 w-3.5 text-primary" />Visible final response</span>
            <span className="flex items-center gap-1 text-[10px] font-normal text-muted-foreground">
              <Clock3 className="h-3 w-3" />{finalResponse.length.toLocaleString()} chars
            </span>
          </summary>
          {finalResponse ? (
            <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-words rounded bg-zinc-950 p-2 font-mono text-[10px] leading-4 text-zinc-100">
              {finalResponse}
            </pre>
          ) : (
            <div className="mt-2 text-[10px] text-muted-foreground">No final response was persisted.</div>
          )}
        </details>
      </div>
    </section>
  );
}
