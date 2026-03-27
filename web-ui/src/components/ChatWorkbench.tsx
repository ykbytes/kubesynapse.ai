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
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { CopyButton } from "./CopyButton";
import { EmptyState } from "./EmptyState";
import { StatusBadge } from "./StatusBadge";
import { ActivityTimeline } from "./ActivityTimeline";
import type { AgentDiscoveryPeer, InvocationSummary, RuntimeKind, SpecialistSubagentDraft, UiActivity, UiMessage, UiToolCall } from "../types";
import type { UiTodo } from "../types";
import { OperationLog } from "./OperationLog";
import { FileExplorer } from "./FileExplorer";
import type { AgentFileListResult, ChatSessionSummary, MemoryRecordInfo } from "@/lib/api";
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
/*  Collapsible section                                               */
/* ------------------------------------------------------------------ */
function Section({
  title,
  badge,
  defaultOpen = false,
  children,
}: {
  title: string;
  badge?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const contentRef = useRef<HTMLDivElement>(null);
  return (
    <div className="rounded-md border border-border">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
      >
        <span className="transition-transform duration-200" style={{ transform: open ? "rotate(90deg)" : "rotate(0deg)" }}>
          <ChevronRight className="h-3.5 w-3.5" />
        </span>
        {title}
        {badge && (
          <Badge variant="outline" className="ml-auto text-[10px]">
            {badge}
          </Badge>
        )}
      </button>
      <div
        ref={contentRef}
        className="grid transition-[grid-template-rows] duration-200 ease-out"
        style={{ gridTemplateRows: open ? "1fr" : "0fr" }}
      >
        <div className="overflow-hidden">
          <div className="border-t border-border px-3 py-3 space-y-3">{children}</div>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Message bubble — ChatGPT-style layout                             */
/* ------------------------------------------------------------------ */

const MessageBubble = memo(function MessageBubble({ message, index }: { message: UiMessage; index: number }) {
  const [thinkingOpen, setThinkingOpen] = useState(false);
  const isStreaming = message.status === "streaming";
  const isUser = message.role === "user";
  const isSystem = message.role === "system";

  // ── User message: right-aligned solid bubble ──
  if (isUser) {
    return (
      <div
        className="flex justify-end animate-slide-up"
        style={{ animationDelay: `${Math.min(index * 30, 300)}ms`, animationFillMode: "backwards" }}
      >
        <div className="max-w-[75%] rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-primary-foreground shadow-sm">
          <div className="whitespace-pre-wrap break-words text-sm leading-relaxed">
            {message.content || ""}
          </div>
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

        {/* Tool calls & patches */}
        {(message.toolCalls?.length || message.patches?.length) ? (
          <div className="mt-2.5 space-y-1.5">
            {message.toolCalls?.map((tc, idx) => (
              <InlineToolCallCard key={`${tc.tool}-${idx}`} tc={tc} />
            ))}
            {message.patches?.map((p, idx) => (
              <PatchBadge key={`patch-${idx}`} files={p.files} />
            ))}
          </div>
        ) : null}

        {/* Copy button — appears on hover */}
        {message.content && !isStreaming && (
          <div className="mt-1 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity duration-200">
            <CopyButton value={message.content} className="h-6 w-6" />
          </div>
        )}
      </div>
    </div>
  );
});

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
/*  Inline tool call card (inside assistant messages)                 */
/* ------------------------------------------------------------------ */
const InlineToolCallCard = memo(function InlineToolCallCard({ tc }: { tc: UiToolCall }) {
  const [expanded, setExpanded] = useState(false);
  const isFailed = tc.status === "error";
  const isRunning = tc.status === "running";
  const StatusIcon = isFailed ? XCircle : isRunning ? LoaderCircle : CheckCircle2;
  const statusLabel = isFailed ? "failed" : isRunning ? "running" : "done";
  const statusColor = isFailed ? "text-red-500" : isRunning ? "text-amber-500" : "text-emerald-500";

  const inputSummary = useMemo(() => {
    if (!tc.input) return "";
    if (typeof tc.input === "string") return tc.input.slice(0, 200);
    if (typeof tc.input === "object") {
      const obj = tc.input as Record<string, unknown>;
      const filePath = obj.filePath || obj.file_path || obj.path || obj.command || obj.url;
      if (typeof filePath === "string") return filePath;
      return JSON.stringify(tc.input).slice(0, 200);
    }
    return String(tc.input).slice(0, 200);
  }, [tc.input]);

  return (
    <div className="rounded-lg border border-border/50 bg-muted/30 text-xs">
      <button
        type="button"
        onClick={() => setExpanded((o) => !o)}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-muted-foreground hover:text-foreground transition-colors"
      >
        <Cog className={`h-3 w-3 shrink-0 ${isRunning ? "animate-[spin_2s_linear_infinite]" : ""}`} />
        <span className="font-medium text-foreground truncate">{tc.tool || "tool"}</span>
        {inputSummary && <span className="truncate text-muted-foreground/70 max-w-[16rem]">{inputSummary}</span>}
        <StatusIcon className={`h-3 w-3 ml-auto shrink-0 ${statusColor}`} />
        <span className={`text-[10px] ${statusColor}`}>{statusLabel}</span>
        <ChevronRight className={`h-3 w-3 shrink-0 transition-transform ${expanded ? "rotate-90" : ""}`} />
      </button>
      {expanded && tc.output && (
        <div className="border-t border-border/40 px-2.5 py-2">
          <div className="relative group">
            <pre className="whitespace-pre-wrap break-words font-mono text-[10px] leading-relaxed text-muted-foreground max-h-40 overflow-auto">
              {tc.output}
            </pre>
            <div className="absolute top-0.5 right-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
              <CopyButton value={tc.output} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
});

/* ------------------------------------------------------------------ */
/*  Patch badge (inside assistant messages)                            */
/* ------------------------------------------------------------------ */
const PatchBadge = memo(function PatchBadge({ files }: { files: string[] }) {
  return (
    <div className="flex items-center gap-1.5 rounded-lg border border-border/50 bg-muted/30 px-2.5 py-1.5 text-xs text-muted-foreground">
      <FileDiff className="h-3 w-3 shrink-0 text-blue-500" />
      <span className="font-medium text-foreground">Files changed:</span>
      {files.map((f) => (
        <span key={f} className="font-mono text-[10px] text-blue-500 truncate max-w-[12rem]">{f.split("/").pop() || f}</span>
      ))}
    </div>
  );
});

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
  const [diffOpen, setDiffOpen] = useState(false);
  const [diffContent, setDiffContent] = useState<string | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const reachablePeers = useMemo(() => discoveryPeers.filter((peer) => peer.reachable), [discoveryPeers]);
  const activePeerValue = a2aTargetAgent && a2aTargetNamespace ? `${a2aTargetNamespace}/${a2aTargetAgent}` : "";
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
    setDownloadingPath(null);
  }, [agentName]);

  const stableListArtifacts = useCallback(() => onListArtifacts(), [onListArtifacts]);
  const stableDownloadArtifact = useCallback(
    (path: string, filename?: string) => onDownloadArtifact(path, filename),
    [onDownloadArtifact],
  );

  const handleDiffToggle = useCallback(async () => {
    if (diffOpen) { setDiffOpen(false); return; }
    const tid = summary?.threadId;
    if (!tid || !agentName || !token) return;
    setDiffOpen(true);
    setDiffLoading(true);
    try {
      const diff = await fetchSessionDiff(token, namespace, agentName, tid);
      setDiffContent(diff || null);
    } catch {
      setDiffContent(null);
    } finally {
      setDiffLoading(false);
    }
  }, [diffOpen, summary, agentName, token, namespace]);

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
              onClick={() => { setFilesOpen((o) => !o); if (!filesOpen) { setDetailsOpen(false); if (planOpen) planDock.toggle(); setMemoryOpen(false); } }}
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
              onClick={() => void handleDiffToggle()}
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
              <EmptyState
                icon={MessageSquare}
                title="No messages yet"
                description={emptyMessage || "Send your first message to start a conversation. Try asking the agent to analyze code, fix a bug, or build a new feature."}
              />
            )}

            {downloadableArtifacts.length > 0 && (
              <div className="rounded-2xl border border-border/70 bg-background/80 p-3 shadow-sm backdrop-blur-sm">
                <div className="mb-2 flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
                  <FileText className="h-3.5 w-3.5" />
                  Generated files
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
                <MessageBubble key={message.id} message={message} index={i} />
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

        {diffOpen && (
          <aside className="absolute inset-y-3 right-3 z-10 flex w-[min(32rem,calc(100%-1.5rem))] flex-col overflow-hidden rounded-2xl border border-border/80 bg-background/96 shadow-2xl backdrop-blur-md">
            <div className="flex items-center justify-between border-b border-border/60 px-3 py-2.5">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">Session</div>
                <div className="text-sm font-semibold">File changes</div>
              </div>
              <Button type="button" variant="ghost" size="icon" className="h-7 w-7" onClick={() => setDiffOpen(false)}>
                <PanelRightClose className="h-3.5 w-3.5" />
              </Button>
            </div>
            <ScrollArea className="min-h-0 flex-1">
              {diffLoading ? (
                <div className="flex items-center justify-center p-6">
                  <LoaderCircle className="h-5 w-5 animate-spin text-muted-foreground" />
                </div>
              ) : diffContent ? (
                <div className="p-3">
                  <pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-muted-foreground">
                    {diffContent.split("\n").map((line, idx) => {
                      let lineClass = "";
                      if (line.startsWith("+++") || line.startsWith("---")) lineClass = "text-muted-foreground font-semibold";
                      else if (line.startsWith("+")) lineClass = "text-emerald-500 bg-emerald-500/10";
                      else if (line.startsWith("-")) lineClass = "text-red-500 bg-red-500/10";
                      else if (line.startsWith("@@")) lineClass = "text-blue-500";
                      else if (line.startsWith("diff ")) lineClass = "text-foreground font-semibold mt-2 block";
                      return <div key={idx} className={lineClass}>{line || "\u00A0"}</div>;
                    })}
                  </pre>
                </div>
              ) : (
                <div className="flex items-center justify-center p-6 text-center text-sm text-muted-foreground">
                  No file changes detected in this session.
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
          <aside className="absolute inset-y-3 right-3 z-10 flex w-[min(24rem,calc(100%-1.5rem))] flex-col overflow-hidden rounded-2xl border border-border/80 bg-background/96 shadow-2xl backdrop-blur-md">
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
        {!chatFocused && activeSessionId && (
          <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-border/70 bg-muted/15 px-3 py-2 text-[11px] text-muted-foreground">
            <Brain className="h-3.5 w-3.5 text-primary" />
            <span className="font-medium text-foreground/85">Session continuity</span>
            <span className="font-mono text-[10px]">{activeSessionId}</span>
            <Badge variant={sessionSaving ? "default" : sessionDirty ? "secondary" : "outline"} className="text-[10px]">
              {sessionSaving ? "Saving" : sessionDirty ? "Unsaved changes" : "Saved"}
            </Badge>
            {lastSessionSaveAt && <span>Last save {formatRelativeTime(lastSessionSaveAt)}</span>}
            {continuityHighlights.map((item) => (
              <Badge key={item} variant="outline" className="text-[10px] text-primary">
                {item}
              </Badge>
            ))}
            <Button type="button" variant="ghost" size="sm" className="ml-auto h-7 px-2 text-[10px]" onClick={onSaveSession}>
              Save session
            </Button>
          </div>
        )}
        {!chatFocused && (
          <>
        {/* Toggle chips */}
        <div className="flex flex-wrap gap-2">
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
        </div>

        {/* Collapsible control sections */}
        {runtimeKind === "langgraph" && (
          <>
            <Section
              title="Explicit A2A route"
              badge={`${reachablePeers.length} reachable`}
            >
              {specialistMode && (
                <p className="text-xs text-amber-400">
                  Clear the specialist team to use single-hop A2A routing.
                </p>
              )}
              <div className="space-y-1.5">
                <Label className="text-xs">Discoverable peer</Label>
                <Select
                  disabled={specialistMode}
                  value={
                    reachablePeers.some(
                      (peer) =>
                        `${peer.namespace}/${peer.name}` === activePeerValue,
                    )
                      ? activePeerValue
                      : "__direct__"
                  }
                  onValueChange={(nextValue) => {
                    if (!nextValue || nextValue === "__direct__") {
                      onA2ATargetNamespaceChange("");
                      onA2ATargetAgentChange("");
                      return;
                    }
                    const idx = nextValue.indexOf("/");
                    onA2ATargetNamespaceChange(nextValue.slice(0, idx));
                    onA2ATargetAgentChange(nextValue.slice(idx + 1));
                  }}
                >
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue placeholder="Direct reply from selected agent" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__direct__">Direct reply from selected agent</SelectItem>
                    {reachablePeers.map((peer) => {
                      const value = `${peer.namespace}/${peer.name}`;
                      return (
                        <SelectItem key={value} value={value}>
                          {value} · {peer.runtime_kind ?? "runtime"} · {peer.model ?? "model"}
                        </SelectItem>
                      );
                    })}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid gap-2 sm:grid-cols-3">
                <div className="space-y-1">
                  <Label className="text-[11px]">Target namespace</Label>
                  <Input
                    className="h-7 text-xs"
                    disabled={specialistMode}
                    placeholder="team-b"
                    value={a2aTargetNamespace}
                    onChange={(e) => onA2ATargetNamespaceChange(e.target.value)}
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-[11px]">Target agent</Label>
                  <Input
                    className="h-7 text-xs"
                    disabled={specialistMode}
                    placeholder="reviewer"
                    value={a2aTargetAgent}
                    onChange={(e) => onA2ATargetAgentChange(e.target.value)}
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-[11px]">Timeout (s)</Label>
                  <Input
                    className="h-7 text-xs"
                    disabled={specialistMode}
                    type="number"
                    min="1"
                    placeholder="default"
                    value={a2aTimeoutSeconds}
                    onChange={(e) => onA2ATimeoutSecondsChange(e.target.value)}
                  />
                </div>
              </div>
              {discoveryLoading && (
                <p className="text-[11px] text-muted-foreground">Loading discoverable peers...</p>
              )}
              {discoveryError && (
                <p className="text-xs text-destructive">{discoveryError}</p>
              )}
            </Section>

            <Section
              title="Specialist team"
              badge={`${specialistSubagents.length} member${specialistSubagents.length === 1 ? "" : "s"}`}
            >
              {a2aMode && (
                <p className="text-xs text-amber-400">
                  Clear the explicit A2A route to coordinate a specialist team.
                </p>
              )}
              <div className="flex items-center gap-2">
                <div className="space-y-1 flex-1">
                  <Label className="text-[11px]">Strategy</Label>
                  <Select
                    disabled={a2aMode}
                    value={subagentStrategy}
                    onValueChange={(v) =>
                      onSubagentStrategyChange(v as "sequential" | "parallel")
                    }
                  >
                    <SelectTrigger className="h-7 text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="sequential">Sequential</SelectItem>
                      <SelectItem value="parallel">Parallel</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex gap-1.5 self-end">
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 text-xs"
                    disabled={a2aMode}
                    onClick={onAddSpecialistSubagent}
                  >
                    <Plus className="mr-1 h-3 w-3" />
                    Add
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 text-xs"
                    disabled={a2aMode || specialistSubagents.length === 0}
                    onClick={onClearSpecialistTeam}
                  >
                    Clear
                  </Button>
                </div>
              </div>
              {specialistSubagents.length === 0 ? (
                <p className="text-[11px] text-muted-foreground">
                  Add specialists to coordinate planner, researcher, coder, or domain agents.
                </p>
              ) : (
                <div className="space-y-2">
                  {specialistSubagents.map((subagent, index) => (
                    <Card key={subagent.id} className="shadow-none">
                      <CardContent className="p-3 space-y-2">
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-medium">
                            Specialist {index + 1}
                          </span>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7 hover:bg-destructive/20 hover:text-destructive"
                            disabled={a2aMode}
                            onClick={() => onRemoveSpecialistSubagent(subagent.id)}
                            aria-label="Remove specialist"
                          >
                            <X className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                        <div className="grid gap-2 sm:grid-cols-2">
                          <div className="space-y-1">
                            <Label className="text-[11px]">Namespace</Label>
                            <Input
                              className="h-7 text-xs"
                              disabled={a2aMode}
                              placeholder="team-b"
                              value={subagent.namespace}
                              onChange={(e) =>
                                onUpdateSpecialistSubagent(subagent.id, { namespace: e.target.value })
                              }
                            />
                          </div>
                          <div className="space-y-1">
                            <Label className="text-[11px]">Agent</Label>
                            <Input
                              className="h-7 text-xs"
                              disabled={a2aMode}
                              placeholder="analysis-agent"
                              value={subagent.name}
                              onChange={(e) =>
                                onUpdateSpecialistSubagent(subagent.id, { name: e.target.value })
                              }
                            />
                          </div>
                          <div className="space-y-1">
                            <Label className="text-[11px]">Role</Label>
                            <Input
                              className="h-7 text-xs"
                              disabled={a2aMode}
                              placeholder="incident analyst"
                              value={subagent.role}
                              onChange={(e) =>
                                onUpdateSpecialistSubagent(subagent.id, { role: e.target.value })
                              }
                            />
                          </div>
                          <div className="space-y-1">
                            <Label className="text-[11px]">Timeout (s)</Label>
                            <Input
                              className="h-7 text-xs"
                              disabled={a2aMode}
                              type="number"
                              min="1"
                              placeholder="default"
                              value={subagent.timeoutSeconds}
                              onChange={(e) =>
                                onUpdateSpecialistSubagent(subagent.id, {
                                  timeoutSeconds: e.target.value,
                                })
                              }
                            />
                          </div>
                        </div>
                        <div className="space-y-1">
                          <Label className="text-[11px]">Delegated task</Label>
                          <Textarea
                            rows={2}
                            className="text-xs"
                            disabled={a2aMode}
                            placeholder="Inspect the failing workflow and explain the root cause."
                            value={subagent.task}
                            onChange={(e) =>
                              onUpdateSpecialistSubagent(subagent.id, { task: e.target.value })
                            }
                          />
                        </div>
                        <div className="grid gap-2 sm:grid-cols-2">
                          <div className="space-y-1">
                            <Label className="text-[11px]">Shared files</Label>
                            <Textarea
                              rows={2}
                              className="text-xs font-mono"
                              disabled={a2aMode}
                              placeholder={"src/app.py | main logic\nnotes/incident.md | notes"}
                              value={subagent.inputFilesText}
                              onChange={(e) =>
                                onUpdateSpecialistSubagent(subagent.id, {
                                  inputFilesText: e.target.value,
                                })
                              }
                            />
                          </div>
                          <div className="space-y-1">
                            <Label className="text-[11px]">Result artifact path</Label>
                            <Input
                              className="h-7 text-xs font-mono"
                              disabled={a2aMode}
                              placeholder="artifacts/analysis.md"
                              value={subagent.resultFilePath}
                              onChange={(e) =>
                                onUpdateSpecialistSubagent(subagent.id, {
                                  resultFilePath: e.target.value,
                                })
                              }
                            />
                          </div>
                        </div>
                        <label className="flex items-center gap-1.5 cursor-pointer text-xs">
                          <input
                            type="checkbox"
                            checked={subagent.shareSandboxSession}
                            disabled={a2aMode}
                            onChange={(e) =>
                              onUpdateSpecialistSubagent(subagent.id, {
                                shareSandboxSession: e.target.checked,
                              })
                            }
                            className="h-3.5 w-3.5 rounded border-input"
                          />
                          Share sandbox session
                        </label>
                      </CardContent>
                    </Card>
                  ))}
                </div>
              )}
            </Section>
          </>
        )}

        {runtimeKind === "goose" && (
          <Section title="Goose run controls" badge="safe subset">
            <div className="grid gap-2 sm:grid-cols-2">
              <div className="space-y-1">
                <Label className="text-[11px]">Max turns</Label>
                <Input
                  className="h-7 text-xs"
                  type="number"
                  min="1"
                  placeholder="runtime default"
                  value={gooseMaxTurns}
                  onChange={(e) => onGooseMaxTurnsChange(e.target.value)}
                />
              </div>
              <div className="space-y-1">
                <Label className="text-[11px]">Working directory</Label>
                <Input
                  className="h-7 text-xs font-mono"
                  placeholder="workspace/subdir"
                  value={gooseWorkingDirectory}
                  onChange={(e) => onGooseWorkingDirectoryChange(e.target.value)}
                />
              </div>
            </div>
            <div className="space-y-1">
              <Label className="text-[11px]">Agent system prompt (read-only)</Label>
              <Textarea
                rows={3}
                readOnly
                className="text-xs opacity-70"
                value={gooseSystemPrompt}
              />
            </div>
            <p className="text-[11px] text-amber-400">
              Goose system overrides are locked. Edit the agent definition to change this prompt.
            </p>
          </Section>
        )}

        {runtimeKind === "opencode" && (
          <Section title="OpenCode run controls" badge="autonomous">
            <div className="grid gap-2 sm:grid-cols-2">
              <div className="space-y-1">
                <Label className="text-[11px]">Output format</Label>
                <Select value={opencodeOutputFormat} onValueChange={onOpenCodeOutputFormatChange}>
                  <SelectTrigger className="h-7 text-xs">
                    <SelectValue placeholder="text (default)" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="text">text</SelectItem>
                    <SelectItem value="json">json</SelectItem>
                    <SelectItem value="stream-json">stream-json</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label className="text-[11px]">Max turns</Label>
                <Input
                  className="h-7 text-xs"
                  type="number"
                  min="1"
                  placeholder="runtime default"
                  value={opencodeMaxTurns}
                  onChange={(e) => onOpenCodeMaxTurnsChange(e.target.value)}
                />
              </div>
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              <div className="space-y-1">
                <Label className="text-[11px]">Working directory</Label>
                <Input
                  className="h-7 text-xs font-mono"
                  placeholder="workspace/subdir"
                  value={opencodeWorkingDirectory}
                  onChange={(e) => onOpenCodeWorkingDirectoryChange(e.target.value)}
                />
              </div>
              <div className="flex items-center gap-2 pt-4">
                <label className="flex items-center gap-1.5 cursor-pointer text-xs">
                  <input
                    type="checkbox"
                    checked={opencodeAutonomous}
                    onChange={(e) => onOpenCodeAutonomousChange(e.target.checked)}
                    className="h-3.5 w-3.5 rounded border-input"
                  />
                  Autonomous mode
                </label>
              </div>
            </div>
            <p className="text-[11px] text-amber-400">
              Autonomous mode enables multi-turn execution with context-overflow recovery and automatic agent selection.
            </p>
          </Section>
        )}

        <Separator />
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
            <div className="absolute right-2 bottom-2">
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

        {error && (
          <div role="alert" className="flex items-center gap-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-1.5 text-xs text-destructive">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
            <span className="flex-1">{error}</span>
            <Button
              variant="ghost"
              size="sm"
              className="h-6 px-2 text-[11px] text-destructive hover:text-destructive"
              onClick={() => { onSubmit(); }}
              disabled={!canSubmit || !tokenReady || isSending}
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
          </div>
        )}
      </div>
    </div>
  );
}
