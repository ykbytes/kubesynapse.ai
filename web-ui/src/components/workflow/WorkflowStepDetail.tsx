import { useEffect, useState } from "react";
import {
  Blocks,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Circle,
  LoaderCircle,
  Repeat,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { CopyButton } from "../shared/CopyButton";
import { JsonBlock } from "../shared/JsonBlock";
import {
  formatMs,
  isJsonContractFailure,
  requiredJsonPathsForStep,
  artifactSummaryLabel,
  artifactSummaryMeta,
  toolCallSummaryLabel,
  toolCallSummaryMeta,
  stepStatusIcon,
  statusBadgeVariant,
} from "./workflow-helpers";
import type { WorkflowStep, WorkflowStepState } from "../../types";

/* ────────── loop progress display ────────── */

function LoopProgressDisplay({ progress }: { progress: NonNullable<WorkflowStepState["loopProgress"]> }) {
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
            <Badge
              variant="outline"
              className={`text-xs ${
                cbState === "open"
                  ? "border-destructive/40 text-destructive"
                  : "border-amber-500/40 text-amber-300"
              }`}
            >
              CB: {cbState}
            </Badge>
          )}
          <span className="text-xs tabular-nums text-muted-foreground">{pct}%</span>
        </div>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-violet-500/10">
        <div className="h-full rounded-full bg-violet-500 transition-all" style={{ width: `${pct}%` }} />
      </div>

      {items.length > 0 && (
        <div className="mt-2 space-y-1">
          <div className="text-xs font-medium text-violet-300/80">Plan checklist</div>
          {items.map((item, i) => (
            <div
              key={i}
              className={`flex items-start gap-2 rounded px-2 py-1 text-xs ${
                item.done ? "bg-emerald-500/10 text-emerald-300" : "text-muted-foreground"
              }`}
            >
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
        <span className="text-xs text-muted-foreground">Branch: {progress.featureBranch}</span>
      )}
      {progress.lastCommitSha && (
        <span className="ml-2 text-xs font-mono text-muted-foreground">
          Last commit: {progress.lastCommitSha.slice(0, 8)}
        </span>
      )}
      {progress.exitReason && (
        <div className="text-xs text-amber-300">Exit: {progress.exitReason}</div>
      )}
    </div>
  );
}

/* ────────── plan progress display (non-loop steps) ────────── */

function PlanProgressDisplay({ progress }: { progress: NonNullable<WorkflowStepState["planProgress"]> }) {
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
        <span className="text-xs tabular-nums text-muted-foreground">{pct}%</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-sky-500/10">
        <div className="h-full rounded-full bg-sky-500 transition-all" style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-2 space-y-1">
        {items.map((item, i) => (
          <div
            key={i}
            className={`flex items-start gap-2 rounded px-2 py-1 text-xs ${
              item.done ? "bg-emerald-500/10 text-emerald-300" : "text-muted-foreground"
            }`}
          >
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

interface WorkflowStepDetailProps {
  step: WorkflowStep;
  state: WorkflowStepState | undefined;
  isApprovalWaiting: boolean;
  approvalReason: string;
  approvalBusy: boolean;
  onApprovalReasonChange: (v: string) => void;
  onApprovalDecision: (d: "approved" | "denied") => void;
}

export function WorkflowStepDetail({
  step,
  state,
  isApprovalWaiting,
  approvalReason,
  approvalBusy,
  onApprovalReasonChange,
  onApprovalDecision,
}: WorkflowStepDetailProps) {
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
    if (
      isApprovalWaiting ||
      status === "running" ||
      status === "failed" ||
      jsonContractFailure ||
      warningCount > 0
    ) {
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
      <div className="flex-1 pb-3 min-w-0">
        {/* header row */}
        <button
          type="button"
          className="flex w-full items-center gap-2 text-left"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? (
            <ChevronDown className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          )}
          <span className="text-sm font-medium truncate">{step.name}</span>
          <Badge variant={statusBadgeVariant(status)} className="text-xs shrink-0">
            {status}
          </Badge>
          {step.step_type === "loop" && (
            <Badge
              variant="outline"
              className="border-violet-500/30 bg-violet-500/10 text-violet-300 text-xs shrink-0"
            >
              <Repeat className="mr-1 h-3 w-3" />
              loop
            </Badge>
          )}
          {step.step_type === "review" && (
            <Badge
              variant="outline"
              className="border-blue-500/30 bg-blue-500/10 text-blue-300 text-xs shrink-0"
            >
              <ShieldCheck className="mr-1 h-3 w-3" />
              review
            </Badge>
          )}
          {state?.verificationResult && (
            <Badge
              variant="outline"
              className={`text-xs shrink-0 ${
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
              className={`text-xs shrink-0 ${
                state.reviewResult.approved
                  ? "border-green-500/30 bg-green-500/10 text-green-300"
                  : "border-amber-500/30 bg-amber-500/10 text-amber-300"
              }`}
            >
              {state.reviewResult.approved ? "✓ approved" : "✗ rejected"}
            </Badge>
          )}
          <span className="text-xs text-muted-foreground truncate">
            {step.agent_ref}
            {step.require_approval ? " · approval gate" : ""}
          </span>
          {state?.loopProgress && (
            <span className="text-xs tabular-nums text-violet-300 shrink-0">
              {state.loopProgress.completedItems}/{state.loopProgress.totalItems} items
            </span>
          )}
          {state?.planProgress && !state?.loopProgress && (
            <span className="text-xs tabular-nums text-sky-300 shrink-0">
              {state.planProgress.completedItems}/{state.planProgress.totalItems} tasks
            </span>
          )}
          {state?.toolCallCount != null && state.toolCallCount > 0 && (
            <span className="text-xs tabular-nums text-sky-300 shrink-0">
              {state.toolCallCount} tool{state.toolCallCount === 1 ? "" : "s"}
            </span>
          )}
          {state?.artifactCount != null && state.artifactCount > 0 && (
            <span className="text-xs tabular-nums text-emerald-300 shrink-0">
              {state.artifactCount} file{state.artifactCount === 1 ? "" : "s"}
            </span>
          )}
          {warningCount > 0 && (
            <span className="text-xs tabular-nums text-amber-300 shrink-0">
              {warningCount} warning{warningCount === 1 ? "" : "s"}
            </span>
          )}
          {state?.latencyMs != null && (
            <span className="ml-auto text-xs tabular-nums text-muted-foreground shrink-0">
              {formatMs(state.latencyMs)}
            </span>
          )}
        </button>

        {/* expanded detail */}
        {expanded && (
          <div className="mt-2 space-y-2 rounded-xl border border-border/60 bg-background/70 p-3 text-xs shadow-sm backdrop-blur-sm animate-fade-in">
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
              {state?.latencyMs != null && <span>Duration: {formatMs(state.latencyMs)}</span>}
              {state?.attempts != null && state.attempts > 0 && (
                <span>Attempts: {state.attempts}</span>
              )}
              {state?.approvalWaitMs != null && (
                <span>Approval wait: {formatMs(state.approvalWaitMs)}</span>
              )}
            </div>

            {((state?.toolCallCount ?? 0) > 0 || (state?.artifactCount ?? 0) > 0 || warnings.length > 0) ? (
              <div className="flex flex-wrap gap-2">
                {(state?.toolCallCount ?? 0) > 0 && (
                  <Badge
                    variant="outline"
                    className="border-sky-500/30 bg-sky-500/10 text-xs text-sky-300"
                  >
                    {state?.toolCallCount} tool call{state?.toolCallCount === 1 ? "" : "s"}
                  </Badge>
                )}
                {(state?.artifactCount ?? 0) > 0 && (
                  <Badge
                    variant="outline"
                    className="border-emerald-500/30 bg-emerald-500/10 text-xs text-emerald-300"
                  >
                    {state?.artifactCount} artifact{state?.artifactCount === 1 ? "" : "s"}
                  </Badge>
                )}
                {warnings.length > 0 && (
                  <Badge
                    variant="outline"
                    className="border-amber-500/30 bg-amber-500/10 text-xs text-amber-300"
                  >
                    {warnings.length} warning{warnings.length === 1 ? "" : "s"}
                  </Badge>
                )}
              </div>
            ) : null}

            {state?.loopProgress && <LoopProgressDisplay progress={state.loopProgress} />}

            {state?.planProgress && !state?.loopProgress && (
              <PlanProgressDisplay progress={state.planProgress} />
            )}

            {state?.verificationResult && (
              <div
                className={`rounded-lg border px-3 py-2 ${
                  state.verificationResult.passed
                    ? "border-green-500/30 bg-green-500/10 text-green-300"
                    : "border-red-500/30 bg-red-500/10 text-red-300"
                }`}
              >
                <span className="font-medium">
                  Verification: {state.verificationResult.passed ? "PASSED" : "FAILED"}
                </span>
                {state.verificationResult.criteria && (
                  <div className="mt-1 text-muted-foreground">
                    Criteria: {state.verificationResult.criteria}
                  </div>
                )}
                {state.verificationResult.response && (
                  <div className="mt-1 whitespace-pre-wrap">{state.verificationResult.response}</div>
                )}
              </div>
            )}

            {state?.reviewResult && (
              <div
                className={`rounded-lg border px-3 py-2 ${
                  state.reviewResult.approved
                    ? "border-green-500/30 bg-green-500/10 text-green-300"
                    : "border-amber-500/30 bg-amber-500/10 text-amber-300"
                }`}
              >
                <span className="font-medium">
                  Review:{" "}
                  {state.reviewResult.verdict ??
                    (state.reviewResult.approved ? "APPROVED" : "REJECTED")}
                </span>
                {state.reviewResult.criteria && (
                  <div className="mt-1 text-muted-foreground">
                    Criteria: {state.reviewResult.criteria}
                  </div>
                )}
                {state.reviewResult.response && (
                  <div className="mt-1 whitespace-pre-wrap">{state.reviewResult.response}</div>
                )}
              </div>
            )}

            {state?.iterationFailures && state.iterationFailures.length > 0 && (
              <details>
                <summary className="cursor-pointer text-xs font-medium text-amber-300 hover:text-amber-200">
                  {state.iterationFailures.length} iteration failure(s)
                </summary>
                <div className="mt-1 space-y-1">
                  {state.iterationFailures.map((f, i) => (
                    <div
                      key={i}
                      className="rounded-md border border-red-500/20 bg-red-500/5 px-2 py-1 text-xs"
                    >
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
                <div className="mt-1 text-xs leading-relaxed text-amber-100/80">
                  The agent may still have written files or completed tool calls, but the workflow only
                  marks the step successful when the final response returns valid JSON with every required
                  path.
                </div>
                {requiredJsonPaths.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {requiredJsonPaths.map((path) => (
                      <Badge
                        key={path}
                        variant="outline"
                        className="border-amber-500/30 bg-background/60 text-xs text-amber-200"
                      >
                        {path}
                      </Badge>
                    ))}
                  </div>
                )}
                {state?.responsePreview && (
                  <pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap rounded-lg bg-background/70 p-2 text-xs leading-relaxed text-foreground">
                    {state.responsePreview}
                  </pre>
                )}
              </div>
            )}

            {state?.error && (
              <div className="group relative rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-destructive">
                <div className="absolute top-1.5 right-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
                  <CopyButton value={state.error} />
                </div>
                <span className="font-medium">
                  Error{state.failureClass ? ` (${state.failureClass})` : ""}:
                </span>{" "}
                {state.error}
              </div>
            )}

            {!jsonContractFailure && state?.responsePreview && (
              <details>
                <summary className="cursor-pointer text-xs font-medium text-muted-foreground hover:text-foreground">
                  Last response preview
                </summary>
                <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap rounded-lg bg-background p-2 text-xs leading-relaxed text-muted-foreground">
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
                      <div
                        key={`${toolCall.tool ?? toolCall.preview ?? index}-${index}`}
                        className="rounded-md border border-sky-500/20 bg-sky-500/5 px-2 py-1 text-xs"
                      >
                        <div className="font-medium text-sky-200">
                          {toolCallSummaryLabel(toolCall, index)}
                        </div>
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
                      <div
                        key={`${artifact.path ?? artifact.name ?? artifact.preview ?? index}-${index}`}
                        className="rounded-md border border-emerald-500/20 bg-emerald-500/5 px-2 py-1 text-xs"
                      >
                        <div className="font-medium text-emerald-200">
                          {artifactSummaryLabel(artifact, index)}
                        </div>
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
                    <div
                      key={`${warning.slice(0, 48)}-${index}`}
                      className="rounded-md border border-amber-500/20 bg-amber-500/5 px-2 py-1 text-xs text-amber-100"
                    >
                      {warning}
                    </div>
                  ))}
                </div>
              </details>
            )}

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

            {step.prompt && (
              <details className="group">
                <summary className="cursor-pointer text-xs font-medium text-muted-foreground hover:text-foreground">
                  Prompt
                </summary>
                <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap rounded-lg bg-background p-2 text-xs leading-relaxed text-muted-foreground">
                  {step.prompt}
                </pre>
              </details>
            )}

            {step.depends_on.length > 0 && (
              <div className="text-muted-foreground">
                Depends on:{" "}
                {step.depends_on.map((d) => (
                  <Badge key={d} variant="outline" className="ml-1 text-xs">
                    {d}
                  </Badge>
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
                className="h-8 rounded-lg bg-emerald-600 text-xs hover:bg-emerald-500"
                disabled={approvalBusy}
                onClick={() => onApprovalDecision("approved")}
              >
                {approvalBusy ? (
                  <LoaderCircle className="mr-1 h-3 w-3 animate-spin" />
                ) : (
                  <CheckCircle2 className="mr-1 h-3 w-3" />
                )}
                Approve
              </Button>
              <Button
                size="sm"
                variant="destructive"
                className="h-8 rounded-lg text-xs"
                disabled={approvalBusy}
                onClick={() => onApprovalDecision("denied")}
              >
                {approvalBusy ? (
                  <LoaderCircle className="mr-1 h-3 w-3 animate-spin" />
                ) : (
                  <XCircle className="mr-1 h-3 w-3" />
                )}
                Deny
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
