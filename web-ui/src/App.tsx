import "@fontsource/newsreader/600.css";
import "@fontsource/space-grotesk/400.css";
import "@fontsource/space-grotesk/500.css";
import "@fontsource/space-grotesk/700.css";

import { useEffect, useRef, useState } from "react";
import { LayoutPanelTop, Shield, Sparkles } from "lucide-react";

import { AgentManagementPanel } from "./components/AgentManagementPanel";
import { ChatWorkbench } from "./components/ChatWorkbench";
import { CreateAgentPanel } from "./components/CreateAgentPanel";
import { EvalManager } from "./components/EvalManager";
import { InspectorPanel } from "./components/InspectorPanel";
import { ResourceInspectorPanel } from "./components/ResourceInspectorPanel";
import { WorkflowManager } from "./components/WorkflowManager";
import { WorkspaceSidebar, type SidebarResourceItem } from "./components/WorkspaceSidebar";
import {
  createAgent,
  createEval,
  createWorkflow,
  decideApproval,
  deleteAgent,
  deleteEval,
  deleteWorkflow,
  fetchAgent,
  fetchAgentLogs,
  fetchGatewayHealth,
  invokeAgent,
  listAgents,
  listEvals,
  listPolicies,
  listWorkflows,
  streamAgentInvoke,
  updateAgent,
  updateEval,
  updateWorkflow,
} from "./lib/api";
import type {
  AgentDetail,
  AgentInfo,
  EvalInfo,
  EvalPayload,
  EvalUpdatePayload,
  GatewayHealth,
  InvocationSummary,
  InvokePayload,
  PolicyInfo,
  UiActivity,
  UiMessage,
  UpdateAgentPayload,
  WorkflowInfo,
  WorkflowPayload,
  WorkflowUpdatePayload,
  WorkspaceView,
} from "./types";

const TOKEN_STORAGE_KEY = "ai-agent-sandbox/token";
const NAMESPACE_STORAGE_KEY = "ai-agent-sandbox/namespace";
const DEFAULT_AGENT_NAME = "workspace-assistant";
const DEFAULT_AGENT_MODEL = "gpt-4";
const DEFAULT_SYSTEM_PROMPT =
  "You are a helpful enterprise assistant. Answer clearly, stay factual, and do not fabricate information.";

type InvokeExecutionOptions = {
  agentName: string;
  payload: InvokePayload;
  userPrompt?: string;
  appendUserMessage?: boolean;
  systemNotice?: string;
};

function createId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
}

function workflowSpecFromResource(resource: WorkflowInfo | null): Record<string, unknown> | null {
  if (!resource) {
    return null;
  }
  return {
    description: resource.description,
    input: resource.input,
    message_bus: resource.message_bus,
    steps: resource.steps,
  };
}

function workflowStatusFromResource(resource: WorkflowInfo | null): Record<string, unknown> | null {
  if (!resource) {
    return null;
  }
  return {
    phase: resource.phase,
    current_step: resource.current_step,
    observed_generation: resource.observed_generation,
    pending_approval: resource.pending_approval,
    artifact_ref: resource.artifact_ref,
    worker_job: resource.worker_job,
    created_at: resource.created_at,
  };
}

function evalSpecFromResource(resource: EvalInfo | null): Record<string, unknown> | null {
  if (!resource) {
    return null;
  }
  return {
    agent_ref: resource.agent_ref,
    schedule: resource.schedule,
    test_suite: resource.test_suite,
    failure_threshold: resource.failure_threshold,
  };
}

function evalStatusFromResource(resource: EvalInfo | null): Record<string, unknown> | null {
  if (!resource) {
    return null;
  }
  return {
    phase: resource.phase,
    passed: resource.passed,
    last_run: resource.last_run,
    observed_generation: resource.observed_generation,
    artifact_ref: resource.artifact_ref,
    worker_job: resource.worker_job,
    created_at: resource.created_at,
  };
}

