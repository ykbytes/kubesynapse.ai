import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  createAgent,
  createEval,
  createGitCredentials,
  createGitHubCredentials,
  createWorkflow,
  deleteAgent,
  deleteEval,
  deleteWorkflow,
  discoverAgentPeers,
  fetchAgent,
  fetchWorkflow,
  listAgents,
  listEvals,
  listPolicies,
  listWorkflows,
  triggerWorkflow,
  cancelWorkflow,
  updateAgent,
  updateEval,
  updateWorkflow,
  apiErrorMessage,
} from "@/lib/api";
import { parseA2APeerRefsText } from "@/lib/a2a";
import { parseMcpServersText, parseMcpSidecarsText } from "@/lib/mcp";
import { buildSkillFiles } from "@/lib/skills";
import { buildGooseConfigFiles } from "@/lib/gooseConfig";
import { buildOpenCodeConfigFiles } from "@/lib/opencodeConfig";
import { useConnection } from "./ConnectionContext";
import { toast } from "sonner";
import type {
  AgentDetail,
  AgentDiscoveryPeer,
  AgentInfo,
  CreateAgentPayload,
  EvalInfo,
  EvalPayload,
  EvalUpdatePayload,
  GitFormState,
  GitHubFormState,
  PolicyInfo,
  RuntimeKind,
  TextFileDraft,
  UpdateAgentPayload,
  WorkflowInfo,
  WorkflowPayload,
  WorkflowUpdatePayload,
  WorkspaceView,
} from "@/types";
import type { SidebarResourceItem } from "@/components/AppSidebar";

// ── Context value type ──

export interface WorkspaceContextValue {
  // Data
  agents: AgentInfo[];
  policies: PolicyInfo[];
  workflows: WorkflowInfo[];
  evals: EvalInfo[];
  selectedAgentDetail: AgentDetail | null;
  selectedRuntimeKind: RuntimeKind;

  // Selection
  activeView: WorkspaceView;
  selectedAgentName: string;
  selectedWorkflowName: string;
  selectedEvalName: string;
  agentCreateMode: boolean;
  workflowCreateMode: boolean;
  evalCreateMode: boolean;
  setActiveView: (view: WorkspaceView) => void;
  setSelectedAgentName: (name: string) => void;
  setAgentCreateMode: (mode: boolean) => void;
  setWorkflowCreateMode: (mode: boolean) => void;
  setEvalCreateMode: (mode: boolean) => void;
  setSelectedAgentDetail: (detail: AgentDetail | null) => void;

  // Loading / errors
  catalogLoading: boolean;
  workspaceError: string;
  setWorkspaceError: (msg: string) => void;
  agentManageError: string;
  setAgentManageError: (msg: string) => void;
  workflowError: string;
  evalError: string;

  // Discovery
  discoverablePeers: AgentDiscoveryPeer[];
  discoveryLoading: boolean;
  discoveryError: string;

  // Operation flags
  savingAgent: boolean;
  deletingAgent: boolean;
  isCreatingAgent: boolean;
  savingWorkflow: boolean;
  deletingWorkflow: boolean;
  runningWorkflow: boolean;
  cancellingWorkflow: boolean;
  savingEval: boolean;
  deletingEval: boolean;

  // UI
  sidebarCollapsed: boolean;
  setSidebarCollapsed: (fn: (prev: boolean) => boolean) => void;
  inspectorOpen: boolean;
  setInspectorOpen: (open: boolean) => void;
  agentViewTab: "config" | "chat";
  setAgentViewTab: (tab: "config" | "chat") => void;

  // Create-agent form
  createAgentName: string;
  createAgentModel: string;
  createAgentSystemPrompt: string;
  createAgentRuntimeKind: RuntimeKind;
  createAgentMcpServersText: string;
  createAgentMcpSidecarsText: string;
  createAgentA2AAllowedCallersText: string;
  createAgentSkillFileDrafts: TextFileDraft[];
  createAgentGooseConfigFileDrafts: TextFileDraft[];
  createAgentOpenCodeConfigFileDrafts: TextFileDraft[];
  createAgentGitForm: GitFormState;
  createAgentGitHubForm: GitHubFormState;
  createError: string;
  setCreateAgentName: (v: string) => void;
  setCreateAgentModel: (v: string) => void;
  setCreateAgentSystemPrompt: (v: string) => void;
  setCreateAgentRuntimeKind: (v: RuntimeKind) => void;
  setCreateAgentMcpServersText: (v: string) => void;
  setCreateAgentMcpSidecarsText: (v: string) => void;
  setCreateAgentA2AAllowedCallersText: (v: string) => void;
  setCreateAgentSkillFileDrafts: (v: TextFileDraft[]) => void;
  setCreateAgentGooseConfigFileDrafts: (v: TextFileDraft[]) => void;
  setCreateAgentOpenCodeConfigFileDrafts: (v: TextFileDraft[]) => void;
  setCreateAgentGitForm: (v: GitFormState) => void;
  setCreateAgentGitHubForm: (v: GitHubFormState) => void;

