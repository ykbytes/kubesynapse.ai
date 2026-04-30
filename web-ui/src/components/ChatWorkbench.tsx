import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowUp,
  ArrowUpRight,
  AtSign,
  Brain,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Circle,
  Cog,
  Download,
  FileDiff,
  FileText,
  FolderOpen,
  LoaderCircle,
  Maximize2,
  MessageSquare,
  MemoryStick,
  Minimize2,
  Paperclip,
  Pencil,
  Pin,
  PanelRightClose,
  PanelRightOpen,
  Plus,
  RotateCcw,
  Search,
  Square,
  X,
  XCircle,
  Zap,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { CopyButton } from "./CopyButton";
import { EmptyState } from "./EmptyState";
import { StatusBadge } from "./StatusBadge";
import { ActivityTimeline } from "./ActivityTimeline";
import { ChatSettingsDrawer } from "./ChatSettingsDrawer";
import type { AgentDiscoveryPeer, AgentInfo, FactoryMode, InvocationSummary, RuntimeKind, SpecialistSubagentDraft, UiActivity, UiMessage } from "../types";
import type { UiTodo } from "../types";
import { OperationLog } from "./OperationLog";
import { FileExplorer } from "./FileExplorer";
import type { AgentArtifactPreview, AgentFileListResult, ChatSessionSummary, MemoryRecordInfo } from "@/lib/api";
import { fetchSessionDiff } from "@/lib/api";
import { extractAgentCallsFromSummary, parseAgentInvokeCommand, sanitizeText, type AgentCallSummary } from "@/lib/agentCalls";
import { factoryModeShortLabel, isFactoryAgentName } from "@/lib/factoryModes";
import { usePlanDock } from "@/hooks/usePlanDock";
import { cn } from "@/lib/utils";
import { useChat } from "@/contexts/ChatContext";
import { useWorkspace } from "@/contexts/WorkspaceContext";
import { useConnection } from "@/contexts/ConnectionContext";
import { QuestionDock } from "./QuestionDock";
import { MarkdownRenderer } from "./MarkdownRenderer";
import { deriveAgentVisualSignals, extractMcpCapabilityIds, getCapabilitySignal } from "@/lib/agentSignals";

interface ChatWorkbenchProps {
  agentName: string;
  runtimeKind: RuntimeKind;
  prompt: string;
  messages: UiMessage[];
  activity: UiActivity[];
  todos: UiTodo[];
  phase: "plan" | "build" | "idle";
  isSending: boolean;
  tokenReady: boolean;
  streamMode: boolean;
  requireApproval: boolean;
  approvalSupported: boolean;
  a2aTargetAgent: string;
  a2aTargetNamespace: string;
  a2aTimeoutSeconds: string;
  specialistSubagents: SpecialistSubagentDraft[];
  specialistTeamConfigured: boolean;
  agents: AgentInfo[];
  discoveryPeers: AgentDiscoveryPeer[];
  discoveryLoading: boolean;
  discoveryError: string;
  opencodeOutputFormat: string;
  opencodeAutonomous: boolean;
  opencodeMaxTurns: string;
  opencodeWorkingDirectory: string;
  factoryMode: FactoryMode;
  summary: InvocationSummary | null;
  activeSessionId: string | null;
  sessionDirty: boolean;
  sessionSaving: boolean;
  lastSessionSaveAt: string | null;
  activeSessionSummary: ChatSessionSummary | null;
  activeMemoryRecords: MemoryRecordInfo[];
  agentMemoryRecords: MemoryRecordInfo[];
  onPromoteMemoryRecord: (recordId: number, promoted: boolean) => void;
  onEditMemoryRecord: (recordId: number, patch: { topic?: string; content?: string; promoted?: boolean }) => void;
  onDeleteMemoryRecord: (recordId: number) => void;
  emptyMessage: string;
  error: string;
  onDownloadArtifact: (path: string, filename?: string) => Promise<void>;
  onDownloadArtifactZip: () => Promise<void>;
  onListArtifacts: () => Promise<AgentFileListResult>;
  onPreviewArtifact: (path: string) => Promise<AgentArtifactPreview>;
  onPromptChange: (value: string) => void;
  onToggleStreamMode: (value: boolean) => void;
  onToggleRequireApproval: (value: boolean) => void;
  onA2ATargetAgentChange: (value: string) => void;
  onA2ATargetNamespaceChange: (value: string) => void;
  onA2ATimeoutSecondsChange: (value: string) => void;
  onOpenCodeOutputFormatChange: (value: string) => void;
  onOpenCodeAutonomousChange: (value: boolean) => void;
  onOpenCodeMaxTurnsChange: (value: string) => void;
  onOpenCodeWorkingDirectoryChange: (value: string) => void;
  onFactoryModeChange: (value: FactoryMode) => void;
  onSaveSession: () => void;
  canSubmit: boolean;
  onSubmit: (attachments?: UiMessage["attachments"]) => void;
  onCancel: () => void;
}

const DRAWER_PANEL_CLASS = "absolute inset-y-3 right-3 z-10 flex flex-col overflow-hidden rounded-[1.4rem] border border-border/80 bg-background/96 shadow-2xl shadow-black/30 backdrop-blur-xl";
const SURFACE_PANEL_CLASS = "rounded-sm border border-border/70 bg-background/80 shadow-sm backdrop-blur-sm";

/* Auto-scroll reasoning box that stays at bottom */
function AutoScrollReasoning({ reasoning }: { reasoning: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [reasoning]);
  return (
    <div
      ref={ref}
      className="mt-1 max-h-48 overflow-y-auto rounded-sm border border-border/60 bg-muted/30 px-2.5 py-1.5 text-[11px] italic leading-relaxed text-muted-foreground whitespace-pre-wrap break-words shadow-inner"
    >
      {reasoning}
    </div>
  );
}

/* Highlight @mentions in text */
function renderMentions(text: string, agents: AgentInfo[]): React.ReactNode {
  const parts = text.split(/(@[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?)/gi);
  return parts.map((part, i) => {
    const name = part.startsWith("@") ? part.slice(1) : null;
    const agent = name ? agents.find((a) => a.name.toLowerCase() === name.toLowerCase()) : null;
    if (agent) {
      return (
        <span key={i} className="inline-flex items-center gap-0.5 rounded-md bg-primary-foreground/20 px-1 py-0.5 text-xs font-semibold">
          <AtSign className="h-3 w-3" />
          {agent.name}
        </span>
      );
    }
    return <span key={i}>{part}</span>;
  });
}

/* ------------------------------------------------------------------ */
/*  Message bubble — ChatGPT-style layout                             */
/* ------------------------------------------------------------------ */

const MessageBubble = memo(function MessageBubble({
  message,
  index,
  onEditPrompt: _onEditPrompt,
  onRegeneratePrompt: _onRegeneratePrompt,
  promptForRegenerate: _promptForRegenerate,
  operationSummary,
  liveActivity = [],
  phase = "idle",
  agents = [],
}: {
  message: UiMessage;
  index: number;
  onEditPrompt?: (text: string) => void;
  onRegeneratePrompt?: (text?: string) => Promise<void>;
  promptForRegenerate?: string | null;
  operationSummary?: InvocationSummary | null;
  liveActivity?: UiActivity[];
  phase?: "plan" | "build" | "idle";
  agents?: AgentInfo[];
}) {
  const [thinkingOpen, setThinkingOpen] = useState(false);
  const isStreaming = message.status === "streaming";
  const isUser = message.role === "user";
  const isSystem = message.role === "system";
  const streamingStatus = isStreaming ? describeStreamingStatus(message, operationSummary, liveActivity, phase) : "";
  const showInlineActivity = liveActivity.length > 0 && (isStreaming || !operationSummary);
  const agentCalls = useMemo(() => extractAgentCallsFromSummary(operationSummary ?? null), [operationSummary]);

  // ── User message: right-aligned solid bubble ──
  if (isUser) {
    const attachments = message.attachments;
    const hasAttachments = attachments && attachments.length > 0;
    return (
      <div
        className="group flex justify-end animate-slide-up"
        style={{ animationDelay: `${Math.min(index * 30, 300)}ms`, animationFillMode: "backwards" }}
      >
          <div className="max-w-[75%]">
          <div className="rounded-lg rounded-br-sm border border-primary/35 bg-primary px-4 py-3 text-primary-foreground shadow-sm shadow-primary/20">
            {/* Attachment previews */}
            {hasAttachments && (
              <div className="mb-2 flex flex-wrap gap-2">
                {attachments.map((att, i) =>
                  att.isImage ? (
                    <img
                      key={i}
                      src={att.dataUrl}
                      alt={att.name}
                      className="max-h-40 max-w-[200px] rounded-md border border-primary-foreground/20 object-cover"
                    />
                  ) : (
                    <span
                      key={i}
                      className="inline-flex items-center gap-1 rounded-md border border-primary-foreground/20 bg-primary-foreground/10 px-2 py-0.5 text-xs text-primary-foreground"
                    >
                      <Paperclip className="h-3 w-3" />
                      {att.name}
                    </span>
                  ),
                )}
              </div>
            )}
            <div className="whitespace-pre-wrap break-words text-sm leading-relaxed">
              {message.content ? renderMentions(message.content, agents) : ""}
            </div>
          </div>
          {message.timestamp && (
            <div className="mt-1 text-right text-[10px] text-muted-foreground/40 opacity-0 transition-opacity duration-150 group-hover:opacity-100">
              {formatMessageTimestamp(message.timestamp)}
            </div>
          )}
        </div>
      </div>
    );
  }

  // ── System message: centered muted pill ──
  if (isSystem) {
    return (
      <div
        className="flex justify-center animate-slide-up"
        style={{ animationDelay: `${Math.min(index * 30, 300)}ms`, animationFillMode: "backwards" }}
      >
        <div className="flex items-center gap-2 rounded-full border border-amber-500/25 bg-amber-500/10 px-4 py-2 text-[11px] text-amber-300 shadow-sm shadow-amber-950/20 backdrop-blur-sm">
          <Zap className="h-3 w-3" />
          <span>{message.content || "System message"}</span>
        </div>
      </div>
    );
  }

  // ── Assistant message: left-aligned, full-width, with avatar ──
  return (
    <div
      className="group flex gap-2 animate-slide-up"
      style={{ animationDelay: `${Math.min(index * 30, 300)}ms`, animationFillMode: "backwards" }}
      role={isStreaming ? "status" : undefined}
      aria-live={isStreaming ? "polite" : undefined}
    >
      {/* Content */}
      <div className="min-w-0 flex-1 rounded-lg border border-border/70 bg-background/75 px-4 py-3 shadow-sm backdrop-blur-sm">
        {/* Thinking section */}
        {message.reasoning && (
          <div className="mb-1.5">
            <button
              onClick={() => setThinkingOpen((o) => !o)}
              className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground transition-colors duration-150"
              aria-expanded={thinkingOpen}
            >
              <Brain className="h-2.5 w-2.5" aria-hidden="true" />
              {thinkingOpen ? <ChevronDown className="h-2.5 w-2.5" /> : <ChevronRight className="h-2.5 w-2.5" />}
              <span>Reasoning</span>
            </button>
            {thinkingOpen && (
              <AutoScrollReasoning reasoning={message.reasoning} />
            )}
          </div>
        )}

        {agentCalls.length > 0 ? <AgentCallBanner calls={agentCalls} isStreaming={isStreaming} /> : null}

        {/* Streaming placeholder */}
        {isStreaming && !message.content ? (
          <div className="py-1.5" aria-label={streamingStatus}>
            <StreamingIndicator label={streamingStatus} />
          </div>
        ) : (
          <>
            <MarkdownRenderer content={message.content || ""} />
            {isStreaming && (
              <div className="mt-2">
                <StreamingIndicator label={streamingStatus} compact />
              </div>
            )}
          </>
        )}

        {showInlineActivity ? <LiveActivityFeed activity={liveActivity} isStreaming={isStreaming} /> : null}

        {/* Execution timeline — replaces flat tool cards */}
        {!isStreaming && operationSummary ? (
          <div className="mt-2.5">
            <OperationLog summary={operationSummary} />
          </div>
        ) : null}

        {/* Model + timestamp metadata (visible on hover) */}
        {(message.modelName || message.timestamp) && (
          <div className="mt-1.5 flex items-center gap-1.5 text-[10px] text-muted-foreground/40 opacity-0 transition-opacity duration-150 group-hover:opacity-100">
            {message.modelName && <span className="font-medium">{message.modelName}</span>}
            {message.modelName && message.timestamp && <span>·</span>}
            {message.timestamp && <span>{formatMessageTimestamp(message.timestamp)}</span>}
          </div>
        )}
      </div>
    </div>
  );
});

type StarterPrompt = {
  label: string;
  description: string;
  prompt: string;
};

type DownloadableArtifact = {
  path: string;
  filename: string;
  source: "artifact" | "result";
};

type DownloadablePathSource = DownloadableArtifact["source"];

type TeamRunSummary = {
  status: "ready" | "running" | "complete" | "needs-review";
  memberCount: number;
  completedCount: number;
  failedCount: number;
  runningCount: number;
  queuedCount: number;
  resultFileCount: number;
  sharedFileCount: number;
  sharedSandboxSession: boolean;
};

const DOWNLOADABLE_FILE_RE = /\.(pdf|md|txt|json|yaml|yml|csv|html|svg|png|jpg|jpeg|gif|doc|docx)$/i;
const FILE_OUTPUT_TOOL_NAMES = new Set(["write", "edit", "patch", "create_file", "apply_patch"]);

function basename(path: string): string {
  return path.replace(/\\/g, "/").split("/").filter(Boolean).pop() || path;
}

function truncateText(value: string | null | undefined, maxChars = 120): string {
  const text = String(value || "").trim();
  if (!text) return "";
  if (text.length <= maxChars) return text;
  return `${text.slice(0, maxChars - 1).trimEnd()}…`;
}

function formatAgentIdentity(agentName: string, namespace: string | null): string {
  return namespace && namespace !== "default" ? `${namespace}/${agentName}` : agentName;
}

function formatAgentPeerLabel(call: AgentCallSummary): string {
  return formatAgentIdentity(call.agentName, call.namespace);
}

function agentCallIsRunning(status: string): boolean {
  return ["running", "working", "in_progress", "approval_pending"].includes(status.trim().toLowerCase());
}

function agentCallIsError(status: string): boolean {
  return ["error", "failed", "blocked", "denied"].includes(status.trim().toLowerCase());
}

function formatAgentCallStatus(status: string): string {
  const normalized = status.trim().toLowerCase();
  if (!normalized) return "completed";
  return normalized.replace(/_/g, " ");
}

interface GroupedAgentCall {
  label: string;
  count: number;
  worstStatus: string;
  calls: AgentCallSummary[];
}

function groupAgentCalls(calls: AgentCallSummary[]): GroupedAgentCall[] {
  const map = new Map<string, GroupedAgentCall>();
  for (const call of calls) {
    const label = formatAgentPeerLabel(call);
    const existing = map.get(label);
    if (existing) {
      existing.count += 1;
      existing.calls.push(call);
      // Promote worst status: error > running > completed
      if (agentCallIsError(call.status)) existing.worstStatus = call.status;
      else if (agentCallIsRunning(call.status) && !agentCallIsError(existing.worstStatus)) existing.worstStatus = call.status;
    } else {
      map.set(label, { label, count: 1, worstStatus: call.status, calls: [call] });
    }
  }
  return Array.from(map.values());
}

function AgentCallBanner({ calls, isStreaming }: { calls: AgentCallSummary[]; isStreaming: boolean }) {
  const groups = useMemo(() => groupAgentCalls(calls), [calls]);
  const uniqueNames = groups.map((g) => g.label);
  const headerLabel = calls.every((call) => call.kind === "explicit-a2a") ? "Delegated to" : "Contacted";
  const overallStatus = groups.length > 0 ? groups[groups.length - 1].worstStatus : "completed";
  const isError = agentCallIsError(overallStatus);
  const isRunning = isStreaming || (!isError && agentCallIsRunning(overallStatus));
  const statusColor = isError ? "text-red-400" : isRunning ? "text-amber-400" : "text-emerald-400";

  return (
    <div className="mb-1.5 flex items-center gap-2 rounded-md border border-primary/20 bg-primary/[0.06] px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-primary shadow-sm shadow-primary/10">
      <ArrowUpRight className="h-3 w-3 shrink-0" />
      <span className="truncate">
        {headerLabel}{" "}
        {uniqueNames.length <= 3
          ? uniqueNames.join(", ")
          : `${uniqueNames.slice(0, 2).join(", ")} +${uniqueNames.length - 2}`}
      </span>
      <span className={`ml-1 text-[10px] font-medium normal-case tracking-normal ${statusColor}`}>
        {formatAgentCallStatus(overallStatus)}
      </span>
      {isRunning ? (
        <LoaderCircle className="ml-auto h-3 w-3 animate-spin text-amber-400" />
      ) : null}
    </div>
  );
}

function formatStreamingTarget(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return "";
  if (trimmed === "." || trimmed === "./") return "workspace";
  if (!trimmed.includes("/") && !trimmed.includes("\\")) return truncateText(trimmed, 48);
  const parts = trimmed.replace(/\\/g, "/").split("/").filter(Boolean);
  const compact = parts.length > 3 ? parts.slice(-3).join("/") : parts.join("/");
  return truncateText(compact, 48);
}

function extractStreamingTarget(input: unknown, depth = 0): string {
  if (depth > 2 || !input || typeof input !== "object") return "";
  const record = input as Record<string, unknown>;

  for (const key of ["filePath", "file", "path", "directory", "cwd", "pattern"]) {
    const candidate = record[key];
    if (typeof candidate === "string" && candidate.trim()) return formatStreamingTarget(candidate);
  }

  for (const key of ["command", "cmd"]) {
    const candidate = record[key];
    if (typeof candidate === "string" && candidate.trim()) return truncateText(candidate, 48);
  }

  for (const key of ["tool_args", "args", "input"]) {
    const candidate = record[key];
    if (candidate && typeof candidate === "object") {
      const nested = extractStreamingTarget(candidate, depth + 1);
      if (nested) return nested;
    }
  }

  return "";
}

function extractStreamingAgentInvoke(input: unknown, depth = 0): { namespace: string | null; agentName: string } | null {
  if (depth > 2 || !input || typeof input !== "object") return null;
  const record = input as Record<string, unknown>;

  for (const key of ["command", "cmd"]) {
    const candidate = record[key];
    if (typeof candidate === "string" && candidate.trim()) {
      const parsed = parseAgentInvokeCommand(candidate);
      if (parsed) return parsed;
    }
  }

  for (const key of ["tool_args", "args", "input"]) {
    const candidate = record[key];
    if (candidate && typeof candidate === "object") {
      const nested = extractStreamingAgentInvoke(candidate, depth + 1);
      if (nested) return nested;
    }
  }

  return null;
}

function extractStreamingArtifactTarget(message: UiMessage, operationSummary?: InvocationSummary | null): string {
  const artifacts = operationSummary?.artifacts ?? [];
  for (let index = artifacts.length - 1; index >= 0; index -= 1) {
    const artifact = artifacts[index];
    if (!artifact || typeof artifact !== "object") continue;
    const path = (artifact as Record<string, unknown>).path;
    if (typeof path === "string" && path.trim()) return formatStreamingTarget(path);
  }

  const patches = message.patches ?? [];
  for (let patchIndex = patches.length - 1; patchIndex >= 0; patchIndex -= 1) {
    const files = patches[patchIndex]?.files ?? [];
    for (let fileIndex = files.length - 1; fileIndex >= 0; fileIndex -= 1) {
      const path = files[fileIndex];
      if (typeof path === "string" && path.trim()) return formatStreamingTarget(path);
    }
  }

  return "";
}

type LiveActivityTone = "running" | "success" | "error" | "info";

type LiveActivityEntry = {
  id: string;
  label: string;
  detail?: string;
  tone: LiveActivityTone;
  icon: typeof Cog;
};

const TOOL_NODE_LABELS: Record<string, string> = {
  sandbox_tool: "Sandbox tool",
  mcp_tool: "MCP tool",
  retrieval: "Knowledge lookup",
  output_guard: "Output guard",
};

const LIVE_ACTIVITY_STYLES: Record<LiveActivityTone, { badge: string; icon: string }> = {
  running: {
    badge: "border-primary/25 bg-primary/10 text-primary",
    icon: "bg-primary/10 text-primary",
  },
  success: {
    badge: "border-emerald-500/25 bg-emerald-500/10 text-emerald-400",
    icon: "bg-emerald-500/10 text-emerald-400",
  },
  error: {
    badge: "border-destructive/25 bg-destructive/10 text-destructive",
    icon: "bg-destructive/10 text-destructive",
  },
  info: {
    badge: "border-border/70 bg-muted/40 text-muted-foreground",
    icon: "bg-muted/40 text-muted-foreground",
  },
};

function humanizeEventLabel(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return "Operation";
  return trimmed
    .split(/[_\-/]+/)
    .filter(Boolean)
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(" ");
}

function formatBytes(value: unknown): string {
  const raw = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(raw) || raw <= 0) return "";
  const units = ["B", "KB", "MB", "GB"];
  let size = raw;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  const precision = size >= 10 || unitIndex === 0 ? 0 : 1;
  return `${size.toFixed(precision)} ${units[unitIndex]}`;
}

