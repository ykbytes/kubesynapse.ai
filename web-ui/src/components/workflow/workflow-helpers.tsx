import {
  AlertTriangle,
  CheckCircle2,
  Circle,
  Clock,
  LoaderCircle,
  ShieldCheck,
  SkipForward,
  XCircle,
} from "lucide-react";
import type {
  WorkflowStep,
  WorkflowStepState,
  WorkflowStepArtifactSummary,
  WorkflowStepToolCallSummary,
} from "../../types";

export function defaultStepsForAgent(agentName?: string): WorkflowStep[] {
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

export function formatMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const m = Math.floor(ms / 60_000);
  const s = Math.round((ms % 60_000) / 1000);
  return `${m}m ${s}s`;
}

export function formatElapsed(startedAt?: string | null): string {
  if (!startedAt) return "—";
  const start = new Date(startedAt).getTime();
  if (Number.isNaN(start)) return "—";
  const elapsed = Date.now() - start;
  return formatMs(Math.max(0, elapsed));
}

export function stepStatusIcon(
  status: string,
  isApprovalWaiting: boolean
): { icon: React.ReactNode; ring: string } {
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

export function statusBadgeVariant(
  status: string
): "default" | "secondary" | "destructive" | "outline" {
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

export function isJsonContractFailure(error?: string | null): boolean {
  const normalized = (error ?? "").toLowerCase();
  return (
    normalized.includes("did not return json output") ||
    normalized.includes("missing required json paths")
  );
}

export function requiredJsonPathsForStep(
  step: WorkflowStep,
  state?: WorkflowStepState
): string[] {
  const stateExecution = state?.execution as Record<string, unknown> | null | undefined;
  const stepExecution = step.execution as Record<string, unknown> | null | undefined;
  const rawPaths =
    stateExecution?.requiredJsonPaths ?? stepExecution?.requiredJsonPaths;
  if (!Array.isArray(rawPaths)) return [];
  return rawPaths.filter(
    (path): path is string => typeof path === "string" && path.trim().length > 0
  );
}

export function artifactSummaryLabel(
  artifact: WorkflowStepArtifactSummary,
  index: number
): string {
  return (
    artifact.path?.trim() ||
    artifact.name?.trim() ||
    artifact.preview?.trim() ||
    `Artifact ${index + 1}`
  );
}

export function artifactSummaryMeta(artifact: WorkflowStepArtifactSummary): string {
  return [artifact.tool, artifact.status, artifact.type]
    .filter((value): value is string => typeof value === "string" && value.trim().length > 0)
    .join(" · ");
}

export function toolCallSummaryLabel(
  toolCall: WorkflowStepToolCallSummary,
  index: number
): string {
  return toolCall.tool?.trim() || toolCall.preview?.trim() || `Tool ${index + 1}`;
}

export function toolCallSummaryMeta(toolCall: WorkflowStepToolCallSummary): string {
  const parts = [toolCall.status, toolCall.inputPreview].filter(
    (value): value is string => typeof value === "string" && value.trim().length > 0
  );
  if (parts.length > 0) return parts.join(" · ");
  return toolCall.preview?.trim() || "";
}

export type StepViewFilter = "all" | "active" | "attention" | "activity" | "complete";

export interface WorkflowSignalStep {
  name: string;
  reasons: string[];
  toolCallCount: number;
  artifactCount: number;
  warningCount: number;
}

export function isStepActive(status: string, isApprovalWaiting: boolean): boolean {
  return isApprovalWaiting || status === "running" || status === "queued";
}

export function isStepComplete(status: string): boolean {
  return status === "succeeded" || status === "completed" || status === "skipped";
}

export function hasStepActivity(state?: WorkflowStepState): boolean {
  return (state?.toolCallCount ?? 0) > 0 || (state?.artifactCount ?? 0) > 0;
}

export function needsStepAttention(
  state?: WorkflowStepState,
  isApprovalWaiting = false
): boolean {
  if (isApprovalWaiting) return true;
  if (!state) return false;
  if (state.status === "failed" || state.status === "continued") return true;
  if (state.verificationResult && !state.verificationResult.passed) return true;
  if (state.reviewResult && !state.reviewResult.approved) return true;
  if ((state.warnings?.length ?? 0) > 0) return true;
  return isJsonContractFailure(state.error);
}

export function stepMatchesViewFilter(
  filter: StepViewFilter,
  state: WorkflowStepState | undefined,
  isApprovalWaiting: boolean
): boolean {
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
