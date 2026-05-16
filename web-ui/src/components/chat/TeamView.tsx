import { useMemo, useState } from "react";
import {
  Bot, ChevronRight, ChevronDown, Clock, ArrowRight,
  Loader2, CheckCircle2, XCircle, AlertTriangle, Users, Wrench,
  MessageSquare, PanelRightClose, PanelRightOpen,
} from "lucide-react";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { ScrollArea } from "../ui/scroll-area";
import { Separator } from "../ui/separator";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import { deriveAgentVisualSignals, type AgentSignalSource } from "@/lib/agentSignals";
import { cn } from "@/lib/utils";
import type {
  AgentDiscoveryPeer,
  InvocationSummary,
  SpecialistSubagentDraft,
  SubagentInvocationMetadata,
  SubagentInvocationResult,
  UiActivity,
} from "../../types";

/* ------------------------------------------------------------------ */
/*  Avatar                                                            */
/* ------------------------------------------------------------------ */

const GRADIENT_PAIRS: [string, string][] = [
  ["#6366f1", "#a78bfa"], // indigo → violet
  ["#f59e0b", "#fbbf24"], // amber
  ["#10b981", "#34d399"], // emerald
  ["#ef4444", "#f87171"], // red
  ["#3b82f6", "#60a5fa"], // blue
  ["#ec4899", "#f472b6"], // pink
  ["#14b8a6", "#2dd4bf"], // teal
  ["#f97316", "#fb923c"], // orange
];

