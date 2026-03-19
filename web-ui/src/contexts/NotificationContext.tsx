import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createNotificationStream } from "@/lib/api";
import { toast } from "sonner";

// ── Types ──

export type NotificationKind =
  | "agent.status_changed"
  | "workflow.completed"
  | "workflow.failed"
  | "workflow.approval_needed"
  | "workflow.status_changed"
  | "eval.completed"
  | "eval.failed"
  | "eval.status_changed"
  | "system.error";

export interface Notification {
  id: string;
  kind: NotificationKind;
  name: string;
  namespace: string;
  phase: string;
  previousPhase?: string;
  timestamp: string;
  read: boolean;
}

export interface NotificationContextValue {
  notifications: Notification[];
  unreadCount: number;
  markRead: (id: string) => void;
  markAllRead: () => void;
  clearAll: () => void;
}

const NotificationContext = createContext<NotificationContextValue | null>(null);

const MAX_NOTIFICATIONS = 50;

let _notifId = 0;
function nextId(): string {
  return `notif-${++_notifId}-${Date.now()}`;
}

function toastLabel(kind: NotificationKind, name: string, phase: string): string {
  switch (kind) {
    case "agent.status_changed":
      return `Agent "${name}" → ${phase}`;
    case "workflow.completed":
      return `Workflow "${name}" completed`;
    case "workflow.failed":
      return `Workflow "${name}" failed`;
    case "workflow.approval_needed":
      return `Workflow "${name}" needs approval`;
    case "workflow.status_changed":
      return `Workflow "${name}" → ${phase}`;
    case "eval.completed":
      return `Eval "${name}" completed`;
    case "eval.failed":
      return `Eval "${name}" failed`;
    case "eval.status_changed":
      return `Eval "${name}" → ${phase}`;
    case "system.error":
      return `System error`;
    default:
      return `${name} → ${phase}`;
  }
}

function toastKind(kind: NotificationKind): "success" | "error" | "warning" | "info" {
  if (kind.endsWith(".completed")) return "success";
  if (kind.endsWith(".failed") || kind === "system.error") return "error";
  if (kind === "workflow.approval_needed") return "warning";
  return "info";
}

// ── Provider ──

export function NotificationProvider({
  token,
  namespace,
  children,
}: {
  token: string;
  namespace: string;
  children: ReactNode;
}) {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const esRef = useRef<EventSource | null>(null);

  // Connect / reconnect SSE
  useEffect(() => {
    if (!token.trim()) return;

    const es = createNotificationStream(token, namespace);
    esRef.current = es;

    function handleEvent(e: MessageEvent) {
      try {
        const data = JSON.parse(e.data);
        const kind = (data.kind ?? e.type ?? "system.error") as NotificationKind;
        const notif: Notification = {
          id: nextId(),
          kind,
          name: data.name ?? "",
          namespace: data.namespace ?? namespace,
          phase: data.phase ?? "",
          previousPhase: data.previousPhase,
          timestamp: data.timestamp ?? new Date().toISOString(),
          read: false,
        };

        setNotifications((prev) => [notif, ...prev].slice(0, MAX_NOTIFICATIONS));

        // Show toast
        const label = toastLabel(kind, notif.name, notif.phase);
        const variant = toastKind(kind);
        toast[variant](label);
      } catch {
        // Ignore unparseable frames (e.g. keepalive comments)
      }
    }

    // Listen to all known event types from the server
    const eventTypes = [
      "agent.status_changed",
      "workflow.completed",
      "workflow.failed",
      "workflow.approval_needed",
      "workflow.status_changed",
      "eval.completed",
      "eval.failed",
      "eval.status_changed",
      "system.error",
    ];
    for (const t of eventTypes) {
      es.addEventListener(t, handleEvent);
    }
    // Also handle generic/unnamed events
    es.onmessage = handleEvent;

    es.onerror = () => {
      // EventSource auto-reconnects; no action needed
    };

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [token, namespace]);

  const markRead = useCallback((id: string) => {
    setNotifications((prev) =>
      prev.map((n) => (n.id === id ? { ...n, read: true } : n)),
    );
  }, []);

  const markAllRead = useCallback(() => {
    setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
  }, []);

  const clearAll = useCallback(() => {
    setNotifications([]);
  }, []);

  const unreadCount = useMemo(
    () => notifications.filter((n) => !n.read).length,
    [notifications],
  );

  const value = useMemo<NotificationContextValue>(
    () => ({ notifications, unreadCount, markRead, markAllRead, clearAll }),
    [notifications, unreadCount, markRead, markAllRead, clearAll],
  );

  return (
    <NotificationContext.Provider value={value}>
      {children}
    </NotificationContext.Provider>
  );
}

export function useNotifications(): NotificationContextValue {
  const ctx = useContext(NotificationContext);
  if (!ctx) throw new Error("useNotifications must be used within NotificationProvider");
  return ctx;
}