function joinDetail(parts: Array<string | null | undefined>): string | undefined {
  const values = parts.map((part) => String(part || "").trim()).filter(Boolean);
  if (values.length === 0) return undefined;
  return values.join(" · ");
}

function summarizeTodoProgress(payload: Record<string, unknown>): string | undefined {
  const todos = Array.isArray(payload.todos) ? payload.todos : [];
  if (todos.length === 0) return undefined;
  const completed = todos.filter((item) => {
    if (!item || typeof item !== "object") return false;
    const status = String((item as Record<string, unknown>).status ?? "").trim().toLowerCase();
    return status === "completed" || status === "cancelled";
  }).length;
  return `${completed} of ${todos.length} tasks done`;
}

function createLiveActivityEntry(item: UiActivity): LiveActivityEntry | null {
  const payload = item.payload;

  if (item.event === "response.started") {
    return {
      id: item.id,
      label: "Connected to runtime",
      detail: typeof payload.thread_id === "string" && payload.thread_id.trim() ? `thread ${payload.thread_id.slice(0, 8)}` : undefined,
      tone: "info",
      icon: Activity,
    };
  }

  if (item.event === "response.turn_started") {
    const agent = String(payload.agent ?? "").trim().toLowerCase();
    const turn = typeof payload.turn === "number" ? `turn ${payload.turn}` : "";
    const maxTurns = typeof payload.max_turns === "number" ? `${payload.max_turns} max turns` : "";
    return {
      id: item.id,
      label: agent === "plan" ? "Planning the response" : agent === "build" ? "Executing the plan" : "Starting a new turn",
      detail: joinDetail([turn, maxTurns]),
      tone: "running",
      icon: agent === "plan" ? Brain : Bot,
    };
  }

  if (item.event === "response.turn_completed") {
    const status = String(payload.status ?? "").trim().toLowerCase();
    const turn = typeof payload.turn === "number" ? `turn ${payload.turn}` : "";
    const responseLength = typeof payload.response_length === "number" ? `${payload.response_length} chars` : "";
    return {
      id: item.id,
      label: status === "incomplete" ? "Turn paused for another pass" : "Completed a turn",
      detail: joinDetail([turn, responseLength]),
      tone: status === "incomplete" ? "running" : "success",
      icon: status === "incomplete" ? LoaderCircle : CheckCircle2,
    };
  }

  if (item.event === "graph.node") {
    const node = String(payload.node ?? "").trim();
    const status = String(payload.status ?? "").trim().toLowerCase();
    const baseLabel = TOOL_NODE_LABELS[node] ?? humanizeEventLabel(node);
    return {
      id: item.id,
      label: status === "started"
        ? `Running ${baseLabel.toLowerCase()}`
        : status === "failed"
          ? `${baseLabel} failed`
          : `${baseLabel} completed`,
      detail: joinDetail([
        typeof payload.invoke_status === "string" ? sanitizeText(payload.invoke_status) : undefined,
        typeof payload.error === "string" ? sanitizeText(payload.error) : undefined,
      ]),
      tone: status === "failed" ? "error" : status === "started" ? "running" : "success",
      icon: status === "failed" ? AlertTriangle : status === "started" ? LoaderCircle : CheckCircle2,
    };
  }

  if (item.event === "mcp.result") {
    const serverType = String(payload.serverType ?? "").trim();
    const toolName = String(payload.toolName ?? "").trim();
    const label = serverType || toolName ? `${serverType ? `${serverType}/` : ""}${toolName || "tool"}` : "MCP tool";
    return {
      id: item.id,
      label: `Completed ${label}`,
      detail: formatBytes(payload.bytes) || undefined,
      tone: "success",
      icon: CheckCircle2,
    };
  }

  if (item.event === "subagent.call") {
    const targetAgent = String(payload.targetAgent ?? "subagent").trim();
    const status = String(payload.status ?? "").trim().toLowerCase();
    return {
      id: item.id,
      label: status === "started"
        ? `Calling ${targetAgent}`
        : status === "failed"
          ? `${targetAgent} failed`
          : `${targetAgent} completed`,
      detail: joinDetail([
        typeof payload.targetNamespace === "string" ? payload.targetNamespace : undefined,
        formatBytes(payload.bytes),
        typeof payload.resultFilePath === "string" ? payload.resultFilePath : undefined,
        typeof payload.error === "string" ? sanitizeText(payload.error) : undefined,
      ]),
      tone: status === "failed" ? "error" : status === "started" ? "running" : "success",
      icon: status === "failed" ? AlertTriangle : status === "started" ? LoaderCircle : CheckCircle2,
    };
  }

  if (item.event === "response.tool_call") {
    const tool = String(payload.tool ?? "").trim();
    const status = String(payload.status ?? "unknown").trim().toLowerCase();
    const agentInvokeTarget = (tool === "bash" || tool === "shell") ? extractStreamingAgentInvoke(payload.input) : null;
    if (agentInvokeTarget) {
      const peerLabel = formatAgentIdentity(agentInvokeTarget.agentName, agentInvokeTarget.namespace);
      return {
        id: item.id,
        label: status === "completed"
          ? `${peerLabel} replied`
          : status === "failed" || status === "error"
            ? `${peerLabel} failed`
            : `Calling ${peerLabel}`,
        detail: typeof payload.output === "string" && payload.output.trim() ? truncateText(sanitizeText(payload.output), 84) : undefined,
        tone: status === "completed" ? "success" : status === "failed" || status === "error" ? "error" : "running",
        icon: status === "completed" ? CheckCircle2 : status === "failed" || status === "error" ? AlertTriangle : ArrowUpRight,
      };
    }
    const target = extractStreamingTarget(payload.input);
    const toolLabel = tool ? humanizeEventLabel(tool) : "Tool call";
    return {
      id: item.id,
      label: status === "completed"
        ? `${toolLabel} finished`
        : status === "failed" || status === "error"
          ? `${toolLabel} failed`
          : `${toolLabel} running`,
      detail: joinDetail([
        target,
        typeof payload.output === "string" && payload.output.trim() ? truncateText(sanitizeText(payload.output), 84) : undefined,
      ]),
      tone: status === "completed" ? "success" : status === "failed" || status === "error" ? "error" : "running",
      icon: status === "completed" ? CheckCircle2 : status === "failed" || status === "error" ? AlertTriangle : Cog,
    };
  }

  if (item.event === "response.patch") {
    const files = Array.isArray(payload.files) ? payload.files.map((file) => String(file)).filter(Boolean) : [];
    return {
      id: item.id,
      label: files.length === 1 ? "Patched 1 file" : `Patched ${files.length} files`,
      detail: files.length > 0 ? truncateText(files.join(", "), 84) : undefined,
      tone: "success",
      icon: FileDiff,
    };
  }

  if (item.event === "todo.updated") {
    return {
      id: item.id,
      label: "Updated the execution plan",
      detail: summarizeTodoProgress(payload),
      tone: "info",
      icon: Circle,
    };
  }

  if (item.event === "question.asked") {
    const questions = Array.isArray(payload.questions) ? payload.questions : [];
    const firstQuestion = questions[0] && typeof questions[0] === "object"
      ? String((questions[0] as Record<string, unknown>).question ?? "").trim()
      : "";
    return {
      id: item.id,
      label: "Waiting for your input",
      detail: firstQuestion ? truncateText(firstQuestion, 84) : questions.length > 0 ? `${questions.length} question${questions.length > 1 ? "s" : ""}` : undefined,
      tone: "running",
      icon: MessageSquare,
    };
  }

  if (item.event === "response.error_recovery") {
    const retry = typeof payload.retry === "number" ? `retry ${payload.retry}` : "";
    const maxRetries = typeof payload.max_retries === "number" ? `${payload.max_retries} max` : "";
    return {
      id: item.id,
      label: "Recovering from a transient error",
      detail: joinDetail([retry, maxRetries]),
      tone: "info",
      icon: RotateCcw,
    };
  }

  if (item.event === "response.completed") {
    const status = String(payload.status ?? "completed").trim().toLowerCase();
    return {
      id: item.id,
      label: status === "approval_pending" ? "Waiting for approval" : "Response completed",
      detail: typeof payload.policy_name === "string" ? payload.policy_name : undefined,
      tone: status === "blocked" ? "error" : status === "approval_pending" ? "running" : "success",
      icon: status === "blocked" ? AlertTriangle : status === "approval_pending" ? LoaderCircle : CheckCircle2,
    };
  }

  return null;
}

