import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  BrainCircuit,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  FileCode2,
  Filter,
  MessageSquare,
  Radio,
  RefreshCw,
  ShieldAlert,
  Wrench,
  XCircle,
  Zap,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import type { AgentActivity, AgentActivityType } from "@/types";

/* ────────── activity type config ────────── */

interface ActivityTypeConfig {
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  color: string;
  bg: string;
  border: string;
}

const TYPE_CONFIG: Record<AgentActivityType, ActivityTypeConfig> = {
  reasoning: {
    label: "Reasoning",
    icon: BrainCircuit,
    color: "text-sky-400",
    bg: "bg-sky-500/5",
    border: "border-sky-500/20",
  },
  operation: {
    label: "Operation",
    icon: Wrench,
    color: "text-amber-400",
    bg: "bg-amber-500/5",
    border: "border-amber-500/20",
  },
  a2a: {
    label: "A2A",
    icon: MessageSquare,
    color: "text-violet-400",
    bg: "bg-violet-500/5",
    border: "border-violet-500/20",
  },
  file: {
    label: "File",
    icon: FileCode2,
    color: "text-emerald-400",
    bg: "bg-emerald-500/5",
    border: "border-emerald-500/20",
  },
  warning: {
    label: "Warning",
    icon: AlertTriangle,
    color: "text-amber-400",
    bg: "bg-amber-500/5",
    border: "border-amber-500/20",
  },
  error: {
    label: "Error",
    icon: XCircle,
    color: "text-red-400",
    bg: "bg-red-500/5",
    border: "border-red-500/20",
  },
  success: {
    label: "Success",
    icon: CheckCircle2,
    color: "text-emerald-400",
    bg: "bg-emerald-500/5",
    border: "border-emerald-500/20",
  },
  system: {
    label: "System",
    icon: Zap,
    color: "text-muted-foreground",
    bg: "bg-muted/30",
    border: "border-border/40",
  },
};

const ALL_TYPES = Object.keys(TYPE_CONFIG) as AgentActivityType[];

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
  const [selectedTypes, setSelectedTypes] = useState<Set<AgentActivityType>>(new Set(ALL_TYPES));
  const [autoScroll, setAutoScroll] = useState(true);
  const [userScrolledUp, setUserScrolledUp] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const filtered = useMemo(
    () => activities.filter((a) => selectedTypes.has(a.type)),
    [activities, selectedTypes],
  );

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

  const toggleType = (type: AgentActivityType) => {
    setSelectedTypes((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  };

  const showEmpty = filtered.length === 0;
  const statusDot = isConnected ? (isActive ? "bg-emerald-500 animate-pulse" : "bg-sky-500") : "bg-red-500";

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

      {/* Type filters */}
      {!compact && (
        <div className="flex items-center gap-1 px-3 py-1.5 border-b shrink-0 overflow-x-auto">
          <Filter className="h-3 w-3 text-muted-foreground shrink-0 mr-1" />
          {ALL_TYPES.map((type) => {
            const cfg = TYPE_CONFIG[type];
            const active = selectedTypes.has(type);
            const Icon = cfg.icon;
            return (
              <button
                key={type}
                onClick={() => toggleType(type)}
                className={cn(
                  "flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium transition-colors border",
                  active
                    ? cn(cfg.bg, cfg.color, cfg.border)
                    : "bg-muted/30 text-muted-foreground border-transparent opacity-60",
                )}
                title={cfg.label}
              >
                <Icon className="h-3 w-3" />
                <span className="hidden sm:inline">{cfg.label}</span>
              </button>
            );
          })}
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
                  <Icon className={cn("h-3.5 w-3.5 shrink-0 mt-0.5", cfg.color)} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className="text-[10px] tabular-nums text-muted-foreground">
                        {formatTimestamp(activity.timestamp)}
                      </span>
                      {activity.agentRef && (
                        <Badge variant="outline" className="text-[9px] h-3.5 px-1">
                          {activity.agentRef}
                        </Badge>
                      )}
                      {activity.step && (
                        <Badge variant="secondary" className="text-[9px] h-3.5 px-1">
                          {activity.step}
                        </Badge>
                      )}
                    </div>
                    <p className={cn("mt-0.5 leading-snug", cfg.color)}>{activity.message}</p>

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

      {/* Footer status */}
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
