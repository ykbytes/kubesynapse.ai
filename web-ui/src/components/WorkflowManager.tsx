import {
  AlertTriangle,
  Blocks,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Circle,
  Clock,
  Download,
  FolderOpen,
  LoaderCircle,
  Pencil,
  Play,
  PlusCircle,
  Repeat,
  Save,
  ShieldCheck,
  SkipForward,
  Sparkles,
  Square,
  Timer,
  Trash2,
  Workflow,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { ConfirmDialog } from "./ConfirmDialog";
import { CopyButton } from "./CopyButton";
import { ExpandableMarkdownEditor } from "./ExpandableMarkdownEditor";
import { JsonBlock } from "./JsonBlock";
import { WorkflowLogPanel } from "./WorkflowLogPanel";
import { FileExplorer } from "./FileExplorer";
import { useConnection } from "@/contexts/ConnectionContext";
import { fetchWorkflowNextAction, listAgentArtifacts, downloadAgentArtifact, downloadAgentArtifactZip, previewAgentArtifact, type WorkflowRunRecord } from "@/lib/api";
import { FACTORY_MODE_OPTIONS, factoryModeLabel, isFactoryWorkflowName } from "@/lib/factoryModes";
import { RunHistoryPanel } from "./composer/RunHistoryPanel";
import type {
  AgentInfo,
  FactoryMode,
  LoopProgress,
  PlanProgress,
  WorkflowInfo,
  WorkflowNextAction,
  WorkflowPayload,
  WorkflowStep,
  WorkflowStepArtifactSummary,
  WorkflowStepState,
  WorkflowStepToolCallSummary,
  WorkflowSummary,
  WorkflowUpdatePayload,
} from "../types";

/* ───────────── props ───────────── */

interface WorkflowManagerProps {
  workflow: WorkflowInfo | null;
  agents: AgentInfo[];
  isSaving: boolean;
  isDeleting: boolean;
  isRunning: boolean;
  error: string;
  onCreate: (payload: WorkflowPayload) => void;
  onUpdate: (name: string, payload: WorkflowUpdatePayload) => void;
  onDelete: (name: string) => void;
  onTrigger: (name: string, input?: string, factoryMode?: FactoryMode) => void;
  onCancel?: (name: string) => void;
  isCancelling?: boolean;
  onRetryFailed?: (name: string) => void;
  isRetrying?: boolean;
  factoryMode: FactoryMode;
  onFactoryModeChange: (value: FactoryMode) => void;
  approvalReason: string;
  approvalBusy: boolean;
  onApprovalReasonChange: (value: string) => void;
  onApprovalDecision: (decision: "approved" | "denied") => void;
  onOpenComposer?: () => void;
}

/* ───────────── helpers ───────────── */

function defaultStepsForAgent(agentName?: string): WorkflowStep[] {
  return [
    {
      name: "step-1",
      agent_ref: agentName ?? "",
      prompt: "",
      depends_on: [],
      require_approval: false,
      verify: null,
      review_criteria: null,
    },
  ];
}

function formatMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const m = Math.floor(ms / 60_000);
  const s = Math.round((ms % 60_000) / 1000);
  return `${m}m ${s}s`;
}

function formatElapsed(startedAt?: string | null): string {
  if (!startedAt) return "—";
  const start = new Date(startedAt).getTime();
  if (Number.isNaN(start)) return "—";
  const elapsed = Date.now() - start;
  return formatMs(Math.max(0, elapsed));
}

const WORKSPACE_PANEL_CLASS = "border-border/65 bg-background/75 shadow-sm backdrop-blur-sm";
const SIGNAL_PANEL_CLASS = "rounded-[1.15rem] border p-3 shadow-sm backdrop-blur-sm";

function stepStatusIcon(status: string, isApprovalWaiting: boolean): { icon: React.ReactNode; ring: string } {
  if (isApprovalWaiting) {
    return {
      icon: <ShieldCheck className="h-4 w-4 text-amber-400" />,
      ring: "border-amber-500/30 bg-amber-500/10",
    };
  }
  switch (status) {
    case "succeeded":
    case "completed":
      return {
        icon: <CheckCircle2 className="h-4 w-4 text-emerald-400" />,
        ring: "border-emerald-500/30 bg-emerald-500/10",
      };
    case "failed":
      return {
        icon: <XCircle className="h-4 w-4 text-destructive" />,
        ring: "border-destructive/40 bg-destructive/10",
      };
    case "running":
      return {
        icon: <LoaderCircle className="h-4 w-4 animate-spin text-primary" />,
        ring: "border-primary/30 bg-primary/10 animate-glow-pulse shadow-md shadow-primary/15",
      };
    case "skipped":
      return {
        icon: <SkipForward className="h-4 w-4 text-muted-foreground/60" />,
        ring: "border-border/60 bg-background/60",
      };
    case "queued":
      return {
        icon: <Clock className="h-4 w-4 text-blue-400" />,
        ring: "border-blue-500/30 bg-blue-500/10",
      };
    case "cancelled":
      return {
        icon: <XCircle className="h-4 w-4 text-orange-400" />,
        ring: "border-orange-500/30 bg-orange-500/10",
      };
    case "continued":
      return {
        icon: <AlertTriangle className="h-4 w-4 text-amber-400" />,
        ring: "border-amber-500/30 bg-amber-500/10",
      };
    default:
      return {
        icon: <Circle className="h-4 w-4 text-muted-foreground/50" />,
        ring: "border-border/60 bg-background/60",
      };
  }
}

function statusBadgeVariant(status: string): "default" | "secondary" | "destructive" | "outline" {
  switch (status) {
    case "succeeded":
    case "completed":
      return "default";
    case "failed":
    case "cancelled":
      return "destructive";
    case "continued":
      return "secondary";
    case "running":
    case "queued":
      return "secondary";
    default:
      return "outline";
  }
}

function isJsonContractFailure(error?: string | null): boolean {
  const normalized = (error ?? "").toLowerCase();
  return normalized.includes("did not return json output") || normalized.includes("missing required json paths");
}

function requiredJsonPathsForStep(step: WorkflowStep, state?: WorkflowStepState): string[] {
  const stateExecution = state?.execution as Record<string, unknown> | null | undefined;
  const stepExecution = step.execution as Record<string, unknown> | null | undefined;
  const rawPaths = stateExecution?.requiredJsonPaths ?? stepExecution?.requiredJsonPaths;
  if (!Array.isArray(rawPaths)) return [];
  return rawPaths.filter((path): path is string => typeof path === "string" && path.trim().length > 0);
}

function artifactSummaryLabel(artifact: WorkflowStepArtifactSummary, index: number): string {
  return artifact.path?.trim() || artifact.name?.trim() || artifact.preview?.trim() || `Artifact ${index + 1}`;
}

function artifactSummaryMeta(artifact: WorkflowStepArtifactSummary): string {
  return [artifact.tool, artifact.status, artifact.type]
    .filter((value): value is string => typeof value === "string" && value.trim().length > 0)
    .join(" · ");
}

function toolCallSummaryLabel(toolCall: WorkflowStepToolCallSummary, index: number): string {
  return toolCall.tool?.trim() || toolCall.preview?.trim() || `Tool ${index + 1}`;
}

function toolCallSummaryMeta(toolCall: WorkflowStepToolCallSummary): string {
  const parts = [toolCall.status, toolCall.inputPreview]
    .filter((value): value is string => typeof value === "string" && value.trim().length > 0);
  if (parts.length > 0) return parts.join(" · ");
  return toolCall.preview?.trim() || "";
}

type StepViewFilter = "all" | "active" | "attention" | "activity" | "complete";

interface WorkflowSignalStep {
  name: string;
  reasons: string[];
  toolCallCount: number;
  artifactCount: number;
  warningCount: number;
}

function isStepActive(status: string, isApprovalWaiting: boolean): boolean {
  return isApprovalWaiting || status === "running" || status === "queued";
}

function isStepComplete(status: string): boolean {
  return status === "succeeded" || status === "completed" || status === "skipped";
}

function hasStepActivity(state?: WorkflowStepState): boolean {
  return (state?.toolCallCount ?? 0) > 0 || (state?.artifactCount ?? 0) > 0;
}

function needsStepAttention(state?: WorkflowStepState, isApprovalWaiting = false): boolean {
  if (isApprovalWaiting) return true;
  if (!state) return false;
  if (state.status === "failed" || state.status === "continued") return true;
  if (state.verificationResult && !state.verificationResult.passed) return true;
  if (state.reviewResult && !state.reviewResult.approved) return true;
  if ((state.warnings?.length ?? 0) > 0) return true;
  return isJsonContractFailure(state.error);
}

function stepMatchesViewFilter(filter: StepViewFilter, state: WorkflowStepState | undefined, isApprovalWaiting: boolean): boolean {
  const status = state?.status ?? "pending";
  switch (filter) {
    case "active":
      return isStepActive(status, isApprovalWaiting);
    case "attention":
      return needsStepAttention(state, isApprovalWaiting);
    case "activity":
      return hasStepActivity(state);
    case "complete":
      return isStepComplete(status);
    default:
      return true;
  }
}

/* ────────── progress bar component ────────── */

function ProgressSummaryBar({ summary, phase }: { summary: WorkflowSummary; phase: string }) {
  const total = summary.totalSteps ?? 0;
  const completed = summary.completedSteps ?? 0;
  const failed = summary.failedSteps ?? 0;
  const continued = summary.continuedSteps ?? 0;
  const skipped = summary.skippedSteps ?? 0;
  const waiting = summary.waitingApprovalSteps ?? 0;
  const done = completed + failed + skipped;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;

  const isActive = phase === "running" || phase === "queued";

  const completedStyle = useMemo(() => ({ width: `${(completed / total) * 100}%` }), [completed, total]);
  const failedStyle = useMemo(() => ({ left: `${(completed / total) * 100}%`, width: `${(failed / total) * 100}%` }), [completed, failed, total]);
  const skippedStyle = useMemo(() => ({ left: `${((completed + failed) / total) * 100}%`, width: `${(skipped / total) * 100}%` }), [completed, failed, skipped, total]);

  return (
    <div className="space-y-3">
      {/* counters row */}
      <div className="flex flex-wrap items-center gap-4 text-xs">
        <span className="flex items-center gap-1 text-emerald-400">
          <CheckCircle2 className="h-3.5 w-3.5" /> {completed} completed
        </span>
        {failed > 0 && (
          <span className="flex items-center gap-1 text-destructive">
            <XCircle className="h-3.5 w-3.5" /> {failed} failed
          </span>
        )}
        {continued > 0 && (
          <span className="flex items-center gap-1 text-amber-400">
            <AlertTriangle className="h-3.5 w-3.5" /> {continued} continued
          </span>
        )}
        {skipped > 0 && (
          <span className="flex items-center gap-1 text-muted-foreground">
            <SkipForward className="h-3.5 w-3.5" /> {skipped} skipped
          </span>
        )}
        {waiting > 0 && (
          <span className="flex items-center gap-1 text-amber-400">
            <ShieldCheck className="h-3.5 w-3.5" /> {waiting} awaiting approval
          </span>
        )}
        <span className="ml-auto text-muted-foreground">{done}/{total} steps · {pct}%</span>
      </div>

      {/* animated bar */}
      <div className="relative h-2 overflow-hidden rounded-full bg-border/40">
        {total > 0 && (
          <>
            <div
              className="absolute inset-y-0 left-0 rounded-full bg-emerald-500 transition-all duration-500"
              style={completedStyle}
            />
            <div
              className="absolute inset-y-0 rounded-full bg-destructive transition-all duration-500"
              style={failedStyle}
            />
            <div
              className="absolute inset-y-0 rounded-full bg-muted-foreground/40 transition-all duration-500"
              style={skippedStyle}
            />
          </>
        )}
      </div>

      {/* frontier + elapsed */}
      <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
        {isActive && summary.currentFrontier && summary.currentFrontier.length > 0 && (
          <span>
            Frontier: {summary.currentFrontier.map((s) => (
              <Badge key={s} variant="outline" className="ml-1 text-[10px]">{s}</Badge>
            ))}
          </span>
        )}
        {summary.startedAt && (
          <span className="flex items-center gap-1">
            <Timer className="h-3 w-3" />
            {isActive ? `Elapsed: ${formatElapsed(summary.startedAt)}` : `Started: ${new Date(summary.startedAt).toLocaleTimeString()}`}
          </span>
        )}
        {summary.runId && (
          <span className="ml-auto font-mono text-[10px] opacity-60">run: {summary.runId}</span>
        )}
      </div>
    </div>
  );
}