  // Sidebar derived
  sidebarCounts: Record<WorkspaceView, number>;
  sidebarItems: SidebarResourceItem[];
  sidebarSelectedId: string;
  emptySidebarMessage: string;
  selectedAgent: AgentInfo | null;
  selectedWorkflow: WorkflowInfo | null;
  selectedEval: EvalInfo | null;

  // Actions
  refreshWorkspaceData: (options?: { silent?: boolean; token?: string; namespace?: string }) => Promise<void>;
  handleCreateAgent: () => Promise<AgentInfo | null>;
  handleSaveAgent: (payload: UpdateAgentPayload, a2aAllowedCallersText: string, skillFiles: Record<string, string>, gooseConfigFiles: Record<string, unknown>, opencodeConfigFiles: Record<string, unknown>) => Promise<void>;
  handleDeleteAgent: () => Promise<string | null>;
  handleCreateWorkflow: (payload: WorkflowPayload) => Promise<void>;
  handleUpdateWorkflow: (name: string, payload: WorkflowUpdatePayload) => Promise<void>;
  handleDeleteWorkflow: (name: string) => Promise<void>;
  handleTriggerWorkflow: (name: string, input?: string) => Promise<void>;
  handleCancelWorkflow: (name: string) => Promise<void>;
  handleCreateEval: (payload: EvalPayload) => Promise<void>;
  handleUpdateEval: (name: string, payload: EvalUpdatePayload) => Promise<void>;
  handleDeleteEval: (name: string) => Promise<void>;
  handleSelectResource: (name: string) => void;
  handleCreateNew: () => void;
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

const DEFAULT_AGENT_NAME = "workspace-assistant";
const DEFAULT_AGENT_MODEL = "gpt-4";
const DEFAULT_SYSTEM_PROMPT =
  "You are a helpful enterprise assistant. Answer clearly, stay factual, and do not fabricate information.";

/** Return `prev` (same reference) when JSON is unchanged, avoiding unnecessary re-renders. */
function stableArrayUpdate<T>(prev: T[], next: T[]): T[] {
  if (prev.length !== next.length) return next;
  if (prev.length === 0) return prev;
  // Fast path: stringify comparison for small K8s resource arrays
  if (JSON.stringify(prev) === JSON.stringify(next)) return prev;
  return next;
}

// ── Provider ──

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const { token, namespace } = useConnection();

  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [policies, setPolicies] = useState<PolicyInfo[]>([]);
  const [workflows, setWorkflows] = useState<WorkflowInfo[]>([]);
  const [evals, setEvals] = useState<EvalInfo[]>([]);

  const [activeView, setActiveView] = useState<WorkspaceView>("agents");
  const [selectedAgentName, setSelectedAgentName] = useState("");
  const [selectedWorkflowName, setSelectedWorkflowName] = useState("");
  const [selectedEvalName, setSelectedEvalName] = useState("");
  const [selectedPolicyName, setSelectedPolicyName] = useState("");
  const [agentCreateMode, setAgentCreateMode] = useState(false);
  const [workflowCreateMode, setWorkflowCreateMode] = useState(false);
  const [evalCreateMode, setEvalCreateMode] = useState(false);
  const [selectedAgentDetail, setSelectedAgentDetail] = useState<AgentDetail | null>(null);

  const [catalogLoading, setCatalogLoading] = useState(false);
  const [workspaceError, setWorkspaceError] = useState("");
  const [agentManageError, setAgentManageError] = useState("");
  const [workflowError, setWorkflowError] = useState("");
  const [evalError, setEvalError] = useState("");
  const [createError, setCreateError] = useState("");

  const [savingAgent, setSavingAgent] = useState(false);
  const [deletingAgent, setDeletingAgent] = useState(false);
  const [isCreatingAgent, setIsCreatingAgent] = useState(false);
  const [savingWorkflow, setSavingWorkflow] = useState(false);
  const [deletingWorkflow, setDeletingWorkflow] = useState(false);
  const [runningWorkflow, setRunningWorkflow] = useState(false);
  const [cancellingWorkflow, setCancellingWorkflow] = useState(false);
  const [savingEval, setSavingEval] = useState(false);
  const [deletingEval, setDeletingEval] = useState(false);

  const [discoverablePeers, setDiscoverablePeers] = useState<AgentDiscoveryPeer[]>([]);
  const [discoveryLoading, setDiscoveryLoading] = useState(false);
  const [discoveryError, setDiscoveryError] = useState("");

  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [agentViewTab, setAgentViewTab] = useState<"config" | "chat">("chat");

