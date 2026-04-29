import { useEffect, useMemo, useState } from "react";
import { Clock, FolderOpen, Pencil, Blocks } from "lucide-react";
import { useConnection } from "@/contexts/ConnectionContext";
import { fetchWorkflowNextAction, type WorkflowRunRecord } from "@/lib/api";
import { isFactoryWorkflowName } from "@/lib/factoryModes";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "./ConfirmDialog";
import { WorkflowHeader } from "./workflow/WorkflowHeader";
import { WorkflowStatusBar } from "./workflow/WorkflowStatusBar";
import { WorkflowExecutionBrief } from "./workflow/WorkflowExecutionBrief";
import { WorkflowDefinitionForm } from "./workflow/WorkflowDefinitionForm";
import { WorkflowSidebar } from "./workflow/WorkflowSidebar";
import { WorkflowStepsList } from "./workflow/WorkflowStepsList";
import { WorkflowLiveView } from "./workflow/WorkflowLiveView";
import { WorkflowHistoryView } from "./workflow/WorkflowHistoryView";
import {
  defaultStepsForAgent,
  formatElapsed,
  isStepActive,
  isStepComplete,
  hasStepActivity,
  needsStepAttention,
  type StepViewFilter,
  type WorkflowSignalStep,
} from "./workflow/workflow-helpers";
import type {
  AgentInfo,
  FactoryMode,
  WorkflowInfo,
  WorkflowNextAction,
  WorkflowPayload,
  WorkflowStep,
  WorkflowUpdatePayload,
} from "../types";

/* ───────────── props ───────────── */

