import { useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Cloud,
  Cog,
  FileCode,
  FileSearch,
  GitCommitHorizontal,
  Mail,
  Package,
  Terminal,
  Upload,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { InvocationSummary } from "@/types";

/* ------------------------------------------------------------------ */
/*  Operation classification                                          */
/* ------------------------------------------------------------------ */

type OpKind = "file-create" | "file-edit" | "file-read" | "git-commit" | "git-push" | "deploy" | "notify" | "shell" | "tool";

interface ClassifiedOp {
  kind: OpKind;
  label: string;
  detail: string;
  status: string;
  input?: string;
  output?: string;
}

const KIND_STYLES: Record<OpKind, { icon: typeof Cog; text: string; bg: string }> = {
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
  return String(rec.filePath ?? rec.file ?? rec.path ?? "").trim();
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
  const inputStr = typeof inputRaw === "string" ? inputRaw : typeof inputRaw === "object" ? JSON.stringify(inputRaw) : "";
  const outputStr = typeof outputRaw === "string" ? outputRaw : "";
  const path = extractPath(inputRaw);
  const cmd = extractCommand(inputRaw);
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

  // Artifacts first (higher fidelity for file ops)
  for (const art of summary.artifacts ?? []) {
    if (!art || typeof art !== "object") continue;
    const op = classifyArtifact(art);
    ops.push(op);
    if (op.detail) artifactPaths.add(op.detail);
  }

  // Tool calls, dedup file-create/file-edit if already covered by artifacts
  for (const tc of summary.toolCalls ?? []) {
    if (!tc || typeof tc !== "object") continue;
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
  const StatusIcon = isFailed ? XCircle : CheckCircle2;
  const statusColor = isFailed ? "text-red-400" : "text-emerald-400";

  return (
    <div className={`rounded border border-border/40 ${style.bg} text-xs`}>
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
        <StatusIcon className={`h-3 w-3 shrink-0 ${statusColor}`} />
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
  const tokens = metadata.total_tokens as number | undefined ?? metadata.token_count as number | undefined;
  const cost = metadata.cost_usd as number | undefined ?? metadata.cost as number | undefined;
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

/* ------------------------------------------------------------------ */
/*  Public component                                                  */
/* ------------------------------------------------------------------ */

interface OperationLogProps {
  summary: InvocationSummary | null;
}

export function OperationLog({ summary }: OperationLogProps) {
  if (!summary) return null;

  const ops = buildOperations(summary);
  if (ops.length === 0) return null;

  const defaultOpen = ops.length <= 10;
  const [collapsed, setCollapsed] = useState(!defaultOpen);

  const fileOps = ops.filter((o) => o.kind === "file-create" || o.kind === "file-edit");
  const otherOps = ops.filter((o) => o.kind !== "file-create" && o.kind !== "file-edit" && o.kind !== "file-read");
  const readOps = ops.filter((o) => o.kind === "file-read");

  const badgeParts: string[] = [];
  if (fileOps.length > 0) badgeParts.push(`${fileOps.length} file${fileOps.length > 1 ? "s" : ""}`);
  if (otherOps.length > 0) badgeParts.push(`${otherOps.length} action${otherOps.length > 1 ? "s" : ""}`);
  if (readOps.length > 0) badgeParts.push(`${readOps.length} read${readOps.length > 1 ? "s" : ""}`);

  return (
    <div className="mx-3 mb-2 rounded-md border border-border/60 bg-muted/20 overflow-hidden animate-slide-up">
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
        <div className="border-t border-border/40 px-2 py-1.5 space-y-1 max-h-64 overflow-y-auto">
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
