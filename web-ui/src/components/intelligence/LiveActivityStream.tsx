import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  MessageSquare,
  Radio,
  RefreshCw,
  ShieldAlert,
  Wrench,
  XCircle,
  Zap,
  Sparkles,
  Clock,
  BrainCircuit,
  FileCode2,
  Search,
  AlertCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import type { AgentActivity, AgentActivityType } from "@/types";

/* ────────── activity type config ────────── */

interface ActivityTypeConfig {
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  color: string;
  bg: string;
  border: string;
  severity: number; // 0=info, 1=warning, 2=error
}

const TYPE_CONFIG: Record<AgentActivityType, ActivityTypeConfig> = {
  reasoning: {
    label: "Reasoning",
    icon: BrainCircuit,
    color: "text-sky-400",
    bg: "bg-sky-500/5",
    border: "border-sky-500/20",
    severity: 0,
  },
  operation: {
    label: "Operation",
    icon: Wrench,
    color: "text-amber-400",
    bg: "bg-amber-500/5",
    border: "border-amber-500/20",
    severity: 0,
  },
  a2a: {
    label: "A2A",
    icon: MessageSquare,
    color: "text-violet-400",
    bg: "bg-violet-500/5",
    border: "border-violet-500/20",
    severity: 0,
  },
  file: {
    label: "File",
    icon: FileCode2,
    color: "text-emerald-400",
    bg: "bg-emerald-500/5",
    border: "border-emerald-500/20",
    severity: 0,
  },
  warning: {
    label: "Warning",
    icon: AlertTriangle,
    color: "text-amber-400",
    bg: "bg-amber-500/5",
    border: "border-amber-500/20",
    severity: 1,
  },
  error: {
    label: "Error",
    icon: XCircle,
    color: "text-red-400",
    bg: "bg-red-500/5",
    border: "border-red-500/20",
    severity: 2,
  },
  success: {
    label: "Success",
    icon: CheckCircle2,
    color: "text-emerald-400",
    bg: "bg-emerald-500/5",
    border: "border-emerald-500/20",
    severity: 0,
  },
  system: {
    label: "System",
    icon: Zap,
    color: "text-muted-foreground",
    bg: "bg-muted/30",
    border: "border-border/40",
    severity: 0,
  },
};

/* ────────── mode presets ────────── */

type StreamMode = "keyMoments" | "verbose" | "problems" | "currentStep";

interface ModePreset {
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  description: string;
  filter: (activity: AgentActivity) => boolean;
}

function isKeyMoment(activity: AgentActivity): boolean {
  const ev = activity.event.toLowerCase();
  return (
    activity.type === "error" ||
    activity.type === "warning" ||
    ev.includes("failed") ||
    ev.includes("completed") ||
    ev.includes("started") ||
    ev.includes("approval") ||
    ev.includes("verify") ||
    ev.includes("artifact")
  );
}

function isProblem(activity: AgentActivity): boolean {
  return activity.type === "error" || activity.type === "warning";
}

/* ────────── helpers ────────── */

