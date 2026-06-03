import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { AgentStepNode, AgentStepNodeData } from "@/lib/composer-utils";
import { runtimeAccentClass, getCurrentDirection } from "@/lib/composer-utils";
import { getRuntimeSignal } from "@/lib/agentSignals";
import { cn } from "@/lib/utils";
import {
  UserCheck,
  Repeat,
  CheckCircle2,
  XCircle,
  LoaderCircle,
  Clock,
  ShieldAlert,
  ShieldCheck,
  AlertTriangle,
  GitBranch,
  FileText,
  Wrench,
} from "lucide-react";
import { resolveToolMeta } from "@/lib/tool-utils";

/* ── Runtime icon mapping ── */

function RuntimeIcon({ kind, className }: { kind?: string | null; className?: string }) {
  const signal = getRuntimeSignal(kind as Parameters<typeof getRuntimeSignal>[0]);
  const Icon = signal.icon;
  return <Icon className={cn("h-3.5 w-3.5", className)} />;
}

/* ── Status helpers ── */

function humanizeStepStatus(status: string): string {
  return status
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

function stepStatusRing(status?: string | null): string {
  switch (status) {
    case "completed":
      return "ring-emerald-500/50";
    case "running":
      return "ring-amber-500/50";
    case "failed":
    case "denied":
      return "ring-red-500/50";
    case "waiting_approval":
      return "ring-orange-500/50";
    case "continued":
      return "ring-amber-500/50";
    case "cancelled":
      return "ring-orange-500/40";
    case "skipped":
      return "ring-border/40";
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
    case "denied":
      return "border-red-500/40";
    case "waiting_approval":
      return "border-orange-500/40";
    case "continued":
      return "border-amber-500/40";
    case "cancelled":
      return "border-orange-500/30";
    case "skipped":
      return "border-border/60";
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
    denied: {
      icon: <ShieldAlert className="h-3 w-3" />,
      label: "Denied",
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
    skipped: {
      icon: <Clock className="h-3 w-3" />,
      label: "Skipped",
      cls: "text-muted-foreground bg-muted/50 border-border",
    },
  };
  const info = map[status] ?? {
    icon: <Clock className="h-3 w-3" />,
    label: humanizeStepStatus(status),
    cls: "text-muted-foreground bg-muted/50 border-border",
  };
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

/* ── Static styles ── */

const RUNNING_PULSE_STYLE: React.CSSProperties = { animation: "node-pulse-ring 2s ease-out infinite" };

/* ── Main node component ── */

export function AgentNode({ data, selected }: NodeProps<AgentStepNode>) {
  const status = data.stepState?.status;
  const isRunning = status === "running";
  const dir = getCurrentDirection();
  const isHorizontal = dir === "horizontal";

  const targetPos = isHorizontal ? Position.Left : Position.Top;
  const sourcePos = isHorizontal ? Position.Right : Position.Bottom;

  const targetHandleClass = isHorizontal
    ? "!h-5 !w-2 !rounded-sm !bg-primary/80 !border-0 !left-[-4px] group-hover/node:!bg-primary group-hover/node:!shadow-[0_0_6px_oklch(0.65_0.13_175_/_0.4)] transition-all"
    : "!w-5 !h-2 !rounded-sm !bg-primary/80 !border-0 !top-[-4px] group-hover/node:!bg-primary group-hover/node:!shadow-[0_0_6px_oklch(0.65_0.13_175_/_0.4)] transition-all";

  const sourceHandleClass = isHorizontal
    ? "!h-5 !w-2 !rounded-sm !bg-primary/80 !border-0 !right-[-4px] group-hover/node:!bg-primary group-hover/node:!shadow-[0_0_6px_oklch(0.65_0.13_175_/_0.4)] transition-all"
    : "!w-5 !h-2 !rounded-sm !bg-primary/80 !border-0 !bottom-[-4px] group-hover/node:!bg-primary group-hover/node:!shadow-[0_0_6px_oklch(0.65_0.13_175_/_0.4)] transition-all";

  return (
    <div
      aria-label={`${data.stepName} step${data.agentRef ? `, agent ${data.agentRef}` : ""}${data.requireApproval ? ", requires approval" : ""}`}
      className={cn(
        "group/node relative w-[280px] rounded-xl border bg-card/80 backdrop-blur-sm shadow-lg transition-all duration-150",
        "border-l-[3px]",
        runtimeAccentClass(data.runtimeKind),
        stepStatusBorder(status),
        selected && cn(
          "ring-2 ring-offset-1 ring-offset-background shadow-xl scale-[1.02]",
          stepStatusRing(status) || "ring-primary/60",
        ),
        !selected && "hover:shadow-xl hover:shadow-primary/5 hover:ring-1 hover:ring-primary/20",
      )}
    >
      {/* Running pulse overlay */}
      {isRunning && (
        <div
          className="absolute inset-0 rounded-xl border-2 border-amber-500/30 pointer-events-none"
          style={RUNNING_PULSE_STYLE}
        />
      )}

      {/* ── Input handle ── */}
      {!isHorizontal && (
        <div className="absolute -top-5 left-1/2 -translate-x-1/2 flex flex-col items-center pointer-events-none">
          <span className="text-[8px] font-semibold uppercase tracking-widest text-muted-foreground/60 mb-0.5 select-none">in</span>
        </div>
      )}
      <Handle
        type="target"
        position={targetPos}
        className={targetHandleClass}
      />

      {/* ── Header ── */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border/30">
        <RuntimeIcon kind={data.runtimeKind} />
        <span className="text-xs font-semibold truncate flex-1">{data.stepName}</span>
        <StatusBadge status={status} />
      </div>

      {/* ── Body ── */}
      <div className="px-3 py-2 space-y-1.5">
        {/* Agent ref chip */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="inline-flex items-center rounded-md border border-border/40 bg-secondary/40 px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground truncate max-w-[180px]">
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
              <Repeat className="h-2.5 w-2.5" /> Loop{data.loopConfig?.maxIterations ? ` x${data.loopConfig.maxIterations}` : ""}
            </span>
          )}
          {data.stepType === "conditional" && (
            <span className="inline-flex items-center gap-0.5 rounded-full bg-purple-500/10 border border-purple-500/20 px-1.5 py-0.5 text-[9px] text-purple-400 font-medium">
              <GitBranch className="h-2.5 w-2.5" /> Conditional
            </span>
          )}
          {data.stepType === "review" && !data.stepState?.reviewResult && (
            <span className="inline-flex items-center gap-0.5 rounded-full bg-rose-500/10 border border-rose-500/20 px-1.5 py-0.5 text-[9px] text-rose-400 font-medium">
              <ShieldCheck className="h-2.5 w-2.5" /> Review
            </span>
          )}
          {data.verify && !data.stepState?.verificationResult && (
            <span className="inline-flex items-center gap-0.5 rounded-full bg-muted/60 border border-border/60 px-1.5 py-0.5 text-[9px] text-muted-foreground font-medium">
              <ShieldCheck className="h-2.5 w-2.5" /> Will Verify
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

        {/* Execution summary strip */}
        {data.stepState && (data.stepState.toolCallCount ?? 0) > 0 && (
          <div className="flex items-center gap-2 text-[9px] text-muted-foreground border-t border-border/20 pt-1.5 mt-1">
            <span className="flex items-center gap-0.5">
              <Wrench className="h-2.5 w-2.5" />
              {data.stepState.toolCallCount} tool{data.stepState.toolCallCount !== 1 ? "s" : ""}
            </span>
            {(data.stepState.artifactCount ?? 0) > 0 && (
              <span className="flex items-center gap-0.5">
                <FileText className="h-2.5 w-2.5" />
                {data.stepState.artifactCount} file{data.stepState.artifactCount !== 1 ? "s" : ""}
              </span>
            )}
            {data.stepState.latencyMs != null && (
              <span className="font-mono tabular-nums">
                {data.stepState.latencyMs < 1000
                  ? `${data.stepState.latencyMs}ms`
                  : `${(data.stepState.latencyMs / 1000).toFixed(1)}s`}
              </span>
            )}
          </div>
        )}

        {/* Dominant signal */}
        {data.stepState?.warnings && data.stepState.warnings.length > 0 && (
          <div className="mt-1">
            <span className="inline-flex items-center gap-0.5 rounded-full bg-amber-500/10 border border-amber-500/20 px-1.5 py-0.5 text-[9px] text-amber-400 font-medium">
              <AlertTriangle className="h-2.5 w-2.5" /> {data.stepState.warnings.length} warning{data.stepState.warnings.length !== 1 ? "s" : ""}
            </span>
          </div>
        )}

        {/* Current activity preview (when running) */}
        {status === "running" && data.stepState?.toolCalls && data.stepState.toolCalls.length > 0 && (
          <div className="flex items-center gap-1.5 text-[9px] text-primary/80 border-t border-border/20 pt-1 mt-1">
            <LoaderCircle className="h-2.5 w-2.5 animate-spin shrink-0" />
            <span className="truncate">
              {(() => {
                const last = data.stepState!.toolCalls![data.stepState!.toolCalls!.length - 1];
                const meta = resolveToolMeta(last.tool);
                return meta.label;
              })()}
            </span>
          </div>
        )}
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
        position={sourcePos}
        className={sourceHandleClass}
      />
      {!isHorizontal && (
        <div className="absolute -bottom-5 left-1/2 -translate-x-1/2 flex flex-col items-center pointer-events-none">
          <span className="text-[8px] font-semibold uppercase tracking-widest text-muted-foreground/60 mt-0.5 select-none">out</span>
        </div>
      )}
    </div>
  );
}
