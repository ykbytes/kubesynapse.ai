import { useMemo, useState } from "react";
import {
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Cloud,
  Cog,
  Compass,
  FileCode,
  FileSearch,
  GitCommitHorizontal,
  LoaderCircle,
  Mail,
  Package,
  Terminal,
  Upload,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { extractAgentCallFromToolCall, extractAgentCallsFromSummary, sanitizeText, type AgentCallSummary } from "@/lib/agentCalls";
import type { InvocationSummary } from "@/types";

/* ------------------------------------------------------------------ */
/*  Operation classification                                          */
/* ------------------------------------------------------------------ */

type OpKind = "agent-call" | "file-create" | "file-edit" | "file-read" | "git-commit" | "git-push" | "deploy" | "notify" | "shell" | "tool";

interface ClassifiedOp {
  kind: OpKind;
  label: string;
  detail: string;
  status: string;
  input?: string;
  output?: string;
}

const KIND_STYLES: Record<OpKind, { icon: typeof Cog; text: string; bg: string }> = {
  "agent-call": { icon: Bot, text: "text-primary", bg: "bg-primary/10" },
  "file-create": { icon: FileCode, text: "text-emerald-400", bg: "bg-emerald-500/10" },
  "file-edit": { icon: FileCode, text: "text-blue-400", bg: "bg-blue-500/10" },
  "file-read": { icon: FileSearch, text: "text-muted-foreground", bg: "bg-muted/30" },
  "git-commit": { icon: GitCommitHorizontal, text: "text-emerald-400", bg: "bg-emerald-500/10" },
  "git-push": { icon: Upload, text: "text-emerald-400", bg: "bg-emerald-500/10" },
  deploy: { icon: Cloud, text: "text-blue-400", bg: "bg-blue-500/10" },
  notify: { icon: Mail, text: "text-blue-400", bg: "bg-blue-500/10" },
  shell: { icon: Terminal, text: "text-muted-foreground", bg: "bg-muted/30" },
  tool: { icon: Cog, text: "text-amber-400", bg: "bg-amber-500/10" },
};

function extractPath(input: unknown): string {
  if (!input || typeof input !== "object") return "";
  const rec = input as Record<string, unknown>;
  if (typeof rec.filePath === "string") return rec.filePath.trim();
  if (typeof rec.file === "string") return rec.file.trim();
  if (typeof rec.path === "string") return rec.path.trim();
  return "";
}

function extractCommand(input: unknown): string {
  if (typeof input === "string") return input;
  if (!input || typeof input !== "object") return "";
  const rec = input as Record<string, unknown>;
  return String(rec.command ?? rec.cmd ?? rec.input ?? "").trim();
}

function classifyToolCall(tc: Record<string, unknown>): ClassifiedOp {
  const tool = String(tc.tool ?? "").toLowerCase();
  const status = String(tc.status ?? "unknown");
  const inputRaw = tc.input;
  const outputRaw = tc.output;
  const inputStr = sanitizeText(typeof inputRaw === "string" ? inputRaw : typeof inputRaw === "object" ? JSON.stringify(inputRaw) : "");
  const outputStr = sanitizeText(typeof outputRaw === "string" ? outputRaw : "");
  const path = extractPath(inputRaw);
  const cmd = sanitizeText(extractCommand(inputRaw));
  const cmdLower = cmd.toLowerCase();

  if (tool === "write") {
    return { kind: "file-create", label: path ? `File created: ${basename(path)}` : "File created", detail: path, status, input: truncate(inputStr, 200), output: truncate(outputStr, 200) };
  }
  if (tool === "edit") {
    return { kind: "file-edit", label: path ? `File edited: ${basename(path)}` : "File edited", detail: path, status, input: truncate(inputStr, 200), output: truncate(outputStr, 200) };
  }
  if (tool === "patch") {
    return { kind: "file-edit", label: "Files patched", detail: path, status, input: truncate(inputStr, 200), output: truncate(outputStr, 200) };
  }
  if (tool === "read" || tool === "glob" || tool === "grep") {
    return { kind: "file-read", label: path ? `${capitalize(tool)}: ${basename(path)}` : capitalize(tool), detail: path, status, input: truncate(inputStr, 200), output: truncate(outputStr, 200) };
  }
  if (tool === "bash" || tool === "shell") {
    if (/\bgit\s+commit\b/.test(cmdLower)) {
      return { kind: "git-commit", label: "Committed", detail: truncate(cmd, 80), status, input: truncate(cmd, 200), output: truncate(outputStr, 200) };
    }
    if (/\bgit\s+push\b/.test(cmdLower)) {
      return { kind: "git-push", label: "Commit pushed", detail: truncate(cmd, 80), status, input: truncate(cmd, 200), output: truncate(outputStr, 200) };
    }
    if (/\b(kubectl|helm|deploy|terraform|pulumi)\b/.test(cmdLower)) {
      return { kind: "deploy", label: "Resource deployed", detail: truncate(cmd, 80), status, input: truncate(cmd, 200), output: truncate(outputStr, 200) };
    }
    if (/\b(email|send|notify|notification|mail)\b/.test(cmdLower)) {
      return { kind: "notify", label: "Notification sent", detail: truncate(cmd, 80), status, input: truncate(cmd, 200), output: truncate(outputStr, 200) };
    }
    if (/\b(npm|yarn|pnpm|pip|cargo|go)\s+(install|build|run|test)\b/.test(cmdLower)) {
      return { kind: "shell", label: "Package operation", detail: truncate(cmd, 80), status, input: truncate(cmd, 200), output: truncate(outputStr, 200) };
    }
    return { kind: "shell", label: "Command executed", detail: truncate(cmd, 80), status, input: truncate(cmd, 200), output: truncate(outputStr, 200) };
  }
  return { kind: "tool", label: tool || "Tool call", detail: truncate(inputStr, 80), status, input: truncate(inputStr, 200), output: truncate(outputStr, 200) };
}

function classifyAgentCall(call: AgentCallSummary): ClassifiedOp {
  const peer = call.namespace && call.namespace !== "default" ? `${call.namespace}/${call.agentName}` : call.agentName;
  const route = call.kind === "explicit-a2a" ? "Direct A2A" : "Gateway tool call";
  // Only include transport if it differs from what the route already implies
  const transport = call.transport && call.transport !== "gateway" ? call.transport : null;
  const detailParts = [route, transport, call.threadId].filter((value): value is string => Boolean(value));
  return {
    kind: "agent-call",
    label: `Agent response: ${peer}`,
    detail: detailParts.join(" · "),
    status: call.status,
    input: call.commandPreview ? sanitizeText(call.commandPreview) : undefined,
    output: call.responsePreview ? sanitizeText(call.responsePreview) : undefined,
  };
}

function classifyArtifact(art: Record<string, unknown>): ClassifiedOp {
  const path = String(art.path ?? "").trim();
  const tool = String(art.tool ?? "").toLowerCase();
  const status = String(art.status ?? "completed");
  if (tool === "write") {
    return { kind: "file-create", label: `File created: ${basename(path)}`, detail: path, status };
  }
  if (tool === "edit" || tool === "patch") {
    return { kind: "file-edit", label: `File edited: ${basename(path)}`, detail: path, status };
  }
  return { kind: "file-create", label: `Artifact: ${basename(path)}`, detail: path, status };
}

function classifySubagentResultFile(path: string): ClassifiedOp {
  return {
    kind: "file-create",
    label: `Team result: ${basename(path)}`,
    detail: path,
    status: "completed",
  };
}

function classifySharedTeamFile(path: string, purpose: string | null | undefined): ClassifiedOp {
  return {
    kind: "file-read",
    label: `Shared with team: ${basename(path)}`,
    detail: path,
    status: "completed",
    output: purpose ? sanitizeText(purpose) : undefined,
  };
}

function basename(p: string): string {
  const parts = p.replace(/\\/g, "/").split("/");
  return parts[parts.length - 1] || p;
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function truncate(s: string, max: number): string {
  return s.length > max ? `${s.slice(0, max)}…` : s;
}

/* ------------------------------------------------------------------ */
/*  Deduplicate: prefer artifacts over tool_calls for same file path  */
/* ------------------------------------------------------------------ */
function buildOperations(summary: InvocationSummary): ClassifiedOp[] {
  const ops: ClassifiedOp[] = [];
  const artifactPaths = new Set<string>();

  for (const agentCall of extractAgentCallsFromSummary(summary)) {
    ops.push(classifyAgentCall(agentCall));
  }

  const seenSharedTeamFiles = new Set<string>();
  for (const path of summary.subagents?.resultFiles ?? []) {
    const normalized = String(path || "").trim();
    if (!normalized || artifactPaths.has(normalized)) continue;
    ops.push(classifySubagentResultFile(normalized));
    artifactPaths.add(normalized);
  }
  for (const sharedFile of summary.subagents?.sharedFiles ?? []) {
    const path = String(sharedFile.path ?? "").trim();
    if (!path) continue;
    const purpose = typeof sharedFile.purpose === "string" ? sharedFile.purpose : undefined;
    const identity = `${path}|${purpose ?? ""}`;
    if (seenSharedTeamFiles.has(identity)) continue;
    seenSharedTeamFiles.add(identity);
    ops.push(classifySharedTeamFile(path, purpose));
  }

  // Artifacts first (higher fidelity for file ops)
  for (const art of summary.artifacts ?? []) {
    if (!art || typeof art !== "object") continue;
    const op = classifyArtifact(art);
    if (op.detail && artifactPaths.has(op.detail)) continue;
    ops.push(op);
    if (op.detail) artifactPaths.add(op.detail);
  }

  // Tool calls, dedup file-create/file-edit if already covered by artifacts
  for (const tc of summary.toolCalls ?? []) {
    if (!tc || typeof tc !== "object") continue;
    if (extractAgentCallFromToolCall(tc)) continue;
    const op = classifyToolCall(tc);
    if ((op.kind === "file-create" || op.kind === "file-edit") && op.detail && artifactPaths.has(op.detail)) continue;
    ops.push(op);
  }

  return ops;
}

/* ------------------------------------------------------------------ */
/*  Single operation row                                              */
/* ------------------------------------------------------------------ */

function OpRow({ op }: { op: ClassifiedOp }) {
  const [expanded, setExpanded] = useState(false);
  const style = KIND_STYLES[op.kind];
  const Icon = style.icon;
  const isFailed = op.status === "error" || op.status === "failed";
  const isRunning = op.status === "running" || op.status === "working" || op.status === "in_progress";
  const StatusIcon = isFailed ? XCircle : isRunning ? LoaderCircle : CheckCircle2;
  const statusColor = isFailed ? "text-red-400" : isRunning ? "text-amber-400" : "text-emerald-400";
  const rootClassName = op.kind === "agent-call"
    ? `rounded border border-primary/20 bg-primary/[0.06] text-xs`
    : `rounded border border-border/40 ${style.bg} text-xs`;

  return (
    <div className={rootClassName}>
      <button
        type="button"
        onClick={() => setExpanded((o) => !o)}
        className="flex w-full items-center gap-2 px-2.5 py-1 text-left hover:brightness-110 transition-all"
      >
        <Icon className={`h-3 w-3 shrink-0 ${style.text}`} />
        <span className="flex-1 truncate text-foreground">{op.label}</span>
        {op.detail && op.detail !== op.label && (
          <span className="hidden sm:block truncate max-w-[180px] text-[10px] text-muted-foreground font-mono">
            {op.detail}
          </span>
        )}
        <StatusIcon className={`h-3 w-3 shrink-0 ${statusColor} ${isRunning ? "animate-spin" : ""}`} />
        {(op.input || op.output) && (
          <span className="transition-transform duration-150" style={{ transform: expanded ? "rotate(90deg)" : "rotate(0deg)" }}>
            <ChevronRight className="h-3 w-3 text-muted-foreground" />
          </span>
        )}
      </button>
      {expanded && (op.input || op.output) && (
        <div className="border-t border-border/30 px-2.5 py-1.5 space-y-1">
          {op.input && (
            <div>
              <span className="text-[10px] font-medium text-muted-foreground">Input: </span>
              <span className="text-[10px] text-muted-foreground font-mono break-all">{op.input}</span>
            </div>
          )}
          {op.output && (
            <div>
              <span className="text-[10px] font-medium text-muted-foreground">Output: </span>
              <span className="text-[10px] text-muted-foreground font-mono break-all">{op.output}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Metadata footer                                                   */
/* ------------------------------------------------------------------ */

function MetadataFooter({ metadata }: { metadata: Record<string, unknown> }) {
  const tokens = (metadata.total_tokens ?? metadata.token_count) as number | undefined;
  const cost = (metadata.cost_usd ?? metadata.cost) as number | undefined;
  const model = metadata.model as string | undefined;
  if (!tokens && !cost && !model) return null;
  return (
    <div className="flex items-center gap-3 px-2.5 py-1 text-[10px] text-muted-foreground border-t border-border/30">
      {model && <span>{model}</span>}
      <span className="flex-1" />
      {tokens != null && <span className="tabular-nums">{tokens.toLocaleString()} tokens</span>}
      {cost != null && cost > 0 && (
        <Badge variant="secondary" className="text-[9px] px-1 py-0 text-emerald-500">
          ${cost.toFixed(4)}
        </Badge>
      )}
    </div>
  );
}

function ContinuityFooter({ summary }: { summary: InvocationSummary }) {
  const continuity = summary.continuity;
  if (!continuity) return null;

  const items = [
    continuity.sessionRecovered ? "session recovered" : null,
    continuity.handoffResumed ? "handoff resumed" : null,
    continuity.memoryApplied
      ? continuity.memoryEntryCount && continuity.memoryEntryCount > 0
        ? `${continuity.memoryEntryCount} memories applied`
        : "memory applied"
      : null,
    continuity.createdNewSession && !continuity.sessionRecovered ? "fresh session" : null,
  ].filter((item): item is string => Boolean(item));

  if (items.length === 0 && !continuity.remoteSessionId) return null;

  return (
    <div className="flex flex-wrap items-center gap-1.5 border-t border-border/30 px-2.5 py-1.5 text-[10px] text-muted-foreground">
      <span className="inline-flex items-center gap-1 font-medium text-foreground/85">
        <Compass className="h-3 w-3 text-primary" />
        Continuity
      </span>
      {items.map((item) => (
        <Badge key={item} variant="outline" className="px-1 py-0 text-[9px]">
          {item}
        </Badge>
      ))}
      {continuity.remoteSessionId && (
        <span className="ml-auto font-mono text-[9px] text-muted-foreground/80">{continuity.remoteSessionId}</span>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Public component                                                  */
/* ------------------------------------------------------------------ */

interface OperationLogProps {
  summary: InvocationSummary | null;
  className?: string;
}

export function OperationLog({ summary, className }: OperationLogProps) {
  if (!summary) return null;

  const ops = useMemo(() => buildOperations(summary), [summary]);
  if (ops.length === 0) return null;

  const defaultOpen = ops.length <= 10;
  const [collapsed, setCollapsed] = useState(!defaultOpen);

  const { agentOps, fileOps, otherOps, readOps, badgeParts } = useMemo(() => {
    const agent = ops.filter((o) => o.kind === "agent-call");
    const f = ops.filter((o) => o.kind === "file-create" || o.kind === "file-edit");
    const other = ops.filter((o) => o.kind !== "agent-call" && o.kind !== "file-create" && o.kind !== "file-edit" && o.kind !== "file-read");
    const reads = ops.filter((o) => o.kind === "file-read");
    const parts: string[] = [];
    if (agent.length > 0) parts.push(`${agent.length} agent call${agent.length > 1 ? "s" : ""}`);
    if (f.length > 0) parts.push(`${f.length} file${f.length > 1 ? "s" : ""}`);
    if (other.length > 0) parts.push(`${other.length} action${other.length > 1 ? "s" : ""}`);
    if (reads.length > 0) parts.push(`${reads.length} read${reads.length > 1 ? "s" : ""}`);
    return { agentOps: agent, fileOps: f, otherOps: other, readOps: reads, badgeParts: parts };
  }, [ops]);
  return (
    <div className={`rounded-md border border-border/60 bg-muted/20 overflow-hidden animate-slide-up ${className ?? ""}`.trim()}>
      {/* Header */}
      <button
        type="button"
        onClick={() => setCollapsed((c) => !c)}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        {collapsed ? <ChevronRight className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
        <Package className="h-3 w-3" />
        <span className="font-medium">Operations</span>
        <Badge variant="outline" className="ml-1 text-[10px] px-1 py-0">
          {ops.length}
        </Badge>
        {badgeParts.length > 0 && (
          <span className="text-[10px] text-muted-foreground/60">{badgeParts.join(" · ")}</span>
        )}
      </button>

      {!collapsed && (
        <div className="border-t border-border/40 px-2 py-1.5 space-y-1 max-h-96 overflow-y-auto">
          {agentOps.length > 0 && (
            <div className="space-y-1">
              <div className="px-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-primary/85">Agent calls</div>
              {agentOps.map((op, i) => (
                <OpRow key={`agent-${i}-${op.label}-${op.detail}`} op={op} />
              ))}
            </div>
          )}
          {/* File write/edit operations first */}
          {fileOps.map((op, i) => (
            <OpRow key={`file-${i}-${op.kind}-${op.detail}`} op={op} />
          ))}
          {/* Other significant operations */}
          {otherOps.map((op, i) => (
            <OpRow key={`other-${i}-${op.kind}-${op.detail}`} op={op} />
          ))}
          {/* Read operations (less prominent) */}
          {readOps.length > 0 && (
            <ReadOpsCollapsed readOps={readOps} />
          )}
        </div>
      )}

      {/* Metadata footer */}
      {!collapsed && summary.metadata && <MetadataFooter metadata={summary.metadata} />}
      {!collapsed && <ContinuityFooter summary={summary} />}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Read operations collapsed group                                   */
/* ------------------------------------------------------------------ */

function ReadOpsCollapsed({ readOps }: { readOps: ClassifiedOp[] }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="rounded border border-border/30 bg-muted/10 text-xs">
      <button
        type="button"
        onClick={() => setExpanded((o) => !o)}
        className="flex w-full items-center gap-2 px-2 py-1 text-left text-muted-foreground hover:text-foreground transition-colors"
      >
        <FileSearch className="h-3 w-3 shrink-0" />
        <span className="flex-1">{readOps.length} file read{readOps.length > 1 ? "s" : ""}</span>
        {expanded ? <ChevronDown className="h-2.5 w-2.5" /> : <ChevronRight className="h-2.5 w-2.5" />}
      </button>
      {expanded && (
        <div className="border-t border-border/20 px-2 py-1 space-y-0.5">
          {readOps.map((op, i) => (
            <OpRow key={`read-${i}-${op.kind}-${op.detail}`} op={op} />
          ))}
        </div>
      )}
    </div>
  );
}
