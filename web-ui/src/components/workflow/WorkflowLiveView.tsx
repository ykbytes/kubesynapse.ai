import { useMemo } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  Clock,
  LoaderCircle,
  Play,
  Repeat,
  ShieldCheck,
  SkipForward,
  Sparkles,
  Square,
  Timer,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ExpandableMarkdownEditor } from "../ExpandableMarkdownEditor";
import { WorkflowStepDetail } from "./WorkflowStepDetail";
import {
  formatMs,
  formatElapsed,
  stepStatusIcon,
  stepMatchesViewFilter,
  type WorkflowSignalStep,
} from "./workflow-helpers";
import { FACTORY_MODE_OPTIONS } from "@/lib/factoryModes";
import type {
  FactoryMode,
  WorkflowInfo,
  WorkflowNextAction,
  WorkflowStep,
  WorkflowSummary,
} from "../../types";

type StepViewFilter = "all" | "active" | "attention" | "activity" | "complete";

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
  const failedStyle = useMemo(
    () => ({ left: `${(completed / total) * 100}%`, width: `${(failed / total) * 100}%` }),
    [completed, failed, total]
  );
  const skippedStyle = useMemo(
    () => ({ left: `${((completed + failed) / total) * 100}%`, width: `${(skipped / total) * 100}%` }),
    [completed, failed, skipped, total]
  );

  return (
    <div className="space-y-3">
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
        <span className="ml-auto text-muted-foreground">
          {done}/{total} steps · {pct}%
        </span>
      </div>

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

      <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
        {isActive && summary.currentFrontier && summary.currentFrontier.length > 0 && (
          <span>
            Frontier:{" "}
            {summary.currentFrontier.map((s) => (
              <Badge key={s} variant="outline" className="ml-1 text-xs">
                {s}
              </Badge>
            ))}
          </span>
        )}
        {summary.startedAt && (
          <span className="flex items-center gap-1">
            <Timer className="h-3 w-3" />
            {isActive
              ? `Elapsed: ${formatElapsed(summary.startedAt)}`
              : `Started: ${new Date(summary.startedAt).toLocaleTimeString()}`}
          </span>
        )}
        {summary.runId && (
          <span className="ml-auto font-mono text-xs opacity-60">run: {summary.runId}</span>
        )}
      </div>
    </div>
  );
}

/* ────────── live view ────────── */

interface WorkflowLiveViewProps {
  workflow: WorkflowInfo;
  steps: WorkflowStep[];
  wfSummary?: WorkflowSummary;
  isActive: boolean;
  pendingApprovalStep: string | null;
  workflowSignals: {
    attentionSteps: WorkflowSignalStep[];
    activitySteps: WorkflowSignalStep[];
    activeSteps: number;
    completedSteps: number;
    totalToolCalls: number;
    totalArtifacts: number;
    totalWarnings: number;
    verificationFailures: number;
    reviewRejections: number;
    jsonContractFailures: number;
  };
  stepViewFilter: StepViewFilter;
  setStepViewFilter: (v: StepViewFilter) => void;
  approvalReason: string;
  approvalBusy: boolean;
  onApprovalReasonChange: (v: string) => void;
  onApprovalDecision: (d: "approved" | "denied") => void;
  nextAction: WorkflowNextAction | null;
  showTriggerConfirm: boolean;
  setShowTriggerConfirm: (v: boolean) => void;
  triggerInput: string;
  setTriggerInput: (v: string) => void;
  isRunning: boolean;
  isCancelling?: boolean;
  isRetrying?: boolean;
  isFactoryWorkflow: boolean;
  factoryMode: FactoryMode;
  onFactoryModeChange: (v: FactoryMode) => void;
  onCancel: () => void;
  onTrigger: () => void;
  onRetryFailed?: (name: string) => void;
}

