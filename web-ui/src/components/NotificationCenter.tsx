import { useState } from "react";
import { Bell, CheckCheck, Trash2, Workflow, Bot, FlaskConical, AlertTriangle, Info, CheckCircle2, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useNotifications, type Notification, type NotificationKind } from "@/contexts/NotificationContext";
import { useWorkspace } from "@/contexts/WorkspaceContext";
import type { WorkspaceView } from "@/types";

function kindIcon(kind: NotificationKind) {
  if (kind.startsWith("agent.")) return <Bot className="h-3.5 w-3.5 text-primary" />;
  if (kind.startsWith("workflow.")) return <Workflow className="h-3.5 w-3.5 text-blue-400" />;
  if (kind.startsWith("eval.")) return <FlaskConical className="h-3.5 w-3.5 text-violet-400" />;
  return <Info className="h-3.5 w-3.5 text-muted-foreground" />;
}

function phaseIcon(kind: NotificationKind) {
  if (kind.endsWith(".completed")) return <CheckCircle2 className="h-3 w-3 text-emerald-400" />;
  if (kind.endsWith(".failed") || kind === "system.error") return <XCircle className="h-3 w-3 text-red-400" />;
  if (kind === "workflow.approval_needed") return <AlertTriangle className="h-3 w-3 text-amber-400" />;
  return null;
}

function relativeTime(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime();
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
  if (kind.startsWith("eval.")) return "evals";
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
  const ariaLabel = targetView && notif.name
    ? `Open ${notif.name} in ${targetView}`
    : `Mark notification for ${notif.name || "system"} as read`;

  return (
    <button
      type="button"
      className={`flex w-full items-start gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-accent ${notif.read ? "opacity-60" : ""}`}
      aria-label={ariaLabel}
      onClick={() => onNavigate(notif)}
    >
      <span className="mt-0.5 flex-shrink-0">{kindIcon(notif.kind)}</span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          {phaseIcon(notif.kind)}
          <span className={`text-xs truncate ${notif.read ? "text-muted-foreground" : "text-foreground font-medium"}`}>
            {notif.name || "system"}
          </span>
        </div>
        <p className="text-[11px] text-muted-foreground truncate">
          {notif.previousPhase && notif.previousPhase !== notif.phase
            ? `${notif.previousPhase} → ${notif.phase}`
            : notif.phase}
        </p>
      </div>
      <span className="text-[10px] text-muted-foreground whitespace-nowrap mt-0.5">
        {relativeTime(notif.timestamp)}
      </span>
      {!notif.read && <span className="mt-1.5 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-primary" />}
    </button>
  );
}

export function NotificationCenter() {
  const [open, setOpen] = useState(false);
  const { notifications, unreadCount, markRead, markAllRead, clearAll } = useNotifications();
  const ws = useWorkspace();

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
        <Button variant="outline" size="icon" className="relative h-8 w-8 border-border/60 text-foreground hover:bg-accent" aria-label="Notifications">
          <Bell className="h-4 w-4" />
          {unreadCount > 0 && (
            <span className="absolute -top-1 -right-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary text-[10px] font-bold text-primary-foreground px-1">
              {unreadCount > 99 ? "99+" : unreadCount}
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-0" sideOffset={6}>
        <div className="flex items-center justify-between border-b border-border/50 px-3 py-2">
          <span className="text-xs font-semibold text-foreground">Notifications</span>
          <div className="flex items-center gap-1">
            {unreadCount > 0 && (
              <Button variant="ghost" size="sm" className="h-6 px-1.5 text-[11px]" onClick={markAllRead}>
                <CheckCheck className="mr-1 h-3 w-3" /> Read all here
              </Button>
            )}
            {notifications.length > 0 && (
              <Button variant="ghost" size="sm" className="h-6 px-1.5 text-[11px] text-muted-foreground" onClick={clearAll}>
                <Trash2 className="mr-1 h-3 w-3" /> Clear feed
              </Button>
            )}
          </div>
        </div>

        <ScrollArea className="max-h-72">
          {notifications.length === 0 ? (
            <p className="px-3 py-6 text-center text-xs text-muted-foreground">No notifications yet in this session.</p>
          ) : (
            <div className="p-1">
              {notifications.map((n) => (
                <NotificationItem key={n.id} notif={n} onNavigate={handleNotificationClick} />
              ))}
            </div>
          )}
        </ScrollArea>
      </PopoverContent>
    </Popover>
  );
}
