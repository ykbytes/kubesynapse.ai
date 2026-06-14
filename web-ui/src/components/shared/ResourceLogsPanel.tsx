import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Circle,
  Copy,
  Download,
  Pause,
  Play,
  ScrollText,
  Search,
  ShieldOff,
  Wifi,
  WifiOff,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";
import {
  apiErrorMessage,
  fetchAgentLogs,
  fetchWorkflowLogs,
  streamAgentLogs,
  streamWorkflowLogs,
} from "@/lib/api";
import type { AgentLogsResponse, WorkflowLogsResponse } from "@/types";

const MAX_BUFFERED_LINES = 5000;
const INITIAL_TAIL = 200;

export type ResourceLogsSource =
  | { kind: "agent"; agentName: string; container?: string }
  | { kind: "workflow"; workflowName: string; runId?: string | null };

export interface ResourceLogsPanelProps {
  token: string;
  namespace: string;
  source: ResourceLogsSource;
  /** Compact metadata strip rendered above the log stream. */
  contextLabel?: string;
  /** When the user lacks the runtime:logs capability, render a non-fatal notice. */
  capabilityMissing?: boolean;
  className?: string;
}

type ConnectionState = "idle" | "loading" | "live" | "paused" | "error" | "denied";

const LEVEL_PATTERNS: { value: "all" | "error" | "warn" | "info" | "debug"; label: string; test: (line: string) => boolean }[] = [
  { value: "all", label: "All", test: () => true },
  {
    value: "error",
    label: "Errors",
    test: (line) => /(?:\bERROR\b|\bFATAL\b|\bCRITICAL\b|Traceback|Exception)/i.test(line),
  },
  {
    value: "warn",
    label: "Warnings",
    test: (line) => /\b(WARN|WARNING)\b/i.test(line),
  },
  {
    value: "info",
    label: "Info",
    test: (line) => /\bINFO\b/i.test(line),
  },
  {
    value: "debug",
    label: "Debug",
    test: (line) => /\bDEBUG\b/i.test(line),
  },
];

function classifyLogLevel(line: string): "error" | "warn" | "info" | "debug" | "other" {
  if (LEVEL_PATTERNS[1].test(line)) return "error";
  if (LEVEL_PATTERNS[2].test(line)) return "warn";
  if (LEVEL_PATTERNS[3].test(line)) return "info";
  if (LEVEL_PATTERNS[4].test(line)) return "debug";
  return "other";
}

function stripLogTimestamp(line: string): string {
  // Kubernetes `read_namespaced_pod_log(..., timestamps=True)` prepends
  // `2026-06-13T12:00:00.000Z `. Strip it for cleaner filtering; keep the
  // original in the rendered output via a separate field if needed later.
  return line.replace(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\s+/, "");
}

