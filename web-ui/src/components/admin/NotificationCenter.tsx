import { useMemo, useState } from "react";
import {
  AlertTriangle,
  Bell,
  Bot,
  CheckCheck,
  CheckCircle2,
  ChevronRight,
  Info,
  Trash2,
  Workflow,
  XCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useNotifications, type Notification, type NotificationKind } from "@/contexts/NotificationContext";
import { useWorkspace } from "@/contexts/WorkspaceContext";
import { cn } from "@/lib/utils";
import type { WorkspaceView } from "@/types";

type NotificationFilter = "all" | "unread" | "attention";

function kindIcon(notif: Notification) {
  if (notif.resourceType === "agent") return <Bot className="h-3.5 w-3.5" />;
  if (notif.resourceType === "workflow") return <Workflow className="h-3.5 w-3.5" />;
  return notif.severity === "error"
    ? <AlertTriangle className="h-3.5 w-3.5" />
    : <Info className="h-3.5 w-3.5" />;
}

function statusIcon(notif: Notification) {
  if (notif.statusLabel === "Deleted") return <Trash2 className="h-3 w-3" />;
  if (notif.kind.endsWith(".completed")) return <CheckCircle2 className="h-3 w-3" />;
  if (notif.kind.endsWith(".failed") || notif.kind === "system.error") return <XCircle className="h-3 w-3" />;
  if (notif.kind === "workflow.approval_needed") return <AlertTriangle className="h-3 w-3" />;
  return <Info className="h-3 w-3" />;
}

function severityClasses(severity: Notification["severity"]): { shell: string; icon: string; badge: string; meta: string } {
  switch (severity) {
    case "success":
      return {
        shell: "border-emerald-500/20 bg-emerald-500/6",
        icon: "bg-emerald-500/12 text-emerald-600 dark:text-emerald-300",
        badge: "border-emerald-500/20 bg-emerald-500/10 text-emerald-700 dark:text-emerald-200",
        meta: "text-emerald-700 dark:text-emerald-200",
      };
    case "error":
      return {
        shell: "border-red-500/20 bg-red-500/6",
        icon: "bg-red-500/12 text-red-600 dark:text-red-300",
        badge: "border-red-500/20 bg-red-500/10 text-red-700 dark:text-red-200",
        meta: "text-red-700 dark:text-red-200",
      };
    case "warning":
      return {
        shell: "border-amber-500/20 bg-amber-500/6",
        icon: "bg-amber-500/12 text-amber-700 dark:text-amber-200",
        badge: "border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-200",
        meta: "text-amber-700 dark:text-amber-200",
      };
    default:
      return {
        shell: "border-border/60 bg-background/70",
        icon: "bg-muted text-muted-foreground",
        badge: "border-border/60 bg-muted/60 text-muted-foreground",
        meta: "text-muted-foreground",
      };
  }
}

