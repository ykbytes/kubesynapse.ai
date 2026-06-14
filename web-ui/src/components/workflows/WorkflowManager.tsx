import { useEffect, useMemo, useState } from "react";
import {
  BarChart3,
  Blocks,
  Clock,
  FolderOpen,
  LoaderCircle,
  Pencil,
  Play,
  Save,
  ScrollText,
  Square,
  Trash2,
  Workflow,
} from "lucide-react";
import { useConnection } from "@/contexts/ConnectionContext";
import { fetchWorkflowNextAction, type WorkflowRunRecord } from "@/lib/api";
import { isFactoryWorkflowName } from "@/lib/factoryModes";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ConfirmDialog } from "../shared/ConfirmDialog";
import { ErrorBanner } from "../shared/ErrorBanner";
import { ErrorDialog } from "../shared/ErrorDialog";
import { ResourceLogsPanel } from "../shared/ResourceLogsPanel";
import { WorkflowDefinitionForm } from "../workflow/WorkflowDefinitionForm";
import { WorkflowSidebar } from "../workflow/WorkflowSidebar";
import { WorkflowStepsList } from "../workflow/WorkflowStepsList";
import { WorkflowLiveView } from "../workflow/WorkflowLiveView";
import { WorkflowHistoryView } from "../workflow/WorkflowHistoryView";
import { WorkflowFilesView } from "../workflow/WorkflowFilesView";
import { useManifestViewer } from "@/hooks/useManifestViewer";
import {
  defaultStepsForAgent,
  isStepActive,
  isStepComplete,
  hasStepActivity,
  needsStepAttention,
  type StepViewFilter,
  type WorkflowSignalStep,
} from "../workflow/workflow-helpers";
import type {
  AgentInfo,
  FactoryMode,
  WorkflowInfo,
  WorkflowNextAction,
  WorkflowPayload,
  WorkflowStep,
  WorkflowUpdatePayload,
} from "../../types";

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
  const { canMutate, token, namespace, hasCapability } = useConnection();

  /* state */
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [input, setInput] = useState("");
  const [contextRef, setContextRef] = useState("");
  const [messageBus, setMessageBus] = useState("in-memory");
  const [steps, setSteps] = useState<WorkflowStep[]>(() => defaultStepsForAgent(agents[0]?.name));
  const [nextAction, setNextAction] = useState<WorkflowNextAction | null>(null);
  const [stepViewFilter, setStepViewFilter] = useState<StepViewFilter>("all");
  const [workspaceTab, setWorkspaceTab] = useState<"overview" | "runs" | "files" | "definition" | "logs">("definition");
  const [selectedHistoryRun, setSelectedHistoryRun] = useState<WorkflowRunRecord | null>(null);
  const [triggerInput, setTriggerInput] = useState("");
  const [showTriggerConfirm, setShowTriggerConfirm] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [errorDialogOpen, setErrorDialogOpen] = useState(false);

  useEffect(() => {
    if (error) setErrorDialogOpen(true);
  }, [error]);

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
    setWorkspaceTab(workflow && hasBeenTriggered ? "overview" : "definition");
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
  const activeTab = workflow && hasBeenTriggered ? workspaceTab : "definition";
  const { ManifestButton, ManifestModalComponent } = useManifestViewer({
    resourceType: "workflow",
    resourceName: workflow?.name ?? "",
    namespace: namespace ?? "default",
    token: token ?? "",
  });

  return (
    <div className="animate-fade-in">
      <Tabs
        value={activeTab}
        onValueChange={(value) => setWorkspaceTab(value as "overview" | "runs" | "files" | "definition" | "logs")}
        className="overflow-hidden rounded-lg border border-border/70 bg-background/70 shadow-sm"
      >
        <div className="border-b border-border/70 bg-card/70">
          <div className="flex flex-col gap-4 px-5 py-4 xl:flex-row xl:items-start xl:justify-between">
            <div className="flex min-w-0 gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md border border-primary/25 bg-primary/10 text-primary">
                <Workflow className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="min-w-0 truncate text-lg font-semibold tracking-normal text-foreground">
                    {workflow?.name ?? "Create workflow"}
                  </h1>
                  <Badge
                    variant={
                      isActive
                        ? "default"
                        : workflow?.phase === "failed" || workflow?.phase === "cancelled"
                          ? "destructive"
                          : "secondary"
                    }
                    className="capitalize"
                  >
                    {workflow?.phase ?? "draft"}
                  </Badge>
                  {isFactoryWorkflow && (
                    <Badge variant="outline" className="border-primary/25 bg-primary/5 text-primary">
                      Factory
                    </Badge>
                  )}
                </div>
                <p className="mt-1 max-w-3xl text-sm leading-relaxed text-muted-foreground">
                  {workflow?.description || workflowBrief.body}
                </p>
                {workflow && (
                  <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <span>{steps.length} step{steps.length === 1 ? "" : "s"}</span>
                    <span>{uniqueAgentCount} agent{uniqueAgentCount === 1 ? "" : "s"}</span>
                    {workflow.run_id && <span className="font-mono">{workflow.run_id}</span>}
                  </div>
                )}
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              {workflow?.name && (
                <Button
                  variant="outline"
                  size="sm"
                  className="h-9 rounded-md text-xs"
                  onClick={() => {
                    setTriggerInput(workflow?.input ?? "");
                    setShowTriggerConfirm(true);
                    setWorkspaceTab("overview");
                  }}
                  disabled={isRunning || isActive}
                >
                  {isRunning ? <LoaderCircle className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Play className="mr-1.5 h-3.5 w-3.5" />}
                  {isRunning ? "Running..." : "Run"}
                </Button>
              )}
              {isActive && (
                <Button
                  variant="destructive"
                  size="sm"
                  className="h-9 rounded-md text-xs"
                  onClick={handleCancel}
                  disabled={isCancelling}
                >
                  {isCancelling ? <LoaderCircle className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Square className="mr-1.5 h-3.5 w-3.5" />}
                  {isCancelling ? "Cancelling..." : "Cancel"}
                </Button>
              )}
              {canMutate && (
                <Button size="sm" className="h-9 rounded-md text-xs" onClick={handleSave} disabled={!canSubmit || isSaving}>
                  {isSaving ? <LoaderCircle className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Save className="mr-1.5 h-3.5 w-3.5" />}
                  {isSaving ? "Saving..." : workflow ? "Save" : "Create"}
                </Button>
              )}
              {onOpenComposer && workflow?.name && (
                <Button variant="outline" size="sm" className="h-9 rounded-md text-xs" onClick={onOpenComposer}>
                  <Blocks className="mr-1.5 h-3.5 w-3.5" />
                  Composer
                </Button>
              )}
              {workflow?.name && <ManifestButton />}
              {workflow?.name && canMutate && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-9 rounded-md text-xs text-destructive hover:bg-destructive/10 hover:text-destructive"
                  onClick={() => setDeleteDialogOpen(true)}
                >
                  <Trash2 className="mr-1.5 h-3.5 w-3.5" />
                  Delete
                </Button>
              )}
            </div>
          </div>

          <div className="flex flex-col gap-3 border-t border-border/60 px-5 py-3 lg:flex-row lg:items-center lg:justify-between">
            <TabsList className="h-auto w-full justify-start gap-1 rounded-md bg-muted/45 p-1 lg:w-auto">
              {workflow && hasBeenTriggered && (
                <>
                  <TabsTrigger value="overview" className="gap-2 rounded px-3 py-2 text-xs">
                    <Clock className="h-3.5 w-3.5" />
                    Overview
                  </TabsTrigger>
                  <TabsTrigger value="runs" className="gap-2 rounded px-3 py-2 text-xs">
                    <BarChart3 className="h-3.5 w-3.5" />
                    Runs
                  </TabsTrigger>
                  <TabsTrigger value="files" className="gap-2 rounded px-3 py-2 text-xs">
                    <FolderOpen className="h-3.5 w-3.5" />
                    Files
                  </TabsTrigger>
                  <TabsTrigger value="logs" className="gap-2 rounded px-3 py-2 text-xs">
                    <ScrollText className="h-3.5 w-3.5" />
                    Logs
                  </TabsTrigger>
                </>
              )}
              <TabsTrigger value="definition" className="gap-2 rounded px-3 py-2 text-xs">
                <Pencil className="h-3.5 w-3.5" />
                Definition
              </TabsTrigger>
            </TabsList>
          </div>
        </div>

        {workflow && hasBeenTriggered && (
          <TabsContent value="overview" className="m-0 p-5">
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

        {workflow && hasBeenTriggered && (
          <TabsContent value="runs" className="m-0 p-5">
              <WorkflowHistoryView
                workflow={workflow}
                selectedHistoryRun={selectedHistoryRun}
                setSelectedHistoryRun={setSelectedHistoryRun}
                isActive={isActive}
              />
          </TabsContent>
        )}

        {workflow && hasBeenTriggered && (
          <TabsContent value="files" className="m-0 p-5">
            <WorkflowFilesView agents={workflowAgents} liveUpdatesEnabled={isActive} />
          </TabsContent>
        )}

        {workflow && hasBeenTriggered && (
          <TabsContent value="logs" className="m-0 p-5">
            <div className="rounded-lg border border-border/60 bg-card/55 p-4">
              <div className="mb-3 flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
                <div>
                  <div className="text-xs font-medium text-muted-foreground">Live worker logs</div>
                  <div className="text-sm font-semibold text-foreground">
                    Stream logs from the workflow worker pod.
                  </div>
                </div>
                <span className="text-[10px] text-muted-foreground">
                  Requires the <code className="px-1 py-0.5 rounded bg-muted">runtime:logs</code> capability, granted by an administrator.
                </span>
              </div>
              <ResourceLogsPanel
                token={token}
                namespace={namespace}
                source={{ kind: "workflow", workflowName: workflow.name, runId: workflow.run_id ?? null }}
                contextLabel="container: worker"
                capabilityMissing={!hasCapability("runtime:logs")}
              />
            </div>
          </TabsContent>
        )}

        <TabsContent value="definition" className="m-0 space-y-6 p-5">
          {workflow && (
            <div className="rounded-lg border border-border/60 bg-card/55 p-4">
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
                      className="h-8 rounded-md text-xs"
                      onClick={() => setWorkspaceTab("overview")}
                    >
                      <Clock className="mr-1.5 h-3.5 w-3.5" />
                      Back to overview
                    </Button>
                  )}
                  {onOpenComposer && (
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-8 rounded-md text-xs"
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

          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_20rem]">
            <div className="min-w-0">
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
            <div className="rounded-lg border border-border/70 bg-card/55 p-5">
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

      {error && (
        <div className="mt-4">
          <ErrorBanner error={error} onDismiss={() => setErrorDialogOpen(false)} />
        </div>
      )}
      <ErrorDialog
        error={error ? new Error(error) : null}
        open={errorDialogOpen}
        onClose={() => setErrorDialogOpen(false)}
      />

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
      <ManifestModalComponent />
    </div>
  );
}
