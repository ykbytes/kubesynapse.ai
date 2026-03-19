import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, LoaderCircle, RefreshCw, Search, TerminalSquare } from "lucide-react";

import { useConnection } from "@/contexts/ConnectionContext";
import {
  fetchAgentLogs,
  fetchWorkflowLogs,
  streamAgentLogs,
  streamWorkflowLogs,
} from "@/lib/api";
import type { WorkflowInfo } from "@/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ScrollArea } from "@/components/ui/scroll-area";

interface WorkflowLogPanelProps {
  workflow: WorkflowInfo;
}

type LogSource = "worker" | string;
type FilterMode = "all" | "opencode" | "errors";

const MAX_LINES = 400;
const OPEN_CODE_KEYWORDS = [
  "opencode",
  "context_overflow",
  "structured_output",
  "session",
  "compaction",
  "compact",
  "mcp",
  "tool_call",
  "approval",
  "retry",
  "auth",
];
const ERROR_KEYWORDS = [
  "error",
  "failed",
  "exception",
  "traceback",
  "timeout",
  "denied",
  "rejected",
  "context_overflow",
];

function normalizeLines(raw: string): string[] {
  return raw
    .split(/\r?\n/)
    .map((line) => line.trimEnd())
    .filter(Boolean);
}

function matchesKeyword(line: string, keywords: string[]): boolean {
  const lower = line.toLowerCase();
  return keywords.some((keyword) => lower.includes(keyword));
}

function parseLine(line: string): { message: string; level: string | null } {
  try {
    const parsed = JSON.parse(line) as Record<string, unknown>;
    const message = typeof parsed.message === "string"
      ? parsed.message
      : typeof parsed.msg === "string"
        ? parsed.msg
        : line;
    const level = typeof parsed.level === "string"
      ? parsed.level
      : typeof parsed.levelname === "string"
        ? parsed.levelname
        : null;
    return { message, level };
  } catch {
    return { message: line, level: null };
  }
}

function appendLines(current: string[], incoming: string[]): string[] {
  if (incoming.length === 0) return current;
  const next = [...current, ...incoming];
  return next.length > MAX_LINES ? next.slice(next.length - MAX_LINES) : next;
}

