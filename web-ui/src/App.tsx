import "@fontsource/space-grotesk/400.css";
import "@fontsource/space-grotesk/500.css";
import "@fontsource/space-grotesk/700.css";

import { useEffect, useRef, useState } from "react";
import { PanelRightOpen } from "lucide-react";
import { Toaster, toast } from "sonner";

import { AgentManagementPanel } from "./components/AgentManagementPanel";
import { AppSidebar, type SidebarResourceItem } from "./components/AppSidebar";
import { ChatWorkbench } from "./components/ChatWorkbench";
import { CreateAgentPanel } from "./components/CreateAgentPanel";
import { EvalManager } from "./components/EvalManager";
import { AgentInspectorDrawer, ResourceInspectorDrawer } from "./components/InspectorDrawer";
import { SkillsCatalogPanel } from "./components/SkillsCatalogPanel";
import { TopBar } from "./components/TopBar";
import { WorkflowManager } from "./components/WorkflowManager";
import { Button } from "@/components/ui/button";
import {
  buildOidcLoginUrl,
  buildSamlLoginUrl,
  buildInvocationSummary,
  createAgent,
  createEval,
  createWorkflow,
  decideApproval,
  deleteAgent,
  deleteEval,
  deleteWorkflow,
  discoverAgentPeers,
  fetchAgent,
  fetchAgentLogs,
  fetchAuthConfig,
  fetchCurrentUser,
  fetchGatewayHealth,
  invokeAgent,
  loginWithPassword,
  listAgents,
  listEvals,
  listPolicies,
  listWorkflows,
  logoutSession,
  refreshAuthSession,
  registerWithPassword,
  streamAgentInvoke,
  updateAgent,
  updateEval,
  updateWorkflow,
} from "./lib/api";
import { isValidK8sName, parseA2APeerRefsText } from "./lib/a2a";
import { buildGooseConfigFiles } from "./lib/gooseConfig";
import { parseMcpServersText, parseMcpSidecarsText } from "./lib/mcp";
import { buildSkillFiles } from "./lib/skills";
import type {
  AgentDetail,
  AgentDiscoveryPeer,
  AgentInfo,
  AuthConfig,
  AuthenticatedUser,
  EvalInfo,
  EvalPayload,
  EvalUpdatePayload,
  GatewayHealth,
  InvocationSummary,
  InvokePayload,
  SpecialistSubagentDraft,
  PolicyInfo,
  RuntimeKind,
  TextFileDraft,
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

type GooseChatSettings = {
  maxTurns: string;
  workingDirectory: string;
};

const DEFAULT_GOOSE_CHAT_SETTINGS: GooseChatSettings = {
  maxTurns: "",
  workingDirectory: "",
};

function createSpecialistSubagentDraft(initial?: Partial<SpecialistSubagentDraft>): SpecialistSubagentDraft {
  return {
    id: createId(),
    name: initial?.name ?? "",
    namespace: initial?.namespace ?? "",
    role: initial?.role ?? "",
    task: initial?.task ?? "",
    inputFilesText: initial?.inputFilesText ?? "",
    resultFilePath: initial?.resultFilePath ?? "",
    shareSandboxSession: initial?.shareSandboxSession ?? true,
    timeoutSeconds: initial?.timeoutSeconds ?? "",
  };
}

function createId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
}

function parseGooseMaxTurns(value: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) {
    return undefined;
  }
  if (!/^\d+$/.test(trimmed)) {
    throw new Error("Goose max turns must be a positive integer.");
  }

  const parsed = Number.parseInt(trimmed, 10);
  if (parsed < 1) {
    throw new Error("Goose max turns must be at least 1.");
  }

  return parsed;
}

function parseA2ATimeoutSeconds(value: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) {
    return undefined;
  }

  const parsed = Number.parseFloat(trimmed);
  if (!Number.isFinite(parsed) || parsed < 1) {
    throw new Error("A2A timeout seconds must be a number greater than or equal to 1.");
  }

  return parsed;
}

function parseSubagentTimeoutSeconds(value: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) {
    return undefined;
  }

  const parsed = Number.parseFloat(trimmed);
  if (!Number.isFinite(parsed) || parsed < 1) {
    throw new Error("Subagent timeout seconds must be a number greater than or equal to 1.");
  }

  return parsed;
}

function parseSubagentInputFiles(text: string): Array<{ path: string; purpose?: string }> {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [pathPart, ...purposeParts] = line.split("|");
      const path = pathPart?.trim() ?? "";
      if (!path) {
        throw new Error("Shared file entries must include a path.");
      }
      const purpose = purposeParts.join("|").trim();
      return purpose ? { path, purpose } : { path };
    });
}

function hasSpecialistTeamEntries(items: SpecialistSubagentDraft[]): boolean {
  return items.some(
    (item) =>
      item.name.trim() ||
      item.namespace.trim() ||
      item.role.trim() ||
      item.task.trim() ||
      item.inputFilesText.trim() ||
      item.resultFilePath.trim(),
  );
}

