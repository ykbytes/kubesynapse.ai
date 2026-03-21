import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Cog,
  Download,
  FileText,
  FolderOpen,
  LoaderCircle,
  MessageSquare,
  PanelRightClose,
  PanelRightOpen,
  Plus,
  RotateCcw,
  Send,
  Square,
  User,
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
import type { AgentDiscoveryPeer, InvocationSummary, RuntimeKind, SpecialistSubagentDraft, UiActivity, UiMessage } from "../types";
import { OperationLog } from "./OperationLog";
import { FileExplorer } from "./FileExplorer";
import type { AgentFileListResult } from "@/lib/api";

interface ChatWorkbenchProps {
  agentName: string;
  runtimeKind: RuntimeKind;
  prompt: string;
  messages: UiMessage[];
  activity: UiActivity[];
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
/*  Message bubble                                                    */
/* ------------------------------------------------------------------ */
const roleBg: Record<string, string> = {
  user: "bg-primary/10 border-primary/20",
  assistant: "bg-muted/50 border-border",
  system: "bg-amber-500/10 border-amber-500/20",
};

const roleIcon: Record<string, typeof User> = {
  user: User,
  assistant: Bot,
  system: Zap,
};

const MessageBubble = memo(function MessageBubble({ message, index }: { message: UiMessage; index: number }) {
  const bg = roleBg[message.role] ?? "bg-muted/30 border-border";
  const RoleIcon = roleIcon[message.role] ?? MessageSquare;
  const isStreaming = message.status === "streaming";
  const isAssistant = message.role === "assistant";
  const alignment = message.role === "user" ? "justify-end pl-10" : "justify-start pr-10";
  return (
    <div className={`flex ${alignment}`}>
      <div
        className={`group relative w-fit max-w-[min(54rem,100%)] rounded-2xl border px-4 py-3 text-sm animate-slide-up transition-shadow duration-200 hover:shadow-md ${bg}`}
        style={{ animationDelay: `${Math.min(index * 30, 300)}ms`, animationFillMode: "backwards" }}
        role={isStreaming ? "status" : undefined}
        aria-live={isStreaming ? "polite" : undefined}
      >
        <div className="mb-1.5 flex items-center gap-2 text-[11px] text-muted-foreground">
          <RoleIcon className="h-3.5 w-3.5" aria-hidden="true" />
          <span className="font-medium capitalize">{message.role}</span>
          {message.status && message.status !== "complete" && (
            <Badge variant="outline" className="text-[10px] px-1.5 py-0">
              {message.status}
            </Badge>
          )}
          {isAssistant && message.content && !isStreaming && (
            <div className="ml-auto opacity-0 group-hover:opacity-100 transition-opacity duration-200">
              <CopyButton value={message.content} />
            </div>
          )}
        </div>
        {isStreaming && !message.content ? (
          <div className="streaming-dots flex items-center gap-1.5 py-1 text-muted-foreground" aria-label="Thinking">
            <span /><span /><span />
            <span className="text-[11px] ml-1">Thinking...</span>
          </div>
        ) : (
          <div className="whitespace-pre-wrap break-words text-sm leading-relaxed">
            {message.content || ""}
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
  canSubmit,
  onSubmit,
  onCancel,
}: ChatWorkbenchProps) {
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const isAtBottomRef = useRef(true);
  const scrollContainerRef = useRef<HTMLElement | null>(null);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [filesOpen, setFilesOpen] = useState(false);
  const [downloadingPath, setDownloadingPath] = useState<string | null>(null);
  const reachablePeers = useMemo(() => discoveryPeers.filter((peer) => peer.reachable), [discoveryPeers]);
  const activePeerValue = a2aTargetAgent && a2aTargetNamespace ? `${a2aTargetNamespace}/${a2aTargetAgent}` : "";
  const a2aMode = Boolean(a2aTargetAgent && a2aTargetNamespace);
  const specialistMode = specialistTeamConfigured;
  const detailCount = (summary ? 1 : 0) + (activity.length > 0 ? 1 : 0);
  const downloadableArtifacts = useMemo(() => collectDownloadableArtifacts(summary, messages), [summary, messages]);

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
    messagesEndRef.current?.scrollIntoView({ behavior: "auto" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages.length, messages[messages.length - 1]?.status, messages[messages.length - 1]?.content?.length]);

  useEffect(() => {
    setDetailsOpen(false);
    setFilesOpen(false);
    setDownloadingPath(null);
  }, [agentName]);

  const stableListArtifacts = useCallback(() => onListArtifacts(), [onListArtifacts]);
  const stableDownloadArtifact = useCallback(
    (path: string, filename?: string) => onDownloadArtifact(path, filename),
    [onDownloadArtifact],
  );

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
          {agentName && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-8 gap-1 rounded-full px-2 text-xs"
              onClick={() => { setFilesOpen((o) => !o); if (!filesOpen) setDetailsOpen(false); }}
            >
              <FolderOpen className="h-3.5 w-3.5" />
              Files
            </Button>
          )}
          {detailCount > 0 && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-8 gap-1 rounded-full px-2 text-xs"
              onClick={() => { setDetailsOpen((open) => !open); if (!detailsOpen) setFilesOpen(false); }}
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
        </div>
      </div>

      <div className="relative flex min-h-0 flex-1 overflow-hidden">
        <ScrollArea
          className="flex-1 min-h-0"
          ref={scrollAreaRef}
          onScrollCapture={(e) => {
            const el = e.currentTarget.querySelector("[data-radix-scroll-area-viewport]") as HTMLElement | null;
            if (el) {
              isAtBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
            }
          }}
        >
          <div className="mx-auto flex w-full max-w-4xl flex-col gap-4 px-4 py-4" aria-label="Conversation history" aria-live="polite" aria-atomic="false">
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
      </div>

      {/* Composer */}
      <div className="border-t border-border/70 bg-background/90 p-3 backdrop-blur-sm space-y-3">
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

        {/* Prompt input */}
        <Textarea
          autoFocus
          placeholder="Describe what you want the agent to do — e.g. 'Refactor the auth module to use JWT tokens' or 'Write unit tests for the payment service'..."
          value={prompt}
          onChange={(e) => onPromptChange(e.target.value)}
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && canSubmit && tokenReady && !isSending) {
              e.preventDefault();
              onSubmit();
            }
            if (e.key === "Escape" && prompt.trim()) {
              e.preventDefault();
              onPromptChange("");
            }
          }}
          rows={3}
          className="resize-none"
          aria-label="Prompt"
        />

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
          {isSending ? (
            <Button
              variant="destructive"
              onClick={onCancel}
              aria-label="Stop request"
              className="animate-scale-in transition-transform duration-150 active:scale-95"
            >
              <Square className="mr-1.5 h-4 w-4" />
              Stop
            </Button>
          ) : (
            <Button
              onClick={onSubmit}
              disabled={!agentName || !canSubmit || !tokenReady}
              aria-label="Send message (Cmd+Enter)"
              className="transition-transform duration-150 active:scale-95"
            >
              <Send className="mr-1.5 h-4 w-4" />
              Send
              <kbd className="ml-2 text-[10px] rounded px-1 py-0.5 bg-primary-foreground/20 hidden sm:inline">⌘↵</kbd>
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