/* ────────── loop progress display ────────── */

function LoopProgressDisplay({ progress }: { progress: LoopProgress }) {
  const pct = progress.totalItems > 0 ? Math.round((progress.completedItems / progress.totalItems) * 100) : 0;
  const cbState = progress.circuitBreakerState?.state ?? "closed";
  const items = progress.checklistItems ?? [];

  return (
    <div className="space-y-2 rounded-lg border border-violet-500/20 bg-violet-500/5 p-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs font-medium text-violet-300">
          <Repeat className="h-3.5 w-3.5" />
          Loop progress — iteration {progress.iteration}/{progress.maxIterations} · {progress.completedItems}/{progress.totalItems} items done
        </div>
        <div className="flex items-center gap-2">
          {cbState !== "closed" && (
            <Badge variant="outline" className={`text-[10px] ${cbState === "open" ? "border-destructive/40 text-destructive" : "border-amber-500/40 text-amber-300"}`}>
              CB: {cbState}
            </Badge>
          )}
          <span className="text-[10px] tabular-nums text-muted-foreground">{pct}%</span>
        </div>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-violet-500/10">
        <div className="h-full rounded-full bg-violet-500 transition-all" style={{ width: `${pct}%` }} />
      </div>

      {/* Checklist items visualization */}
      {items.length > 0 && (
        <div className="mt-2 space-y-1">
          <div className="text-[10px] font-medium text-violet-300/80 uppercase tracking-wide">Plan checklist</div>
          {items.map((item, i) => (
            <div key={i} className={`flex items-start gap-2 rounded px-2 py-1 text-[11px] ${item.done ? "bg-emerald-500/10 text-emerald-300" : "text-muted-foreground"}`}>
              {item.done ? (
                <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-emerald-400" />
              ) : (
                <Circle className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground/50" />
              )}
              <span className={item.done ? "line-through opacity-70" : ""}>{item.text}</span>
            </div>
          ))}
        </div>
      )}

      {progress.featureBranch && (
        <span className="text-[10px] text-muted-foreground">Branch: {progress.featureBranch}</span>
      )}
      {progress.lastCommitSha && (
        <span className="ml-2 text-[10px] font-mono text-muted-foreground">Last commit: {progress.lastCommitSha.slice(0, 8)}</span>
      )}
      {progress.exitReason && (
        <div className="text-[10px] text-amber-300">Exit: {progress.exitReason}</div>
      )}
    </div>
  );
}

/* ────────── plan progress display (non-loop steps) ────────── */

