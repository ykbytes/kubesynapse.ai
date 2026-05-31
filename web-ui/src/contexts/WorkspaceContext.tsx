import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  createAgent,
  createGitCredentials,
  createGitHubCredentials,
  createWorkflow,
  deleteAgent,
  deleteWorkflow,
  discoverAgentPeers,
  fetchAgent,
  fetchWorkflow,
  listAgents,
  listPolicies,
  listWorkflows,
  triggerWorkflow,
  cancelWorkflow,
  retryFailedSteps,
  updateAgent,
  updateWorkflow,
  apiErrorMessage,
} from "@/lib/api";
import { parseA2APeerRefsText } from "@/lib/a2a";
import { parseMcpServersText, parseMcpSidecarsText } from "@/lib/mcp";
import { buildSkillFiles } from "@/lib/skills";
import { buildOpenCodeConfigFiles } from "@/lib/opencodeConfig";
import { deriveAgentVisualSignals } from "@/lib/agentSignals";
import { systemPromptLengthError } from "@/lib/agentPrompt";
import { useConnection } from "./ConnectionContext";
import { toast } from "sonner";
import type {
  AgentDetail,
  AgentDiscoveryPeer,
  AgentInfo,
  CreateAgentPayload,
  FactoryMode,
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
import type { SidebarResourceItem } from "@/components/app/AppSidebar";
import { DEFAULT_FACTORY_MODE, isFactoryWorkflowName } from "@/lib/factoryModes";

// ── Context value type ──

export interface WorkspaceContextValue {
  // Data
  agents: AgentInfo[];
  policies: PolicyInfo[];
  workflows: WorkflowInfo[];
  selectedAgentDetail: AgentDetail | null;
  selectedRuntimeKind: RuntimeKind;
  selectedPolicyName: string;

  // Selection
  activeView: WorkspaceView;
  selectedAgentName: string;
  selectedWorkflowName: string;
  agentCreateMode: boolean;
  workflowCreateMode: boolean;
  setActiveView: (view: WorkspaceView) => void;
  setSelectedAgentName: (name: string) => void;
  setAgentCreateMode: (mode: boolean) => void;
  setWorkflowCreateMode: (mode: boolean) => void;
  setSelectedAgentDetail: (detail: AgentDetail | null) => void;
  selectPolicy: (name: string) => void;

  // Loading / errors
  catalogLoading: boolean;
  workspaceError: string;
  setWorkspaceError: (msg: string) => void;
  agentManageError: string;
  setAgentManageError: (msg: string) => void;
  workflowError: string;

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
  retryingWorkflow: boolean;

  // UI
  sidebarCollapsed: boolean;
  setSidebarCollapsed: (fn: (prev: boolean) => boolean) => void;
  inspectorOpen: boolean;
  setInspectorOpen: (open: boolean) => void;
  agentViewTab: "config" | "chat";
  setAgentViewTab: (tab: "config" | "chat") => void;
  catalogTab: "skills" | "mcp";
  setCatalogTab: (tab: "skills" | "mcp") => void;
  intelligenceTab: "intelligence" | "observatory";
  setIntelligenceTab: (tab: "intelligence" | "observatory") => void;
  configPanelCollapsed: boolean;
  setConfigPanelCollapsed: (collapsed: boolean) => void;
  chatFocused: boolean;
  setChatFocused: (focused: boolean) => void;

  // Create-agent form
  createAgentName: string;
  createAgentModel: string;
  createAgentSystemPrompt: string;
  createAgentRuntimeKind: RuntimeKind;
  createAgentMcpConnectionIds: string[];
  createAgentMcpServersText: string;
  createAgentMcpSidecarsText: string;
  createAgentA2AAllowedCallersText: string;
  createAgentSkillFileDrafts: TextFileDraft[];
  createAgentOpenCodeConfigFileDrafts: TextFileDraft[];
  createAgentGitForm: GitFormState;
  createAgentGitHubForm: GitHubFormState;
  createError: string;
  setCreateAgentName: (v: string) => void;
  setCreateAgentModel: (v: string) => void;
  setCreateAgentSystemPrompt: (v: string) => void;
  setCreateAgentRuntimeKind: (v: RuntimeKind) => void;
  setCreateAgentMcpConnectionIds: (v: string[]) => void;
  setCreateAgentMcpServersText: (v: string) => void;
  setCreateAgentMcpSidecarsText: (v: string) => void;
  setCreateAgentA2AAllowedCallersText: (v: string) => void;
  setCreateAgentSkillFileDrafts: (v: TextFileDraft[]) => void;
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
  selectedFactoryWorkflowMode: FactoryMode;
  setSelectedFactoryWorkflowMode: (value: FactoryMode) => void;
  observatoryFocus: {
    workflowName: string;
    runId?: string | null;
    requestedAt: number;
  } | null;

  // Actions
  refreshWorkspaceData: (options?: { silent?: boolean; token?: string; namespace?: string }) => Promise<void>;
  handleCreateAgent: () => Promise<AgentInfo | null>;
  handleSaveAgent: (payload: UpdateAgentPayload, a2aAllowedCallersText: string, skillFiles: Record<string, string>, opencodeConfigFiles: Record<string, unknown>) => Promise<void>;
  handleDeleteAgent: () => Promise<string | null>;
  handleCreateWorkflow: (payload: WorkflowPayload) => Promise<void>;
  handleUpdateWorkflow: (name: string, payload: WorkflowUpdatePayload) => Promise<void>;
  handleDeleteWorkflow: (name: string) => Promise<void>;
  handleTriggerWorkflow: (name: string, input?: string, factoryMode?: FactoryMode) => Promise<void>;
  handleCancelWorkflow: (name: string) => Promise<void>;
  handleRetryFailedSteps: (name: string) => Promise<void>;
  handleSelectResource: (name: string) => void;
  handleCreateNew: () => void;
  navigateToResource: (view: WorkspaceView, name?: string) => void;
  openObservatoryForWorkflowRun: (workflowName: string, runId?: string | null) => void;
  clearObservatoryFocus: () => void;
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

const DEFAULT_AGENT_NAME = "workspace-assistant";
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

function stableAgentDetailCacheUpdate(
  prev: Record<string, AgentDetail>,
  details: AgentDetail[],
): Record<string, AgentDetail> {
  let changed = false;
  const next = { ...prev };

  for (const detail of details) {
    const existing = prev[detail.name];
    if (existing && JSON.stringify(existing) === JSON.stringify(detail)) {
      continue;
    }
    next[detail.name] = detail;
    changed = true;
  }

  return changed ? next : prev;
}

// ── Provider ──

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const { token, namespace } = useConnection();

  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [policies, setPolicies] = useState<PolicyInfo[]>([]);
  const [workflows, setWorkflows] = useState<WorkflowInfo[]>([]);

  const [activeView, setActiveView] = useState<WorkspaceView>("agents");
  const [selectedAgentName, setSelectedAgentName] = useState("");
  const [selectedWorkflowName, setSelectedWorkflowName] = useState("");
  const [selectedPolicyName, setSelectedPolicyName] = useState("");
  const [agentCreateMode, setAgentCreateMode] = useState(false);
  const [workflowCreateMode, setWorkflowCreateMode] = useState(false);
  const [selectedAgentDetail, setSelectedAgentDetail] = useState<AgentDetail | null>(null);
  const [agentDetailCache, setAgentDetailCache] = useState<Record<string, AgentDetail>>({});

  const [catalogLoading, setCatalogLoading] = useState(false);
  const [workspaceError, setWorkspaceError] = useState("");
  const [agentManageError, setAgentManageError] = useState("");
  const [workflowError, setWorkflowError] = useState("");
  const [createError, setCreateError] = useState("");

  const [savingAgent, setSavingAgent] = useState(false);
  const [deletingAgent, setDeletingAgent] = useState(false);
  const [isCreatingAgent, setIsCreatingAgent] = useState(false);
  const [savingWorkflow, setSavingWorkflow] = useState(false);
  const [deletingWorkflow, setDeletingWorkflow] = useState(false);
  const [runningWorkflow, setRunningWorkflow] = useState(false);
  const [cancellingWorkflow, setCancellingWorkflow] = useState(false);
  const [retryingWorkflow, setRetryingWorkflow] = useState(false);

  const [discoverablePeers, setDiscoverablePeers] = useState<AgentDiscoveryPeer[]>([]);
  const [discoveryLoading, setDiscoveryLoading] = useState(false);
  const [discoveryError, setDiscoveryError] = useState("");
  const [factoryWorkflowModeByName, setFactoryWorkflowModeByName] = useState<Record<string, FactoryMode>>({});

  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [agentViewTab, setAgentViewTab] = useState<"config" | "chat">("chat");
  const [catalogTab, setCatalogTab] = useState<"skills" | "mcp">("mcp");
  const [intelligenceTab, setIntelligenceTab] = useState<"intelligence" | "observatory">("observatory");
  const [configPanelCollapsed, setConfigPanelCollapsed] = useState(false);
  const [chatFocused, setChatFocused] = useState(false);
  const [observatoryFocus, setObservatoryFocus] = useState<{
    workflowName: string;
    runId?: string | null;
    requestedAt: number;
  } | null>(null);

  // Create-agent form
  const [createAgentName, setCreateAgentName] = useState(DEFAULT_AGENT_NAME);
  const [createAgentModel, setCreateAgentModel] = useState("");
  const [createAgentSystemPrompt, setCreateAgentSystemPrompt] = useState(DEFAULT_SYSTEM_PROMPT);
  const [createAgentRuntimeKind, setCreateAgentRuntimeKind] = useState<RuntimeKind>("opencode");
  const [createAgentMcpConnectionIds, setCreateAgentMcpConnectionIds] = useState<string[]>([]);
  const [createAgentMcpServersText, setCreateAgentMcpServersText] = useState("");
  const [createAgentMcpSidecarsText, setCreateAgentMcpSidecarsText] = useState("");
  const [createAgentA2AAllowedCallersText, setCreateAgentA2AAllowedCallersText] = useState("");
  const [createAgentSkillFileDrafts, setCreateAgentSkillFileDrafts] = useState<TextFileDraft[]>([]);
  const [createAgentOpenCodeConfigFileDrafts, setCreateAgentOpenCodeConfigFileDrafts] = useState<TextFileDraft[]>([]);
  const [createAgentGitForm, setCreateAgentGitForm] = useState<GitFormState>({
    enabled: false, repoUrl: "", authMethod: "token", pushPolicy: "after-each-commit",
    defaultBranch: "main", branch: "", token: "", username: "", password: "", sshPrivateKey: "",
  });
  const [createAgentGitHubForm, setCreateAgentGitHubForm] = useState<GitHubFormState>({ enabled: false, token: "" });

  // Refs for polling callbacks
  const selectedAgentNameRef = useRef(selectedAgentName);
  selectedAgentNameRef.current = selectedAgentName;
  const selectedWorkflowNameRef = useRef(selectedWorkflowName);
  selectedWorkflowNameRef.current = selectedWorkflowName;
  const agentCreateModeRef = useRef(agentCreateMode);
  agentCreateModeRef.current = agentCreateMode;
  const workflowCreateModeRef = useRef(workflowCreateMode);
  workflowCreateModeRef.current = workflowCreateMode;
  const agentDetailRequestsRef = useRef<Set<string>>(new Set());

  // ── Derived ──

  const selectedAgent = useMemo(() => agents.find((a) => a.name === selectedAgentName) ?? null, [agents, selectedAgentName]);
  const selectedWorkflow = useMemo(() => workflowCreateMode ? null : workflows.find((w) => w.name === selectedWorkflowName) ?? null, [workflows, selectedWorkflowName, workflowCreateMode]);
  const selectedFactoryWorkflowMode = useMemo<FactoryMode>(() => (
    selectedWorkflowName ? factoryWorkflowModeByName[selectedWorkflowName] ?? DEFAULT_FACTORY_MODE : DEFAULT_FACTORY_MODE
  ), [factoryWorkflowModeByName, selectedWorkflowName]);
  const selectedRuntimeKind: RuntimeKind = selectedAgentDetail?.runtime_kind ?? "opencode";
  const cachedSelectedAgentDetail = selectedAgentName ? agentDetailCache[selectedAgentName] : undefined;

  const sidebarCounts = useMemo<Record<WorkspaceView, number>>(() => ({
    agents: agents.length,
    chat: agents.length,
    workflows: workflows.length,
    composer: workflows.length,
    catalog: 0,
    policies: policies.length,
    intelligence: 0,
    settings: 0,
    admin: 0,
    docs: 0,
    webhooks: 0,
  }), [agents.length, workflows.length, policies.length]);

  const sidebarItems = useMemo<SidebarResourceItem[]>(() =>
    activeView === "agents" || activeView === "chat"
      ? agents.map((a) => ({
          id: a.name,
          title: a.name,
          subtitle: a.model,
          status: a.status,
          note: a.namespace,
          signals: deriveAgentVisualSignals(agentDetailCache[a.name] ?? { runtime_kind: a.runtime_kind }),
        }))
      : activeView === "workflows" || activeView === "composer" || activeView === "intelligence"
        ? workflows.map((w) => ({ id: w.name, title: w.name, subtitle: w.description || `${w.steps.length} step${w.steps.length === 1 ? "" : "s"}`, status: w.phase, note: w.current_step ? `Current step: ${w.current_step}` : `${w.steps.length} steps` }))
        : activeView === "policies"
          ? policies.map((p) => ({ id: p.name, title: p.name, subtitle: `${p.allowed_models.length} model${p.allowed_models.length === 1 ? "" : "s"}`, status: "active", note: p.namespace }))
          : [],
    [activeView, agents, workflows, policies, agentDetailCache],
  );

  const sidebarSelectedId = activeView === "agents" || activeView === "chat" ? selectedAgentName : (activeView === "workflows" || activeView === "composer" || activeView === "intelligence") ? selectedWorkflowName : activeView === "policies" ? selectedPolicyName : "";

  const emptySidebarMessage = useMemo(() => !token.trim()
    ? "Authenticate with a gateway token and load the namespace catalog."
    : activeView === "agents"
      ? `No agents are provisioned in namespace '${namespace}'. Create an agent to start a runtime.`
      : activeView === "chat"
        ? `No agents are provisioned in namespace '${namespace}'. Create one in the Agents view, then return here to chat.`
        : activeView === "workflows" || activeView === "composer"
          ? `No workflows are defined in namespace '${namespace}'. Create one to orchestrate agent steps.`
          : activeView === "intelligence"
            ? `No workflows are defined in namespace '${namespace}'. Create or trigger a workflow to inspect run observability.`
          : activeView === "catalog"
            ? "Browse skills and MCP integrations in the main panel."
            : activeView === "settings"
            ? "Manage LLM providers and API keys."
            : activeView === "admin"
              ? "Manage users, roles, and namespace access."
              : activeView === "policies"
                ? `No policies are defined in namespace '${namespace}'. Create one to enforce guardrails.`
                : activeView === "docs"
                  ? "Browse the documentation in the main panel."
                  : "Manage webhook receivers and event-driven triggers in the main panel.",
    [token, activeView, namespace],
  );

  // ── refreshWorkspaceData ──

  const refreshWorkspaceData = useCallback(
    async (options?: { silent?: boolean; token?: string; namespace?: string }) => {
      const silent = options?.silent ?? false;
      const activeToken = options?.token ?? token;
      const activeNamespace = options?.namespace ?? namespace;
      if (!activeToken.trim()) {
        setAgents([]); setPolicies([]); setWorkflows([]); setSelectedAgentDetail(null); setAgentDetailCache({});
        return;
      }
      if (!silent) { setCatalogLoading(true); setWorkspaceError(""); }
      try {
        const [nextAgents, nextPolicies, nextWorkflows] = await Promise.all([
          listAgents(activeToken, activeNamespace),
          listPolicies(activeToken, activeNamespace),
          listWorkflows(activeToken, activeNamespace),
        ]);
        setAgents((prev) => stableArrayUpdate(prev, nextAgents));
        setPolicies((prev) => stableArrayUpdate(prev, nextPolicies));
        setWorkflows((prev) => {
          // When the 3s workflow poll is active, preserve its fresher data for the
          // actively-polled workflow so the slower 10s list poll doesn't overwrite it.
          const polledName = workflowPollingRef.current ? selectedWorkflowNameRef.current : null;
          if (polledName) {
            const existing = prev.find((pw) => pw.name === polledName);
            if (existing) {
              const merged = nextWorkflows.map((nw) => nw.name === polledName ? existing : nw);
              return stableArrayUpdate(prev, merged);
            }
          }
          return stableArrayUpdate(prev, nextWorkflows);
        });
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
      setAgents([]); setPolicies([]); setWorkflows([]); setSelectedAgentDetail(null); setAgentDetailCache({});
      setWorkspaceError("");
      initialLoadDoneRef.current = false;
      prevNamespaceRef.current = namespace;
      agentDetailRequestsRef.current.clear();
      return;
    }
    // Namespace changed → clear selections and show loading
    const namespaceChanged = prevNamespaceRef.current !== namespace;
    prevNamespaceRef.current = namespace;
    if (namespaceChanged) {
      setSelectedAgentName(""); setSelectedAgentDetail(null); setDiscoverablePeers([]); setAgentDetailCache({});
      setSelectedWorkflowName("");
      setAgentCreateMode(false); setWorkflowCreateMode(false);
      agentDetailRequestsRef.current.clear();
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
    if ((activeView === "agents" || activeView === "chat") && !agentCreateMode && !selectedAgentName && agents.length > 0) setSelectedAgentName(agents[0].name);
    if ((activeView === "workflows" || activeView === "composer") && !workflowCreateMode && !selectedWorkflowName && workflows.length > 0) setSelectedWorkflowName(workflows[0].name);
    if (activeView === "policies" && !selectedPolicyName && policies.length > 0) setSelectedPolicyName(policies[0].name);
  }, [activeView, agents, workflows, policies, agentCreateMode, workflowCreateMode, selectedAgentName, selectedWorkflowName, selectedPolicyName]);

  // Fetch agent detail
  useEffect(() => {
    if (!token.trim() || !selectedAgentName || agentCreateMode) { setSelectedAgentDetail(null); return; }
    if (cachedSelectedAgentDetail) {
      setSelectedAgentDetail(cachedSelectedAgentDetail);
      setAgentManageError("");
      return;
    }
    let cancelled = false;
    void fetchAgent(token, namespace, selectedAgentName)
      .then((detail) => {
        if (!cancelled) {
          setSelectedAgentDetail(detail);
          setAgentDetailCache((current) => stableAgentDetailCacheUpdate(current, [detail]));
          setAgentManageError("");
        }
      })
      .catch((err) => { if (!cancelled) { setAgentManageError(apiErrorMessage(err)); setSelectedAgentDetail(null); } });
    return () => { cancelled = true; };
  }, [token, namespace, selectedAgentName, agentCreateMode, cachedSelectedAgentDetail]);

  useEffect(() => {
    if (!token.trim() || (activeView !== "agents" && activeView !== "chat") || agentCreateMode || agents.length === 0) {
      return;
    }
    let cancelled = false;
    const missingNames = agents
      .map((agent) => agent.name)
      .filter((name) => !agentDetailCache[name] && !agentDetailRequestsRef.current.has(name));
    if (missingNames.length === 0) return;
    for (const name of missingNames) agentDetailRequestsRef.current.add(name);
    void Promise.allSettled(missingNames.map((name) => fetchAgent(token, namespace, name)))
      .then((results) => {
        if (cancelled) return;
        setAgentDetailCache((current) => {
          return stableAgentDetailCacheUpdate(
            current,
            results.flatMap((result) => (result.status === "fulfilled" ? [result.value] : [])),
          );
        });
      })
      .finally(() => {
        for (const name of missingNames) agentDetailRequestsRef.current.delete(name);
      });
    return () => { cancelled = true; };
  }, [token, namespace, activeView, agentCreateMode, agents, agentDetailCache]);

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
      const promptValidationError = systemPromptLengthError(createAgentSystemPrompt);
      if (promptValidationError) {
        setCreateError(promptValidationError);
        toast.error("Failed to create agent", { description: promptValidationError });
        return null;
      }
      const agentModel = createAgentModel.trim();
      if (!agentModel) {
        const message = "Select a connected model before creating an agent.";
        setCreateError(message);
        toast.error("Failed to create agent", { description: message });
        return null;
      }
      const agentName = createAgentName.trim();
      if (createAgentGitForm.enabled) {
        if (!createAgentGitForm.repoUrl.trim()) throw new Error("Git repository URL is required when git integration is enabled.");
        if (createAgentGitForm.authMethod === "token" && !createAgentGitForm.token.trim()) throw new Error("A git personal access token is required when token auth is selected.");
        if (createAgentGitForm.authMethod === "basic" && (!createAgentGitForm.username.trim() || !createAgentGitForm.password.trim())) throw new Error("Git username and password are required when basic auth is selected.");
        if (createAgentGitForm.authMethod === "ssh" && !createAgentGitForm.sshPrivateKey.trim()) throw new Error("A git SSH private key is required when SSH auth is selected.");
      }
      if (createAgentGitHubForm.enabled) {
        throw new Error("GitHub MCP access is not supported for OpenCode agents.");
      }
      const allowedCallers = parseA2APeerRefsText(createAgentA2AAllowedCallersText);
      const skillFiles = buildSkillFiles(createAgentSkillFileDrafts);
      const mcpServers = parseMcpServersText(createAgentMcpServersText);
      const mcpSidecars = parseMcpSidecarsText(createAgentMcpSidecarsText);
      const opencodeConfigFiles = buildOpenCodeConfigFiles(createAgentOpenCodeConfigFileDrafts);

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
        name: agentName, model: agentModel, system_prompt: createAgentSystemPrompt.trim(),
        runtime_kind: createAgentRuntimeKind,
        mcp_connection_ids: createAgentMcpConnectionIds,
        mcp_servers: createAgentMcpConnectionIds.length === 0 ? mcpServers : undefined,
        mcp_sidecars: createAgentMcpConnectionIds.length === 0 ? mcpSidecars : undefined,
        a2a_config: allowedCallers.length > 0 ? { allowed_callers: allowedCallers } : undefined,
        skills: Object.keys(skillFiles).length > 0 ? { files: skillFiles } : undefined,
        opencode_config_files: createAgentRuntimeKind === "opencode" ? opencodeConfigFiles : undefined,
        git_config: createAgentGitForm.enabled ? {
          repo_url: createAgentGitForm.repoUrl, default_branch: createAgentGitForm.defaultBranch || "main",
          branch: createAgentGitForm.branch || undefined,
          push_policy: createAgentGitForm.pushPolicy, auth_method: createAgentGitForm.authMethod,
          credential_secret_ref: gitCredentialSecretRef,
        } : undefined,
        github_config: createAgentGitHubForm.enabled ? { credential_secret_ref: githubCredentialSecretRef } : undefined,
      };
      const created = await createAgent(token, namespace, payload);
      setAgentCreateMode(false);
      setCreateAgentRuntimeKind("opencode");
      setCreateAgentMcpConnectionIds([]);
      setCreateAgentMcpServersText(""); setCreateAgentMcpSidecarsText(""); setCreateAgentA2AAllowedCallersText("");
      setCreateAgentSkillFileDrafts([]); setCreateAgentOpenCodeConfigFileDrafts([]);
      setCreateAgentGitForm({ enabled: false, repoUrl: "", authMethod: "token", pushPolicy: "after-each-commit", defaultBranch: "main", branch: "", token: "", username: "", password: "", sshPrivateKey: "" });
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
    createAgentMcpConnectionIds, createAgentMcpServersText, createAgentMcpSidecarsText, createAgentA2AAllowedCallersText,
    createAgentSkillFileDrafts, createAgentOpenCodeConfigFileDrafts, createAgentGitForm, createAgentGitHubForm, refreshWorkspaceData]);

  const handleSaveAgent = useCallback(async (
    payload: UpdateAgentPayload,
    a2aAllowedCallersText: string,
    skillFiles: Record<string, string>,
    opencodeConfigFiles: Record<string, unknown>,
  ) => {
    if (!token.trim() || !selectedAgentName) return;
    setSavingAgent(true); setAgentManageError("");
    try {
      const promptValidationError = systemPromptLengthError(payload.system_prompt ?? "");
      if (promptValidationError) {
        setAgentManageError(promptValidationError);
        toast.error("Failed to save agent", { description: promptValidationError });
        return;
      }
      const allowedCallers = parseA2APeerRefsText(a2aAllowedCallersText);
      const nextRuntimeKind = payload.runtime_kind ?? selectedAgentDetail?.runtime_kind ?? "opencode";
      const nextPayload: UpdateAgentPayload = {
        ...payload,
        runtime_kind: nextRuntimeKind,
        a2a_config: { allowed_callers: allowedCallers },
        skills: { files: skillFiles },
        opencode_config_files: nextRuntimeKind === "opencode" ? opencodeConfigFiles : undefined,
        github_config: null,
      };
      const updated = await updateAgent(token, namespace, selectedAgentName, nextPayload);
      setSelectedAgentDetail(updated);
      setAgentDetailCache((current) => stableAgentDetailCacheUpdate(current, [updated]));
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
      setAgentDetailCache((current) => {
        const { [agentName]: _removed, ...rest } = current;
        return rest;
      });
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

  const handleTriggerWorkflow = useCallback(async (name: string, input?: string, factoryMode?: FactoryMode) => {
    if (!token.trim()) return;
    setRunningWorkflow(true); setWorkflowError("");
    try {
      const effectiveFactoryMode = factoryMode ?? (isFactoryWorkflowName(name) ? (factoryWorkflowModeByName[name] ?? DEFAULT_FACTORY_MODE) : undefined);
      const updated = await triggerWorkflow(token, namespace, name, input, effectiveFactoryMode);
      // Optimistically merge the returned resource so the polling effect
      // can detect the phase change immediately instead of waiting for the
      // next 10-second workspace refresh.
      setWorkflows((prev) => prev.map((w) => (w.name === updated.name ? updated : w)));
      toast.success("Workflow triggered");
    }
    catch (err) { const msg = apiErrorMessage(err); setWorkflowError(msg); toast.error("Failed to trigger workflow", { description: msg }); }
    finally { setRunningWorkflow(false); }
  }, [token, namespace, factoryWorkflowModeByName]);

  const setSelectedFactoryWorkflowMode = useCallback((value: FactoryMode) => {
    if (!selectedWorkflowName) return;
    setWorkflowError("");
    setFactoryWorkflowModeByName((prev) => ({ ...prev, [selectedWorkflowName]: value }));
  }, [selectedWorkflowName]);

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

  const handleRetryFailedSteps = useCallback(async (name: string) => {
    if (!token.trim()) return;
    setRetryingWorkflow(true); setWorkflowError("");
    try {
      const updated = await retryFailedSteps(token, namespace, name);
      setWorkflows((prev) => prev.map((w) => (w.name === updated.name ? updated : w)));
      toast.success("Retrying failed steps");
    }
    catch (err) { const msg = apiErrorMessage(err); setWorkflowError(msg); toast.error("Failed to retry failed steps", { description: msg }); }
    finally { setRetryingWorkflow(false); }
  }, [token, namespace]);

  const handleSelectResource = useCallback((name: string) => {
    if (activeView === "agents" || activeView === "chat") {
      setAgentCreateMode(false);
      setSelectedAgentName(name);
      if (activeView === "chat") {
        setAgentViewTab("chat");
        setChatFocused(false);
      }
    }
    else if (activeView === "workflows" || activeView === "composer" || activeView === "intelligence") { setWorkflowCreateMode(false); setSelectedWorkflowName(name); }
    else if (activeView === "policies") { setSelectedPolicyName(name); }
  }, [activeView]);

  const handleCreateNew = useCallback(() => {
    setWorkspaceError(""); setCreateError(""); setAgentManageError(""); setWorkflowError("");
    if (activeView === "agents") { setAgentCreateMode(true); setSelectedAgentName(""); }
    else if (activeView === "chat") { setActiveView("agents"); setAgentCreateMode(true); setSelectedAgentName(""); setChatFocused(false); }
    else if (activeView === "workflows" || activeView === "composer") { setWorkflowCreateMode(true); setSelectedWorkflowName(""); }
  }, [activeView]);

  const navigateToResource = useCallback((view: WorkspaceView, name?: string) => {
    setActiveView(view);
    setInspectorOpen(false);

    if (view === "agents" || view === "chat") {
      setAgentCreateMode(false);
      setSelectedAgentName(name ?? "");
      if (view === "chat") {
        setAgentViewTab("chat");
        setChatFocused(false);
      }
      return;
    }

    if (view === "workflows" || view === "composer") {
      setWorkflowCreateMode(false);
      setSelectedWorkflowName(name ?? "");
      return;
    }

    if (view === "policies") {
      setSelectedPolicyName(name ?? "");
      return;
    }

    if (view === "catalog") {
      setCatalogTab("mcp");
      return;
    }

    if (view === "intelligence") {
      setIntelligenceTab("observatory");
    }
  }, []);

  const openObservatoryForWorkflowRun = useCallback((workflowName: string, runId?: string | null) => {
    setIntelligenceTab("observatory");
    setActiveView("intelligence");
    setInspectorOpen(false);
    setObservatoryFocus({ workflowName, runId: runId ?? null, requestedAt: Date.now() });
  }, []);

  const clearObservatoryFocus = useCallback(() => {
    setObservatoryFocus(null);
  }, []);

  const ctxValue = useMemo<WorkspaceContextValue>(() => ({
    agents, policies, workflows, selectedAgentDetail, selectedRuntimeKind, selectedPolicyName,
    activeView, selectedAgentName, selectedWorkflowName,
    agentCreateMode, workflowCreateMode,
    setActiveView, setSelectedAgentName, setAgentCreateMode, setWorkflowCreateMode, setSelectedAgentDetail,
    catalogLoading, workspaceError, setWorkspaceError, agentManageError, setAgentManageError, workflowError,
    discoverablePeers, discoveryLoading, discoveryError,
    savingAgent, deletingAgent, isCreatingAgent, savingWorkflow, deletingWorkflow, runningWorkflow, cancellingWorkflow, retryingWorkflow,
    sidebarCollapsed, setSidebarCollapsed, inspectorOpen, setInspectorOpen, agentViewTab, setAgentViewTab, catalogTab, setCatalogTab, intelligenceTab, setIntelligenceTab, configPanelCollapsed, setConfigPanelCollapsed, chatFocused, setChatFocused,
    createAgentName, createAgentModel, createAgentSystemPrompt, createAgentRuntimeKind, createAgentMcpConnectionIds,
    createAgentMcpServersText, createAgentMcpSidecarsText, createAgentA2AAllowedCallersText,
    createAgentSkillFileDrafts, createAgentOpenCodeConfigFileDrafts, createAgentGitForm, createAgentGitHubForm, createError,
    setCreateAgentName, setCreateAgentModel, setCreateAgentSystemPrompt, setCreateAgentRuntimeKind, setCreateAgentMcpConnectionIds,
    setCreateAgentMcpServersText, setCreateAgentMcpSidecarsText, setCreateAgentA2AAllowedCallersText,
    setCreateAgentSkillFileDrafts, setCreateAgentOpenCodeConfigFileDrafts, setCreateAgentGitForm, setCreateAgentGitHubForm,
    sidebarCounts, sidebarItems, sidebarSelectedId, emptySidebarMessage, selectedAgent, selectedWorkflow, selectedFactoryWorkflowMode, setSelectedFactoryWorkflowMode, observatoryFocus,
    refreshWorkspaceData, handleCreateAgent, handleSaveAgent, handleDeleteAgent,
    handleCreateWorkflow, handleUpdateWorkflow, handleDeleteWorkflow, handleTriggerWorkflow, handleCancelWorkflow, handleRetryFailedSteps,
    handleSelectResource, handleCreateNew, navigateToResource, openObservatoryForWorkflowRun, clearObservatoryFocus,
    selectPolicy: (name: string) => setSelectedPolicyName(name),
  }), [
    agents, policies, workflows, selectedAgentDetail, selectedRuntimeKind, selectedPolicyName,
    activeView, selectedAgentName, selectedWorkflowName,
    agentCreateMode, workflowCreateMode,
    catalogLoading, workspaceError, agentManageError, workflowError,
    discoverablePeers, discoveryLoading, discoveryError,
    savingAgent, deletingAgent, isCreatingAgent, savingWorkflow, deletingWorkflow, runningWorkflow, cancellingWorkflow, retryingWorkflow,
    sidebarCollapsed, inspectorOpen, agentViewTab, catalogTab, intelligenceTab, configPanelCollapsed, chatFocused,
    createAgentName, createAgentModel, createAgentSystemPrompt, createAgentRuntimeKind, createAgentMcpConnectionIds,
    createAgentMcpServersText, createAgentMcpSidecarsText, createAgentA2AAllowedCallersText,
    createAgentSkillFileDrafts, createAgentOpenCodeConfigFileDrafts, createAgentGitForm, createAgentGitHubForm, createError,
    sidebarCounts, sidebarItems, sidebarSelectedId, emptySidebarMessage, selectedAgent, selectedWorkflow, selectedFactoryWorkflowMode, observatoryFocus,
    refreshWorkspaceData, handleCreateAgent, handleSaveAgent, handleDeleteAgent,
    handleCreateWorkflow, handleUpdateWorkflow, handleDeleteWorkflow, handleTriggerWorkflow, handleCancelWorkflow, handleRetryFailedSteps,
    handleSelectResource, handleCreateNew, navigateToResource, setSelectedFactoryWorkflowMode, openObservatoryForWorkflowRun, clearObservatoryFocus,
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
