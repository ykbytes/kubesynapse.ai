import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  Brain,
  ChevronDown,
  ChevronRight,
  Cog,
  DollarSign,
  FileCode,
  Lightbulb,
  AlertTriangle,
  Footprints,
  Clock,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { JsonBlock } from "../shared/JsonBlock";
import type { UiActivity } from "@/types";

/* ------------------------------------------------------------------ */
/*  Event categorisation                                              */
/* ------------------------------------------------------------------ */

type EventCategory = "progress" | "tool" | "diff" | "tokens" | "thinking" | "error" | "plan" | "other";

const CATEGORY_STYLES: Record<EventCategory, { bg: string; text: string; icon: typeof Activity }> = {
  progress: { bg: "bg-blue-500/10 border-blue-500/25", text: "text-blue-400", icon: Footprints },
  tool: { bg: "bg-amber-500/10 border-amber-500/25", text: "text-amber-400", icon: Cog },
  diff: { bg: "bg-emerald-500/10 border-emerald-500/25", text: "text-emerald-400", icon: FileCode },
  tokens: { bg: "bg-teal-500/10 border-teal-500/25", text: "text-teal-400", icon: DollarSign },
  thinking: { bg: "bg-purple-500/10 border-purple-500/25", text: "text-purple-400", icon: Brain },
  error: { bg: "bg-red-500/10 border-red-500/25", text: "text-red-400", icon: AlertTriangle },
  plan: { bg: "bg-indigo-500/10 border-indigo-500/25", text: "text-indigo-400", icon: Lightbulb },
  other: { bg: "bg-muted/30 border-border/50", text: "text-muted-foreground", icon: Activity },
};

function categorize(event: string): EventCategory {
  if (event.includes("error") || event.includes("fail")) return "error";
  if (event.includes("plan")) return "plan";
  if (event.includes("diff")) return "diff";
  if (event.includes("token")) return "tokens";
  if (event.includes("think")) return "thinking";
  if (event.includes("tool")) return "tool";
  if (event.includes("progress") || event.includes("step")) return "progress";
  return "other";
}

function formatTs(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return "";
  }
}

function summarize(event: string, payload: Record<string, unknown>): string {
  const cat = categorize(event);
  switch (cat) {
    case "progress": {
      const step = payload.step as number | undefined;
      const max = payload.maxSteps as number | undefined;
      const action = payload.action as string | undefined;
      const parts: string[] = [];
      if (step != null && max != null) parts.push(`Step ${step}/${max}`);
      if (action) parts.push(action);
      return parts.join(" — ") || event;
    }
    case "tool": {
      const action = (payload.action ?? payload.tool ?? payload.name ?? "") as string;
      const status = payload.status as string | undefined;
      return [action, status].filter(Boolean).join(" — ") || event;
    }
    case "diff": {
      const diff = payload.diff as string | undefined;
      if (!diff) return event;
      const lines = diff.split("\n");
      const adds = lines.filter((l) => l.startsWith("+") && !l.startsWith("+++")).length;
      const dels = lines.filter((l) => l.startsWith("-") && !l.startsWith("---")).length;
      return `+${adds} -${dels} lines`;
    }
    case "tokens": {
      const total = payload.total_tokens as number | undefined;
      const cost = payload.cost_usd as number | undefined;
      const parts: string[] = [];
      if (total != null) parts.push(`${total.toLocaleString()} tokens`);
      if (cost != null && cost > 0) parts.push(`$${cost.toFixed(4)}`);
      return parts.join(" · ") || event;
    }
    case "thinking": {
      const text = (payload.thinking ?? payload.text ?? "") as string;
      return text.length > 80 ? `${text.slice(0, 80)}…` : text || event;
    }
    case "error": {
      const msg = (payload.message ?? payload.error ?? "") as string;
      return msg.length > 80 ? `${msg.slice(0, 80)}…` : msg || event;
    }
    case "plan": {
      const steps = payload.steps as string[] | undefined;
      return steps ? `${steps.length} steps` : event;
    }
    default:
      return event;
  }
}

/* ------------------------------------------------------------------ */
/*  Diff viewer (inline)                                              */
/* ------------------------------------------------------------------ */
function InlineDiff({ diff }: { diff: string }) {
  const lines = diff.split("\n");
  return (
    <pre className="mt-1 overflow-x-auto font-mono text-[11px] leading-relaxed max-h-48 overflow-y-auto">
      {lines.map((line, i) => {
        let color = "text-muted-foreground";
        if (line.startsWith("+")) color = "text-emerald-500";
        else if (line.startsWith("-")) color = "text-red-500";
        else if (line.startsWith("@@")) color = "text-blue-400";
        return (
          <div key={i} className={color}>
            {line}
          </div>
        );
      })}
    </pre>
  );
}

/* ------------------------------------------------------------------ */
/*  Single event row                                                  */
/* ------------------------------------------------------------------ */