export function WorkflowLogPanel({ workflow }: WorkflowLogPanelProps) {
  const { token, namespace } = useConnection();
  const [source, setSource] = useState<LogSource>("worker");
  const [filterMode, setFilterMode] = useState<FilterMode>("opencode");
  const [searchText, setSearchText] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const [lines, setLines] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string>("");
  const [streamMeta, setStreamMeta] = useState<{ podName?: string; jobName?: string }>({});
  const agentOptions = useMemo(
    () => Array.from(new Set(workflow.steps.map((step) => step.agent_ref).filter(Boolean))),
    [workflow.steps],
  );

  useEffect(() => {
    setSource("worker");
    setLines([]);
    setError("");
    setStreamMeta({});
  }, [workflow.name, workflow.run_id]);

  useEffect(() => {
    if (!token || !namespace || !workflow.name) return undefined;

    const controller = new AbortController();
    let active = true;

    async function loadAndStream() {
      setLoading(true);
      setStreaming(false);
      setError("");
      setLines([]);
      setStreamMeta({});
      try {
        if (source === "worker") {
          const initial = await fetchWorkflowLogs(token, namespace, workflow.name, 200);
          if (!active) return;
          setLines(normalizeLines(initial.logs));
          setStreamMeta({ podName: initial.pod_name, jobName: initial.job_name });
          setLoading(false);
          setStreaming(true);
          await streamWorkflowLogs({
            signal: controller.signal,
            token,
            namespace,
            workflowName: workflow.name,
            tail: 50,
            onLine: (line) => {
              if (!active) return;
              setLines((current) => appendLines(current, [line]));
            },
            onStarted: (info) => {
              if (!active) return;
              setStreamMeta({ podName: info.pod_name, jobName: info.job_name });
              setStreaming(true);
            },
            onError: (streamError) => {
              if (!active || controller.signal.aborted) return;
              setError(streamError.message);
              setStreaming(false);
            },
            onStopped: () => {
              if (!active) return;
              setStreaming(false);
            },
          });
        } else {
          const initial = await fetchAgentLogs(token, namespace, source, 200);
          if (!active) return;
          setLines(normalizeLines(initial.logs));
          setStreamMeta({ podName: initial.pod_name });
          setLoading(false);
          setStreaming(true);
          await streamAgentLogs({
            signal: controller.signal,
            token,
            namespace,
            agentName: source,
            tail: 50,
            onLine: (line) => {
              if (!active) return;
              setLines((current) => appendLines(current, [line]));
            },
            onStarted: (info) => {
              if (!active) return;
              setStreamMeta({ podName: info.pod_name });
              setStreaming(true);
            },
            onError: (streamError) => {
              if (!active || controller.signal.aborted) return;
              setError(streamError.message);
              setStreaming(false);
            },
            onStopped: () => {
              if (!active) return;
              setStreaming(false);
            },
          });
        }
      } catch (loadError) {
        if (!active || controller.signal.aborted) return;
        setError(loadError instanceof Error ? loadError.message : String(loadError));
        setStreaming(false);
      } finally {
        if (active) setLoading(false);
      }
    }

    void loadAndStream();
    return () => {
      active = false;
      controller.abort();
    };
  }, [namespace, refreshKey, source, token, workflow.name, workflow.run_id]);

  const filteredLines = useMemo(() => {
    return lines.filter((line) => {
      if (filterMode === "opencode" && !matchesKeyword(line, OPEN_CODE_KEYWORDS)) return false;
      if (filterMode === "errors" && !matchesKeyword(line, ERROR_KEYWORDS)) return false;
      if (searchText.trim() && !line.toLowerCase().includes(searchText.trim().toLowerCase())) return false;
      return true;
    });
  }, [filterMode, lines, searchText]);

  const title = source === "worker" ? "worker orchestration" : `${source} runtime`;

  return (
    <Card className="shadow-none">
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <TerminalSquare className="h-4 w-4 text-muted-foreground" />
            <CardTitle className="text-sm">Live logs</CardTitle>
            <Badge variant="outline" className="text-[10px]">
              {title}
            </Badge>
            {streaming && (
              <Badge variant="outline" className="border-emerald-500/30 text-[10px] text-emerald-300">
                streaming
              </Badge>
            )}
          </div>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-8 rounded-xl text-xs"
            disabled={loading}
            title="Reload logs"
            onClick={() => setRefreshKey((current) => current + 1)}
          >
            <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 md:grid-cols-[1fr_1fr_1.3fr]">
          <div className="space-y-1.5">
            <Label className="text-xs">Source</Label>
            <Select value={source} onValueChange={setSource}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="worker">Workflow worker</SelectItem>
                {agentOptions.map((agentName) => (
                  <SelectItem key={agentName} value={agentName}>
                    Agent: {agentName}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs">Filter</Label>
            <Select value={filterMode} onValueChange={(value) => setFilterMode(value as FilterMode)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All logs</SelectItem>
                <SelectItem value="opencode">OpenCode-focused</SelectItem>
                <SelectItem value="errors">Errors only</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs">Search</Label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={searchText}
                onChange={(event) => setSearchText(event.target.value)}
                className="pl-7"
                placeholder="timeout, context_overflow, approval..."
              />
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
          {streamMeta.jobName && <span>Job: {streamMeta.jobName}</span>}
          {streamMeta.podName && <span>Pod: {streamMeta.podName}</span>}
          <span>Visible lines: {filteredLines.length}</span>
          <span>Total buffered: {lines.length}</span>
        </div>

        {error && (
          <div className="flex items-center gap-2 rounded-xl border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <div className="rounded-xl border border-border/60 bg-background/70">
          <ScrollArea className="h-80">
            <div className="space-y-1 p-3 font-mono text-[11px] leading-relaxed">
              {loading && (
                <div className="flex items-center gap-2 text-muted-foreground">
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                  Loading logs...
                </div>
              )}
              {!loading && filteredLines.length === 0 && (
                <div className="text-muted-foreground">No log lines match the current filter.</div>
              )}
              {filteredLines.map((line, index) => {
                const parsed = parseLine(line);
                const level = (parsed.level || "").toLowerCase();
                const colorClass = level.includes("error") || matchesKeyword(parsed.message, ERROR_KEYWORDS)
                  ? "text-red-300"
                  : level.includes("warn")
                    ? "text-amber-300"
                    : matchesKeyword(parsed.message, OPEN_CODE_KEYWORDS)
                      ? "text-sky-300"
                      : "text-muted-foreground";
                return (
                  <div key={`${index}-${line.slice(0, 32)}`} className={colorClass}>
                    {line}
                  </div>
                );
              })}
            </div>
          </ScrollArea>
        </div>
      </CardContent>
    </Card>
  );
}
