import {
  CheckCircle2,
  Clock,
  LoaderCircle,
  ShieldCheck,
  Users,
  Workflow,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { WorkflowSummary } from "../../types";

interface WorkflowStatusBarProps {
  phase: string;
  isActive: boolean;
  stepsCount: number;
  wfSummary?: WorkflowSummary;
  uniqueAgentCount: number;
  approvalStepCount: number;
  completedStepCount: number;
  failedStepCount: number;
  waitingApprovalCount: number;
  elapsed?: string;
}

export function WorkflowStatusBar({
  phase,
  isActive,
  stepsCount,
  wfSummary,
  uniqueAgentCount,
  approvalStepCount,
  failedStepCount,
  waitingApprovalCount,
  elapsed,
}: WorkflowStatusBarProps) {
  const totalSteps = wfSummary?.totalSteps ?? stepsCount;
  const doneSteps = wfSummary
    ? (wfSummary.completedSteps ?? 0) +
      (wfSummary.failedSteps ?? 0) +
      (wfSummary.skippedSteps ?? 0)
    : 0;

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-border/60 bg-card/40 px-4 py-3">
      {/* Phase */}
      <div className="flex items-center gap-2">
        {phase === "running" || phase === "queued" ? (
          <LoaderCircle className="h-4 w-4 animate-spin text-primary" />
        ) : phase === "failed" || phase === "cancelled" ? (
          <XCircle className="h-4 w-4 text-destructive" />
        ) : phase === "completed" || phase === "succeeded" ? (
          <CheckCircle2 className="h-4 w-4 text-emerald-400" />
        ) : (
          <Clock className="h-4 w-4 text-muted-foreground" />
        )}
        <span className="text-sm font-medium capitalize">{phase}</span>
      </div>

      <div className="hidden h-4 w-px bg-border sm:block" />

      {/* Steps */}
      <div className="flex items-center gap-2">
        <Workflow className="h-4 w-4 text-muted-foreground" />
        <span className="text-sm text-muted-foreground">Steps</span>
        <Badge variant="secondary" className="text-xs">
          {wfSummary ? `${doneSteps}/${totalSteps}` : stepsCount}
        </Badge>
        {failedStepCount > 0 && (
          <span className="text-xs text-destructive">{failedStepCount} failed</span>
        )}
      </div>

      <div className="hidden h-4 w-px bg-border sm:block" />

      {/* Agents */}
      <div className="flex items-center gap-2">
        <Users className="h-4 w-4 text-muted-foreground" />
        <span className="text-sm text-muted-foreground">Agents</span>
        <Badge variant="secondary" className="text-xs">
          {uniqueAgentCount}
        </Badge>
      </div>

      <div className="hidden h-4 w-px bg-border sm:block" />

      {/* Approvals */}
      <div className="flex items-center gap-2">
        <ShieldCheck className="h-4 w-4 text-muted-foreground" />
        <span className="text-sm text-muted-foreground">Approvals</span>
        <Badge variant="secondary" className="text-xs">
          {isActive ? waitingApprovalCount : approvalStepCount}
        </Badge>
      </div>

      {isActive && elapsed && (
        <>
          <div className="hidden h-4 w-px bg-border sm:block" />
          <div className="ml-auto flex items-center gap-2">
            <Clock className="h-4 w-4 text-muted-foreground" />
            <span className="text-sm text-muted-foreground">{elapsed}</span>
          </div>
        </>
      )}
    </div>
  );
}