function EventRow({ item }: { item: UiActivity }) {
  const [expanded, setExpanded] = useState(false);
  const cat = categorize(item.event);
  const style = CATEGORY_STYLES[cat];
  const Icon = style.icon;
  const diff = cat === "diff" ? (item.payload.diff as string | undefined) : undefined;
  const summaryText = summarize(item.event, item.payload);

  return (
    <div className={`rounded-md border ${style.bg} text-xs animate-slide-up`}>
      <button
        type="button"
        onClick={() => setExpanded((o) => !o)}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left hover:brightness-110 transition-all"
      >
        <Icon className={`h-3 w-3 shrink-0 ${style.text}`} />
        <Badge variant="outline" className={`text-[9px] px-1 py-0 shrink-0 ${style.text}`}>
          {item.event.replace("agent.", "").replace("step.", "")}
        </Badge>
        <span className="flex-1 truncate text-muted-foreground" title={summaryText}>{summaryText}</span>
        <span className="shrink-0 text-[10px] text-muted-foreground/60 tabular-nums">
          <Clock className="mr-0.5 inline h-2.5 w-2.5" />
          {formatTs(item.timestamp)}
        </span>
        {expanded ? <ChevronDown className="h-3 w-3 shrink-0" /> : <ChevronRight className="h-3 w-3 shrink-0" />}
      </button>
      {expanded && (
        <div className="border-t border-border/40 px-2.5 py-2 space-y-1">
          {diff && <InlineDiff diff={diff} />}
          <JsonBlock data={item.payload} maxHeight="max-h-48" />
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Summary bar (sticky header with cost / step / tokens)             */
/* ------------------------------------------------------------------ */
function SummaryBar({ activity }: { activity: UiActivity[] }) {
  const stepProgress = activity.find((item) => item.event === "agent.step.progress");
  const tokens = activity.find((item) => item.event === "agent.tokens");
  const step = stepProgress?.payload?.step as number | undefined;
  const maxSteps = stepProgress?.payload?.maxSteps as number | undefined;
  const totalTokens = tokens?.payload?.total_tokens as number | undefined;
  const costUsd = tokens?.payload?.cost_usd as number | undefined;

  if (!step && !totalTokens) return null;

  return (
    <div className="flex items-center gap-3 px-2.5 py-1.5 text-[11px] text-muted-foreground border-b border-border/40">
      {step != null && maxSteps != null && (
        <span className="font-medium">
          Step {step}/{maxSteps}
        </span>
      )}
      <span className="flex-1" />
      {costUsd != null && costUsd > 0 && (
        <Badge variant="secondary" className="text-[10px] px-1.5 py-0 text-emerald-500">
          ${costUsd.toFixed(4)}
        </Badge>
      )}
      {totalTokens != null && <span className="tabular-nums">{totalTokens.toLocaleString()} tok</span>}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Filter chip bar                                                   */
/* ------------------------------------------------------------------ */

const FILTER_OPTIONS: { label: string; value: EventCategory | "all" }[] = [
  { label: "All", value: "all" },
  { label: "Progress", value: "progress" },
  { label: "Tools", value: "tool" },
  { label: "Diffs", value: "diff" },
  { label: "Tokens", value: "tokens" },
  { label: "Thinking", value: "thinking" },
  { label: "Errors", value: "error" },
  { label: "Plan", value: "plan" },
];

/* ------------------------------------------------------------------ */
/*  Public component                                                  */
/* ------------------------------------------------------------------ */

interface ActivityTimelineProps {
  activity: UiActivity[];
  /** Show filter chips */
  showFilters?: boolean;
  /** Show the compact summary bar at top */
  showSummary?: boolean;
  /** If true, auto-scrolls to bottom on new events */
  autoScroll?: boolean;
  /** CSS class override for the wrapper */
  className?: string;
  /** Max height class (default is h-52 for inline, h-full for drawer) */
  heightClass?: string;
}

export function ActivityTimeline({
  activity,
  showFilters = false,
  showSummary = true,
  autoScroll = true,
  className = "",
  heightClass = "h-52",
}: ActivityTimelineProps) {
  const [filter, setFilter] = useState<EventCategory | "all">("all");
  const [collapsed, setCollapsed] = useState(false);
  const endRef = useRef<HTMLDivElement | null>(null);

  // Activity is stored newest-first; display oldest-first (chronological)
  const chronological = useMemo(() => [...activity].reverse(), [activity]);
  const filtered = useMemo(
    () => (filter === "all" ? chronological : chronological.filter((item) => categorize(item.event) === filter)),
    [chronological, filter],
  );

  useEffect(() => {
    if (autoScroll && endRef.current) {
      endRef.current.scrollIntoView({ behavior: "auto" });
    }
  }, [activity.length, autoScroll]);

  if (activity.length === 0) return null;

  return (
    <div className={`rounded-md border border-border/60 bg-muted/20 overflow-hidden ${className}`}>
      {/* Collapsible header */}
      <button
        type="button"
        onClick={() => setCollapsed((c) => !c)}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        {collapsed ? <ChevronRight className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
        <Activity className="h-3 w-3" />
        <span className="font-medium">Activity</span>
        <Badge variant="outline" className="ml-1 text-[10px] px-1 py-0">
          {activity.length}
        </Badge>
        <span className="flex-1" />
      </button>

      {!collapsed && (
        <>
          {showFilters && (
            <div className="flex flex-wrap gap-1 px-2.5 py-1 border-t border-border/40">
              {FILTER_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setFilter(opt.value)}
                  className={`rounded-full border px-2 py-0.5 text-[10px] transition ${
                    filter === opt.value
                      ? "border-primary/40 bg-primary/10 text-foreground"
                      : "border-border/60 text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          )}
          {showSummary && <SummaryBar activity={activity} />}
          <ScrollArea className={heightClass}>
            <div className="space-y-1 p-2">
              {filtered.map((item) => (
                <EventRow key={item.id} item={item} />
              ))}
              <div ref={endRef} />
            </div>
          </ScrollArea>
        </>
      )}
    </div>
  );
}