  // Create-agent form
  const [createAgentName, setCreateAgentName] = useState(DEFAULT_AGENT_NAME);
  const [createAgentModel, setCreateAgentModel] = useState(DEFAULT_AGENT_MODEL);
  const [createAgentSystemPrompt, setCreateAgentSystemPrompt] = useState(DEFAULT_SYSTEM_PROMPT);
  const [createAgentRuntimeKind, setCreateAgentRuntimeKind] = useState<RuntimeKind>("langgraph");
  const [createAgentMcpServersText, setCreateAgentMcpServersText] = useState("");
  const [createAgentMcpSidecarsText, setCreateAgentMcpSidecarsText] = useState("");
  const [createAgentA2AAllowedCallersText, setCreateAgentA2AAllowedCallersText] = useState("");
  const [createAgentSkillFileDrafts, setCreateAgentSkillFileDrafts] = useState<TextFileDraft[]>([]);
  const [createAgentGooseConfigFileDrafts, setCreateAgentGooseConfigFileDrafts] = useState<TextFileDraft[]>([]);
  const [createAgentOpenCodeConfigFileDrafts, setCreateAgentOpenCodeConfigFileDrafts] = useState<TextFileDraft[]>([]);
  const [createAgentGitForm, setCreateAgentGitForm] = useState<GitFormState>({
    enabled: false, repoUrl: "", authMethod: "token", pushPolicy: "after-each-commit",
    defaultBranch: "main", token: "", username: "", password: "", sshPrivateKey: "",
  });
  const [createAgentGitHubForm, setCreateAgentGitHubForm] = useState<GitHubFormState>({ enabled: false, token: "" });

  // Refs for polling callbacks
  const selectedAgentNameRef = useRef(selectedAgentName);
  selectedAgentNameRef.current = selectedAgentName;
  const selectedWorkflowNameRef = useRef(selectedWorkflowName);
  selectedWorkflowNameRef.current = selectedWorkflowName;
  const selectedEvalNameRef = useRef(selectedEvalName);
  selectedEvalNameRef.current = selectedEvalName;
  const agentCreateModeRef = useRef(agentCreateMode);
  agentCreateModeRef.current = agentCreateMode;
  const workflowCreateModeRef = useRef(workflowCreateMode);
  workflowCreateModeRef.current = workflowCreateMode;
  const evalCreateModeRef = useRef(evalCreateMode);
  evalCreateModeRef.current = evalCreateMode;

  // ── Derived ──

  const selectedAgent = useMemo(() => agents.find((a) => a.name === selectedAgentName) ?? null, [agents, selectedAgentName]);
  const selectedWorkflow = useMemo(() => workflowCreateMode ? null : workflows.find((w) => w.name === selectedWorkflowName) ?? null, [workflows, selectedWorkflowName, workflowCreateMode]);
  const selectedEval = useMemo(() => evalCreateMode ? null : evals.find((e) => e.name === selectedEvalName) ?? null, [evals, selectedEvalName, evalCreateMode]);
  const selectedRuntimeKind: RuntimeKind = selectedAgentDetail?.runtime_kind ?? "langgraph";

  const sidebarCounts = useMemo<Record<WorkspaceView, number>>(() => ({
    agents: agents.length, workflows: workflows.length, composer: workflows.length, evals: evals.length, catalog: 0, policies: policies.length, settings: 0, admin: 0,
  }), [agents.length, workflows.length, evals.length, policies.length]);

  const sidebarItems = useMemo<SidebarResourceItem[]>(() =>
    activeView === "agents"
      ? agents.map((a) => ({ id: a.name, title: a.name, subtitle: a.model, status: a.status, note: a.namespace }))
      : activeView === "workflows" || activeView === "composer"
        ? workflows.map((w) => ({ id: w.name, title: w.name, subtitle: w.description || `${w.steps.length} step${w.steps.length === 1 ? "" : "s"}`, status: w.phase, note: w.current_step ? `Current step: ${w.current_step}` : `${w.steps.length} steps` }))
        : activeView === "evals"
          ? evals.map((e) => ({ id: e.name, title: e.name, subtitle: e.agent_ref, status: e.phase, note: `${e.test_suite.length} case${e.test_suite.length === 1 ? "" : "s"}` }))
          : activeView === "policies"
            ? policies.map((p) => ({ id: p.name, title: p.name, subtitle: `${p.allowed_models.length} model${p.allowed_models.length === 1 ? "" : "s"}`, status: "active", note: p.namespace }))
            : [],
    [activeView, agents, workflows, evals, policies],
  );

  const sidebarSelectedId = activeView === "agents" ? selectedAgentName : (activeView === "workflows" || activeView === "composer") ? selectedWorkflowName : activeView === "policies" ? selectedPolicyName : selectedEvalName;

  const emptySidebarMessage = useMemo(() => !token.trim()
    ? "Authenticate with a gateway token and load the namespace catalog."
    : activeView === "agents"
      ? `No agents are provisioned in namespace '${namespace}'. Create an agent to start a runtime.`
      : activeView === "workflows" || activeView === "composer"
        ? `No workflows are defined in namespace '${namespace}'. Create one to orchestrate agent steps.`
        : activeView === "catalog"
          ? "Browse the catalog in the main panel."
          : activeView === "settings"
            ? "Manage LLM providers and API keys."
            : activeView === "admin"
              ? "Manage users, roles, and namespace access."
              : activeView === "policies"
                ? `No policies are defined in namespace '${namespace}'. Create one to enforce guardrails.`
                : `No evaluations are defined in namespace '${namespace}'. Create one to validate agent quality.`,
    [token, activeView, namespace],
  );

  // ── refreshWorkspaceData ──