function buildLiveActivityEntries(activity: UiActivity[], limit = 6): LiveActivityEntry[] {
  const entries: LiveActivityEntry[] = [];
  for (const item of activity) {
    const entry = createLiveActivityEntry(item);
    if (entry) entries.push(entry);
  }
  return entries.slice(-limit);
}

function LiveActivityFeed({ activity, isStreaming }: { activity: UiActivity[]; isStreaming: boolean }) {
  const entries = useMemo(() => buildLiveActivityEntries(activity), [activity]);

  if (entries.length === 0) return null;

  return (
    <div className="mt-2 rounded-lg border border-border/50 bg-muted/10 px-2 py-1.5">
      <div className="mb-1 flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
        {isStreaming ? <LoaderCircle className="h-3 w-3 animate-spin text-primary" /> : <CheckCircle2 className="h-3 w-3 text-emerald-400" />}
        <span>{isStreaming ? "Live" : "Activity"}</span>
        <Badge variant="outline" className="ml-auto px-1 py-0 text-[9px]">
          {entries.length}
        </Badge>
      </div>
      <div className="space-y-1">
        {entries.map((entry) => {
          const styles = LIVE_ACTIVITY_STYLES[entry.tone];
          const Icon = entry.icon;
          const iconClassName = entry.tone === "running" && (entry.icon === LoaderCircle || entry.icon === Cog)
            ? "h-3 w-3 animate-spin"
            : "h-3 w-3";
          return (
            <div key={entry.id} className="flex items-start gap-1.5 rounded-md border border-border/40 bg-background/60 px-2 py-1">
              <div className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full ${styles.icon}`}>
                <Icon className={iconClassName} />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="min-w-0 flex-1 break-words text-[11px] font-medium text-foreground">{entry.label}</span>
                  <span className={`rounded-full border px-1 py-0 text-[8px] font-semibold uppercase tracking-[0.12em] ${styles.badge}`}>
                    {entry.tone === "running" ? "live" : entry.tone === "success" ? "done" : entry.tone === "error" ? "err" : "info"}
                  </span>
                </div>
                {entry.detail && (
                  <div className="mt-0 break-words text-[10px] leading-snug text-muted-foreground">{entry.detail}</div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function StreamingIndicator({ label, compact = false }: { label: string; compact?: boolean }) {
  return (
    <div className={`inline-flex max-w-full items-center gap-2 rounded-full border border-primary/20 bg-primary/5 text-foreground/85 shadow-sm ${compact ? "px-2.5 py-1" : "px-3 py-1.5"}`}>
      <span className="streaming-loader text-primary" aria-hidden="true">
        <span />
        <span />
        <span />
      </span>
      <span className="min-w-0 truncate text-[11px] font-medium">{label}</span>
      {compact ? <span className="streaming-caret text-primary" aria-hidden="true" /> : null}
    </div>
  );
}

function describeStreamingStatus(
  message: UiMessage,
  operationSummary?: InvocationSummary | null,
  activity: UiActivity[] = [],
  phase: "plan" | "build" | "idle" = "idle",
): string {
  const liveEntries = buildLiveActivityEntries(activity, 6);
  for (let index = liveEntries.length - 1; index >= 0; index -= 1) {
    const entry = liveEntries[index];
    if (entry.tone === "running" || entry.tone === "info") return entry.label;
  }
  if (liveEntries.length > 0) return liveEntries[liveEntries.length - 1].label;

  if (phase === "plan") return "Planning the response";
  if (phase === "build") return "Continuing the response";

  const toolCalls = message.toolCalls ?? [];
  for (let index = toolCalls.length - 1; index >= 0; index -= 1) {
    const toolCall = toolCalls[index];
    if (toolCall.status !== "running" && toolCall.status !== "unknown") continue;
    if (toolCall.tool.trim().toLowerCase() === "bash" || toolCall.tool.trim().toLowerCase() === "shell") {
      const agentInvokeTarget = extractStreamingAgentInvoke(toolCall.input);
      if (agentInvokeTarget) return `Calling ${formatAgentIdentity(agentInvokeTarget.agentName, agentInvokeTarget.namespace)}`;
    }
    const target = extractStreamingTarget(toolCall.input);
    switch (toolCall.tool.trim().toLowerCase()) {
      case "read":
        return target ? `Reading ${target}` : "Reading files";
      case "glob":
      case "ls":
        return target ? `Scanning ${target}` : "Scanning files";
      case "grep":
        return target ? `Searching ${target}` : "Searching code";
      case "write":
        return target ? `Writing ${target}` : "Writing files";
      case "edit":
        return target ? `Editing ${target}` : "Editing files";
      case "patch":
        return target ? `Updating ${target}` : "Applying patch";
      case "bash":
      case "shell":
        return target ? `Running ${target}` : "Running command";
      default:
        return "Running operations";
    }
  }

  const artifactTarget = extractStreamingArtifactTarget(message, operationSummary);
  if (artifactTarget) return `Updating ${artifactTarget}`;
  if (message.reasoning?.trim()) return "Reasoning live";
  if (toolCalls.length > 0) return "Processing tool results";
  return "Preparing response";
}

function formatRelativeTime(iso: string | null): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function formatMessageTimestamp(iso: string): string {
  try {
    const date = new Date(iso);
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
}

function formatMemoryTypeLabel(value: string): string {
  return value.replace(/_/g, " ");
}

function formatMemorySource(record: MemoryRecordInfo, activeSessionId: string | null): string {
  if (record.session_id && activeSessionId && record.session_id === activeSessionId) return "This session";
  if (record.session_id) return "Saved session";
  return "Agent memory";
}

function buildContinuityHighlights(summary: InvocationSummary | null): string[] {
  const continuity = summary?.continuity;
  if (!continuity) return [];
  const items: string[] = [];
  if (continuity.sessionRecovered) items.push("Recovered remote session");
  if (continuity.handoffResumed) items.push("Resumed from handoff");
  if (continuity.memoryApplied) {
    const count = continuity.memoryEntryCount;
    items.push(count && count > 0 ? `Injected ${count} memory entries` : "Injected durable memory");
  }
  if (continuity.createdNewSession && !continuity.sessionRecovered) items.push("Started fresh remote session");
  return items;
}

const MemoryRecordCard = memo(function MemoryRecordCard({
  record,
  activeSessionId,
  compact = false,
  editable = false,
  editingMemoryId,
  editingMemoryTopic,
  editingMemoryContent,
  onStartEdit,
  onEditTopicChange,
  onEditContentChange,
  onSaveEdit,
  onCancelEdit,
  onPromote,
  onDelete,
}: {
  record: MemoryRecordInfo;
  activeSessionId: string | null;
  compact?: boolean;
  editable?: boolean;
  editingMemoryId?: number | null;
  editingMemoryTopic?: string;
  editingMemoryContent?: string;
  onStartEdit?: (record: MemoryRecordInfo) => void;
  onEditTopicChange?: (value: string) => void;
  onEditContentChange?: (value: string) => void;
  onSaveEdit?: (recordId: number) => void;
  onCancelEdit?: () => void;
  onPromote: (recordId: number, promoted: boolean) => void;
  onDelete: (recordId: number) => void;
}) {
  const isEditing = editable && editingMemoryId === record.id;
  return (
    <div className="rounded-xl border border-border/60 bg-background/80 px-3 py-3 text-xs text-muted-foreground">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline">{formatMemoryTypeLabel(record.memory_type)}</Badge>
        {record.promoted && <Badge variant="default">Pinned</Badge>}
        <span className="font-medium text-foreground/90">{record.topic || "Untitled note"}</span>
        <span className="text-[10px] text-muted-foreground">score {record.score.toFixed(1)}</span>
        {record.created_at && <span className="text-[10px] text-muted-foreground">{formatRelativeTime(record.created_at)}</span>}
        <span className="ml-auto text-[10px] text-muted-foreground">{formatMemorySource(record, activeSessionId)}</span>
      </div>
      {isEditing ? (
        <div className="mt-3 space-y-2">
          <Input
            value={editingMemoryTopic || ""}
            onChange={(e) => onEditTopicChange?.(e.target.value)}
            className="h-8 text-xs"
            placeholder="Topic"
          />
          <Textarea
            value={editingMemoryContent || ""}
            onChange={(e) => onEditContentChange?.(e.target.value)}
            className="min-h-20 resize-y text-xs"
            placeholder="Memory content"
          />
          <div className="flex items-center gap-2">
            <Button type="button" size="sm" className="h-7 px-2 text-[10px]" onClick={() => onSaveEdit?.(record.id)}>
              Save
            </Button>
            <Button type="button" variant="outline" size="sm" className="h-7 px-2 text-[10px]" onClick={onCancelEdit}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <>
          <div className={`mt-2 leading-relaxed text-foreground/85 ${compact ? "line-clamp-3" : ""}`}>{record.content}</div>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground">
            {record.promote_reason && <span className="text-primary/80">{record.promote_reason}</span>}
            {record.username && <span>by {record.username}</span>}
          </div>
          <div className="mt-3 flex items-center gap-1">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={() => onPromote(record.id, !record.promoted)}
              title={record.promoted ? "Unpin memory" : "Pin memory"}
              aria-label={record.promoted ? "Unpin memory" : "Pin memory"}
            >
              <Pin className="h-3 w-3" />
            </Button>
            {editable && (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                onClick={() => onStartEdit?.(record)}
                title="Edit memory"
                aria-label="Edit memory"
              >
                <Pencil className="h-3 w-3" />
              </Button>
            )}
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-7 w-7 text-destructive"
              onClick={() => onDelete(record.id)}
              title="Delete memory"
              aria-label="Delete memory"
            >
              <X className="h-3 w-3" />
            </Button>
          </div>
        </>
      )}
    </div>
  );
});

function normalizeDownloadablePath(rawPath: unknown): string | null {
  if (typeof rawPath !== "string") return null;
  const path = rawPath.trim().replace(/\\/g, "/");
  if (!path || !DOWNLOADABLE_FILE_RE.test(path)) return null;
  if (/^(?:https?:)?\/\//i.test(path)) return null;
  return path;
}

function collectStructuredPaths(record: unknown, fields: string[]): string[] {
  if (!record || typeof record !== "object") return [];
  const value = record as Record<string, unknown>;
  return fields
    .map((field) => normalizeDownloadablePath(value[field]))
    .filter((item): item is string => Boolean(item));
}

function collectFileToolPaths(toolCalls: Array<Record<string, unknown>> | null | undefined): string[] {
  const paths = new Set<string>();
  for (const toolCall of toolCalls ?? []) {
    if (!toolCall || typeof toolCall !== "object") continue;
    const tool = String(toolCall.tool ?? "").trim().toLowerCase();
    if (!FILE_OUTPUT_TOOL_NAMES.has(tool)) continue;
    for (const path of collectStructuredPaths(toolCall.input, ["filePath", "path", "file"])) {
      paths.add(path);
    }
    for (const path of collectStructuredPaths(toolCall.output, ["filePath", "path", "file", "resultFilePath"])) {
      paths.add(path);
    }
  }
  return Array.from(paths);
}

function collectSubagentResultPaths(metadata: InvocationSummary["subagents"] | UiMessage["subagents"] | null | undefined): string[] {
  const paths = new Set<string>();
  for (const rawPath of metadata?.resultFiles ?? []) {
    const normalized = normalizeDownloadablePath(rawPath);
    if (normalized) paths.add(normalized);
  }
  for (const result of metadata?.results ?? []) {
    const normalized = normalizeDownloadablePath(result.resultFilePath);
    if (normalized) paths.add(normalized);
  }
  return Array.from(paths);
}

function countUniqueSharedFiles(metadata: InvocationSummary["subagents"] | null | undefined): number {
  const identities = new Set<string>();
  for (const file of metadata?.sharedFiles ?? []) {
    const path = String(file.path ?? "").trim();
    if (!path) continue;
    identities.add(`${path}|${String(file.purpose ?? "").trim()}`);
  }
  return identities.size;
}

function isSubagentSuccess(status: string): boolean {
  const normalized = status.trim().toLowerCase();
  return normalized === "completed" || normalized === "success";
}

function isSubagentFailure(status: string): boolean {
  const normalized = status.trim().toLowerCase();
  return normalized === "failed" || normalized === "error" || normalized === "blocked";
}

function isSubagentRunning(status: string): boolean {
  const normalized = status.trim().toLowerCase();
  return normalized === "running" || normalized === "streaming" || normalized === "in_progress" || normalized === "working";
}

function summarizeTeamRun(
  metadata: InvocationSummary["subagents"] | null | undefined,
  specialistSubagents: SpecialistSubagentDraft[],
  isSending: boolean,
): TeamRunSummary | null {
  const memberCount = specialistSubagents.filter((item) => item.name.trim()).length;
  if (!metadata && memberCount === 0) return null;

  const results = metadata?.results ?? [];
  const completedCount = results.filter((item) => isSubagentSuccess(item.status)).length;
  const failedCount = results.filter((item) => isSubagentFailure(item.status)).length;
  const runningCount = results.filter((item) => isSubagentRunning(item.status)).length;
  const queuedCount = Math.max(memberCount - completedCount - failedCount - runningCount, 0);
  const resultFileCount = collectSubagentResultPaths(metadata).length;
  const sharedFileCount = countUniqueSharedFiles(metadata);

  let status: TeamRunSummary["status"] = "ready";
  if (isSending || runningCount > 0) {
    status = "running";
  } else if (failedCount > 0) {
    status = "needs-review";
  } else if (results.length > 0) {
    status = "complete";
  }

  return {
    status,
    memberCount,
    completedCount,
    failedCount,
    runningCount,
    queuedCount,
    resultFileCount,
    sharedFileCount,
    sharedSandboxSession: Boolean(metadata?.sharedSandboxSession),
  };
}

function collectDownloadableArtifacts(summary: InvocationSummary | null, messages: UiMessage[]): DownloadableArtifact[] {
  const paths = new Map<string, DownloadableArtifact>();

  const addPath = (rawPath: unknown, source: DownloadablePathSource) => {
    const path = normalizeDownloadablePath(rawPath);
    if (!path) return;
    const existing = paths.get(path);
    if (!existing) {
      paths.set(path, { path, filename: basename(path), source });
      return;
    }
    if (existing.source !== "result" && source === "result") {
      paths.set(path, { ...existing, source });
    }
  };

  for (const artifact of summary?.artifacts ?? []) {
    for (const path of collectStructuredPaths(artifact, ["path", "filePath", "resultFilePath"])) addPath(path, "artifact");
  }
  for (const path of collectFileToolPaths(summary?.toolCalls as Array<Record<string, unknown>> | null | undefined)) {
    addPath(path, "artifact");
  }
  for (const path of collectSubagentResultPaths(summary?.subagents)) addPath(path, "result");

  for (const message of messages) {
    for (const artifact of message.artifacts ?? []) {
      for (const path of collectStructuredPaths(artifact, ["path", "filePath", "resultFilePath"])) addPath(path, "artifact");
    }
    for (const patch of message.patches ?? []) {
      for (const file of patch.files) addPath(file, "artifact");
    }
    for (const path of collectFileToolPaths(message.toolCalls as unknown as Array<Record<string, unknown>> | null | undefined)) {
      addPath(path, "artifact");
    }
    for (const path of collectSubagentResultPaths(message.subagents)) addPath(path, "result");
  }

  return Array.from(paths.values());
}

function buildInlineOperationSummary(message: UiMessage, fallbackSummary?: InvocationSummary | null): InvocationSummary | null {
  const hasMessageOperations = Boolean(
    (message.toolCalls && message.toolCalls.length > 0)
    || (message.artifacts && message.artifacts.length > 0)
    || (message.patches && message.patches.length > 0)
    || message.a2a
    || message.subagents
    || message.metadata,
  );

  if (!hasMessageOperations) {
    return fallbackSummary ?? null;
  }

  const artifacts = message.artifacts && message.artifacts.length > 0
    ? message.artifacts
    : (message.patches ?? []).flatMap((patch) =>
        patch.files.map((path) => ({ path, tool: "patch", status: message.status === "error" ? "error" : "completed" })),
      );

  return {
    threadId: `message-${message.id}`,
    status: message.status === "error" ? "blocked" : message.status === "streaming" ? "running" : "completed",
    warnings: [],
    toolCalls: (message.toolCalls as Array<Record<string, unknown>> | undefined) ?? null,
    artifacts,
    a2a: message.a2a ?? fallbackSummary?.a2a ?? null,
    subagents: message.subagents ?? fallbackSummary?.subagents ?? null,
    metadata: message.metadata ?? fallbackSummary?.metadata ?? null,
    continuity: fallbackSummary?.continuity ?? null,
  };
}

/* ------------------------------------------------------------------ */
/*  Tool call bubble                                                  */
/* ------------------------------------------------------------------ */
const ToolBubble = memo(function ToolBubble({ message }: { message: UiMessage }) {
  const [expanded, setExpanded] = useState(false);
  const isRunning = message.status === "streaming";
  const isFailed = message.status === "error";
  const statusVariant = isFailed ? "error" : isRunning ? "warning" : "success";
  const StatusIcon = isFailed ? XCircle : isRunning ? LoaderCircle : CheckCircle2;
  const statusLabel = isFailed ? "failed" : isRunning ? "running" : "done";
  return (
    <div className="rounded-lg border border-border/60 bg-muted/20 text-sm animate-slide-up transition-shadow duration-200 hover:shadow-sm">
      <button
        type="button"
        onClick={() => setExpanded((o) => !o)}
        aria-expanded={expanded}
        className="flex w-full items-center gap-2 px-3 py-2 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        <Cog className={`h-3.5 w-3.5 transition-transform duration-300 ${isRunning ? "animate-[spin-slow_2s_linear_infinite]" : ""}`} />
        <span className="font-medium text-foreground">{message.toolName || message.toolNode || "tool"}</span>
        <StatusBadge icon={StatusIcon} status={statusVariant} className="ml-auto">
          {statusLabel}
        </StatusBadge>
        <span className="transition-transform duration-200" style={{ transform: expanded ? "rotate(90deg)" : "rotate(0deg)" }}>
          <ChevronRight className="h-3.5 w-3.5" />
        </span>
      </button>
      <div
        className="grid transition-[grid-template-rows] duration-200 ease-out"
        style={{ gridTemplateRows: expanded ? "1fr" : "0fr" }}
      >
        <div className="overflow-hidden">
          <div className="border-t border-border/40 px-3 py-2">
            {message.content ? (
              <div className="relative group">
                <pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-muted-foreground max-h-48 overflow-auto">
                  {message.content}
                </pre>
                <div className="absolute top-1 right-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  <CopyButton value={message.content} />
                </div>
              </div>
            ) : (
              <p className="text-[11px] text-muted-foreground italic">
                {isFailed ? "Tool failed with no error details." : "Tool executed but produced no output."}
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
});

const planTone: Record<UiTodo["status"], { text: string; border: string; bg: string; icon: string }> = {
  pending: {
    text: "text-muted-foreground/70",
    border: "border-transparent",
    bg: "",
    icon: "text-muted-foreground/30",
  },
  in_progress: {
    text: "text-foreground font-medium",
    border: "border-primary/20",
    bg: "bg-primary/5",
    icon: "text-primary",
  },
  completed: {
    text: "text-muted-foreground/60",
    border: "border-transparent",
    bg: "",
    icon: "text-emerald-500",
  },
  cancelled: {
    text: "text-muted-foreground/50",
    border: "border-transparent",
    bg: "",
    icon: "text-amber-400",
  },
};

function PlanStatusIcon({ status }: { status: UiTodo["status"] }) {
  if (status === "completed") return <CheckCircle2 className="h-4 w-4 text-emerald-400" />;
  if (status === "in_progress") return (
    <span className="relative flex h-4 w-4 items-center justify-center">
      <span className="absolute inline-flex h-3 w-3 animate-ping rounded-full bg-primary/40" />
      <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-primary" />
    </span>
  );
  if (status === "cancelled") return <XCircle className="h-4 w-4 text-amber-400" />;
  return <Circle className="h-3 w-3 text-muted-foreground/40" />;
}

const PlanPanel = memo(function PlanPanel({
  todos,
  phase,
  isSending,
}: {
  todos: UiTodo[];
  phase: "plan" | "build" | "idle";
  isSending: boolean;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const userScrolledRef = useRef(false);
  const scrollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const done = useMemo(() => todos.filter((item) => item.status === "completed" || item.status === "cancelled").length, [todos]);
  const progress = todos.length > 0 ? Math.round((done / todos.length) * 100) : 0;
  const allDone = todos.length > 0 && done === todos.length;

  // Auto-scroll to in_progress item
  useEffect(() => {
    if (collapsed || userScrolledRef.current) return;
    const el = listRef.current?.querySelector("[data-plan-active]");
    if (el) el.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [todos, collapsed]);

  // Detect manual scroll
  const handleListScroll = useCallback(() => {
    userScrolledRef.current = true;
    if (scrollTimerRef.current) clearTimeout(scrollTimerRef.current);
    scrollTimerRef.current = setTimeout(() => { userScrolledRef.current = false; }, 250);
  }, []);

  // Cleanup timer on unmount
  useEffect(() => () => { if (scrollTimerRef.current) clearTimeout(scrollTimerRef.current); }, []);

  // Content height tracking for collapse animation
  const contentRef = useRef<HTMLDivElement>(null);
  const [contentHeight, setContentHeight] = useState<number | undefined>(undefined);
  useEffect(() => {
    if (!contentRef.current) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) setContentHeight(entry.contentRect.height);
    });
    observer.observe(contentRef.current);
    return () => observer.disconnect();
  }, []);

  return (
    <div className="p-3 space-y-2">
      {/* Header with progress */}
      <div className="flex items-center justify-between px-1 pb-1">
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          className="flex items-center gap-2 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
        >
          <ChevronDown className={`h-3.5 w-3.5 transition-transform duration-200 ${collapsed ? "-rotate-90" : ""}`} />
          {allDone ? "Completed" : `${done} of ${todos.length} done`}
        </button>
        {phase !== "idle" && (
          <Badge
            variant="outline"
            className={`px-2 py-0.5 text-[10px] font-semibold ${
              phase === "plan"
                ? "border-amber-500/40 text-amber-500 bg-amber-500/10"
                : "border-blue-500/40 text-blue-500 bg-blue-500/10"
            }`}
          >
            {phase === "plan" ? "PLANNING" : "BUILDING"}
          </Badge>
        )}
      </div>

      {/* Progress bar */}
      <div className="h-1 overflow-hidden rounded-full bg-border/30 mx-1">
        {isSending && todos.length === 0 ? (
          <div className="h-full w-full animate-pulse rounded-full bg-gradient-to-r from-transparent via-primary/40 to-transparent" />
        ) : (
          <div
            className={`h-full rounded-full transition-all duration-500 ${allDone ? "bg-emerald-500" : "bg-primary"}`}
            style={{ width: `${progress}%` }}
          />
        )}
      </div>

      {/* Todo list */}
      <div
        className="overflow-hidden transition-all duration-300"
        style={{
          maxHeight: collapsed ? 0 : contentHeight != null ? `${contentHeight}px` : "32rem",
          opacity: collapsed ? 0 : 1,
        }}
      >
        <div ref={contentRef}>
          {isSending && todos.length === 0 ? (
            <div className="space-y-1 py-1">
              {[1, 2, 3].map((i) => (
                <div key={i} className="flex items-center gap-3 px-2 py-2 animate-pulse">
                  <div className="h-4 w-4 rounded-full bg-muted-foreground/15" />
                  <div className="h-3.5 flex-1 rounded bg-muted-foreground/10" style={{ width: `${60 + i * 10}%` }} />
                </div>
              ))}
            </div>
          ) : (
            <div
              ref={listRef}
              className="max-h-[32rem] space-y-0.5 overflow-y-auto"
              onScroll={handleListScroll}
              role="list"
            >
              {todos.map((todo, index) => {
                const tone = planTone[todo.status];
                const isActive = todo.status === "in_progress";
                const isDone = todo.status === "completed" || todo.status === "cancelled";
                return (
                  <div
                    key={`${todo.content}-${index}`}
                    {...(isActive ? { "data-plan-active": true } : {})}
                    className={`flex items-start gap-3 rounded-lg border px-3 py-2 transition-all duration-200 ${tone.border} ${tone.bg}`}
                    role="listitem"
                  >
                    <div className="mt-0.5 flex h-4 w-4 flex-shrink-0 items-center justify-center">
                      <PlanStatusIcon status={todo.status} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <span className={`text-[13px] leading-snug ${tone.text} ${isDone ? "line-through" : ""}`}>
                        {todo.content}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
});

/* ------------------------------------------------------------------ */
/*  Unified diff viewer                                               */
/* ------------------------------------------------------------------ */
export const DiffViewer = memo(function DiffViewer({ diff }: { diff: string }) {
  const [expanded, setExpanded] = useState(false);
  const { lines, addCount, removeCount } = useMemo(() => {
    if (!diff) return { lines: [], addCount: 0, removeCount: 0 };
    const l = diff.split("\n");
    return {
      lines: l,
      addCount: l.filter((s) => s.startsWith("+") && !s.startsWith("+++")).length,
      removeCount: l.filter((s) => s.startsWith("-") && !s.startsWith("---")).length,
    };
  }, [diff]);
  if (!diff) return null;
  return (
    <div className="rounded-md border border-border/60 bg-muted/20 text-xs animate-slide-up my-1">
      <button
        type="button"
        onClick={() => setExpanded((o) => !o)}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        <span className="font-medium text-foreground">Diff</span>
        <span className="text-emerald-500">+{addCount}</span>
        <span className="text-red-500">-{removeCount}</span>
      </button>
      {expanded && (
        <div className="border-t border-border/40 px-3 py-2 overflow-x-auto max-h-[40vh] md:max-h-64 overflow-y-auto">
          <pre className="font-mono text-[11px] leading-relaxed">
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
        </div>
      )}
    </div>
  );
});

/* ------------------------------------------------------------------ */
/*  Main component                                                    */
/* ------------------------------------------------------------------ */
export function ChatWorkbench({
  agentName,
  runtimeKind,
  prompt,
  messages,
  activity,
  todos,
  phase,
  isSending,
  tokenReady,
  streamMode,
  requireApproval,
  approvalSupported,
  a2aTargetAgent,
  a2aTargetNamespace,
  a2aTimeoutSeconds,
  specialistSubagents,
  specialistTeamConfigured,
  agents,
  discoveryPeers,
  discoveryLoading,
  discoveryError,
  opencodeOutputFormat,
  opencodeAutonomous,
  opencodeMaxTurns,
  opencodeWorkingDirectory,
  factoryMode,
  summary,
  activeSessionId,
  sessionDirty,
  sessionSaving,
  lastSessionSaveAt,
  activeSessionSummary,
  activeMemoryRecords,
  agentMemoryRecords,
  onPromoteMemoryRecord,
  onEditMemoryRecord,
  onDeleteMemoryRecord,
  emptyMessage,
  error,
  onDownloadArtifact,
  onDownloadArtifactZip,
  onListArtifacts,
  onPreviewArtifact,
  onPromptChange,
  onToggleStreamMode,
  onToggleRequireApproval,
  onA2ATargetAgentChange,
  onA2ATargetNamespaceChange,
  onA2ATimeoutSecondsChange,
  onOpenCodeOutputFormatChange,
  onOpenCodeAutonomousChange,
  onOpenCodeMaxTurnsChange,
  onOpenCodeWorkingDirectoryChange,
  onFactoryModeChange,
  onSaveSession,
  canSubmit,
  onSubmit,
  onCancel,
}: ChatWorkbenchProps) {
  const {
    pendingQuestion, questionResponding, handleQuestionReply, handleQuestionReject,
    lastUserPrompt, handleReusePrompt, handleRegeneratePrompt,
  } = useChat();
  const { chatFocused, setChatFocused, selectedAgentDetail, selectedAgent, navigateToResource, handleCreateNew } = useWorkspace();
  const { token, namespace, canMutate } = useConnection();
  const chatSignals = useMemo(
    () => deriveAgentVisualSignals(selectedAgentDetail ?? { runtime_kind: runtimeKind }),
    [runtimeKind, selectedAgentDetail],
  );
  const ChatRuntimeIcon = chatSignals.runtime.icon;
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const isAtBottomRef = useRef(true);
  const scrollContainerRef = useRef<HTMLElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const planDock = usePlanDock({ todos, isSending });
  const planOpen = planDock.visible;
  const [filesOpen, setFilesOpen] = useState(false);
  const [memoryOpen, setMemoryOpen] = useState(false);
  const [memoryFilter, setMemoryFilter] = useState<"all" | "procedural" | "episodic" | "pinned">("all");
  const [memorySearch, setMemorySearch] = useState("");
  const [sessionMemoryExpanded, setSessionMemoryExpanded] = useState(false);
  const [agentMemoryExpanded, setAgentMemoryExpanded] = useState(false);
  const [editingMemoryId, setEditingMemoryId] = useState<number | null>(null);
  const [editingMemoryTopic, setEditingMemoryTopic] = useState("");
  const [editingMemoryContent, setEditingMemoryContent] = useState("");
  const [downloadingPath, setDownloadingPath] = useState<string | null>(null);
  const [fileExplorerView, setFileExplorerView] = useState<"all" | "changed">("all");
  /* ── @-mention A2A dropdown ── */
  const [mentionOpen, setMentionOpen] = useState(false);
  const [mentionIndex, setMentionIndex] = useState(0);
  const [mentionQuery, setMentionQuery] = useState("");
  const mentionContainerRef = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [attachments, setAttachments] = useState<Array<{ id: string; name: string; type: string; size: number; dataUrl: string; isImage: boolean }>>([]);
  const mentionableAgents = useMemo(() => agents.filter((a) => a.name !== agentName), [agents, agentName]);
  const filteredMentionAgents = useMemo(() => {
    const q = mentionQuery.toLowerCase();
    if (!q) return mentionableAgents;
    return mentionableAgents.filter((a) =>
      a.name.toLowerCase().includes(q) || a.namespace.toLowerCase().includes(q) || (a.model ?? "").toLowerCase().includes(q),
    );
  }, [mentionableAgents, mentionQuery]);
  const a2aMode = Boolean(a2aTargetAgent && a2aTargetNamespace);
  const specialistMode = specialistTeamConfigured;
  const showFactoryMode = isFactoryAgentName(agentName);
  const detailCount = (summary ? 1 : 0) + (activity.length > 0 ? 1 : 0);
  const planCount = todos.length;
  const memoryCount = agentMemoryRecords.length + activeMemoryRecords.length;
  const downloadableArtifacts = useMemo(() => collectDownloadableArtifacts(summary, messages), [summary, messages]);
  const teamRunSummary = useMemo(
    () => summarizeTeamRun(summary?.subagents ?? null, specialistSubagents, isSending),
    [isSending, specialistSubagents, summary?.subagents],
  );
  const filteredAgentMemoryRecords = useMemo(() => {
    const query = memorySearch.trim().toLowerCase();
    return agentMemoryRecords.filter((record) => {
      const matchesFilter = memoryFilter === "all"
        ? true
        : memoryFilter === "pinned"
          ? record.promoted
          : record.memory_type === memoryFilter;
      if (!matchesFilter) return false;
      if (!query) return true;
      return [record.topic, record.content, record.promote_reason, record.memory_type]
        .some((value) => String(value || "").toLowerCase().includes(query));
    });
  }, [agentMemoryRecords, memoryFilter, memorySearch]);
  const continuityHighlights = useMemo(() => buildContinuityHighlights(summary), [summary]);
  const chatMcpCapabilities = useMemo(() => {
    if (!selectedAgentDetail) {
      return [];
    }
    return extractMcpCapabilityIds(selectedAgentDetail)
      .map((id) => getCapabilitySignal(id))
      .sort((left, right) => right.priority - left.priority || left.label.localeCompare(right.label));
  }, [selectedAgentDetail]);
  const visibleChatMcpCapabilities = chatMcpCapabilities.slice(0, 4);
  const overflowChatMcpCapabilities = chatMcpCapabilities.slice(4);
  const visibleSessionMemoryRecords = sessionMemoryExpanded ? activeMemoryRecords : activeMemoryRecords.slice(0, 4);
  const visibleAgentMemoryRecords = agentMemoryExpanded ? filteredAgentMemoryRecords : filteredAgentMemoryRecords.slice(0, 8);
  const lastAssistantMessageId = useMemo(() => {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      if (messages[index]?.role === "assistant") return messages[index].id;
    }
    return null;
  }, [messages]);
  const starterPrompts = useMemo<StarterPrompt[]>(() => {
    const base: StarterPrompt[] = [
      {
        label: "Ship a scoped change",
        description: "Inspect the codebase, make a tight plan, and implement the highest-leverage fix safely.",
        prompt: `Inspect the current ${agentName || "workspace"} codebase, propose a concise plan, then implement the highest-leverage improvement with minimal unrelated changes.`,
      },
      {
        label: "Trace a regression",
        description: "Walk the failure path end-to-end, isolate root cause, and patch it with validation.",
        prompt: "Trace the latest regression end-to-end, identify the root cause, and patch it with the smallest safe change. Explain what broke and how you verified the fix.",
      },
      {
        label: "Review operational risk",
        description: "Prioritize bugs, missing guardrails, and test gaps like a production review.",
        prompt: "Review this code like a production readiness pass. Prioritize the highest-risk bugs, behavioral regressions, and missing tests, then fix the top issue.",
      },
      {
        label: "Summarize the session",
        description: "Capture current context, changed files, and the next three best moves for this thread.",
        prompt: "Summarize the current session state, important files, open risks, and the next three best moves to keep momentum.",
      },
    ];
    if (mentionableAgents.length > 0) {
      base.push({
        label: "Delegate to another agent",
        description: `Route this request through @${mentionableAgents[0].name} for cross-agent collaboration.`,
        prompt: `@${mentionableAgents[0].name} Please review the current codebase and suggest the most impactful improvement we can make this sprint.`,
      });
    }
    return base;
  }, [agentName, mentionableAgents]);

  // Resolve the Radix ScrollArea Viewport (the actual scrollable container)
  const scrollAreaRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (scrollAreaRef.current) {
      scrollContainerRef.current =
        scrollAreaRef.current.querySelector("[data-radix-scroll-area-viewport]") ?? scrollAreaRef.current;
    }
  }, []);

  useEffect(() => {
    // Always scroll to bottom when streaming or when new messages arrive
    const isStreamingActive = messages.length > 0 && messages[messages.length - 1]?.status === "streaming";
    if (!isAtBottomRef.current && !isStreamingActive) return;
    // Use requestAnimationFrame to ensure DOM has updated before scrolling
    requestAnimationFrame(() => {
      const viewport = scrollContainerRef.current;
      if (viewport) {
        viewport.scrollTop = viewport.scrollHeight;
      }
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages.length, messages[messages.length - 1]?.status, messages[messages.length - 1]?.content?.length, messages[messages.length - 1]?.reasoning?.length]);

  useEffect(() => {
    setDetailsOpen(false);
    setFilesOpen(false);
    setMemoryOpen(false);
    setFileExplorerView("all");
    setDownloadingPath(null);
  }, [agentName]);

  /* Close mention dropdown on click outside */
  useEffect(() => {
    if (!mentionOpen) return;
    function onDocClick(e: MouseEvent) {
      const container = mentionContainerRef.current;
      if (container && !container.contains(e.target as Node)) {
        setMentionOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [mentionOpen]);

  const focusComposer = useCallback(() => {
    requestAnimationFrame(() => {
      const textarea = textareaRef.current;
      if (!textarea) return;
      textarea.focus();
      const nextPosition = textarea.value.length;
      textarea.setSelectionRange(nextPosition, nextPosition);
    });
  }, []);

  const handlePromptReuse = useCallback((text: string) => {
    handleReusePrompt(text);
    focusComposer();
  }, [focusComposer, handleReusePrompt]);

  /* Detect if user is typing an @mention */
  function getMentionContext(text: string, cursorPos: number): { query: string; start: number } | null {
    const beforeCursor = text.slice(0, cursorPos);
    const match = beforeCursor.match(/@([^@\s]*)$/);
    if (!match) return null;
    return { query: match[1], start: beforeCursor.lastIndexOf("@") };
  }

  function handleMentionSelect(agent: AgentInfo) {
    const textarea = textareaRef.current;
    if (!textarea) return;
    const cursorPos = textarea.selectionStart ?? prompt.length;
    const ctx = getMentionContext(prompt, cursorPos);
    if (ctx) {
      const before = prompt.slice(0, ctx.start);
      const after = prompt.slice(cursorPos);
      const newText = `${before}@${agent.name} ${after}`;
      onPromptChange(newText);
      onA2ATargetAgentChange(agent.name);
      onA2ATargetNamespaceChange(agent.namespace);
      requestAnimationFrame(() => {
        const pos = ctx.start + agent.name.length + 2; // +2 for @ and space
        textarea.setSelectionRange(pos, pos);
        textarea.focus();
      });
    } else {
      onA2ATargetAgentChange(agent.name);
      onA2ATargetNamespaceChange(agent.namespace);
    }
    setMentionOpen(false);
    setMentionQuery("");
    setMentionIndex(0);
  }

  function clearA2A() {
    onA2ATargetAgentChange("");
    onA2ATargetNamespaceChange("");
    onA2ATimeoutSecondsChange("");
  }

  function parseA2AFromPrompt(text: string): AgentInfo | null {
    const match = text.match(/@([a-z0-9](?:[a-z0-9\-]*[a-z0-9])?)/i);
    if (!match) return null;
    const name = match[1];
    const agent = agents.find((a) => a.name.toLowerCase() === name.toLowerCase());
    return agent ?? null;
  }

  function handleSubmitWithMention() {
    const detectedAgent = parseA2AFromPrompt(prompt);
    if (detectedAgent && !a2aTargetAgent) {
      onA2ATargetAgentChange(detectedAgent.name);
      onA2ATargetNamespaceChange(detectedAgent.namespace);
    }
    // Prepend text file contents to prompt
    if (attachments.length > 0) {
      const textAttachments = attachments.filter((a) => !a.isImage);
      if (textAttachments.length > 0) {
        const prefix = textAttachments
          .map((a) => {
            try {
              const content = atob(a.dataUrl.split(",")[1] ?? "");
              return `--- File: ${a.name} ---\n${content}\n--- End File ---`;
            } catch { return ""; }
          })
          .filter(Boolean)
          .join("\n\n");
        if (prefix) {
          onPromptChange(prefix + "\n\n" + prompt);
        }
      }
    }
    // Capture attachments for the user message before clearing
    const messageAttachments = attachments.length > 0
      ? attachments.map(({ name, type, dataUrl, isImage }) => ({ name, type, dataUrl, isImage }))
      : undefined;
    setAttachments([]);
    onSubmit(messageAttachments);
  }

  /* ── File attachment helpers ── */
  function processFiles(files: FileList | File[]) {
    const fileArray = Array.from(files);
    fileArray.forEach((file) => {
      if (file.size > 10 * 1024 * 1024) return; // 10MB limit
      const reader = new FileReader();
      reader.onload = () => {
        const dataUrl = reader.result as string;
        const isImage = file.type.startsWith("image/");
        setAttachments((prev) => [
          ...prev,
          { id: crypto.randomUUID(), name: file.name, type: file.type, size: file.size, dataUrl, isImage },
        ]);
      };
      reader.readAsDataURL(file);
    });
  }

  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    if (e.target.files && e.target.files.length > 0) {
      processFiles(e.target.files);
      e.target.value = ""; // reset so same file can be re-selected
    }
  }

  function handlePaste(e: React.ClipboardEvent) {
    const items = e.clipboardData?.items;
    if (!items) return;
    const files: File[] = [];
    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      if (item.kind === "file") {
        const file = item.getAsFile();
        if (file) files.push(file);
      }
    }
    if (files.length > 0) {
      e.preventDefault();
      processFiles(files);
    }
  }

  function removeAttachment(id: string) {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
  }

  const findPromptForRegenerate = useCallback((messageIndex: number): string | null => {
    for (let index = messageIndex - 1; index >= 0; index -= 1) {
      const candidate = messages[index];
      if (candidate.role === "user" && candidate.content.trim()) {
        return candidate.content;
      }
    }
    return lastUserPrompt;
  }, [lastUserPrompt, messages]);

  const onSaveSessionRef = useRef(onSaveSession);
  const sessionSavingRef = useRef(sessionSaving);
  const messagesLengthRef = useRef(messages.length);
  useEffect(() => { onSaveSessionRef.current = onSaveSession; }, [onSaveSession]);
  useEffect(() => { sessionSavingRef.current = sessionSaving; }, [sessionSaving]);
  useEffect(() => { messagesLengthRef.current = messages.length; }, [messages.length]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== "s") return;
      if (!messagesLengthRef.current || sessionSavingRef.current) return;
      event.preventDefault();
      onSaveSessionRef.current();
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  const stableListArtifacts = useCallback(() => onListArtifacts(), [onListArtifacts]);
  const stableDownloadArtifact = useCallback(
    (path: string, filename?: string) => onDownloadArtifact(path, filename),
    [onDownloadArtifact],
  );
  const stableDownloadArtifactZip = useCallback(() => onDownloadArtifactZip(), [onDownloadArtifactZip]);
  const stablePreviewArtifact = useCallback((path: string) => onPreviewArtifact(path), [onPreviewArtifact]);
  const stableLoadSessionDiff = useCallback(() => {
    if (!token || !summary?.threadId) return Promise.resolve("");
    return fetchSessionDiff(token, namespace, agentName, summary.threadId);
  }, [agentName, namespace, summary?.threadId, token]);

  async function handleArtifactDownload(path: string, filename?: string) {
    try {
      setDownloadingPath(path);
      await onDownloadArtifact(path, filename);
    } finally {
      setDownloadingPath((current) => (current === path ? null : current));
    }
  }

  return (
    <div className="flex h-full min-w-0 flex-1 flex-col overflow-hidden rounded-none border border-border/60 bg-[linear-gradient(180deg,rgba(255,255,255,0.04),rgba(255,255,255,0.01)_14rem)] shadow-[0_26px_70px_-48px_rgba(0,0,0,0.8)]">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border/70 bg-background/80 px-2.5 py-1.5 backdrop-blur-md">
        <div className="flex items-center gap-2">
          {agentName && (
            <span className={`h-2 w-2 shrink-0 rounded-full ${
              selectedAgent?.status === "running" ? "bg-emerald-400" :
              selectedAgent?.status === "pending" || selectedAgent?.status === "creating" ? "bg-amber-400" :
              selectedAgent?.status === "error" || selectedAgent?.status === "failed" ? "bg-red-400" :
              "bg-muted-foreground/40"
            }`} />
          )}
          <h2 className="text-[13px] font-semibold tracking-tight">
            {agentName ?? "Choose an agent"}
          </h2>
          {agentName && selectedAgent?.status && (
            <span className="rounded-full border border-border/60 bg-muted/30 px-1.5 py-0 text-[9px] font-medium text-muted-foreground">
              {selectedAgent.status}
            </span>
          )}
          {agentName && selectedAgent?.model && (
            <span className="hidden text-[10px] text-muted-foreground/70 xl:block">{selectedAgent.model}</span>
          )}
          {agentName && canMutate && (
            <Button variant="ghost" size="sm" className="h-6 gap-0.5 rounded-full px-1.5 text-[10px]" onClick={handleCreateNew}>
              <Plus className="h-3 w-3" />
              New
            </Button>
          )}
          {agentName && (
            <Button variant="ghost" size="sm" className="h-6 gap-0.5 rounded-full px-1.5 text-[10px]" onClick={() => navigateToResource("agents", agentName)}>
              <Cog className="h-3 w-3" />
              Manage
            </Button>
          )}
          {agentName && visibleChatMcpCapabilities.length > 0 && (
            <TooltipProvider delayDuration={120}>
              <div className="flex flex-wrap items-center gap-1.5">
                {visibleChatMcpCapabilities.map((capability) => (
                  <Tooltip key={capability.id}>
                    <TooltipTrigger asChild>
                      <Badge variant="outline" className={`h-5 rounded-full px-1.5 text-[9px] ${capability.tone}`}>
                        <capability.icon className="mr-0.5 h-2.5 w-2.5" />
                        {capability.shortLabel}
                      </Badge>
                    </TooltipTrigger>
                    <TooltipContent side="bottom" className="max-w-[220px]">
                      <p className="text-xs font-medium text-foreground">{capability.label}</p>
                      <p className="mt-1 text-xs leading-5 text-muted-foreground">
                        Attached through the MCP registry using saved connections, shared hub routes, or managed sidecars.
                      </p>
                    </TooltipContent>
                  </Tooltip>
                ))}
                {overflowChatMcpCapabilities.length > 0 ? (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Badge variant="outline" className="h-6 rounded-full border-border/60 bg-background/70 px-2 text-[10px] text-muted-foreground">
                        +{overflowChatMcpCapabilities.length}
                      </Badge>
                    </TooltipTrigger>
                    <TooltipContent side="bottom" className="max-w-[220px]">
                      <p className="text-xs font-medium text-foreground">Additional MCP capabilities</p>
                      <p className="mt-1 text-xs leading-5 text-muted-foreground">
                        {overflowChatMcpCapabilities.map((capability) => capability.label).join(", ")}
                      </p>
                    </TooltipContent>
                  </Tooltip>
                ) : null}
              </div>
            </TooltipProvider>
          )}
        </div>
        <div className="flex items-center gap-2">
          {activeSessionId && (
            <div className="hidden items-center gap-2 rounded-full border border-border/70 bg-muted/20 px-2.5 py-1 text-[11px] text-muted-foreground lg:flex">
              <Brain className="h-3.5 w-3.5 text-primary" />
              <span className="font-mono text-[10px] text-foreground/80">{activeSessionId.slice(0, 8)}</span>
              <Badge variant={sessionSaving ? "default" : sessionDirty ? "secondary" : "outline"} className="px-1 py-0 text-[10px]">
                {sessionSaving ? "Saving" : sessionDirty ? "Unsaved" : "Saved"}
              </Badge>
              {lastSessionSaveAt && <span>{formatRelativeTime(lastSessionSaveAt)}</span>}
              {continuityHighlights.slice(0, 2).map((item) => (
                <Badge key={item} variant="outline" className="px-1 py-0 text-[10px] text-primary">
                  {item}
                </Badge>
              ))}
            </div>
          )}
          {runtimeKind === "opencode" && agentName && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-6 gap-0.5 rounded-full px-1.5 text-[10px]"
              onClick={() => { planDock.toggle(); if (!planOpen) { setDetailsOpen(false); setFilesOpen(false); setMemoryOpen(false); } }}
            >
              {planOpen ? <PanelRightClose className="h-3 w-3" /> : <PanelRightOpen className="h-3 w-3" />}
              Plan
              <Badge variant="outline" className="ml-0.5 px-1 py-0 text-[9px]">
                {planCount}
              </Badge>
            </Button>
          )}
          {agentName && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-6 gap-0.5 rounded-full px-1.5 text-[10px]"
              onClick={() => {
                const nextOpen = !(filesOpen && fileExplorerView === "all");
                setFileExplorerView("all");
                setFilesOpen(nextOpen);
                if (nextOpen) {
                  setDetailsOpen(false);
                  if (planOpen) planDock.toggle();
                  setMemoryOpen(false);
                }
              }}
            >
              <FolderOpen className="h-3 w-3" />
              Files
            </Button>
          )}
          {runtimeKind === "opencode" && summary?.threadId && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-6 gap-0.5 rounded-full px-1.5 text-[10px]"
              onClick={() => {
                const nextOpen = !(filesOpen && fileExplorerView === "changed");
                setFileExplorerView("changed");
                setFilesOpen(nextOpen);
                if (nextOpen) {
                  setDetailsOpen(false);
                  if (planOpen) planDock.toggle();
                  setMemoryOpen(false);
                }
              }}
            >
              <FileDiff className="h-3 w-3" />
              Changes
            </Button>
          )}
          {memoryCount > 0 && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-6 gap-0.5 rounded-full px-1.5 text-[10px]"
              onClick={() => { setMemoryOpen((open) => !open); if (!memoryOpen) { setDetailsOpen(false); if (planOpen) planDock.toggle(); setFilesOpen(false); } }}
            >
              <MemoryStick className="h-3 w-3" />
              Memory
              <Badge variant="outline" className="ml-0.5 px-1 py-0 text-[9px]">
                {memoryCount}
              </Badge>
            </Button>
          )}
          {detailCount > 0 && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-6 gap-0.5 rounded-full px-1.5 text-[10px]"
              onClick={() => { setDetailsOpen((open) => !open); if (!detailsOpen) { if (planOpen) planDock.toggle(); setFilesOpen(false); setMemoryOpen(false); } }}
            >
              {detailsOpen ? <PanelRightClose className="h-3 w-3" /> : <PanelRightOpen className="h-3 w-3" />}
              Details
              <Badge variant="outline" className="ml-0.5 px-1 py-0 text-[9px]">
                {detailCount}
              </Badge>
            </Button>
          )}
          <Badge variant={streamMode ? "default" : "secondary"} className="text-[9px] px-1.5 py-0 h-5">
            {streamMode ? "stream" : "single"}
          </Badge>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-6 w-6 rounded-full"
            onClick={() => setChatFocused(!chatFocused)}
            title={chatFocused ? "Exit focused mode" : "Focused mode"}
            aria-label={chatFocused ? "Exit focused mode" : "Enter focused mode"}
          >
            {chatFocused ? <Minimize2 className="h-3 w-3" /> : <Maximize2 className="h-3 w-3" />}
          </Button>
        </div>
      </div>

      <div className="relative flex min-h-0 flex-1 overflow-hidden">
        <ScrollArea
          className="flex-1 min-h-0"
          ref={scrollAreaRef}
          onScrollCapture={(e) => {
            const el = e.currentTarget.querySelector("[data-radix-scroll-area-viewport]") as HTMLElement | null;
            if (el) {
              isAtBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
            }
          }}
        >
          <div className="mx-auto flex w-full max-w-6xl flex-col gap-3 px-4 py-3" aria-label="Conversation history" aria-live="polite" aria-atomic="false">
            {messages.length === 0 && (
              <div className="space-y-3">
                <EmptyState
                  icon={MessageSquare}
                  title="No messages yet"
                  description={emptyMessage || (mentionableAgents.length > 0
                    ? "Send your first message or type @ to delegate to another agent. Try asking the agent to analyze code, fix a bug, or build a new feature."
                    : "Send your first message to start a conversation. Try asking the agent to analyze code, fix a bug, or build a new feature.")}
                />
                <div className={`${SURFACE_PANEL_CLASS} p-2.5`}>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <div className="text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">Starter prompts</div>
                      <div className="mt-1 text-xs text-muted-foreground">Prime the composer with a sharper brief instead of starting from a blank box.</div>
                    </div>
                    <Badge variant="outline" className="text-[10px]">Click to draft</Badge>
                  </div>
                  <div className="mt-3 grid gap-2 sm:grid-cols-2">
                    {starterPrompts.map((item, index) => (
                      <button
                        key={item.label}
                        type="button"
                        onClick={() => handlePromptReuse(item.prompt)}
                        className="group rounded-sm border border-border/70 bg-background/70 px-3 py-2 text-left shadow-sm transition-all duration-200 hover:-translate-y-px hover:border-primary/30 hover:bg-primary/5"
                        style={{ animationDelay: `${index * 45}ms`, animationFillMode: "backwards" }}
                      >
                        <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                          <Zap className="h-3.5 w-3.5 text-primary transition-transform duration-200 group-hover:scale-110" />
                          {item.label}
                        </div>
                        <div className="mt-2 text-[11px] leading-relaxed text-muted-foreground">{item.description}</div>
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {teamRunSummary && (
              <div className="rounded-sm border border-primary/20 bg-primary/[0.06] p-2.5 shadow-sm shadow-primary/10 backdrop-blur-sm">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.16em] text-primary">
                      <Activity className="h-3.5 w-3.5" />
                      Team coordination
                    </div>
                    <div className="mt-1 text-sm font-medium text-foreground">
                      {teamRunSummary.status === "running"
                        ? "Agents are actively coordinating on this request."
                        : teamRunSummary.status === "complete"
                          ? "The team run finished and left structured handoff data."
                          : teamRunSummary.status === "needs-review"
                            ? "The team run completed with failures or blocked steps."
                            : "The specialist team is configured and ready for the next request."}
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      Watch live delegation in the Team panel beside the chat, or below it on narrower screens. Open Files for result artifacts and Details for the full execution log.
                    </div>
                  </div>
                  <Badge
                    variant={teamRunSummary.status === "needs-review" ? "destructive" : teamRunSummary.status === "running" ? "secondary" : "outline"}
                    className="text-[10px] uppercase tracking-[0.12em]"
                  >
                    {teamRunSummary.status === "needs-review"
                      ? "needs review"
                      : teamRunSummary.status === "complete"
                        ? "complete"
                        : teamRunSummary.status}
                  </Badge>
                </div>
                <div className="mt-3 flex flex-wrap gap-2 text-[10px]">
                  <Badge variant="outline">{teamRunSummary.memberCount} member{teamRunSummary.memberCount === 1 ? "" : "s"}</Badge>
                  {teamRunSummary.completedCount > 0 && <Badge variant="outline">{teamRunSummary.completedCount} done</Badge>}
                  {teamRunSummary.runningCount > 0 && <Badge variant="outline">{teamRunSummary.runningCount} running</Badge>}
                  {teamRunSummary.queuedCount > 0 && <Badge variant="outline">{teamRunSummary.queuedCount} queued</Badge>}
                  {teamRunSummary.failedCount > 0 && <Badge variant="outline">{teamRunSummary.failedCount} failed</Badge>}
                  {teamRunSummary.resultFileCount > 0 && <Badge variant="outline">{teamRunSummary.resultFileCount} result file{teamRunSummary.resultFileCount === 1 ? "" : "s"}</Badge>}
                  {teamRunSummary.sharedFileCount > 0 && <Badge variant="outline">{teamRunSummary.sharedFileCount} shared input{teamRunSummary.sharedFileCount === 1 ? "" : "s"}</Badge>}
                  {teamRunSummary.sharedSandboxSession && <Badge variant="outline">shared sandbox</Badge>}
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button
                    type="button"
                    size="sm"
                    className="h-7 gap-1.5 px-2 text-[10px]"
                    onClick={() => {
                      setFileExplorerView("all");
                      setFilesOpen(true);
                      setDetailsOpen(false);
                      if (planOpen) planDock.toggle();
                      setMemoryOpen(false);
                    }}
                  >
                    <FolderOpen className="h-3.5 w-3.5" />
                    Open files
                  </Button>
                  {detailCount > 0 && (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-7 gap-1.5 px-2 text-[10px]"
                      onClick={() => {
                        setDetailsOpen(true);
                        if (planOpen) planDock.toggle();
                        setFilesOpen(false);
                        setMemoryOpen(false);
                      }}
                    >
                      <PanelRightOpen className="h-3.5 w-3.5" />
                      Open details
                    </Button>
                  )}
                </div>
              </div>
            )}

            {downloadableArtifacts.length > 0 && (
              <div className={`${SURFACE_PANEL_CLASS} p-3`}>
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
                    <FileText className="h-3.5 w-3.5" />
                    Run files
                  </div>
                  <Badge variant="outline" className="text-[10px]">{downloadableArtifacts.length} ready</Badge>
                </div>
                <div className="mb-3 text-xs text-muted-foreground">
                  Workspace files produced or explicitly handed off during this run.
                </div>
                <div className="flex flex-wrap gap-2">
                  {downloadableArtifacts.map((artifact) => {
                    const isLoading = downloadingPath === artifact.path;
                    return (
                      <button
                        key={artifact.path}
                        type="button"
                        onClick={() => void handleArtifactDownload(artifact.path, artifact.filename)}
                        className="group flex min-w-[13rem] items-center gap-2 rounded-xl border border-border/70 bg-muted/30 px-3 py-2 text-left transition hover:border-primary/30 hover:bg-primary/5"
                      >
                        <div className="rounded-lg bg-primary/10 p-1.5 text-primary">
                          {isLoading ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <div className="truncate text-sm font-medium text-foreground">{artifact.filename}</div>
                            <Badge variant="outline" className="h-5 px-1.5 text-[9px] uppercase tracking-[0.12em]">
                              {artifact.source === "result" ? "team output" : "artifact"}
                            </Badge>
                          </div>
                          <div className="truncate text-[11px] text-muted-foreground">{artifact.path}</div>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {messages.map((message, i) =>
              message.role === "tool" ? (
                <ToolBubble key={message.id} message={message} />
              ) : (
                <MessageBubble
                  key={message.id}
                  message={message}
                  index={i}
                  onEditPrompt={handlePromptReuse}
                  onRegeneratePrompt={handleRegeneratePrompt}
                  promptForRegenerate={message.role === "assistant" ? findPromptForRegenerate(i) : null}
                  liveActivity={message.id === lastAssistantMessageId ? activity : []}
                  phase={message.id === lastAssistantMessageId ? phase : "idle"}
                  operationSummary={message.role === "assistant"
                    ? buildInlineOperationSummary(message, message.id === lastAssistantMessageId ? summary : null)
                    : null}
                  agents={agents}
                />
              ),
            )}
            <div ref={messagesEndRef} />
          </div>
        </ScrollArea>

        {runtimeKind === "opencode" && planOpen && agentName && (
          <aside className={`${DRAWER_PANEL_CLASS} w-[min(24rem,calc(100%-1.5rem))]`}>
            <div className="flex items-center justify-between border-b border-border/60 px-3 py-2.5">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">OpenCode</div>
                <div className="text-sm font-semibold">Plan tracker</div>
              </div>
              <Button type="button" variant="ghost" size="icon" className="h-7 w-7" onClick={() => planDock.toggle()} aria-label="Close plan panel">
                <PanelRightClose className="h-3.5 w-3.5" />
              </Button>
            </div>
            <ScrollArea className="min-h-0 flex-1">
              {todos.length > 0 ? (
                <PlanPanel todos={todos} phase={phase} isSending={isSending} />
              ) : (
                <div className="flex h-full items-center justify-center p-6 text-center text-sm text-muted-foreground">
                  OpenCode will populate this panel after it creates a todo plan for the current task.
                </div>
              )}
            </ScrollArea>
          </aside>
        )}

        {detailsOpen && detailCount > 0 && (
          <aside className={`${DRAWER_PANEL_CLASS} w-[min(24rem,calc(100%-1.5rem))]`}>
            <div className="flex items-center justify-between border-b border-border/60 px-3 py-2.5">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">Inspector</div>
                <div className="text-sm font-semibold">Run details</div>
              </div>
              <Button type="button" variant="ghost" size="icon" className="h-7 w-7" onClick={() => setDetailsOpen(false)} aria-label="Close details panel">
                <PanelRightClose className="h-3.5 w-3.5" />
              </Button>
            </div>
            <ScrollArea className="min-h-0 flex-1">
              <div className="space-y-3 p-3">
                {summary && <OperationLog summary={summary} className="mx-3 mb-2" />}
                {activeSessionSummary && (
                  <div className={`${SURFACE_PANEL_CLASS} space-y-3 p-3`}>
                    <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
                      <Brain className="h-3.5 w-3.5" />
                      Session memory
                    </div>
                    <div className="flex flex-wrap gap-2 text-[11px] text-muted-foreground">
                      <Badge variant="outline">{activeSessionSummary.message_count} messages</Badge>
                      {activeSessionSummary.tool_names.length > 0 && (
                        <Badge variant="outline">{truncateText(activeSessionSummary.tool_names.join(", "), 40)}</Badge>
                      )}
                      {activeSessionId && <Badge variant="outline">session {activeSessionId.slice(0, 8)}</Badge>}
                      <Badge variant={sessionSaving ? "default" : sessionDirty ? "secondary" : "outline"}>
                        {sessionSaving ? "Saving" : sessionDirty ? "Unsaved" : "Saved"}
                      </Badge>
                    </div>
                    {lastSessionSaveAt && (
                      <div className="text-[11px] text-muted-foreground">Last saved {formatRelativeTime(lastSessionSaveAt)}</div>
                    )}
                    {continuityHighlights.length > 0 && (
                      <div className="flex flex-wrap gap-2">
                        {continuityHighlights.map((item) => (
                          <Badge key={item} variant="secondary" className="bg-primary/10 text-primary">
                            {item}
                          </Badge>
                        ))}
                      </div>
                    )}
                    {activeSessionSummary.last_user_message && (
                      <div className="space-y-1">
                        <div className="text-[11px] font-medium text-muted-foreground">Last user request</div>
                        <div className="rounded-xl border border-border/60 bg-background/80 px-3 py-2 text-xs leading-relaxed text-foreground/85">
                          {truncateText(activeSessionSummary.last_user_message, 180)}
                        </div>
                      </div>
                    )}
                    {activeSessionSummary.last_assistant_message && (
                      <div className="space-y-1">
                        <div className="text-[11px] font-medium text-muted-foreground">Last assistant takeaway</div>
                        <div className="rounded-xl border border-border/60 bg-background/80 px-3 py-2 text-xs leading-relaxed text-foreground/85">
                          {truncateText(activeSessionSummary.last_assistant_message, 220)}
                        </div>
                      </div>
                    )}
                    {(activeSessionSummary.memory_candidates.episodic.length > 0 || activeSessionSummary.memory_candidates.procedural.length > 0) && (
                      <div className="space-y-2">
                        {activeSessionSummary.memory_candidates.episodic.map((candidate, index) => (
                          <div key={`episodic-${index}`} className="rounded-xl border border-border/60 bg-background/80 px-3 py-2 text-xs text-muted-foreground">
                            <div className="font-medium text-foreground/85">{candidate.type}</div>
                            {candidate.names && candidate.names.length > 0 && <div>{truncateText(candidate.names.join(", "), 120)}</div>}
                            {candidate.text && <div>{truncateText(candidate.text, 140)}</div>}
                          </div>
                        ))}
                        {activeSessionSummary.memory_candidates.procedural.map((candidate, index) => (
                          <div key={`procedural-${index}`} className="rounded-xl border border-primary/20 bg-primary/5 px-3 py-2 text-xs text-muted-foreground">
                            <div className="font-medium text-foreground/85">{candidate.type}</div>
                            {candidate.text && <div>{truncateText(candidate.text, 160)}</div>}
                            {candidate.names && candidate.names.length > 0 && <div>{truncateText(candidate.names.join(", "), 120)}</div>}
                          </div>
                        ))}
                      </div>
                    )}
                    {(activeMemoryRecords.length > 0 || agentMemoryRecords.length > 0) && (
                      <div className="rounded-xl border border-primary/15 bg-primary/5 px-3 py-3 text-xs text-muted-foreground">
                        <div className="flex items-center justify-between gap-2">
                          <div>
                            <div className="font-medium text-foreground">Memory workspace</div>
                            <div className="mt-1 text-[11px]">
                              Inspect session and durable memory from the dedicated memory drawer.
                            </div>
                          </div>
                          <Button type="button" size="sm" className="h-7 px-2 text-[10px]" onClick={() => { setMemoryOpen(true); setDetailsOpen(false); }}>
                            Open memory
                          </Button>
                        </div>
                      </div>
                    )}
                  </div>
                )}
                {activity.length > 0 && (
                  <ActivityTimeline
                    activity={activity}
                    showSummary={true}
                    showFilters={false}
                    autoScroll={isSending}
                    heightClass="max-h-[28rem]"
                  />
                )}
              </div>
            </ScrollArea>
          </aside>
        )}

        {filesOpen && agentName && (
          <aside className={`${DRAWER_PANEL_CLASS} w-[min(76rem,calc(100%-1.5rem))]`}>
            <div className="flex items-center justify-between border-b border-border/60 px-3 py-2.5">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">Workspace</div>
                <div className="text-sm font-semibold">Agent files</div>
              </div>
              <Button type="button" variant="ghost" size="icon" className="h-7 w-7" onClick={() => setFilesOpen(false)} aria-label="Close files panel">
                <PanelRightClose className="h-3.5 w-3.5" />
              </Button>
            </div>
            <FileExplorer
              agentName={agentName}
              onLoad={stableListArtifacts}
              onDownload={stableDownloadArtifact}
              onDownloadAll={stableDownloadArtifactZip}
              onPreview={stablePreviewArtifact}
              onLoadDiff={runtimeKind === "opencode" && summary?.threadId ? stableLoadSessionDiff : undefined}
              preferredView={fileExplorerView}
              liveUpdatesEnabled={isSending || phase !== "idle"}
            />
          </aside>
        )}

        {memoryOpen && agentName && (
          <aside className={`${DRAWER_PANEL_CLASS} w-[min(30rem,calc(100%-1.5rem))]`}>
            <div className="flex items-center justify-between border-b border-border/60 px-3 py-2.5">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">Memory workspace</div>
                <div className="text-sm font-semibold">Session + durable memory</div>
              </div>
              <Button type="button" variant="ghost" size="icon" className="h-7 w-7" onClick={() => setMemoryOpen(false)} aria-label="Close memory panel">
                <PanelRightClose className="h-3.5 w-3.5" />
              </Button>
            </div>
            <ScrollArea className="min-h-0 flex-1">
              <div className="space-y-4 p-3">
                {activeSessionSummary && (
                  <div className={`${SURFACE_PANEL_CLASS} space-y-3 p-3`}>
                    <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
                      <Brain className="h-3.5 w-3.5" />
                      Session memory
                    </div>
                    <div className="flex flex-wrap gap-2 text-[11px] text-muted-foreground">
                      <Badge variant="outline">{activeSessionSummary.message_count} messages</Badge>
                      {activeSessionId && <Badge variant="outline">session {activeSessionId.slice(0, 8)}</Badge>}
                    </div>
                    {(activeSessionSummary.memory_candidates.episodic.length > 0 || activeSessionSummary.memory_candidates.procedural.length > 0) && (
                      <div className="space-y-2">
                        {activeSessionSummary.memory_candidates.episodic.map((candidate, index) => (
                          <div key={`episodic-drawer-${index}`} className="rounded-xl border border-border/60 bg-background/80 px-3 py-2 text-xs text-muted-foreground">
                            <div className="font-medium text-foreground/85">{candidate.type}</div>
                            {candidate.names && candidate.names.length > 0 && <div>{truncateText(candidate.names.join(", "), 120)}</div>}
                            {candidate.text && <div>{truncateText(candidate.text, 200)}</div>}
                          </div>
                        ))}
                        {activeSessionSummary.memory_candidates.procedural.map((candidate, index) => (
                          <div key={`procedural-drawer-${index}`} className="rounded-xl border border-primary/20 bg-primary/5 px-3 py-2 text-xs text-muted-foreground">
                            <div className="font-medium text-foreground/85">{candidate.type}</div>
                            {candidate.text && <div>{truncateText(candidate.text, 220)}</div>}
                            {candidate.names && candidate.names.length > 0 && <div>{truncateText(candidate.names.join(", "), 120)}</div>}
                          </div>
                        ))}
                      </div>
                    )}
                    {activeMemoryRecords.length > 0 && (
                      <div className="space-y-2">
                        <div className="flex items-center justify-between gap-2">
                          <div className="text-[11px] font-medium text-muted-foreground">Persisted session records</div>
                          {activeMemoryRecords.length > visibleSessionMemoryRecords.length && (
                            <Button type="button" variant="ghost" size="sm" className="h-6 px-2 text-[10px]" onClick={() => setSessionMemoryExpanded((open) => !open)}>
                              {sessionMemoryExpanded ? "Show less" : `Show all (${activeMemoryRecords.length})`}
                            </Button>
                          )}
                        </div>
                        {visibleSessionMemoryRecords.map((record) => (
                          <MemoryRecordCard
                            key={`drawer-session-${record.id}`}
                            record={record}
                            activeSessionId={activeSessionId}
                            compact={!sessionMemoryExpanded}
                            onPromote={onPromoteMemoryRecord}
                            onDelete={onDeleteMemoryRecord}
                          />
                        ))}
                      </div>
                    )}
                  </div>
                )}

                <div className={`${SURFACE_PANEL_CLASS} space-y-3 p-3`}>
                  <div className="flex items-center justify-between gap-2">
                    <div>
                      <div className="text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">Durable memory manager</div>
                      <div className="mt-1 text-xs text-muted-foreground">Search, pin, edit, and prune cross-session memory.</div>
                    </div>
                    <Badge variant="outline">{filteredAgentMemoryRecords.length} shown</Badge>
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {(["all", "procedural", "episodic", "pinned"] as const).map((filterKey) => (
                      <Button
                        key={filterKey}
                        type="button"
                        variant={memoryFilter === filterKey ? "default" : "outline"}
                        size="sm"
                        className="h-6 px-2 text-[10px]"
                        onClick={() => setMemoryFilter(filterKey)}
                      >
                        {filterKey}
                      </Button>
                    ))}
                  </div>
                  <div className="relative">
                    <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      value={memorySearch}
                      onChange={(e) => setMemorySearch(e.target.value)}
                      className="h-8 pl-7 text-xs"
                      placeholder="Search topic, content, or reason"
                    />
                  </div>
                  {filteredAgentMemoryRecords.length > visibleAgentMemoryRecords.length && (
                    <div className="flex justify-end">
                      <Button type="button" variant="ghost" size="sm" className="h-6 px-2 text-[10px]" onClick={() => setAgentMemoryExpanded((open) => !open)}>
                        {agentMemoryExpanded ? "Show less" : `Show all (${filteredAgentMemoryRecords.length})`}
                      </Button>
                    </div>
                  )}
                  {visibleAgentMemoryRecords.map((record) => (
                    <MemoryRecordCard
                      key={`drawer-manager-${record.id}`}
                      record={record}
                      activeSessionId={activeSessionId}
                      editable={true}
                      compact={!agentMemoryExpanded}
                      editingMemoryId={editingMemoryId}
                      editingMemoryTopic={editingMemoryTopic}
                      editingMemoryContent={editingMemoryContent}
                      onStartEdit={(current) => {
                        setEditingMemoryId(current.id);
                        setEditingMemoryTopic(current.topic || "");
                        setEditingMemoryContent(current.content || "");
                      }}
                      onEditTopicChange={setEditingMemoryTopic}
                      onEditContentChange={setEditingMemoryContent}
                      onSaveEdit={(recordId) => {
                        onEditMemoryRecord(recordId, { topic: editingMemoryTopic, content: editingMemoryContent });
                        setEditingMemoryId(null);
                      }}
                      onCancelEdit={() => setEditingMemoryId(null)}
                      onPromote={onPromoteMemoryRecord}
                      onDelete={onDeleteMemoryRecord}
                    />
                  ))}
                  {filteredAgentMemoryRecords.length === 0 && (
                    <div className="rounded-xl border border-dashed border-border/60 px-3 py-4 text-center text-xs text-muted-foreground">
                      No memory records match the current filter.
                    </div>
                  )}
                </div>
              </div>
            </ScrollArea>
          </aside>
        )}
      </div>

      {/* Composer */}
      <div className="space-y-1 border-t border-border/60 bg-background/92 px-3 py-1.5 backdrop-blur-xl">
        {!chatFocused && (
          <>
        {/* Compact controls row: toggles + settings drawer */}
        <div className="flex flex-wrap items-center gap-2">
          {showFactoryMode && (
            <Badge variant="outline" className="h-6 rounded-full border-primary/25 bg-primary/5 px-2 text-[10px] uppercase tracking-[0.14em] text-primary/80">
              Factory {factoryModeShortLabel(factoryMode)}
            </Badge>
          )}
          <label className="flex items-center gap-1.5 cursor-pointer text-xs">
            <input
              type="checkbox"
              checked={streamMode}
              onChange={(e) => onToggleStreamMode(e.target.checked)}
              className="h-3.5 w-3.5 rounded border-input"
            />
            Stream
          </label>
          <label className="flex items-center gap-1.5 cursor-pointer text-xs">
            <input
              type="checkbox"
              checked={requireApproval}
              disabled={!approvalSupported}
              onChange={(e) => onToggleRequireApproval(e.target.checked)}
              className="h-3.5 w-3.5 rounded border-input"
            />
            {approvalSupported
              ? "Require approval"
              : <span className="opacity-60">Approval unavailable</span>
            }
          </label>
          <div className="ml-auto">
            <ChatSettingsDrawer
              runtimeKind={runtimeKind}
              signalSource={selectedAgentDetail ?? { runtime_kind: runtimeKind }}
              a2aTargetAgent={a2aTargetAgent}
              a2aTargetNamespace={a2aTargetNamespace}
              a2aTimeoutSeconds={a2aTimeoutSeconds}
              onA2ATargetAgentChange={onA2ATargetAgentChange}
              onA2ATargetNamespaceChange={onA2ATargetNamespaceChange}
              onA2ATimeoutSecondsChange={onA2ATimeoutSecondsChange}
              discoveryPeers={discoveryPeers}
              discoveryLoading={discoveryLoading}
              discoveryError={discoveryError}
              opencodeOutputFormat={opencodeOutputFormat}
              opencodeAutonomous={opencodeAutonomous}
              opencodeMaxTurns={opencodeMaxTurns}
              opencodeWorkingDirectory={opencodeWorkingDirectory}
              showFactoryMode={showFactoryMode}
              factoryMode={factoryMode}
              onOpenCodeOutputFormatChange={onOpenCodeOutputFormatChange}
              onOpenCodeAutonomousChange={onOpenCodeAutonomousChange}
              onOpenCodeMaxTurnsChange={onOpenCodeMaxTurnsChange}
              onOpenCodeWorkingDirectoryChange={onOpenCodeWorkingDirectoryChange}
              onFactoryModeChange={onFactoryModeChange}
            />
          </div>
        </div>
          </>
        )}

        {/* Question dock — blocks input when agent asks a question */}
        {pendingQuestion && (
          <QuestionDock
            request={pendingQuestion}
            responding={questionResponding}
            onReply={handleQuestionReply}
            onReject={handleQuestionReject}
          />
        )}

        {/* Prompt input */}
        <div className="relative mx-auto w-full max-w-6xl" ref={mentionContainerRef}>
          {/* Parsed @mentions from prompt text */}
          {(() => {
            const mentionNames = Array.from(new Set((prompt.match(/@([a-z0-9](?:[a-z0-9\-]*[a-z0-9])?)/gi) || []).map((m) => m.slice(1))));
            if (mentionNames.length === 0) return null;
            return (
              <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
                {mentionNames.map((name) => {
                  const agent = agents.find((a) => a.name.toLowerCase() === name.toLowerCase());
                  return (
                    <Badge
                      key={name}
                      variant="outline"
                      className={`h-5 gap-0.5 rounded-full px-1.5 text-[10px] ${agent ? "border-primary/25 bg-primary/5 text-primary" : "border-amber-500/25 bg-amber-500/10 text-amber-300"}`}
                    >
                      <AtSign className="h-3 w-3" />
                      {name}
                      {!agent && <span className="text-[9px] opacity-70">(unknown)</span>}
                    </Badge>
                  );
                })}
              </div>
            );
          })()}
          {/* A2A target chip */}
          {a2aMode && (
            <div className="mb-1.5 flex items-center gap-2">
              <Badge variant="outline" className="h-6 gap-1 rounded-full border-primary/25 bg-primary/5 px-2 text-[10px] text-primary">
                <AtSign className="h-3 w-3" />
                {a2aTargetNamespace}/{a2aTargetAgent}
                <button
                  type="button"
                  onClick={clearA2A}
                  className="ml-0.5 inline-flex items-center justify-center rounded-full hover:bg-primary/10"
                  aria-label="Clear A2A target"
                  title="Clear A2A target"
                >
                  <X className="h-3 w-3" />
                </button>
              </Badge>
              <span className="text-[10px] text-muted-foreground/60">Request will route through this agent</span>
            </div>
          )}
          <div className="relative rounded-lg border-2 border-border bg-background/80 shadow-sm transition-colors focus-within:border-primary/40 focus-within:bg-primary/5">
            {/* Attachment previews */}
            {attachments.length > 0 && (
              <div className="flex flex-wrap gap-2 px-3 pt-2">
                {attachments.map((att) => (
                  <div key={att.id} className="group/att relative flex items-center gap-1.5 rounded-md border border-border/60 bg-muted/40 px-2 py-1">
                    {att.isImage ? (
                      <img src={att.dataUrl} alt={att.name} className="h-8 w-8 rounded object-cover" />
                    ) : (
                      <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                    )}
                    <span className="max-w-[120px] truncate text-[11px] text-muted-foreground">{att.name}</span>
                    <button
                      type="button"
                      onClick={() => removeAttachment(att.id)}
                      className="ml-0.5 rounded-full p-0.5 text-muted-foreground/60 hover:bg-destructive/10 hover:text-destructive transition-colors"
                      aria-label={`Remove ${att.name}`}
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                ))}
              </div>
            )}
            {/* Hidden file input */}
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept="image/*,.txt,.md,.json,.yaml,.yml,.csv,.log,.py,.js,.ts,.tsx,.jsx,.sh,.bash,.sql,.xml,.html,.css,.toml,.ini,.cfg,.env,.dockerfile,Dockerfile"
              className="hidden"
              onChange={handleFileSelect}
            />
            <Textarea
              ref={textareaRef}
              autoFocus
              placeholder={chatFocused ? "Message the agent…" : "Describe what you want the agent to do…"}
              value={prompt}
              onChange={(e) => {
                onPromptChange(e.target.value);
                const el = e.target;
                el.style.height = "auto";
                el.style.height = Math.min(el.scrollHeight, 200) + "px";
                const cursorPos = el.selectionStart ?? e.target.value.length;
                const ctx = getMentionContext(e.target.value, cursorPos);
                if (ctx) {
                  setMentionQuery(ctx.query);
                  setMentionOpen(true);
                  setMentionIndex(0);
                } else {
                  setMentionOpen(false);
                }
              }}
              onPaste={handlePaste}
              onKeyDown={(e) => {
                if (mentionOpen && filteredMentionAgents.length > 0) {
                  if (e.key === "ArrowDown") {
                    e.preventDefault();
                    setMentionIndex((i) => (i + 1) % filteredMentionAgents.length);
                    return;
                  }
                  if (e.key === "ArrowUp") {
                    e.preventDefault();
                    setMentionIndex((i) => (i - 1 + filteredMentionAgents.length) % filteredMentionAgents.length);
                    return;
                  }
                  if (e.key === "Enter" || e.key === "Tab") {
                    e.preventDefault();
                    handleMentionSelect(filteredMentionAgents[mentionIndex]);
                    return;
                  }
                  if (e.key === "Escape") {
                    e.preventDefault();
                    setMentionOpen(false);
                    return;
                  }
                }
                if (e.key === "ArrowUp" && !e.shiftKey && !e.altKey && !e.metaKey && !e.ctrlKey && !prompt.trim()) {
                  if (lastUserPrompt) {
                    e.preventDefault();
                    handlePromptReuse(lastUserPrompt);
                  }
                  return;
                }
                if (e.key === "Enter" && !e.shiftKey && canSubmit && tokenReady && !isSending) {
                  e.preventDefault();
                  handleSubmitWithMention();
                  if (textareaRef.current) { textareaRef.current.style.height = "auto"; }
                }
                if (e.key === "Escape" && prompt.trim() && !mentionOpen) {
                  e.preventDefault();
                  onPromptChange("");
                  if (textareaRef.current) { textareaRef.current.style.height = "auto"; }
                }
              }}
              rows={1}
              className="resize-none border-0 bg-transparent pr-12 pl-3 py-2 min-h-[2.25rem] max-h-[160px] overflow-y-auto focus-visible:ring-0 focus-visible:ring-offset-0 placeholder:text-muted-foreground/50 text-sm"
              aria-label="Prompt"
            />
            {/* @-mention dropdown — appears ABOVE input so it never gets hidden */}
            {mentionOpen && filteredMentionAgents.length > 0 && (
              <div className="absolute left-0 right-0 bottom-full z-50 mb-1 overflow-hidden rounded-lg border border-border/80 bg-background/98 shadow-xl backdrop-blur-xl">
                <div className="max-h-[240px] overflow-y-auto py-1">
                  {filteredMentionAgents.map((agent, index) => (
                    <button
                      key={`${agent.namespace}/${agent.name}`}
                      type="button"
                      onClick={() => handleMentionSelect(agent)}
                      className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors ${
                        index === mentionIndex ? "bg-primary/10 text-foreground" : "text-muted-foreground hover:bg-accent/50 hover:text-foreground"
                      }`}
                    >
                      <AtSign className="h-3.5 w-3.5 shrink-0 text-primary" />
                      <span className="font-medium text-foreground">{agent.name}</span>
                      <span className="text-xs text-muted-foreground">{agent.namespace}</span>
                      {agent.model && <span className="text-[10px] text-muted-foreground/60">{agent.model}</span>}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {/* Bottom bar inside composer: runtime chip + attach + send */}
            <div className="flex items-center justify-between px-2 pb-2">
              <div className="flex items-center gap-1.5">
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 text-muted-foreground hover:text-foreground"
                  onClick={() => fileInputRef.current?.click()}
                  aria-label="Attach file"
                  title="Attach file or image"
                >
                  <Paperclip className="h-4 w-4" />
                </Button>
                {agentName && (
                  <Badge variant="outline" className={cn("inline-flex items-center gap-1 px-1.5 py-0 text-[10px] border", chatSignals.runtime.tone)}>
                    <ChatRuntimeIcon className="h-3 w-3" />
                    {chatSignals.runtime.shortLabel}
                  </Badge>
                )}
                <span className="text-[10px] text-muted-foreground/50">
                  Enter send · Shift+Enter newline{lastUserPrompt ? " · ArrowUp reuse last prompt" : ""}{mentionableAgents.length > 0 ? " · @ mention agent" : ""}
                </span>
              </div>
              <div>
                {isSending ? (
                  <Button
                    variant="destructive"
                    size="icon"
                    onClick={onCancel}
                    aria-label="Stop request"
                    className="h-8 w-8 rounded-full transition-transform duration-150 active:scale-95 shadow-sm"
                  >
                    <Square className="h-4 w-4" />
                  </Button>
                ) : (
                  <Button
                    size="icon"
                    onClick={handleSubmitWithMention}
                    disabled={!agentName || !canSubmit || !tokenReady}
                    aria-label="Send message (Enter)"
                    className="h-8 w-8 rounded-full transition-transform duration-150 active:scale-95 shadow-sm"
                  >
                    <ArrowUp className="h-4 w-4" />
                  </Button>
                )}
              </div>
            </div>
          </div>
        </div>

        {error && (
          <div role="alert" className="flex items-center gap-2 rounded-sm border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive shadow-sm">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
            <span className="flex-1">{error}</span>
            <Button
              variant="ghost"
              size="sm"
              className="h-6 px-2 text-[11px] text-destructive hover:text-destructive"
              onClick={() => {
                if (prompt.trim()) {
                  onSubmit();
                  return;
                }
                void handleRegeneratePrompt();
              }}
              disabled={(!canSubmit && !lastUserPrompt) || !tokenReady || isSending}
            >
              <RotateCcw className="mr-1 h-3 w-3" />
              Retry
            </Button>
          </div>
        )}

        {!chatFocused && (
          <div className="flex items-center justify-between gap-3">
            <p className="text-[11px] text-muted-foreground flex-1">
              {!tokenReady
                ? "Enter a gateway token before sending chat requests."
                : specialistMode
                  ? "This request coordinates the specialist team."
                  : a2aMode
                    ? "Request routes through the configured A2A target."
                    : "Authenticated requests via the API gateway."}
            </p>
            <p className="text-[10px] text-muted-foreground/70">
              Ctrl/Cmd+S saves the session.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
