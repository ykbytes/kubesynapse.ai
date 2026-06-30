import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  BookOpen,
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
import { MarkdownRenderer } from "@/components/shared/MarkdownRenderer";
import { cn } from "@/lib/utils";
import type { OptimizerTrace, OptimizerTraceEvent } from "@/types";

type TraceFilter = "all" | "context" | "reasoning" | "tools" | "decisions" | "errors";

interface OptimizerTracePanelProps {
  trace?: OptimizerTrace | null;
  audit?: Record<string, unknown>;
  visibleResponse?: string | null;
  candidateName?: string | null;
}

const FILTERS: Array<{ value: TraceFilter; label: string }> = [
  { value: "all", label: "All activity" },
  { value: "context", label: "Loaded context" },
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

function summarizeToolCall(call: Record<string, unknown>): { title: string; summary: string } {
  const payload = record(call);
  const title = display(payload.tool_name ?? payload.tool ?? payload.name, "tool");
  const summary = display(
    payload.summary ??
    payload.path ??
    payload.args_preview ??
    payload.detail ??
    payload.status,
    "No tool detail captured.",
  );
  return { title, summary };
}

function summarizeArtifact(artifact: Record<string, unknown>): { title: string; summary: string } {
  const payload = record(artifact);
  const title = display(payload.name ?? payload.path ?? payload.uri, "artifact");
  const summary = display(
    payload.type ??
    payload.preview ??
    payload.status ??
    payload.description,
    "Captured during candidate generation.",
  );
  return { title, summary };
}

function eventIcon(kind: OptimizerTraceEvent["kind"]) {
  if (kind === "skill") return BookOpen;
  if (kind === "reasoning") return BrainCircuit;
  if (kind === "tool") return Wrench;
  if (kind === "error" || kind === "warning") return AlertTriangle;
  if (kind === "completion") return CheckCircle2;
  if (kind === "response") return FileJson;
  return CircleDot;
}

function eventTone(kind: OptimizerTraceEvent["kind"]): string {
  if (kind === "skill") return "border-cyan-500/35 bg-cyan-500/8 text-cyan-700 dark:text-cyan-300";
  if (kind === "reasoning") return "border-violet-500/35 bg-violet-500/8 text-violet-700 dark:text-violet-300";
  if (kind === "tool") return "border-sky-500/35 bg-sky-500/8 text-sky-700 dark:text-sky-300";
  if (kind === "error") return "border-red-500/35 bg-red-500/8 text-red-700 dark:text-red-300";
  if (kind === "warning") return "border-amber-500/35 bg-amber-500/8 text-amber-700 dark:text-amber-300";
  if (kind === "completion") return "border-emerald-500/35 bg-emerald-500/8 text-emerald-700 dark:text-emerald-300";
  return "border-border/60 bg-muted/25 text-foreground";
}

function matchesFilter(event: OptimizerTraceEvent, filter: TraceFilter): boolean {
  if (filter === "all") return true;
  if (filter === "context") return event.kind === "skill";
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
  const preferredEvent =
    filteredEvents.find((event) => event.kind === "reasoning") ??
    filteredEvents.find((event) => event.kind === "skill") ??
    filteredEvents[0] ??
    null;
  const selectedEvent =
    filteredEvents.find((event) => event.id === selectedEventId) ??
    preferredEvent;

  useEffect(() => {
    if (!filteredEvents.some((event) => event.id === selectedEventId)) {
      setSelectedEventId(preferredEvent?.id ?? null);
    }
  }, [filteredEvents, preferredEvent, selectedEventId]);

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
  const toolCalls = effectiveTrace.tool_calls ?? [];
  const artifacts = effectiveTrace.artifacts ?? [];
  const loadedSkillEvents = effectiveTrace.events.filter((event) => event.kind === "skill");
  const finalResponse = effectiveTrace.final_response || visibleResponse || "";
  const selectedPayload = record(selectedEvent?.payload);
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

        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[10px] text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <Clock3 className="h-3.5 w-3.5" />
            <strong className="font-semibold text-foreground">{formatDuration(effectiveTrace.duration_ms)}</strong>
          </span>
          <span className="min-w-0 truncate">
            Model <strong className="font-semibold text-foreground">{display(effectiveTrace.model, "--")}</strong>
          </span>
          <span><strong className="font-semibold text-foreground">{effectiveTrace.summary.event_count}</strong> events</span>
          <span><strong className="font-semibold text-foreground">{effectiveTrace.summary.tool_count}</strong> tools</span>
          <span><strong className="font-semibold text-foreground">{loadedSkillEvents.length || skills.length}</strong> skills loaded</span>
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

      <div className="grid min-h-[32rem] lg:grid-cols-[15.5rem_minmax(0,1fr)]">
        <div className="border-b border-border/50 bg-muted/10 lg:border-b-0 lg:border-r">
          <div className="flex items-center justify-between border-b border-border/40 px-3 py-2">
            <div className="text-[10px] font-semibold uppercase text-muted-foreground">Activity</div>
            <div className="text-[10px] text-muted-foreground">{filteredEvents.length}</div>
          </div>
          <div className="max-h-[42rem] overflow-y-auto px-2 py-2">
            {filteredEvents.length > 0 ? (
              <div className="relative space-y-1 before:absolute before:bottom-4 before:left-[1.08rem] before:top-4 before:w-px before:bg-border/50">
                {filteredEvents.map((event) => {
                  const Icon = eventIcon(event.kind);
                  const selected = selectedEvent?.id === event.id;
                  return (
                    <button
                      key={event.id}
                      type="button"
                      className={cn(
                        "relative grid w-full grid-cols-[1.75rem_minmax(0,1fr)] gap-2 rounded-md border px-1.5 py-2 text-left transition-colors",
                        selected
                          ? "border-primary/35 bg-background shadow-sm"
                          : "border-transparent hover:border-border/50 hover:bg-background/65",
                      )}
                      onClick={() => setSelectedEventId(event.id)}
                    >
                      <span className={cn("z-10 flex h-7 w-7 items-center justify-center rounded-full border bg-background", eventTone(event.kind))}>
                        <Icon className="h-3.5 w-3.5" />
                      </span>
                      <span className="min-w-0">
                        <span className="flex items-center justify-between gap-2">
                          <span className="truncate text-[11px] font-semibold text-foreground">{event.title}</span>
                          <span className="shrink-0 text-[9px] tabular-nums text-muted-foreground">{formatTime(event.timestamp)}</span>
                        </span>
                        <span className="mt-0.5 block line-clamp-2 text-[10px] leading-4 text-muted-foreground">
                          {event.summary || "No summary emitted."}
                        </span>
                      </span>
                    </button>
                  );
                })}
              </div>
            ) : (
              <div className="p-8 text-center text-[11px] text-muted-foreground">No events match this filter.</div>
            )}
          </div>
        </div>

        <div className="min-w-0 bg-background/45">
          <div className="flex items-center justify-between border-b border-border/40 px-4 py-2">
            <div className="text-[10px] font-semibold uppercase text-muted-foreground">Conversation</div>
            {selectedEvent && (
              <span className="text-[10px] text-muted-foreground">
                #{selectedEvent.sequence} · {formatTime(selectedEvent.timestamp)}
              </span>
            )}
          </div>
          <div className="max-h-[42rem] overflow-y-auto px-3 py-4 sm:px-5">
            {selectedEvent ? (
              <article className="mx-auto max-w-4xl">
                <div className="flex items-start gap-3">
                  <div className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-full border", eventTone(selectedEvent.kind))}>
                    {(() => {
                      const Icon = eventIcon(selectedEvent.kind);
                      return <Icon className="h-4 w-4" />;
                    })()}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <span className="text-sm font-semibold text-foreground">
                        {selectedEvent.kind === "reasoning" || selectedEvent.kind === "response"
                          ? display(effectiveTrace.agent_name, "optimizer")
                          : selectedEvent.title}
                      </span>
                      <Badge variant="outline" className="h-5 text-[9px]">{selectedEvent.kind}</Badge>
                    </div>
                    <div className={cn(
                      "mt-2 rounded-lg border px-4 py-3 shadow-sm",
                      selectedEvent.kind === "reasoning"
                        ? "border-violet-500/20 bg-violet-500/5"
                        : selectedEvent.kind === "skill"
                          ? "border-cyan-500/20 bg-cyan-500/5"
                          : "border-border/50 bg-card",
                    )}>
                      <div className="mb-2 text-sm font-semibold text-foreground">{selectedEvent.title}</div>
                      <MarkdownRenderer
                        content={selectedEvent.summary || "No summary was emitted for this event."}
                        className="text-[13px] leading-6 text-foreground/85 [&_p]:my-2 [&_li]:text-[13px]"
                      />

                      {selectedEvent.kind === "skill" && (
                        <div className="mt-3 grid gap-2 border-t border-cyan-500/15 pt-3 text-[10px] sm:grid-cols-2">
                          <div className="rounded-md border border-border/40 bg-background/70 p-2">
                            <div className="text-muted-foreground">Skill</div>
                            <div className="mt-0.5 font-semibold text-foreground">{display(selectedPayload.name, "unnamed skill")}</div>
                          </div>
                          <div className="rounded-md border border-border/40 bg-background/70 p-2">
                            <div className="text-muted-foreground">Delivery</div>
                            <div className="mt-0.5 font-semibold text-foreground">{display(selectedPayload.delivery, "runtime context").replace(/_/g, " ")}</div>
                          </div>
                          <div className="rounded-md border border-border/40 bg-background/70 p-2 sm:col-span-2">
                            <div className="text-muted-foreground">Materialized file</div>
                            <div className="mt-0.5 break-all font-mono text-foreground">{display(selectedPayload.file, "path unavailable")}</div>
                          </div>
                        </div>
                      )}
                    </div>

                    {selectedEvent.kind === "reasoning" && (
                      <div className="mt-2 text-[10px] leading-4 text-muted-foreground">
                        Observable reasoning summary emitted by the runtime. Hidden model chain-of-thought is not exposed.
                      </div>
                    )}
                    {selectedEvent.payload !== undefined && (
                      <details className="mt-3 rounded-md border border-border/45 bg-card/60 p-2">
                        <summary className="cursor-pointer list-none text-[11px] font-semibold text-foreground">Raw event data</summary>
                        <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded bg-zinc-950 p-3 font-mono text-[10px] leading-4 text-zinc-100">
                          {JSON.stringify(selectedEvent.payload, null, 2)}
                        </pre>
                      </details>
                    )}
                  </div>
                </div>
              </article>
            ) : (
              <div className="flex min-h-64 items-center justify-center text-center text-[11px] text-muted-foreground">
                Select an event to inspect its details.
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="grid border-t border-border/50 lg:grid-cols-2">
        <details className="border-b border-border/45 p-3 lg:border-r">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-2 text-xs font-semibold text-foreground">
            <span className="flex items-center gap-2"><BookOpen className="h-3.5 w-3.5 text-primary" />Loaded context</span>
            <span className="text-[10px] font-normal text-muted-foreground">{skills.length} skills · {resources.length} resources</span>
          </summary>
          <div className="mt-2 space-y-2.5">
            {loadedSkillEvents.length > 0 ? (
              <div className="space-y-1.5">
                {loadedSkillEvents.map((event) => {
                  const payload = record(event.payload);
                  return (
                    <div key={event.id} className="rounded-md border border-cyan-500/20 bg-cyan-500/5 px-2.5 py-2">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="text-[11px] font-semibold text-foreground">{display(payload.name, event.title)}</span>
                        <Badge variant="outline" className="h-5 border-cyan-500/25 text-[9px]">
                          {display(payload.delivery, "loaded").replace(/_/g, " ")}
                        </Badge>
                      </div>
                      <div className="mt-1 break-all font-mono text-[9px] leading-4 text-muted-foreground">
                        {display(payload.file, "Materialized file path unavailable")}
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="rounded-md border border-dashed border-border/50 p-2 text-[10px] text-muted-foreground">
                This candidate predates explicit runtime skill-load events. Reported skill use is shown below.
              </div>
            )}
            <div className="flex flex-wrap gap-1">
              {skills.map((skill) => <Badge key={skill} variant="outline" className="h-5 text-[9px]">{skill}</Badge>)}
            </div>
            {resources.length > 0 && (
              <div className="space-y-1">
                {resources.map((resource) => (
                  <div key={resource} className="break-all rounded border border-border/35 bg-muted/20 px-2 py-1 text-[10px] text-foreground">
                    {resource}
                  </div>
                ))}
              </div>
            )}
          </div>
        </details>

        <details className="border-b border-border/45 p-3">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-2 text-xs font-semibold text-foreground">
            <span className="flex items-center gap-2"><Wrench className="h-3.5 w-3.5 text-primary" />Tool calls & artifacts</span>
            <span className="text-[10px] font-normal text-muted-foreground">{toolCalls.length} tools · {artifacts.length} artifacts</span>
          </summary>
          <div className="mt-2 space-y-3">
            <div>
              <div className="text-[10px] font-medium text-muted-foreground">Tools used</div>
              {toolCalls.length > 0 ? (
                <div className="mt-1 space-y-1.5">
                  {toolCalls.slice(0, 8).map((call, index) => {
                    const { title, summary } = summarizeToolCall(record(call));
                    return (
                      <div key={`${title}-${index}`} className="rounded border border-border/35 bg-muted/20 px-2 py-1.5">
                        <div className="truncate text-[10px] font-semibold text-foreground">{title}</div>
                        <div className="mt-0.5 line-clamp-2 text-[10px] leading-4 text-muted-foreground">{summary}</div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="mt-1 text-[10px] text-muted-foreground">No explicit tool calls were persisted.</div>
              )}
            </div>
            <div>
              <div className="text-[10px] font-medium text-muted-foreground">Artifacts returned</div>
              {artifacts.length > 0 ? (
                <div className="mt-1 space-y-1.5">
                  {artifacts.slice(0, 8).map((artifact, index) => {
                    const { title, summary } = summarizeArtifact(record(artifact));
                    return (
                      <div key={`${title}-${index}`} className="rounded border border-border/35 bg-muted/20 px-2 py-1.5">
                        <div className="truncate text-[10px] font-semibold text-foreground">{title}</div>
                        <div className="mt-0.5 line-clamp-2 text-[10px] leading-4 text-muted-foreground">{summary}</div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="mt-1 text-[10px] text-muted-foreground">No optimizer artifacts were persisted.</div>
              )}
            </div>
          </div>
        </details>

        <details className="p-3 lg:col-span-2">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-2 text-xs font-semibold text-foreground">
            <span className="flex items-center gap-2"><FileJson className="h-3.5 w-3.5 text-primary" />Visible final response</span>
            <span className="flex items-center gap-1 text-[10px] font-normal text-muted-foreground">
              <Clock3 className="h-3 w-3" />{finalResponse.length.toLocaleString()} chars
            </span>
          </summary>
          {finalResponse ? (
            <div className="mt-2 max-h-[34rem] overflow-auto rounded-md border border-border/40 bg-background/70 px-4 py-3">
              <MarkdownRenderer
                content={finalResponse}
                className="text-[12px] leading-5 text-foreground/85 [&_p]:my-2 [&_li]:text-[12px]"
              />
            </div>
          ) : (
            <div className="mt-2 text-[10px] text-muted-foreground">No final response was persisted.</div>
          )}
        </details>
      </div>
    </section>
  );
}
