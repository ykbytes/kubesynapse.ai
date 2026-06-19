import {
  AlertTriangle,
  ArrowUpCircle,
  CheckCircle2,
  Circle,
  Clock,
  Sparkles,
  XCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface TimelineEvent {
  timestamp: string;
  event: string;
  message: string;
}

type EventKind =
  | "firing"
  | "acknowledged"
  | "diagnosing"
  | "remediated"
  | "resolved"
  | "closed"
  | "escalated"
  | "note";

const EVENT_ICONS: Record<EventKind, typeof Circle> = {
  firing: AlertTriangle,
  acknowledged: Circle,
  diagnosing: Sparkles,
  remediated: CheckCircle2,
  resolved: CheckCircle2,
  closed: XCircle,
  escalated: ArrowUpCircle,
  note: Circle,
};

const EVENT_DOT_COLORS: Record<EventKind, string> = {
  firing: "bg-red-500/80",
  acknowledged: "bg-sky-500/80",
  diagnosing: "bg-amber-500/80",
  remediated: "bg-emerald-500/80",
  resolved: "bg-emerald-500/80",
  closed: "bg-slate-400",
  escalated: "bg-amber-500/80",
  note: "bg-slate-400",
};

function formatTimestamp(ts: string): string {
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

function relativeFromNow(ts: string): string {
  try {
    const diff = Date.now() - new Date(ts).getTime();
    if (diff < 0) return "just now";
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
  } catch {
    return "";
  }
}

interface IncidentTimelineProps {
  events: TimelineEvent[];
}

export function IncidentTimeline({ events }: IncidentTimelineProps) {
  if (!events || events.length === 0) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-dashed border-border/40 py-6 text-sm text-muted-foreground/50">
        <Clock className="size-4" />
        No timeline events yet.
      </div>
    );
  }

  return (
    <ol className="relative" role="list" aria-label="Incident timeline">
      {/* Spine line */}
      <span
        aria-hidden="true"
        className="absolute left-[7px] top-3 bottom-3 w-px bg-border/30"
      />

      {events.map((event, i) => {
        const kind = (event.event in EVENT_ICONS ? event.event : "note") as EventKind;
        const Icon = EVENT_ICONS[kind] ?? Clock;
        const dotColor = EVENT_DOT_COLORS[kind] ?? "bg-slate-400";
        const isLast = i === events.length - 1;

        return (
          <li
            key={i}
            className={cn("relative flex gap-3", !isLast && "pb-5")}
          >
            {/* Dot */}
            <span
              className={cn(
                "relative z-10 mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full ring-4 ring-background",
                dotColor,
              )}
              aria-hidden="true"
            >
              <Icon className="size-2.5 text-background" />
            </span>

            {/* Content */}
            <div className="min-w-0 flex-1 pt-0.5">
              <p className="text-sm text-foreground">{event.message}</p>
              <div className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground/50">
                <span className="font-medium uppercase tracking-wide">{event.event}</span>
                <span>·</span>
                <span>{formatTimestamp(event.timestamp)}</span>
                <span className="text-muted-foreground/40">({relativeFromNow(event.timestamp)})</span>
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