export interface WorkflowManagerProps {
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

/* ───────────── main component ───────────── */

export function WorkflowManager({
  workflow,
  agents,
  isSaving,
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

  /* state */
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
  const [triggerInput, setTriggerInput] = useState("");
  const [showTriggerConfirm, setShowTriggerConfirm] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  /* effects */
  useEffect(() => {
    if (workflow) {
      setName(workflow.name);
      setDescription(workflow.description);
      setInput(workflow.input);
      setContextRef(workflow.context_ref ?? "");
      setMessageBus(workflow.message_bus);
      setSteps(workflow.steps.length > 0 ? workflow.steps : defaultStepsForAgent(agents[0]?.name));
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
        if (!cancelled) setNextAction(payload);
      } catch {
        if (!cancelled) setNextAction(null);
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

  useEffect(() => {
    const hasBeenTriggered = Boolean(
      workflow && (workflow.phase !== "pending" || workflow.run_id || workflow.summary)
    );
    setWorkspaceTab(workflow && hasBeenTriggered ? "live" : "definition");
  }, [workflow?.name, workflow?.run_id, workflow?.phase, workflow?.summary]);

  /* step helpers */
  function updateStep(index: number, updater: (current: WorkflowStep) => WorkflowStep) {
    setSteps((current) =>
      current.map((step, stepIndex) => (stepIndex === index ? updater(step) : step))
    );
  }

  function renameStep(index: number, nextName: string) {
    setSteps((current) => {
      const previousName = current[index]?.name ?? "";
      return current.map((step, stepIndex) => {
        const renamedStep =
          stepIndex === index
            ? { ...step, name: nextName }
            : step;
        if (!previousName || previousName === nextName) {
          return renamedStep;
        }
        return {
          ...renamedStep,
          depends_on: renamedStep.depends_on.map((dep) =>
            dep === previousName ? nextName : dep
          ),
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
          depends_on: step.depends_on.filter((dep) => dep !== removedName),
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

  function handleAddStep() {
    setSteps((current) => [
      ...current,
      {
        name: `step-${current.length + 1}`,
        agent_ref: agents[0]?.name ?? "",
        prompt: "",
        depends_on: [],
        require_approval: false,
      },
    ]);
  }

  function handleTrigger() {
    if (!workflow) return;
    onTrigger(
      workflow.name,
      triggerInput.trim() || undefined,
      isFactoryWorkflowName(workflow.name) ? factoryMode : undefined
    );
    setShowTriggerConfirm(false);
  }

  function handleSave() {
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
  }

  function handleCancel() {
    if (workflow && onCancel) onCancel(workflow.name);
  }

  /* derived values */
  const stepNames = steps.map((s) => s.name.trim()).filter(Boolean);
  const hasUniqueStepNames = new Set(stepNames).size === stepNames.length;
  const canSubmit =
    Boolean(name.trim()) && steps.length > 0 && hasUniqueStepNames &&
    steps.every((step) => step.name.trim() && step.agent_ref.trim());
  const uniqueAgentCount = new Set(steps.map((s) => s.agent_ref).filter(Boolean)).size;
  const approvalStepCount = steps.filter((s) => s.require_approval).length;
  const loopStepCount = steps.filter((s) => s.step_type === "loop").length;
  const reviewStepCount = steps.filter((s) => s.step_type === "review").length;

  const pendingApprovalStep = useMemo(() => {
    if (!workflow?.pending_approval) return null;
    const pa = workflow.pending_approval;
    return typeof pa.stepName === "string" ? pa.stepName : workflow.current_step || null;
  }, [workflow?.pending_approval, workflow?.current_step]);

  const wfSummary = workflow?.summary ?? undefined;
  const isActive =
    workflow?.phase === "running" || workflow?.phase === "queued" || workflow?.phase === "waiting-approval";
  const hasBeenTriggered = Boolean(
    workflow && (workflow.phase !== "pending" || workflow.run_id || workflow.summary)
  );
  const completedStepCount =
    wfSummary?.completedSteps ??
    Object.values(workflow?.step_states ?? {}).filter(
      (s) => s?.status === "succeeded" || s?.status === "completed"
    ).length;
  const failedStepCount =
    wfSummary?.failedSteps ??
    Object.values(workflow?.step_states ?? {}).filter((s) => s?.status === "failed").length;
  const waitingApprovalCount =
    wfSummary?.waitingApprovalSteps ?? (workflow?.pending_approval ? 1 : 0);
  const currentFocus =
    workflow?.current_step ||
    wfSummary?.currentFrontier?.[0] ||
    nextAction?.failedSteps?.[0] ||
    nextAction?.verifyFailures?.[0] ||
    "Ready for execution";

  const workflowBrief = useMemo(() => {
    if (!workflow) {
      return {
        title: "Design an orchestration path that is easy to operate",
        body: "Use clear step ownership, deliberate approval gates, and retry-friendly boundaries so the workflow reads like an operational playbook instead of a prompt chain.",
      };
    }
    if (workflow.phase === "waiting-approval") {
      return {
        title: "Execution is blocked on a human gate",
        body: `The current run has reached an approval boundary at ${currentFocus}. Resolve that decision before expecting additional progress from the operator.`,
      };
    }
    if (workflow.phase === "running" || workflow.phase === "queued") {
      return {
        title: "The workflow is actively progressing through its execution graph",
        body: `${completedStepCount} of ${wfSummary?.totalSteps ?? steps.length} steps are complete. Focus attention on ${currentFocus} and use logs or run history to verify whether this run is tracking normally.`,
      };
    }
    if (workflow.phase === "failed") {
      return {
        title: "The latest run failed and should be triaged before re-running end to end",
        body: `${failedStepCount} step${failedStepCount === 1 ? "" : "s"} failed. Use the failed-step summary, logs, and recent-run comparison below to isolate what regressed and retry only what broke.`,
      };
    }
    if (workflow.phase === "completed" || workflow.phase === "succeeded") {
      return {
        title: "The workflow is in a strong state for reuse and comparison",
        body: `The last execution completed successfully across ${wfSummary?.totalSteps ?? steps.length} steps. Compare that result against prior runs before changing prompts, agents, or approval policy.`,
      };
    }
    return {
      title: "The workflow definition is ready, but the operational story is still ahead",
      body: "Run the workflow once to capture the first execution baseline, then refine failure handling, approvals, and run-to-run consistency from real results.",
    };
  }, [completedStepCount, currentFocus, failedStepCount, steps.length, wfSummary?.totalSteps, workflow]);

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
      if (state?.error && state.error.toLowerCase().includes("did not return json output")) {
        jsonContractFailures += 1;
        reasons.push("json");
      }
      if (warningCount > 0) {
        reasons.push(`${warningCount} warning${warningCount === 1 ? "" : "s"}`);
      }

      if (isStepActive(status, isApprovalWaiting)) activeSteps += 1;
      if (isStepComplete(status)) completedSteps += 1;
      if (needsStepAttention(state, isApprovalWaiting)) {
        attentionSteps.push({ name: step.name, reasons, toolCallCount, artifactCount, warningCount });
      }
      if (hasStepActivity(state)) {
        activitySteps.push({ name: step.name, reasons, toolCallCount, artifactCount, warningCount });
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

  const workflowAgents = useMemo(() => {
    if (!workflow) return [] as string[];
    const result = new Set<string>();
    for (const step of workflow.steps) {
      if (step.agent_ref) {
        result.add(step.agent_ref);
      }
    }
    return Array.from(result);
  }, [workflow]);

  const isFactoryWorkflow = isFactoryWorkflowName(workflow?.name);

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <WorkflowHeader
        workflowName={workflow?.name ?? null}
        phase={workflow?.phase ?? "draft"}
        isActive={isActive}
        isFactoryWorkflow={isFactoryWorkflow}
        factoryMode={factoryMode}
        isRunning={isRunning}
        isCancelling={isCancelling}
        isSaving={isSaving}
        canSubmit={canSubmit}
        canMutate={canMutate}
        onRun={() => {
          setTriggerInput(workflow?.input ?? "");
          setShowTriggerConfirm(true);
        }}
        onCancel={handleCancel}
        onSave={handleSave}
        onDelete={() => setDeleteDialogOpen(true)}
        onOpenComposer={onOpenComposer}
      />

      {/* Status bar */}
      <WorkflowStatusBar
        phase={workflow?.phase ?? "draft"}
        isActive={isActive}
        stepsCount={steps.length}
        wfSummary={wfSummary}
        uniqueAgentCount={uniqueAgentCount}
        approvalStepCount={approvalStepCount}
        completedStepCount={completedStepCount}
        failedStepCount={failedStepCount}
        waitingApprovalCount={waitingApprovalCount}
        elapsed={isActive && wfSummary?.startedAt ? formatElapsed(wfSummary.startedAt) : undefined}
      />

      {/* Execution brief */}
      <WorkflowExecutionBrief
        title={workflowBrief.title}
        body={workflowBrief.body}
        nextAction={nextAction}
      />

      {/* Tabs */}
      <Tabs
        value={workflow && hasBeenTriggered ? workspaceTab : "definition"}
        onValueChange={(value) => setWorkspaceTab(value as "live" | "history" | "definition")}
        className="space-y-6"
      >
        {workflow && hasBeenTriggered && (
          <div className="rounded-2xl border border-border/60 bg-card/40 p-2">
            <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
              <div className="px-2 py-1">
                <div className="text-xs font-medium text-muted-foreground">Workflow workspace</div>
                <div className="text-sm font-semibold text-foreground">
                  Operate, trace, or edit without leaving this page.
                </div>
              </div>
              <TabsList className="h-auto w-full flex-wrap justify-start gap-2 rounded-xl bg-transparent p-0 lg:w-auto">
                <TabsTrigger
                  value="live"
                  className="gap-2 rounded-xl border border-border/60 bg-background/70 px-3 py-2 text-xs data-[state=active]:border-primary/30 data-[state=active]:bg-primary/10 data-[state=active]:text-foreground data-[state=active]:shadow-none"
                >
                  <Clock className="h-3.5 w-3.5" />
                  Live run
                </TabsTrigger>
                <TabsTrigger
                  value="history"
                  className="gap-2 rounded-xl border border-border/60 bg-background/70 px-3 py-2 text-xs data-[state=active]:border-primary/30 data-[state=active]:bg-primary/10 data-[state=active]:text-foreground data-[state=active]:shadow-none"
                >
                  <FolderOpen className="h-3.5 w-3.5" />
                  History and trace
                </TabsTrigger>
                <TabsTrigger
                  value="definition"
                  className="gap-2 rounded-xl border border-border/60 bg-background/70 px-3 py-2 text-xs data-[state=active]:border-primary/30 data-[state=active]:bg-primary/10 data-[state=active]:text-foreground data-[state=active]:shadow-none"
                >
                  <Pencil className="h-3.5 w-3.5" />
                  Definition
                </TabsTrigger>
              </TabsList>
            </div>
          </div>
        )}

        {/* Live tab */}
        {workflow && hasBeenTriggered && (
          <TabsContent value="live" className="mt-0">
            <WorkflowLiveView
              workflow={workflow}
              steps={steps}
              wfSummary={wfSummary}
              isActive={isActive}
              pendingApprovalStep={pendingApprovalStep}
              workflowSignals={workflowSignals}
              stepViewFilter={stepViewFilter}
              setStepViewFilter={setStepViewFilter}
              approvalReason={approvalReason}
              approvalBusy={approvalBusy}
              onApprovalReasonChange={onApprovalReasonChange}
              onApprovalDecision={onApprovalDecision}
              nextAction={nextAction}
              showTriggerConfirm={showTriggerConfirm}
              setShowTriggerConfirm={setShowTriggerConfirm}
              triggerInput={triggerInput}
              setTriggerInput={setTriggerInput}
              isRunning={isRunning}
              isCancelling={isCancelling}
              isRetrying={isRetrying}
              isFactoryWorkflow={isFactoryWorkflow}
              factoryMode={factoryMode}
              onFactoryModeChange={onFactoryModeChange}
              onCancel={handleCancel}
              onTrigger={handleTrigger}
              onRetryFailed={onRetryFailed}
            />
          </TabsContent>
        )}

        {/* History tab */}
        {workflow && hasBeenTriggered && (
          <TabsContent value="history" className="mt-0">
              <WorkflowHistoryView
                workflow={workflow}
                selectedHistoryRun={selectedHistoryRun}
                setSelectedHistoryRun={setSelectedHistoryRun}
                activeRunAgents={workflowAgents}
                isActive={isActive}
              />
          </TabsContent>
        )}

        {/* Definition tab */}
        <TabsContent value="definition" className="mt-0 space-y-6">
          {/* Definition studio banner */}
          {workflow && (
            <div className="rounded-2xl border border-border/60 bg-card/40 p-4">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                <div>
                  <div className="text-xs font-medium text-muted-foreground">Definition studio</div>
                  <div className="text-sm font-semibold text-foreground">
                    Refine the workflow contract, step graph, and execution policy.
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  {hasBeenTriggered && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-8 rounded-lg text-xs"
                      onClick={() => setWorkspaceTab("live")}
                    >
                      <Clock className="mr-1.5 h-3.5 w-3.5" />
                      Back to live run
                    </Button>
                  )}
                  {onOpenComposer && (
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-8 rounded-lg text-xs"
                      onClick={onOpenComposer}
                    >
                      <Blocks className="mr-1.5 h-3.5 w-3.5" />
                      Edit in Composer
                    </Button>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Form + Sidebar */}
          <div className="grid gap-6 xl:grid-cols-[1fr_20rem]">
            <div className="rounded-2xl border border-border/70 bg-card/55 p-5">
              <WorkflowDefinitionForm
                name={name}
                setName={setName}
                description={description}
                setDescription={setDescription}
                input={input}
                setInput={setInput}
                contextRef={contextRef}
                setContextRef={setContextRef}
                isEditing={Boolean(workflow)}
              />
            </div>
            <div className="rounded-2xl border border-border/70 bg-card/55 p-5">
              <WorkflowSidebar
                messageBus={messageBus}
                setMessageBus={setMessageBus}
                loopStepCount={loopStepCount}
                reviewStepCount={reviewStepCount}
                uniqueAgentCount={uniqueAgentCount}
                stepsCount={steps.length}
                isTriggered={hasBeenTriggered}
                wfSummary={wfSummary}
                phase={workflow?.phase ?? "draft"}
              />
            </div>
          </div>

          {/* Steps */}
          <WorkflowStepsList
            steps={steps}
            agents={agents}
            onAddStep={handleAddStep}
            onRenameStep={renameStep}
            onUpdateStep={updateStep}
            onRemoveStep={removeStep}
            onToggleDependency={toggleDependency}
          />
        </TabsContent>
      </Tabs>

      {/* Error */}
      {error && (
        <div className="rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive" role="alert">
          {error}
        </div>
      )}

      {/* Delete dialog */}
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
    </div>
  );
}
