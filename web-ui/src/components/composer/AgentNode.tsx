import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { AgentStepNode, AgentStepNodeData } from "@/lib/composer-utils";
import { runtimeAccentClass } from "@/lib/composer-utils";
import { cn } from "@/lib/utils";
import {
  UserCheck,
  Repeat,
  CheckCircle2,
  XCircle,
  LoaderCircle,
  Clock,
  Bot,
  Brain,
  Bird,
  Code,
  Terminal,
  ShieldAlert,
  ShieldCheck,
  AlertTriangle,
  GitBranch,
} from "lucide-react";

/* ── Runtime icon mapping ── */

function RuntimeIcon({ kind, className }: { kind?: string | null; className?: string }) {
  const cls = className ?? "h-3.5 w-3.5";
  switch (kind) {
    case "langgraph":
      return <Brain className={cn(cls, "text-violet-400")} />;
    case "goose":
      return <Bird className={cn(cls, "text-amber-400")} />;
    case "opencode":
      return <Code className={cn(cls, "text-sky-400")} />;
    case "codex":
      return <Terminal className={cn(cls, "text-emerald-400")} />;
    default:
      return <Bot className={cn(cls, "text-muted-foreground")} />;
  }
}

/* ── Status helpers ── */

function stepStatusRing(status?: string | null): string {
  switch (status) {
    case "completed":
      return "ring-emerald-500/50";
    case "running":
      return "ring-amber-500/50";
    case "failed":
      return "ring-red-500/50";
    case "waiting_approval":
      return "ring-orange-500/50";
    default:
      return "";
  }
}

function stepStatusBorder(status?: string | null): string {
  switch (status) {
    case "completed":
      return "border-emerald-500/40";
    case "running":
      return "border-amber-500/40";
    case "failed":
      return "border-red-500/40";
    case "waiting_approval":
      return "border-orange-500/40";
    default:
      return "border-border/60";
  }
}

function StatusBadge({ status }: { status?: string | null }) {
  if (!status) return null;
  const map: Record<string, { icon: React.ReactNode; label: string; cls: string }> = {
    completed: {
      icon: <CheckCircle2 className="h-3 w-3" />,
      label: "Done",
      cls: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20",
    },
    running: {
      icon: <LoaderCircle className="h-3 w-3 animate-spin" />,
      label: "Running",
      cls: "text-amber-400 bg-amber-500/10 border-amber-500/20",
    },
    failed: {
      icon: <XCircle className="h-3 w-3" />,
      label: "Failed",
      cls: "text-red-400 bg-red-500/10 border-red-500/20",
    },
    waiting_approval: {
      icon: <ShieldAlert className="h-3 w-3" />,
      label: "Approval",
      cls: "text-orange-400 bg-orange-500/10 border-orange-500/20",
    },
    continued: {
      icon: <AlertTriangle className="h-3 w-3" />,
      label: "Continued",
      cls: "text-amber-400 bg-amber-500/10 border-amber-500/20",
    },
    cancelled: {
      icon: <XCircle className="h-3 w-3" />,
      label: "Cancelled",
      cls: "text-orange-400 bg-orange-500/10 border-orange-500/20",
    },
  };
  const info = map[status];
  if (!info) return null;
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[9px] font-medium leading-none", info.cls)}>
      {info.icon}
      {info.label}
    </span>
  );
}

