import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowUp,
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
  Pencil,
  Pin,
  PanelRightClose,
  PanelRightOpen,
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
import { CopyButton } from "./CopyButton";
import { EmptyState } from "./EmptyState";
import { StatusBadge } from "./StatusBadge";
import { ActivityTimeline } from "./ActivityTimeline";
import { MessageToolbar } from "./MessageToolbar";
import { ExecutionTimeline } from "./ExecutionTimeline";
import { ChatSettingsDrawer } from "./ChatSettingsDrawer";
import type { AgentDiscoveryPeer, InvocationSummary, RuntimeKind, SpecialistSubagentDraft, UiActivity, UiMessage } from "../types";
import type { UiTodo } from "../types";
import { OperationLog } from "./OperationLog";
import { FileExplorer } from "./FileExplorer";
import type { AgentArtifactPreview, AgentFileListResult, ChatSessionSummary, MemoryRecordInfo } from "@/lib/api";
import { fetchSessionDiff } from "@/lib/api";
import { usePlanDock } from "@/hooks/usePlanDock";
import { useChat } from "@/contexts/ChatContext";
import { useWorkspace } from "@/contexts/WorkspaceContext";
import { useConnection } from "@/contexts/ConnectionContext";
import { QuestionDock } from "./QuestionDock";
import { FollowupDock } from "./FollowupDock";
import { MarkdownRenderer } from "./MarkdownRenderer";

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
  subagentStrategy: "sequential" | "parallel";
  discoveryPeers: AgentDiscoveryPeer[];
  discoveryLoading: boolean;
  discoveryError: string;
  gooseMaxTurns: string;
  gooseWorkingDirectory: string;
  gooseSystemPrompt: string;
  opencodeOutputFormat: string;
  opencodeAutonomous: boolean;
  opencodeMaxTurns: string;
  opencodeWorkingDirectory: string;
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
  onListArtifacts: () => Promise<AgentFileListResult>;
  onPreviewArtifact: (path: string) => Promise<AgentArtifactPreview>;
  onPromptChange: (value: string) => void;
  onToggleStreamMode: (value: boolean) => void;
  onToggleRequireApproval: (value: boolean) => void;
  onA2ATargetAgentChange: (value: string) => void;
  onA2ATargetNamespaceChange: (value: string) => void;
  onA2ATimeoutSecondsChange: (value: string) => void;
  onSubagentStrategyChange: (value: "sequential" | "parallel") => void;
  onAddSpecialistSubagent: () => void;
  onUpdateSpecialistSubagent: (id: string, patch: Partial<SpecialistSubagentDraft>) => void;
  onRemoveSpecialistSubagent: (id: string) => void;
  onClearSpecialistTeam: () => void;
  onGooseMaxTurnsChange: (value: string) => void;
  onGooseWorkingDirectoryChange: (value: string) => void;
  onOpenCodeOutputFormatChange: (value: string) => void;
  onOpenCodeAutonomousChange: (value: boolean) => void;
  onOpenCodeMaxTurnsChange: (value: string) => void;
  onOpenCodeWorkingDirectoryChange: (value: string) => void;
  onSaveSession: () => void;
  canSubmit: boolean;
  onSubmit: () => void;
  onCancel: () => void;
}

/* ------------------------------------------------------------------ */
/*  Message bubble — ChatGPT-style layout                             */
/* ------------------------------------------------------------------ */

