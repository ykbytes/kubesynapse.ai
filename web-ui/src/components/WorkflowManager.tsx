import {
  AlertTriangle,
  Blocks,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Circle,
  Clock,
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
import { useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { ConfirmDialog } from "./ConfirmDialog";
import { CopyButton } from "./CopyButton";
import { JsonBlock } from "./JsonBlock";
import type {
  AgentInfo,
  LoopProgress,
  WorkflowInfo,
  WorkflowPayload,
  WorkflowStep,
  WorkflowStepState,
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
  onTrigger: (name: string, input?: string) => void;
  onCancel?: (name: string) => void;
  isCancelling?: boolean;
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
        ring: "border-primary/30 bg-primary/10",
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
    case "running":
    case "queued":
      return "secondary";
    default:
      return "outline";
  }
}

/* ────────── progress bar component ────────── */

function ProgressSummaryBar({ summary, phase }: { summary: WorkflowSummary; phase: string }) {
  const total = summary.totalSteps ?? 0;
  const completed = summary.completedSteps ?? 0;
  const failed = summary.failedSteps ?? 0;
  const skipped = summary.skippedSteps ?? 0;
  const waiting = summary.waitingApprovalSteps ?? 0;
  const done = completed + failed + skipped;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;

  const isActive = phase === "running" || phase === "queued";

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
              style={{ width: `${(completed / total) * 100}%` }}
            />
            <div
              className="absolute inset-y-0 rounded-full bg-destructive transition-all duration-500"
              style={{ left: `${(completed / total) * 100}%`, width: `${(failed / total) * 100}%` }}
            />
            <div
              className="absolute inset-y-0 rounded-full bg-muted-foreground/40 transition-all duration-500"
              style={{ left: `${((completed + failed) / total) * 100}%`, width: `${(skipped / total) * 100}%` }}
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

  return (
    <div className="flex gap-3">
      {/* connector + icon */}
      <div className="flex flex-col items-center">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full border transition-all duration-200 ${ring} hover:brightness-110 hover:scale-105 active:scale-95`}
          title={expanded ? "Collapse" : "Expand"}
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
          <span className="text-xs text-muted-foreground">
            {step.agent_ref}{step.require_approval ? " · approval gate" : ""}
          </span>
          {state?.loopProgress && (
            <span className="text-[10px] tabular-nums text-violet-300">
              {state.loopProgress.completedItems}/{state.loopProgress.totalItems} items
            </span>
          )}
          {state?.latencyMs != null && (
            <span className="ml-auto text-[10px] tabular-nums text-muted-foreground">{formatMs(state.latencyMs)}</span>
          )}
        </button>

        {/* expanded detail */}
        {expanded && (
          <div className="mt-2 space-y-2 rounded-xl border border-border/50 bg-background/50 p-3 text-xs">
            {/* timing & attempts */}
            <div className="flex flex-wrap gap-4 text-muted-foreground">
              {state?.startedAt && (
                <span>Started: {new Date(state.startedAt).toLocaleTimeString()}</span>
              )}
              {state?.completedAt && (
                <span>Completed: {new Date(state.completedAt).toLocaleTimeString()}</span>
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

            {/* loop progress */}
            {state?.loopProgress && (
              <LoopProgressDisplay progress={state.loopProgress} />
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

            {/* execution output */}
            {state?.execution && Object.keys(state.execution).length > 0 && (
              <details>
                <summary className="cursor-pointer text-xs font-medium text-muted-foreground hover:text-foreground">
                  Execution output
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
  approvalReason,
  approvalBusy,
  onApprovalReasonChange,
  onApprovalDecision,
  onOpenComposer,
}: WorkflowManagerProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [input, setInput] = useState("");
  const [messageBus, setMessageBus] = useState("in-memory");
  const [steps, setSteps] = useState<WorkflowStep[]>(() => defaultStepsForAgent(agents[0]?.name));

  // Trigger confirmation input (separate from workflow spec input)
  const [triggerInput, setTriggerInput] = useState("");
  const [showTriggerConfirm, setShowTriggerConfirm] = useState(false);

  useEffect(() => {
    if (workflow) {
      setName(workflow.name);
      setDescription(workflow.description);
      setInput(workflow.input);
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
    setMessageBus("in-memory");
    setSteps(defaultStepsForAgent(agents[0]?.name));
    setTriggerInput("");
    setShowTriggerConfirm(false);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflow?.name, workflow?.phase, workflow?.current_step]);

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

  // Derive pending approval step name for inline controls
  const pendingApprovalStep = useMemo(() => {
    if (!workflow?.pending_approval) return null;
    const pa = workflow.pending_approval;
    return typeof pa.stepName === "string" ? pa.stepName : (workflow.current_step || null);
  }, [workflow?.pending_approval, workflow?.current_step]);

  const wfSummary: WorkflowSummary | undefined = workflow?.summary ?? undefined;
  const isActive = workflow?.phase === "running" || workflow?.phase === "queued" || workflow?.phase === "waiting-approval";
  const hasBeenTriggered = Boolean(workflow && (workflow.phase !== "pending" || workflow.run_id || workflow.summary));
  const [showEditor, setShowEditor] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  function handleTrigger() {
    if (!workflow) return;
    onTrigger(workflow.name, triggerInput.trim() || undefined);
    setShowTriggerConfirm(false);
  }

  return (
    <Card className="border-border/70 bg-card/95 shadow-[0_24px_80px_-48px_rgba(0,0,0,0.65)]">
      <CardHeader className="pb-4">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-primary/20 bg-primary/10 text-primary shadow-inner shadow-primary/10">
            <Workflow className="h-5 w-5" />
          </div>
          <div className="flex-1 space-y-1">
            <CardTitle className="text-lg">{workflow ? workflow.name : "Create workflow"}</CardTitle>
            <CardDescription>
              {workflow
                ? "Refine the orchestration, approvals, and step wiring for this workflow."
                : "Compose a multi-step agent pipeline with clearer sequencing, dependencies, and review gates."}
            </CardDescription>
          </div>
          <Badge variant={isActive ? "default" : (workflow?.phase === "failed" || workflow?.phase === "cancelled") ? "destructive" : "secondary"}>
            {workflow?.phase ?? "draft"}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        {/* ── Summary counters ── */}
        <div className="grid gap-3 md:grid-cols-4">
          <div className="rounded-2xl border border-border/60 bg-background/60 p-3">
            <p className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground/70">Status</p>
            <p className="mt-1 text-xl font-semibold text-foreground">{workflow?.phase ?? "draft"}</p>
          </div>
          <div className="rounded-2xl border border-border/60 bg-background/60 p-3">
            <p className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground/70">Steps</p>
            <p className="mt-1 text-xl font-semibold text-foreground">
              {wfSummary ? `${(wfSummary.completedSteps ?? 0) + (wfSummary.failedSteps ?? 0)}/${wfSummary.totalSteps ?? steps.length}` : steps.length}
            </p>
          </div>
          <div className="rounded-2xl border border-border/60 bg-background/60 p-3">
            <p className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground/70">Agents</p>
            <p className="mt-1 text-xl font-semibold text-foreground">{uniqueAgentCount}</p>
          </div>
          <div className="rounded-2xl border border-border/60 bg-background/60 p-3">
            <p className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground/70">
              {isActive ? "Elapsed" : "Approvals"}
            </p>
            <p className="mt-1 text-xl font-semibold text-foreground">
              {isActive && wfSummary?.startedAt ? formatElapsed(wfSummary.startedAt) : approvalStepCount}
            </p>
          </div>
        </div>

        {/* ── Live progress bar (when summary exists) ── */}
        {workflow && wfSummary && (wfSummary.totalSteps ?? 0) > 0 && (
          <Card className="shadow-none">
            <CardContent className="p-4">
              <ProgressSummaryBar summary={wfSummary} phase={workflow.phase} />
            </CardContent>
          </Card>
        )}

        {/* ── Step pipeline (live view + expandable detail) ── */}
        {workflow && steps.length > 0 && (
          <Card className="shadow-none">
            <CardHeader className="pb-3">
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
                      className="h-8 rounded-xl text-xs"
                      disabled={isCancelling}
                      onClick={() => onCancel(workflow.name)}
                    >
                      {isCancelling ? <LoaderCircle className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Square className="mr-1.5 h-3.5 w-3.5" />}
                      {isCancelling ? "Cancelling…" : "Cancel"}
                    </Button>
                  )}
                  <Button
                    size="sm"
                    className="h-8 rounded-xl text-xs transition-transform duration-150 active:scale-95"
                    disabled={isRunning || isActive}
                    onClick={() => {
                      setTriggerInput(workflow.input ?? "");
                      setShowTriggerConfirm(true);
                    }}
                  >
                    <Play className="mr-1.5 h-3.5 w-3.5" />
                    Run workflow
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {/* trigger confirmation with input editor */}
              {showTriggerConfirm && !isActive && (
                <div className="mb-4 rounded-xl border border-primary/30 bg-primary/5 p-4 space-y-3">
                  <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                    <Play className="h-4 w-4 text-primary" />
                    Confirm workflow execution
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">Input (editable before run)</Label>
                    <Textarea
                      rows={4}
                      className="text-xs"
                      value={triggerInput}
                      onChange={(e) => setTriggerInput(e.target.value)}
                      placeholder="Describe the task, context, or parameters for this workflow run…"
                    />
                  </div>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      className="h-8 rounded-xl text-xs"
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
                      className="h-8 rounded-xl text-xs"
                      onClick={() => setShowTriggerConfirm(false)}
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              )}

              {/* running indicator */}
              {isActive && (
                <div className="mb-4 flex items-center gap-2 rounded-xl border border-primary/30 bg-primary/5 px-3 py-2 text-sm text-primary">
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                  <span>Workflow is {workflow.phase}… polling for updates every 3 seconds.</span>
                </div>
              )}

              {/* pending approval banner (global) */}
              {isActive && workflow.pending_approval && !pendingApprovalStep && (
                <div className="mb-4 flex items-center gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-300">
                  <ShieldCheck className="h-4 w-4 shrink-0" />
                  <span>Waiting for approval at <strong>{workflow.current_step || "unknown step"}</strong></span>
                </div>
              )}

              {/* step list */}
              <div className="space-y-0">
                {steps.map((step, idx) => {
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
                      {idx < steps.length - 1 && (
                        <div className="ml-4 h-3 w-px bg-border/50" />
                      )}
                    </div>
                  );
                })}
              </div>

              {/* workflow result summary */}
              {(workflow.phase === "succeeded" || workflow.phase === "completed") && (
                <div className="mt-4 flex items-center gap-2 rounded-xl border border-emerald-500/30 bg-emerald-500/5 px-3 py-2 text-sm text-emerald-400">
                  <CheckCircle2 className="h-4 w-4 shrink-0" />
                  <span>Workflow completed successfully.</span>
                  {wfSummary?.startedAt && wfSummary?.updatedAt && !Number.isNaN(new Date(wfSummary.startedAt).getTime()) && !Number.isNaN(new Date(wfSummary.updatedAt).getTime()) && (
                    <span className="ml-auto text-xs text-muted-foreground">
                      Total: {formatMs(new Date(wfSummary.updatedAt).getTime() - new Date(wfSummary.startedAt).getTime())}
                    </span>
                  )}
                </div>
              )}
              {workflow.phase === "failed" && (
                <div className="mt-4 flex items-center gap-2 rounded-xl border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
                  <AlertTriangle className="h-4 w-4 shrink-0" />
                  <span>Workflow failed at step <strong>{workflow.current_step || "unknown"}</strong>.</span>
                </div>
              )}
              {workflow.phase === "cancelled" && (
                <div className="mt-4 flex items-center gap-2 rounded-xl border border-orange-500/30 bg-orange-500/5 px-3 py-2 text-sm text-orange-400">
                  <XCircle className="h-4 w-4 shrink-0" />
                  <span>Workflow was cancelled{workflow.current_step ? ` at step ${workflow.current_step}` : ""}.</span>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* ── Editor toggle for triggered workflows ── */}
        {hasBeenTriggered && (
          <Button
            variant="ghost"
            size="sm"
            className="h-8 self-start rounded-xl text-xs text-muted-foreground"
            onClick={() => setShowEditor((v) => !v)}
          >
            {showEditor ? <ChevronDown className="mr-1.5 h-3.5 w-3.5" /> : <Pencil className="mr-1.5 h-3.5 w-3.5" />}
            {showEditor ? "Hide step editor" : "Edit workflow steps"}
          </Button>
        )}

        {/* ── Workflow details + execution profile (editor) ── */}
        {(!hasBeenTriggered || showEditor) && <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
          <Card className="shadow-none">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">Workflow details</CardTitle>
              <CardDescription>Name the flow, describe its purpose, and define the initial instruction payload.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label className="text-xs">Name</Label>
                  <Input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="research-report-pipeline"
                    disabled={Boolean(workflow)}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs">Description</Label>
                  <Input
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="Research to report pipeline"
                  />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">Workflow input</Label>
                <Textarea
                  rows={4}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder="Describe the task, desired output, and constraints the first step should receive."
                />
              </div>
            </CardContent>
          </Card>

          <Card className="shadow-none">
            <CardHeader className="pb-3">
              <div className="flex items-center gap-2">
                <div className="flex h-8 w-8 items-center justify-center rounded-xl border border-emerald-500/20 bg-emerald-500/10 text-emerald-300">
                  <Sparkles className="h-4 w-4" />
                </div>
                <div>
                  <CardTitle className="text-sm">Execution profile</CardTitle>
                  <CardDescription>Keep orchestration simple, then add review gates only where the flow truly needs human control.</CardDescription>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1.5">
                <Label className="text-xs">Message bus</Label>
                <Select value={messageBus} onValueChange={setMessageBus}>
                  <SelectTrigger className="h-9 text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="in-memory">in-memory</SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-[11px] text-muted-foreground">The current gateway API supports the in-memory workflow bus only.</p>
              </div>
              <Separator />
              <div className="rounded-2xl border border-border/60 bg-background/60 p-3 text-sm text-muted-foreground">
                <p className="font-medium text-foreground">Operator-friendly defaults</p>
                <p className="mt-1 leading-6">Each step is independently targetable, dependencies stay explicit, and approval gates are visible directly on the step card instead of hidden in free-form text.</p>
              </div>
            </CardContent>
          </Card>
        </div>}

        {/* ── Step editor ── */}
        {(!hasBeenTriggered || showEditor) && <div className="flex items-center justify-between border-t border-border pt-4">
          <div>
            <h3 className="text-sm font-medium text-foreground">Workflow steps</h3>
            <p className="text-xs text-muted-foreground">Model the sequence, assign each step to an agent, and toggle dependencies with buttons instead of comma parsing.</p>
          </div>
          <Button
            variant="outline"
            size="sm"
            className="h-8 rounded-xl text-xs"
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
        </div>}

        {(!hasBeenTriggered || showEditor) && <div className="space-y-3">
          {steps.map((step, index) => (
            <Card key={index} className="shadow-none">
              <CardContent className="space-y-4 p-4">
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
                          step_type: v as "agent" | "loop",
                          loop_config: v === "loop" && !current.loop_config
                            ? { maxIterations: 20, planSource: "inline", plan: "", commitAfterEachItem: true, circuitBreaker: { noProgressThreshold: 3, cooldownMinutes: 2 } }
                            : current.loop_config,
                        }))
                      }
                    >
                      <SelectTrigger className="h-9 rounded-xl text-xs">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="agent">Agent (single run)</SelectItem>
                        <SelectItem value="loop">Dev-loop (iterative)</SelectItem>
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

                <div className="space-y-1">
                  <Label className="text-[11px]">Prompt</Label>
                  <Textarea
                    rows={4}
                    className="text-xs"
                    value={step.prompt}
                    onChange={(e) =>
                      updateStep(index, (current) => ({ ...current, prompt: e.target.value }))
                    }
                    placeholder="Explain what this step should do, what context it receives, and what output it should pass to the next step."
                  />
                </div>

                {step.step_type === "loop" && (
                  <div className="space-y-3 rounded-2xl border border-violet-500/30 bg-violet-500/5 p-4">
                    <div className="flex items-center gap-2 text-sm font-medium text-violet-300">
                      <Repeat className="h-4 w-4" />
                      Loop configuration
                    </div>
                    <div className="grid gap-3 sm:grid-cols-3">
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

                <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border/60 bg-background/50 p-3">
                  <div>
                    <p className="text-sm font-medium text-foreground">Human approval</p>
                    <p className="text-xs text-muted-foreground">Pause the workflow before this step starts and wait for an approval decision.</p>
                  </div>
                  <Button
                    type="button"
                    variant={step.require_approval ? "default" : "outline"}
                    size="sm"
                    className="rounded-xl"
                    onClick={() =>
                      updateStep(index, (current) => ({
                        ...current,
                        require_approval: !current.require_approval,
                      }))
                    }
                  >
                    {step.require_approval ? "Approval enabled" : "Enable approval"}
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>}

        {error && (
          <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </div>
        )}

        <div className="flex items-center justify-end gap-2 border-t border-border pt-4">
          {workflow && (
            <div className="mr-auto flex items-center gap-2">
              <Button
                variant="outline"
                onClick={() => {
                  setTriggerInput(workflow.input ?? "");
                  setShowTriggerConfirm(true);
                }}
                disabled={isRunning}
              >
                {isRunning ? <LoaderCircle className="mr-1.5 h-4 w-4 animate-spin" /> : <Play className="mr-1.5 h-4 w-4" />}
                {isRunning ? "Running…" : "Run"}
              </Button>
              {isActive && onCancel && (
                <Button
                  variant="destructive"
                  disabled={isCancelling}
                  onClick={() => onCancel(workflow.name)}
                >
                  {isCancelling ? <LoaderCircle className="mr-1.5 h-4 w-4 animate-spin" /> : <Square className="mr-1.5 h-4 w-4" />}
                  {isCancelling ? "Cancelling…" : "Cancel"}
                </Button>
              )}
            </div>
          )}
          <Button
            onClick={() => {
              const payload = { description, input, message_bus: messageBus, steps };
              if (workflow) {
                onUpdate(workflow.name, payload as WorkflowUpdatePayload);
                return;
              }
              onCreate({ name, ...payload });
            }}
            disabled={!canSubmit || isSaving}
          >
            {isSaving ? <LoaderCircle className="mr-1.5 h-4 w-4 animate-spin" /> : <Save className="mr-1.5 h-4 w-4" />}
            {isSaving ? "Saving..." : workflow ? "Save workflow" : "Create workflow"}
          </Button>
          {workflow && onOpenComposer && (
            <Button
              variant="outline"
              onClick={onOpenComposer}
            >
              <Blocks className="mr-1.5 h-4 w-4" />
              Edit in Composer
            </Button>
          )}
          {workflow && (
            <Button
              variant="destructive"
              onClick={() => setDeleteDialogOpen(true)}
              disabled={isDeleting}
            >
              {isDeleting ? <LoaderCircle className="mr-1.5 h-4 w-4 animate-spin" /> : <Trash2 className="mr-1.5 h-4 w-4" />}
              {isDeleting ? "Deleting..." : "Delete"}
            </Button>
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