function LoopProgressBar({ data }: { data: AgentStepNodeData }) {
  const lp = data.stepState?.loopProgress;
  if (!lp || data.stepType !== "loop") return null;
  const pct = lp.totalItems > 0 ? Math.round((lp.completedItems / lp.totalItems) * 100) : 0;
  return (
    <div className="mt-1.5">
      <div className="flex items-center justify-between text-[9px] text-muted-foreground mb-0.5">
        <span>Iter {lp.iteration}/{lp.maxIterations}</span>
        <span>{lp.completedItems}/{lp.totalItems} items</span>
      </div>
      <div className="h-1 w-full rounded-full bg-muted">
        <div
          className="h-1 rounded-full bg-blue-500 transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function PlanProgressBar({ data }: { data: AgentStepNodeData }) {
  const pp = data.stepState?.planProgress;
  if (!pp || pp.totalItems === 0 || data.stepState?.loopProgress) return null;
  const pct = Math.round((pp.completedItems / pp.totalItems) * 100);
  return (
    <div className="mt-1.5">
      <div className="flex items-center justify-between text-[9px] text-muted-foreground mb-0.5">
        <span>Plan</span>
        <span>{pp.completedItems}/{pp.totalItems} tasks</span>
      </div>
      <div className="h-1 w-full rounded-full bg-muted">
        <div
          className="h-1 rounded-full bg-sky-500 transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function LatencyBadge({ ms }: { ms?: number | null }) {
  if (ms == null) return null;
  const label = ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
  return (
    <span className="inline-flex items-center gap-0.5 text-[9px] text-muted-foreground font-mono">
      <Clock className="h-2.5 w-2.5" />
      {label}
    </span>
  );
}

/* ── Main node component ── */

export function AgentNode({ data, selected }: NodeProps<AgentStepNode>) {
  const status = data.stepState?.status;
  const isRunning = status === "running";

  return (
    <div
      aria-label={`${data.stepName} step${data.agentRef ? `, agent ${data.agentRef}` : ""}${data.requireApproval ? ", requires approval" : ""}`}
      className={cn(
        "group/node relative w-[280px] rounded-xl border bg-card shadow-md transition-all duration-200",
        "border-l-[3px]",
        runtimeAccentClass(data.runtimeKind),
        stepStatusBorder(status),
        selected && cn(
          "ring-2 ring-offset-1 ring-offset-background shadow-xl scale-[1.02]",
          stepStatusRing(status) || "ring-primary/60",
          "animate-glow-pulse",
        ),
        !selected && "hover:shadow-lg hover:shadow-primary/5 hover:ring-1 hover:ring-primary/20",
      )}
    >
      {/* Running pulse overlay */}
      {isRunning && (
        <div
          className="absolute inset-0 rounded-xl border-2 border-amber-500/30 pointer-events-none"
          style={{ animation: "node-pulse-ring 2s ease-out infinite" }}
        />
      )}

      {/* ── Input handle ── */}
      <div className="absolute -top-5 left-1/2 -translate-x-1/2 flex flex-col items-center pointer-events-none">
        <span className="text-[8px] font-semibold uppercase tracking-widest text-muted-foreground/60 mb-0.5 select-none">in</span>
      </div>
      <Handle
        type="target"
        position={Position.Top}
        className="!w-5 !h-2 !rounded-sm !bg-primary/80 !border-0 !top-[-4px] group-hover/node:!bg-primary group-hover/node:!shadow-[0_0_6px_oklch(0.65_0.13_175_/_0.4)] transition-all"
      />

      {/* ── Header ── */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border/40">
        <RuntimeIcon kind={data.runtimeKind} />
        <span className="text-xs font-semibold truncate flex-1">{data.stepName}</span>
        <StatusBadge status={status} />
      </div>

      {/* ── Body ── */}
      <div className="px-3 py-2 space-y-1.5">
        {/* Agent ref chip */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="inline-flex items-center rounded-md border bg-secondary/50 px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground truncate max-w-[180px]">
            {data.agentRef || "unassigned"}
          </span>
          <LatencyBadge ms={data.stepState?.latencyMs} />
        </div>

        {/* Prompt preview */}
        {data.prompt && (
          <p className="text-[10px] text-muted-foreground/70 line-clamp-2 leading-tight" title={data.prompt}>
            {data.prompt}
          </p>
        )}

        {/* Config indicator pills */}
        <div className="flex items-center gap-1 flex-wrap">
          {data.requireApproval && (
            <span className="inline-flex items-center gap-0.5 rounded-full bg-orange-500/10 border border-orange-500/20 px-1.5 py-0.5 text-[9px] text-orange-400 font-medium">
              <UserCheck className="h-2.5 w-2.5" /> HITL
            </span>
          )}
          {data.stepType === "loop" && (
            <span className="inline-flex items-center gap-0.5 rounded-full bg-blue-500/10 border border-blue-500/20 px-1.5 py-0.5 text-[9px] text-blue-400 font-medium">
              <Repeat className="h-2.5 w-2.5" /> Loop{data.loopConfig?.maxIterations ? ` ×${data.loopConfig.maxIterations}` : ""}
            </span>
          )}
          {data.stepType === "conditional" && (
            <span className="inline-flex items-center gap-0.5 rounded-full bg-purple-500/10 border border-purple-500/20 px-1.5 py-0.5 text-[9px] text-purple-400 font-medium">
              <GitBranch className="h-2.5 w-2.5" /> Conditional
            </span>
          )}
          {data.stepState?.verificationResult && (
            <span className={cn(
              "inline-flex items-center gap-0.5 rounded-full border px-1.5 py-0.5 text-[9px] font-medium",
              data.stepState.verificationResult.passed
                ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-400"
                : "bg-red-500/10 border-red-500/20 text-red-400",
            )}>
              <ShieldCheck className="h-2.5 w-2.5" /> {data.stepState.verificationResult.passed ? "Verified" : "Verify Failed"}
            </span>
          )}
          {data.stepState?.reviewResult && (
            <span className={cn(
              "inline-flex items-center gap-0.5 rounded-full border px-1.5 py-0.5 text-[9px] font-medium",
              data.stepState.reviewResult.approved
                ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-400"
                : "bg-amber-500/10 border-amber-500/20 text-amber-400",
            )}>
              <ShieldCheck className="h-2.5 w-2.5" /> {data.stepState.reviewResult.approved ? "Approved" : "Rejected"}
            </span>
          )}
          {data.stepState?.iterationFailures && data.stepState.iterationFailures.length > 0 && (
            <span className="inline-flex items-center gap-0.5 rounded-full bg-red-500/10 border border-red-500/20 px-1.5 py-0.5 text-[9px] text-red-400 font-medium">
              <AlertTriangle className="h-2.5 w-2.5" /> {data.stepState.iterationFailures.length} failures
            </span>
          )}
        </div>

        {/* Loop progress bar */}
        <LoopProgressBar data={data} />
        {/* Plan progress bar */}
        <PlanProgressBar data={data} />

        {/* Error preview */}
        {status === "failed" && data.stepState?.error && (
          <p className="text-[9px] text-red-400 truncate" title={data.stepState.error}>
            {data.stepState.error}
          </p>
        )}
      </div>

      {/* ── Output handle ── */}
      <Handle
        type="source"
        position={Position.Bottom}
        className="!w-5 !h-2 !rounded-sm !bg-primary/80 !border-0 !bottom-[-4px] group-hover/node:!bg-primary group-hover/node:!shadow-[0_0_6px_oklch(0.65_0.13_175_/_0.4)] transition-all"
      />
      <div className="absolute -bottom-5 left-1/2 -translate-x-1/2 flex flex-col items-center pointer-events-none">
        <span className="text-[8px] font-semibold uppercase tracking-widest text-muted-foreground/60 mt-0.5 select-none">out</span>
      </div>
    </div>
  );
}