export function WorkflowLiveView({
  workflow,
  steps,
  wfSummary,
  isActive,
  pendingApprovalStep,
  workflowSignals,
  stepViewFilter,
  setStepViewFilter,
  approvalReason,
  approvalBusy,
  onApprovalReasonChange,
  onApprovalDecision,
  nextAction,
  showTriggerConfirm,
  setShowTriggerConfirm,
  triggerInput,
  setTriggerInput,
  isRunning,
  isCancelling,
  isRetrying,
  isFactoryWorkflow,
  factoryMode,
  onFactoryModeChange,
  onCancel,
  onTrigger,
  onRetryFailed,
}: WorkflowLiveViewProps) {
  const stepFilterOptions = [
    { value: "all" as const, label: "All", count: steps.length },
    { value: "active" as const, label: "Active", count: workflowSignals.activeSteps },
    { value: "attention" as const, label: "Attention", count: workflowSignals.attentionSteps.length },
    { value: "activity" as const, label: "Activity", count: workflowSignals.activitySteps.length },
    { value: "complete" as const, label: "Done", count: workflowSignals.completedSteps },
  ];

  const visibleSteps = steps.filter((step) =>
    stepMatchesViewFilter(
      stepViewFilter,
      workflow.step_states?.[step.name],
      pendingApprovalStep === step.name
    )
  );

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Progress bar */}
      {wfSummary && (wfSummary.totalSteps ?? 0) > 0 && (
        <Card className="border-border/65 bg-background/75 shadow-sm backdrop-blur-sm">
          <CardContent className="p-4">
            <ProgressSummaryBar summary={wfSummary} phase={workflow.phase} />
          </CardContent>
        </Card>
      )}

      {/* Agent pipeline */}
      {steps.length > 1 && (
        <Card className="border-border/65 bg-background/75 shadow-sm backdrop-blur-sm">
          <CardContent className="p-4">
            <div className="text-xs font-medium text-muted-foreground mb-3">Agent pipeline</div>
            <div className="flex items-center gap-1 overflow-x-auto pb-1">
              {steps.map((step, idx) => {
                const state = workflow.step_states?.[step.name];
                const status = state?.status ?? "pending";
                const lp = state?.loopProgress;
                const pp = state?.planProgress;
                const isRunningStep = status === "running";
                const isDone = status === "succeeded" || status === "completed";
                const isFailed = status === "failed";

                return (
                  <div key={step.name} className="flex items-center gap-1 shrink-0">
                    <div
                      className={`rounded-xl border px-3 py-2 min-w-[140px] transition-all ${
                        isRunningStep
                          ? "border-primary/40 bg-primary/10 ring-1 ring-primary/20"
                          : isDone
                            ? "border-emerald-500/30 bg-emerald-500/10"
                            : isFailed
                              ? "border-destructive/30 bg-destructive/10"
                              : "border-border/40 bg-background/60"
                      }`}
                    >
                      <div className="flex items-center gap-1.5 mb-1">
                        {stepStatusIcon(status, false).icon}
                        <span className="text-xs font-medium truncate">{step.name}</span>
                      </div>
                      <div className="text-xs text-muted-foreground truncate">{step.agent_ref}</div>
                      {lp && lp.totalItems > 0 && (
                        <div className="mt-1.5">
                          <div className="h-1 w-full overflow-hidden rounded-full bg-border/40">
                            <div
                              className={`h-full rounded-full transition-all duration-500 ${isDone ? "bg-emerald-500" : "bg-primary"}`}
                              style={{
                                width: `${Math.round((lp.completedItems / lp.totalItems) * 100)}%`,
                              }}
                            />
                          </div>
                          <div className="text-xs text-muted-foreground mt-0.5">
                            {lp.completedItems}/{lp.totalItems} · iter {lp.iteration}/{lp.maxIterations}
                          </div>
                        </div>
                      )}
                      {pp && pp.totalItems > 0 && !lp && (
                        <div className="mt-1.5">
                          <div className="h-1 w-full overflow-hidden rounded-full bg-border/40">
                            <div
                              className={`h-full rounded-full transition-all duration-500 ${isDone ? "bg-emerald-500" : "bg-sky-500"}`}
                              style={{
                                width: `${Math.round((pp.completedItems / pp.totalItems) * 100)}%`,
                              }}
                            />
                          </div>
                          <div className="text-xs text-muted-foreground mt-0.5">
                            {pp.completedItems}/{pp.totalItems} tasks
                          </div>
                        </div>
                      )}
                      {isRunningStep && !lp && !pp && (
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

      {/* Suggested next action */}
      {nextAction && (
        <Card className="border-primary/20 bg-primary/5 shadow-sm backdrop-blur-sm">
          <CardContent className="p-4">
            <div className="flex items-start gap-3">
              <Sparkles className="h-4 w-4 mt-0.5 text-primary shrink-0" />
              <div className="space-y-1">
                <p className="text-xs font-medium text-primary/80">Suggested Next</p>
                <p className="text-sm font-semibold text-foreground">{nextAction.action}</p>
                <p className="text-xs text-muted-foreground">{nextAction.reason}</p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Operator signals */}
      <Card className="border-border/65 bg-background/75 shadow-sm backdrop-blur-sm">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Operator signals</CardTitle>
          <CardDescription className="text-xs">High-signal blockers from the current run.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-3">
              <div className="text-xs text-muted-foreground">Attention</div>
              <div className="text-lg font-semibold text-foreground">{workflowSignals.attentionSteps.length}</div>
              <div className="text-xs text-muted-foreground">
                {workflowSignals.verificationFailures} verify · {workflowSignals.reviewRejections} review ·{" "}
                {workflowSignals.jsonContractFailures} JSON
              </div>
            </div>
            <div className="rounded-xl border border-primary/20 bg-primary/5 p-3">
              <div className="text-xs text-muted-foreground">Active now</div>
              <div className="text-lg font-semibold text-foreground">{workflowSignals.activeSteps}</div>
              <div className="text-xs text-muted-foreground">
                {workflow.pending_approval ? 1 : 0} wait
              </div>
            </div>
            <div className="rounded-xl border border-sky-500/20 bg-sky-500/5 p-3">
              <div className="text-xs text-muted-foreground">Tool activity</div>
              <div className="text-lg font-semibold text-foreground">{workflowSignals.totalToolCalls}</div>
              <div className="text-xs text-muted-foreground">
                {workflowSignals.activitySteps.length} step{workflowSignals.activitySteps.length === 1 ? "" : "s"}{" "}
                with actions
              </div>
            </div>
            <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-3">
              <div className="text-xs text-muted-foreground">Files observed</div>
              <div className="text-lg font-semibold text-foreground">{workflowSignals.totalArtifacts}</div>
              <div className="text-xs text-muted-foreground">
                {workflowSignals.totalWarnings} warning{workflowSignals.totalWarnings === 1 ? "" : "s"}
              </div>
            </div>
          </div>

          {workflowSignals.attentionSteps.length > 0 ? (
            <div className="space-y-2">
              <div className="text-xs font-medium text-muted-foreground">Needs attention</div>
              <div className="flex flex-wrap gap-2">
                {workflowSignals.attentionSteps.slice(0, 8).map((signal) => (
                  <div
                    key={signal.name}
                    className="rounded-full border border-amber-500/20 bg-amber-500/5 px-3 py-1.5 text-xs"
                  >
                    <span className="font-medium text-foreground">{signal.name}</span>
                    {signal.reasons.length > 0 && (
                      <span className="ml-2 text-muted-foreground">{signal.reasons.join(" · ")}</span>
                    )}
                  </div>
                ))}
                {workflowSignals.attentionSteps.length > 8 && (
                  <Badge
                    variant="outline"
                    className="border-amber-500/20 bg-amber-500/5 text-xs text-amber-200"
                  >
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
              <div className="text-xs font-medium text-muted-foreground">Observed activity</div>
              <div className="flex flex-wrap gap-2">
                {workflowSignals.activitySteps.slice(0, 8).map((signal) => (
                  <div
                    key={`${signal.name}-activity`}
                    className="rounded-full border border-sky-500/20 bg-sky-500/5 px-3 py-1.5 text-xs text-muted-foreground"
                  >
                    <span className="font-medium text-foreground">{signal.name}</span>
                    <span className="ml-2">
                      {signal.toolCallCount} tools · {signal.artifactCount} files
                      {signal.warningCount > 0 ? ` · ${signal.warningCount} warnings` : ""}
                    </span>
                  </div>
                ))}
                {workflowSignals.activitySteps.length > 8 && (
                  <Badge
                    variant="outline"
                    className="border-sky-500/20 bg-sky-500/5 text-xs text-sky-200"
                  >
                    +{workflowSignals.activitySteps.length - 8} more
                  </Badge>
                )}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Step pipeline */}
      <Card className="border-border/65 bg-background/75 shadow-sm backdrop-blur-sm">
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <div className="flex items-center gap-2">
              <Clock className="h-4 w-4 text-muted-foreground" />
              <CardTitle className="text-sm">Step pipeline</CardTitle>
              {isActive && (
                <Badge variant="outline" className="text-xs border-primary/30 text-primary animate-pulse">
                  LIVE
                </Badge>
              )}
            </div>
            <div className="flex items-center gap-2">
              {isActive && (
                <Button
                  size="sm"
                  variant="destructive"
                  className="h-8 rounded-lg text-xs"
                  disabled={isCancelling}
                  onClick={onCancel}
                >
                  {isCancelling ? (
                    <LoaderCircle className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Square className="mr-1.5 h-3.5 w-3.5" />
                  )}
                  {isCancelling ? "Cancelling…" : "Cancel"}
                </Button>
              )}
              <Button
                size="sm"
                className="h-8 rounded-lg text-xs transition-transform duration-150 active:scale-95"
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
        <CardContent className="space-y-4">
          {/* Trigger confirmation */}
          {showTriggerConfirm && !isActive && (
            <div className="rounded-xl border border-primary/30 bg-primary/5 p-4 space-y-3">
              <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                <Play className="h-4 w-4 text-primary" />
                Confirm run
              </div>
              {isFactoryWorkflow && (
                <div className="rounded-xl border border-border/60 bg-background/70 p-3 space-y-2">
                  <Label className="text-xs font-medium text-muted-foreground">Factory mode</Label>
                  <Select value={factoryMode} onValueChange={(v) => onFactoryModeChange(v as FactoryMode)}>
                    <SelectTrigger className="h-9 text-xs">
                      <SelectValue placeholder="Select a factory mode" />
                    </SelectTrigger>
                    <SelectContent>
                      {FACTORY_MODE_OPTIONS.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          <div className="flex flex-col gap-0.5 py-0.5 text-left">
                            <span className="text-xs font-medium">{option.label}</span>
                            <span className="text-xs text-muted-foreground">{option.description}</span>
                          </div>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}
              <ExpandableMarkdownEditor
                value={triggerInput}
                onChange={setTriggerInput}
                label="Input (editable before run)"
                rows={3}
                placeholder="Describe the task, context, or parameters for this workflow run…"
                dialogTitle="Workflow Run Input"
                dialogDescription="Edit the input payload for this workflow execution. Supports Markdown."
              />
              <div className="flex gap-2">
                <Button
                  size="sm"
                  className="h-8 rounded-lg text-xs"
                  disabled={isRunning}
                  onClick={onTrigger}
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
                  className="h-8 rounded-lg text-xs"
                  onClick={() => setShowTriggerConfirm(false)}
                >
                  Cancel
                </Button>
              </div>
            </div>
          )}

          {/* Running indicator */}
          {isActive && (
            <div className="flex items-center gap-2 rounded-xl border border-primary/30 bg-primary/5 px-3 py-2 text-sm text-primary">
              <LoaderCircle className="h-4 w-4 animate-spin" />
              <span>Workflow is {workflow.phase}…</span>
            </div>
          )}

          {/* Pending approval banner (global) */}
          {isActive && workflow.pending_approval && !pendingApprovalStep && (
            <div className="flex items-center gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-300">
              <ShieldCheck className="h-4 w-4 shrink-0" />
              <span>
                Waiting for approval at <strong>{workflow.current_step || "unknown step"}</strong>
              </span>
            </div>
          )}

          {/* Filters */}
          <div className="flex flex-col gap-2 xl:flex-row xl:items-center xl:justify-between">
            <div className="flex flex-wrap gap-1">
              {stepFilterOptions.map((option) => (
                <Button
                  key={option.value}
                  type="button"
                  size="sm"
                  variant={stepViewFilter === option.value ? "secondary" : "ghost"}
                  className="h-7 rounded-lg px-2 text-xs"
                  onClick={() => setStepViewFilter(option.value)}
                >
                  {option.label}
                  <Badge variant="outline" className="ml-1.5 text-xs">
                    {option.count}
                  </Badge>
                </Button>
              ))}
            </div>
            <div className="text-xs text-muted-foreground">
              {visibleSteps.length === steps.length
                ? `Showing all ${steps.length} step${steps.length === 1 ? "" : "s"}`
                : `Showing ${visibleSteps.length} of ${steps.length} step${steps.length === 1 ? "" : "s"}`}
            </div>
          </div>

          {/* Step list */}
          {visibleSteps.length === 0 ? (
            <div className="rounded-xl border border-border/60 bg-background/60 px-3 py-3 text-xs text-muted-foreground">
              No steps match the current filter.
              {stepViewFilter !== "all" && (
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  className="ml-2 h-6 rounded-lg px-2 text-xs"
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
                    <WorkflowStepDetail
                      step={step}
                      state={state}
                      isApprovalWaiting={isStepApprovalWaiting}
                      approvalReason={approvalReason}
                      approvalBusy={approvalBusy}
                      onApprovalReasonChange={onApprovalReasonChange}
                      onApprovalDecision={onApprovalDecision}
                    />
                    {idx < visibleSteps.length - 1 && (
                      <div className="ml-4 h-3 w-px bg-border/50" />
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {/* Success summary */}
          {(workflow.phase === "succeeded" || workflow.phase === "completed") && (() => {
            const started = wfSummary?.startedAt ? new Date(wfSummary.startedAt) : null;
            const ended = wfSummary?.updatedAt ? new Date(wfSummary.updatedAt) : null;
            const durationMs =
              started && ended && !Number.isNaN(started.getTime()) && !Number.isNaN(ended.getTime())
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
                      <p className="text-xs text-muted-foreground">Started</p>
                      <p className="text-xs font-mono text-foreground">{started.toLocaleString()}</p>
                    </div>
                  )}
                  {ended && !Number.isNaN(ended.getTime()) && (
                    <div className="rounded-lg border border-border/40 bg-background/60 px-2.5 py-1.5">
                      <p className="text-xs text-muted-foreground">Completed</p>
                      <p className="text-xs font-mono text-foreground">{ended.toLocaleString()}</p>
                    </div>
                  )}
                  {durationMs != null && (
                    <div className="rounded-lg border border-border/40 bg-background/60 px-2.5 py-1.5">
                      <p className="text-xs text-muted-foreground">Duration</p>
                      <p className="text-xs font-mono text-foreground">{formatMs(durationMs)}</p>
                    </div>
                  )}
                </div>
              </div>
            );
          })()}

          {/* Failure summary */}
          {workflow.phase === "failed" && (() => {
            const started = wfSummary?.startedAt ? new Date(wfSummary.startedAt) : null;
            const ended = wfSummary?.updatedAt ? new Date(wfSummary.updatedAt) : null;
            const durationMs =
              started && ended && !Number.isNaN(started.getTime()) && !Number.isNaN(ended.getTime())
                ? ended.getTime() - started.getTime()
                : null;
            const failedStepNames = Object.entries(workflow.step_states ?? {})
              .filter(([, s]) => s?.status === "failed")
              .map(([n]) => n);
            return (
              <div className="mt-3 space-y-2">
                <div className="flex items-center gap-2 rounded-xl border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
                  <AlertTriangle className="h-4 w-4 shrink-0" />
                  <span className="font-medium">
                    Failed at <strong>{workflow.current_step || "unknown"}</strong>
                  </span>
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
                      className="h-8 rounded-lg text-xs border-amber-500/40 hover:bg-amber-500/10"
                      disabled={isRetrying}
                      onClick={() => onRetryFailed(workflow.name)}
                    >
                      {isRetrying ? (
                        <LoaderCircle className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Repeat className="mr-1.5 h-3.5 w-3.5" />
                      )}
                      {isRetrying ? "Retrying…" : "Retry failed"}
                    </Button>
                  </div>
                )}
                {(started || ended) && (
                  <div className="grid gap-2 sm:grid-cols-2">
                    {started && !Number.isNaN(started.getTime()) && (
                      <div className="rounded-lg border border-border/40 bg-background/60 px-2.5 py-1.5">
                        <p className="text-xs text-muted-foreground">Started</p>
                        <p className="text-xs font-mono text-foreground">{started.toLocaleString()}</p>
                      </div>
                    )}
                    {ended && !Number.isNaN(ended.getTime()) && (
                      <div className="rounded-lg border border-border/40 bg-background/60 px-2.5 py-1.5">
                        <p className="text-xs text-muted-foreground">Failed at</p>
                        <p className="text-xs font-mono text-foreground">{ended.toLocaleString()}</p>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })()}

          {/* Cancelled summary */}
          {workflow.phase === "cancelled" && (
            <div className="mt-3 flex items-center gap-2 rounded-xl border border-orange-500/30 bg-orange-500/5 px-3 py-2 text-sm text-orange-400">
              <XCircle className="h-4 w-4 shrink-0" />
              <span>Cancelled{workflow.current_step ? ` at step ${workflow.current_step}` : ""}.</span>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