  const refreshWorkspaceData = useCallback(
    async (options?: { silent?: boolean; token?: string; namespace?: string }) => {
      const silent = options?.silent ?? false;
      const activeToken = options?.token ?? token;
      const activeNamespace = options?.namespace ?? namespace;
      if (!activeToken.trim()) {
        setAgents([]); setPolicies([]); setWorkflows([]); setEvals([]); setSelectedAgentDetail(null);
        return;
      }
      if (!silent) { setCatalogLoading(true); setWorkspaceError(""); }
      try {
        const [nextAgents, nextPolicies, nextWorkflows, nextEvals] = await Promise.all([
          listAgents(activeToken, activeNamespace),
          listPolicies(activeToken, activeNamespace),
          listWorkflows(activeToken, activeNamespace),
          listEvals(activeToken, activeNamespace),
        ]);
        setAgents((prev) => stableArrayUpdate(prev, nextAgents));
        setPolicies((prev) => stableArrayUpdate(prev, nextPolicies));
        setWorkflows((prev) => stableArrayUpdate(prev, nextWorkflows));
        setEvals((prev) => stableArrayUpdate(prev, nextEvals));
        if (!agentCreateModeRef.current) {
          const cur = selectedAgentNameRef.current;
          const next = nextAgents.some((a) => a.name === cur) ? cur : nextAgents[0]?.name ?? "";
          if (next !== cur) setSelectedAgentName(next);
        }
        if (!workflowCreateModeRef.current) {
          const cur = selectedWorkflowNameRef.current;
          const next = nextWorkflows.some((w) => w.name === cur) ? cur : nextWorkflows[0]?.name ?? "";
          if (next !== cur) setSelectedWorkflowName(next);
        }
        if (!evalCreateModeRef.current) {
          const cur = selectedEvalNameRef.current;
          const next = nextEvals.some((e) => e.name === cur) ? cur : nextEvals[0]?.name ?? "";
          if (next !== cur) setSelectedEvalName(next);
        }
      } catch (err) {
        if (!silent) setWorkspaceError(apiErrorMessage(err));
      } finally {
        if (!silent) setCatalogLoading(false);
      }
    },
    [token, namespace],
  );

  // ── Effects ──

