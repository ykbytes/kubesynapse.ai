import { useEffect, useRef, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Cog,
  LoaderCircle,
  Plus,
  Send,
  Sparkles,
  X,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { ActivityTimeline } from "./ActivityTimeline";
import type { AgentDiscoveryPeer, RuntimeKind, SpecialistSubagentDraft, UiActivity, UiMessage } from "../types";

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
  emptyMessage: string;
  error: string;
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
  canSubmit: boolean;
  onSubmit: () => void;
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
  return (
    <div className="rounded-md border border-border">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-3 py-2 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
      >
        {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        {title}
        {badge && (
          <Badge variant="outline" className="ml-auto text-[10px]">
            {badge}
          </Badge>
        )}
      </button>
      {open && <div className="border-t border-border px-3 py-3 space-y-3">{children}</div>}
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

function MessageBubble({ message }: { message: UiMessage }) {
  const bg = roleBg[message.role] ?? "bg-muted/30 border-border";
  const isStreaming = message.status === "streaming";
  return (
    <div
      className={`rounded-md border px-3 py-2 text-sm animate-slide-up ${bg}`}
      role={isStreaming ? "status" : undefined}
      aria-live={isStreaming ? "polite" : undefined}
    >
      <div className="mb-1 flex items-center gap-2 text-[11px] text-muted-foreground">
        <span className="font-medium capitalize">{message.role}</span>
        {message.status && message.status !== "complete" && (
          <Badge variant="outline" className="text-[10px] px-1.5 py-0">
            {message.status}
          </Badge>
        )}
      </div>
      {isStreaming && !message.content ? (
        <div className="streaming-dots flex items-center gap-1 py-1 text-muted-foreground" aria-label="Waiting for model output">
          <span /><span /><span />
        </div>
      ) : (
        <pre className="whitespace-pre-wrap break-words font-sans text-sm leading-relaxed">
          {message.content || ""}
        </pre>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Tool call bubble                                                  */
/* ------------------------------------------------------------------ */
function ToolBubble({ message }: { message: UiMessage }) {
  const [expanded, setExpanded] = useState(false);
  const isRunning = message.status === "streaming";
  const isFailed = message.status === "error";
  const statusColor = isFailed
    ? "text-destructive"
    : isRunning
      ? "text-amber-500"
      : "text-emerald-500";
  const statusLabel = isFailed ? "failed" : isRunning ? "running" : "done";
  return (
    <div className="rounded-md border border-border/60 bg-muted/20 text-sm animate-slide-up">
      <button
        type="button"
        onClick={() => setExpanded((o) => !o)}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        <Cog className={`h-3.5 w-3.5 ${isRunning ? "animate-spin" : ""}`} />
        <span className="font-medium text-foreground">{message.toolName || message.toolNode || "tool"}</span>
        <Badge variant="outline" className={`ml-auto text-[10px] px-1.5 py-0 ${statusColor}`}>
          {statusLabel}
        </Badge>
        {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
      </button>
      {expanded && (
        <div className="border-t border-border/40 px-3 py-2">
          {message.content ? (
            <pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-muted-foreground max-h-48 overflow-auto">
              {message.content}
            </pre>
          ) : (
            <p className="text-[11px] text-muted-foreground italic">No detail available.</p>
          )}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Unified diff viewer                                               */
/* ------------------------------------------------------------------ */
// @ts-ignore - Component used conditionally
function DiffViewer({ diff }: { diff: string }) {
  const [expanded, setExpanded] = useState(false);
  if (!diff) return null;
  const lines = diff.split("\n");
  const addCount = lines.filter((l) => l.startsWith("+") && !l.startsWith("+++")).length;
  const removeCount = lines.filter((l) => l.startsWith("-") && !l.startsWith("---")).length;
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
        <div className="border-t border-border/40 px-3 py-2 overflow-x-auto max-h-64 overflow-y-auto">
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
}

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
  emptyMessage,
  error,
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
  canSubmit,
  onSubmit,
}: ChatWorkbenchProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const reachablePeers = discoveryPeers.filter((peer) => peer.reachable);
  const activePeerValue = a2aTargetAgent && a2aTargetNamespace ? `${a2aTargetNamespace}/${a2aTargetAgent}` : "";
  const a2aMode = Boolean(a2aTargetAgent && a2aTargetNamespace);
  const specialistMode = specialistTeamConfigured;

  useEffect(() => {
    if (!scrollRef.current) return;
    const latestMessage = messages[messages.length - 1];
    scrollRef.current.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: latestMessage?.status === "streaming" ? "auto" : "smooth",
    });
  }, [messages]);

  return (
    <div className="flex h-full flex-col gap-0">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <div>
          <p className="text-[11px] uppercase tracking-wider text-muted-foreground">
            Conversation surface
          </p>
          <h2 className="text-sm font-semibold">
            {agentName ? `${agentName} Console` : "Choose an agent"}
          </h2>
        </div>
        <Badge variant={streamMode ? "default" : "secondary"}>
          {streamMode ? "streaming" : "single-shot"}
        </Badge>
      </div>

      {/* Messages */}
      <ScrollArea className="flex-1 min-h-0" ref={scrollRef}>
        <div className="space-y-3 p-4" aria-label="Conversation history" aria-live="polite" aria-atomic="false">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center gap-2 py-16 text-muted-foreground">
              <Sparkles className="h-5 w-5" />
              <p className="text-sm">{emptyMessage}</p>
            </div>
          )}
          {messages.map((message) =>
            message.role === "tool" ? (
              <ToolBubble key={message.id} message={message} />
            ) : (
              <MessageBubble key={message.id} message={message} />
            ),
          )}
        </div>
      </ScrollArea>

      {/* Inline agent activity timeline */}
      {activity.length > 0 && (
        <div className="mx-3 mb-2">
          <ActivityTimeline
            activity={activity}
            showSummary={true}
            showFilters={false}
            autoScroll={isSending}
            heightClass="max-h-52"
          />
        </div>
      )}

      {/* Composer */}
      <div className="border-t border-border p-3 space-y-3">
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
            {approvalSupported ? "Require approval" : "Approval (LangGraph only)"}
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
                <select
                  className="flex h-8 w-full rounded-md border border-input bg-transparent px-2 text-xs shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  disabled={specialistMode}
                  value={
                    reachablePeers.some(
                      (peer) =>
                        `${peer.namespace}/${peer.name}` === activePeerValue,
                    )
                      ? activePeerValue
                      : ""
                  }
                  onChange={(e) => {
                    const nextValue = e.target.value;
                    if (!nextValue) {
                      onA2ATargetNamespaceChange("");
                      onA2ATargetAgentChange("");
                      return;
                    }
                    const idx = nextValue.indexOf("/");
                    onA2ATargetNamespaceChange(nextValue.slice(0, idx));
                    onA2ATargetAgentChange(nextValue.slice(idx + 1));
                  }}
                >
                  <option value="">Direct reply from selected agent</option>
                  {reachablePeers.map((peer) => {
                    const value = `${peer.namespace}/${peer.name}`;
                    return (
                      <option key={value} value={value}>
                        {value} · {peer.runtime_kind ?? "runtime"} · {peer.model ?? "model"}
                      </option>
                    );
                  })}
                </select>
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
                  <select
                    className="flex h-7 w-full rounded-md border border-input bg-transparent px-2 text-xs shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                    disabled={a2aMode}
                    value={subagentStrategy}
                    onChange={(e) =>
                      onSubagentStrategyChange(e.target.value as "sequential" | "parallel")
                    }
                  >
                    <option value="sequential">Sequential</option>
                    <option value="parallel">Parallel</option>
                  </select>
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
                            size="sm"
                            className="h-5 w-5 p-0"
                            disabled={a2aMode}
                            onClick={() => onRemoveSpecialistSubagent(subagent.id)}
                          >
                            <X className="h-3 w-3" />
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

        <Separator />

        {/* Prompt input */}
        <Textarea
          placeholder="Ask the agent to plan, invoke tools, or reason over retrieved context..."
          value={prompt}
          onChange={(e) => onPromptChange(e.target.value)}
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && canSubmit && tokenReady && !isSending) {
              e.preventDefault();
              onSubmit();
            }
          }}
          rows={3}
          className="resize-none"
          aria-label="Prompt"
        />

        {error && (
          <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-1.5 text-xs text-destructive">
            {error}
          </p>
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
          <Button
            onClick={onSubmit}
            disabled={!agentName || !canSubmit || !tokenReady || isSending}
            aria-label={isSending ? "Working, please wait" : "Send message (Cmd+Enter)"}
          >
            {isSending ? (
              <LoaderCircle className="mr-1.5 h-4 w-4 animate-spin" />
            ) : (
              <Send className="mr-1.5 h-4 w-4" />
            )}
            {isSending ? "Working..." : "Send"}
          </Button>
        </div>
      </div>
    </div>
  );
}