const MessageBubble = memo(function MessageBubble({
  message,
  index,
  onEditPrompt,
  onRegeneratePrompt,
  promptForRegenerate,
}: {
  message: UiMessage;
  index: number;
  onEditPrompt?: (text: string) => void;
  onRegeneratePrompt?: (text?: string) => Promise<void>;
  promptForRegenerate?: string | null;
}) {
  const [thinkingOpen, setThinkingOpen] = useState(false);
  const isStreaming = message.status === "streaming";
  const isUser = message.role === "user";
  const isSystem = message.role === "system";

  // ── User message: right-aligned solid bubble ──
  if (isUser) {
    return (
      <div
        className="group flex justify-end animate-slide-up"
        style={{ animationDelay: `${Math.min(index * 30, 300)}ms`, animationFillMode: "backwards" }}
      >
        <div className="max-w-[75%]">
          <div className="rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-primary-foreground shadow-sm">
            <div className="whitespace-pre-wrap break-words text-sm leading-relaxed">
              {message.content || ""}
            </div>
          </div>
          {message.content && (
            <div className="mt-1 flex justify-end">
              <MessageToolbar content={message.content} isUser onEdit={onEditPrompt ? () => onEditPrompt(message.content) : undefined} />
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
        <div className="flex items-center gap-2 rounded-full border border-amber-500/20 bg-amber-500/10 px-4 py-1.5 text-xs text-amber-400">
          <Zap className="h-3 w-3" />
          <span>{message.content || "System message"}</span>
        </div>
      </div>
    );
  }

  // ── Assistant message: left-aligned, full-width, with avatar ──
  return (
    <div
      className="group flex gap-3 animate-slide-up"
      style={{ animationDelay: `${Math.min(index * 30, 300)}ms`, animationFillMode: "backwards" }}
      role={isStreaming ? "status" : undefined}
      aria-live={isStreaming ? "polite" : undefined}
    >
      {/* Avatar */}
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-primary/20 to-primary/5 border border-primary/15 mt-0.5">
        <Bot className="h-3.5 w-3.5 text-primary" />
      </div>

      {/* Content */}
      <div className="min-w-0 flex-1">
        {/* Thinking section */}
        {message.reasoning && (
          <div className="mb-2">
            <button
              onClick={() => setThinkingOpen((o) => !o)}
              className="flex items-center gap-1.5 text-[11px] text-muted-foreground hover:text-foreground transition-colors duration-150"
              aria-expanded={thinkingOpen}
            >
              <Brain className="h-3 w-3" aria-hidden="true" />
              {thinkingOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
              <span>Thinking</span>
            </button>
            {thinkingOpen && (
              <div className="mt-1.5 rounded-lg border border-border/50 bg-muted/40 px-3 py-2 text-xs text-muted-foreground italic whitespace-pre-wrap break-words leading-relaxed max-h-64 overflow-y-auto">
                {message.reasoning}
              </div>
            )}
          </div>
        )}

        {/* Streaming placeholder */}
        {isStreaming && !message.content ? (
          <div className="streaming-dots flex items-center gap-1.5 py-1 text-muted-foreground" aria-label="Thinking">
            <span /><span /><span />
            <span className="text-[11px] ml-1">Thinking...</span>
          </div>
        ) : (
          <MarkdownRenderer content={message.content || ""} />
        )}

        {/* Execution timeline — replaces flat tool cards */}
        {(message.toolCalls?.length || message.patches?.length) ? (
          <div className="mt-2.5">
            <ExecutionTimeline
              toolCalls={message.toolCalls ?? []}
              patches={message.patches}
            />
          </div>
        ) : null}

        {/* Message toolbar — appears on hover */}
        {message.content && (
          <div className="mt-1">
            <MessageToolbar
              content={message.content}
              isStreaming={isStreaming}
              onRegenerate={promptForRegenerate ? () => { void onRegeneratePrompt?.(promptForRegenerate); } : undefined}
            />
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
};

const DOWNLOADABLE_PATH_PATTERN = /(?:^|[\s\"'`(])((?:\/[A-Za-z0-9._\-/]+|[A-Za-z0-9._-]+(?:\/[A-Za-z0-9._-]+)+)(?:\.pdf|\.md|\.txt|\.json|\.yaml|\.yml|\.csv|\.html|\.svg|\.png|\.jpg|\.jpeg|\.gif|\.doc|\.docx))(?=$|[\s\"'`),])/gi;

function basename(path: string): string {
  return path.replace(/\\/g, "/").split("/").filter(Boolean).pop() || path;
}

function truncateText(value: string | null | undefined, maxChars = 120): string {
  const text = String(value || "").trim();
  if (!text) return "";
  if (text.length <= maxChars) return text;
  return `${text.slice(0, maxChars - 1).trimEnd()}…`;
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
            >
              <X className="h-3 w-3" />
            </Button>
          </div>
        </>
      )}
    </div>
  );
});

function collectPathsFromUnknown(value: unknown): string[] {
  if (typeof value === "string") {
    return Array.from(value.matchAll(DOWNLOADABLE_PATH_PATTERN), (match) => match[1]);
  }
  if (Array.isArray(value)) {
    return value.flatMap((item) => collectPathsFromUnknown(item));
  }
  if (value && typeof value === "object") {
    return Object.values(value).flatMap((item) => collectPathsFromUnknown(item));
  }
  return [];
}

function collectDownloadableArtifacts(summary: InvocationSummary | null, messages: UiMessage[]): DownloadableArtifact[] {
  const paths = new Map<string, DownloadableArtifact>();

  const addPath = (rawPath: string | null | undefined) => {
    const path = String(rawPath || "").trim().replace(/\\/g, "/");
    if (!path || !/\.(pdf|md|txt|json|yaml|yml|csv|html|svg|png|jpg|jpeg|gif|doc|docx)$/i.test(path)) return;
    if (!paths.has(path)) {
      paths.set(path, { path, filename: basename(path) });
    }
  };

  for (const artifact of summary?.artifacts ?? []) {
    if (artifact && typeof artifact === "object") {
      addPath(String((artifact as Record<string, unknown>).path ?? ""));
      for (const candidate of collectPathsFromUnknown(artifact)) addPath(candidate);
    }
  }
  for (const toolCall of summary?.toolCalls ?? []) {
    if (toolCall && typeof toolCall === "object") {
      for (const candidate of collectPathsFromUnknown(toolCall)) addPath(candidate);
    }
  }
  for (const message of messages) {
    if (message.role === "assistant" || message.role === "tool") {
      for (const candidate of collectPathsFromUnknown(message.content)) addPath(candidate);
    }
  }

  return Array.from(paths.values());
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
  subagentStrategy,
  discoveryPeers,
  discoveryLoading,
  discoveryError,
  gooseMaxTurns,
  gooseWorkingDirectory,
  gooseSystemPrompt,
  opencodeOutputFormat,
  opencodeAutonomous,
  opencodeMaxTurns,
  opencodeWorkingDirectory,
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
  onListArtifacts,
  onPreviewArtifact,
  onPromptChange,
  onToggleStreamMode,
  onToggleRequireApproval,
  onA2ATargetAgentChange,
  onA2ATargetNamespaceChange,
  onA2ATimeoutSecondsChange,
  onSubagentStrategyChange,
  onAddSpecialistSubagent,
  onUpdateSpecialistSubagent,
  onRemoveSpecialistSubagent,
  onClearSpecialistTeam,
  onGooseMaxTurnsChange,
  onGooseWorkingDirectoryChange,
  onOpenCodeOutputFormatChange,
  onOpenCodeAutonomousChange,
  onOpenCodeMaxTurnsChange,
  onOpenCodeWorkingDirectoryChange,
  onSaveSession,
  canSubmit,
  onSubmit,
  onCancel,
}: ChatWorkbenchProps) {
  const {
    pendingQuestion, questionResponding, handleQuestionReply, handleQuestionReject,
    followupSuggestions, followupSending, handleFollowupSend, handleFollowupEdit,
    lastUserPrompt, handleReusePrompt, handleRegeneratePrompt,
  } = useChat();
  const { chatFocused, setChatFocused } = useWorkspace();
  const { token, namespace } = useConnection();
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
  const a2aMode = Boolean(a2aTargetAgent && a2aTargetNamespace);
  const specialistMode = specialistTeamConfigured;
  const detailCount = (summary ? 1 : 0) + (activity.length > 0 ? 1 : 0);
  const planCount = todos.length;
  const memoryCount = agentMemoryRecords.length + activeMemoryRecords.length;
  const downloadableArtifacts = useMemo(() => collectDownloadableArtifacts(summary, messages), [summary, messages]);
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
  const visibleSessionMemoryRecords = sessionMemoryExpanded ? activeMemoryRecords : activeMemoryRecords.slice(0, 4);
  const visibleAgentMemoryRecords = agentMemoryExpanded ? filteredAgentMemoryRecords : filteredAgentMemoryRecords.slice(0, 8);
  const starterPrompts = useMemo<StarterPrompt[]>(() => {
    if (runtimeKind === "opencode") {
      return [
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
    }
    if (runtimeKind === "goose") {
      return [
        {
          label: "Plan the approach",
          description: "Ask for a structured execution plan before taking action in the sandbox.",
          prompt: "Review the current task, outline the safest execution plan, and identify any assumptions or blockers before making changes.",
        },
        {
          label: "Inspect the workspace",
          description: "Map the relevant files, dependencies, and runtime constraints before moving.",
          prompt: "Inspect this workspace and summarize the important files, runtime dependencies, and constraints that matter for the next change.",
        },
        {
          label: "Prepare a handoff",
          description: "Create a concise state summary with next actions for another operator.",
          prompt: "Create a concise handoff covering current state, important findings, and the next concrete actions to take.",
        },
        {
          label: "Audit for drift",
          description: "Compare intent versus current state and flag the highest-signal mismatches.",
          prompt: "Audit the current workspace for drift, inconsistencies, or likely integration gaps and explain the highest-priority issues.",
        },
      ];
    }
    return [
      {
        label: "Map the architecture",
        description: "Summarize how the system fits together before asking for deeper changes.",
        prompt: "Explain the current architecture, important services, and where the key integration points live in this project.",
      },
      {
        label: "Plan the next move",
        description: "Ask for a sequence of concrete actions with clear tradeoffs.",
        prompt: "Given the current state, propose the next three highest-leverage actions and explain the tradeoffs for each.",
      },
      {
        label: "Stress the design",
        description: "Look for edge cases, operational risk, and quality gaps before shipping.",
        prompt: "Review the current implementation for operational risks, edge cases, and UX gaps that could hurt production quality.",
      },
      {
        label: "Create a concise brief",
        description: "Turn the current objective into a scoped execution brief the agent can follow.",
        prompt: "Convert the current goal into a concise execution brief with success criteria, constraints, and the smallest useful first step.",
      },
    ];
  }, [agentName, runtimeKind]);

  // Resolve the Radix ScrollArea Viewport (the actual scrollable container)
  const scrollAreaRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (scrollAreaRef.current) {
      scrollContainerRef.current =
        scrollAreaRef.current.querySelector("[data-radix-scroll-area-viewport]") ?? scrollAreaRef.current;
    }
  }, []);

  useEffect(() => {
    if (!isAtBottomRef.current || messages.length === 0) return;
    // Use requestAnimationFrame to ensure DOM has updated before scrolling
    requestAnimationFrame(() => {
      const viewport = scrollContainerRef.current;
      if (viewport) {
        viewport.scrollTop = viewport.scrollHeight;
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages.length, messages[messages.length - 1]?.status, messages[messages.length - 1]?.content?.length]);

  useEffect(() => {
    setDetailsOpen(false);
    setFilesOpen(false);
    setMemoryOpen(false);
    setFileExplorerView("all");
    setDownloadingPath(null);
  }, [agentName]);

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

  const findPromptForRegenerate = useCallback((messageIndex: number): string | null => {
    for (let index = messageIndex - 1; index >= 0; index -= 1) {
      const candidate = messages[index];
      if (candidate.role === "user" && candidate.content.trim()) {
        return candidate.content;
      }
    }
    return lastUserPrompt;
  }, [lastUserPrompt, messages]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== "s") return;
      if (!messages.length || sessionSaving) return;
      event.preventDefault();
      onSaveSession();
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [messages.length, onSaveSession, sessionSaving]);

  const stableListArtifacts = useCallback(() => onListArtifacts(), [onListArtifacts]);
  const stableDownloadArtifact = useCallback(
    (path: string, filename?: string) => onDownloadArtifact(path, filename),
    [onDownloadArtifact],
  );
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
    <div className="flex h-full min-w-0 flex-1 flex-col overflow-hidden rounded-l-[1.25rem] bg-[linear-gradient(180deg,rgba(255,255,255,0.02),transparent_12rem)]">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border/70 px-4 py-3">
        <div>
          <p className="text-[11px] uppercase tracking-wider text-muted-foreground">
            Conversation surface
          </p>
          <h2 className="text-sm font-semibold tracking-tight">
            {agentName ? `${agentName} Console` : "Choose an agent"}
          </h2>
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
              className="h-8 gap-1 rounded-full px-2 text-xs"
              onClick={() => { planDock.toggle(); if (!planOpen) { setDetailsOpen(false); setFilesOpen(false); setMemoryOpen(false); } }}
            >
              {planOpen ? <PanelRightClose className="h-3.5 w-3.5" /> : <PanelRightOpen className="h-3.5 w-3.5" />}
              Plan
              <Badge variant="outline" className="ml-1 px-1 py-0 text-[10px]">
                {planCount}
              </Badge>
            </Button>
          )}
          {agentName && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-8 gap-1 rounded-full px-2 text-xs"
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
              <FolderOpen className="h-3.5 w-3.5" />
              Files
            </Button>
          )}
          {runtimeKind === "opencode" && summary?.threadId && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-8 gap-1 rounded-full px-2 text-xs"
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
              <FileDiff className="h-3.5 w-3.5" />
              Changes
            </Button>
          )}
          {memoryCount > 0 && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-8 gap-1 rounded-full px-2 text-xs"
              onClick={() => { setMemoryOpen((open) => !open); if (!memoryOpen) { setDetailsOpen(false); if (planOpen) planDock.toggle(); setFilesOpen(false); } }}
            >
              <MemoryStick className="h-3.5 w-3.5" />
              Memory
              <Badge variant="outline" className="ml-1 px-1 py-0 text-[10px]">
                {memoryCount}
              </Badge>
            </Button>
          )}
          {detailCount > 0 && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-8 gap-1 rounded-full px-2 text-xs"
              onClick={() => { setDetailsOpen((open) => !open); if (!detailsOpen) { if (planOpen) planDock.toggle(); setFilesOpen(false); setMemoryOpen(false); } }}
            >
              {detailsOpen ? <PanelRightClose className="h-3.5 w-3.5" /> : <PanelRightOpen className="h-3.5 w-3.5" />}
              Details
              <Badge variant="outline" className="ml-1 px-1 py-0 text-[10px]">
                {detailCount}
              </Badge>
            </Button>
          )}
          <Badge variant={streamMode ? "default" : "secondary"}>
            {streamMode ? "streaming" : "single-shot"}
          </Badge>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-8 w-8 rounded-full"
            onClick={() => setChatFocused(!chatFocused)}
            title={chatFocused ? "Exit focused mode" : "Focused mode"}
          >
            {chatFocused ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
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
          <div className="mx-auto flex w-full max-w-4xl flex-col gap-5 px-4 py-6" aria-label="Conversation history" aria-live="polite" aria-atomic="false">
            {messages.length === 0 && (
              <div className="space-y-4">
                <EmptyState
                  icon={MessageSquare}
                  title="No messages yet"
                  description={emptyMessage || "Send your first message to start a conversation. Try asking the agent to analyze code, fix a bug, or build a new feature."}
                />
                <div className="rounded-2xl border border-border/70 bg-card/70 p-3 shadow-sm backdrop-blur-sm">
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
                        className="group rounded-2xl border border-border/70 bg-background/70 px-3 py-3 text-left transition-all duration-200 hover:-translate-y-px hover:border-primary/30 hover:bg-primary/5"
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

            {downloadableArtifacts.length > 0 && (
              <div className="rounded-2xl border border-border/70 bg-background/80 p-3 shadow-sm backdrop-blur-sm">
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
                    <FileText className="h-3.5 w-3.5" />
                    Generated files
                  </div>
                  <Badge variant="outline" className="text-[10px]">{downloadableArtifacts.length} ready</Badge>
                </div>
                <div className="mb-3 text-xs text-muted-foreground">
                  Files detected from structured artifacts, tool results, and assistant responses in this run.
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
                          <div className="truncate text-sm font-medium text-foreground">{artifact.filename}</div>
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
                />
              ),
            )}
            <div ref={messagesEndRef} />
          </div>
        </ScrollArea>

        {runtimeKind === "opencode" && planOpen && agentName && (
          <aside className="absolute inset-y-3 right-3 z-10 flex w-[min(24rem,calc(100%-1.5rem))] flex-col overflow-hidden rounded-2xl border border-border/80 bg-background/96 shadow-2xl backdrop-blur-md">
            <div className="flex items-center justify-between border-b border-border/60 px-3 py-2.5">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">OpenCode</div>
                <div className="text-sm font-semibold">Plan tracker</div>
              </div>
              <Button type="button" variant="ghost" size="icon" className="h-7 w-7" onClick={() => planDock.toggle()}>
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
          <aside className="absolute inset-y-3 right-3 z-10 flex w-[min(24rem,calc(100%-1.5rem))] flex-col overflow-hidden rounded-2xl border border-border/80 bg-background/96 shadow-2xl backdrop-blur-md">
            <div className="flex items-center justify-between border-b border-border/60 px-3 py-2.5">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">Inspector</div>
                <div className="text-sm font-semibold">Run details</div>
              </div>
              <Button type="button" variant="ghost" size="icon" className="h-7 w-7" onClick={() => setDetailsOpen(false)}>
                <PanelRightClose className="h-3.5 w-3.5" />
              </Button>
            </div>
            <ScrollArea className="min-h-0 flex-1">
              <div className="space-y-3 p-3">
                {summary && <OperationLog summary={summary} />}
                {activeSessionSummary && (
                  <div className="rounded-2xl border border-border/70 bg-muted/20 p-3 space-y-3">
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
          <aside className="absolute inset-y-3 right-3 z-10 flex w-[min(76rem,calc(100%-1.5rem))] flex-col overflow-hidden rounded-2xl border border-border/80 bg-background/96 shadow-2xl backdrop-blur-md">
            <div className="flex items-center justify-between border-b border-border/60 px-3 py-2.5">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">Workspace</div>
                <div className="text-sm font-semibold">Agent files</div>
              </div>
              <Button type="button" variant="ghost" size="icon" className="h-7 w-7" onClick={() => setFilesOpen(false)}>
                <PanelRightClose className="h-3.5 w-3.5" />
              </Button>
            </div>
            <FileExplorer
              agentName={agentName}
              onLoad={stableListArtifacts}
              onDownload={stableDownloadArtifact}
              onPreview={stablePreviewArtifact}
              onLoadDiff={runtimeKind === "opencode" && summary?.threadId ? stableLoadSessionDiff : undefined}
              preferredView={fileExplorerView}
              liveUpdatesEnabled={isSending || phase !== "idle"}
            />
          </aside>
        )}

        {memoryOpen && agentName && (
          <aside className="absolute inset-y-3 right-3 z-10 flex w-[min(30rem,calc(100%-1.5rem))] flex-col overflow-hidden rounded-2xl border border-border/80 bg-background/96 shadow-2xl backdrop-blur-md">
            <div className="flex items-center justify-between border-b border-border/60 px-3 py-2.5">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">Memory workspace</div>
                <div className="text-sm font-semibold">Session + durable memory</div>
              </div>
              <Button type="button" variant="ghost" size="icon" className="h-7 w-7" onClick={() => setMemoryOpen(false)}>
                <PanelRightClose className="h-3.5 w-3.5" />
              </Button>
            </div>
            <ScrollArea className="min-h-0 flex-1">
              <div className="space-y-4 p-3">
                {activeSessionSummary && (
                  <div className="space-y-3 rounded-2xl border border-border/70 bg-muted/20 p-3">
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

                <div className="space-y-3 rounded-2xl border border-border/70 bg-muted/20 p-3">
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
      <div className="border-t border-border/40 bg-background/95 px-4 py-3 backdrop-blur-md space-y-2">
        {!chatFocused && (
          <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-border/70 bg-muted/15 px-3 py-2 text-[11px] text-muted-foreground">
            <Badge variant="outline" className="text-[10px] uppercase">{runtimeKind}</Badge>
            <Badge variant={tokenReady ? "outline" : "secondary"} className="text-[10px]">
              {tokenReady ? "Gateway ready" : "Token required"}
            </Badge>
            <Badge variant={streamMode ? "default" : "secondary"} className="text-[10px]">
              {streamMode ? "Streaming" : "Single-shot"}
            </Badge>
            <Badge variant={requireApproval ? "secondary" : "outline"} className="text-[10px]">
              {requireApproval ? "Approval on" : "Approval off"}
            </Badge>
            <Badge variant="outline" className="text-[10px] text-primary">
              {specialistMode ? "Specialist team" : a2aMode ? "A2A route" : "Direct run"}
            </Badge>
            {activeSessionId ? (
              <>
                <Brain className="ml-1 h-3.5 w-3.5 text-primary" />
                <span className="font-mono text-[10px] text-foreground/85">{activeSessionId.slice(0, 8)}</span>
                <Badge variant={sessionSaving ? "default" : sessionDirty ? "secondary" : "outline"} className="text-[10px]">
                  {sessionSaving ? "Saving" : sessionDirty ? "Unsaved" : "Saved"}
                </Badge>
                {lastSessionSaveAt && <span>Saved {formatRelativeTime(lastSessionSaveAt)}</span>}
                {continuityHighlights.slice(0, 2).map((item) => (
                  <Badge key={item} variant="outline" className="text-[10px] text-primary">
                    {item}
                  </Badge>
                ))}
              </>
            ) : (
              <span>A saved session will appear after the first completed run.</span>
            )}
            <div className="ml-auto flex flex-wrap items-center gap-2">
              {lastUserPrompt && (
                <Button type="button" variant="ghost" size="sm" className="h-7 gap-1 px-2 text-[10px]" onClick={() => handlePromptReuse(lastUserPrompt)}>
                  <Pencil className="h-3 w-3" />
                  Reuse last prompt
                </Button>
              )}
              <Button type="button" variant="ghost" size="sm" className="h-7 px-2 text-[10px]" onClick={onSaveSession} disabled={!messages.length || sessionSaving || !tokenReady}>
                Save session
              </Button>
            </div>
          </div>
        )}
        {!chatFocused && (
          <>
        {/* Compact controls row: toggles + settings drawer */}
        <div className="flex flex-wrap items-center gap-2">
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
              : <span className="opacity-60">Approval (LangGraph / OpenCode)</span>
            }
          </label>
          <div className="ml-auto">
            <ChatSettingsDrawer
              runtimeKind={runtimeKind}
              a2aTargetAgent={a2aTargetAgent}
              a2aTargetNamespace={a2aTargetNamespace}
              a2aTimeoutSeconds={a2aTimeoutSeconds}
              onA2ATargetAgentChange={onA2ATargetAgentChange}
              onA2ATargetNamespaceChange={onA2ATargetNamespaceChange}
              onA2ATimeoutSecondsChange={onA2ATimeoutSecondsChange}
              specialistSubagents={specialistSubagents}
              specialistTeamConfigured={specialistTeamConfigured}
              subagentStrategy={subagentStrategy}
              onSubagentStrategyChange={onSubagentStrategyChange}
              onAddSpecialistSubagent={onAddSpecialistSubagent}
              onUpdateSpecialistSubagent={onUpdateSpecialistSubagent}
              onRemoveSpecialistSubagent={onRemoveSpecialistSubagent}
              onClearSpecialistTeam={onClearSpecialistTeam}
              discoveryPeers={discoveryPeers}
              discoveryLoading={discoveryLoading}
              discoveryError={discoveryError}
              gooseMaxTurns={gooseMaxTurns}
              gooseWorkingDirectory={gooseWorkingDirectory}
              gooseSystemPrompt={gooseSystemPrompt}
              onGooseMaxTurnsChange={onGooseMaxTurnsChange}
              onGooseWorkingDirectoryChange={onGooseWorkingDirectoryChange}
              opencodeOutputFormat={opencodeOutputFormat}
              opencodeAutonomous={opencodeAutonomous}
              opencodeMaxTurns={opencodeMaxTurns}
              opencodeWorkingDirectory={opencodeWorkingDirectory}
              onOpenCodeOutputFormatChange={onOpenCodeOutputFormatChange}
              onOpenCodeAutonomousChange={onOpenCodeAutonomousChange}
              onOpenCodeMaxTurnsChange={onOpenCodeMaxTurnsChange}
              onOpenCodeWorkingDirectoryChange={onOpenCodeWorkingDirectoryChange}
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

        {/* Followup suggestions — quick-reply buttons */}
        {!pendingQuestion && followupSuggestions.length > 0 && !isSending && (
          <FollowupDock
            items={followupSuggestions}
            sending={followupSending}
            onSend={handleFollowupSend}
            onEdit={handleFollowupEdit}
          />
        )}

        {/* Prompt input */}
        <div className="relative mx-auto w-full max-w-4xl">
          <div className="relative rounded-2xl border border-border/60 bg-muted/20 shadow-lg shadow-black/5 transition-colors focus-within:border-primary/30 focus-within:bg-muted/30">
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
              }}
              onKeyDown={(e) => {
                if (e.key === "ArrowUp" && !e.shiftKey && !e.altKey && !e.metaKey && !e.ctrlKey && !prompt.trim()) {
                  if (lastUserPrompt) {
                    e.preventDefault();
                    handlePromptReuse(lastUserPrompt);
                  }
                  return;
                }
                if (e.key === "Enter" && !e.shiftKey && canSubmit && tokenReady && !isSending) {
                  e.preventDefault();
                  onSubmit();
                  if (textareaRef.current) { textareaRef.current.style.height = "auto"; }
                }
                if (e.key === "Escape" && prompt.trim()) {
                  e.preventDefault();
                  onPromptChange("");
                  if (textareaRef.current) { textareaRef.current.style.height = "auto"; }
                }
              }}
              rows={1}
              className="resize-none border-0 bg-transparent pr-12 pl-4 py-3 min-h-[2.75rem] max-h-[200px] overflow-y-auto focus-visible:ring-0 focus-visible:ring-offset-0 placeholder:text-muted-foreground/50"
              aria-label="Prompt"
            />
            {/* Bottom bar inside composer: runtime chip + send */}
            <div className="flex items-center justify-between px-2 pb-2">
              <div className="flex items-center gap-1.5">
                {agentName && (
                  <Badge variant="outline" className="px-1.5 py-0 text-[10px] text-muted-foreground border-border/50">
                    {runtimeKind}
                  </Badge>
                )}
                <span className="text-[10px] text-muted-foreground/50">
                  Enter send · Shift+Enter newline{lastUserPrompt ? " · ArrowUp reuse last prompt" : ""}
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
                    onClick={onSubmit}
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
          <div role="alert" className="flex items-center gap-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-1.5 text-xs text-destructive">
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