function hashString(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) {
    h = ((h << 5) - h + s.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

function AgentAvatar({ name, size = 28 }: { name: string; size?: number }) {
  const idx = hashString(name) % GRADIENT_PAIRS.length;
  const [c1, c2] = GRADIENT_PAIRS[idx];
  const initials = name
    .split(/[-_.\s]+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("");
  const gradId = `grad-${name.replace(/\W/g, "")}`;
  return (
    <svg width={size} height={size} viewBox="0 0 28 28" className="shrink-0 rounded-full" aria-hidden>
      <defs>
        <linearGradient id={gradId} x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor={c1} />
          <stop offset="100%" stopColor={c2} />
        </linearGradient>
      </defs>
      <rect width="28" height="28" rx="14" fill={`url(#${gradId})`} />
      <text x="14" y="14" textAnchor="middle" dominantBaseline="central" fill="#fff"
        fontWeight="600" fontSize="10">{initials}</text>
    </svg>
  );
}

/* ------------------------------------------------------------------ */
/*  Status helpers                                                    */
/* ------------------------------------------------------------------ */

type SubagentStatus = "idle" | "thinking" | "responding" | "completed" | "failed" | "blocked";

function deriveStatus(result: SubagentInvocationResult | undefined, isSending: boolean): SubagentStatus {
  if (!result) return isSending ? "thinking" : "idle";
  const s = result.status?.toLowerCase() ?? "";
  if (s === "completed" || s === "success") return "completed";
  if (s === "failed" || s === "error") return "failed";
  if (s === "blocked") return "blocked";
  if (s === "streaming" || s === "running") return "responding";
  return isSending ? "thinking" : "idle";
}

function StatusIcon({ status }: { status: SubagentStatus }) {
  switch (status) {
    case "idle": return <Clock className="h-3 w-3 text-muted-foreground" />;
    case "thinking": return <Loader2 className="h-3 w-3 text-blue-500 animate-spin" />;
    case "responding": return <Loader2 className="h-3 w-3 text-primary animate-spin" />;
    case "completed": return <CheckCircle2 className="h-3 w-3 text-emerald-500" />;
    case "failed": return <XCircle className="h-3 w-3 text-red-500" />;
    case "blocked": return <AlertTriangle className="h-3 w-3 text-yellow-500" />;
  }
}

function statusBadgeVariant(status: SubagentStatus): "default" | "secondary" | "destructive" | "outline" {
  switch (status) {
    case "completed": return "default";
    case "failed":
    case "blocked": return "destructive";
    case "thinking":
    case "responding": return "secondary";
    default: return "outline";
  }
}

/* ------------------------------------------------------------------ */
/*  Activity feed                                                     */
/* ------------------------------------------------------------------ */

interface ActivityEvent {
  id: string;
  timestamp: string;
  icon: "delegation" | "tool" | "result" | "error" | "synthesis";
  agent: string;
  description: string;
}

function buildActivityFeed(
  subagents: SpecialistSubagentDraft[],
  metadata: SubagentInvocationMetadata | null | undefined,
  uiActivity: UiActivity[],
): ActivityEvent[] {
  const events: ActivityEvent[] = [];
  let idx = 0;

  // Delegation events from draft
  for (const sa of subagents) {
    if (sa.name.trim()) {
      events.push({
        id: `deleg-${idx++}`,
        timestamp: new Date().toISOString(),
        icon: "delegation",
        agent: sa.name,
        description: sa.task ? `Delegated: "${truncateText(sa.task, 80)}"` : "Delegated task",
      });
    }
  }

  // Results from completed invocations
  if (metadata?.results) {
    for (const result of metadata.results) {
      const name = result.name || "unknown";

      if (result.sharedFiles?.length) {
        events.push({
          id: `files-${idx++}`,
          timestamp: new Date().toISOString(),
          icon: "tool",
          agent: name,
          description: `Shared ${result.sharedFiles.length} file(s)`,
        });
      }

      if (result.resultFilePath) {
        events.push({
          id: `result-file-${idx++}`,
          timestamp: new Date().toISOString(),
          icon: "tool",
          agent: name,
          description: `Wrote ${truncateText(result.resultFilePath, 80)}`,
        });
      }

      if (result.error) {
        events.push({
          id: `err-${idx++}`,
          timestamp: new Date().toISOString(),
          icon: "error",
          agent: name,
          description: `Error: ${truncateText(result.error, 100)}`,
        });
      } else if (result.responsePreview) {
        events.push({
          id: `resp-${idx++}`,
          timestamp: new Date().toISOString(),
          icon: "result",
          agent: name,
          description: `Returned result (${truncateText(result.responsePreview, 80)})`,
        });
      }
    }
  }

  // Synthesis event
  if (metadata?.results?.length && metadata.results.every((r) =>
    r.status === "completed" || r.status === "success" || r.status === "blocked" || r.status === "failed")) {
    const succeeded = metadata.results.filter((r) =>
      r.status === "completed" || r.status === "success").length;
    events.push({
      id: `synth-${idx++}`,
      timestamp: new Date().toISOString(),
      icon: "synthesis",
      agent: "Coordinator",
      description: `Synthesized final response (${succeeded}/${metadata.results.length} succeeded)`,
    });
  }

  // Complement with UI activity events for subagent-related entries
  for (const act of uiActivity) {
    const ev = act.event?.toLowerCase() ?? "";
    if (ev.includes("subagent") || ev.includes("delegat") || ev.includes("specialist")) {
      events.push({
        id: `ua-${act.id}`,
        timestamp: act.timestamp,
        icon: "tool",
        agent: String((act.payload as Record<string, unknown>)?.agent ?? "Agent"),
        description: `${act.event}: ${truncateText(JSON.stringify(act.payload), 90)}`,
      });
    }
  }

  return events;
}

function ActivityIcon({ type }: { type: ActivityEvent["icon"] }) {
  switch (type) {
    case "delegation": return <ArrowRight className="h-3 w-3 text-blue-500" />;
    case "tool": return <Wrench className="h-3 w-3 text-amber-500" />;
    case "result": return <MessageSquare className="h-3 w-3 text-emerald-500" />;
    case "error": return <XCircle className="h-3 w-3 text-red-500" />;
    case "synthesis": return <CheckCircle2 className="h-3 w-3 text-primary" />;
  }
}

function truncateText(text: string, max: number): string {
  return text.length > max ? text.slice(0, max - 1) + "…" : text;
}

/* ------------------------------------------------------------------ */
/*  Subagent card                                                     */
/* ------------------------------------------------------------------ */

function SubagentCard({
  draft,
  result,
  isSending,
  signalSource,
  reachable,
}: {
  draft: SpecialistSubagentDraft;
  result: SubagentInvocationResult | undefined;
  isSending: boolean;
  signalSource?: AgentSignalSource;
  reachable?: boolean;
}) {
  const status = deriveStatus(result, isSending);
  const [expanded, setExpanded] = useState(false);
  const displayName = draft.name || "Unnamed Agent";
  const hasContent = result?.responsePreview || result?.error || draft.task;
  const signals = deriveAgentVisualSignals(signalSource ?? {});
  const RuntimeIcon = signals.runtime.icon;

  return (
    <div className="rounded-lg border border-border bg-card p-2.5 space-y-1.5">
      <button
        className="flex items-center gap-2 w-full text-left"
        onClick={() => hasContent && setExpanded(!expanded)}
        aria-expanded={expanded}
      >
        <AgentAvatar name={displayName} size={24} />
        <div className="flex-1 min-w-0">
          <p className="text-xs font-medium truncate">{displayName}</p>
          {draft.role && (
            <p className="text-[10px] text-muted-foreground truncate">{draft.role}</p>
          )}
          <div className="mt-1 flex flex-wrap items-center gap-1">
            <span className={cn("inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10px]", signals.runtime.tone)}>
              <RuntimeIcon className="h-3 w-3" />
              {signals.runtime.shortLabel}
            </span>
            {reachable !== undefined && (
              <span className={cn(
                "inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10px]",
                reachable
                  ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-200"
                  : "border-red-500/25 bg-red-500/10 text-red-200",
              )}>
                {reachable ? "reachable" : "unreachable"}
              </span>
            )}
          </div>
        </div>
        <StatusIcon status={status} />
        <Badge variant={statusBadgeVariant(status)} className="text-[10px] px-1.5 py-0">
          {status}
        </Badge>
        {hasContent && (
          expanded
            ? <ChevronDown className="h-3 w-3 text-muted-foreground" />
            : <ChevronRight className="h-3 w-3 text-muted-foreground" />
        )}
      </button>

      {expanded && (
        <div className="pl-8 space-y-1">
          {draft.task && (
            <p className="text-[11px] text-muted-foreground">
              <span className="font-medium">Task:</span> {draft.task}
            </p>
          )}
          {(result?.transport || result?.threadId) && (
            <div className="flex flex-wrap gap-1">
              {result.transport && <Badge variant="outline" className="px-1 py-0 text-[10px]">{result.transport}</Badge>}
              {result.threadId && <Badge variant="outline" className="px-1 py-0 font-mono text-[10px]">{truncateText(result.threadId, 16)}</Badge>}
            </div>
          )}
          {result?.responsePreview && (
            <div className="rounded border border-border bg-muted/40 p-2 text-[11px] whitespace-pre-wrap max-h-32 overflow-auto">
              {result.responsePreview}
            </div>
          )}
          {result?.resultFilePath && (
            <div className="rounded border border-border bg-background/70 p-2 text-[10px]">
              <div className="font-medium text-foreground/85">Result file</div>
              <div className="mt-0.5 break-all font-mono text-muted-foreground">{result.resultFilePath}</div>
            </div>
          )}
          {result?.sharedFiles?.length ? (
            <div className="rounded border border-border bg-background/70 p-2 text-[10px]">
              <div className="font-medium text-foreground/85">Shared files</div>
              <div className="mt-1 space-y-1">
                {result.sharedFiles.slice(0, 4).map((file, index) => (
                  <div key={`${file.path ?? "shared"}-${index}`} className="rounded border border-border/60 bg-muted/40 px-2 py-1">
                    <div className="break-all font-mono text-muted-foreground">{file.path || "workspace file"}</div>
                    {file.purpose && <div className="mt-0.5 text-muted-foreground/80">{file.purpose}</div>}
                  </div>
                ))}
                {result.sharedFiles.length > 4 && (
                  <div className="text-muted-foreground">+{result.sharedFiles.length - 4} more shared file(s)</div>
                )}
              </div>
            </div>
          ) : null}
          {result?.error && (
            <p className="text-[11px] text-destructive">{result.error}</p>
          )}
          {result?.warnings?.length ? (
            <div className="space-y-0.5">
              {result.warnings.map((w, i) => (
                <p key={i} className="text-[10px] text-yellow-600 dark:text-yellow-400">⚠ {w}</p>
              ))}
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main TeamView panel                                               */
/* ------------------------------------------------------------------ */

interface TeamViewProps {
  specialistSubagents: SpecialistSubagentDraft[];
  specialistTeamConfigured: boolean;
  subagentStrategy: "sequential" | "parallel";
  summary: InvocationSummary | null;
  isSending: boolean;
  activity: UiActivity[];
  discoverablePeers: AgentDiscoveryPeer[];
}

export function TeamView({
  specialistSubagents,
  specialistTeamConfigured,
  subagentStrategy,
  summary,
  isSending,
  activity,
  discoverablePeers,
}: TeamViewProps) {
  const [collapsed, setCollapsed] = useState(false);

  const metadata = summary?.subagents ?? null;
  const results = metadata?.results ?? [];

  // Map results by name for quick lookup
  const resultsByName = useMemo(() => {
    const map = new Map<string, SubagentInvocationResult>();
    for (const r of results) {
      map.set(r.name, r);
    }
    return map;
  }, [results]);
  const peerByIdentity = useMemo(() => {
    const exact = new Map<string, AgentDiscoveryPeer>();
    const byName = new Map<string, AgentDiscoveryPeer>();
    for (const peer of discoverablePeers) {
      exact.set(`${peer.namespace}/${peer.name}`, peer);
      if (!byName.has(peer.name)) byName.set(peer.name, peer);
    }
    return { exact, byName };
  }, [discoverablePeers]);

  const activityFeed = useMemo(
    () => buildActivityFeed(specialistSubagents, metadata, activity),
    [specialistSubagents, metadata, activity],
  );
  const resultFileCount = useMemo(() => {
    const files = new Set<string>();
    for (const path of metadata?.resultFiles ?? []) {
      const normalized = path.trim();
      if (normalized) files.add(normalized);
    }
    for (const result of results) {
      const normalized = result.resultFilePath?.trim();
      if (normalized) files.add(normalized);
    }
    return files.size;
  }, [metadata?.resultFiles, results]);

  // Summary stats
  const total = specialistSubagents.filter((s) => s.name.trim()).length;
  const completed = results.filter((r) => r.status === "completed" || r.status === "success").length;
  const failed = results.filter((r) => r.status === "failed" || r.status === "error").length;

  if (!specialistTeamConfigured && !metadata) return null;

  if (collapsed) {
    return (
      <div className="flex items-center justify-between gap-3 border-t border-border bg-card px-3 py-2 2xl:flex-col 2xl:items-center 2xl:justify-start 2xl:border-t-0 2xl:border-l 2xl:px-1 2xl:py-3">
        <div className="flex items-center gap-2 2xl:mt-2 2xl:flex-col 2xl:gap-1">
          <Users className="h-4 w-4 text-muted-foreground" />
          <span className="text-[10px] text-muted-foreground">{total}</span>
        </div>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setCollapsed(false)}>
              <PanelRightOpen className="h-4 w-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="left">Show team panel</TooltipContent>
        </Tooltip>
      </div>
    );
  }

  return (
    <div className="flex w-full shrink-0 flex-col border-t border-border bg-card 2xl:w-64 2xl:border-t-0 2xl:border-l">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border">
        <div className="flex items-center gap-1.5">
          <Users className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="text-xs font-semibold">Team</span>
          <Badge variant="secondary" className="text-[10px] px-1 py-0 ml-1">
            {subagentStrategy}
          </Badge>
        </div>
        <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => setCollapsed(true)}>
          <PanelRightClose className="h-3.5 w-3.5" />
        </Button>
      </div>

      {/* Stats bar */}
      {results.length > 0 && (
        <div className="flex items-center gap-3 px-3 py-1.5 border-b border-border text-[10px] text-muted-foreground">
          <span className="text-emerald-500">{completed} done</span>
          {failed > 0 && <span className="text-red-500">{failed} failed</span>}
          {resultFileCount > 0 && <span>{resultFileCount} file{resultFileCount === 1 ? "" : "s"}</span>}
          {metadata?.sharedSandboxSession && <span>shared sandbox</span>}
          <span>{total} total</span>
        </div>
      )}

      <ScrollArea className="flex-1 min-h-0">
        <div className="p-2 space-y-3">
          {/* Subagent cards */}
          <div className="space-y-1.5">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground px-1">
              Members
            </p>
            {specialistSubagents.filter((s) => s.name.trim()).length === 0 ? (
              <div className="flex flex-col items-center gap-1 py-4 text-[11px] text-muted-foreground">
                <Bot className="h-5 w-5" />
                <span>No team members configured</span>
              </div>
            ) : (
              specialistSubagents
                .filter((s) => s.name.trim())
                .map((sa) => {
                  const peer = peerByIdentity.exact.get(`${sa.namespace}/${sa.name}`) ?? peerByIdentity.byName.get(sa.name);
                  return (
                    <SubagentCard
                      key={sa.id}
                      draft={sa}
                      result={resultsByName.get(sa.name)}
                      isSending={isSending}
                      signalSource={peer ? { runtime_kind: peer.runtime_kind } : undefined}
                      reachable={peer?.reachable}
                    />
                  );
                })
            )}
          </div>

          {/* Additional results not in drafts (e.g. from prior invocation) */}
          {results.filter((r) => !specialistSubagents.some((s) => s.name === r.name)).length > 0 && (
            <>
              <Separator />
              <div className="space-y-1.5">
                <p className="text-[10px] uppercase tracking-wider text-muted-foreground px-1">
                  Other Agents
                </p>
                {results
                  .filter((r) => !specialistSubagents.some((s) => s.name === r.name))
                  .map((r, i) => {
                    const peer = peerByIdentity.exact.get(`${r.namespace}/${r.name}`) ?? peerByIdentity.byName.get(r.name);
                    return (
                      <SubagentCard
                        key={`extra-${i}`}
                        draft={{
                          id: `extra-${i}`,
                          name: r.name,
                          namespace: r.namespace,
                          role: r.role ?? "",
                          task: r.task ?? "",
                          inputFilesText: "",
                          resultFilePath: r.resultFilePath ?? "",
                          shareSandboxSession: false,
                          timeoutSeconds: "",
                        }}
                        result={r}
                        isSending={false}
                        signalSource={peer ? { runtime_kind: peer.runtime_kind } : undefined}
                        reachable={peer?.reachable}
                      />
                    );
                  })}
              </div>
            </>
          )}

          {/* Activity feed */}
          {activityFeed.length > 0 && (
            <>
              <Separator />
              <div className="space-y-1.5">
                <p className="text-[10px] uppercase tracking-wider text-muted-foreground px-1">
                  Activity
                </p>
                <div className="space-y-1">
                  {activityFeed.map((ev) => (
                    <div key={ev.id} className="flex items-start gap-1.5 px-1">
                      <div className="mt-0.5 shrink-0">
                        <ActivityIcon type={ev.icon} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="text-[11px] leading-snug">
                          <span className="font-medium">{ev.agent}</span>{" "}
                          <span className="text-muted-foreground">{ev.description}</span>
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}

          {/* Delegation flow diagram (text-based) */}
          {metadata && results.length > 1 && (
            <>
              <Separator />
              <div className="space-y-1.5">
                <p className="text-[10px] uppercase tracking-wider text-muted-foreground px-1">
                  Delegation Flow
                </p>
                <div className="space-y-0.5 px-1">
                  {results.map((r, i) => (
                    <div key={i} className="flex items-center gap-1 text-[10px]">
                      <AgentAvatar name="Coordinator" size={14} />
                      <ArrowRight className="h-2.5 w-2.5 text-muted-foreground" />
                      <AgentAvatar name={r.name} size={14} />
                      <span className="truncate text-muted-foreground ml-0.5">{r.name}</span>
                      <StatusIcon status={deriveStatus(r, false)} />
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
