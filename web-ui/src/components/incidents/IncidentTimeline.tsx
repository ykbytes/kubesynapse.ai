import {
  Activity,
  AlertTriangle,
  ArrowUpCircle,
  CheckCircle2,
  Circle,
  Clock,
  StickyNote,
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
  diagnosing: Activity,
  remediated: CheckCircle2,
  resolved: CheckCircle2,
  closed: XCircle,
  escalated: ArrowUpCircle,
  note: StickyNote,
};

const EVENT_TONES: Record<EventKind, string> = {
  firing: "border-destructive/40 bg-destructive/12 text-destructive",
  acknowledged: "border-info/40 bg-info/12 text-info-foreground",
  diagnosing: "border-warning/40 bg-warning/12 text-warning-foreground",
  remediated: "border-success/40 bg-success/12 text-success-foreground",
  resolved: "border-success/40 bg-success/12 text-success-foreground",
  closed: "border-border/70 bg-secondary/80 text-muted-foreground",
  escalated: "border-warning/40 bg-warning/15 text-warning-foreground",
  note: "border-border/70 bg-secondary/82 text-foreground/85",
};

const DEFAULT_TONE = "border-border/70 bg-secondary/82 text-muted-foreground";

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
      <div className="flex items-center gap-2 rounded-lg border border-dashed border-border/60 bg-secondary/40 p-4 text-sm text-muted-foreground">
        <Clock className="h-4 w-4" />
        No timeline events yet — updates will appear here as the incident evolves.
      </div>
    );
  }

  return (
    <ol className="relative space-y-0" role="list" aria-label="Incident timeline">
      <span
        aria-hidden="true"
        className="absolute left-[15px] top-2 bottom-2 w-px bg-gradient-to-b from-border/70 via-border/40 to-transparent"
      />
      {events.map((event, i) => {
        const kind = (event.event in EVENT_ICONS ? event.event : "note") as EventKind;
        const Icon = EVENT_ICONS[kind] ?? Clock;
        const tone = EVENT_TONES[kind] ?? DEFAULT_TONE;
        const isLast = i === events.length - 1;
        return (
          <li
            key={i}
            className={cn(
              "relative flex gap-3 pb-4 last:pb-0 animate-slide-up",
            )}
            style={{ animationDelay: `${i * 30}ms` }}
          >
            <span
              className={cn(
                "relative z-10 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full border shadow-inner",
                tone,
              )}
              aria-hidden="true"
            >
              <Icon className="h-3.5 w-3.5" />
            </span>
            <div className="min-w-0 flex-1 pt-0.5">
              <div className="flex flex-wrap items-baseline gap-x-2">
                <span className="text-sm font-medium text-foreground">{event.message}</span>
                <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
                  {event.event}
                </span>
              </div>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {formatTimestamp(event.timestamp)}
                {relativeFromNow(event.timestamp) && (
                  <span className="ml-1.5 text-muted-foreground/70">({relativeFromNow(event.timestamp)})</span>
                )}
              </p>
            </div>
            {!isLast && <span className="sr-only">Older event</span>}
          </li>
        );
      })}
    </ol>
  );
}
