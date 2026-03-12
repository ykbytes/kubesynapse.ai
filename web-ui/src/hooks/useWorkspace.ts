import { useCallback, useEffect, useState } from "react";
import {
  createAgent,
  createEval,
  createWorkflow,
  deleteAgent,
  deleteEval,
  deleteWorkflow,
  discoverAgentPeers,
  fetchAgent,
  listAgents,
  listEvals,
  listPolicies,
  listWorkflows,
  updateAgent,
  updateEval,
  updateWorkflow,
} from "@/lib/api";
import { parseA2APeerRefsText } from "@/lib/a2a";
import type {
  AgentDetail,
  AgentDiscoveryPeer,
  AgentInfo,
  CreateAgentPayload,
  EvalInfo,
  EvalPayload,
  EvalUpdatePayload,
  PolicyInfo,
  UpdateAgentPayload,
  WorkflowInfo,
  WorkflowPayload,
  WorkflowUpdatePayload,
  WorkspaceView,
} from "@/types";

export function useWorkspace(token: string, namespace: string) {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [policies, setPolicies] = useState<PolicyInfo[]>([]);
  const [workflows, setWorkflows] = useState<WorkflowInfo[]>([]);
  const [evals, setEvals] = useState<EvalInfo[]>([]);

  const [activeView, setActiveView] = useState<WorkspaceView>("agents");
  const [selectedAgentName, setSelectedAgentName] = useState("");
  const [selectedWorkflowName, setSelectedWorkflowName] = useState("");
  const [selectedEvalName, setSelectedEvalName] = useState("");
  const [agentCreateMode, setAgentCreateMode] = useState(false);
  const [workflowCreateMode, setWorkflowCreateMode] = useState(false);
  const [evalCreateMode, setEvalCreateMode] = useState(false);
  const [selectedAgentDetail, setSelectedAgentDetail] = useState<AgentDetail | null>(null);

  const [catalogLoading, setCatalogLoading] = useState(false);
  const [workspaceError, setWorkspaceError] = useState("");

  const [savingAgent, setSavingAgent] = useState(false);
  const [deletingAgent, setDeletingAgent] = useState(false);
  const [savingWorkflow, setSavingWorkflow] = useState(false);
  const [deletingWorkflow, setDeletingWorkflow] = useState(false);
  const [savingEval, setSavingEval] = useState(false);
  const [deletingEval, setDeletingEval] = useState(false);

  const [discoverablePeers, setDiscoverablePeers] = useState<AgentDiscoveryPeer[]>([]);
  const [discoveryLoading, setDiscoveryLoading] = useState(false);
  const [discoveryError, setDiscoveryError] = useState("");

  const [agentManageError, setAgentManageError] = useState("");
  const [workflowError, setWorkflowError] = useState("");
  const [evalError, setEvalError] = useState("");

  const refreshWorkspaceData = useCallback(
    async (options?: { silent?: boolean }) => {
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
      } catch (err) {
        if (!silent) {
          setWorkspaceError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (!silent) {
          setCatalogLoading(false);
        }
      }
    },
    [token, namespace],
  );

  // Periodic refresh
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
    const timer = window.setInterval(() => void refreshWorkspaceData({ silent: true }), 10_000);
    return () => window.clearInterval(timer);
  }, [token, namespace, refreshWorkspaceData]);

  // Auto-select first resource
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
  }, [
    activeView,
    agents,
    workflows,
    evals,
    agentCreateMode,
    workflowCreateMode,
    evalCreateMode,
    selectedAgentName,
    selectedWorkflowName,
    selectedEvalName,
  ]);

  // Fetch agent detail
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
      .catch((err) => {
        if (!cancelled) {
          setAgentManageError(err instanceof Error ? err.message : String(err));
          setSelectedAgentDetail(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [token, namespace, selectedAgentName, agentCreateMode]);

  // Peer discovery
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
      .catch((err) => {
        if (!cancelled) {
          setDiscoverablePeers([]);
          setDiscoveryError(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!cancelled) setDiscoveryLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token, namespace, selectedAgentName, agentCreateMode, selectedAgentDetail?.policy_ref, agents]);

  const handleCreateAgent = useCallback(
    async (payload: CreateAgentPayload) => {
      const created = await createAgent(token, namespace, payload);
      setAgentCreateMode(false);
      setSelectedAgentName(created.name);
      await refreshWorkspaceData({ silent: false });
      setWorkspaceError("Agent created. Provisioning may take a few seconds before the runtime is ready.");
      return created;
    },
    [token, namespace, refreshWorkspaceData],
  );

  const handleSaveAgent = useCallback(
    async (payload: UpdateAgentPayload, a2aAllowedCallersText: string, skillFiles: Record<string, string>, gooseConfigFiles: Record<string, unknown>) => {
      if (!token.trim() || !selectedAgentName) return;
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
      } catch (err) {
        setAgentManageError(err instanceof Error ? err.message : String(err));
      } finally {
        setSavingAgent(false);
      }
    },
    [token, namespace, selectedAgentName, refreshWorkspaceData],
  );

  const handleDeleteAgent = useCallback(async () => {
    if (!token.trim() || !selectedAgentName) return;
    setDeletingAgent(true);
    setAgentManageError("");
    try {
      await deleteAgent(token, namespace, selectedAgentName);
      setSelectedAgentName("");
      setSelectedAgentDetail(null);
      setAgentCreateMode(agents.length <= 1);
      await refreshWorkspaceData({ silent: false });
    } catch (err) {
      setAgentManageError(err instanceof Error ? err.message : String(err));
    } finally {
      setDeletingAgent(false);
    }
  }, [token, namespace, selectedAgentName, agents.length, refreshWorkspaceData]);

  const handleCreateWorkflow = useCallback(
    async (payload: WorkflowPayload) => {
      if (!token.trim()) return;
      setSavingWorkflow(true);
      setWorkflowError("");
      try {
        const created = await createWorkflow(token, namespace, payload);
        setWorkflowCreateMode(false);
        setSelectedWorkflowName(created.name);
        await refreshWorkspaceData({ silent: false });
        setWorkspaceError("Workflow created. The operator will queue it immediately.");
      } catch (err) {
        setWorkflowError(err instanceof Error ? err.message : String(err));
      } finally {
        setSavingWorkflow(false);
      }
    },
    [token, namespace, refreshWorkspaceData],
  );

  const handleUpdateWorkflow = useCallback(
    async (name: string, payload: WorkflowUpdatePayload) => {
      if (!token.trim()) return;
      setSavingWorkflow(true);
      setWorkflowError("");
      try {
        await updateWorkflow(token, namespace, name, payload);
        await refreshWorkspaceData({ silent: false });
      } catch (err) {
        setWorkflowError(err instanceof Error ? err.message : String(err));
      } finally {
        setSavingWorkflow(false);
      }
    },
    [token, namespace, refreshWorkspaceData],
  );

  const handleDeleteWorkflow = useCallback(
    async (name: string) => {
      if (!token.trim()) return;
      setDeletingWorkflow(true);
      setWorkflowError("");
      try {
        await deleteWorkflow(token, namespace, name);
        setSelectedWorkflowName("");
        setWorkflowCreateMode(workflows.length <= 1);
        await refreshWorkspaceData({ silent: false });
      } catch (err) {
        setWorkflowError(err instanceof Error ? err.message : String(err));
      } finally {
        setDeletingWorkflow(false);
      }
    },
    [token, namespace, workflows.length, refreshWorkspaceData],
  );

  const handleCreateEval = useCallback(
    async (payload: EvalPayload) => {
      if (!token.trim()) return;
      setSavingEval(true);
      setEvalError("");
      try {
        const created = await createEval(token, namespace, payload);
        setEvalCreateMode(false);
        setSelectedEvalName(created.name);
        await refreshWorkspaceData({ silent: false });
        setWorkspaceError("Evaluation created. The operator will queue it immediately.");
      } catch (err) {
        setEvalError(err instanceof Error ? err.message : String(err));
      } finally {
        setSavingEval(false);
      }
    },
    [token, namespace, refreshWorkspaceData],
  );

  const handleUpdateEval = useCallback(
    async (name: string, payload: EvalUpdatePayload) => {
      if (!token.trim()) return;
      setSavingEval(true);
      setEvalError("");
      try {
        await updateEval(token, namespace, name, payload);
        await refreshWorkspaceData({ silent: false });
      } catch (err) {
        setEvalError(err instanceof Error ? err.message : String(err));
      } finally {
        setSavingEval(false);
      }
    },
    [token, namespace, refreshWorkspaceData],
  );

  const handleDeleteEval = useCallback(
    async (name: string) => {
      if (!token.trim()) return;
      setDeletingEval(true);
      setEvalError("");
      try {
        await deleteEval(token, namespace, name);
        setSelectedEvalName("");
        setEvalCreateMode(evals.length <= 1);
        await refreshWorkspaceData({ silent: false });
      } catch (err) {
        setEvalError(err instanceof Error ? err.message : String(err));
      } finally {
        setDeletingEval(false);
      }
    },
    [token, namespace, evals.length, refreshWorkspaceData],
  );

  const handleSelectResource = useCallback(
    (name: string) => {
      if (activeView === "agents") {
        setAgentCreateMode(false);
        setSelectedAgentName(name);
      } else if (activeView === "workflows") {
        setWorkflowCreateMode(false);
        setSelectedWorkflowName(name);
      } else {
        setEvalCreateMode(false);
        setSelectedEvalName(name);
      }
    },
    [activeView],
  );

  const handleCreateNew = useCallback(() => {
    setWorkspaceError("");
    setAgentManageError("");
    setWorkflowError("");
    setEvalError("");
    if (activeView === "agents") {
      setAgentCreateMode(true);
      setSelectedAgentName("");
    } else if (activeView === "workflows") {
      setWorkflowCreateMode(true);
      setSelectedWorkflowName("");
    } else {
      setEvalCreateMode(true);
      setSelectedEvalName("");
    }
  }, [activeView]);

  return {
    // Data
    agents,
    policies,
    workflows,
    evals,
    // View & selection
    activeView,
    setActiveView,
    selectedAgentName,
    setSelectedAgentName,
    selectedWorkflowName,
    selectedEvalName,
    agentCreateMode,
    setAgentCreateMode,
    workflowCreateMode,
    evalCreateMode,
    selectedAgentDetail,
    setSelectedAgentDetail,
    // Loading
    catalogLoading,
    // Errors
    workspaceError,
    setWorkspaceError,
    agentManageError,
    setAgentManageError,
    workflowError,
    evalError,
    // Discovery
    discoverablePeers,
    discoveryLoading,
    discoveryError,
    // Operation flags
    savingAgent,
    deletingAgent,
    savingWorkflow,
    deletingWorkflow,
    savingEval,
    deletingEval,
    // Actions
    refreshWorkspaceData,
    handleCreateAgent,
    handleSaveAgent,
    handleDeleteAgent,
    handleCreateWorkflow,
    handleUpdateWorkflow,
    handleDeleteWorkflow,
    handleCreateEval,
    handleUpdateEval,
    handleDeleteEval,
    handleSelectResource,
    handleCreateNew,
  };
}