  // Workspace data polling
  const initialLoadDoneRef = useRef(false);
  const prevNamespaceRef = useRef(namespace);
  useEffect(() => {
    if (!token.trim()) {
      setAgents([]); setPolicies([]); setWorkflows([]); setEvals([]); setSelectedAgentDetail(null);
      setWorkspaceError("");
      initialLoadDoneRef.current = false;
      prevNamespaceRef.current = namespace;
      return;
    }
    // Namespace changed → clear selections and show loading
    const namespaceChanged = prevNamespaceRef.current !== namespace;
    prevNamespaceRef.current = namespace;
    if (namespaceChanged) {
      setSelectedAgentName(""); setSelectedAgentDetail(null); setDiscoverablePeers([]);
      setSelectedWorkflowName(""); setSelectedEvalName("");
      setAgentCreateMode(false); setWorkflowCreateMode(false); setEvalCreateMode(false);
    }
    // First mount or namespace change: non-silent (show loading). Subsequent restarts (e.g. token refresh): silent.
    const silent = initialLoadDoneRef.current && !namespaceChanged;
    initialLoadDoneRef.current = true;
    void refreshWorkspaceData({ silent });
    const timer = window.setInterval(() => void refreshWorkspaceData({ silent: true }), 10_000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, namespace]);

  // Auto-select first resource
  useEffect(() => {
    if (activeView === "agents" && !agentCreateMode && !selectedAgentName && agents.length > 0) setSelectedAgentName(agents[0].name);
    if ((activeView === "workflows" || activeView === "composer") && !workflowCreateMode && !selectedWorkflowName && workflows.length > 0) setSelectedWorkflowName(workflows[0].name);
    if (activeView === "evals" && !evalCreateMode && !selectedEvalName && evals.length > 0) setSelectedEvalName(evals[0].name);
    if (activeView === "policies" && !selectedPolicyName && policies.length > 0) setSelectedPolicyName(policies[0].name);
  }, [activeView, agents, workflows, evals, policies, agentCreateMode, workflowCreateMode, evalCreateMode, selectedAgentName, selectedWorkflowName, selectedEvalName, selectedPolicyName]);

  // Fetch agent detail
  useEffect(() => {
    if (!token.trim() || !selectedAgentName || agentCreateMode) { setSelectedAgentDetail(null); return; }
    let cancelled = false;
    void fetchAgent(token, namespace, selectedAgentName)
      .then((detail) => { if (!cancelled) { setSelectedAgentDetail(detail); setAgentManageError(""); } })
      .catch((err) => { if (!cancelled) { setAgentManageError(apiErrorMessage(err)); setSelectedAgentDetail(null); } });
    return () => { cancelled = true; };
  }, [token, namespace, selectedAgentName, agentCreateMode]);

  // Peer discovery
  useEffect(() => {
    if (!token.trim() || !selectedAgentName || agentCreateMode) {
      setDiscoverablePeers([]); setDiscoveryError(""); setDiscoveryLoading(false); return;
    }
    let cancelled = false;
    setDiscoveryLoading(true);
    void discoverAgentPeers(token, namespace, selectedAgentName)
      .then((r) => { if (!cancelled) { setDiscoverablePeers(r.peers); setDiscoveryError(""); } })
      .catch((err) => { if (!cancelled) { setDiscoverablePeers([]); setDiscoveryError(apiErrorMessage(err)); } })
      .finally(() => { if (!cancelled) setDiscoveryLoading(false); });
    return () => { cancelled = true; };
  }, [token, namespace, selectedAgentName, agentCreateMode, selectedAgentDetail?.policy_ref, agents.length]);

  // Workflow polling — restart when the selected workflow's phase changes
  const selectedWorkflowPhase = selectedWorkflow?.phase ?? "";
  const workflowPollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    if (workflowPollingRef.current) { clearInterval(workflowPollingRef.current); workflowPollingRef.current = null; }
    if (!selectedWorkflowName || !token.trim()) return;
    const isActive = selectedWorkflowPhase === "running" || selectedWorkflowPhase === "queued" || selectedWorkflowPhase === "waiting-approval" || selectedWorkflowPhase === "pending";
    if (!isActive) return;
    workflowPollingRef.current = setInterval(async () => {
      try {
        const updated = await fetchWorkflow(token, namespace, selectedWorkflowName);
        setWorkflows((prev) => prev.map((w) => (w.name === updated.name ? updated : w)));
        if (updated.phase !== "running" && updated.phase !== "queued" && updated.phase !== "waiting-approval" && updated.phase !== "pending") {
          if (workflowPollingRef.current) { clearInterval(workflowPollingRef.current); workflowPollingRef.current = null; }
          toast.info(`Workflow ${updated.name} ${updated.phase}`);
        }
      } catch (err) {
          console.warn("[workflow-poll]", apiErrorMessage(err));
        }
    }, 3000);
    return () => { if (workflowPollingRef.current) { clearInterval(workflowPollingRef.current); workflowPollingRef.current = null; } };
  }, [selectedWorkflowName, selectedWorkflowPhase, token, namespace]);

  // ── Handlers ──

  const handleCreateAgent = useCallback(async (): Promise<AgentInfo | null> => {
    if (!token.trim()) { setCreateError("Enter the gateway token before creating an agent."); return null; }
    setIsCreatingAgent(true);
    setCreateError("");
    try {
      const agentName = createAgentName.trim();
      if (createAgentGitForm.enabled) {
        if (!createAgentGitForm.repoUrl.trim()) throw new Error("Git repository URL is required when git integration is enabled.");
        if (createAgentGitForm.authMethod === "token" && !createAgentGitForm.token.trim()) throw new Error("A git personal access token is required when token auth is selected.");
        if (createAgentGitForm.authMethod === "basic" && (!createAgentGitForm.username.trim() || !createAgentGitForm.password.trim())) throw new Error("Git username and password are required when basic auth is selected.");
        if (createAgentGitForm.authMethod === "ssh" && !createAgentGitForm.sshPrivateKey.trim()) throw new Error("A git SSH private key is required when SSH auth is selected.");
      }
      if (createAgentGitHubForm.enabled) {
        if (createAgentRuntimeKind !== "langgraph") throw new Error("GitHub MCP access currently requires the LangGraph runtime.");
        if (!createAgentGitHubForm.token.trim()) throw new Error("A GitHub personal access token is required when GitHub MCP access is enabled.");
      }
      const allowedCallers = parseA2APeerRefsText(createAgentA2AAllowedCallersText);
      const skillFiles = buildSkillFiles(createAgentSkillFileDrafts);
      const mcpServers = createAgentRuntimeKind === "langgraph" ? parseMcpServersText(createAgentMcpServersText) : [];
      const mcpSidecars = createAgentRuntimeKind !== "goose" ? parseMcpSidecarsText(createAgentMcpSidecarsText) : [];
      const gooseConfigFiles = createAgentRuntimeKind === "goose" ? buildGooseConfigFiles(createAgentGooseConfigFileDrafts) : {};
      const opencodeConfigFiles = createAgentRuntimeKind === "opencode" ? buildOpenCodeConfigFiles(createAgentOpenCodeConfigFileDrafts) : {};

      let gitCredentialSecretRef: string | undefined;
      if (createAgentGitForm.enabled) {
        const cred = await createGitCredentials(token, agentName, {
          auth_method: createAgentGitForm.authMethod,
          token: createAgentGitForm.authMethod === "token" ? createAgentGitForm.token : undefined,
          username: createAgentGitForm.authMethod === "basic" ? createAgentGitForm.username : undefined,
          password: createAgentGitForm.authMethod === "basic" ? createAgentGitForm.password : undefined,
          ssh_private_key: createAgentGitForm.authMethod === "ssh" ? createAgentGitForm.sshPrivateKey : undefined,
        }, namespace);
        gitCredentialSecretRef = typeof cred.secret_name === "string" && cred.secret_name.trim() ? cred.secret_name.trim() : `${agentName}-git-credentials`;
      }
      let githubCredentialSecretRef: string | undefined;
      if (createAgentGitHubForm.enabled) {
        const cred = await createGitHubCredentials(token, agentName, { token: createAgentGitHubForm.token }, namespace);
        githubCredentialSecretRef = typeof cred.secret_name === "string" && cred.secret_name.trim() ? cred.secret_name.trim() : `${agentName}-github-credentials`;
      }

      const payload: CreateAgentPayload = {
        name: agentName, model: createAgentModel.trim(), system_prompt: createAgentSystemPrompt.trim(),
        runtime_kind: createAgentRuntimeKind, mcp_servers: mcpServers, mcp_sidecars: mcpSidecars,
        a2a_config: allowedCallers.length > 0 ? { allowed_callers: allowedCallers } : undefined,
        skills: Object.keys(skillFiles).length > 0 ? { files: skillFiles } : undefined,
        goose_config_files: gooseConfigFiles,
        opencode_config_files: opencodeConfigFiles,
        git_config: createAgentGitForm.enabled ? {
          repo_url: createAgentGitForm.repoUrl, default_branch: createAgentGitForm.defaultBranch || "main",
          push_policy: createAgentGitForm.pushPolicy, auth_method: createAgentGitForm.authMethod,
          credential_secret_ref: gitCredentialSecretRef,
        } : undefined,
        github_config: createAgentGitHubForm.enabled ? { credential_secret_ref: githubCredentialSecretRef } : undefined,
      };
      const created = await createAgent(token, namespace, payload);
      setAgentCreateMode(false);
      setCreateAgentMcpServersText(""); setCreateAgentMcpSidecarsText(""); setCreateAgentA2AAllowedCallersText("");
      setCreateAgentSkillFileDrafts([]); setCreateAgentGooseConfigFileDrafts([]); setCreateAgentOpenCodeConfigFileDrafts([]);
      setCreateAgentGitForm({ enabled: false, repoUrl: "", authMethod: "token", pushPolicy: "after-each-commit", defaultBranch: "main", token: "", username: "", password: "", sshPrivateKey: "" });
      setCreateAgentGitHubForm({ enabled: false, token: "" });
      setSelectedAgentName(created.name);
      await refreshWorkspaceData({ silent: false });
      toast.success("Agent created", { description: "Provisioning may take a few seconds before the runtime is ready." });
      return created;
    } catch (err) {
      const msg = apiErrorMessage(err);
      setCreateError(msg);
      toast.error("Failed to create agent", { description: msg });
      return null;
    } finally {
      setIsCreatingAgent(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, namespace, createAgentName, createAgentModel, createAgentSystemPrompt, createAgentRuntimeKind,
    createAgentMcpServersText, createAgentMcpSidecarsText, createAgentA2AAllowedCallersText,
    createAgentSkillFileDrafts, createAgentGooseConfigFileDrafts, createAgentOpenCodeConfigFileDrafts, createAgentGitForm, createAgentGitHubForm, refreshWorkspaceData]);

  const handleSaveAgent = useCallback(async (
    payload: UpdateAgentPayload, a2aAllowedCallersText: string,
    skillFiles: Record<string, string>, gooseConfigFiles: Record<string, unknown>,
    opencodeConfigFiles: Record<string, unknown>,
  ) => {
    if (!token.trim() || !selectedAgentName) return;
    setSavingAgent(true); setAgentManageError("");
    try {
      const allowedCallers = parseA2APeerRefsText(a2aAllowedCallersText);
      const nextPayload: UpdateAgentPayload = {
        ...payload,
        a2a_config: { allowed_callers: allowedCallers },
        skills: { files: skillFiles },
        goose_config_files: payload.runtime_kind === "goose" ? gooseConfigFiles : {},
        opencode_config_files: payload.runtime_kind === "opencode" ? opencodeConfigFiles : {},
      };
      const updated = await updateAgent(token, namespace, selectedAgentName, nextPayload);
      setSelectedAgentDetail(updated);
      await refreshWorkspaceData({ silent: true });
      toast.success("Agent saved");
    } catch (err) {
      const msg = apiErrorMessage(err);
      setAgentManageError(msg);
      toast.error("Failed to save agent", { description: msg });
    } finally { setSavingAgent(false); }
  }, [token, namespace, selectedAgentName, refreshWorkspaceData]);

  const handleDeleteAgent = useCallback(async (): Promise<string | null> => {
    if (!token.trim() || !selectedAgentName) return null;
    const agentName = selectedAgentName;
    setDeletingAgent(true); setAgentManageError("");
    try {
      await deleteAgent(token, namespace, agentName);
      setSelectedAgentName(""); setSelectedAgentDetail(null);
      setAgentCreateMode(agents.length <= 1);
      await refreshWorkspaceData({ silent: false });
      toast.success("Agent deleted");
      return agentName;
    } catch (err) {
      const msg = apiErrorMessage(err);
      setAgentManageError(msg);
      toast.error("Failed to delete agent", { description: msg });
      return null;
    } finally { setDeletingAgent(false); }
  }, [token, namespace, selectedAgentName, agents.length, refreshWorkspaceData]);

  const handleCreateWorkflow = useCallback(async (payload: WorkflowPayload) => {
    if (!token.trim()) return;
    setSavingWorkflow(true); setWorkflowError("");
    try {
      const created = await createWorkflow(token, namespace, payload);
      setWorkflowCreateMode(false); setSelectedWorkflowName(created.name);
      await refreshWorkspaceData({ silent: false }); toast.success("Workflow created");
    } catch (err) { const msg = apiErrorMessage(err); setWorkflowError(msg); toast.error("Failed to create workflow", { description: msg }); }
    finally { setSavingWorkflow(false); }
  }, [token, namespace, refreshWorkspaceData]);

  const handleUpdateWorkflow = useCallback(async (name: string, payload: WorkflowUpdatePayload) => {
    if (!token.trim()) return;
    setSavingWorkflow(true); setWorkflowError("");
    try { await updateWorkflow(token, namespace, name, payload); await refreshWorkspaceData({ silent: false }); toast.success("Workflow saved"); }
    catch (err) { const msg = apiErrorMessage(err); setWorkflowError(msg); toast.error("Failed to save workflow", { description: msg }); }
    finally { setSavingWorkflow(false); }
  }, [token, namespace, refreshWorkspaceData]);

  const handleDeleteWorkflow = useCallback(async (name: string) => {
    if (!token.trim()) return;
    setDeletingWorkflow(true); setWorkflowError("");
    try {
      await deleteWorkflow(token, namespace, name);
      setSelectedWorkflowName(""); setWorkflowCreateMode(workflows.length <= 1);
      await refreshWorkspaceData({ silent: false }); toast.success("Workflow deleted");
    } catch (err) { const msg = apiErrorMessage(err); setWorkflowError(msg); toast.error("Failed to delete workflow", { description: msg }); }
    finally { setDeletingWorkflow(false); }
  }, [token, namespace, workflows.length, refreshWorkspaceData]);

  const handleTriggerWorkflow = useCallback(async (name: string, input?: string) => {
    if (!token.trim()) return;
    setRunningWorkflow(true); setWorkflowError("");
    try {
      const updated = await triggerWorkflow(token, namespace, name, input);
      // Optimistically merge the returned resource so the polling effect
      // can detect the phase change immediately instead of waiting for the
      // next 10-second workspace refresh.
      setWorkflows((prev) => prev.map((w) => (w.name === updated.name ? updated : w)));
      toast.success("Workflow triggered");
    }
    catch (err) { const msg = apiErrorMessage(err); setWorkflowError(msg); toast.error("Failed to trigger workflow", { description: msg }); }
    finally { setRunningWorkflow(false); }
  }, [token, namespace]);

  const handleCancelWorkflow = useCallback(async (name: string) => {
    if (!token.trim()) return;
    setCancellingWorkflow(true); setWorkflowError("");
    try {
      const updated = await cancelWorkflow(token, namespace, name);
      setWorkflows((prev) => prev.map((w) => (w.name === updated.name ? updated : w)));
      toast.success("Workflow cancelled");
    }
    catch (err) { const msg = apiErrorMessage(err); setWorkflowError(msg); toast.error("Failed to cancel workflow", { description: msg }); }
    finally { setCancellingWorkflow(false); }
  }, [token, namespace]);

  const handleCreateEval = useCallback(async (payload: EvalPayload) => {
    if (!token.trim()) return;
    setSavingEval(true); setEvalError("");
    try {
      const created = await createEval(token, namespace, payload);
      setEvalCreateMode(false); setSelectedEvalName(created.name);
      await refreshWorkspaceData({ silent: false }); toast.success("Evaluation created");
    } catch (err) { const msg = apiErrorMessage(err); setEvalError(msg); toast.error("Failed to create evaluation", { description: msg }); }
    finally { setSavingEval(false); }
  }, [token, namespace, refreshWorkspaceData]);

  const handleUpdateEval = useCallback(async (name: string, payload: EvalUpdatePayload) => {
    if (!token.trim()) return;
    setSavingEval(true); setEvalError("");
    try { await updateEval(token, namespace, name, payload); await refreshWorkspaceData({ silent: false }); toast.success("Evaluation saved"); }
    catch (err) { const msg = apiErrorMessage(err); setEvalError(msg); toast.error("Failed to save evaluation", { description: msg }); }
    finally { setSavingEval(false); }
  }, [token, namespace, refreshWorkspaceData]);

  const handleDeleteEval = useCallback(async (name: string) => {
    if (!token.trim()) return;
    setDeletingEval(true); setEvalError("");
    try {
      await deleteEval(token, namespace, name);
      setSelectedEvalName(""); setEvalCreateMode(evals.length <= 1);
      await refreshWorkspaceData({ silent: false }); toast.success("Evaluation deleted");
    } catch (err) { const msg = apiErrorMessage(err); setEvalError(msg); toast.error("Failed to delete evaluation", { description: msg }); }
    finally { setDeletingEval(false); }
  }, [token, namespace, evals.length, refreshWorkspaceData]);

  const handleSelectResource = useCallback((name: string) => {
    if (activeView === "agents") { setAgentCreateMode(false); setSelectedAgentName(name); }
    else if (activeView === "workflows" || activeView === "composer") { setWorkflowCreateMode(false); setSelectedWorkflowName(name); }
    else if (activeView === "policies") { setSelectedPolicyName(name); }
    else { setEvalCreateMode(false); setSelectedEvalName(name); }
  }, [activeView]);

  const handleCreateNew = useCallback(() => {
    setWorkspaceError(""); setCreateError(""); setAgentManageError(""); setWorkflowError(""); setEvalError("");
    if (activeView === "agents") { setAgentCreateMode(true); setSelectedAgentName(""); }
    else if (activeView === "workflows" || activeView === "composer") { setWorkflowCreateMode(true); setSelectedWorkflowName(""); }
    else { setEvalCreateMode(true); setSelectedEvalName(""); }
  }, [activeView]);

  const ctxValue = useMemo<WorkspaceContextValue>(() => ({
    agents, policies, workflows, evals, selectedAgentDetail, selectedRuntimeKind,
    activeView, selectedAgentName, selectedWorkflowName, selectedEvalName,
    agentCreateMode, workflowCreateMode, evalCreateMode,
    setActiveView, setSelectedAgentName, setAgentCreateMode, setWorkflowCreateMode, setEvalCreateMode, setSelectedAgentDetail,
    catalogLoading, workspaceError, setWorkspaceError, agentManageError, setAgentManageError, workflowError, evalError,
    discoverablePeers, discoveryLoading, discoveryError,
    savingAgent, deletingAgent, isCreatingAgent, savingWorkflow, deletingWorkflow, runningWorkflow, cancellingWorkflow, savingEval, deletingEval,
    sidebarCollapsed, setSidebarCollapsed, inspectorOpen, setInspectorOpen, agentViewTab, setAgentViewTab,
    createAgentName, createAgentModel, createAgentSystemPrompt, createAgentRuntimeKind,
    createAgentMcpServersText, createAgentMcpSidecarsText, createAgentA2AAllowedCallersText,
    createAgentSkillFileDrafts, createAgentGooseConfigFileDrafts, createAgentOpenCodeConfigFileDrafts, createAgentGitForm, createAgentGitHubForm, createError,
    setCreateAgentName, setCreateAgentModel, setCreateAgentSystemPrompt, setCreateAgentRuntimeKind,
    setCreateAgentMcpServersText, setCreateAgentMcpSidecarsText, setCreateAgentA2AAllowedCallersText,
    setCreateAgentSkillFileDrafts, setCreateAgentGooseConfigFileDrafts, setCreateAgentOpenCodeConfigFileDrafts, setCreateAgentGitForm, setCreateAgentGitHubForm,
    sidebarCounts, sidebarItems, sidebarSelectedId, emptySidebarMessage, selectedAgent, selectedWorkflow, selectedEval,
    refreshWorkspaceData, handleCreateAgent, handleSaveAgent, handleDeleteAgent,
    handleCreateWorkflow, handleUpdateWorkflow, handleDeleteWorkflow, handleTriggerWorkflow, handleCancelWorkflow,
    handleCreateEval, handleUpdateEval, handleDeleteEval, handleSelectResource, handleCreateNew,
  }), [
    agents, policies, workflows, evals, selectedAgentDetail, selectedRuntimeKind,
    activeView, selectedAgentName, selectedWorkflowName, selectedEvalName,
    agentCreateMode, workflowCreateMode, evalCreateMode,
    catalogLoading, workspaceError, agentManageError, workflowError, evalError,
    discoverablePeers, discoveryLoading, discoveryError,
    savingAgent, deletingAgent, isCreatingAgent, savingWorkflow, deletingWorkflow, runningWorkflow, cancellingWorkflow, savingEval, deletingEval,
    sidebarCollapsed, inspectorOpen, agentViewTab,
    createAgentName, createAgentModel, createAgentSystemPrompt, createAgentRuntimeKind,
    createAgentMcpServersText, createAgentMcpSidecarsText, createAgentA2AAllowedCallersText,
    createAgentSkillFileDrafts, createAgentGooseConfigFileDrafts, createAgentOpenCodeConfigFileDrafts, createAgentGitForm, createAgentGitHubForm, createError,
    sidebarCounts, sidebarItems, sidebarSelectedId, emptySidebarMessage, selectedAgent, selectedWorkflow, selectedEval,
    refreshWorkspaceData, handleCreateAgent, handleSaveAgent, handleDeleteAgent,
    handleCreateWorkflow, handleUpdateWorkflow, handleDeleteWorkflow, handleTriggerWorkflow, handleCancelWorkflow,
    handleCreateEval, handleUpdateEval, handleDeleteEval, handleSelectResource, handleCreateNew,
  ]);

  return (
    <WorkspaceContext.Provider value={ctxValue}>
      {children}
    </WorkspaceContext.Provider>
  );
}

// ── Hook ──

export function useWorkspace() {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error("useWorkspace must be used within WorkspaceProvider");
  return ctx;
}
