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

export type NotificationSeverity = "success" | "error" | "warning" | "info";
export type NotificationResourceType = "agent" | "workflow" | "eval" | "system";

interface NotificationPayload {
  kind?: NotificationKind | string;
  name?: string;
  namespace?: string;
  phase?: string;
  previousPhase?: string;
  timestamp?: string;
  message?: string;
  summary?: string;
  detail?: string;
}

export interface Notification {
  id: string;
  kind: NotificationKind;
  resourceType: NotificationResourceType;
  severity: NotificationSeverity;
  name: string;
  namespace: string;
  phase: string;
  previousPhase?: string;
  timestamp: string;
  title: string;
  description: string;
  statusLabel: string;
  fingerprint: string;
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

const MAX_NOTIFICATIONS = 100;
const NOTIFICATION_STORAGE_PREFIX = "kubesynapse.notifications";

let _notifId = 0;
function nextId(): string {
  return `notif-${++_notifId}-${Date.now()}`;
}

function normalizeKind(kind: string | undefined): NotificationKind {
  switch (kind) {
    case "agent.status_changed":
    case "workflow.completed":
    case "workflow.failed":
    case "workflow.approval_needed":
    case "workflow.status_changed":
    case "eval.completed":
    case "eval.failed":
    case "eval.status_changed":
    case "system.error":
      return kind;
    default:
      return "system.error";
  }
}

function phaseLabel(rawPhase: string): string {
  const phase = rawPhase.trim().toLowerCase();
  if (!phase) return "Update";
  if (phase === "waitingapproval" || phase === "waiting_approval" || phase === "waiting-approval") {
    return "Waiting for approval";
  }
  if (phase === "succeeded") return "Completed";
  if (phase === "failed") return "Failed";
  if (phase === "deleted") return "Deleted";
  if (phase === "unknown") return "Status unavailable";
  return phase
    .split(/[\s_-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function resourceTypeForKind(kind: NotificationKind): NotificationResourceType {
  if (kind.startsWith("agent.")) return "agent";
  if (kind.startsWith("workflow.")) return "workflow";
  if (kind.startsWith("eval.")) return "eval";
  return "system";
}

function resourceLabel(type: NotificationResourceType): string {
  switch (type) {
    case "agent":
      return "Agent";
    case "workflow":
      return "Workflow";
    case "eval":
      return "Eval";
    default:
      return "System";
  }
}

function toastKind(kind: NotificationKind): NotificationSeverity {
  if (kind.endsWith(".completed")) return "success";
  if (kind.endsWith(".failed") || kind === "system.error") return "error";
  if (kind === "workflow.approval_needed") return "warning";
  return "info";
}

function notificationStorageKey(namespace: string): string {
  return `${NOTIFICATION_STORAGE_PREFIX}:${namespace}`;
}

function buildTitle(kind: NotificationKind, resourceType: NotificationResourceType, name: string, statusLabel: string): string {
  const label = resourceLabel(resourceType);
  switch (kind) {
    case "workflow.completed":
      return `${label} completed`;
    case "workflow.failed":
      return `${label} failed`;
    case "workflow.approval_needed":
      return `${label} needs approval`;
    case "eval.completed":
      return `${label} completed`;
    case "eval.failed":
      return `${label} failed`;
    case "system.error":
      return "System error";
    default:
      if (statusLabel === "Deleted") return `${label} deleted`;
      return name ? `${label} status updated` : `${label} update`;
  }
}

function buildDescription(
  kind: NotificationKind,
  resourceType: NotificationResourceType,
  name: string,
  statusLabel: string,
  previousStatusLabel: string | null,
  payload: NotificationPayload,
): string {
  const label = resourceLabel(resourceType);
  const safeName = name || label;
  const message = String(payload.message || payload.summary || payload.detail || "").trim();

  if (kind === "system.error") {
    return message || "The notification stream reported an unexpected platform error.";
  }
  if (kind === "workflow.approval_needed") {
    return `${safeName} is waiting for human approval before execution can continue.`;
  }
  if (statusLabel === "Deleted") {
    return previousStatusLabel
      ? `${safeName} was removed after previously being ${previousStatusLabel.toLowerCase()}.`
      : `${safeName} was removed from the current namespace.`;
  }
  if (previousStatusLabel && previousStatusLabel !== statusLabel) {
    return `${safeName} changed from ${previousStatusLabel.toLowerCase()} to ${statusLabel.toLowerCase()}.`;
  }
  if (message) {
    return message;
  }
  return `${safeName} is currently ${statusLabel.toLowerCase()}.`;
}

function notificationFingerprint(kind: NotificationKind, payload: NotificationPayload, statusLabel: string): string {
  return JSON.stringify({
    kind,
    name: payload.name || "",
    namespace: payload.namespace || "",
    phase: payload.phase || "",
    previousPhase: payload.previousPhase || "",
    statusLabel,
    message: payload.message || payload.summary || payload.detail || "",
    timestamp: payload.timestamp || "",
  });
}

function normalizeNotification(payload: NotificationPayload, fallbackKind: string | undefined, namespace: string): Notification {
  const kind = normalizeKind(String(payload.kind || fallbackKind || "system.error"));
  const resourceType = resourceTypeForKind(kind);
  const severity = toastKind(kind);
  const currentStatusLabel = phaseLabel(String(payload.phase || ""));
  const previousStatusLabel = payload.previousPhase ? phaseLabel(String(payload.previousPhase)) : null;
  const name = String(payload.name || "").trim();
  const title = buildTitle(kind, resourceType, name, currentStatusLabel);
  const description = buildDescription(kind, resourceType, name, currentStatusLabel, previousStatusLabel, payload);
  const fingerprint = notificationFingerprint(kind, payload, currentStatusLabel);

  return {
    id: nextId(),
    kind,
    resourceType,
    severity,
    name,
    namespace: String(payload.namespace || namespace || "default"),
    phase: String(payload.phase || "").trim().toLowerCase(),
    previousPhase: payload.previousPhase ? String(payload.previousPhase).trim().toLowerCase() : undefined,
    timestamp: String(payload.timestamp || new Date().toISOString()),
    title,
    description,
    statusLabel: currentStatusLabel,
    fingerprint,
    read: false,
  };
}

function isNotification(value: unknown): value is Notification {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<Notification>;
  return typeof candidate.id === "string"
    && typeof candidate.kind === "string"
    && typeof candidate.timestamp === "string"
    && typeof candidate.title === "string"
    && typeof candidate.description === "string"
    && typeof candidate.statusLabel === "string"
    && typeof candidate.read === "boolean";
}

function loadStoredNotifications(namespace: string): Notification[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(notificationStorageKey(namespace));
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isNotification).slice(0, MAX_NOTIFICATIONS);
  } catch {
    return [];
  }
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
  const [notifications, setNotifications] = useState<Notification[]>(() => loadStoredNotifications(namespace));
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    setNotifications(loadStoredNotifications(namespace));
  }, [namespace]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      window.localStorage.setItem(
        notificationStorageKey(namespace),
        JSON.stringify(notifications.slice(0, MAX_NOTIFICATIONS)),
      );
    } catch {
      // Ignore storage errors; notifications still work in-memory.
    }
  }, [namespace, notifications]);

  // Connect / reconnect SSE
  useEffect(() => {
    if (!token.trim()) return;

    const es = createNotificationStream(token, namespace);
    esRef.current = es;

    function handleEvent(e: MessageEvent) {
      try {
        const data = JSON.parse(e.data) as NotificationPayload;
        const notif = normalizeNotification(data, e.type, namespace);

        setNotifications((prev) => {
          if (prev.some((item) => item.fingerprint === notif.fingerprint)) {
            return prev;
          }
          return [notif, ...prev].slice(0, MAX_NOTIFICATIONS);
        });

        // Show toast
        const variant = notif.severity;
        toast[variant](notif.title, {
          description: notif.description,
        });
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