export function ResourceLogsPanel(props: ResourceLogsPanelProps) {
  const { token, namespace, source, contextLabel, capabilityMissing, className } = props;

  const [tail, setTail] = useState<number>(INITIAL_TAIL);
  const [level, setLevel] = useState<"all" | "error" | "warn" | "info" | "debug">("all");
  const [query, setQuery] = useState("");
  const [autoscroll, setAutoscroll] = useState(true);
  const [paused, setPaused] = useState(false);
  const [connection, setConnection] = useState<ConnectionState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [podLabel, setPodLabel] = useState<string | null>(null);
  const [lines, setLines] = useState<string[]>([]);
  const [denialMessage, setDenialMessage] = useState<string | null>(null);
  const [lastEventAt, setLastEventAt] = useState<number | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const pausedRef = useRef(false);
  pausedRef.current = paused;
  const pendingRef = useRef<string[]>([]);
  const flushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const sourceKey = useMemo(() => {
    if (source.kind === "agent") return `agent:${namespace}/${source.agentName}`;
    return `workflow:${namespace}/${source.workflowName}/${source.runId ?? "active"}`;
  }, [namespace, source]);

  // The component is fully uncontrolled per source: switching context aborts
  // the live stream and refetches the new tail so the buffer stays accurate.
  useEffect(() => {
    setLines([]);
    setErrorMessage(null);
    setDenialMessage(null);
    setPodLabel(null);
    setConnection("idle");
    pendingRef.current = [];
    if (flushTimerRef.current) {
      clearTimeout(flushTimerRef.current);
      flushTimerRef.current = null;
    }
    if (capabilityMissing) {
      setConnection("denied");
      return;
    }
    let cancelled = false;

    (async () => {
      setConnection("loading");
      try {
        if (source.kind === "agent") {
          const resp: AgentLogsResponse = await fetchAgentLogs(
            token,
            namespace,
            source.agentName,
            tail,
          );
          if (cancelled) return;
          setPodLabel(resp.pod_name ?? null);
          const initial = (resp.logs ?? "").split("\n").filter(Boolean);
          setLines(initial.slice(-MAX_BUFFERED_LINES));
        } else {
          const resp: WorkflowLogsResponse = await fetchWorkflowLogs(
            token,
            namespace,
            source.workflowName,
            tail,
          );
          if (cancelled) return;
          setPodLabel(resp.pod_name ?? resp.job_name ?? null);
          const initial = (resp.logs ?? "").split("\n").filter(Boolean);
          setLines(initial.slice(-MAX_BUFFERED_LINES));
        }
        setConnection("live");
      } catch (err) {
        if (cancelled) return;
        const message = apiErrorMessage(err);
        if (/capability/i.test(message) || /403/.test(message)) {
          setDenialMessage(message);
          setConnection("denied");
        } else {
          setErrorMessage(message || "Could not load logs");
          setConnection("error");
        }
        return;
      }
      if (cancelled) return;
      const controller = new AbortController();
      abortRef.current = controller;
      const flush = () => {
        if (pendingRef.current.length === 0) return;
        const batch = pendingRef.current;
        pendingRef.current = [];
        setLines((prev) => {
          const merged = prev.concat(batch);
          if (merged.length > MAX_BUFFERED_LINES) {
            return merged.slice(merged.length - MAX_BUFFERED_LINES);
          }
          return merged;
        });
        setLastEventAt(Date.now());
      };
      try {
        if (source.kind === "agent") {
          await streamAgentLogs({
            token,
            namespace,
            agentName: source.agentName,
            signal: controller.signal,
            tail,
            onLine: (line) => {
              if (pausedRef.current) return;
              pendingRef.current.push(line);
              if (flushTimerRef.current) return;
              flushTimerRef.current = setTimeout(() => {
                flushTimerRef.current = null;
                flush();
              }, 150);
            },
            onStarted: (info) => setPodLabel((prev) => prev ?? info.pod_name),
            onError: (err) => {
              setErrorMessage(err.message);
              setConnection("error");
            },
            onStopped: () => {
              flush();
              setConnection((prev) => (prev === "error" ? prev : "idle"));
            },
          });
        } else {
          await streamWorkflowLogs({
            token,
            namespace,
            workflowName: source.workflowName,
            signal: controller.signal,
            tail,
            onLine: (line) => {
              if (pausedRef.current) return;
              pendingRef.current.push(line);
              if (flushTimerRef.current) return;
              flushTimerRef.current = setTimeout(() => {
                flushTimerRef.current = null;
                flush();
              }, 150);
            },
            onStarted: (info) => setPodLabel((prev) => prev ?? info.pod_name ?? null),
            onError: (err) => {
              setErrorMessage(err.message);
              setConnection("error");
            },
            onStopped: () => {
              flush();
              setConnection((prev) => (prev === "error" ? prev : "idle"));
            },
          });
        }
      } catch (err) {
        if (cancelled || controller.signal.aborted) return;
        setErrorMessage(apiErrorMessage(err) || "Live log stream failed");
        setConnection("error");
      }
    })();

    return () => {
      cancelled = true;
      abortRef.current?.abort();
      abortRef.current = null;
    };
  }, [sourceKey, tail, token, namespace, source, capabilityMissing]);

  // Drop pause buffer when the user toggles pause off, so they always see
  // fresh lines after resuming.
  useEffect(() => {
    if (!paused) pendingRef.current = [];
  }, [paused]);

  const visibleLines = useMemo(() => {
    const trimmed = query.trim().toLowerCase();
    const levelTest = LEVEL_PATTERNS.find((p) => p.value === level) ?? LEVEL_PATTERNS[0];
    return lines.filter((line) => {
      if (level !== "all" && !levelTest.test(stripLogTimestamp(line))) return false;
      if (!trimmed) return true;
      return stripLogTimestamp(line).toLowerCase().includes(trimmed);
    });
  }, [lines, level, query]);

  const errorCount = useMemo(
    () => lines.filter((line) => classifyLogLevel(stripLogTimestamp(line)) === "error").length,
    [lines],
  );
  const warnCount = useMemo(
    () => lines.filter((line) => classifyLogLevel(stripLogTimestamp(line)) === "warn").length,
    [lines],
  );

  const onCopy = useCallback(async () => {
    if (typeof navigator === "undefined" || !navigator.clipboard) return;
    const text = visibleLines.map(stripLogTimestamp).join("\n");
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Clipboard rejection is non-fatal; the user can still select manually.
    }
  }, [visibleLines]);

  const onDownload = useCallback(() => {
    const text = visibleLines.map(stripLogTimestamp).join("\n");
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const subject = source.kind === "agent" ? source.agentName : source.workflowName;
    a.href = url;
    a.download = `${subject}-logs.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, [visibleLines, source]);

  return (
    <div className={cn("flex min-h-0 flex-col gap-3", className)}>
      <div className="flex flex-wrap items-center gap-2 rounded-md border border-border/60 bg-muted/20 p-2">
        <ConnectionBadge state={connection} paused={paused} lastEventAt={lastEventAt} />
        {podLabel && (
          <span className="text-[11px] text-muted-foreground">
            <span className="font-mono">{podLabel}</span>
            {contextLabel ? <span className="text-muted-foreground/80"> · {contextLabel}</span> : null}
          </span>
        )}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1.5">
            <Label className="text-[10px] uppercase tracking-wide text-muted-foreground">Level</Label>
            <Select value={level} onValueChange={(v) => setLevel(v as typeof level)}>
              <SelectTrigger className="h-7 w-[110px] text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {LEVEL_PATTERNS.map((p) => (
                  <SelectItem key={p.value} value={p.value}>
                    {p.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex items-center gap-1.5">
            <Label className="text-[10px] uppercase tracking-wide text-muted-foreground">Tail</Label>
            <Select value={String(tail)} onValueChange={(v) => setTail(Number(v))}>
              <SelectTrigger className="h-7 w-[88px] text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {[50, 100, 200, 500, 1000, 2000, 5000].map((value) => (
                  <SelectItem key={value} value={String(value)}>
                    {value} lines
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="relative">
            <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Filter"
              className="h-7 w-[180px] pl-7 text-xs"
            />
          </div>
          <Button
            size="sm"
            variant={autoscroll ? "secondary" : "ghost"}
            className="h-7 px-2 text-xs"
            onClick={() => setAutoscroll((v) => !v)}
            aria-pressed={autoscroll}
          >
            <ScrollText className="mr-1 h-3.5 w-3.5" />
            Tail {autoscroll ? "on" : "off"}
          </Button>
          <Button size="sm" variant="ghost" className="h-7 px-2 text-xs" onClick={() => setPaused((p) => !p)}>
            {paused ? <Play className="mr-1 h-3.5 w-3.5" /> : <Pause className="mr-1 h-3.5 w-3.5" />}
            {paused ? "Resume" : "Pause"}
          </Button>
          <Button size="sm" variant="ghost" className="h-7 px-2 text-xs" onClick={onCopy} disabled={!visibleLines.length}>
            <Copy className="mr-1 h-3.5 w-3.5" />
            Copy
          </Button>
          <Button size="sm" variant="ghost" className="h-7 px-2 text-xs" onClick={onDownload} disabled={!visibleLines.length}>
            <Download className="mr-1 h-3.5 w-3.5" />
            Export
          </Button>
        </div>
      </div>

      {errorMessage && connection === "error" && (
        <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/5 p-2 text-xs text-destructive">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span className="break-words">{errorMessage}</span>
        </div>
      )}

      {denialMessage && (
        <div className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/5 p-2 text-xs text-amber-700 dark:text-amber-300">
          <ShieldOff className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span className="break-words">
            <strong className="font-semibold">Access not granted.</strong>{" "}
            {denialMessage} An administrator can grant the <code>runtime:logs</code> capability from the Admin → Users panel.
          </span>
        </div>
      )}

      <div className="flex items-center justify-between text-[10px] text-muted-foreground">
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="h-5 px-1.5 text-[10px] uppercase">
            {visibleLines.length} shown
          </Badge>
          {lines.length > 0 && (
            <Badge variant="outline" className="h-5 px-1.5 text-[10px] uppercase">
              {lines.length} buffered
            </Badge>
          )}
          {errorCount > 0 && (
            <Badge variant="destructive" className="h-5 px-1.5 text-[10px] uppercase">
              {errorCount} errors
            </Badge>
          )}
          {warnCount > 0 && (
            <Badge variant="outline" className="h-5 px-1.5 text-[10px] uppercase text-amber-500">
              {warnCount} warnings
            </Badge>
          )}
        </div>
        <span className="font-mono text-[10px]">
          {paused ? "paused" : connection}
        </span>
      </div>

      <ScrollArea className="min-h-[300px] flex-1 rounded-md border border-border/60 bg-slate-950" ref={(el) => {
        if (!el || !autoscroll || paused) return;
        const viewport = el.querySelector("[data-radix-scroll-area-viewport]") as HTMLElement | null;
        if (viewport) viewport.scrollTop = viewport.scrollHeight;
      }}>
        <div className="max-h-[60vh] overflow-auto p-3 font-mono text-[11px] leading-relaxed text-slate-100">
          {visibleLines.length === 0 ? (
            <div className="flex h-32 flex-col items-center justify-center gap-2 text-slate-500">
              {connection === "denied" ? (
                <>
                  <ShieldOff className="h-5 w-5" />
                  <p>Live logs are not available for your account.</p>
                </>
              ) : connection === "loading" ? (
                <>
                  <Activity className="h-5 w-5 animate-pulse" />
                  <p>Loading log tail…</p>
                </>
              ) : (
                <>
                  <ScrollText className="h-5 w-5" />
                  <p>No log lines match the current filter.</p>
                </>
              )}
            </div>
          ) : (
            visibleLines.map((line, idx) => {
              const stripped = stripLogTimestamp(line);
              const level = classifyLogLevel(stripped);
              return (
                <div
                  key={`${idx}-${line.slice(0, 32)}`}
                  className={cn(
                    "whitespace-pre-wrap break-words",
                    level === "error" && "text-red-300",
                    level === "warn" && "text-amber-200",
                    level === "info" && "text-sky-200",
                    level === "debug" && "text-slate-400",
                  )}
                >
                  {stripped}
                </div>
              );
            })
          )}
        </div>
      </ScrollArea>

      <p className="text-[10px] text-muted-foreground">
        Pod logs may contain environment-derived data. Lines are scoped to this namespace; access requires the <code>runtime:logs</code> capability.
      </p>
    </div>
  );
}

function ConnectionBadge({
  state,
  paused,
  lastEventAt,
}: {
  state: ConnectionState;
  paused: boolean;
  lastEventAt: number | null;
}) {
  const icon =
    state === "denied" ? (
      <ShieldOff className="h-3.5 w-3.5 text-amber-500" />
    ) : state === "error" ? (
      <WifiOff className="h-3.5 w-3.5 text-destructive" />
    ) : state === "loading" ? (
      <Activity className="h-3.5 w-3.5 animate-pulse text-muted-foreground" />
    ) : state === "live" ? (
      <Wifi className="h-3.5 w-3.5 text-emerald-500" />
    ) : state === "paused" || paused ? (
      <Circle className="h-3.5 w-3.5 text-amber-500" />
    ) : (
      <CheckCircle2 className="h-3.5 w-3.5 text-muted-foreground" />
    );

  const label =
    state === "denied"
      ? "Access denied"
      : state === "error"
        ? "Disconnected"
        : state === "loading"
          ? "Loading"
          : state === "live"
            ? paused
              ? "Paused"
              : "Live"
            : state === "paused" || paused
              ? "Paused"
              : "Idle";

  return (
    <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
      {icon}
      <span className="font-medium uppercase tracking-wide text-foreground/80">{label}</span>
      {state === "live" && lastEventAt && !paused ? (
        <span className="text-[10px] text-muted-foreground/70">streaming</span>
      ) : null}
    </div>
  );
}