function PlanProgressDisplay({ progress }: { progress: PlanProgress }) {
  const items = progress.items ?? [];
  const pct = progress.totalItems > 0 ? Math.round((progress.completedItems / progress.totalItems) * 100) : 0;
  if (items.length === 0) return null;

  return (
    <div className="space-y-2 rounded-lg border border-sky-500/20 bg-sky-500/5 p-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs font-medium text-sky-300">
          <Blocks className="h-3.5 w-3.5" />
          Agent plan — {progress.completedItems}/{progress.totalItems} tasks done
        </div>
        <span className="text-[10px] tabular-nums text-muted-foreground">{pct}%</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-sky-500/10">
        <div className="h-full rounded-full bg-sky-500 transition-all" style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-2 space-y-1">
        {items.map((item, i) => (
          <div key={i} className={`flex items-start gap-2 rounded px-2 py-1 text-[11px] ${item.done ? "bg-emerald-500/10 text-emerald-300" : "text-muted-foreground"}`}>
            {item.done ? (
              <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-emerald-400" />
            ) : (
              <Circle className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground/50" />
            )}
            <span className={item.done ? "line-through opacity-70" : ""}>{item.text}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ────────── step detail card ────────── */

function StepDetailCard({
  step,
  state,
  isApprovalWaiting,
  approvalReason,
  approvalBusy,
  onApprovalReasonChange,
  onApprovalDecision,
}: {
  step: WorkflowStep;
  state: WorkflowStepState | undefined;
  isApprovalWaiting: boolean;
  approvalReason: string;
  approvalBusy: boolean;
  onApprovalReasonChange: (v: string) => void;
  onApprovalDecision: (d: "approved" | "denied") => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const status = state?.status ?? "pending";
  const { icon, ring } = stepStatusIcon(status, isApprovalWaiting);
  const jsonContractFailure = isJsonContractFailure(state?.error);
  const requiredJsonPaths = requiredJsonPathsForStep(step, state);
  const artifactSummaries = state?.artifacts ?? [];
  const toolCallSummaries = state?.toolCalls ?? [];
  const warnings = state?.warnings ?? [];
  const warningCount = warnings.length;

  useEffect(() => {
    if (isApprovalWaiting || status === "running" || status === "failed" || jsonContractFailure || warningCount > 0) {
      setExpanded(true);
    }
  }, [isApprovalWaiting, jsonContractFailure, status, step.name, warningCount]);

  return (
    <div className="group relative flex gap-3">
      {/* connector + icon */}
      <div className="flex flex-col items-center">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-2xl border bg-background/80 shadow-sm transition-all duration-300 ${ring} hover:brightness-110 hover:scale-105 active:scale-95 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none`}
          title={expanded ? "Collapse" : "Expand"}
          aria-label={expanded ? "Collapse step details" : "Expand step details"}
        >
          {icon}
        </button>
      </div>

      {/* content */}
      <div className="flex-1 pb-3">
        {/* header row */}
        <button
          type="button"
          className="flex w-full items-center gap-2 text-left"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? (
            <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
          )}
          <span className="text-sm font-medium">{step.name}</span>
          <Badge variant={statusBadgeVariant(status)} className="text-[10px]">{status}</Badge>
          {step.step_type === "loop" && (
            <Badge variant="outline" className="border-violet-500/30 bg-violet-500/10 text-violet-300 text-[10px]">
              <Repeat className="mr-1 h-3 w-3" />loop
            </Badge>
          )}
          {step.step_type === "review" && (
            <Badge variant="outline" className="border-blue-500/30 bg-blue-500/10 text-blue-300 text-[10px]">
              <ShieldCheck className="mr-1 h-3 w-3" />review
            </Badge>
          )}
          {state?.verificationResult && (
            <Badge
              variant="outline"
              className={`text-[10px] ${
                state.verificationResult.passed
                  ? "border-green-500/30 bg-green-500/10 text-green-300"
                  : "border-red-500/30 bg-red-500/10 text-red-300"
              }`}
            >
              {state.verificationResult.passed ? "✓ verified" : "✗ verify failed"}
            </Badge>
          )}
          {state?.reviewResult && (
            <Badge
              variant="outline"
              className={`text-[10px] ${
                state.reviewResult.approved
                  ? "border-green-500/30 bg-green-500/10 text-green-300"
                  : "border-amber-500/30 bg-amber-500/10 text-amber-300"
              }`}
            >
              {state.reviewResult.approved ? "✓ approved" : "✗ rejected"}
            </Badge>
          )}
          <span className="text-xs text-muted-foreground">
            {step.agent_ref}{step.require_approval ? " · approval gate" : ""}
          </span>
          {state?.loopProgress && (
            <span className="text-[10px] tabular-nums text-violet-300">
              {state.loopProgress.completedItems}/{state.loopProgress.totalItems} items
            </span>
          )}
          {state?.planProgress && !state?.loopProgress && (
            <span className="text-[10px] tabular-nums text-sky-300">
              {state.planProgress.completedItems}/{state.planProgress.totalItems} tasks
            </span>
          )}
          {state?.toolCallCount != null && state.toolCallCount > 0 && (
            <span className="text-[10px] tabular-nums text-sky-300">
              {state.toolCallCount} tool{state.toolCallCount === 1 ? "" : "s"}
            </span>
          )}
          {state?.artifactCount != null && state.artifactCount > 0 && (
            <span className="text-[10px] tabular-nums text-emerald-300">
              {state.artifactCount} file{state.artifactCount === 1 ? "" : "s"}
            </span>
          )}
          {warningCount > 0 && (
            <span className="text-[10px] tabular-nums text-amber-300">
              {warningCount} warning{warningCount === 1 ? "" : "s"}
            </span>
          )}
          {state?.latencyMs != null && (
            <span className="ml-auto text-[10px] tabular-nums text-muted-foreground">{formatMs(state.latencyMs)}</span>
          )}
        </button>

        {/* expanded detail */}
        {expanded && (
          <div className="mt-2 space-y-2 rounded-[1.15rem] border border-border/60 bg-background/70 p-3 text-xs shadow-sm backdrop-blur-sm animate-slide-down">
            {/* timing & attempts */}
            <div className="flex flex-wrap gap-4 text-muted-foreground">
              {state?.startedAt && (
                <span>Started: {new Date(state.startedAt).toLocaleTimeString()}</span>
              )}
              {state?.completedAt && (
                <span>Completed: {new Date(state.completedAt).toLocaleTimeString()}</span>
              )}
              {state?.updatedAt && !state?.completedAt && (
                <span>Last update: {new Date(state.updatedAt).toLocaleTimeString()}</span>
              )}
              {state?.latencyMs != null && (
                <span>Duration: {formatMs(state.latencyMs)}</span>
              )}
              {state?.attempts != null && state.attempts > 0 && (
                <span>Attempts: {state.attempts}</span>
              )}
              {state?.approvalWaitMs != null && (
                <span>Approval wait: {formatMs(state.approvalWaitMs)}</span>
              )}
            </div>

            {(state?.toolCallCount != null && state.toolCallCount > 0) || (state?.artifactCount != null && state.artifactCount > 0) || warnings.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {state?.toolCallCount != null && state.toolCallCount > 0 && (
                  <Badge variant="outline" className="border-sky-500/30 bg-sky-500/10 text-[10px] text-sky-300">
                    {state.toolCallCount} tool call{state.toolCallCount === 1 ? "" : "s"}
                  </Badge>
                )}
                {state?.artifactCount != null && state.artifactCount > 0 && (
                  <Badge variant="outline" className="border-emerald-500/30 bg-emerald-500/10 text-[10px] text-emerald-300">
                    {state.artifactCount} artifact{state.artifactCount === 1 ? "" : "s"}
                  </Badge>
                )}
                {warnings.length > 0 && (
                  <Badge variant="outline" className="border-amber-500/30 bg-amber-500/10 text-[10px] text-amber-300">
                    {warnings.length} warning{warnings.length === 1 ? "" : "s"}
                  </Badge>
                )}
              </div>
            ) : null}

            {/* loop progress */}
            {state?.loopProgress && (
              <LoopProgressDisplay progress={state.loopProgress} />
            )}

            {/* plan progress (non-loop steps with agent plan) */}
            {state?.planProgress && !state?.loopProgress && (
              <PlanProgressDisplay progress={state.planProgress} />
            )}

            {/* verification result */}
            {state?.verificationResult && (
              <div className={`rounded-lg border px-3 py-2 ${
                state.verificationResult.passed
                  ? "border-green-500/30 bg-green-500/10 text-green-300"
                  : "border-red-500/30 bg-red-500/10 text-red-300"
              }`}>
                <span className="font-medium">
                  Verification: {state.verificationResult.passed ? "PASSED" : "FAILED"}
                </span>
                {state.verificationResult.criteria && (
                  <div className="mt-1 text-muted-foreground">Criteria: {state.verificationResult.criteria}</div>
                )}
                {state.verificationResult.response && (
                  <div className="mt-1 whitespace-pre-wrap">{state.verificationResult.response}</div>
                )}
              </div>
            )}

            {/* review result */}
            {state?.reviewResult && (
              <div className={`rounded-lg border px-3 py-2 ${
                state.reviewResult.approved
                  ? "border-green-500/30 bg-green-500/10 text-green-300"
                  : "border-amber-500/30 bg-amber-500/10 text-amber-300"
              }`}>
                <span className="font-medium">
                  Review: {state.reviewResult.verdict ?? (state.reviewResult.approved ? "APPROVED" : "REJECTED")}
                </span>
                {state.reviewResult.criteria && (
                  <div className="mt-1 text-muted-foreground">Criteria: {state.reviewResult.criteria}</div>
                )}
                {state.reviewResult.response && (
                  <div className="mt-1 whitespace-pre-wrap">{state.reviewResult.response}</div>
                )}
              </div>
            )}

            {/* iteration failures */}
            {state?.iterationFailures && state.iterationFailures.length > 0 && (
              <details>
                <summary className="cursor-pointer text-xs font-medium text-amber-300 hover:text-amber-200">
                  {state.iterationFailures.length} iteration failure(s)
                </summary>
                <div className="mt-1 space-y-1">
                  {state.iterationFailures.map((f, i) => (
                    <div key={i} className="rounded-md border border-red-500/20 bg-red-500/5 px-2 py-1 text-[11px]">
                      <span className="text-muted-foreground">Iteration {f.iteration}</span>
                      {f.failureClass && <span className="ml-1 text-red-400">({f.failureClass})</span>}
                      <span className="ml-1 text-red-300">{f.error}</span>
                    </div>
                  ))}
                </div>
              </details>
            )}

            {jsonContractFailure && (
              <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-amber-100">
                <div className="font-medium text-amber-300">JSON contract failure</div>
                <div className="mt-1 text-[11px] leading-relaxed text-amber-100/80">
                  The agent may still have written files or completed tool calls, but the workflow only marks the step successful when the final response returns valid JSON with every required path.
                </div>
                {requiredJsonPaths.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {requiredJsonPaths.map((path) => (
                      <Badge key={path} variant="outline" className="border-amber-500/30 bg-background/60 text-[10px] text-amber-200">
                        {path}
                      </Badge>
                    ))}
                  </div>
                )}
                {state?.responsePreview && (
                  <pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap rounded-lg bg-background/70 p-2 text-[11px] leading-relaxed text-foreground">
                    {state.responsePreview}
                  </pre>
                )}
              </div>
            )}

            {/* error */}
            {state?.error && (
              <div className="group relative rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-destructive">
                <div className="absolute top-1.5 right-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
                  <CopyButton value={state.error} />
                </div>
                <span className="font-medium">Error{state.failureClass ? ` (${state.failureClass})` : ""}:</span>{" "}
                {state.error}
              </div>
            )}

            {!jsonContractFailure && state?.responsePreview && (
              <details>
                <summary className="cursor-pointer text-xs font-medium text-muted-foreground hover:text-foreground">
                  Last response preview
                </summary>
                <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap rounded-lg bg-background p-2 text-[11px] leading-relaxed text-muted-foreground">
                  {state.responsePreview}
                </pre>
              </details>
            )}

            {toolCallSummaries.length > 0 && (
              <details>
                <summary className="cursor-pointer text-xs font-medium text-muted-foreground hover:text-foreground">
                  Recent tool activity
                </summary>
                <div className="mt-1 space-y-1">
                  {toolCallSummaries.map((toolCall, index) => {
                    const meta = toolCallSummaryMeta(toolCall);
                    return (
                      <div key={`${toolCall.tool ?? toolCall.preview ?? index}-${index}`} className="rounded-md border border-sky-500/20 bg-sky-500/5 px-2 py-1 text-[11px]">
                        <div className="font-medium text-sky-200">{toolCallSummaryLabel(toolCall, index)}</div>
                        {meta && <div className="mt-0.5 text-muted-foreground">{meta}</div>}
                      </div>
                    );
                  })}
                </div>
              </details>
            )}

            {artifactSummaries.length > 0 && (
              <details>
                <summary className="cursor-pointer text-xs font-medium text-muted-foreground hover:text-foreground">
                  Artifacts observed
                </summary>
                <div className="mt-1 space-y-1">
                  {artifactSummaries.map((artifact, index) => {
                    const meta = artifactSummaryMeta(artifact);
                    return (
                      <div key={`${artifact.path ?? artifact.name ?? artifact.preview ?? index}-${index}`} className="rounded-md border border-emerald-500/20 bg-emerald-500/5 px-2 py-1 text-[11px]">
                        <div className="font-medium text-emerald-200">{artifactSummaryLabel(artifact, index)}</div>
                        {meta && <div className="mt-0.5 text-muted-foreground">{meta}</div>}
                      </div>
                    );
                  })}
                </div>
              </details>
            )}

            {warnings.length > 0 && (
              <details>
                <summary className="cursor-pointer text-xs font-medium text-muted-foreground hover:text-foreground">
                  Warnings
                </summary>
                <div className="mt-1 space-y-1">
                  {warnings.map((warning, index) => (
                    <div key={`${warning.slice(0, 48)}-${index}`} className="rounded-md border border-amber-500/20 bg-amber-500/5 px-2 py-1 text-[11px] text-amber-100">
                      {warning}
                    </div>
                  ))}
                </div>
              </details>
            )}

            {/* execution policy */}
            {state?.execution && Object.keys(state.execution).length > 0 && (
              <details>
                <summary className="cursor-pointer text-xs font-medium text-muted-foreground hover:text-foreground">
                  Execution policy
                </summary>
                <div className="mt-1">
                  <JsonBlock data={state.execution} maxHeight="max-h-48" />
                </div>
              </details>
            )}

            {/* step prompt */}
            {step.prompt && (
              <details className="group">
                <summary className="cursor-pointer text-xs font-medium text-muted-foreground hover:text-foreground">
                  Prompt
                </summary>
                <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap rounded-lg bg-background p-2 text-[11px] leading-relaxed text-muted-foreground">
                  {step.prompt}
                </pre>
              </details>
            )}

            {/* dependencies */}
            {step.depends_on.length > 0 && (
              <div className="text-muted-foreground">
                Depends on: {step.depends_on.map((d) => (
                  <Badge key={d} variant="outline" className="ml-1 text-[10px]">{d}</Badge>
                ))}
              </div>
            )}
          </div>
        )}

        {/* inline approval controls */}
        {isApprovalWaiting && (
          <div className="mt-2 rounded-xl border border-amber-500/30 bg-amber-500/5 p-3 space-y-2">
            <div className="flex items-center gap-2 text-sm text-amber-300">
              <ShieldCheck className="h-4 w-4" />
              <span className="font-medium">Approval required for step “{step.name}”</span>
            </div>
            <Textarea
              rows={2}
              className="text-xs"
              placeholder="Optional reason or notes…"
              value={approvalReason}
              onChange={(e) => onApprovalReasonChange(e.target.value)}
              disabled={approvalBusy}
            />
            <div className="flex gap-2">
              <Button
                size="sm"
                className="h-7 rounded-lg bg-emerald-600 text-xs hover:bg-emerald-500"
                disabled={approvalBusy}
                onClick={() => onApprovalDecision("approved")}
              >
                {approvalBusy ? <LoaderCircle className="mr-1 h-3 w-3 animate-spin" /> : <CheckCircle2 className="mr-1 h-3 w-3" />}
                Approve
              </Button>
              <Button
                size="sm"
                variant="destructive"
                className="h-7 rounded-lg text-xs"
                disabled={approvalBusy}
                onClick={() => onApprovalDecision("denied")}
              >
                {approvalBusy ? <LoaderCircle className="mr-1 h-3 w-3 animate-spin" /> : <XCircle className="mr-1 h-3 w-3" />}
                Deny
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ────────── agent file browser tabs ────────── */

function AgentFileBrowserTabs({
  agents,
  token,
  namespace,
  liveUpdatesEnabled,
}: {
  agents: string[];
  token: string | null;
  namespace: string;
  liveUpdatesEnabled: boolean;
}) {
  const [activeAgent, setActiveAgent] = useState(agents[0] ?? "");
  const [zipping, setZipping] = useState(false);

  const loadFiles = useCallback(async () => {
    if (!token || !activeAgent) return { files: [], truncated: false, roots: [] };
    return listAgentArtifacts(token, namespace, activeAgent);
  }, [token, namespace, activeAgent]);

  const handleDownload = useCallback(async (path: string, filename?: string) => {
    if (!token || !activeAgent) return;
    await downloadAgentArtifact(token, namespace, activeAgent, path, filename);
  }, [token, namespace, activeAgent]);

  const handlePreview = useCallback(async (path: string) => {
    if (!token || !activeAgent) {
      throw new Error("Enter a gateway token before previewing files.");
    }
    return previewAgentArtifact(token, namespace, activeAgent, path);
  }, [token, namespace, activeAgent]);

  const handleDownloadZip = useCallback(async () => {
    if (!token || !activeAgent) return;
    setZipping(true);
    try {
      await downloadAgentArtifactZip(token, namespace, activeAgent);
    } finally {
      setZipping(false);
    }
  }, [token, namespace, activeAgent]);

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        {agents.length > 1 && (
          <div className="flex gap-1 flex-1">
            {agents.map((agent) => (
              <Button
                key={agent}
                size="sm"
                variant={agent === activeAgent ? "secondary" : "ghost"}
                className="h-7 rounded-lg text-[11px]"
                onClick={() => setActiveAgent(agent)}
              >
                {agent}
              </Button>
            ))}
          </div>
        )}
        <Button
          size="sm"
          variant="outline"
          className="h-7 rounded-lg text-[11px] ml-auto"
          disabled={zipping || !activeAgent}
          onClick={handleDownloadZip}
        >
          <Download className="h-3.5 w-3.5 mr-1.5" />
          {zipping ? "Downloading…" : "Download All (ZIP)"}
        </Button>
      </div>
      {activeAgent && (
        <FileExplorer
          agentName={activeAgent}
          onLoad={loadFiles}
          onDownload={handleDownload}
          onPreview={handlePreview}
          liveUpdatesEnabled={liveUpdatesEnabled}
        />
      )}
    </div>
  );
}

/* ────────── main component ────────── */

export function WorkflowManager({
  workflow,
  agents,
  isSaving,
  isDeleting,
  isRunning,
  error,
  onCreate,
  onUpdate,
  onDelete,
  onTrigger,
  onCancel,
  isCancelling,
  onRetryFailed,
  isRetrying,
  factoryMode,
  onFactoryModeChange,
  approvalReason,
  approvalBusy,
  onApprovalReasonChange,
  onApprovalDecision,
  onOpenComposer,
}: WorkflowManagerProps) {
  const { canMutate, token, namespace } = useConnection();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [input, setInput] = useState("");
  const [contextRef, setContextRef] = useState("");
  const [messageBus, setMessageBus] = useState("in-memory");
  const [steps, setSteps] = useState<WorkflowStep[]>(() => defaultStepsForAgent(agents[0]?.name));
  const [nextAction, setNextAction] = useState<WorkflowNextAction | null>(null);
  const [stepViewFilter, setStepViewFilter] = useState<StepViewFilter>("all");
  const [workspaceTab, setWorkspaceTab] = useState<"live" | "history" | "definition">("definition");
  const [selectedHistoryRun, setSelectedHistoryRun] = useState<WorkflowRunRecord | null>(null);

  // Trigger confirmation input (separate from workflow spec input)
  const [triggerInput, setTriggerInput] = useState("");
  const [showTriggerConfirm, setShowTriggerConfirm] = useState(false);

  useEffect(() => {
    if (workflow) {
      setName(workflow.name);
      setDescription(workflow.description);
      setInput(workflow.input);
      setContextRef(workflow.context_ref ?? "");
      setMessageBus(workflow.message_bus);
      setSteps(workflow.steps.length > 0 ? workflow.steps : defaultStepsForAgent(agents[0]?.name));
      // Pre-fill trigger input with workflow spec input
      setTriggerInput(workflow.input ?? "");
      setShowTriggerConfirm(false);
      return;
    }
    setName("");
    setDescription("");
    setInput("");
    setContextRef("");
    setMessageBus("in-memory");
    setSteps(defaultStepsForAgent(agents[0]?.name));
    setTriggerInput("");
    setShowTriggerConfirm(false);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflow?.name, workflow?.phase, workflow?.current_step]);

  useEffect(() => {
    let cancelled = false;
    async function loadNextAction() {
      if (!workflow || !token || !namespace) {
        setNextAction(null);
        return;
      }
      try {
        const payload = await fetchWorkflowNextAction(token, namespace, workflow.name);
        if (!cancelled) {
          setNextAction(payload);
        }
      } catch {
        if (!cancelled) {
          setNextAction(null);
        }
      }
    }
    void loadNextAction();
    return () => {
      cancelled = true;
    };
  }, [workflow?.name, workflow?.phase, workflow?.current_step, token, namespace]);

  useEffect(() => {
    setStepViewFilter("all");
  }, [workflow?.name, workflow?.run_id]);

  useEffect(() => {
    setSelectedHistoryRun(null);
  }, [workflow?.name]);

  function updateStep(index: number, updater: (current: WorkflowStep) => WorkflowStep) {
    setSteps((current) => current.map((step, stepIndex) => (stepIndex === index ? updater(step) : step)));
  }

  function renameStep(index: number, nextName: string) {
    setSteps((current) => {
      const previousName = current[index]?.name ?? "";
      return current.map((step, stepIndex) => {
        const renamedStep =
          stepIndex === index
            ? {
                ...step,
                name: nextName,
              }
            : step;

        if (!previousName || previousName === nextName) {
          return renamedStep;
        }

        return {
          ...renamedStep,
          depends_on: renamedStep.depends_on.map((dependency) => (dependency === previousName ? nextName : dependency)),
        };
      });
    });
  }

  function removeStep(index: number) {
    setSteps((current) => {
      const removedName = current[index]?.name ?? "";
      return current
        .filter((_, stepIndex) => stepIndex !== index)
        .map((step) => ({
          ...step,
          depends_on: step.depends_on.filter((dependency) => dependency !== removedName),
        }));
    });
  }

  function toggleDependency(index: number, dependency: string) {
    updateStep(index, (current) => {
      const active = current.depends_on.includes(dependency);
      return {
        ...current,
        depends_on: active
          ? current.depends_on.filter((item) => item !== dependency)
          : [...current.depends_on, dependency],
      };
    });
  }

  const stepNames = steps.map((s) => s.name.trim()).filter(Boolean);
  const hasUniqueStepNames = new Set(stepNames).size === stepNames.length;
  const canSubmit = Boolean(name.trim()) && steps.length > 0 && hasUniqueStepNames && steps.every((step) => step.name.trim() && step.agent_ref.trim());
  const uniqueAgentCount = new Set(steps.map((step) => step.agent_ref).filter(Boolean)).size;
  const approvalStepCount = steps.filter((step) => step.require_approval).length;
  const loopStepCount = steps.filter((step) => step.step_type === "loop").length;
  const reviewStepCount = steps.filter((step) => step.step_type === "review").length;

  // Derive pending approval step name for inline controls
  const pendingApprovalStep = useMemo(() => {
    if (!workflow?.pending_approval) return null;
    const pa = workflow.pending_approval;
    return typeof pa.stepName === "string" ? pa.stepName : (workflow.current_step || null);
  }, [workflow?.pending_approval, workflow?.current_step]);

  const wfSummary: WorkflowSummary | undefined = workflow?.summary ?? undefined;
  const isActive = workflow?.phase === "running" || workflow?.phase === "queued" || workflow?.phase === "waiting-approval";
  const hasBeenTriggered = Boolean(workflow && (workflow.phase !== "pending" || workflow.run_id || workflow.summary));
  const completedStepCount = wfSummary?.completedSteps ?? Object.values(workflow?.step_states ?? {}).filter((state) => state?.status === "succeeded" || state?.status === "completed").length;
  const failedStepCount = wfSummary?.failedSteps ?? Object.values(workflow?.step_states ?? {}).filter((state) => state?.status === "failed").length;
  const waitingApprovalCount = wfSummary?.waitingApprovalSteps ?? (workflow?.pending_approval ? 1 : 0);
  const currentFocus = workflow?.current_step || wfSummary?.currentFrontier?.[0] || nextAction?.failedSteps?.[0] || nextAction?.verifyFailures?.[0] || "Ready for execution";
  const workflowBrief = useMemo(() => {
    if (!workflow) {
      return {
        tone: "border-primary/20 bg-primary/5",
        title: "Design an orchestration path that is easy to operate",
        body: "Use clear step ownership, deliberate approval gates, and retry-friendly boundaries so the workflow reads like an operational playbook instead of a prompt chain.",
      };
    }
    if (workflow.phase === "waiting-approval") {
      return {
        tone: "border-amber-500/20 bg-amber-500/10",
        title: "Execution is blocked on a human gate",
        body: `The current run has reached an approval boundary at ${currentFocus}. Resolve that decision before expecting additional progress from the operator.`,
      };
    }
    if (workflow.phase === "running" || workflow.phase === "queued") {
      return {
        tone: "border-primary/20 bg-primary/5",
        title: "The workflow is actively progressing through its execution graph",
        body: `${completedStepCount} of ${wfSummary?.totalSteps ?? steps.length} steps are complete. Focus attention on ${currentFocus} and use logs or run history to verify whether this run is tracking normally.`,
      };
    }
    if (workflow.phase === "failed") {
      return {
        tone: "border-red-500/20 bg-red-500/10",
        title: "The latest run failed and should be triaged before re-running end to end",
        body: `${failedStepCount} step${failedStepCount === 1 ? "" : "s"} failed. Use the failed-step summary, logs, and recent-run comparison below to isolate what regressed and retry only what broke.`,
      };
    }
    if (workflow.phase === "completed" || workflow.phase === "succeeded") {
      return {
        tone: "border-emerald-500/20 bg-emerald-500/10",
        title: "The workflow is in a strong state for reuse and comparison",
        body: `The last execution completed successfully across ${wfSummary?.totalSteps ?? steps.length} steps. Compare that result against prior runs before changing prompts, agents, or approval policy.`,
      };
    }
    return {
      tone: "border-border/60 bg-muted/20",
      title: "The workflow definition is ready, but the operational story is still ahead",
      body: "Run the workflow once to capture the first execution baseline, then refine failure handling, approvals, and run-to-run consistency from real results.",
    };
  }, [completedStepCount, currentFocus, failedStepCount, steps.length, wfSummary?.totalSteps, workflow,]);
  const workflowSignals = useMemo(() => {
    const attentionSteps: WorkflowSignalStep[] = [];
    const activitySteps: WorkflowSignalStep[] = [];
    let activeSteps = 0;
    let completedSteps = 0;
    let totalToolCalls = 0;
    let totalArtifacts = 0;
    let totalWarnings = 0;
    let verificationFailures = 0;
    let reviewRejections = 0;
    let jsonContractFailures = 0;

    for (const step of steps) {
      const state = workflow?.step_states?.[step.name];
      const isApprovalWaiting = pendingApprovalStep === step.name;
      const status = state?.status ?? "pending";
      const warningCount = state?.warnings?.length ?? 0;
      const toolCallCount = state?.toolCallCount ?? 0;
      const artifactCount = state?.artifactCount ?? 0;
      const reasons: string[] = [];

      if (isApprovalWaiting) reasons.push("approval");
      if (status === "failed") reasons.push("failed");
      if (status === "continued") reasons.push("continued");
      if (state?.verificationResult && !state.verificationResult.passed) {
        verificationFailures += 1;
        reasons.push("verify");
      }
      if (state?.reviewResult && !state.reviewResult.approved) {
        reviewRejections += 1;
        reasons.push("review");
      }
      if (isJsonContractFailure(state?.error)) {
        jsonContractFailures += 1;
        reasons.push("json");
      }
      if (warningCount > 0) {
        reasons.push(`${warningCount} warning${warningCount === 1 ? "" : "s"}`);
      }

      if (isStepActive(status, isApprovalWaiting)) activeSteps += 1;
      if (isStepComplete(status)) completedSteps += 1;
      if (needsStepAttention(state, isApprovalWaiting)) {
        attentionSteps.push({
          name: step.name,
          reasons,
          toolCallCount,
          artifactCount,
          warningCount,
        });
      }
      if (hasStepActivity(state)) {
        activitySteps.push({
          name: step.name,
          reasons,
          toolCallCount,
          artifactCount,
          warningCount,
        });
      }

      totalToolCalls += toolCallCount;
      totalArtifacts += artifactCount;
      totalWarnings += warningCount;
    }

    return {
      attentionSteps,
      activitySteps,
      activeSteps,
      completedSteps,
      totalToolCalls,
      totalArtifacts,
      totalWarnings,
      verificationFailures,
      reviewRejections,
      jsonContractFailures,
    };
  }, [pendingApprovalStep, steps, workflow?.step_states]);
  const stepFilterOptions = useMemo(() => ([
    { value: "all" as const, label: "All", count: steps.length },
    { value: "active" as const, label: "Active", count: workflowSignals.activeSteps },
    { value: "attention" as const, label: "Attention", count: workflowSignals.attentionSteps.length },
    { value: "activity" as const, label: "Activity", count: workflowSignals.activitySteps.length },
    { value: "complete" as const, label: "Done", count: workflowSignals.completedSteps },
  ]), [steps.length, workflowSignals.activeSteps, workflowSignals.activitySteps.length, workflowSignals.attentionSteps.length, workflowSignals.completedSteps]);
  const visibleSteps = useMemo(() => (
    steps.filter((step) => stepMatchesViewFilter(stepViewFilter, workflow?.step_states?.[step.name], pendingApprovalStep === step.name))
  ), [pendingApprovalStep, stepViewFilter, steps, workflow?.step_states]);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const isFactoryWorkflow = isFactoryWorkflowName(workflow?.name);
  const activeRunAgents = useMemo(() => {
    if (!workflow) return [] as string[];
    const result = new Set<string>();
    for (const step of workflow.steps) {
      const state = workflow.step_states?.[step.name];
      if (state && state.status !== "pending" && step.agent_ref) {
        result.add(step.agent_ref);
      }
    }
    return Array.from(result);
  }, [workflow]);

  useEffect(() => {
    setWorkspaceTab(workflow && hasBeenTriggered ? "live" : "definition");
  }, [hasBeenTriggered, workflow?.name, workflow?.run_id]);

  function handleTrigger() {
    if (!workflow) return;
    onTrigger(workflow.name, triggerInput.trim() || undefined, isFactoryWorkflow ? factoryMode : undefined);
    setShowTriggerConfirm(false);
  }

  return (
    <Card className="border-border/70 bg-card/95 shadow-[0_24px_80px_-48px_rgba(0,0,0,0.65)]">
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary shadow-inner shadow-primary/10">
            <Workflow className="h-4 w-4" />
          </div>
          <div className="flex-1">
            <CardTitle className="text-sm">{workflow ? workflow.name : "Create workflow"}</CardTitle>
          </div>
          <div className="flex items-center gap-2">
            {isFactoryWorkflow && (
              <Badge variant="outline" className="border-primary/20 bg-primary/5 text-primary/80 text-[10px]">
                {factoryModeLabel(factoryMode)}
              </Badge>
            )}
            <Badge variant={isActive ? "default" : (workflow?.phase === "failed" || workflow?.phase === "cancelled") ? "destructive" : "secondary"} className="text-[10px]">
              {workflow?.phase ?? "draft"}
            </Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* ── Summary counters — single compact strip ── */}
        <div className="grid grid-cols-4 gap-1.5">
          <div className={`${SIGNAL_PANEL_CLASS} border-primary/20 bg-primary/5 px-2.5 py-1`}>
            <div className="flex items-baseline justify-between gap-1">
              <span className="text-[9px] uppercase tracking-widest text-primary/70">Status</span>
              <span className="text-sm font-semibold text-foreground">{workflow?.phase ?? "draft"}</span>
            </div>
          </div>
          <div className={`${SIGNAL_PANEL_CLASS} border-sky-500/20 bg-sky-500/5 px-2.5 py-1`}>
            <div className="flex items-baseline justify-between gap-1">
              <span className="text-[9px] uppercase tracking-widest text-sky-400/70">Steps</span>
              <span className="text-sm font-semibold text-foreground">
                {wfSummary ? `${(wfSummary.completedSteps ?? 0) + (wfSummary.failedSteps ?? 0)}/${wfSummary.totalSteps ?? steps.length}` : steps.length}
              </span>
            </div>
          </div>
          <div className={`${SIGNAL_PANEL_CLASS} border-violet-500/20 bg-violet-500/5 px-2.5 py-1`}>
            <div className="flex items-baseline justify-between gap-1">
              <span className="text-[9px] uppercase tracking-widest text-violet-400/70">Agents</span>
              <span className="text-sm font-semibold text-foreground">{uniqueAgentCount}</span>
            </div>
          </div>
          <div className={`${SIGNAL_PANEL_CLASS} border-amber-500/20 bg-amber-500/5 px-2.5 py-1`}>
            <div className="flex items-baseline justify-between gap-1">
              <span className="text-[9px] uppercase tracking-widest text-amber-400/70">{isActive ? "Elapsed" : "Approvals"}</span>
              <span className="text-sm font-semibold text-foreground">
                {isActive && wfSummary?.startedAt ? formatElapsed(wfSummary.startedAt) : approvalStepCount}
              </span>
            </div>
          </div>
        </div>

        <Card className={WORKSPACE_PANEL_CLASS}>
          <CardContent className="p-2">
            <div className="grid gap-2 xl:grid-cols-[minmax(0,1.45fr)_minmax(16rem,1fr)]">
              <div className={workflowBrief.tone + " rounded-xl border px-2.5 py-2 shadow-sm backdrop-blur-sm"}>
                <div className="text-[9px] uppercase tracking-widest text-muted-foreground/70">Execution brief</div>
                <div className="text-xs font-semibold text-foreground">{workflowBrief.title}</div>
                <p className="text-[11px] leading-snug text-muted-foreground">{workflowBrief.body}</p>
                {nextAction && (
                  <div className="mt-1.5 rounded-lg border border-border/50 bg-background/60 px-2 py-1">
                    <div className="text-[9px] uppercase tracking-widest text-muted-foreground">Next</div>
                    <div className="text-xs font-medium text-foreground">{nextAction.action}</div>
                  </div>
                )}
              </div>
              <div className="grid gap-1.5 sm:grid-cols-2">
                <div className={`${SIGNAL_PANEL_CLASS} border-border/60 bg-background/70 px-2 py-1.5`}>
                  <div className="text-[9px] uppercase tracking-widest text-muted-foreground/60">Focus</div>
                  <div className="text-xs font-medium text-foreground">{currentFocus}</div>
                </div>
                <div className={`${SIGNAL_PANEL_CLASS} border-border/60 bg-background/70 px-2 py-1.5`}>
                  <div className="text-[9px] uppercase tracking-widest text-muted-foreground/60">Governance</div>
                  <div className="text-xs font-medium text-foreground">{approvalStepCount} gate{approvalStepCount === 1 ? "" : "s"}</div>
                </div>
                <div className={`${SIGNAL_PANEL_CLASS} border-border/60 bg-background/70 px-2 py-1.5`}>
                  <div className="text-[9px] uppercase tracking-widest text-muted-foreground/60">Model</div>
                  <div className="text-xs font-medium text-foreground">{messageBus}</div>
                  <div className="text-[10px] text-muted-foreground">{loopStepCount > 0 ? `${loopStepCount} loop` : "No loops"} · {reviewStepCount} review</div>
                </div>
                <div className={`${SIGNAL_PANEL_CLASS} border-border/60 bg-background/70 px-2 py-1.5`}>
                  <div className="text-[9px] uppercase tracking-widest text-muted-foreground/60">Run posture</div>
                  <div className="text-xs font-medium text-foreground">{completedStepCount} ok / {failedStepCount} fail</div>
                  <div className="text-[10px] text-muted-foreground">{uniqueAgentCount} agent{uniqueAgentCount === 1 ? "" : "s"} · {steps.length} step{steps.length === 1 ? "" : "s"}</div>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* ── Live progress bar (when summary exists) ── */}
        {workflow && wfSummary && (wfSummary.totalSteps ?? 0) > 0 && (
          <Card className={WORKSPACE_PANEL_CLASS}>
            <CardContent className="p-3">
              <ProgressSummaryBar summary={wfSummary} phase={workflow.phase} />
            </CardContent>
          </Card>
        )}

        <Tabs
          value={workflow && hasBeenTriggered ? workspaceTab : "definition"}
          onValueChange={(value) => setWorkspaceTab(value as "live" | "history" | "definition")}
          className="space-y-3"
        >
          {workflow && hasBeenTriggered && (
            <div className="rounded-[1.25rem] border border-border/60 bg-[linear-gradient(135deg,rgba(59,130,246,0.08),transparent_58%),linear-gradient(180deg,rgba(255,255,255,0.03),transparent)] p-2">
              <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
                <div className="px-2 py-1">
                  <div className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">Workflow workspace</div>
                  <div className="text-sm font-semibold text-foreground">Operate, trace, or edit without leaving this page.</div>
                </div>
                <TabsList className="h-auto w-full flex-wrap justify-start gap-2 rounded-[1rem] bg-transparent p-0 lg:w-auto">
                  <TabsTrigger value="live" className="gap-2 rounded-xl border border-border/60 bg-background/70 px-3 py-2 text-xs data-[state=active]:border-primary/30 data-[state=active]:bg-primary/10 data-[state=active]:text-foreground data-[state=active]:shadow-none">
                    <Clock className="h-3.5 w-3.5" />
                    Live run
                  </TabsTrigger>
                  <TabsTrigger value="history" className="gap-2 rounded-xl border border-border/60 bg-background/70 px-3 py-2 text-xs data-[state=active]:border-primary/30 data-[state=active]:bg-primary/10 data-[state=active]:text-foreground data-[state=active]:shadow-none">
                    <FolderOpen className="h-3.5 w-3.5" />
                    History and trace
                  </TabsTrigger>
                  <TabsTrigger value="definition" className="gap-2 rounded-xl border border-border/60 bg-background/70 px-3 py-2 text-xs data-[state=active]:border-primary/30 data-[state=active]:bg-primary/10 data-[state=active]:text-foreground data-[state=active]:shadow-none">
                    <Pencil className="h-3.5 w-3.5" />
                    Definition
                  </TabsTrigger>
                </TabsList>
              </div>
            </div>
          )}

          {workflow && hasBeenTriggered && (
            <TabsContent value="live" className="mt-0 space-y-3 animate-fade-in">

        {/* ── Cross-agent pipeline overview ── */}
        {workflow && hasBeenTriggered && steps.length > 1 && (
          <Card className={WORKSPACE_PANEL_CLASS}>
            <CardContent className="p-3">
              <div className="text-[10px] font-medium text-muted-foreground/80 uppercase tracking-wide mb-2">Agent pipeline</div>
              <div className="flex items-center gap-1 overflow-x-auto pb-1">
                {steps.map((step, idx) => {
                  const state = workflow.step_states?.[step.name];
                  const status = state?.status ?? "pending";
                  const lp = state?.loopProgress;
                  const pp = state?.planProgress;
                  const isRunning = status === "running";
                  const isDone = status === "succeeded" || status === "completed";
                  const isFailed = status === "failed";

                  return (
                    <div key={step.name} className="flex items-center gap-1">
                      <div className={`rounded-lg border px-3 py-2 min-w-[120px] transition-all ${
                        isRunning ? "border-primary/40 bg-primary/10 ring-1 ring-primary/20" :
                        isDone ? "border-emerald-500/30 bg-emerald-500/10" :
                        isFailed ? "border-destructive/30 bg-destructive/10" :
                        "border-border/40 bg-background/60"
                      }`}>
                        <div className="flex items-center gap-1.5 mb-1">
                          {stepStatusIcon(status, false).icon}
                          <span className="text-[11px] font-medium truncate">{step.name}</span>
                        </div>
                        <div className="text-[10px] text-muted-foreground truncate">{step.agent_ref}</div>
                        {lp && lp.totalItems > 0 && (
                          <div className="mt-1.5">
                            <div className="h-1 w-full overflow-hidden rounded-full bg-border/40">
                              <div
                                className={`h-full rounded-full transition-all duration-500 ${isDone ? "bg-emerald-500" : "bg-primary"}`}
                                style={{ width: `${Math.round((lp.completedItems / lp.totalItems) * 100)}%` }}
                              />
                            </div>
                            <div className="text-[9px] text-muted-foreground mt-0.5">
                              {lp.completedItems}/{lp.totalItems} · iter {lp.iteration}/{lp.maxIterations}
                            </div>
                          </div>
                        )}
                        {pp && pp.totalItems > 0 && !lp && (
                          <div className="mt-1.5">
                            <div className="h-1 w-full overflow-hidden rounded-full bg-border/40">
                              <div
                                className={`h-full rounded-full transition-all duration-500 ${isDone ? "bg-emerald-500" : "bg-sky-500"}`}
                                style={{ width: `${Math.round((pp.completedItems / pp.totalItems) * 100)}%` }}
                              />
                            </div>
                            <div className="text-[9px] text-muted-foreground mt-0.5">
                              {pp.completedItems}/{pp.totalItems} tasks
                            </div>
                          </div>
                        )}
                        {isRunning && !lp && !pp && (
                          <div className="mt-1">
                            <LoaderCircle className="h-3 w-3 animate-spin text-primary" />
                          </div>
                        )}
                      </div>
                      {idx < steps.length - 1 && (
                        <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/40 shrink-0" />
                      )}
                    </div>
                  );
                })}
              </div>
            </CardContent>
          </Card>
        )}

        {/* ── Suggested next action ── */}
        {workflow && nextAction && (
          <Card className="border-primary/20 bg-primary/5 shadow-sm backdrop-blur-sm">
            <CardContent className="p-3">
              <div className="flex items-start gap-2">
                <Sparkles className="h-4 w-4 mt-0.5 text-primary" />
                <div className="space-y-0.5">
                  <p className="text-xs uppercase tracking-[0.14em] text-primary/80">Suggested Next</p>
                  <p className="text-sm font-semibold text-foreground">{nextAction.action}</p>
                  <p className="text-xs text-muted-foreground">{nextAction.reason}</p>
                </div>
              </div>
            </CardContent>
          </Card>
        )}

        {workflow && hasBeenTriggered && (
          <Card className={WORKSPACE_PANEL_CLASS}>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Operator signals</CardTitle>
              <CardDescription>High-signal blockers from the current run.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
                <div className="rounded-2xl border border-amber-500/20 bg-amber-500/5 p-2.5">
                  <div className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">Attention</div>
                  <div className="text-lg font-semibold text-foreground">{workflowSignals.attentionSteps.length}</div>
                  <div className="text-[11px] text-muted-foreground">{workflowSignals.verificationFailures} verify · {workflowSignals.reviewRejections} review · {workflowSignals.jsonContractFailures} JSON</div>
                </div>
                <div className="rounded-2xl border border-primary/20 bg-primary/5 p-2.5">
                  <div className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">Active now</div>
                  <div className="text-lg font-semibold text-foreground">{workflowSignals.activeSteps}</div>
                  <div className="text-[11px] text-muted-foreground">{waitingApprovalCount} wait · {currentFocus}</div>
                </div>
                <div className="rounded-2xl border border-sky-500/20 bg-sky-500/5 p-2.5">
                  <div className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">Tool activity</div>
                  <div className="text-lg font-semibold text-foreground">{workflowSignals.totalToolCalls}</div>
                  <div className="text-[11px] text-muted-foreground">{workflowSignals.activitySteps.length} step{workflowSignals.activitySteps.length === 1 ? "" : "s"} with actions</div>
                </div>
                <div className="rounded-2xl border border-emerald-500/20 bg-emerald-500/5 p-2.5">
                  <div className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">Files observed</div>
                  <div className="text-lg font-semibold text-foreground">{workflowSignals.totalArtifacts}</div>
                  <div className="text-[11px] text-muted-foreground">{workflowSignals.totalWarnings} warning{workflowSignals.totalWarnings === 1 ? "" : "s"}</div>
                </div>
              </div>

              {workflowSignals.attentionSteps.length > 0 ? (
                <div className="space-y-2">
                  <div className="text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground/80">Needs attention</div>
                  <div className="flex flex-wrap gap-2">
                    {workflowSignals.attentionSteps.slice(0, 8).map((signal) => (
                      <div key={signal.name} className="rounded-full border border-amber-500/20 bg-amber-500/5 px-3 py-1.5 text-[11px]">
                        <span className="font-medium text-foreground">{signal.name}</span>
                        {signal.reasons.length > 0 && <span className="ml-2 text-muted-foreground">{signal.reasons.join(" · ")}</span>}
                      </div>
                    ))}
                    {workflowSignals.attentionSteps.length > 8 && (
                      <Badge variant="outline" className="border-amber-500/20 bg-amber-500/5 text-[10px] text-amber-200">
                        +{workflowSignals.attentionSteps.length - 8} more
                      </Badge>
                    )}
                  </div>
                </div>
              ) : (
                <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 px-3 py-2 text-xs text-emerald-300">
                  No failed steps, approval blockers, or warning signals are active right now.
                </div>
              )}

              {workflowSignals.activitySteps.length > 0 && (
                <div className="space-y-2">
                  <div className="text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground/80">Observed activity</div>
                  <div className="flex flex-wrap gap-2">
                    {workflowSignals.activitySteps.slice(0, 8).map((signal) => (
                      <div key={`${signal.name}-activity`} className="rounded-full border border-sky-500/20 bg-sky-500/5 px-3 py-1.5 text-[11px] text-muted-foreground">
                        <span className="font-medium text-foreground">{signal.name}</span>
                        <span className="ml-2">{signal.toolCallCount} tools · {signal.artifactCount} files{signal.warningCount > 0 ? ` · ${signal.warningCount} warnings` : ""}</span>
                      </div>
                    ))}
                    {workflowSignals.activitySteps.length > 8 && (
                      <Badge variant="outline" className="border-sky-500/20 bg-sky-500/5 text-[10px] text-sky-200">
                        +{workflowSignals.activitySteps.length - 8} more
                      </Badge>
                    )}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* ── Step pipeline (live view + expandable detail) ── */}
        {workflow && steps.length > 0 && (
          <Card className={WORKSPACE_PANEL_CLASS}>
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Clock className="h-4 w-4 text-muted-foreground" />
                  <CardTitle className="text-sm">Step pipeline</CardTitle>
                  {isActive && (
                    <Badge variant="outline" className="text-[10px] border-primary/30 text-primary animate-pulse">
                      LIVE
                    </Badge>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  {isActive && onCancel && (
                    <Button
                      size="sm"
                      variant="destructive"
                      className="h-7 rounded-xl text-xs"
                      disabled={isCancelling}
                      onClick={() => onCancel(workflow.name)}
                    >
                      {isCancelling ? <LoaderCircle className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Square className="mr-1.5 h-3.5 w-3.5" />}
                      {isCancelling ? "Cancelling…" : "Cancel"}
                    </Button>
                  )}
                  <Button
                    size="sm"
                    className="h-7 rounded-xl text-xs transition-transform duration-150 active:scale-95"
                    disabled={isRunning || isActive}
                    onClick={() => {
                      setTriggerInput(workflow.input ?? "");
                      setShowTriggerConfirm(true);
                    }}
                  >
                    <Play className="mr-1.5 h-3.5 w-3.5" />
                    Run
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {/* trigger confirmation with input editor */}
              {showTriggerConfirm && !isActive && (
                <div className="mb-3 rounded-xl border border-primary/30 bg-primary/5 p-3 space-y-2">
                  <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                    <Play className="h-4 w-4 text-primary" />
                    Confirm run
                  </div>
                  {isFactoryWorkflow && (
                    <div className="rounded-xl border border-border/60 bg-background/70 p-2.5 space-y-1.5">
                      <div className="space-y-1">
                        <Label className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">Factory mode</Label>
                        <Select value={factoryMode} onValueChange={(value) => onFactoryModeChange(value as FactoryMode)}>
                          <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Select a factory mode" /></SelectTrigger>
                          <SelectContent>
                            {FACTORY_MODE_OPTIONS.map((option) => (
                              <SelectItem key={option.value} value={option.value}>
                                <div className="flex flex-col gap-0.5 py-0.5 text-left">
                                  <span className="text-xs font-medium">{option.label}</span>
                                  <span className="text-[10px] text-muted-foreground">{option.description}</span>
                                </div>
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    </div>
                  )}
                  <ExpandableMarkdownEditor
                    value={triggerInput}
                    onChange={setTriggerInput}
                    label="Input (editable before run)"
                    rows={3}
                    textareaClassName="text-xs"
                    placeholder="Describe the task, context, or parameters for this workflow run…"
                    dialogTitle="Workflow Run Input"
                    dialogDescription="Edit the input payload for this workflow execution. Supports Markdown."
                  />
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      className="h-7 rounded-xl text-xs"
                      disabled={isRunning}
                      onClick={handleTrigger}
                    >
                      {isRunning ? (
                        <LoaderCircle className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Play className="mr-1.5 h-3.5 w-3.5" />
                      )}
                      {isRunning ? "Starting…" : "Confirm & run"}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-7 rounded-xl text-xs"
                      onClick={() => setShowTriggerConfirm(false)}
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              )}

              {/* running indicator */}
              {isActive && (
                <div className="mb-3 flex items-center gap-2 rounded-xl border border-primary/30 bg-primary/5 px-3 py-2 text-sm text-primary">
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                  <span>Workflow is {workflow.phase}…</span>
                </div>
              )}

              {/* pending approval banner (global) */}
              {isActive && workflow.pending_approval && !pendingApprovalStep && (
                <div className="mb-3 flex items-center gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-300">
                  <ShieldCheck className="h-4 w-4 shrink-0" />
                  <span>Waiting for approval at <strong>{workflow.current_step || "unknown step"}</strong></span>
                </div>
              )}

              <div className="mb-3 flex flex-col gap-2 xl:flex-row xl:items-center xl:justify-between">
                <div className="flex flex-wrap gap-1">
                  {stepFilterOptions.map((option) => (
                    <Button
                      key={option.value}
                      type="button"
                      size="sm"
                      variant={stepViewFilter === option.value ? "secondary" : "ghost"}
                      className="h-7 rounded-lg px-2 text-[11px]"
                      onClick={() => setStepViewFilter(option.value)}
                    >
                      {option.label}
                      <Badge variant="outline" className="ml-1.5 text-[10px]">{option.count}</Badge>
                    </Button>
                  ))}
                </div>
                <div className="text-[11px] text-muted-foreground">
                  {visibleSteps.length === steps.length
                    ? `Showing all ${steps.length} step${steps.length === 1 ? "" : "s"}`
                    : `Showing ${visibleSteps.length} of ${steps.length} step${steps.length === 1 ? "" : "s"}`}
                </div>
              </div>

              {/* step list */}
              {visibleSteps.length === 0 ? (
                <div className="rounded-xl border border-border/60 bg-background/60 px-3 py-3 text-xs text-muted-foreground">
                  No steps match the current filter.
                  {stepViewFilter !== "all" && (
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      className="ml-2 h-6 rounded-lg px-2 text-[11px]"
                      onClick={() => setStepViewFilter("all")}
                    >
                      Show all
                    </Button>
                  )}
                </div>
              ) : (
              <div className="space-y-0">
                {visibleSteps.map((step, idx) => {
                  const state = workflow.step_states?.[step.name];
                  const isStepApprovalWaiting = pendingApprovalStep === step.name;

                  return (
                    <div key={step.name}>
                      <StepDetailCard
                        step={step}
                        state={state}
                        isApprovalWaiting={isStepApprovalWaiting}
                        approvalReason={approvalReason}
                        approvalBusy={approvalBusy}
                        onApprovalReasonChange={onApprovalReasonChange}
                        onApprovalDecision={onApprovalDecision}
                      />
                      {/* connector line between steps */}
                      {idx < visibleSteps.length - 1 && (
                        <div className="ml-4 h-3 w-px bg-border/50" />
                      )}
                    </div>
                  );
                })}
              </div>
              )}

              {/* workflow result summary */}
              {(workflow.phase === "succeeded" || workflow.phase === "completed") && (() => {
                const started = wfSummary?.startedAt ? new Date(wfSummary.startedAt) : null;
                const ended = wfSummary?.updatedAt ? new Date(wfSummary.updatedAt) : null;
                const durationMs = started && ended && !Number.isNaN(started.getTime()) && !Number.isNaN(ended.getTime())
                  ? ended.getTime() - started.getTime()
                  : null;

                return (
                  <div className="mt-3 space-y-2">
                    <div className="flex items-center gap-2 rounded-xl border border-emerald-500/30 bg-emerald-500/5 px-3 py-2 text-sm text-emerald-400">
                      <CheckCircle2 className="h-4 w-4 shrink-0" />
                      <span className="font-medium">Completed successfully</span>
                      {durationMs != null && (
                        <Badge variant="outline" className="ml-auto border-emerald-500/20 text-emerald-400 text-xs">
                          {formatMs(durationMs)}
                        </Badge>
                      )}
                    </div>
                    <div className="grid gap-2 sm:grid-cols-3">
                      {started && !Number.isNaN(started.getTime()) && (
                        <div className="rounded-lg border border-border/40 bg-background/60 px-2.5 py-1.5">
                          <p className="text-[10px] uppercase tracking-wider text-muted-foreground/70">Started</p>
                          <p className="text-xs font-mono text-foreground">{started.toLocaleString()}</p>
                        </div>
                      )}
                      {ended && !Number.isNaN(ended.getTime()) && (
                        <div className="rounded-lg border border-border/40 bg-background/60 px-2.5 py-1.5">
                          <p className="text-[10px] uppercase tracking-wider text-muted-foreground/70">Completed</p>
                          <p className="text-xs font-mono text-foreground">{ended.toLocaleString()}</p>
                        </div>
                      )}
                      {durationMs != null && (
                        <div className="rounded-lg border border-border/40 bg-background/60 px-2.5 py-1.5">
                          <p className="text-[10px] uppercase tracking-wider text-muted-foreground/70">Duration</p>
                          <p className="text-xs font-mono text-foreground">{formatMs(durationMs)}</p>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })()}
              {workflow.phase === "failed" && (() => {
                const started = wfSummary?.startedAt ? new Date(wfSummary.startedAt) : null;
                const ended = wfSummary?.updatedAt ? new Date(wfSummary.updatedAt) : null;
                const durationMs = started && ended && !Number.isNaN(started.getTime()) && !Number.isNaN(ended.getTime())
                  ? ended.getTime() - started.getTime()
                  : null;
                const failedStepNames = Object.entries(workflow.step_states ?? {})
                  .filter(([, s]) => s?.status === "failed")
                  .map(([n]) => n);

                return (
                  <div className="mt-3 space-y-2">
                    <div className="flex items-center gap-2 rounded-xl border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
                      <AlertTriangle className="h-4 w-4 shrink-0" />
                      <span className="font-medium">Failed at <strong>{workflow.current_step || "unknown"}</strong></span>
                      {durationMs != null && (
                        <Badge variant="outline" className="ml-auto border-destructive/20 text-destructive text-xs">
                          after {formatMs(durationMs)}
                        </Badge>
                      )}
                    </div>
                    {onRetryFailed && failedStepNames.length > 0 && (
                      <div className="flex items-center gap-3 rounded-xl border border-amber-500/30 bg-amber-500/5 px-3 py-2">
                        <div className="flex-1 space-y-0.5">
                          <p className="text-sm font-medium text-foreground">Retry failed steps</p>
                          <p className="text-xs text-muted-foreground">
                            {failedStepNames.length === 1
                              ? `Re-run "${failedStepNames[0]}" — completed steps preserved.`
                              : `Re-run ${failedStepNames.length} failed steps (${failedStepNames.join(", ")}) — completed steps preserved.`}
                          </p>
                        </div>
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-7 rounded-xl text-xs border-amber-500/40 hover:bg-amber-500/10"
                          disabled={isRetrying}
                          onClick={() => onRetryFailed(workflow.name)}
                        >
                          {isRetrying ? <LoaderCircle className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Repeat className="mr-1.5 h-3.5 w-3.5" />}
                          {isRetrying ? "Retrying…" : "Retry failed"}
                        </Button>
                      </div>
                    )}
                    {(started || ended) && (
                      <div className="grid gap-2 sm:grid-cols-2">
                        {started && !Number.isNaN(started.getTime()) && (
                          <div className="rounded-lg border border-border/40 bg-background/60 px-2.5 py-1.5">
                            <p className="text-[10px] uppercase tracking-wider text-muted-foreground/70">Started</p>
                            <p className="text-xs font-mono text-foreground">{started.toLocaleString()}</p>
                          </div>
                        )}
                        {ended && !Number.isNaN(ended.getTime()) && (
                          <div className="rounded-lg border border-border/40 bg-background/60 px-2.5 py-1.5">
                            <p className="text-[10px] uppercase tracking-wider text-muted-foreground/70">Failed at</p>
                            <p className="text-xs font-mono text-foreground">{ended.toLocaleString()}</p>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })()}
              {workflow.phase === "cancelled" && (
                <div className="mt-3 flex items-center gap-2 rounded-xl border border-orange-500/30 bg-orange-500/5 px-3 py-2 text-sm text-orange-400">
                  <XCircle className="h-4 w-4 shrink-0" />
                  <span>Cancelled{workflow.current_step ? ` at step ${workflow.current_step}` : ""}.</span>
                </div>
              )}
            </CardContent>
          </Card>
        )}

            </TabsContent>
          )}

          {workflow && hasBeenTriggered && (
            <TabsContent value="history" className="mt-0 animate-fade-in">
              <div className="grid gap-3 2xl:grid-cols-[minmax(0,1.14fr)_minmax(24rem,0.86fr)]">
                <RunHistoryPanel workflowName={workflow.name} collapsible={false} onSelectRun={setSelectedHistoryRun} />

                <div className="space-y-3">
                  <WorkflowLogPanel workflow={workflow} selectedRun={selectedHistoryRun} />

                  {activeRunAgents.length > 0 && (
                    <Card className={WORKSPACE_PANEL_CLASS}>
                      <CardHeader className="pb-2">
                        <CardTitle className="flex items-center gap-2 text-sm">
                          <FolderOpen className="h-4 w-4" />
                          Agent workspace files
                        </CardTitle>
                        <CardDescription className="text-xs">Browse files created during this workflow run.</CardDescription>
                      </CardHeader>
                      <CardContent className="p-3">
                        <AgentFileBrowserTabs agents={activeRunAgents} token={token} namespace={namespace ?? "default"} liveUpdatesEnabled={isActive} />
                      </CardContent>
                    </Card>
                  )}
                </div>
              </div>
            </TabsContent>
          )}

          <TabsContent value="definition" className="mt-0 space-y-3 animate-fade-in">
            {workflow && (
              <Card className={WORKSPACE_PANEL_CLASS}>
                <CardContent className="flex flex-col gap-2 p-3 lg:flex-row lg:items-center lg:justify-between">
                  <div className="space-y-0.5">
                    <div className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">Definition studio</div>
                    <div className="text-sm font-semibold text-foreground">Refine the workflow contract, step graph, and execution policy.</div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {hasBeenTriggered && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 rounded-xl text-xs"
                        onClick={() => setWorkspaceTab("live")}
                      >
                        <Clock className="mr-1.5 h-3.5 w-3.5" />
                        Back to live run
                      </Button>
                    )}
                    {workflow && onOpenComposer && (
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-7 rounded-xl text-xs"
                        onClick={onOpenComposer}
                      >
                        <Blocks className="mr-1.5 h-3.5 w-3.5" />
                        Edit in Composer
                      </Button>
                    )}
                  </div>
                </CardContent>
              </Card>
            )}

        {/* ── Workflow details + execution profile (editor) ── */}
        <div className="grid gap-2 xl:grid-cols-[1.1fr_0.9fr]">
          <Card className={WORKSPACE_PANEL_CLASS}>
            <CardHeader className="px-3 py-2 pb-1">
              <CardTitle className="text-xs font-semibold">Workflow details</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 px-3 pb-3 pt-0">
              <div className="grid gap-2 sm:grid-cols-2">
                <div className="space-y-0.5">
                  <Label className="text-[11px]">Name</Label>
                  <Input
                    className="h-8 text-xs"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="research-report-pipeline"
                    disabled={Boolean(workflow)}
                  />
                </div>
                <div className="space-y-0.5">
                  <Label className="text-[11px]">Description</Label>
                  <Input
                    className="h-8 text-xs"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="Research to report pipeline"
                  />
                </div>
                <div className="space-y-0.5">
                  <Label className="text-[11px]">Context ConfigMap</Label>
                  <Input
                    className="h-8 text-xs"
                    value={contextRef}
                    onChange={(e) => setContextRef(e.target.value)}
                    placeholder="project-rules"
                  />
                </div>
              </div>
              <ExpandableMarkdownEditor
                value={input}
                onChange={setInput}
                label="Workflow input"
                rows={3}
                placeholder="Describe the task, desired output, and constraints the first step should receive."
                dialogTitle="Workflow Input"
                dialogDescription="This value is available in step prompts as {{input}}. Supports full Markdown."
              />
            </CardContent>
          </Card>

          <Card className={WORKSPACE_PANEL_CLASS}>
            <CardHeader className="px-3 py-2 pb-1">
              <div className="flex items-center gap-1.5">
                <Sparkles className="h-3.5 w-3.5 text-emerald-400" />
                <CardTitle className="text-xs font-semibold">Execution profile</CardTitle>
              </div>
            </CardHeader>
            <CardContent className="space-y-2 px-3 pb-3 pt-0">
              <div className="space-y-1">
                <Label className="text-xs">Message bus</Label>
                <Select value={messageBus} onValueChange={setMessageBus}>
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="in-memory">in-memory</SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-[11px] text-muted-foreground">The current gateway API supports the in-memory workflow bus only.</p>
              </div>
              <Separator />
              <div className={`${SIGNAL_PANEL_CLASS} border-border/60 bg-background/70 p-2.5 text-xs text-muted-foreground`}>
                <p className="font-medium text-foreground">Operator-friendly defaults</p>
                <p className="mt-0.5 leading-5">Each step is independently targetable, dependencies stay explicit, and approval gates are visible directly on the step card.</p>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* ── Step editor ── */}
        <div className="flex items-center justify-between border-t border-border pt-3">
          <div>
            <h3 className="text-sm font-medium text-foreground">Workflow steps</h3>
            <p className="text-xs text-muted-foreground">Model the sequence, assign agents, and toggle dependencies.</p>
          </div>
          <Button
            variant="outline"
            size="sm"
            className="h-7 rounded-xl text-xs"
            onClick={() =>
              setSteps((current) => [
                ...current,
                {
                  name: `step-${current.length + 1}`,
                  agent_ref: agents[0]?.name ?? "",
                  prompt: "",
                  depends_on: [],
                  require_approval: false,
                },
              ])
            }
          >
            <PlusCircle className="mr-1 h-3 w-3" />
            Add step
          </Button>
        </div>

        <div className="space-y-2">
          {steps.map((step, index) => (
            <Card key={index} className={WORKSPACE_PANEL_CLASS}>
              <CardContent className="space-y-3 p-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <Badge variant="secondary">Step {index + 1}</Badge>
                    {step.require_approval ? (
                      <Badge variant="outline" className="border-amber-500/30 bg-amber-500/10 text-amber-300">
                        <ShieldCheck className="mr-1 h-3 w-3" /> Approval gate
                      </Badge>
                    ) : null}
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 rounded-xl text-xs text-destructive hover:text-destructive"
                    disabled={steps.length === 1}
                    onClick={() => removeStep(index)}
                  >
                    <Trash2 className="mr-1 h-3 w-3" />
                    Remove
                  </Button>
                </div>

                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="space-y-1">
                    <Label className="text-[11px]">Step name</Label>
                    <Input
                      className="h-9 rounded-xl text-xs"
                      value={step.name}
                      onChange={(e) => renameStep(index, e.target.value)}
                    />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-[11px]">Step type</Label>
                    <Select
                      value={step.step_type ?? "agent"}
                      onValueChange={(v) =>
                        updateStep(index, (current) => ({
                          ...current,
                          step_type: v as "agent" | "loop" | "review",
                          loop_config: v === "loop" && !current.loop_config
                            ? { maxIterations: 20, planSource: "inline", plan: "", commitAfterEachItem: true, circuitBreaker: { noProgressThreshold: 3, cooldownMinutes: 2 } }
                            : v === "loop"
                              ? current.loop_config
                              : null,
                        }))
                      }
                    >
                      <SelectTrigger className="h-9 rounded-xl text-xs">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="agent">Agent (single run)</SelectItem>
                        <SelectItem value="loop">Dev-loop (iterative)</SelectItem>
                        <SelectItem value="review">Review</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>

                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="space-y-1">
                    <Label className="text-[11px]">Agent</Label>
                    <Select
                      value={step.agent_ref || "__none__"}
                      onValueChange={(v) =>
                        updateStep(index, (current) => ({ ...current, agent_ref: v === "__none__" ? "" : v }))
                      }
                    >
                      <SelectTrigger className="h-9 rounded-xl text-xs">
                        <SelectValue placeholder="Select agent" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="__none__">Select agent</SelectItem>
                        {agents.map((agent) => (
                          <SelectItem key={agent.name} value={agent.name}>
                            {agent.name} · {agent.model}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>

                <div className="space-y-2">
                  <Label className="text-[11px]">Depends on</Label>
                  <div className="flex flex-wrap gap-2 rounded-2xl border border-border/60 bg-background/50 p-3">
                    {steps
                      .filter((candidate, candidateIndex) => candidateIndex !== index && candidate.name.trim())
                      .map((candidate) => {
                        const active = step.depends_on.includes(candidate.name);
                        return (
                          <button
                            key={candidate.name}
                            type="button"
                            onClick={() => toggleDependency(index, candidate.name)}
                            className={`rounded-full border px-3 py-1 text-xs transition ${
                              active
                                ? "border-primary/40 bg-primary/10 text-foreground"
                                : "border-border/70 bg-background text-muted-foreground hover:border-primary/25 hover:text-foreground"
                            }`}
                          >
                            {candidate.name}
                          </button>
                        );
                      })}
                    {steps.filter((candidate, candidateIndex) => candidateIndex !== index && candidate.name.trim()).length === 0 ? (
                      <p className="text-xs text-muted-foreground">Add another step to create explicit dependencies.</p>
                    ) : null}
                  </div>
                </div>

                <ExpandableMarkdownEditor
                  value={step.prompt}
                  onChange={(v) =>
                    updateStep(index, (current) => ({ ...current, prompt: v }))
                  }
                  label="Prompt"
                  rows={4}
                  textareaClassName="text-xs"
                  placeholder="Explain what this step should do, what context it receives, and what output it should pass to the next step."
                  dialogTitle={`Step Prompt — ${step.name || `Step ${index + 1}`}`}
                  dialogDescription="Write the instruction for this workflow step. Supports Markdown formatting."
                />

                {step.step_type !== "review" && (
                  <div className="space-y-1">
                    <Label className="text-[11px]">Verification criteria</Label>
                    <Textarea
                      rows={3}
                      className="text-xs"
                      value={step.verify ?? ""}
                      onChange={(e) =>
                        updateStep(index, (current) => ({ ...current, verify: e.target.value || null }))
                      }
                      placeholder="Optional verification prompt to run after the step completes."
                    />
                  </div>
                )}

                {step.step_type === "review" && (
                  <div className="space-y-1">
                    <Label className="text-[11px]">Review criteria</Label>
                    <Textarea
                      rows={3}
                      className="text-xs"
                      value={step.review_criteria ?? ""}
                      onChange={(e) =>
                        updateStep(index, (current) => ({ ...current, review_criteria: e.target.value || null }))
                      }
                      placeholder="What should this review step evaluate in the previous output?"
                    />
                  </div>
                )}

                {step.step_type === "loop" && (
                  <div className="space-y-2 rounded-2xl border border-violet-500/30 bg-violet-500/5 p-3">
                    <div className="flex items-center gap-2 text-sm font-medium text-violet-300">
                      <Repeat className="h-4 w-4" />
                      Loop configuration
                    </div>
                    <div className="grid gap-2 sm:grid-cols-3">
                      <div className="space-y-1">
                        <Label className="text-[11px]">Max iterations</Label>
                        <Input
                          type="number"
                          min={1}
                          max={200}
                          className="h-9 rounded-xl text-xs"
                          value={step.loop_config?.maxIterations ?? 20}
                          onChange={(e) =>
                            updateStep(index, (current) => ({
                              ...current,
                              loop_config: { ...current.loop_config, maxIterations: parseInt(e.target.value) || 20 },
                            }))
                          }
                        />
                      </div>
                      <div className="space-y-1">
                        <Label className="text-[11px]">Plan source</Label>
                        <Select
                          value={step.loop_config?.planSource ?? "inline"}
                          onValueChange={(v) =>
                            updateStep(index, (current) => ({
                              ...current,
                              loop_config: { ...current.loop_config, planSource: v as "inline" | "prompt" },
                            }))
                          }
                        >
                          <SelectTrigger className="h-9 rounded-xl text-xs">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="inline">Inline checklist</SelectItem>
                            <SelectItem value="prompt">Agent generates plan</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-1">
                        <Label className="text-[11px]">No-progress threshold</Label>
                        <Input
                          type="number"
                          min={1}
                          max={10}
                          className="h-9 rounded-xl text-xs"
                          value={step.loop_config?.circuitBreaker?.noProgressThreshold ?? 3}
                          onChange={(e) =>
                            updateStep(index, (current) => ({
                              ...current,
                              loop_config: {
                                ...current.loop_config,
                                circuitBreaker: {
                                  ...current.loop_config?.circuitBreaker,
                                  noProgressThreshold: parseInt(e.target.value) || 3,
                                },
                              },
                            }))
                          }
                        />
                      </div>
                    </div>
                    {(step.loop_config?.planSource ?? "inline") === "inline" && (
                      <div className="space-y-1">
                        <Label className="text-[11px]">Plan checklist</Label>
                        <Textarea
                          rows={6}
                          className="font-mono text-xs"
                          value={step.loop_config?.plan ?? ""}
                          onChange={(e) =>
                            updateStep(index, (current) => ({
                              ...current,
                              loop_config: { ...current.loop_config, plan: e.target.value },
                            }))
                          }
                          placeholder={"- [ ] Implement user authentication\n- [ ] Add unit tests for auth module\n- [ ] Update API documentation"}
                        />
                      </div>
                    )}
                    <div className="flex items-center gap-3">
                      <input
                        type="checkbox"
                        id={`commit-after-${index}`}
                        checked={step.loop_config?.commitAfterEachItem ?? true}
                        onChange={(e) =>
                          updateStep(index, (current) => ({
                            ...current,
                            loop_config: { ...current.loop_config, commitAfterEachItem: e.target.checked },
                          }))
                        }
                        className="h-4 w-4 rounded border-border"
                      />
                      <Label htmlFor={`commit-after-${index}`} className="text-xs">Commit after each item</Label>
                    </div>
                  </div>
                )}

                <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border/60 bg-background/50 p-2.5">
                  <div>
                    <p className="text-sm font-medium text-foreground">Human approval</p>
                    <p className="text-xs text-muted-foreground">Pause before this step and wait for approval.</p>
                  </div>
                  <Button
                    type="button"
                    variant={step.require_approval ? "default" : "outline"}
                    size="sm"
                    className="h-7 rounded-xl text-xs"
                    onClick={() =>
                      updateStep(index, (current) => ({
                        ...current,
                        require_approval: !current.require_approval,
                      }))
                    }
                  >
                    {step.require_approval ? "Enabled" : "Enable"}
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

          </TabsContent>
        </Tabs>

        {error && (
          <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">
            {error}
          </div>
        )}

        <div className="flex items-center justify-end gap-2 border-t border-border pt-3">
          {workflow && (
            <div className="mr-auto flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                className="h-8 text-xs"
                onClick={() => {
                  setTriggerInput(workflow.input ?? "");
                  setShowTriggerConfirm(true);
                }}
                disabled={isRunning}
              >
                {isRunning ? <LoaderCircle className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Play className="mr-1.5 h-3.5 w-3.5" />}
                {isRunning ? "Running…" : "Run"}
              </Button>
              {isActive && onCancel && (
                <Button
                  variant="destructive"
                  size="sm"
                  className="h-8 text-xs"
                  disabled={isCancelling}
                  onClick={() => onCancel(workflow.name)}
                >
                  {isCancelling ? <LoaderCircle className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Square className="mr-1.5 h-3.5 w-3.5" />}
                  {isCancelling ? "Cancelling…" : "Cancel"}
                </Button>
              )}
            </div>
          )}
          {canMutate && (
            <Button
              size="sm"
              className="h-8 text-xs"
              onClick={() => {
                const payload = {
                  description,
                  input,
                  context_ref: contextRef.trim() || undefined,
                  message_bus: messageBus,
                  steps,
                };
                if (workflow) {
                  onUpdate(workflow.name, payload as WorkflowUpdatePayload);
                  return;
                }
                onCreate({ name, ...payload });
              }}
              disabled={!canSubmit || isSaving}
            >
              {isSaving ? <LoaderCircle className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Save className="mr-1.5 h-3.5 w-3.5" />}
              {isSaving ? "Saving..." : workflow ? "Save" : "Create"}
            </Button>
          )}
          {workflow && onOpenComposer && (
            <Button
              variant="outline"
              size="sm"
              className="h-8 text-xs"
              onClick={onOpenComposer}
            >
              <Blocks className="mr-1.5 h-3.5 w-3.5" />
              Composer
            </Button>
          )}
          {workflow && canMutate && (
            <Button
              variant="destructive"
              size="sm"
              className="h-8 text-xs"
              onClick={() => setDeleteDialogOpen(true)}
              disabled={isDeleting}
            >
              {isDeleting ? <LoaderCircle className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Trash2 className="mr-1.5 h-3.5 w-3.5" />}
              {isDeleting ? "Deleting..." : "Delete"}
            </Button>
          )}
          {!canMutate && (
            <p className="text-xs text-muted-foreground italic">Read-only — operator role required</p>
          )}
        </div>

        {workflow && (
          <ConfirmDialog
            open={deleteDialogOpen}
            onOpenChange={setDeleteDialogOpen}
            title="Delete workflow"
            description={`This will permanently delete the workflow "${workflow.name}". This action cannot be undone.`}
            confirmLabel="Delete"
            onConfirm={() => onDelete(workflow.name)}
          />
        )}
      </CardContent>
    </Card>
  );
}