function relativeTime(ts: string): string {
  const parsed = new Date(ts).getTime();
  if (!Number.isFinite(parsed)) return "now";
  const diff = Math.max(0, Date.now() - parsed);
  const secs = Math.floor(diff / 1000);
  if (secs < 60) return "just now";
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function targetViewForNotification(kind: NotificationKind): WorkspaceView | null {
  if (kind.startsWith("agent.")) return "agents";
  if (kind.startsWith("workflow.")) return "workflows";
  return null;
}

function NotificationItem({
  notif,
  onNavigate,
}: {
  notif: Notification;
  onNavigate: (notif: Notification) => void;
}) {
  const targetView = targetViewForNotification(notif.kind);
  const tones = severityClasses(notif.severity);
  const ariaLabel = targetView && notif.name
    ? `Open ${notif.name} in ${targetView}`
    : `Mark notification ${notif.title} as read`;

  return (
    <button
      type="button"
      className={cn(
        "group flex w-full items-start gap-3 rounded-xl border px-3 py-3 text-left transition-all hover:border-border hover:bg-accent/40",
        tones.shell,
        notif.read ? "opacity-80" : "shadow-sm",
      )}
      aria-label={ariaLabel}
      onClick={() => onNavigate(notif)}
    >
      <span className={cn("mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg", tones.icon)}>
        {kindIcon(notif)}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className={cn("truncate text-sm", notif.read ? "text-foreground/80" : "font-semibold text-foreground")}>
                {notif.title}
              </span>
              {!notif.read && <span className="h-2 w-2 shrink-0 rounded-full bg-primary" />}
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              {notif.name ? <Badge variant="outline" className="max-w-[11rem] truncate">{notif.name}</Badge> : null}
              <span className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium", tones.badge)}>
                {statusIcon(notif)}
                {notif.statusLabel}
              </span>
            </div>
          </div>
          <span className="whitespace-nowrap text-[11px] text-muted-foreground">
            {relativeTime(notif.timestamp)}
          </span>
        </div>
        <p className="mt-2 line-clamp-2 text-[12px] leading-5 text-muted-foreground">
          {notif.description}
        </p>
        <div className="mt-2 flex items-center justify-between gap-2">
          <span className={cn("text-[11px]", tones.meta)}>
            Namespace: {notif.namespace}
          </span>
          {targetView && notif.name ? (
            <span className="inline-flex items-center gap-1 text-[11px] font-medium text-foreground/75 transition-colors group-hover:text-foreground">
              Open {targetView}
              <ChevronRight className="h-3.5 w-3.5" />
            </span>
          ) : null}
        </div>
      </div>
    </button>
  );
}

export function NotificationCenter() {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState<NotificationFilter>("all");
  const { notifications, unreadCount, markRead, markAllRead, clearAll } = useNotifications();
  const ws = useWorkspace();

  const attentionCount = useMemo(
    () => notifications.filter((notif) => notif.severity === "error" || notif.severity === "warning").length,
    [notifications],
  );

  const visibleNotifications = useMemo(() => {
    if (filter === "unread") return notifications.filter((notif) => !notif.read);
    if (filter === "attention") {
      return notifications.filter((notif) => notif.severity === "error" || notif.severity === "warning");
    }
    return notifications;
  }, [filter, notifications]);

  const handleNotificationClick = (notif: Notification) => {
    markRead(notif.id);
    const targetView = targetViewForNotification(notif.kind);
    if (targetView && notif.name) {
      ws.navigateToResource(targetView, notif.name);
      setOpen(false);
    }
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" size="icon" className="relative h-7 w-7 border-border/60 text-foreground hover:bg-accent" aria-label="Notifications">
          <Bell className="h-3.5 w-3.5" />
          {unreadCount > 0 && (
            <span className="absolute -top-1 -right-1 flex h-3.5 min-w-[0.875rem] items-center justify-center rounded-full bg-primary text-[9px] font-bold text-primary-foreground px-0.5">
              {unreadCount > 99 ? "99+" : unreadCount}
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[26rem] p-0" sideOffset={8}>
        <div className="border-b border-border/60 px-4 py-3">
          <div className="flex items-start justify-between gap-3">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-foreground">Notifications</span>
                {unreadCount > 0 ? <Badge>{unreadCount} new</Badge> : null}
                {attentionCount > 0 ? <Badge variant="destructive">{attentionCount} attention</Badge> : null}
              </div>
              <p className="text-[11px] leading-5 text-muted-foreground">
                Live agent, workflow, and platform updates for the active namespace.
              </p>
            </div>
            <div className="flex items-center gap-1">
              {unreadCount > 0 ? (
                <Button variant="ghost" size="sm" className="h-7 px-2 text-[11px]" onClick={markAllRead}>
                  <CheckCheck className="mr-1 h-3.5 w-3.5" />
                  Read all
                </Button>
              ) : null}
              {notifications.length > 0 ? (
                <Button variant="ghost" size="sm" className="h-7 px-2 text-[11px] text-muted-foreground" onClick={clearAll}>
                  <Trash2 className="mr-1 h-3.5 w-3.5" />
                  Clear
                </Button>
              ) : null}
            </div>
          </div>

          <Tabs value={filter} onValueChange={(value) => setFilter(value as NotificationFilter)} className="mt-3">
            <TabsList className="grid h-8 w-full grid-cols-3">
              <TabsTrigger value="all" className="text-xs">All {notifications.length}</TabsTrigger>
              <TabsTrigger value="unread" className="text-xs">Unread {unreadCount}</TabsTrigger>
              <TabsTrigger value="attention" className="text-xs">Attention {attentionCount}</TabsTrigger>
            </TabsList>
          </Tabs>
        </div>

        <ScrollArea className="max-h-[28rem]">
          {visibleNotifications.length === 0 ? (
            <div className="px-4 py-10 text-center">
              <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-2xl bg-muted text-muted-foreground">
                <Bell className="h-5 w-5" />
              </div>
              <p className="mt-3 text-sm font-medium text-foreground">
                {filter === "all"
                  ? "No notifications yet"
                  : filter === "unread"
                    ? "Nothing unread right now"
                    : "No attention items right now"}
              </p>
              <p className="mt-1 text-[12px] leading-5 text-muted-foreground">
                {filter === "all"
                  ? "This feed will populate as agents, workflows, and system events arrive."
                  : filter === "unread"
                    ? "New items will appear here until you open or mark them as read."
                    : "Warnings and errors will stay grouped here for quick triage."}
              </p>
            </div>
          ) : (
            <div className="space-y-2 p-3">
              {visibleNotifications.map((n) => (
                <NotificationItem key={n.id} notif={n} onNavigate={handleNotificationClick} />
              ))}
            </div>
          )}
        </ScrollArea>
      </PopoverContent>
    </Popover>
  );
}