function formatTimestamp(ts: string): string {
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString(undefined, { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return ts;
  }
}

function activityTypeFromEvent(event: string, details: Record<string, unknown>): AgentActivityType {
  const ev = event.toLowerCase();
  if (ev.includes("error") || ev.includes("failed") || (details.error && String(details.error))) return "error";
  if (ev.includes("warning")) return "warning";
  if (ev.includes("a2a") || ev.includes("handoff")) return "a2a";
  if (ev.includes("file") || ev.includes("artifact")) return "file";
  if (ev.includes("complete") || ev.includes("success")) return "success";
  if (ev.includes("loop") || ev.includes("plan") || ev.includes("think")) return "reasoning";
  if (ev.includes("invoke") || ev.includes("tool") || ev.includes("verify")) return "operation";
  return "system";
}

function activitySummary(event: string, details: Record<string, unknown>): string {
  const ev = event.toLowerCase();
  const step = (details.step || details.stepName || "") as string;
  if (ev.includes("step.started")) return `Step started: ${step}`;
  if (ev.includes("step.completed")) return `Step completed: ${step}`;
  if (ev.includes("step.failed")) return `Step failed: ${step}`;
  if (ev.includes("step.verify")) return `Verifying: ${step}`;
  if (ev.includes("review")) return `Review: ${step}`;
  if (ev.includes("approval")) return `Approval: ${step}`;
  if (ev.includes("loop.iteration")) return `Loop: ${step}`;
  if (ev.includes("artifact")) return `Artifact: ${(details.path || details.name || "") as string}`;
  if (ev.includes("tool")) return `Tool: ${(details.tool_name || details.tool || "") as string}`;
  return event;
}

function activityPills(activity: AgentActivity): string[] {
  const pills: string[] = [];
  const d = activity.details;
  if (d.tool || d.tool_name) pills.push(`tool: ${(d.tool || d.tool_name) as string}`);
  if (d.path || d.name) pills.push(`file: ${(d.path || d.name) as string}`);
  if (d.latencyMs != null) pills.push(`${(d.latencyMs as number) < 1000 ? `${d.latencyMs}ms` : `${((d.latencyMs as number) / 1000).toFixed(1)}s`}`);
  if (d.status) pills.push(d.status as string);
  if (d.agentRef || d.agent) pills.push(`agent: ${(d.agentRef || d.agent) as string}`);
  return pills.slice(0, 3);
}

/* ────────── component ────────── */

interface LiveActivityStreamProps {
  workflowName?: string;
  activities: AgentActivity[];
  isConnected: boolean;
  isActive: boolean;
  phase: string;
  error: string | null;
  onReconnect?: () => void;
  className?: string;
  compact?: boolean;
}

export function LiveActivityStream({
  workflowName: _workflowName,
  activities,
  isConnected,
  isActive,
  phase,
  error,
  onReconnect,
  className,
  compact = false,
}: LiveActivityStreamProps) {
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [streamMode, setStreamMode] = useState<StreamMode>(isActive ? "keyMoments" : "verbose");
  const [searchQuery, setSearchQuery] = useState("");
  const [stepFilter, setStepFilter] = useState<string>("all");
  const [autoScroll, setAutoScroll] = useState(true);
  const [userScrolledUp, setUserScrolledUp] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Derive available steps from activities
  const availableSteps = useMemo(() => {
    const steps = new Set<string>();
    for (const a of activities) {
      if (a.step) steps.add(a.step);
    }
    return Array.from(steps).sort();
  }, [activities]);

  // Determine the active step (most recent event's step)
  const activeStep = useMemo(() => {
    for (let i = activities.length - 1; i >= 0; i--) {
      if (activities[i].step) return activities[i].step;
    }
    return null;
  }, [activities]);

  // Build mode presets with current data
  const modes: Record<StreamMode, ModePreset> = useMemo(() => ({
    keyMoments: {
      label: "Key moments",
      icon: Sparkles,
      description: "Step changes, errors, completions",
      filter: (a) => isKeyMoment(a),
    },
    verbose: {
      label: "Verbose",
      icon: Radio,
      description: "All events",
      filter: () => true,
    },
    problems: {
      label: "Problems",
      icon: AlertCircle,
      description: "Errors and warnings only",
      filter: (a) => isProblem(a),
    },
    currentStep: {
      label: "Current step",
      icon: Clock,
      description: activeStep ? `Events for "${activeStep}"` : "No active step",
      filter: (a) => a.step === activeStep,
    },
  }), [activeStep]);

  // Combined filter
  const filtered = useMemo(() => {
    const modeFilter = modes[streamMode].filter;
    let result = activities.filter(modeFilter);

    if (stepFilter !== "all") {
      result = result.filter((a) => a.step === stepFilter);
    }

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      result = result.filter(
        (a) =>
          a.message.toLowerCase().includes(q) ||
          a.event.toLowerCase().includes(q) ||
          a.step.toLowerCase().includes(q) ||
          a.agentRef.toLowerCase().includes(q) ||
          JSON.stringify(a.details).toLowerCase().includes(q),
      );
    }

    return result;
  }, [activities, streamMode, stepFilter, searchQuery, modes]);

  // Auto-scroll to bottom when new activities arrive
  useEffect(() => {
    if (!autoScroll || userScrolledUp) return;
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [filtered, autoScroll, userScrolledUp]);

  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    setUserScrolledUp(!nearBottom);
    if (nearBottom) setAutoScroll(true);
  };

  const toggleExpanded = (id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const showEmpty = filtered.length === 0;
  const statusDot = isConnected ? (isActive ? "bg-emerald-500 animate-pulse" : "bg-sky-500") : "bg-red-500";
  const ModeIcon = modes[streamMode].icon;

  // When active, default to keyMoments mode
  useEffect(() => {
    if (isActive && streamMode === "verbose") {
      setStreamMode("keyMoments");
    }
  }, [isActive, streamMode]);

  return (
    <div className={cn("flex flex-col h-full bg-background", className)}>
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b shrink-0">
        <div className="flex items-center gap-2">
          <Radio className={cn("h-3.5 w-3.5", statusDot)} />
          <span className="text-xs font-semibold uppercase tracking-wider">Live Activity</span>
          <Badge variant="outline" className="text-[10px] h-4 px-1">
            {filtered.length}
          </Badge>
        </div>
        <div className="flex items-center gap-1">
          {!isConnected && onReconnect && (
            <Button variant="ghost" size="icon" className="h-6 w-6" onClick={onReconnect} title="Reconnect">
              <RefreshCw className="h-3 w-3" />
            </Button>
          )}
        </div>
      </div>

      {/* Mode presets + filters */}
      {!compact && (
        <div className="flex flex-col gap-1 px-3 py-1.5 border-b shrink-0">
          {/* Mode selector */}
          <div className="flex items-center gap-1">
            <Select value={streamMode} onValueChange={(v) => setStreamMode(v as StreamMode)}>
              <SelectTrigger className="h-7 text-[10px] gap-1 px-2">
                <ModeIcon className="h-3 w-3" />
                <SelectValue placeholder="Select mode" />
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(modes) as StreamMode[]).map((mode) => {
                  const m = modes[mode];
                  const MIcon = m.icon;
                  return (
                    <SelectItem key={mode} value={mode} className="text-xs">
                      <div className="flex items-center gap-2">
                        <MIcon className="h-3 w-3" />
                        <span>{m.label}</span>
                        <span className="text-[9px] text-muted-foreground ml-1">{m.description}</span>
                      </div>
                    </SelectItem>
                  );
                })}
              </SelectContent>
            </Select>
          </div>

          {/* Step filter + search */}
          <div className="flex items-center gap-1">
            {availableSteps.length > 1 && (
              <Select value={stepFilter} onValueChange={setStepFilter}>
                <SelectTrigger className="h-7 text-[10px] px-2 max-w-[120px]">
                  <SelectValue placeholder="Step" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all" className="text-xs">All steps</SelectItem>
                  {availableSteps.map((s) => (
                    <SelectItem key={s} value={s} className="text-xs">{s}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
            <div className="relative flex-1">
              <Search className="absolute left-1.5 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground/50" />
              <Input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search events…"
                className="h-7 text-[10px] pl-6"
              />
            </div>
          </div>

          {/* Quick type indicator */}
          {streamMode === "keyMoments" && (
            <div className="flex items-center gap-1 text-[9px] text-muted-foreground/60">
              <Sparkles className="h-2.5 w-2.5" />
              Showing key events only. Switch to "Verbose" for all events.
            </div>
          )}
          {streamMode === "problems" && filtered.length === 0 && (
            <div className="flex items-center gap-1 text-[9px] text-emerald-400/80">
              <CheckCircle2 className="h-2.5 w-2.5" />
              No problems detected.
            </div>
          )}
        </div>
      )}

      {/* Activity feed */}
      <ScrollArea className="flex-1 min-h-0" onScrollCapture={handleScroll}>
        <div ref={scrollRef} className="space-y-1 p-2">
          {showEmpty && (
            <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
              <Activity className="h-8 w-8 mb-2 opacity-40" />
              <p className="text-xs">No activity yet</p>
              <p className="text-[10px] opacity-60">Start the workflow to see live reasoning & operations</p>
            </div>
          )}

          {filtered.map((activity) => {
            const cfg = TYPE_CONFIG[activity.type] ?? TYPE_CONFIG.system;
            const Icon = cfg.icon;
            const isExpanded = expandedIds.has(activity.id);
            const hasDetails = Object.keys(activity.details).length > 0;
            const pills = activityPills(activity);
            const summary = activitySummary(activity.event, activity.details);

            return (
              <div
                key={activity.id}
                className={cn(
                  "rounded-md border px-2.5 py-2 text-xs transition-colors hover:bg-accent/40",
                  cfg.bg,
                  cfg.border,
                )}
              >
                <div className="flex items-start gap-2">
                  <div className="flex flex-col items-center gap-0.5 mt-0.5">
                    <Icon className={cn("h-3.5 w-3.5 shrink-0", cfg.color)} />
                    <div className={cn(
                      "h-full w-px min-h-[8px]",
                      cfg.severity >= 2 ? "bg-red-500/30" : cfg.severity >= 1 ? "bg-amber-500/20" : "bg-border/30",
                    )} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className="text-[10px] tabular-nums text-muted-foreground font-mono">
                        {formatTimestamp(activity.timestamp)}
                      </span>
                      {activity.step && (
                        <Badge variant="outline" className="text-[9px] h-3.5 px-1 border-border/40">
                          {activity.step}
                        </Badge>
                      )}
                      {activity.agentRef && (
                        <Badge variant="secondary" className="text-[9px] h-3.5 px-1">
                          {activity.agentRef}
                        </Badge>
                      )}
                    </div>
                    <p className={cn("mt-0.5 leading-snug", cfg.color)}>{summary}</p>

                    {/* Pills */}
                    {pills.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-1">
                        {pills.map((pill, i) => (
                          <span
                            key={i}
                            className="inline-flex items-center rounded-full bg-muted/60 px-1.5 py-0.5 text-[9px] font-mono text-muted-foreground/80"
                          >
                            {pill}
                          </span>
                        ))}
                      </div>
                    )}

                    {hasDetails && (
                      <button
                        onClick={() => toggleExpanded(activity.id)}
                        className="flex items-center gap-0.5 text-[10px] text-muted-foreground hover:text-foreground mt-1 transition-colors"
                      >
                        {isExpanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                        {isExpanded ? "Hide details" : "Show details"}
                      </button>
                    )}

                    {isExpanded && hasDetails && (
                      <div className="mt-1.5 rounded bg-background/60 border border-border/40 p-2 overflow-x-auto">
                        <pre className="text-[10px] text-muted-foreground whitespace-pre-wrap">
                          {JSON.stringify(activity.details, null, 2)}
                        </pre>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
          <div ref={bottomRef} />
        </div>
      </ScrollArea>

      {/* Footer */}
      <div className="flex items-center justify-between px-3 py-1.5 border-t shrink-0 text-[10px] text-muted-foreground">
        <div className="flex items-center gap-1.5">
          {isConnected ? (
            <>
              <span className={cn("h-1.5 w-1.5 rounded-full", isActive ? "bg-emerald-500 animate-pulse" : "bg-sky-500")} />
              {isActive ? "Streaming" : phase || "Connected"}
            </>
          ) : (
            <>
              <ShieldAlert className="h-3 w-3 text-red-400" />
              Disconnected
            </>
          )}
          {error && <span className="text-red-400 ml-1">· {error}</span>}
        </div>
        {userScrolledUp && activities.length > 0 && (
          <button
            onClick={() => {
              setUserScrolledUp(false);
              setAutoScroll(true);
              bottomRef.current?.scrollIntoView({ behavior: "smooth" });
            }}
            className="flex items-center gap-1 text-sky-400 hover:text-sky-300 transition-colors"
          >
            <ChevronDown className="h-3 w-3" />
            New activity
          </button>
        )}
      </div>
    </div>
  );
}

/* ────────── hook: useWorkflowActivities ────────── */

import { useCallback } from "react";
import { createWorkflowActivitiesStream } from "@/lib/api";

export function useWorkflowActivities(token: string, namespace: string, workflowName: string | null) {
  const [activities, setActivities] = useState<AgentActivity[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [isActive, setIsActive] = useState(false);
  const [phase, setPhase] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);

  const reconnect = useCallback(() => setRetryKey((k) => k + 1), []);

  useEffect(() => {
    if (!workflowName || !token) return;

    setActivities([]);
    setError(null);
    setIsConnected(false);

    let es: EventSource | null = null;
    let cancelled = false;

    try {
      es = createWorkflowActivitiesStream(token, namespace, workflowName, 200);

      es.addEventListener("activities.started", (e) => {
        if (cancelled) return;
        try {
          const data = JSON.parse((e as MessageEvent).data);
          setIsActive(data.is_active ?? false);
          setPhase(data.phase ?? "");
          setIsConnected(true);
        } catch {
          setIsConnected(true);
        }
      });

      es.addEventListener("activity", (e) => {
        if (cancelled) return;
        try {
          const raw = JSON.parse((e as MessageEvent).data);
          const enriched: AgentActivity = {
            ...raw,
            type: activityTypeFromEvent(raw.event ?? "", raw.details ?? {}),
          };
          setActivities((prev) => {
            if (prev.some((a) => a.id === enriched.id)) return prev;
            return [...prev, enriched];
          });
        } catch {
          // ignore malformed events
        }
      });

      es.addEventListener("activities.done", (e) => {
        if (cancelled) return;
        try {
          const data = JSON.parse((e as MessageEvent).data);
          setIsActive(false);
          setPhase(data.phase ?? "");
        } catch {
          setIsActive(false);
        }
      });

      es.addEventListener("activities.error", (e) => {
        if (cancelled) return;
        try {
          const data = JSON.parse((e as MessageEvent).data);
          setError(data.error ?? "Stream error");
        } catch {
          setError("Stream error");
        }
        setIsConnected(false);
      });

      es.onerror = () => {
        if (cancelled) return;
        setIsConnected(false);
      };

      es.onopen = () => {
        if (cancelled) return;
        setIsConnected(true);
        setError(null);
      };
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to connect");
    }

    return () => {
      cancelled = true;
      es?.close();
    };
  }, [workflowName, namespace, token, retryKey]);

  return { activities, isConnected, isActive, phase, error, reconnect };
}