export default function App() {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_STORAGE_KEY) ?? "");
  const [namespace, setNamespace] = useState(() => localStorage.getItem(NAMESPACE_STORAGE_KEY) ?? "default");
  const [activeView, setActiveView] = useState<WorkspaceView>("agents");
  const [health, setHealth] = useState<GatewayHealth | null>(null);
  const [gatewayError, setGatewayError] = useState("");
  const [workspaceError, setWorkspaceError] = useState("");

  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [policies, setPolicies] = useState<PolicyInfo[]>([]);
  const [workflows, setWorkflows] = useState<WorkflowInfo[]>([]);
  const [evals, setEvals] = useState<EvalInfo[]>([]);

  const [selectedAgentName, setSelectedAgentName] = useState("");
  const [selectedWorkflowName, setSelectedWorkflowName] = useState("");
  const [selectedEvalName, setSelectedEvalName] = useState("");
  const [agentCreateMode, setAgentCreateMode] = useState(false);
  const [workflowCreateMode, setWorkflowCreateMode] = useState(false);
  const [evalCreateMode, setEvalCreateMode] = useState(false);
  const [selectedAgentDetail, setSelectedAgentDetail] = useState<AgentDetail | null>(null);

  const [messagesByAgent, setMessagesByAgent] = useState<Record<string, UiMessage[]>>({});
  const [activityByAgent, setActivityByAgent] = useState<Record<string, UiActivity[]>>({});
  const [summaryByAgent, setSummaryByAgent] = useState<Record<string, InvocationSummary | null>>({});
  const [logsByAgent, setLogsByAgent] = useState<Record<string, string>>({});

  const [catalogLoading, setCatalogLoading] = useState(false);
  const [logsLoading, setLogsLoading] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [isCreatingAgent, setIsCreatingAgent] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [savingAgent, setSavingAgent] = useState(false);
  const [deletingAgent, setDeletingAgent] = useState(false);
  const [savingWorkflow, setSavingWorkflow] = useState(false);
  const [deletingWorkflow, setDeletingWorkflow] = useState(false);
  const [savingEval, setSavingEval] = useState(false);
  const [deletingEval, setDeletingEval] = useState(false);

  const [prompt, setPrompt] = useState("");
  const [streamMode, setStreamMode] = useState(true);
  const [requireApproval, setRequireApproval] = useState(false);
  const [chatError, setChatError] = useState("");
  const [createError, setCreateError] = useState("");
  const [agentManageError, setAgentManageError] = useState("");
  const [workflowError, setWorkflowError] = useState("");
  const [evalError, setEvalError] = useState("");
  const [approvalReason, setApprovalReason] = useState("");
  const [approvalBusy, setApprovalBusy] = useState(false);
  const [createAgentName, setCreateAgentName] = useState(DEFAULT_AGENT_NAME);
  const [createAgentModel, setCreateAgentModel] = useState(DEFAULT_AGENT_MODEL);
  const [createAgentSystemPrompt, setCreateAgentSystemPrompt] = useState(DEFAULT_SYSTEM_PROMPT);
  const [createAgentRuntimeKind, setCreateAgentRuntimeKind] = useState<"langgraph" | "goose">("langgraph");

  const threadIdsRef = useRef<Record<string, string>>({});
  const pendingRequestRef = useRef<Record<string, InvokePayload | null>>({});
  const streamAbortRef = useRef<AbortController | null>(null);

  const selectedAgent = agents.find((agent) => agent.name === selectedAgentName) ?? null;
  const selectedWorkflow = workflowCreateMode ? null : workflows.find((item) => item.name === selectedWorkflowName) ?? null;
  const selectedEval = evalCreateMode ? null : evals.find((item) => item.name === selectedEvalName) ?? null;
  const selectedRuntimeKind = selectedAgentDetail?.runtime_kind ?? "langgraph";
  const approvalSupported = selectedRuntimeKind !== "goose";

  const messages = selectedAgentName ? messagesByAgent[selectedAgentName] ?? [] : [];
  const activity = selectedAgentName ? activityByAgent[selectedAgentName] ?? [] : [];
  const summary = selectedAgentName ? summaryByAgent[selectedAgentName] ?? null : null;
  const logs = selectedAgentName ? logsByAgent[selectedAgentName] ?? "" : "";

  useEffect(() => {
    localStorage.setItem(TOKEN_STORAGE_KEY, token);
  }, [token]);

  useEffect(() => {
    localStorage.setItem(NAMESPACE_STORAGE_KEY, namespace);
  }, [namespace]);

  useEffect(() => {
    if (!approvalSupported && requireApproval) {
      setRequireApproval(false);
    }
  }, [approvalSupported, requireApproval]);

  function setMessagesForAgent(agentName: string, updater: (current: UiMessage[]) => UiMessage[]) {
    setMessagesByAgent((current) => ({
      ...current,
      [agentName]: updater(current[agentName] ?? []),
    }));
  }

  function setActivityForAgent(agentName: string, updater: (current: UiActivity[]) => UiActivity[]) {
    setActivityByAgent((current) => ({
      ...current,
      [agentName]: updater(current[agentName] ?? []),
    }));
  }

  function setSummaryForAgent(
    agentName: string,
    updater: (current: InvocationSummary | null) => InvocationSummary | null,
  ) {
    setSummaryByAgent((current) => ({
      ...current,
      [agentName]: updater(current[agentName] ?? null),
    }));
  }

  function setLogsForAgent(agentName: string, value: string) {
    setLogsByAgent((current) => ({
      ...current,
      [agentName]: value,
    }));
  }

  function removeAgentState(agentName: string) {
    setMessagesByAgent((current) => {
      const next = { ...current };
      delete next[agentName];
      return next;
    });
    setActivityByAgent((current) => {
      const next = { ...current };
      delete next[agentName];
      return next;
    });
    setSummaryByAgent((current) => {
      const next = { ...current };
      delete next[agentName];
      return next;
    });
    setLogsByAgent((current) => {
      const next = { ...current };
      delete next[agentName];
      return next;
    });
    delete threadIdsRef.current[agentName];
    delete pendingRequestRef.current[agentName];
  }

  async function refreshHealth(silent = false) {
    try {
      const nextHealth = await fetchGatewayHealth();
      setHealth(nextHealth);
      setGatewayError("");
      return nextHealth;
    } catch (nextError) {
      const message = nextError instanceof Error ? nextError.message : String(nextError);
      setGatewayError(message);
      if (!silent) {
        setHealth(null);
      }
      return null;
    }
  }

  async function refreshWorkspaceData(options?: { silent?: boolean }) {
    const silent = options?.silent ?? false;
    if (!token.trim()) {
      setAgents([]);
      setPolicies([]);
      setWorkflows([]);
      setEvals([]);
      setSelectedAgentDetail(null);
      return;
    }

    if (!silent) {
      setCatalogLoading(true);
      setWorkspaceError("");
    }

    try {
      const [nextAgents, nextPolicies, nextWorkflows, nextEvals] = await Promise.all([
        listAgents(token, namespace),
        listPolicies(token, namespace),
        listWorkflows(token, namespace),
        listEvals(token, namespace),
      ]);

      setAgents(nextAgents);
      setPolicies(nextPolicies);
      setWorkflows(nextWorkflows);
      setEvals(nextEvals);

      if (!agentCreateMode) {
        const nextSelected = nextAgents.some((item) => item.name === selectedAgentName)
          ? selectedAgentName
          : nextAgents[0]?.name ?? "";
        setSelectedAgentName(nextSelected);
      }
      if (!workflowCreateMode) {
        const nextSelected = nextWorkflows.some((item) => item.name === selectedWorkflowName)
          ? selectedWorkflowName
          : nextWorkflows[0]?.name ?? "";
        setSelectedWorkflowName(nextSelected);
      }
      if (!evalCreateMode) {
        const nextSelected = nextEvals.some((item) => item.name === selectedEvalName)
          ? selectedEvalName
          : nextEvals[0]?.name ?? "";
        setSelectedEvalName(nextSelected);
      }
    } catch (nextError) {
      if (!silent) {
        setWorkspaceError(nextError instanceof Error ? nextError.message : String(nextError));
      }
    } finally {
      if (!silent) {
        setCatalogLoading(false);
      }
    }
  }

  useEffect(() => {
    void refreshHealth();
    const timer = window.setInterval(() => {
      void refreshHealth(true);
    }, 15000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!token.trim()) {
      setAgents([]);
      setPolicies([]);
      setWorkflows([]);
      setEvals([]);
      setSelectedAgentDetail(null);
      return;
    }

    void refreshWorkspaceData({ silent: false });
    const timer = window.setInterval(() => {
      void refreshWorkspaceData({ silent: true });
    }, 10000);
    return () => window.clearInterval(timer);
  }, [token, namespace, selectedAgentName, selectedWorkflowName, selectedEvalName, agentCreateMode, workflowCreateMode, evalCreateMode]);

  useEffect(() => {
    if (activeView === "agents" && !agentCreateMode && !selectedAgentName && agents.length > 0) {
      setSelectedAgentName(agents[0].name);
    }
    if (activeView === "workflows" && !workflowCreateMode && !selectedWorkflowName && workflows.length > 0) {
      setSelectedWorkflowName(workflows[0].name);
    }
    if (activeView === "evals" && !evalCreateMode && !selectedEvalName && evals.length > 0) {
      setSelectedEvalName(evals[0].name);
    }
  }, [activeView, agents, workflows, evals, agentCreateMode, workflowCreateMode, evalCreateMode, selectedAgentName, selectedWorkflowName, selectedEvalName]);

  useEffect(() => {
    if (!token.trim() || !selectedAgentName || agentCreateMode) {
      setSelectedAgentDetail(null);
      return;
    }

    let cancelled = false;
    void fetchAgent(token, namespace, selectedAgentName)
      .then((detail) => {
        if (!cancelled) {
          setSelectedAgentDetail(detail);
          setAgentManageError("");
        }
      })
      .catch((nextError) => {
        if (!cancelled) {
          setAgentManageError(nextError instanceof Error ? nextError.message : String(nextError));
          setSelectedAgentDetail(null);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [token, namespace, selectedAgentName, agentCreateMode]);

  function pushActivity(agentName: string, event: string, payload: Record<string, unknown>) {
    if (event === "response.delta") {
      return;
    }
    setActivityForAgent(agentName, (current) => [{ id: createId(), event, payload }, ...current].slice(0, 24));
  }

  function setPendingAssistantContent(
    agentName: string,
    messageId: string,
    nextContent: string,
    status: UiMessage["status"],
  ) {
    setMessagesForAgent(agentName, (current) =>
      current.map((message) =>
        message.id === messageId
          ? {
              ...message,
              content: nextContent,
              status,
            }
          : message,
      ),
    );
  }

  function updateSummary(agentName: string, threadId: string, payload: Record<string, unknown>) {
    setSummaryForAgent(agentName, () => ({
      threadId,
      status: String(payload.status ?? "completed"),
      policyName: (payload.policy_name as string | null | undefined) ?? null,
      toolName: (payload.tool_name as string | null | undefined) ?? null,
      toolResult: (payload.tool_result as Record<string, unknown> | null | undefined) ?? null,
      sandboxSession: (payload.sandbox_session as Record<string, unknown> | null | undefined) ?? null,
      approvalName: (payload.approval_name as string | null | undefined) ?? null,
      retryAfterSeconds: (payload.retry_after_seconds as number | null | undefined) ?? null,
      warnings: Array.isArray(payload.warnings) ? payload.warnings.map(String) : [],
    }));
  }

  async function handleConnect() {
    setIsConnecting(true);
    setWorkspaceError("");
    await refreshHealth();
    await refreshWorkspaceData({ silent: false });
    setIsConnecting(false);
  }

  async function handleCreateAgent() {
    if (!token.trim()) {
      setCreateError("Enter the gateway token before creating an agent.");
      return;
    }

    setIsCreatingAgent(true);
    setCreateError("");
    try {
      const createdAgent = await createAgent(token, namespace, {
        name: createAgentName.trim(),
        model: createAgentModel.trim(),
        system_prompt: createAgentSystemPrompt.trim(),
        runtime_kind: createAgentRuntimeKind,
      });
      setAgentCreateMode(false);
      setSelectedAgentName(createdAgent.name);
      setMessagesForAgent(createdAgent.name, (current) =>
        current.length > 0
          ? current
          : [
              {
                id: createId(),
                role: "system",
                content: "Agent created. Wait until the runtime status turns running, then start chatting.",
                status: "complete",
              },
            ],
      );
      await refreshWorkspaceData({ silent: false });
      setWorkspaceError("Agent created. Provisioning may take a few seconds before the runtime is ready.");
    } catch (nextError) {
      setCreateError(nextError instanceof Error ? nextError.message : String(nextError));
    } finally {
      setIsCreatingAgent(false);
    }
  }

  async function handleSaveAgent(payload: UpdateAgentPayload) {
    if (!token.trim() || !selectedAgentName) {
      return;
    }

    setSavingAgent(true);
    setAgentManageError("");
    try {
      const updated = await updateAgent(token, namespace, selectedAgentName, payload);
      setSelectedAgentDetail(updated);
      await refreshWorkspaceData({ silent: true });
    } catch (nextError) {
      setAgentManageError(nextError instanceof Error ? nextError.message : String(nextError));
    } finally {
      setSavingAgent(false);
    }
  }

  async function handleDeleteAgent() {
    if (!token.trim() || !selectedAgentName) {
      return;
    }

    const agentName = selectedAgentName;
    setDeletingAgent(true);
    setAgentManageError("");
    try {
      await deleteAgent(token, namespace, agentName);
      removeAgentState(agentName);
      setSelectedAgentName("");
      setSelectedAgentDetail(null);
      setAgentCreateMode(agents.length <= 1);
      await refreshWorkspaceData({ silent: false });
    } catch (nextError) {
      setAgentManageError(nextError instanceof Error ? nextError.message : String(nextError));
    } finally {
      setDeletingAgent(false);
    }
  }

  async function handleCreateWorkflow(payload: WorkflowPayload) {
    if (!token.trim()) {
      return;
    }

    setSavingWorkflow(true);
    setWorkflowError("");
    try {
      const created = await createWorkflow(token, namespace, payload);
      setWorkflowCreateMode(false);
      setSelectedWorkflowName(created.name);
      await refreshWorkspaceData({ silent: false });
      setWorkspaceError("Workflow created. The operator will queue it immediately.");
    } catch (nextError) {
      setWorkflowError(nextError instanceof Error ? nextError.message : String(nextError));
    } finally {
      setSavingWorkflow(false);
    }
  }

  async function handleUpdateWorkflow(name: string, payload: WorkflowUpdatePayload) {
    if (!token.trim()) {
      return;
    }

    setSavingWorkflow(true);
    setWorkflowError("");
    try {
      await updateWorkflow(token, namespace, name, payload);
      await refreshWorkspaceData({ silent: false });
    } catch (nextError) {
      setWorkflowError(nextError instanceof Error ? nextError.message : String(nextError));
    } finally {
      setSavingWorkflow(false);
    }
  }

  async function handleDeleteWorkflow(name: string) {
    if (!token.trim()) {
      return;
    }

    setDeletingWorkflow(true);
    setWorkflowError("");
    try {
      await deleteWorkflow(token, namespace, name);
      setSelectedWorkflowName("");
      setWorkflowCreateMode(workflows.length <= 1);
      await refreshWorkspaceData({ silent: false });
    } catch (nextError) {
      setWorkflowError(nextError instanceof Error ? nextError.message : String(nextError));
    } finally {
      setDeletingWorkflow(false);
    }
  }

  async function handleCreateEval(payload: EvalPayload) {
    if (!token.trim()) {
      return;
    }

    setSavingEval(true);
    setEvalError("");
    try {
      const created = await createEval(token, namespace, payload);
      setEvalCreateMode(false);
      setSelectedEvalName(created.name);
      await refreshWorkspaceData({ silent: false });
      setWorkspaceError("Evaluation created. The operator will queue it immediately.");
    } catch (nextError) {
      setEvalError(nextError instanceof Error ? nextError.message : String(nextError));
    } finally {
      setSavingEval(false);
    }
  }

  async function handleUpdateEval(name: string, payload: EvalUpdatePayload) {
    if (!token.trim()) {
      return;
    }

    setSavingEval(true);
    setEvalError("");
    try {
      await updateEval(token, namespace, name, payload);
      await refreshWorkspaceData({ silent: false });
    } catch (nextError) {
      setEvalError(nextError instanceof Error ? nextError.message : String(nextError));
    } finally {
      setSavingEval(false);
    }
  }

  async function handleDeleteEval(name: string) {
    if (!token.trim()) {
      return;
    }

    setDeletingEval(true);
    setEvalError("");
    try {
      await deleteEval(token, namespace, name);
      setSelectedEvalName("");
      setEvalCreateMode(evals.length <= 1);
      await refreshWorkspaceData({ silent: false });
    } catch (nextError) {
      setEvalError(nextError instanceof Error ? nextError.message : String(nextError));
    } finally {
      setDeletingEval(false);
    }
  }

  async function handleLoadLogs() {
    if (!token.trim() || !selectedAgentName) {
      return;
    }
    setLogsLoading(true);
    setWorkspaceError("");
    try {
      const result = await fetchAgentLogs(token, namespace, selectedAgentName);
      setLogsForAgent(selectedAgentName, result.logs);
    } catch (nextError) {
      setWorkspaceError(nextError instanceof Error ? nextError.message : String(nextError));
    } finally {
      setLogsLoading(false);
    }
  }

  async function runInvocation({
    agentName,
    payload,
    userPrompt,
    appendUserMessage = true,
    systemNotice,
  }: InvokeExecutionOptions) {
    const requestId = createId();
    const assistantMessageId = createId();

    setChatError("");
    setWorkspaceError("");
    setLogsForAgent(agentName, "");
    setActivityForAgent(agentName, () => []);
    setMessagesForAgent(agentName, (current) => {
      const next = [...current];
      if (systemNotice) {
        next.push({
          id: createId(),
          role: "system",
          content: systemNotice,
          status: "complete",
        });
      }
      if (appendUserMessage && userPrompt?.trim()) {
        next.push({
          id: createId(),
          role: "user",
          content: userPrompt.trim(),
          status: "complete",
        });
      }
      next.push({ id: assistantMessageId, role: "assistant", content: "", status: "streaming" });
      return next;
    });
    setIsSending(true);

    if (!streamMode) {
      try {
        const result = await invokeAgent(token, namespace, agentName, payload, requestId);
        threadIdsRef.current[agentName] = result.thread_id;
        pendingRequestRef.current[agentName] =
          result.status === "approval_pending" ? { ...payload, thread_id: result.thread_id } : null;
        updateSummary(agentName, result.thread_id, result as unknown as Record<string, unknown>);
        setPendingAssistantContent(
          agentName,
          assistantMessageId,
          result.response || (result.status === "approval_pending" ? "Approval pending. Re-submit after approval." : "No response body returned."),
          result.status === "blocked" ? "error" : "complete",
        );
      } catch (nextError) {
        const message = nextError instanceof Error ? nextError.message : String(nextError);
        pendingRequestRef.current[agentName] = null;
        setPendingAssistantContent(agentName, assistantMessageId, message, "error");
        setChatError(message);
      } finally {
        setIsSending(false);
      }
      return;
    }

    const abortController = new AbortController();
    streamAbortRef.current?.abort();
    streamAbortRef.current = abortController;

    try {
      await streamAgentInvoke({
        signal: abortController.signal,
        token,
        namespace,
        agentName,
        payload,
        requestId,
        onEvent: ({ event, payload: eventPayload }) => {
          pushActivity(agentName, event, eventPayload);

          if (event === "response.delta") {
            const delta = String(eventPayload.delta ?? "");
            setMessagesForAgent(agentName, (current) =>
              current.map((message) =>
                message.id === assistantMessageId
                  ? {
                      ...message,
                      content: `${message.content}${delta}`,
                      status: "streaming",
                    }
                  : message,
              ),
            );
            return;
          }

          if (event === "response.completed") {
            const nextThreadId = String(eventPayload.thread_id ?? threadIdsRef.current[agentName] ?? createId());
            const nextStatus = String(eventPayload.status ?? "completed");
            threadIdsRef.current[agentName] = nextThreadId;
            pendingRequestRef.current[agentName] =
              nextStatus === "approval_pending" ? { ...payload, thread_id: nextThreadId } : null;
            updateSummary(agentName, nextThreadId, eventPayload);
            setMessagesForAgent(agentName, (current) =>
              current.map((message) =>
                message.id === assistantMessageId
                  ? {
                      ...message,
                      content:
                        message.content ||
                        (nextStatus === "approval_pending"
                          ? "Approval pending. Re-submit after approval."
                          : "Invocation completed."),
                      status: nextStatus === "blocked" ? "error" : "complete",
                    }
                  : message,
              ),
            );
            return;
          }

          if ((event === "response.error" || event === "message") && eventPayload.error) {
            const message = String(eventPayload.error);
            pendingRequestRef.current[agentName] = null;
            setPendingAssistantContent(agentName, assistantMessageId, message, "error");
            setChatError(message);
          }
        },
        onError: (nextError) => {
          pendingRequestRef.current[agentName] = null;
          setPendingAssistantContent(agentName, assistantMessageId, nextError.message, "error");
          setChatError(nextError.message);
        },
        onClose: () => undefined,
      });
    } catch (nextError) {
      if (!abortController.signal.aborted) {
        const message = nextError instanceof Error ? nextError.message : String(nextError);
        pendingRequestRef.current[agentName] = null;
        setPendingAssistantContent(agentName, assistantMessageId, message, "error");
        setChatError(message);
      }
    } finally {
      setIsSending(false);
      streamAbortRef.current = null;
    }
  }

  async function handleSubmit() {
    if (!selectedAgentName || !prompt.trim() || !token.trim()) {
      return;
    }

    const agentName = selectedAgentName;
    const nextPrompt = prompt.trim();
    const payload: InvokePayload = {
      prompt: nextPrompt,
      thread_id: threadIdsRef.current[agentName],
      require_approval: requireApproval,
      approval_action: requireApproval ? `Approve UI request for ${agentName}` : undefined,
    };

    setPrompt("");
    await runInvocation({
      agentName,
      payload,
      userPrompt: nextPrompt,
      appendUserMessage: true,
    });
  }

  async function handleAgentApprovalDecision(decision: "approved" | "denied") {
    if (!token.trim() || !selectedAgentName || !summary?.approvalName) {
      return;
    }

    const currentAgentName = selectedAgentName;
    const approvalName = summary.approvalName;
    setApprovalBusy(true);
    setWorkspaceError("");
    try {
      await decideApproval(token, namespace, approvalName, decision, approvalReason);
      if (decision === "denied") {
        pendingRequestRef.current[currentAgentName] = null;
        setSummaryForAgent(currentAgentName, (current) =>
          current
            ? {
                ...current,
                status: "blocked",
              }
            : current,
        );
        setMessagesForAgent(currentAgentName, (current) => [
          ...current,
          {
            id: createId(),
            role: "system",
            content: approvalReason.trim()
              ? `Approval ${approvalName} was denied. Reason: ${approvalReason.trim()}`
              : `Approval ${approvalName} was denied.`,
            status: "complete",
          },
        ]);
      } else {
        const pendingPayload = pendingRequestRef.current[currentAgentName];
        if (!pendingPayload) {
          setSummaryForAgent(currentAgentName, (current) =>
            current
              ? {
                  ...current,
                  status: "approved",
                }
              : current,
          );
        } else {
          await runInvocation({
            agentName: currentAgentName,
            payload: {
              ...pendingPayload,
              thread_id: threadIdsRef.current[currentAgentName] ?? pendingPayload.thread_id,
            },
            appendUserMessage: false,
            systemNotice: `Approval ${approvalName} granted. Retrying the pending request.`,
          });
        }
      }
      setApprovalReason("");
    } catch (nextError) {
      setWorkspaceError(nextError instanceof Error ? nextError.message : String(nextError));
    } finally {
      setApprovalBusy(false);
    }
  }

  async function handleWorkflowApprovalDecision(decision: "approved" | "denied") {
    const approvalName = typeof selectedWorkflow?.pending_approval?.name === "string" ? selectedWorkflow.pending_approval.name : "";
    if (!token.trim() || !approvalName) {
      return;
    }

    setApprovalBusy(true);
    setWorkspaceError("");
    try {
      await decideApproval(token, namespace, approvalName, decision, approvalReason);
      setApprovalReason("");
      await refreshWorkspaceData({ silent: false });
    } catch (nextError) {
      setWorkspaceError(nextError instanceof Error ? nextError.message : String(nextError));
    } finally {
      setApprovalBusy(false);
    }
  }

  function handleCreateNew() {
    setWorkspaceError("");
    setCreateError("");
    setAgentManageError("");
    setWorkflowError("");
    setEvalError("");
    if (activeView === "agents") {
      setAgentCreateMode(true);
      setSelectedAgentName("");
      return;
    }
    if (activeView === "workflows") {
      setWorkflowCreateMode(true);
      setSelectedWorkflowName("");
      return;
    }
    setEvalCreateMode(true);
    setSelectedEvalName("");
  }

  function handleSelectResource(resourceName: string) {
    if (activeView === "agents") {
      setAgentCreateMode(false);
      setSelectedAgentName(resourceName);
      return;
    }
    if (activeView === "workflows") {
      setWorkflowCreateMode(false);
      setSelectedWorkflowName(resourceName);
      return;
    }
    setEvalCreateMode(false);
    setSelectedEvalName(resourceName);
  }

  const sidebarCounts: Record<WorkspaceView, number> = {
    agents: agents.length,
    workflows: workflows.length,
    evals: evals.length,
  };

  const sidebarItems: SidebarResourceItem[] =
    activeView === "agents"
      ? agents.map((agent) => ({
          id: agent.name,
          title: agent.name,
          subtitle: agent.model,
          status: agent.status,
          note: agent.namespace,
        }))
      : activeView === "workflows"
        ? workflows.map((workflow) => ({
            id: workflow.name,
            title: workflow.name,
            subtitle: workflow.description || `${workflow.steps.length} step${workflow.steps.length === 1 ? "" : "s"}`,
            status: workflow.phase,
            note: workflow.current_step ? `Current step: ${workflow.current_step}` : `${workflow.steps.length} steps`,
          }))
        : evals.map((evalResource) => ({
            id: evalResource.name,
            title: evalResource.name,
            subtitle: evalResource.agent_ref,
            status: evalResource.phase,
            note: `${evalResource.test_suite.length} case${evalResource.test_suite.length === 1 ? "" : "s"}`,
          }));

  const sidebarSelectedId =
    activeView === "agents" ? selectedAgentName : activeView === "workflows" ? selectedWorkflowName : selectedEvalName;

  const emptySidebarMessage = !token.trim()
    ? "Add a bearer token and click Connect."
    : activeView === "agents"
      ? "No agents yet. Click + to create one."
      : activeView === "workflows"
        ? "No workflows yet. Click + to create one."
        : "No evaluations yet. Click + to create one.";

  const gatewayStatus = gatewayError ? "offline" : health?.status ?? "loading";
  const heroTitle =
    activeView === "agents"
      ? selectedAgent
        ? `${selectedAgent.name} is ready for chat and management.`
        : agentCreateMode
          ? "Create and provision a new agent."
          : "Connect, create, and manage your agents."
      : activeView === "workflows"
        ? selectedWorkflow
          ? `${selectedWorkflow.name} workflow orchestration.`
          : workflowCreateMode || workflows.length === 0
            ? "Create a workflow and let the operator queue it."
            : "Select a workflow to inspect it."
        : selectedEval
          ? `${selectedEval.name} evaluation suite.`
          : evalCreateMode || evals.length === 0
            ? "Create an evaluation suite and let the operator run it."
            : "Select an evaluation to inspect it.";
  const selectedResourceStatus =
    activeView === "agents"
      ? selectedAgent?.status ?? (agentCreateMode ? "draft" : "none")
      : activeView === "workflows"
        ? selectedWorkflow?.phase ?? (workflowCreateMode ? "draft" : "none")
        : selectedEval?.phase ?? (evalCreateMode ? "draft" : "none");

  const chatEmptyMessage = selectedAgentName
    ? "Start a conversation with this agent. Streaming is enabled by default for faster feedback."
    : "Choose an agent from the sidebar or create a new one.";

  const selectedWorkflowApprovalName =
    typeof selectedWorkflow?.pending_approval?.name === "string" ? selectedWorkflow.pending_approval.name : undefined;

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand-block">
          <span className="brand-mark">
            <LayoutPanelTop size={18} />
          </span>
          <div>
            <p className="eyebrow">Kubeminionagents</p>
            <h1>Agent Sandbox Console</h1>
          </div>
        </div>

        <div className="toolbar-card">
          <label>
            <span>Namespace</span>
            <input value={namespace} onChange={(event) => setNamespace(event.target.value)} />
          </label>
          <label className="token-field">
            <span>API Token</span>
            <input
              type="password"
              placeholder="Bearer token"
              value={token}
              onChange={(event) => setToken(event.target.value)}
            />
          </label>
          <button className="secondary-button" type="button" onClick={() => void handleConnect()} disabled={isConnecting}>
            <Shield size={16} />
            <span>{isConnecting ? "Connecting" : "Connect"}</span>
          </button>
        </div>
      </header>

      <main className="workspace-grid">
        <WorkspaceSidebar
          activeView={activeView}
          counts={sidebarCounts}
          items={sidebarItems}
          selectedId={sidebarSelectedId}
          loading={catalogLoading}
          emptyMessage={emptySidebarMessage}
          onViewChange={setActiveView}
          onRefresh={() => void refreshWorkspaceData({ silent: false })}
          onSelect={handleSelectResource}
          onCreateNew={handleCreateNew}
        />

        <div className="center-column">
          <section className="hero-panel">
            <div>
              <p className="eyebrow">Workspace Status</p>
              <h2>{heroTitle}</h2>
            </div>
            <div className="hero-stats">
              <div className="hero-stat">
                <span>Gateway</span>
                <strong>{gatewayStatus}</strong>
              </div>
              <div className="hero-stat">
                <span>Auth</span>
                <strong>{health?.auth_mode ?? "unknown"}</strong>
              </div>
              <div className="hero-stat">
                <span>View</span>
                <strong>{activeView}</strong>
              </div>
              <div className="hero-stat">
                <span>Selected</span>
                <strong>{selectedResourceStatus}</strong>
              </div>
            </div>
          </section>

          {!token.trim() ? (
            <section className="panel panel-setup">
              <div className="panel-header panel-header-chat">
                <div>
                  <p className="eyebrow">Connect The Workspace</p>
                  <h2>Enter the bearer token and load your control plane</h2>
                </div>
                <span className="mode-pill sync">traditional flow</span>
              </div>
              <p className="setup-lead">
                This UI talks to the API gateway only. Connect once, then manage agents, workflows, evaluations, approvals, and chat from one place.
              </p>
              {workspaceError ? <p className="error-banner">{workspaceError}</p> : null}
            </section>
          ) : activeView === "agents" ? (
            <>
              {agentCreateMode || (!selectedAgentName && agents.length === 0) ? (
                <CreateAgentPanel
                  name={createAgentName}
                  model={createAgentModel}
                  systemPrompt={createAgentSystemPrompt}
                  runtimeKind={createAgentRuntimeKind}
                  isCreating={isCreatingAgent}
                  error={createError}
                  onNameChange={setCreateAgentName}
                  onModelChange={setCreateAgentModel}
                  onSystemPromptChange={setCreateAgentSystemPrompt}
                  onRuntimeKindChange={setCreateAgentRuntimeKind}
                  onCreate={() => void handleCreateAgent()}
                />
              ) : selectedAgentDetail ? (
                <AgentManagementPanel
                  agent={selectedAgentDetail}
                  policies={policies}
                  isSaving={savingAgent}
                  isDeleting={deletingAgent}
                  error={agentManageError}
                  onSave={(payload) => void handleSaveAgent(payload)}
                  onDelete={() => void handleDeleteAgent()}
                />
              ) : (
                <section className="panel panel-setup">
                  <p className="setup-lead">Loading the selected agent settings...</p>
                </section>
              )}

              {!agentCreateMode && selectedAgentName ? (
                <ChatWorkbench
                  agentName={selectedAgentName}
                  prompt={prompt}
                  messages={messages}
                  isSending={isSending}
                  streamMode={streamMode}
                  requireApproval={requireApproval}
                  approvalSupported={approvalSupported}
                  emptyMessage={chatEmptyMessage}
                  error={chatError}
                  onPromptChange={setPrompt}
                  onToggleStreamMode={setStreamMode}
                  onToggleRequireApproval={setRequireApproval}
                  onSubmit={() => void handleSubmit()}
                />
              ) : null}
            </>
          ) : activeView === "workflows" ? (
            <WorkflowManager
              workflow={workflowCreateMode || workflows.length === 0 ? null : selectedWorkflow}
              agents={agents}
              isSaving={savingWorkflow}
              isDeleting={deletingWorkflow}
              error={workflowError}
              onCreate={(payload) => void handleCreateWorkflow(payload)}
              onUpdate={(name, payload) => void handleUpdateWorkflow(name, payload)}
              onDelete={(name) => void handleDeleteWorkflow(name)}
            />
          ) : (
            <EvalManager
              evalResource={evalCreateMode || evals.length === 0 ? null : selectedEval}
              agents={agents}
              isSaving={savingEval}
              isDeleting={deletingEval}
              error={evalError}
              onCreate={(payload) => void handleCreateEval(payload)}
              onUpdate={(name, payload) => void handleUpdateEval(name, payload)}
              onDelete={(name) => void handleDeleteEval(name)}
            />
          )}
        </div>

        {activeView === "agents" ? (
          <InspectorPanel
            health={health}
            gatewayError={gatewayError}
            workspaceError={workspaceError}
            selectedAgentName={selectedAgentName}
            namespace={namespace}
            tokenPresent={Boolean(token.trim())}
            logs={logs}
            logsLoading={logsLoading}
            activity={activity}
            summary={summary}
            approvalReason={approvalReason}
            approvalBusy={approvalBusy}
            onApprovalReasonChange={setApprovalReason}
            onApprove={() => void handleAgentApprovalDecision("approved")}
            onDeny={() => void handleAgentApprovalDecision("denied")}
            onLoadLogs={() => void handleLoadLogs()}
          />
        ) : activeView === "workflows" ? (
          <ResourceInspectorPanel
            title="Workflow Inspector"
            selectedName={selectedWorkflow?.name ?? ""}
            status={selectedWorkflow?.phase ?? (workflowCreateMode ? "draft" : "none")}
            summary={selectedWorkflow?.summary}
            spec={workflowSpecFromResource(selectedWorkflow)}
            details={workflowStatusFromResource(selectedWorkflow)}
            emptyMessage="Select a workflow or create a new one."
            pendingApprovalName={selectedWorkflowApprovalName}
            approvalReason={approvalReason}
            approvalBusy={approvalBusy}
            onApprovalReasonChange={setApprovalReason}
            onApprove={() => void handleWorkflowApprovalDecision("approved")}
            onDeny={() => void handleWorkflowApprovalDecision("denied")}
          />
        ) : (
          <ResourceInspectorPanel
            title="Evaluation Inspector"
            selectedName={selectedEval?.name ?? ""}
            status={selectedEval?.phase ?? (evalCreateMode ? "draft" : "none")}
            summary={selectedEval?.summary}
            spec={evalSpecFromResource(selectedEval)}
            details={evalStatusFromResource(selectedEval)}
            emptyMessage="Select an evaluation or create a new one."
            approvalReason={approvalReason}
            approvalBusy={approvalBusy}
            onApprovalReasonChange={setApprovalReason}
            onApprove={() => undefined}
            onDeny={() => undefined}
          />
        )}
      </main>

      <footer className="app-footer">
        <Sparkles size={16} />
        <span>Production console flow: connect to the gateway, create or edit agents, manage workflows and evaluations, approve queued operations, and chat with runtimes from the same UI.</span>
      </footer>
    </div>
  );
}