function normalizeGooseWorkingDirectory(value: string): string | undefined {
  const trimmed = value.trim();
  if (!trimmed) {
    return undefined;
  }
  if (/^(?:[A-Za-z]:[\\/]|\/)/.test(trimmed)) {
    throw new Error("Goose working directory must stay inside the mounted workspace. Use a relative subdirectory.");
  }

  const segments = trimmed
    .replace(/\\+/g, "/")
    .split("/")
    .filter((segment) => segment.length > 0);

  if (segments.length === 0) {
    return undefined;
  }
  if (segments.some((segment) => segment === "." || segment === "..")) {
    throw new Error("Goose working directory must use a workspace-relative path without '.' or '..' segments.");
  }

  return segments.join("/");
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

function resolveNamespaceForUser(user: AuthenticatedUser | null, currentNamespace: string): string {
  if (!user) {
    return currentNamespace || "default";
  }
  const namespaces = user.allowed_namespaces ?? [];
  if (namespaces.includes("*") || namespaces.includes(currentNamespace)) {
    return currentNamespace || "default";
  }
  return namespaces[0] ?? "default";
}

export default function App() {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_STORAGE_KEY) ?? "");
  const [namespace, setNamespace] = useState(() => localStorage.getItem(NAMESPACE_STORAGE_KEY) ?? "default");
  const [authConfig, setAuthConfig] = useState<AuthConfig | null>(null);
  const [currentUser, setCurrentUser] = useState<AuthenticatedUser | null>(null);
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
  const [gooseChatSettingsByAgent, setGooseChatSettingsByAgent] = useState<Record<string, GooseChatSettings>>({});

  const [catalogLoading, setCatalogLoading] = useState(false);
  const [logsLoading, setLogsLoading] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [authBusy, setAuthBusy] = useState(false);
  const [isCreatingAgent, setIsCreatingAgent] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [savingAgent, setSavingAgent] = useState(false);
  const [deletingAgent, setDeletingAgent] = useState(false);
  const [savingWorkflow, setSavingWorkflow] = useState(false);
  const [deletingWorkflow, setDeletingWorkflow] = useState(false);
  const [savingEval, setSavingEval] = useState(false);
  const [deletingEval, setDeletingEval] = useState(false);

  const [prompt, setPrompt] = useState("");
  const [authUsername, setAuthUsername] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [authEmail, setAuthEmail] = useState("");
  const [authDisplayName, setAuthDisplayName] = useState("");
  const [authPasswordConfirm, setAuthPasswordConfirm] = useState("");
  const [passwordProvider, setPasswordProvider] = useState<"local" | "ldap">("local");
  const [registerMode, setRegisterMode] = useState(false);
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
  const [createAgentMcpServersText, setCreateAgentMcpServersText] = useState("");
  const [createAgentMcpSidecarsText, setCreateAgentMcpSidecarsText] = useState("");
  const [createAgentA2AAllowedCallersText, setCreateAgentA2AAllowedCallersText] = useState("");
  const [createAgentSkillFileDrafts, setCreateAgentSkillFileDrafts] = useState<TextFileDraft[]>([]);
  const [createAgentGooseConfigFileDrafts, setCreateAgentGooseConfigFileDrafts] = useState<TextFileDraft[]>([]);
  const [a2aTargetAgent, setA2ATargetAgent] = useState("");
  const [a2aTargetNamespace, setA2ATargetNamespace] = useState("");
  const [a2aTimeoutSeconds, setA2ATimeoutSeconds] = useState("");
  const [specialistSubagents, setSpecialistSubagents] = useState<SpecialistSubagentDraft[]>([]);
  const [subagentStrategy, setSubagentStrategy] = useState<"sequential" | "parallel">("sequential");
  const [discoverablePeers, setDiscoverablePeers] = useState<AgentDiscoveryPeer[]>([]);
  const [discoveryLoading, setDiscoveryLoading] = useState(false);
  const [discoveryError, setDiscoveryError] = useState("");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(false);

  const threadIdsRef = useRef<Record<string, string>>({});
  const pendingRequestRef = useRef<Record<string, InvokePayload | null>>({});
  const streamAbortRef = useRef<AbortController | null>(null);

  const selectedAgent = agents.find((agent) => agent.name === selectedAgentName) ?? null;
  const selectedWorkflow = workflowCreateMode ? null : workflows.find((item) => item.name === selectedWorkflowName) ?? null;
  const selectedEval = evalCreateMode ? null : evals.find((item) => item.name === selectedEvalName) ?? null;
  const selectedRuntimeKind: RuntimeKind = selectedAgentDetail?.runtime_kind ?? "langgraph";
  const approvalSupported = selectedRuntimeKind !== "goose";

  const messages = selectedAgentName ? messagesByAgent[selectedAgentName] ?? [] : [];
  const activity = selectedAgentName ? activityByAgent[selectedAgentName] ?? [] : [];
  const summary = selectedAgentName ? summaryByAgent[selectedAgentName] ?? null : null;
  const logs = selectedAgentName ? logsByAgent[selectedAgentName] ?? "" : "";
  const specialistTeamConfigured = hasSpecialistTeamEntries(specialistSubagents);
  const selectedGooseChatSettings =
    selectedAgentName ? gooseChatSettingsByAgent[selectedAgentName] ?? DEFAULT_GOOSE_CHAT_SETTINGS : DEFAULT_GOOSE_CHAT_SETTINGS;
  const gooseSystemPromptPreview = selectedAgentDetail?.system_prompt.trim()
    ? selectedAgentDetail.system_prompt
    : "This agent is using the container-level Goose system prompt. Save an agent-specific prompt here when the runtime needs stronger guidance.";
  const canSubmitChat = Boolean(prompt.trim() || specialistSubagents.some((item) => item.task.trim()));

  useEffect(() => {
    localStorage.setItem(TOKEN_STORAGE_KEY, token);
  }, [token]);

  useEffect(() => {
    localStorage.setItem(NAMESPACE_STORAGE_KEY, namespace);
  }, [namespace]);

  useEffect(() => {
    let cancelled = false;

    async function initializeAuth() {
      const nextConfig = await refreshAuthConfiguration();
      if (cancelled || !nextConfig) {
        return;
      }

      if (token.trim()) {
        try {
          const refreshed = await refreshCurrentUserProfile(token);
          if (!cancelled) {
            if (!refreshed) {
              setCurrentUser(null);
            }
          }
        } catch {
          if (nextConfig.browser_auth_enabled) {
            const restored = await restoreBrowserSession({ silent: true });
            if (!restored && !cancelled) {
              setCurrentUser(null);
            }
          }
        }
      } else if (nextConfig.browser_auth_enabled) {
        await restoreBrowserSession({ silent: true });
      }

      const params = new URLSearchParams(window.location.search);
      if (params.has("auth")) {
        const authStatus = params.get("auth");
        if (authStatus === "success") {
          toast.success("Single sign-on session established.");
        } else if (authStatus === "error") {
          toast.error("Single sign-on failed.");
        }
        window.history.replaceState({}, document.title, window.location.pathname);
      }
    }

    void initializeAuth();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!approvalSupported && requireApproval) {
      setRequireApproval(false);
    }
  }, [approvalSupported, requireApproval]);

  useEffect(() => {
    const providers = authConfig?.password_providers ?? [];
    if (providers.length > 0 && !providers.includes(passwordProvider)) {
      setPasswordProvider(providers.includes("ldap") ? "ldap" : "local");
    }
    if (!authConfig?.registration_enabled && registerMode) {
      setRegisterMode(false);
    }
    if (authConfig && !authConfig.bootstrap_complete && authConfig.registration_enabled && !registerMode) {
      setRegisterMode(true);
    }
  }, [authConfig, passwordProvider, registerMode]);

  useEffect(() => {
    if (!currentUser) {
      return;
    }
    const nextNamespace = resolveNamespaceForUser(currentUser, namespace);
    if (nextNamespace !== namespace) {
      setNamespace(nextNamespace);
    }
  }, [currentUser, namespace]);

  useEffect(() => {
    setA2ATargetAgent("");
    setA2ATargetNamespace("");
    setA2ATimeoutSeconds("");
    setSpecialistSubagents([]);
    setSubagentStrategy("sequential");
  }, [selectedAgentName, selectedRuntimeKind]);

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

  function setGooseChatSettingsForAgent(agentName: string, updater: (current: GooseChatSettings) => GooseChatSettings) {
    setGooseChatSettingsByAgent((current) => ({
      ...current,
      [agentName]: updater(current[agentName] ?? DEFAULT_GOOSE_CHAT_SETTINGS),
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

  function updateSpecialistSubagentDraft(id: string, patch: Partial<SpecialistSubagentDraft>) {
    setSpecialistSubagents((current) => current.map((item) => (item.id === id ? { ...item, ...patch } : item)));
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

  function applyAuthenticatedUser(nextUser: AuthenticatedUser, nextToken: string) {
    setToken(nextToken);
    setCurrentUser(nextUser);
    const nextNamespace = resolveNamespaceForUser(nextUser, namespace);
    if (nextNamespace !== namespace) {
      setNamespace(nextNamespace);
    }
    return nextNamespace;
  }

  async function refreshCurrentUserProfile(activeToken = token) {
    if (!activeToken.trim()) {
      setCurrentUser(null);
      return null;
    }
    const nextUser = await fetchCurrentUser(activeToken);
    const nextNamespace = applyAuthenticatedUser(nextUser, activeToken);
    return { user: nextUser, namespace: nextNamespace };
  }

  async function restoreBrowserSession(options?: { silent?: boolean }) {
    const silent = options?.silent ?? false;
    try {
      const session = await refreshAuthSession();
      const nextNamespace = applyAuthenticatedUser(session.user, session.access_token);
      setAuthPassword("");
      return { token: session.access_token, namespace: nextNamespace, user: session.user };
    } catch (nextError) {
      if (!silent) {
        const message = nextError instanceof Error ? nextError.message : String(nextError);
        setWorkspaceError(message);
      }
      return null;
    }
  }

  async function refreshAuthConfiguration() {
    try {
      const nextConfig = await fetchAuthConfig();
      setAuthConfig(nextConfig);
      return nextConfig;
    } catch (nextError) {
      setAuthConfig(null);
      setWorkspaceError(nextError instanceof Error ? nextError.message : String(nextError));
      return null;
    }
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

  async function refreshWorkspaceData(options?: { silent?: boolean; token?: string; namespace?: string }) {
    const silent = options?.silent ?? false;
    const activeToken = options?.token ?? token;
    const activeNamespace = options?.namespace ?? namespace;
    if (!activeToken.trim()) {
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
        listAgents(activeToken, activeNamespace),
        listPolicies(activeToken, activeNamespace),
        listWorkflows(activeToken, activeNamespace),
        listEvals(activeToken, activeNamespace),
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

  useEffect(() => {
    if (!token.trim() || !selectedAgentName || agentCreateMode) {
      setDiscoverablePeers([]);
      setDiscoveryError("");
      setDiscoveryLoading(false);
      return;
    }

    let cancelled = false;
    setDiscoveryLoading(true);
    void discoverAgentPeers(token, namespace, selectedAgentName)
      .then((response) => {
        if (!cancelled) {
          setDiscoverablePeers(response.peers);
          setDiscoveryError("");
        }
      })
      .catch((nextError) => {
        if (!cancelled) {
          setDiscoverablePeers([]);
          setDiscoveryError(nextError instanceof Error ? nextError.message : String(nextError));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setDiscoveryLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [token, namespace, selectedAgentName, agentCreateMode, selectedAgentDetail?.policy_ref, agents]);

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

  function applyInvocationFailure(agentName: string, messageId: string, message: string) {
    pendingRequestRef.current[agentName] = null;
    setPendingAssistantContent(agentName, messageId, message, "error");
    setChatError(message);
  }

  function updateSummary(agentName: string, threadId: string, payload: unknown): InvocationSummary {
    const nextSummary = buildInvocationSummary(threadId, payload);
    setSummaryForAgent(agentName, () => nextSummary);
    return nextSummary;
  }

  async function handleConnect() {
    if (!token.trim()) {
      setWorkspaceError("Enter a bearer token or sign in with a managed account.");
      return;
    }
    setIsConnecting(true);
    setWorkspaceError("");
    try {
      await refreshHealth();
      const refreshed = await refreshCurrentUserProfile(token);
      const nextNamespace = refreshed?.namespace ?? namespace;
      await refreshWorkspaceData({ silent: false, token, namespace: nextNamespace });
    } catch (nextError) {
      setCurrentUser(null);
      setWorkspaceError(nextError instanceof Error ? nextError.message : String(nextError));
    } finally {
      setIsConnecting(false);
    }
  }

  async function handlePasswordAuth() {
    setAuthBusy(true);
    setWorkspaceError("");
    try {
      const wasRegistering = registerMode && passwordProvider === "local";
      const session = wasRegistering
          ? await registerWithPassword(authUsername, authPassword, authEmail, authDisplayName || authUsername)
          : await loginWithPassword(authUsername, authPassword, passwordProvider);
      const nextNamespace = applyAuthenticatedUser(session.user, session.access_token);
      setAuthPassword("");
      setAuthPasswordConfirm("");
      if (wasRegistering) {
        setRegisterMode(false);
        setAuthEmail("");
        setAuthDisplayName("");
      }
      await refreshHealth(true);
      await refreshWorkspaceData({ silent: false, token: session.access_token, namespace: nextNamespace });
      toast.success(wasRegistering ? "Account created." : "Signed in.");
    } catch (nextError) {
      const message = nextError instanceof Error ? nextError.message : String(nextError);
      setWorkspaceError(message);
      toast.error(message);
    } finally {
      setAuthBusy(false);
    }
  }

  async function handleLogout() {
    setAuthBusy(true);
    try {
      await logoutSession(token);
    } catch (nextError) {
      const message = nextError instanceof Error ? nextError.message : String(nextError);
      toast.error(message);
    } finally {
      setAuthBusy(false);
      setToken("");
      setCurrentUser(null);
      setAuthPassword("");
      setWorkspaceError("");
      setAgents([]);
      setPolicies([]);
      setWorkflows([]);
      setEvals([]);
      setSelectedAgentDetail(null);
    }
  }

  function handleOidcStart(providerId: string) {
    window.location.assign(buildOidcLoginUrl(providerId, window.location.pathname));
  }

  function handleSamlStart(providerId: string) {
    window.location.assign(buildSamlLoginUrl(providerId, window.location.pathname));
  }

  async function handleCreateAgent() {
    if (!token.trim()) {
      setCreateError("Enter the gateway token before creating an agent.");
      return;
    }

    setIsCreatingAgent(true);
    setCreateError("");
    try {
      const allowedCallers = parseA2APeerRefsText(createAgentA2AAllowedCallersText);
      const skillFiles = buildSkillFiles(createAgentSkillFileDrafts);
      const mcpServers = createAgentRuntimeKind === "langgraph" ? parseMcpServersText(createAgentMcpServersText) : [];
      const mcpSidecars = createAgentRuntimeKind === "langgraph" ? parseMcpSidecarsText(createAgentMcpSidecarsText) : [];
      const gooseConfigFiles =
        createAgentRuntimeKind === "goose" ? buildGooseConfigFiles(createAgentGooseConfigFileDrafts) : undefined;
      const createdAgent = await createAgent(token, namespace, {
        name: createAgentName.trim(),
        model: createAgentModel.trim(),
        system_prompt: createAgentSystemPrompt.trim(),
        runtime_kind: createAgentRuntimeKind,
        mcp_servers: mcpServers,
        mcp_sidecars: mcpSidecars,
        a2a_config: allowedCallers.length > 0 ? { allowed_callers: allowedCallers } : undefined,
        skills: Object.keys(skillFiles).length > 0 ? { files: skillFiles } : undefined,
        goose_config_files: gooseConfigFiles,
      });
      setAgentCreateMode(false);
      setCreateAgentMcpServersText("");
      setCreateAgentMcpSidecarsText("");
      setCreateAgentA2AAllowedCallersText("");
      setCreateAgentSkillFileDrafts([]);
      setCreateAgentGooseConfigFileDrafts([]);
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
      toast.success("Agent created", { description: "Provisioning may take a few seconds before the runtime is ready." });
    } catch (nextError) {
      const msg = nextError instanceof Error ? nextError.message : String(nextError);
      setCreateError(msg);
      toast.error("Failed to create agent", { description: msg });
    } finally {
      setIsCreatingAgent(false);
    }
  }

  async function handleSaveAgent(
    payload: UpdateAgentPayload,
    a2aAllowedCallersText: string,
    skillFiles: Record<string, string>,
    gooseConfigFiles: Record<string, unknown>,
  ) {
    if (!token.trim() || !selectedAgentName) {
      return;
    }

    setSavingAgent(true);
    setAgentManageError("");
    try {
      const allowedCallers = parseA2APeerRefsText(a2aAllowedCallersText);
      const nextPayload: UpdateAgentPayload = {
        ...payload,
        a2a_config: { allowed_callers: allowedCallers },
        skills: { files: skillFiles },
        goose_config_files: payload.runtime_kind === "goose" ? gooseConfigFiles : {},
      };
      const updated = await updateAgent(token, namespace, selectedAgentName, nextPayload);
      setSelectedAgentDetail(updated);
      await refreshWorkspaceData({ silent: true });
      toast.success("Agent saved");
    } catch (nextError) {
      const msg = nextError instanceof Error ? nextError.message : String(nextError);
      setAgentManageError(msg);
      toast.error("Failed to save agent", { description: msg });
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
      toast.success("Agent deleted");
    } catch (nextError) {
      const msg = nextError instanceof Error ? nextError.message : String(nextError);
      setAgentManageError(msg);
      toast.error("Failed to delete agent", { description: msg });
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
      toast.success("Workflow created");
    } catch (nextError) {
      const msg = nextError instanceof Error ? nextError.message : String(nextError);
      setWorkflowError(msg);
      toast.error("Failed to create workflow", { description: msg });
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
      toast.success("Workflow saved");
    } catch (nextError) {
      const msg = nextError instanceof Error ? nextError.message : String(nextError);
      setWorkflowError(msg);
      toast.error("Failed to save workflow", { description: msg });
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
      toast.success("Workflow deleted");
    } catch (nextError) {
      const msg = nextError instanceof Error ? nextError.message : String(nextError);
      setWorkflowError(msg);
      toast.error("Failed to delete workflow", { description: msg });
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
      toast.success("Evaluation created");
    } catch (nextError) {
      const msg = nextError instanceof Error ? nextError.message : String(nextError);
      setEvalError(msg);
      toast.error("Failed to create evaluation", { description: msg });
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
      toast.success("Evaluation saved");
    } catch (nextError) {
      const msg = nextError instanceof Error ? nextError.message : String(nextError);
      setEvalError(msg);
      toast.error("Failed to save evaluation", { description: msg });
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
      toast.success("Evaluation deleted");
    } catch (nextError) {
      const msg = nextError instanceof Error ? nextError.message : String(nextError);
      setEvalError(msg);
      toast.error("Failed to delete evaluation", { description: msg });
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
        const nextSummary = updateSummary(agentName, result.thread_id, result);
        threadIdsRef.current[agentName] = nextSummary.threadId;
        pendingRequestRef.current[agentName] =
          nextSummary.status === "approval_pending" ? { ...payload, thread_id: nextSummary.threadId } : null;
        setPendingAssistantContent(
          agentName,
          assistantMessageId,
          result.response || (nextSummary.status === "approval_pending" ? "Approval pending. Re-submit after approval." : "No response body returned."),
          nextSummary.status === "blocked" ? "error" : "complete",
        );
      } catch (nextError) {
        const message = nextError instanceof Error ? nextError.message : String(nextError);
        applyInvocationFailure(agentName, assistantMessageId, message);
      } finally {
        setIsSending(false);
      }
      return;
    }

    const abortController = new AbortController();
    streamAbortRef.current?.abort();
    streamAbortRef.current = abortController;
    let streamErrorHandled = false;

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

          /* ---- Tool-call visibility in the chat timeline ---- */
          const TOOL_NODES = new Set(["sandbox_tool", "mcp_tool", "retrieval", "output_guard"]);

          if (event === "graph.node") {
            const nodeName = String(eventPayload.node ?? "");
            const nodeStatus = String(eventPayload.status ?? "");
            if (TOOL_NODES.has(nodeName)) {
              if (nodeStatus === "started") {
                const toolMsgId = `tool-${nodeName}-${createId()}`;
                setMessagesForAgent(agentName, (current) => {
                  // insert tool message just before the trailing assistant message
                  const idx = current.findIndex((m) => m.id === assistantMessageId);
                  const toolMsg: UiMessage = {
                    id: toolMsgId,
                    role: "tool",
                    content: "",
                    status: "streaming",
                    toolName: nodeName.replace(/_/g, " "),
                    toolNode: nodeName,
                  };
                  if (idx >= 0) {
                    const next = [...current];
                    next.splice(idx, 0, toolMsg);
                    return next;
                  }
                  return [...current, toolMsg];
                });
              } else if (nodeStatus === "completed" || nodeStatus === "failed") {
                setMessagesForAgent(agentName, (current) =>
                  current.map((m) =>
                    m.role === "tool" && m.toolNode === nodeName && m.status === "streaming"
                      ? {
                          ...m,
                          status: nodeStatus === "failed" ? "error" : "complete",
                          content:
                            nodeStatus === "failed"
                              ? String(eventPayload.error ?? "Tool call failed")
                              : m.content || "Completed",
                        }
                      : m,
                  ),
                );
              }
            }
            return;
          }

          if (event === "mcp.result") {
            const serverType = String(eventPayload.serverType ?? "");
            const toolName = String(eventPayload.toolName ?? "");
            const label = serverType ? `${serverType}/${toolName}` : toolName;
            // Update the most recent streaming mcp_tool message with details
            setMessagesForAgent(agentName, (current) =>
              current.map((m) =>
                m.role === "tool" && m.toolNode === "mcp_tool" && m.status === "streaming"
                  ? { ...m, toolName: label, content: `${label} → ${eventPayload.bytes ?? "?"} bytes` }
                  : m,
              ),
            );
            return;
          }

          if (event === "subagent.call") {
            const target = String(eventPayload.targetAgent ?? "subagent");
            const status = String(eventPayload.status ?? "");
            if (status === "started") {
              setMessagesForAgent(agentName, (current) => {
                const idx = current.findIndex((m) => m.id === assistantMessageId);
                const toolMsg: UiMessage = {
                  id: `tool-subagent-${createId()}`,
                  role: "tool",
                  content: "",
                  status: "streaming",
                  toolName: `subagent → ${target}`,
                  toolNode: "subagent",
                };
                if (idx >= 0) {
                  const next = [...current];
                  next.splice(idx, 0, toolMsg);
                  return next;
                }
                return [...current, toolMsg];
              });
            } else if (status === "completed" || status === "failed") {
              setMessagesForAgent(agentName, (current) =>
                current.map((m) =>
                  m.role === "tool" && m.toolNode === "subagent" && m.status === "streaming"
                    ? { ...m, status: status === "failed" ? "error" : "complete", content: m.content || "Completed" }
                    : m,
                ),
              );
            }
            return;
          }

          if (event === "response.delta") {
            if (typeof eventPayload.delta !== "string") {
              throw new Error("response.delta events must include a string delta field.");
            }

            const delta = eventPayload.delta;
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
            const nextSummary = updateSummary(agentName, threadIdsRef.current[agentName] ?? "", eventPayload);
            threadIdsRef.current[agentName] = nextSummary.threadId;
            pendingRequestRef.current[agentName] =
              nextSummary.status === "approval_pending" ? { ...payload, thread_id: nextSummary.threadId } : null;
            setMessagesForAgent(agentName, (current) =>
              current.map((message) =>
                message.id === assistantMessageId
                  ? {
                      ...message,
                      content:
                        message.content ||
                        (nextSummary.status === "approval_pending"
                          ? "Approval pending. Re-submit after approval."
                          : "Invocation completed."),
                      status: nextSummary.status === "blocked" ? "error" : "complete",
                    }
                  : message,
              ),
            );
            return;
          }

          if (event === "response.error" || event === "message") {
            if (typeof eventPayload.error !== "string" || !eventPayload.error.trim()) {
              throw new Error(`${event} events must include a non-empty string error field.`);
            }
            applyInvocationFailure(agentName, assistantMessageId, eventPayload.error);
          }
        },
        onError: (nextError) => {
          streamErrorHandled = true;
          applyInvocationFailure(agentName, assistantMessageId, nextError.message);
        },
        onClose: () => undefined,
      });
    } catch (nextError) {
      if (!abortController.signal.aborted && !streamErrorHandled) {
        const message = nextError instanceof Error ? nextError.message : String(nextError);
        applyInvocationFailure(agentName, assistantMessageId, message);
      }
    } finally {
      setIsSending(false);
      streamAbortRef.current = null;
    }
  }

  async function handleSubmit() {
    if (!token.trim()) {
      setChatError("Enter the gateway token before sending chat requests.");
      return;
    }

    if (!selectedAgentName || !canSubmitChat) {
      return;
    }

    const agentName = selectedAgentName;
    const nextPrompt = prompt.trim();
    let gooseMaxTurns: number | undefined;
    let gooseWorkingDirectory: string | undefined;
    let explicitA2ATimeoutSeconds: number | undefined;
    let specialistPayload: InvokePayload["subagents"];

    if (selectedRuntimeKind === "goose") {
      try {
        gooseMaxTurns = parseGooseMaxTurns(selectedGooseChatSettings.maxTurns);
        gooseWorkingDirectory = normalizeGooseWorkingDirectory(selectedGooseChatSettings.workingDirectory);
      } catch (nextError) {
        setChatError(nextError instanceof Error ? nextError.message : String(nextError));
        return;
      }
    }

    try {
      explicitA2ATimeoutSeconds = parseA2ATimeoutSeconds(a2aTimeoutSeconds);
    } catch (nextError) {
      setChatError(nextError instanceof Error ? nextError.message : String(nextError));
      return;
    }

    const normalizedA2ATargetAgent = a2aTargetAgent.trim();
    const normalizedA2ATargetNamespace = a2aTargetNamespace.trim();
    const hasExplicitA2ATarget = normalizedA2ATargetAgent.length > 0 || normalizedA2ATargetNamespace.length > 0;
    if (specialistTeamConfigured && selectedRuntimeKind !== "langgraph") {
      setChatError("Specialist-team orchestration is currently available for LangGraph agents only.");
      return;
    }
    if (hasExplicitA2ATarget) {
      if (!normalizedA2ATargetAgent || !normalizedA2ATargetNamespace) {
        setChatError("Provide both an A2A target namespace and an A2A target agent.");
        return;
      }
      if (!isValidK8sName(normalizedA2ATargetAgent)) {
        setChatError("A2A target agent must be a valid lowercase Kubernetes name.");
        return;
      }
      if (!isValidK8sName(normalizedA2ATargetNamespace)) {
        setChatError("A2A target namespace must be a valid lowercase Kubernetes name.");
        return;
      }
    }

    if (hasExplicitA2ATarget && specialistTeamConfigured) {
      setChatError("Use either an explicit A2A target or a specialist team for this request, not both.");
      return;
    }

    if (specialistTeamConfigured) {
      try {
        specialistPayload = specialistSubagents
          .filter(
            (item) =>
              item.name.trim() ||
              item.namespace.trim() ||
              item.role.trim() ||
              item.task.trim() ||
              item.inputFilesText.trim() ||
              item.resultFilePath.trim(),
          )
          .map((item, index) => {
            const name = item.name.trim();
            const subagentNamespace = item.namespace.trim();
            if (!name || !subagentNamespace) {
              throw new Error(`Specialist ${index + 1} requires both a namespace and an agent name.`);
            }
            if (!isValidK8sName(name)) {
              throw new Error(`Specialist ${index + 1} agent name must be a valid lowercase Kubernetes name.`);
            }
            if (!isValidK8sName(subagentNamespace)) {
              throw new Error(`Specialist ${index + 1} namespace must be a valid lowercase Kubernetes name.`);
            }
            const timeoutSeconds = parseSubagentTimeoutSeconds(item.timeoutSeconds);
            const inputFiles = parseSubagentInputFiles(item.inputFilesText);
            const task = item.task.trim();
            if (!nextPrompt && !task) {
              throw new Error(`Specialist ${index + 1} requires a delegated task when the main prompt is blank.`);
            }
            return {
              name,
              namespace: subagentNamespace,
              role: item.role.trim() || undefined,
              task: task || undefined,
              input_files: inputFiles.length > 0 ? inputFiles : undefined,
              result_file_path: item.resultFilePath.trim() || undefined,
              share_sandbox_session: item.shareSandboxSession,
              timeout_seconds: timeoutSeconds,
            };
          });
      } catch (nextError) {
        setChatError(nextError instanceof Error ? nextError.message : String(nextError));
        return;
      }
    }

    const payload: InvokePayload = {
      prompt: nextPrompt,
      thread_id: threadIdsRef.current[agentName],
      require_approval: requireApproval,
      approval_action: requireApproval ? `Approve UI request for ${agentName}` : undefined,
      a2a_target_agent: hasExplicitA2ATarget ? normalizedA2ATargetAgent : undefined,
      a2a_target_namespace: hasExplicitA2ATarget ? normalizedA2ATargetNamespace : undefined,
      a2a_timeout_seconds: explicitA2ATimeoutSeconds,
      subagents: specialistPayload,
      subagent_strategy: specialistPayload && specialistPayload.length > 0 ? subagentStrategy : undefined,
      max_turns: gooseMaxTurns,
      working_directory: gooseWorkingDirectory,
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
    catalog: 0,
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
        : activeView === "evals"
          ? evals.map((evalResource) => ({
              id: evalResource.name,
              title: evalResource.name,
              subtitle: evalResource.agent_ref,
              status: evalResource.phase,
              note: `${evalResource.test_suite.length} case${evalResource.test_suite.length === 1 ? "" : "s"}`,
            }))
          : []; // catalog view manages its own list

  const sidebarSelectedId =
    activeView === "agents" ? selectedAgentName : activeView === "workflows" ? selectedWorkflowName : selectedEvalName;

  const emptySidebarMessage = !token.trim()
    ? "Authenticate with a gateway token and load the namespace catalog."
    : activeView === "agents"
      ? `No agents are provisioned in namespace '${namespace}'. Create an agent to start a runtime.`
      : activeView === "workflows"
        ? `No workflows are defined in namespace '${namespace}'. Create one to orchestrate agent steps.`
        : activeView === "catalog"
          ? "Browse the catalog in the main panel."
          : `No evaluations are defined in namespace '${namespace}'. Create one to validate agent quality.`;

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
        : activeView === "catalog"
          ? "Browse pre-built skills and MCP tool sidecars."
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
        : activeView === "catalog"
          ? "browse"
          : selectedEval?.phase ?? (evalCreateMode ? "draft" : "none");

  const chatEmptyMessage = selectedAgentName
    ? "Run chat requests, explicit A2A delegations, or specialist-team orchestration from this workspace. Streaming is enabled by default."
    : "Select an agent from the catalog or create a new one to start an invocation.";

  const selectedWorkflowApprovalName =
    typeof selectedWorkflow?.pending_approval?.name === "string" ? selectedWorkflow.pending_approval.name : undefined;

  return (
    <div className="flex h-screen flex-col bg-background text-foreground">
      <TopBar
        health={health}
        gatewayError={gatewayError}
        token={token}
        namespace={namespace}
        isConnecting={isConnecting}
        authConfig={authConfig}
        currentUser={currentUser}
        authBusy={authBusy}
        authUsername={authUsername}
        authPassword={authPassword}
        authEmail={authEmail}
        authDisplayName={authDisplayName}
        authPasswordConfirm={authPasswordConfirm}
        passwordProvider={passwordProvider}
        registerMode={registerMode}
        onTokenChange={setToken}
        onNamespaceChange={setNamespace}
        onAuthUsernameChange={setAuthUsername}
        onAuthPasswordChange={setAuthPassword}
        onAuthEmailChange={setAuthEmail}
        onAuthDisplayNameChange={setAuthDisplayName}
        onAuthPasswordConfirmChange={setAuthPasswordConfirm}
        onPasswordProviderChange={setPasswordProvider}
        onRegisterModeChange={setRegisterMode}
        onConnect={() => void handleConnect()}
        onPasswordSubmit={() => void handlePasswordAuth()}
        onStartOidc={handleOidcStart}
        onStartSaml={handleSamlStart}
        onLogout={() => void handleLogout()}
        onRefreshCurrentUser={async () => {
          await refreshCurrentUserProfile(token);
        }}
      />

      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar — hidden on mobile, visible md+ */}
        <div className="hidden md:flex">
          <AppSidebar
            collapsed={sidebarCollapsed}
            onToggleCollapse={() => setSidebarCollapsed((prev) => !prev)}
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
        </div>

        {/* Center column */}
        <main className="flex flex-1 flex-col overflow-auto p-4 gap-4">
          {/* Inspector toggle */}
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                Workspace Status
              </p>
              <h2 className="text-lg font-semibold text-foreground">{heroTitle}</h2>
            </div>
            <Button variant="outline" size="sm" className="gap-1.5" onClick={() => setInspectorOpen(true)}>
              <PanelRightOpen className="h-4 w-4" />
              Inspector
            </Button>
          </div>

          {/* Status row */}
          <div className="flex flex-wrap gap-2 text-xs">
            <span className="rounded-md border border-border bg-card px-3 py-1.5">
              Gateway: <strong className="text-foreground">{gatewayStatus}</strong>
            </span>
            <span className="rounded-md border border-border bg-card px-3 py-1.5">
              Auth: <strong className="text-foreground">{health?.auth_mode ?? "unknown"}</strong>
            </span>
            <span className="rounded-md border border-border bg-card px-3 py-1.5">
              View: <strong className="text-foreground">{activeView}</strong>
            </span>
            <span className="rounded-md border border-border bg-card px-3 py-1.5">
              Selected: <strong className="text-foreground">{selectedResourceStatus}</strong>
            </span>
          </div>

          {(workspaceError || gatewayError) && (
            <div className="rounded-md border border-destructive/30 bg-destructive/10 px-4 py-2 text-sm text-destructive">
              {workspaceError || gatewayError}
            </div>
          )}

          {!token.trim() ? (
            <div className="flex flex-1 items-center justify-center">
              <div className="text-center space-y-2">
                <h3 className="text-lg font-semibold text-foreground">Connect to the Gateway</h3>
                <p className="text-sm text-muted-foreground max-w-md">
                  Use the top-right access dialog to connect with a bearer token, local credentials, LDAP, or enterprise SSO, then manage agents, workflows, evaluations, approvals, and chat from one place.
                </p>
              </div>
            </div>
          ) : activeView === "agents" ? (
            <>
              {agentCreateMode || (!selectedAgentName && agents.length === 0) ? (
                <CreateAgentPanel
                  token={token}
                  isEmptyWorkspace={agents.length === 0}
                  name={createAgentName}
                  model={createAgentModel}
                  systemPrompt={createAgentSystemPrompt}
                  runtimeKind={createAgentRuntimeKind}
                  mcpServersText={createAgentMcpServersText}
                  mcpSidecarsText={createAgentMcpSidecarsText}
                  a2aAllowedCallersText={createAgentA2AAllowedCallersText}
                  skillFileDrafts={createAgentSkillFileDrafts}
                  gooseConfigFileDrafts={createAgentGooseConfigFileDrafts}
                  isCreating={isCreatingAgent}
                  error={createError}
                  onMcpServersTextChange={setCreateAgentMcpServersText}
                  onMcpSidecarsTextChange={setCreateAgentMcpSidecarsText}
                  onNameChange={setCreateAgentName}
                  onModelChange={setCreateAgentModel}
                  onSystemPromptChange={setCreateAgentSystemPrompt}
                  onRuntimeKindChange={setCreateAgentRuntimeKind}
                  onA2AAllowedCallersTextChange={setCreateAgentA2AAllowedCallersText}
                  onSkillFileDraftsChange={setCreateAgentSkillFileDrafts}
                  onGooseConfigFileDraftsChange={setCreateAgentGooseConfigFileDrafts}
                  onCreate={() => void handleCreateAgent()}
                />
              ) : selectedAgentDetail ? (
                <AgentManagementPanel
                  token={token}
                  agent={selectedAgentDetail}
                  policies={policies}
                  isSaving={savingAgent}
                  isDeleting={deletingAgent}
                  error={agentManageError}
                  onSave={(payload, a2aAllowedCallersText, skillFiles, gooseConfigFiles) =>
                    void handleSaveAgent(payload, a2aAllowedCallersText, skillFiles, gooseConfigFiles)
                  }
                  onDelete={() => void handleDeleteAgent()}
                />
              ) : (
                <div className="flex flex-1 items-center justify-center">
                  <p className="text-sm text-muted-foreground">Loading the selected agent settings...</p>
                </div>
              )}

              {!agentCreateMode && selectedAgentName ? (
                <ChatWorkbench
                  agentName={selectedAgentName}
                  runtimeKind={selectedRuntimeKind}
                  prompt={prompt}
                  messages={messages}
                  isSending={isSending}
                  tokenReady={Boolean(token.trim())}
                  streamMode={streamMode}
                  requireApproval={requireApproval}
                  approvalSupported={approvalSupported}
                  a2aTargetAgent={a2aTargetAgent}
                  a2aTargetNamespace={a2aTargetNamespace}
                  a2aTimeoutSeconds={a2aTimeoutSeconds}
                  specialistSubagents={specialistSubagents}
                  specialistTeamConfigured={specialistTeamConfigured}
                  subagentStrategy={subagentStrategy}
                  discoveryPeers={discoverablePeers}
                  discoveryLoading={discoveryLoading}
                  discoveryError={discoveryError}
                  gooseMaxTurns={selectedGooseChatSettings.maxTurns}
                  gooseWorkingDirectory={selectedGooseChatSettings.workingDirectory}
                  gooseSystemPrompt={gooseSystemPromptPreview}
                  emptyMessage={chatEmptyMessage}
                  error={chatError}
                  onPromptChange={setPrompt}
                  onToggleStreamMode={setStreamMode}
                  onToggleRequireApproval={setRequireApproval}
                  onA2ATargetAgentChange={(value) => {
                    setChatError("");
                    setA2ATargetAgent(value);
                  }}
                  onA2ATargetNamespaceChange={(value) => {
                    setChatError("");
                    setA2ATargetNamespace(value);
                  }}
                  onA2ATimeoutSecondsChange={(value) => {
                    setChatError("");
                    setA2ATimeoutSeconds(value);
                  }}
                  onSubagentStrategyChange={(value) => {
                    setChatError("");
                    setSubagentStrategy(value);
                  }}
                  onAddSpecialistSubagent={() => {
                    setChatError("");
                    setSpecialistSubagents((current) => [...current, createSpecialistSubagentDraft()]);
                  }}
                  onUpdateSpecialistSubagent={(id, patch) => {
                    setChatError("");
                    updateSpecialistSubagentDraft(id, patch);
                  }}
                  onRemoveSpecialistSubagent={(id) => {
                    setChatError("");
                    setSpecialistSubagents((current) => current.filter((item) => item.id !== id));
                  }}
                  onClearSpecialistTeam={() => {
                    setChatError("");
                    setSpecialistSubagents([]);
                    setSubagentStrategy("sequential");
                  }}
                  onGooseMaxTurnsChange={(value) => {
                    setChatError("");
                    setGooseChatSettingsForAgent(selectedAgentName, (current) => ({
                      ...current,
                      maxTurns: value,
                    }));
                  }}
                  onGooseWorkingDirectoryChange={(value) => {
                    setChatError("");
                    setGooseChatSettingsForAgent(selectedAgentName, (current) => ({
                      ...current,
                      workingDirectory: value,
                    }));
                  }}
                  canSubmit={canSubmitChat}
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
          ) : activeView === "catalog" ? (
            <SkillsCatalogPanel token={token} />
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
        </main>
      </div>

      {/* Inspector drawers */}
      {activeView === "agents" ? (
        <AgentInspectorDrawer
          open={inspectorOpen}
          onOpenChange={setInspectorOpen}
          health={health}
          gatewayError={gatewayError}
          workspaceError={workspaceError}
          selectedAgentName={selectedAgentName}
          selectedAgentDetail={selectedAgentDetail}
          discoverablePeers={discoverablePeers}
          discoveryLoading={discoveryLoading}
          discoveryError={discoveryError}
          namespace={namespace}
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
        <ResourceInspectorDrawer
          open={inspectorOpen}
          onOpenChange={setInspectorOpen}
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
        <ResourceInspectorDrawer
          open={inspectorOpen}
          onOpenChange={setInspectorOpen}
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
      <Toaster position="bottom-right" theme="dark" richColors />
    </div>
  );
}
