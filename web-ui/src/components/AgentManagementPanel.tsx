import {
  Bell,
  Calendar,
  Copy,
  LoaderCircle,
  Package,
  Play,
  Plus,
  Radar,
  RefreshCw,
  Save,
  Search,
  Shield,
  ShieldCheck,
  Sparkles,
  Trash2,
  Wand2,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { ConfirmDialog } from "./ConfirmDialog";
import { ModelSelector } from "@/components/ModelSelector";
import { A2A_ALLOWED_CALLERS_PLACEHOLDER, stringifyA2APeerRefs } from "../lib/a2a";
import {
  buildOpenCodeConfigFiles,
  createOpenCodeConfigFileDraft,
  opencodeConfigFileDraftsFromFiles,
} from "../lib/opencodeConfig";
import {
  MCP_SIDECARS_PLACEHOLDER,
  MCP_SERVERS_PLACEHOLDER,
  formatContainerImageDisplay,
  parseMcpServersText,
  parseMcpSidecarsText,
  stringifyMcpServers,
  stringifyMcpSidecars,
} from "../lib/mcp";
import { buildSkillFiles, createSkillFileDraft, skillFileDraftsFromFiles } from "../lib/skills";
import { deriveAgentVisualSignals, getRuntimeSignal } from "@/lib/agentSignals";
import {
  fetchCatalogSkillDetail, fetchMcpConnections, fetchMcpRegistry, fetchSkillsCatalog, refreshSkillsCatalog, createMcpConnection, apiErrorMessage,
  fetchIntelligenceCollectors, fetchIntelligenceSchedules, createIntelligenceSchedule, deleteIntelligenceSchedule,
  fetchIntelligenceAlerts, createIntelligenceAlert, deleteIntelligenceAlert, fetchAlertHistory, fetchPromptContext,
} from "../lib/api";
import type {
  IntelligenceCollector, IntelligenceSchedule, IntelligenceAlert as IntelAlert,
  AlertHistoryEntry, CreateSchedulePayload, CreateAlertPayload,
} from "../lib/api";
import type {
  AgentDetail,
  AgentInfo,
  CatalogSkill,
  CatalogSkillDetail,
  GitConfig,
  McpConnection,
  McpRegistryServer,
  PolicyInfo,
  RuntimeKind,
  TextFileDraft,
  UpdateAgentPayload,
  WorkflowInfo,
} from "../types";
import { A2ACallerPicker } from "./A2ACallerPicker";
import { McpServerBadgeIcon } from "./McpServerBadgeIcon";
import { TextFileBundleEditor } from "./TextFileBundleEditor";
import { useConnection } from "@/contexts/ConnectionContext";
import { useWorkspace } from "@/contexts/WorkspaceContext";
import { SYSTEM_PROMPT_MAX_CHARS, systemPromptLengthError } from "../lib/agentPrompt";

const SKILL_CATEGORY_STYLES: Record<string, string> = {
  design: "border-fuchsia-500/30 bg-fuchsia-500/10 text-fuchsia-200",
  development: "border-sky-500/30 bg-sky-500/10 text-sky-200",
  document: "border-amber-500/30 bg-amber-500/10 text-amber-200",
  communication: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
  productivity: "border-cyan-500/30 bg-cyan-500/10 text-cyan-200",
};

const MCP_SUPPORT_BADGE_STYLES = {
  ready: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  limited: "border-amber-500/30 bg-amber-500/10 text-amber-300",
  planned: "border-slate-500/30 bg-slate-500/10 text-slate-300",
} as const;

const MCP_VALIDATION_BADGE_STYLES = {
  draft: "border-slate-500/30 bg-slate-500/10 text-slate-300",
  valid: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  warning: "border-amber-500/30 bg-amber-500/10 text-amber-300",
  invalid: "border-destructive/30 bg-destructive/10 text-destructive",
} as const;

const PANEL_CARD_CLASS = "border-border/80 bg-background/80 shadow-sm";
const METRIC_PANEL_CLASS = "rounded-lg border px-3 py-1.5 shadow-sm";

type ConnectionFilterValue = "all" | "selected" | "remote" | "hub" | "sidecar";

function normalizeDraftPath(path: string): string {
  return path.replace(/\\+/g, "/").trim();
}

function mergeSkillDrafts(drafts: TextFileDraft[], detail: CatalogSkillDetail): TextFileDraft[] {
  const nextDrafts = [...drafts];
  const pathToIndex = new Map(nextDrafts.map((draft, index) => [normalizeDraftPath(draft.path), index]));
  for (const [path, content] of Object.entries(detail.assets)) {
    const normalizedPath = normalizeDraftPath(path);
    const existingIndex = pathToIndex.get(normalizedPath);
    if (existingIndex === undefined) {
      pathToIndex.set(normalizedPath, nextDrafts.length);
      nextDrafts.push(createSkillFileDraft({ path: normalizedPath, content }));
      continue;
    }
    nextDrafts[existingIndex] = { ...nextDrafts[existingIndex], path: normalizedPath, content };
  }
  return nextDrafts;
}

function removeSkillDrafts(drafts: TextFileDraft[], detail: CatalogSkillDetail): TextFileDraft[] {
  const managedPaths = new Set(Object.keys(detail.assets).map(normalizeDraftPath));
  return drafts.filter((draft) => !managedPaths.has(normalizeDraftPath(draft.path)));
}

function hasSkillAttached(detail: CatalogSkillDetail | undefined, draftPaths: Set<string>): boolean {
  if (!detail) return false;
  return Object.keys(detail.assets).every((path) => draftPaths.has(normalizeDraftPath(path)));
}

function normalizeStringList(values: string[]): string[] {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))].sort((left, right) => left.localeCompare(right));
}

function savedConnectionIdsFromAgent(agent: AgentDetail): string[] {
  return normalizeStringList(
    agent.mcp_connections
      .map((connection) => connection.connection_id ?? "")
      .filter((connectionId): connectionId is string => Boolean(connectionId)),
  );
}

function buildSidecarPreview(connection: McpConnection): Record<string, unknown> | null {
  if (connection.transport !== "sidecar") {
    return null;
  }
  const preview = connection.runtime_preview?.sidecar;
  const rawPort = preview?.port ?? connection.config.sidecar_port;
  const parsedPort = typeof rawPort === "number" ? rawPort : Number(rawPort ?? 8097);
  return {
    name: preview?.name ?? connection.server_id ?? connection.slug,
    image: preview?.image ?? String(connection.config.sidecar_image ?? ""),
    port: Number.isFinite(parsedPort) ? parsedPort : 8097,
  };
}

function formatConnectionRuntimeSummary(connection: McpConnection): string {
  if (connection.transport === "sidecar") {
    const preview = connection.runtime_preview?.sidecar;
    const rawPort = preview?.port ?? connection.config.sidecar_port;
    const port = typeof rawPort === "number" ? rawPort : Number(rawPort ?? NaN);
    const image = typeof preview?.image === "string" && preview.image.trim() ? preview.image : "";
    const label = image ? formatContainerImageDisplay(image) : "Pod sidecar";
    return Number.isFinite(port) ? `${label} on port ${port}` : label;
  }
  if (connection.transport === "remote") {
    const previewUrl = typeof connection.runtime_preview?.url === "string" ? connection.runtime_preview.url.trim() : "";
    if (previewUrl) {
      return previewUrl.replace(/^https?:\/\//, "");
    }
    return connection.status_reason?.trim() || "Remote MCP endpoint";
  }
  return connection.status_reason?.trim() || "Shared namespace hub route";
}

interface AgentManagementPanelProps {
  token: string;
  agent: AgentDetail;
  policies: PolicyInfo[];
  agents: AgentInfo[];
  workflows: WorkflowInfo[];
  isSaving: boolean;
  isDeleting: boolean;
  error: string;
  onSave: (
    payload: UpdateAgentPayload,
    a2aAllowedCallersText: string,
    skillFiles: Record<string, string>,
    opencodeConfigFiles: Record<string, unknown>,
  ) => void;
  onDelete: () => void;
  onClone?: () => void;
  onInjectPrompt?: (text: string) => void;
}

export function AgentManagementPanel({
  token,
  agent,
  policies,
  agents: workspaceAgents,
  workflows: workspaceWorkflows,
  isSaving,
  isDeleting,
  error,
  onSave,
  onDelete,
  onClone,
  onInjectPrompt,
}: AgentManagementPanelProps) {
  const ws = useWorkspace();
  const { namespace, canMutate } = useConnection();
  const [model, setModel] = useState(agent.model);
  const [systemPrompt, setSystemPrompt] = useState(agent.system_prompt);
  const [policyRef, setPolicyRef] = useState(agent.policy_ref ?? "");
  const [storageSize, setStorageSize] = useState(agent.storage_size ?? "1Gi");
  const [runtimeKind, setRuntimeKind] = useState<RuntimeKind>(agent.runtime_kind ?? "opencode");
  const [enableGvisor, setEnableGvisor] = useState(agent.enable_gvisor);
  const [mcpConnectionIds, setMcpConnectionIds] = useState(savedConnectionIdsFromAgent(agent));
  const [mcpServersText, setMcpServersText] = useState(stringifyMcpServers(agent.mcp_servers));
  const [mcpSidecarsText, setMcpSidecarsText] = useState(stringifyMcpSidecars(agent.mcp_sidecars));
  const [a2aAllowedCallersText, setA2aAllowedCallersText] = useState(stringifyA2APeerRefs(agent.a2a_config.allowed_callers));
  const [skillFileDrafts, setSkillFileDrafts] = useState(skillFileDraftsFromFiles(agent.skills.files));
  const [opencodeConfigFileDrafts, setOpenCodeConfigFileDrafts] = useState(opencodeConfigFileDraftsFromFiles(agent.opencode_config_files));
  const [localError, setLocalError] = useState("");
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [connectionSearch, setConnectionSearch] = useState("");
  const [connectionFilter, setConnectionFilter] = useState<ConnectionFilterValue>("all");
  const baselineConnectionIds = useMemo(() => savedConnectionIdsFromAgent(agent), [agent]);

  // Intelligence tab state
  const [intelCollectors, setIntelCollectors] = useState<IntelligenceCollector[]>([]);
  const [intelSchedules, setIntelSchedules] = useState<IntelligenceSchedule[]>([]);
  const [intelAlerts, setIntelAlerts] = useState<IntelAlert[]>([]);
  const [intelHistory, setIntelHistory] = useState<AlertHistoryEntry[]>([]);
  const [intelLoading, setIntelLoading] = useState(false);
  const [promptLoading, setPromptLoading] = useState(false);
  const [promptResult, setPromptResult] = useState("");
  // Schedule form
  const [schedName, setSchedName] = useState("");
  const [schedCron, setSchedCron] = useState("*/30 * * * *");
  const [schedCollector, setSchedCollector] = useState("");
  const [schedBuiltin, setSchedBuiltin] = useState("node_health");
  const [schedEnabled, setSchedEnabled] = useState(true);
  // Alert form
  const [alertName, setAlertName] = useState("");
  const [alertScheduleId, setAlertScheduleId] = useState("");
  const [alertCondType, setAlertCondType] = useState<"contains" | "not_contains" | "exit_code" | "regex">("contains");
  const [alertCondValue, setAlertCondValue] = useState("");
  const [alertAction, setAlertAction] = useState<"notify" | "invoke_agent">("notify");
  const [alertPromptTemplate, setAlertPromptTemplate] = useState("Intelligence alert fired. Output:\n{{output}}\n\nPlease investigate.");
  const systemPromptError = useMemo(() => systemPromptLengthError(systemPrompt), [systemPrompt]);

  // Track whether any field has been edited
  const isDirty = useMemo(() => {
    return (
      model !== agent.model ||
      systemPrompt !== agent.system_prompt ||
      policyRef !== (agent.policy_ref ?? "") ||
      storageSize !== (agent.storage_size ?? "1Gi") ||
      runtimeKind !== (agent.runtime_kind ?? "opencode") ||
      enableGvisor !== agent.enable_gvisor ||
      JSON.stringify(normalizeStringList(mcpConnectionIds)) !== JSON.stringify(baselineConnectionIds) ||
      mcpServersText !== stringifyMcpServers(agent.mcp_servers) ||
      mcpSidecarsText !== stringifyMcpSidecars(agent.mcp_sidecars) ||
      a2aAllowedCallersText !== stringifyA2APeerRefs(agent.a2a_config.allowed_callers) ||
      JSON.stringify(skillFileDrafts) !== JSON.stringify(skillFileDraftsFromFiles(agent.skills.files)) ||
      JSON.stringify(opencodeConfigFileDrafts) !== JSON.stringify(opencodeConfigFileDraftsFromFiles(agent.opencode_config_files))
    );
  }, [
    model, systemPrompt, policyRef, storageSize, runtimeKind, enableGvisor,
    mcpConnectionIds, mcpServersText, mcpSidecarsText, a2aAllowedCallersText,
    skillFileDrafts, opencodeConfigFileDrafts,
    baselineConnectionIds, agent,
  ]);

  // Catalog state
  const [catalogSkills, setCatalogSkills] = useState<CatalogSkill[]>([]);
  const [mcpConnections, setMcpConnections] = useState<McpConnection[]>([]);
  const [mcpRegistry, setMcpRegistry] = useState<McpRegistryServer[]>([]);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [catalogError, setCatalogError] = useState("");
  const [quickAddBusyId, setQuickAddBusyId] = useState("");
  const [skillSearch, setSkillSearch] = useState("");
  const [skillCategory, setSkillCategory] = useState("");
  const [skillDetailsById, setSkillDetailsById] = useState<Record<string, CatalogSkillDetail>>({});
  const [skillBusyId, setSkillBusyId] = useState("");
  const [gitConfig, setGitConfig] = useState<GitConfig | null>(agent.git_config ?? null);

  useEffect(() => {
    setModel(agent.model);
    setSystemPrompt(agent.system_prompt);
    setPolicyRef(agent.policy_ref ?? "");
    setStorageSize(agent.storage_size ?? "1Gi");
    setRuntimeKind(agent.runtime_kind ?? "opencode");
    setEnableGvisor(agent.enable_gvisor);
    setMcpConnectionIds(savedConnectionIdsFromAgent(agent));
    setMcpServersText(stringifyMcpServers(agent.mcp_servers));
    setMcpSidecarsText(stringifyMcpSidecars(agent.mcp_sidecars));
    setA2aAllowedCallersText(stringifyA2APeerRefs(agent.a2a_config.allowed_callers));
    setSkillFileDrafts(skillFileDraftsFromFiles(agent.skills.files));
    setOpenCodeConfigFileDrafts(opencodeConfigFileDraftsFromFiles(agent.opencode_config_files));
    setGitConfig(agent.git_config ?? null);
    setConnectionSearch("");
    setConnectionFilter("all");
    setLocalError("");
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agent.name]);

  // Fetch catalog tools and skills
  useEffect(() => {
    if (!token.trim()) {
      setCatalogSkills([]);
      setMcpConnections([]);
      setMcpRegistry([]);
      setCatalogError("");
      return;
    }
    let cancelled = false;
    setCatalogLoading(true);
    setCatalogError("");
    Promise.all([fetchSkillsCatalog(token), fetchMcpConnections(token, namespace), fetchMcpRegistry(token)])
      .then(([skills, savedConnections, registry]) => {
        if (!cancelled) {
          setCatalogSkills(skills);
          setMcpConnections(savedConnections);
          setMcpRegistry(registry);
        }
      })
      .catch((nextError) => {
        if (!cancelled) setCatalogError(apiErrorMessage(nextError));
      })
      .finally(() => {
        if (!cancelled) setCatalogLoading(false);
      });
    return () => { cancelled = true; };
  }, [token, namespace]);

  // Fetch intelligence data (collectors, schedules, alerts, history)
  const loadIntelligenceData = async () => {
    if (!token.trim()) return;
    setIntelLoading(true);
    try {
      const [colRes, schRes, alRes, hRes] = await Promise.all([
        fetchIntelligenceCollectors(token, namespace),
        fetchIntelligenceSchedules(token, namespace),
        fetchIntelligenceAlerts(token, agent.name, namespace),
        fetchAlertHistory(token, 50, namespace),
      ]);
      setIntelCollectors(colRes.collectors);
      setIntelSchedules(schRes.schedules);
      setIntelAlerts(alRes.alerts);
      setIntelHistory(hRes.history);
    } catch {
      // silently ignore – intelligence tab may just be empty
    } finally {
      setIntelLoading(false);
    }
  };
  useEffect(() => { void loadIntelligenceData(); }, [token, namespace, agent.name]); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleCreateSchedule() {
    if (!schedName.trim() || !schedCron.trim()) return;
    try {
      const body: CreateSchedulePayload = {
        name: schedName.trim(),
        cron: schedCron.trim(),
        collector_id: schedCollector || undefined,
        builtin: schedBuiltin || undefined,
        agent_name: agent.name,
        enabled: schedEnabled,
      };
      await createIntelligenceSchedule(token, body, namespace);
      setSchedName("");
      void loadIntelligenceData();
    } catch (e) {
      setLocalError(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleDeleteSchedule(id: string) {
    try {
      await deleteIntelligenceSchedule(token, id, namespace);
      void loadIntelligenceData();
    } catch (e) {
      setLocalError(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleCreateAlert() {
    if (!alertName.trim() || !alertCondValue.trim()) return;
    try {
      const body: CreateAlertPayload = {
        name: alertName.trim(),
        schedule_id: alertScheduleId || undefined,
        condition_type: alertCondType,
        condition_value: alertCondValue.trim(),
        action: alertAction,
        agent_name: alertAction === "invoke_agent" ? agent.name : undefined,
        prompt_template: alertAction === "invoke_agent" ? alertPromptTemplate : undefined,
        enabled: true,
      };
      await createIntelligenceAlert(token, body, namespace);
      setAlertName("");
      setAlertCondValue("");
      void loadIntelligenceData();
    } catch (e) {
      setLocalError(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleDeleteAlert(id: string) {
    try {
      await deleteIntelligenceAlert(token, id, namespace);
      void loadIntelligenceData();
    } catch (e) {
      setLocalError(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleFetchPromptContext() {
    if (intelCollectors.length === 0) return;
    setPromptLoading(true);
    try {
      const res = await fetchPromptContext(token, {
        collector_id: intelCollectors[0]?.id,
        builtin: "node_health",
      }, namespace);
      setPromptResult(res.context);
    } catch (e) {
      setPromptResult(`Error: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setPromptLoading(false);
    }
  }

  useEffect(() => {
    setLocalError("");
  }, [
    model, systemPrompt, policyRef, storageSize, runtimeKind, enableGvisor,
    mcpConnectionIds, mcpServersText, mcpSidecarsText, a2aAllowedCallersText, skillFileDrafts, opencodeConfigFileDrafts,
  ]);

  // Sidecar parsing
  const sidecarState = useMemo(() => {
    try {
      return { items: parseMcpSidecarsText(mcpSidecarsText), error: "" };
    } catch (nextError) {
      return { items: [] as Array<Record<string, unknown>>, error: nextError instanceof Error ? nextError.message : String(nextError) };
    }
  }, [mcpSidecarsText, runtimeKind]);

  const sharedMcpServers = useMemo(() => parseMcpServersText(mcpServersText), [mcpServersText]);
  const normalizedConnectionIds = useMemo(() => normalizeStringList(mcpConnectionIds), [mcpConnectionIds]);
  const selectedConnections = useMemo(
    () => mcpConnections.filter((connection) => normalizedConnectionIds.includes(connection.id)),
    [mcpConnections, normalizedConnectionIds],
  );
  const selectedConnectionStats = useMemo(
    () => ({
      remote: selectedConnections.filter((connection) => connection.transport === "remote").length,
      hub: selectedConnections.filter((connection) => connection.transport === "hub").length,
      sidecar: selectedConnections.filter((connection) => connection.transport === "sidecar").length,
    }),
    [selectedConnections],
  );
  const usingSavedConnections = normalizedConnectionIds.length > 0;
  const effectiveMcpSidecars = useMemo(() => {
    if (!usingSavedConnections) {
      return sidecarState.items;
    }
    return selectedConnections
      .map((connection) => buildSidecarPreview(connection))
      .filter((connection): connection is Record<string, unknown> => connection !== null);
  }, [selectedConnections, sidecarState.items, usingSavedConnections]);
  const effectiveSharedMcpServers = useMemo(() => {
    if (!usingSavedConnections) {
      return sharedMcpServers;
    }
    return normalizeStringList(
      selectedConnections
        .filter((connection) => connection.transport !== "sidecar")
        .map((connection) => connection.server_id),
    );
  }, [selectedConnections, sharedMcpServers, usingSavedConnections]);

  const selectedToolIds = useMemo(() => {
    const ids = new Set<string>();
    for (const sidecar of effectiveMcpSidecars) {
      const sidecarName = sidecar.name;
      if (typeof sidecarName === "string" && sidecarName.trim()) ids.add(sidecarName.trim());
    }
    return ids;
  }, [effectiveMcpSidecars]);

  // Collector sidecar toggle helper
  const COLLECTOR_SIDECAR_NAME = "collector";
  const COLLECTOR_SIDECAR_IMAGE = "localhost/KubeSynapseai/mcp-collector:dev";
  const COLLECTOR_SIDECAR_PORT = 8100;
  const hasCollectorSidecar = selectedToolIds.has(COLLECTOR_SIDECAR_NAME);

  function handleToggleCollectorSidecar() {
    if (usingSavedConnections) {
      return;
    }
    const nextSidecars = sidecarState.items.filter(
      (s) => !(typeof s.name === "string" && s.name.trim() === COLLECTOR_SIDECAR_NAME),
    );
    if (!hasCollectorSidecar) {
      nextSidecars.push({ name: COLLECTOR_SIDECAR_NAME, image: COLLECTOR_SIDECAR_IMAGE, port: COLLECTOR_SIDECAR_PORT });
    }
    setMcpSidecarsText(stringifyMcpSidecars(nextSidecars));
  }

  function handleToggleSavedConnection(connectionId: string) {
    const connection = mcpConnections.find((item) => item.id === connectionId);
    if (!connection) {
      return;
    }
    if (!connection.attachable) {
      setCatalogError(connection.status_reason ?? `${connection.name} is saved but cannot be attached to agents yet.`);
      return;
    }
    setMcpConnectionIds((current) => (
      current.includes(connectionId)
        ? current.filter((id) => id !== connectionId)
        : [...current, connectionId]
    ));
    setCatalogError("");
  }

  async function handleQuickAddRegistryServer(server: McpRegistryServer) {
    if (!token.trim() || !canMutate) return;
    setQuickAddBusyId(server.id);
    setCatalogError("");
    try {
      const config: Record<string, unknown> = {};
      if (server.transport === "remote" && server.endpoint) {
        config.endpoint_url = server.endpoint;
      }
      if (server.transport === "sidecar" && server.sidecar_port) {
        config.sidecar_port = server.sidecar_port;
      }
      if (server.transport === "sidecar" && server.sidecar_image) {
        config.sidecar_image = server.sidecar_image;
      }
      const created = await createMcpConnection(token, namespace, {
        name: server.name,
        server_id: server.id,
        config,
        credentials: {},
        validate_on_save: false,
      });
      setMcpConnections((current) => [...current, created]);
      setMcpConnectionIds((current) => [...current, created.id]);
      setCatalogError("");
    } catch (err) {
      const msg = apiErrorMessage(err);
      setCatalogError(msg);
    } finally {
      setQuickAddBusyId("");
    }
  }

  function handleOpenMcpManagement() {
    ws.setAgentCreateMode(false);
    ws.setActiveView("mcp");
    setCatalogError("");
  }

  // Skill catalog helpers
  const draftPaths = useMemo(
    () => new Set(skillFileDrafts.map((d) => normalizeDraftPath(d.path)).filter(Boolean)),
    [skillFileDrafts],
  );
  const skillFileDraftsRef = useRef(skillFileDrafts);
  skillFileDraftsRef.current = skillFileDrafts;
  const draftPathsRef = useRef(draftPaths);
  draftPathsRef.current = draftPaths;

  const filteredSkills = useMemo(() => {
    const query = skillSearch.trim().toLowerCase();
    return catalogSkills.filter((skill) => {
      if (skillCategory && skill.category !== skillCategory) return false;
      if (!query) return true;
      return skill.name.toLowerCase().includes(query) || skill.description.toLowerCase().includes(query) || skill.tags.some((t) => t.toLowerCase().includes(query));
    });
  }, [catalogSkills, skillCategory, skillSearch]);

  const selectedCatalogSkills = useMemo(
    () => catalogSkills.filter((skill) => hasSkillAttached(skillDetailsById[skill.id], draftPaths)),
    [catalogSkills, draftPaths, skillDetailsById],
  );

  const skillCategories = useMemo(
    () => [...new Set(catalogSkills.map((s) => s.category).filter(Boolean))].sort(),
    [catalogSkills],
  );

  async function ensureSkillDetail(skillId: string): Promise<CatalogSkillDetail> {
    const cached = skillDetailsById[skillId];
    if (cached) return cached;
    const detail = await fetchCatalogSkillDetail(token, skillId);
    setSkillDetailsById((current) => ({ ...current, [skillId]: detail }));
    return detail;
  }

  async function handleToggleSkill(skillId: string): Promise<void> {
    setCatalogError("");
    setSkillBusyId(skillId);
    try {
      const detail = await ensureSkillDetail(skillId);
      const currentDrafts = skillFileDraftsRef.current;
      const currentPaths = draftPathsRef.current;
      const attached = hasSkillAttached(detail, currentPaths);
      setSkillFileDrafts(attached ? removeSkillDrafts(currentDrafts, detail) : mergeSkillDrafts(currentDrafts, detail));
    } catch (nextError) {
      setCatalogError(nextError instanceof Error ? nextError.message : String(nextError));
    } finally {
      setSkillBusyId("");
    }
  }

  async function handleRefreshCatalog(): Promise<void> {
    setCatalogLoading(true);
    setCatalogError("");
    try {
      await refreshSkillsCatalog(token);
      const [skills, savedConnections] = await Promise.all([fetchSkillsCatalog(token), fetchMcpConnections(token, namespace)]);
      setCatalogSkills(skills);
      setMcpConnections(savedConnections);
      setSkillDetailsById({});
    } catch (nextError) {
      setCatalogError(nextError instanceof Error ? nextError.message : String(nextError));
    } finally {
      setCatalogLoading(false);
    }
  }

  async function handleAutoSelectSkills(): Promise<void> {
    setCatalogError("");
    setCatalogLoading(true);
    try {
      let remaining = catalogSkills;
      const currentPaths = draftPathsRef.current;
      remaining = remaining.filter((s) => !hasSkillAttached(skillDetailsById[s.id], currentPaths));
      let drafts = skillFileDraftsRef.current;
      for (const skill of remaining) {
        const detail = await ensureSkillDetail(skill.id);
        drafts = mergeSkillDrafts(drafts, detail);
      }
      setSkillFileDrafts(drafts);
    } catch (nextError) {
      setCatalogError(nextError instanceof Error ? nextError.message : String(nextError));
    } finally {
      setCatalogLoading(false);
    }
  }

  function handleSaveClick() {
    if (systemPromptError) {
      setLocalError(systemPromptError);
      return;
    }
    try {
      const skillFiles = buildSkillFiles(skillFileDrafts);
      const opencodeConfigFiles = buildOpenCodeConfigFiles(opencodeConfigFileDrafts);
      const mcpServers = usingSavedConnections ? [] : parseMcpServersText(mcpServersText);
      const mcpSidecars = usingSavedConnections ? [] : parseMcpSidecarsText(mcpSidecarsText);
      onSave(
        {
          model: model.trim(),
          system_prompt: systemPrompt,
          policy_ref: policyRef.trim() || undefined,
          storage_size: storageSize.trim() || undefined,
          runtime_kind: runtimeKind,
          enable_gvisor: enableGvisor,
          mcp_connection_ids: usingSavedConnections ? normalizedConnectionIds : [],
          mcp_servers: mcpServers,
          mcp_sidecars: mcpSidecars,
          git_config: gitConfig,
          github_config: null,
        },
        a2aAllowedCallersText,
        skillFiles,
        opencodeConfigFiles,
      );
    } catch (nextError) {
      setLocalError(nextError instanceof Error ? nextError.message : String(nextError));
    }
  }

  const displayError = localError || systemPromptError || error;
  const currentSignals = useMemo(() => deriveAgentVisualSignals({
    runtime_kind: runtimeKind,
    mcp_sidecars: effectiveMcpSidecars,
    mcp_servers: effectiveSharedMcpServers,
    policy_ref: policyRef.trim() || null,
    enable_gvisor: enableGvisor,
    git_config: gitConfig,
    github_config: null,
  }), [runtimeKind, effectiveMcpSidecars, effectiveSharedMcpServers, policyRef, enableGvisor, gitConfig]);
  const capabilityCountLabel = `${currentSignals.capabilities.length} capabilit${currentSignals.capabilities.length === 1 ? "y" : "ies"} attached`;
  const filteredConnections = useMemo(() => {
    const query = connectionSearch.trim().toLowerCase();
    return [...mcpConnections]
      .filter((connection) => {
        if (connectionFilter === "selected" && !normalizedConnectionIds.includes(connection.id)) {
          return false;
        }
        if (connectionFilter !== "all" && connectionFilter !== "selected" && connection.transport !== connectionFilter) {
          return false;
        }
        if (!query) {
          return true;
        }
        return [connection.name, connection.server_name ?? "", connection.server_id, connection.transport]
          .some((value) => value.toLowerCase().includes(query));
      })
      .sort((left, right) => {
        const leftSelected = normalizedConnectionIds.includes(left.id);
        const rightSelected = normalizedConnectionIds.includes(right.id);
        if (leftSelected !== rightSelected) {
          return leftSelected ? -1 : 1;
        }
        if (left.attachable !== right.attachable) {
          return left.attachable ? -1 : 1;
        }
        return left.name.localeCompare(right.name);
      });
  }, [connectionFilter, connectionSearch, mcpConnections, normalizedConnectionIds]);

  const savedServerIds = useMemo(() => new Set(mcpConnections.map((c) => c.server_id)), [mcpConnections]);

  const matchingRegistry = useMemo(() => {
    const query = connectionSearch.trim().toLowerCase();
    if (!query) return [];
    return mcpRegistry.filter((server) => {
      if (savedServerIds.has(server.id)) return false;
      if (connectionFilter !== "all" && connectionFilter !== "selected" && server.transport !== connectionFilter) return false;
      return [server.name, server.id, server.description, server.category]
        .some((value) => value?.toLowerCase().includes(query));
    });
  }, [connectionSearch, connectionFilter, mcpRegistry, savedServerIds]);

  return (
    <Card className="overflow-hidden border-border/70 bg-[linear-gradient(180deg,rgba(255,255,255,0.04),rgba(255,255,255,0.01))] shadow-[0_24px_80px_-48px_rgba(0,0,0,0.65)]">
      <CardHeader className="pb-3">
        <div className="flex min-w-0 items-start gap-3">
          <div className={`mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border shadow-inner ${currentSignals.runtime.tone}`}>
            <currentSignals.runtime.icon className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1 space-y-2">
            <div className="flex flex-wrap items-start gap-2">
              <CardTitle className="min-w-0 break-words text-base leading-tight">{agent.name}</CardTitle>
              <Badge variant={agent.status === "running" ? "default" : "secondary"}>{agent.status}</Badge>
            </div>

            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
              <span className="inline-flex max-w-full items-center gap-1.5">
                <currentSignals.runtime.icon className="h-3.5 w-3.5 shrink-0" />
                <span className="truncate">{currentSignals.runtime.label}</span>
              </span>
              <span className="inline-flex max-w-full items-center gap-1.5" title={currentSignals.access.description}>
                <currentSignals.access.icon className="h-3.5 w-3.5 shrink-0" />
                <span className="truncate">{currentSignals.access.label}</span>
              </span>
              <span>{capabilityCountLabel}</span>
              {policyRef.trim() ? (
                <span className="inline-flex items-center gap-1.5 text-emerald-200">
                  <ShieldCheck className="h-3.5 w-3.5 shrink-0" />
                  Policy attached
                </span>
              ) : null}
              {enableGvisor ? (
                <span className="inline-flex items-center gap-1.5 text-cyan-200">
                  <Shield className="h-3.5 w-3.5 shrink-0" />
                  gVisor sandbox
                </span>
              ) : null}
              {sidecarState.error ? <span className="text-amber-300">Raw sidecar JSON needs attention</span> : null}
            </div>

            <CardDescription className="max-w-none break-words text-sm leading-5">
              Edit runtime, policy, capabilities, and workspace files. Saving writes the updated spec and triggers an operator reconcile.
            </CardDescription>

            <div className="flex flex-wrap gap-2">
              <Badge variant="outline" className="rounded-full border-primary/20 bg-primary/10 text-[10px] uppercase tracking-[0.14em] text-primary">
                {currentSignals.runtime.label}
              </Badge>
              <Badge variant="outline" className="rounded-full border-border/60 bg-background/70 text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                {currentSignals.access.label}
              </Badge>
              <Badge
                variant="outline"
                className={`rounded-full text-[10px] uppercase tracking-[0.14em] ${policyRef.trim() ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-300" : "border-border/60 bg-background/70 text-muted-foreground"}`}
              >
                {policyRef.trim() ? "Guardrails enabled" : "No policy attached"}
              </Badge>
              <Badge
                variant="outline"
                className={`rounded-full text-[10px] uppercase tracking-[0.14em] ${enableGvisor ? "border-cyan-500/25 bg-cyan-500/10 text-cyan-300" : "border-border/60 bg-background/70 text-muted-foreground"}`}
              >
                {enableGvisor ? "gVisor active" : "Standard sandbox"}
              </Badge>
            </div>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="basics" className="space-y-4">
          <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
            <div className={`${METRIC_PANEL_CLASS} border-primary/30 bg-primary/10`}>
              <div className="flex items-center justify-between gap-2">
                <span className="text-[10px] font-bold uppercase tracking-wider text-primary">Runtime</span>
                <span className="text-sm font-bold text-foreground">{currentSignals.runtime.label}</span>
              </div>
              <p className="text-[11px] font-medium text-foreground/80">{currentSignals.access.label}</p>
            </div>
            <div className={`${METRIC_PANEL_CLASS} border-sky-500/30 bg-sky-500/10`}>
              <div className="flex items-center justify-between gap-2">
                <span className="text-[10px] font-bold uppercase tracking-wider text-sky-500">Connections</span>
                <span className="text-sm font-bold text-foreground">{selectedConnections.length}</span>
              </div>
              <p className="text-[11px] font-medium text-foreground/80">
                {usingSavedConnections
                  ? `${selectedConnectionStats.remote} remote · ${selectedConnectionStats.sidecar} sidecar`
                  : `${effectiveMcpSidecars.length} legacy sidecar${effectiveMcpSidecars.length === 1 ? "" : "s"}`}
              </p>
            </div>
            <div className={`${METRIC_PANEL_CLASS} border-violet-500/30 bg-violet-500/10`}>
              <div className="flex items-center justify-between gap-2">
                <span className="text-[10px] font-bold uppercase tracking-wider text-violet-500">Guidance</span>
                <span className="text-sm font-bold text-foreground">{selectedCatalogSkills.length + skillFileDrafts.length}</span>
              </div>
              <p className="text-[11px] font-medium text-foreground/80">{selectedCatalogSkills.length} catalog · {skillFileDrafts.length} file{skillFileDrafts.length === 1 ? "" : "s"}</p>
            </div>
            <div className={`${METRIC_PANEL_CLASS} border-emerald-500/30 bg-emerald-500/10`}>
              <div className="flex items-center justify-between gap-2">
                <span className="text-[10px] font-bold uppercase tracking-wider text-emerald-500">Hardening</span>
                <span className="text-sm font-bold text-foreground">{policyRef.trim() ? "On" : "Off"}</span>
              </div>
              <p className="text-[11px] font-medium text-foreground/80">{enableGvisor ? "gVisor sandbox" : "Standard sandbox"}</p>
            </div>
          </div>

          <TabsList className="h-auto flex-wrap justify-start gap-1 rounded-[1.15rem] border border-border/60 bg-background/75 p-1.5 shadow-sm backdrop-blur-sm">
            <TabsTrigger value="basics">Basics</TabsTrigger>
            <TabsTrigger value="behavior">Behavior</TabsTrigger>
            <TabsTrigger value="tools">Capabilities</TabsTrigger>
            <TabsTrigger value="files">Skills & Files</TabsTrigger>
            <TabsTrigger value="advanced">Advanced</TabsTrigger>
            <TabsTrigger value="intelligence" className="gap-1.5"><Radar className="h-3.5 w-3.5" />Intelligence</TabsTrigger>
          </TabsList>

          {/* ─── Basics ─── */}
          <TabsContent value="basics" className="animate-fade-in space-y-5">
            <div className="grid gap-4">
              <div className="grid gap-4">
                <Card className={PANEL_CARD_CLASS}>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm">Agent identity</CardTitle>
                    <CardDescription>Model and policy govern how this agent responds and which guardrails apply.</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="space-y-1.5">
                      <Label className="text-xs">Model</Label>
                      <ModelSelector value={model} onChange={setModel} />
                      <p className="text-[11px] text-muted-foreground">Pick a model route from the LiteLLM proxy.</p>
                    </div>
                    <div className="space-y-1.5">
                      <Label className="text-xs">Policy</Label>
                      <Select value={policyRef || "__none__"} onValueChange={(v) => setPolicyRef(v === "__none__" ? "" : v)}>
                        <SelectTrigger>
                          <SelectValue placeholder="No policy" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="__none__">No policy</SelectItem>
                          {policies.map((policy) => (
                            <SelectItem key={policy.name} value={policy.name}>{policy.name}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  </CardContent>
                </Card>

                <Card className={PANEL_CARD_CLASS}>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm">Runtime profile</CardTitle>
                    <CardDescription>Choose the agent runtime that fits this deployment.</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <div className="space-y-1.5">
                      <Label className="text-xs">Runtime kind</Label>
                      <Select value={runtimeKind} onValueChange={(v) => setRuntimeKind(v as RuntimeKind)}>
                        <SelectTrigger className="h-8 text-xs">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {(["opencode", "pi"] as RuntimeKind[]).map((kind) => {
                            const signal = getRuntimeSignal(kind);
                            return (
                              <SelectItem key={kind} value={kind} className="text-xs">
                                <span className="inline-flex items-center gap-1.5">
                                  <signal.icon className="h-3.5 w-3.5" />
                                  {signal.label}
                                  {signal.alpha && <Badge variant="outline" className="h-3 px-1 text-[9px]">Alpha</Badge>}
                                </span>
                              </SelectItem>
                            );
                          })}
                        </SelectContent>
                      </Select>
                    </div>
                    {runtimeKind === "opencode" ? (
                      <div className="rounded-2xl border border-emerald-500/30 bg-emerald-500/5 px-4 py-3 text-left text-foreground">
                        <p className="font-medium text-sm">OpenCode runtime</p>
                        <p className="mt-1 text-xs leading-5 text-muted-foreground">
                          Best for autonomous multi-turn coding with structured output, session management, context-overflow recovery, shared MCP routing, and managed sidecars.
                        </p>
                      </div>
                    ) : (
                      <div className="rounded-2xl border border-violet-500/30 bg-violet-500/5 px-4 py-3 text-left text-foreground">
                        <p className="font-medium text-sm">Pi runtime</p>
                        <p className="mt-1 text-xs leading-5 text-muted-foreground">
                          Lightweight alternative runtime using the pi coding agent. Supports streaming, tool use, and MCP connections via the pi extension system.
                        </p>
                      </div>
                    )}
                  </CardContent>
                </Card>
              </div>

              <Card className={PANEL_CARD_CLASS}>
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm">Active configuration</CardTitle>
                  <CardDescription>Current state of this agent.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-3 text-sm text-muted-foreground">
                  {agent.skill_summaries.length > 0 && (
                    <div className="rounded-2xl border border-border/60 bg-background/60 p-3">
                      <p className="font-medium text-foreground">Active skills</p>
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {agent.skill_summaries.map((skill) => (
                          <Badge key={skill.name} variant="outline" className="text-[11px]">{skill.name}</Badge>
                        ))}
                      </div>
                    </div>
                  )}
                  <div className="rounded-2xl border border-border/60 bg-background/60 p-3">
                    <p className="font-medium text-foreground">Changes are reversible</p>
                    <p className="mt-1 leading-6">Save triggers a reconcile. The operator rolls back automatically on spec errors.</p>
                  </div>
                </CardContent>
              </Card>
            </div>
          </TabsContent>

          {/* ─── Behavior ─── */}
          <TabsContent value="behavior" className="animate-fade-in space-y-4">
            <Card className={PANEL_CARD_CLASS}>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">System behavior</CardTitle>
                <CardDescription>Describe how the agent should think, respond, and constrain itself.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-1.5">
                  <Label className="text-xs">System prompt</Label>
                  <Textarea
                    rows={8}
                    value={systemPrompt}
                    onChange={(e) => {
                      if (localError) {
                        setLocalError("");
                      }
                      setSystemPrompt(e.target.value);
                    }}
                  />
                  <div className="flex flex-wrap items-center justify-between gap-2 text-[11px]">
                    <span className={systemPromptError ? "text-destructive" : "text-muted-foreground"}>
                      {systemPrompt.length}/{SYSTEM_PROMPT_MAX_CHARS} characters
                    </span>
                    <span className="text-muted-foreground">
                      A2A caller changes save independently, but the system prompt still must stay within the limit.
                    </span>
                  </div>
                  {systemPromptError ? (
                    <p className="text-xs text-destructive">{systemPromptError}</p>
                  ) : (
                    <p className="text-xs text-muted-foreground">Keep the system prompt at {SYSTEM_PROMPT_MAX_CHARS} characters or fewer.</p>
                  )}
                </div>
                <Separator />
                <div className="space-y-1.5">
                  <Label className="text-xs">Allowed caller agents (A2A)</Label>
                  <p className="text-xs text-muted-foreground">
                    Inbound only. These agents may call this agent. Outbound peer discovery and delegation come from the agent policy&apos;s allowed targets.
                  </p>
                  <A2ACallerPicker
                    value={a2aAllowedCallersText}
                    onChange={setA2aAllowedCallersText}
                    agents={workspaceAgents}
                    workflows={workspaceWorkflows}
                    currentAgentName={agent.name}
                    placeholder={A2A_ALLOWED_CALLERS_PLACEHOLDER}
                  />
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* ─── Capabilities (Tools) ─── */}
          <TabsContent value="tools" className="animate-fade-in space-y-4">
            <>
              <Card className={PANEL_CARD_CLASS}>
                <CardHeader className="pb-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <div className="flex h-8 w-8 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary">
                        <Package className="h-4 w-4" />
                      </div>
                      <div>
                        <CardTitle className="text-sm">MCP connections</CardTitle>
                        <CardDescription>Attach remote endpoints, shared hub routes, and sidecar transports from one reusable connection list.</CardDescription>
                      </div>
                    </div>
                    <Button variant="outline" size="sm" onClick={handleOpenMcpManagement}>
                      Open MCP page
                    </Button>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  {catalogError ? (
                    <div className="rounded-xl border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive" role="alert">{catalogError}</div>
                  ) : null}
                  {sidecarState.error ? (
                    <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300" role="alert">
                      The legacy raw sidecar JSON is invalid. Fix it below before saving legacy overrides.
                    </div>
                  ) : null}
                  <div className="rounded-xl border border-border/60 bg-background/70 px-3 py-3 text-xs leading-5 text-muted-foreground">
                    MCP connections are now the standard attachment path for this agent. Remote, hub, and sidecar transports all bind here, and sidecar connections deploy their containers automatically when the agent reconciles.
                  </div>

                  <div className="overflow-x-auto">
                    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4 min-w-[480px]">
                      <div className="rounded-2xl border border-primary/20 bg-primary/5 p-3">
                        <p className="text-[10px] uppercase tracking-[0.16em] text-primary/70">Selected</p>
                        <p className="mt-1 text-xl font-semibold text-foreground">{selectedConnections.length}</p>
                      </div>
                      <div className="rounded-2xl border border-sky-500/20 bg-sky-500/5 p-3">
                        <p className="text-[10px] uppercase tracking-[0.16em] text-sky-400/70">Remote</p>
                        <p className="mt-1 text-xl font-semibold text-foreground">{selectedConnectionStats.remote}</p>
                      </div>
                      <div className="rounded-2xl border border-violet-500/20 bg-violet-500/5 p-3">
                        <p className="text-[10px] uppercase tracking-[0.16em] text-violet-400/70">Hub</p>
                        <p className="mt-1 text-xl font-semibold text-foreground">{selectedConnectionStats.hub}</p>
                      </div>
                      <div className="rounded-2xl border border-amber-500/20 bg-amber-500/5 p-3">
                        <p className="text-[10px] uppercase tracking-[0.16em] text-amber-400/70">Sidecar</p>
                        <p className="mt-1 text-xl font-semibold text-foreground">{selectedConnectionStats.sidecar}</p>
                      </div>
                    </div>
                  </div>

                  {selectedConnections.length > 0 ? (
                    <div className="space-y-2">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="text-xs font-medium text-foreground">Attached connections</p>
                        <Badge variant="secondary">{selectedConnections.length}</Badge>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {selectedConnections.map((connection) => (
                          <Badge
                            key={connection.id}
                            variant="outline"
                            className={`rounded-full px-3 py-1 ${
                              connection.transport === "remote"
                                ? "border-sky-500/30 bg-sky-500/10 text-sky-300"
                                : connection.transport === "hub"
                                  ? "border-violet-500/30 bg-violet-500/10 text-violet-300"
                                  : "border-amber-500/30 bg-amber-500/10 text-amber-300"
                            }`}
                          >
                            <span className="inline-flex items-center gap-1.5">
                              <McpServerBadgeIcon
                                serverId={connection.server_id}
                                serverName={connection.server_name ?? connection.server_id}
                                transport={connection.transport}
                                size="xs"
                              />
                              <span>{connection.name}</span>
                            </span>
                          </Badge>
                        ))}
                      </div>
                    </div>
                  ) : null}

                  <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                    <div className="relative flex-1">
                      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                      <Input
                        value={connectionSearch}
                        onChange={(event) => setConnectionSearch(event.target.value)}
                        placeholder="Search connections, servers, or transports"
                        className="pl-9"
                      />
                    </div>
                    <div className="flex items-center gap-2">
                      <Select value={connectionFilter} onValueChange={(value) => setConnectionFilter(value as ConnectionFilterValue)}>
                        <SelectTrigger className="w-[190px]">
                          <SelectValue placeholder="Filter connections" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="all">All connections</SelectItem>
                          <SelectItem value="selected">Selected only</SelectItem>
                          <SelectItem value="remote">Remote only</SelectItem>
                          <SelectItem value="hub">Hub only</SelectItem>
                          <SelectItem value="sidecar">Sidecar only</SelectItem>
                        </SelectContent>
                      </Select>
                      <Badge variant="outline" className="border-border/60 bg-background/70 text-[10px] text-muted-foreground">
                        {filteredConnections.length + matchingRegistry.length} shown
                      </Badge>
                    </div>
                  </div>

                  {catalogLoading ? (
                    <div className="flex items-center justify-center rounded-xl border border-dashed border-border/70 bg-background/40 px-4 py-6 text-sm text-muted-foreground">
                      <LoaderCircle className="mr-2 h-4 w-4 animate-spin" /> Loading saved MCP connections...
                    </div>
                  ) : filteredConnections.length > 0 || matchingRegistry.length > 0 ? (
                    <ScrollArea className="max-h-[560px] pr-3">
                      <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
                        {filteredConnections.map((connection) => {
                          const selected = normalizedConnectionIds.includes(connection.id);
                          const blocked = !connection.attachable;
                          return (
                            <button
                              key={connection.id}
                              type="button"
                              onClick={() => handleToggleSavedConnection(connection.id)}
                              disabled={blocked}
                              className={`rounded-2xl border p-4 text-left transition ${
                                selected
                                  ? "border-primary/30 bg-primary/10 shadow-inner shadow-primary/10"
                                  : blocked
                                    ? "cursor-not-allowed border-border/60 bg-background/40 opacity-70"
                                    : "border-border/70 bg-background/60 hover:border-primary/20 hover:bg-accent/40"
                              }`}
                            >
                              <div className="flex items-start gap-3">
                                <McpServerBadgeIcon
                                  serverId={connection.server_id}
                                  serverName={connection.server_name ?? connection.server_id}
                                  transport={connection.transport}
                                  size="md"
                                />
                                <div className="min-w-0 flex-1 space-y-2">
                                  <div className="flex flex-wrap items-center gap-2">
                                    <p className="font-medium text-foreground">{connection.name}</p>
                                    {selected ? (
                                      <Badge variant="secondary" className="text-[10px]">
                                        Attached
                                      </Badge>
                                    ) : null}
                                    {blocked ? (
                                      <Badge variant="outline" className="border-amber-500/30 bg-amber-500/10 text-[10px] text-amber-300">
                                        Needs setup
                                      </Badge>
                                    ) : null}
                                  </div>
                                  <p className="text-sm text-muted-foreground">{connection.server_name ?? connection.server_id}</p>
                                  <p className="text-xs leading-5 text-muted-foreground">{formatConnectionRuntimeSummary(connection)}</p>
                                  {connection.status_reason && !blocked ? (
                                    <p className="text-[11px] leading-5 text-muted-foreground">{connection.status_reason}</p>
                                  ) : null}
                                </div>
                              </div>
                              <div className="mt-4 flex flex-wrap items-center gap-2">
                                <Badge variant="outline" className={`text-[10px] ${MCP_SUPPORT_BADGE_STYLES[connection.support_level]}`}>
                                  {connection.support_level}
                                </Badge>
                                <Badge variant="outline" className={`text-[10px] ${MCP_VALIDATION_BADGE_STYLES[connection.validation.status]}`}>
                                  {connection.validation.status}
                                </Badge>
                                <Badge variant="outline" className="text-[10px] capitalize">
                                  {connection.transport}
                                </Badge>
                                <Badge variant="secondary" className="text-[10px]">
                                  {connection.binding_count} binding{connection.binding_count === 1 ? "" : "s"}
                                </Badge>
                              </div>
                            </button>
                          );
                        })}
                        {matchingRegistry.map((server) => (
                          <div
                            key={server.id}
                            className="rounded-2xl border border-dashed border-border/70 bg-background/40 p-4 text-left transition hover:border-primary/20 hover:bg-accent/30"
                          >
                            <div className="flex items-start gap-3">
                              <McpServerBadgeIcon
                                serverId={server.id}
                                serverName={server.name}
                                transport={server.transport}
                                iconName={server.icon}
                                size="md"
                              />
                              <div className="min-w-0 flex-1 space-y-2">
                                <div className="flex flex-wrap items-center gap-2">
                                  <p className="font-medium text-foreground">{server.name}</p>
                                  <Badge variant="outline" className="border-sky-500/30 bg-sky-500/10 text-[10px] text-sky-300">
                                    Registry
                                  </Badge>
                                </div>
                                <p className="text-sm text-muted-foreground">{server.description}</p>
                                {server.connection_notes ? (
                                  <p className="text-[11px] leading-5 text-muted-foreground">{server.connection_notes}</p>
                                ) : null}
                              </div>
                            </div>
                            <div className="mt-4 flex items-center justify-between">
                              <div className="flex flex-wrap items-center gap-2">
                                <Badge variant="outline" className={`text-[10px] ${MCP_SUPPORT_BADGE_STYLES[server.support_level]}`}>
                                  {server.support_level}
                                </Badge>
                                <Badge variant="outline" className="text-[10px] capitalize">
                                  {server.transport}
                                </Badge>
                                <Badge variant="outline" className="text-[10px]">
                                  {server.tools_count} tool{server.tools_count === 1 ? "" : "s"}
                                </Badge>
                              </div>
                              <Button
                                size="sm"
                                variant="secondary"
                                disabled={!token.trim() || quickAddBusyId === server.id}
                                onClick={() => handleQuickAddRegistryServer(server)}
                              >
                                {quickAddBusyId === server.id ? (
                                  <LoaderCircle className="mr-1 h-3.5 w-3.5 animate-spin" />
                                ) : (
                                  <Plus className="mr-1 h-3.5 w-3.5" />
                                )}
                                Add
                              </Button>
                            </div>
                          </div>
                        ))}
                      </div>
                    </ScrollArea>
                  ) : mcpConnections.length > 0 ? (
                    <div className="rounded-2xl border border-dashed border-border/70 bg-background/40 px-4 py-8 text-center text-sm text-muted-foreground">
                      No saved MCP connections match the current search or transport filter.
                    </div>
                  ) : (
                    <div className="rounded-2xl border border-dashed border-border/70 bg-background/40 px-4 py-8 text-center text-sm text-muted-foreground">
                      <p>No saved MCP connections are available in this namespace yet.</p>
                      <p className="mt-1 text-xs leading-5">Create them in the MCP page first, then attach them here for remote, hub, or sidecar access.</p>
                      <Button variant="outline" size="sm" className="mt-3" onClick={handleOpenMcpManagement}>
                        Create connection
                      </Button>
                    </div>
                  )}
                </CardContent>
              </Card>

                <Accordion type="single" collapsible className="rounded-2xl border border-border/70 bg-background/50 px-4">
                  <AccordionItem value="advanced-routing" className="border-none">
                    <AccordionTrigger className="py-4 text-sm font-medium">Legacy MCP overrides</AccordionTrigger>
                    <AccordionContent className="space-y-4">
                      <div className="rounded-xl border border-border/60 bg-background/60 px-3 py-3 text-[11px] leading-5 text-muted-foreground">
                        Use this only when migrating older agents or attaching an endpoint that is not modeled yet as a saved MCP connection. The connection list above is the preferred attachment path.
                      </div>
                      <div className="grid gap-4 xl:grid-cols-2">
                        <div className="space-y-1.5">
                          <Label className="text-xs">Legacy shared MCP endpoints</Label>
                          <>
                            <Textarea
                              rows={4}
                              value={mcpServersText}
                              onChange={(e) => setMcpServersText(e.target.value)}
                              placeholder={MCP_SERVERS_PLACEHOLDER}
                              className="font-mono text-xs"
                              disabled={usingSavedConnections}
                            />
                            <p className="text-[11px] text-muted-foreground">One legacy shared MCP endpoint per line. These entries are ignored on save whenever MCP connections are selected above.</p>
                          </>
                        </div>
                        <div className="space-y-1.5">
                          <Label className="text-xs">Legacy raw sidecar JSON</Label>
                          <Textarea
                            rows={7}
                            value={mcpSidecarsText}
                            onChange={(e) => setMcpSidecarsText(e.target.value)}
                            placeholder={MCP_SIDECARS_PLACEHOLDER}
                            className="font-mono text-xs"
                            disabled={usingSavedConnections}
                          />
                          <p className="text-[11px] text-muted-foreground">Full access to custom sidecar specs and manual overrides for migration or edge cases not represented as saved connections yet.</p>
                        </div>
                      </div>
                    </AccordionContent>
                  </AccordionItem>
                </Accordion>
              </>
          </TabsContent>

          {/* ─── Skills & Files ─── */}
          <TabsContent value="files" className="animate-fade-in space-y-4">
            <div className="grid gap-4 min-[1900px]:grid-cols-[1.15fr_0.85fr]">
              <Card className={PANEL_CARD_CLASS}>
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <div className="flex h-8 w-8 items-center justify-center rounded-xl border border-sky-500/20 bg-sky-500/10 text-sky-300">
                        <Package className="h-4 w-4" />
                      </div>
                      <div>
                        <CardTitle className="text-sm">Skill library</CardTitle>
                        <CardDescription>Attach curated skills from the catalog with one click.</CardDescription>
                      </div>
                    </div>
                    <div className="flex items-center gap-1">
                      <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => void handleAutoSelectSkills()} disabled={catalogLoading || !token.trim()} title="Auto-attach all skills" aria-label="Auto-attach all skills">
                        <Wand2 className="h-3.5 w-3.5" />
                      </Button>
                      <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => void handleRefreshCatalog()} disabled={catalogLoading || !token.trim()} title="Refresh catalog" aria-label="Refresh catalog">
                        <RefreshCw className={`h-3.5 w-3.5 ${catalogLoading ? "animate-spin" : ""}`} />
                      </Button>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="flex gap-2">
                    <div className="relative flex-1">
                      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                      <Input value={skillSearch} onChange={(e) => setSkillSearch(e.target.value)} placeholder="Search skills, behaviors, or capability tags" className="pl-9" />
                    </div>
                    <Select value={skillCategory || "__all__"} onValueChange={(v) => setSkillCategory(v === "__all__" ? "" : v)}>
                      <SelectTrigger className="w-[180px]">
                        <SelectValue placeholder="All categories" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="__all__">All categories</SelectItem>
                        {skillCategories.map((cat) => (
                          <SelectItem key={cat} value={cat}>{cat}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <ScrollArea className="max-h-[430px] pr-3">
                    <div className="space-y-3">
                      {filteredSkills.map((skill) => {
                        const detail = skillDetailsById[skill.id];
                        const attached = hasSkillAttached(detail, draftPaths);
                        return (
                          <div
                            key={skill.id}
                            className={`rounded-2xl border p-4 transition ${
                              attached
                                ? "border-primary/35 bg-primary/10 shadow-inner shadow-primary/10"
                                : "border-border/70 bg-background/60 hover:border-primary/20 hover:bg-accent/35"
                            }`}
                          >
                            <div className="flex items-start justify-between gap-3">
                              <div className="min-w-0 space-y-2">
                                <div className="flex flex-wrap items-center gap-2">
                                  <p className="font-medium text-foreground">{skill.name}</p>
                                  <Badge variant="outline" className={SKILL_CATEGORY_STYLES[skill.category] ?? ""}>{skill.category}</Badge>
                                </div>
                                <p className="text-sm leading-6 text-muted-foreground">{skill.description}</p>
                                <div className="flex flex-wrap gap-2">
                                  {skill.tags.slice(0, 4).map((tag) => (
                                    <Badge key={tag} variant="secondary" className="rounded-full px-2.5 py-0.5 text-[10px]">{tag}</Badge>
                                  ))}
                                </div>
                              </div>
                              <Button
                                variant={attached ? "secondary" : "default"}
                                size="sm"
                                onClick={() => void handleToggleSkill(skill.id)}
                                disabled={skillBusyId === skill.id || !token.trim()}
                              >
                                {skillBusyId === skill.id ? <LoaderCircle className="mr-1.5 h-4 w-4 animate-spin" /> : null}
                                {attached ? "Remove" : "Attach"}
                              </Button>
                            </div>
                          </div>
                        );
                      })}
                      {!catalogLoading && filteredSkills.length === 0 ? (
                        <div className="rounded-2xl border border-dashed border-border/70 bg-background/40 px-4 py-8 text-center text-sm text-muted-foreground">
                          No skills match the current filters.
                        </div>
                      ) : null}
                      {catalogLoading ? (
                        <div className="flex items-center justify-center py-3 text-sm text-muted-foreground">
                          <LoaderCircle className="mr-2 h-4 w-4 animate-spin" /> Loading skill catalog...
                        </div>
                      ) : null}
                    </div>
                  </ScrollArea>
                </CardContent>
              </Card>

              <Card className={PANEL_CARD_CLASS}>
                <CardHeader className="pb-3">
                  <div className="flex items-center gap-2">
                    <div className="flex h-8 w-8 items-center justify-center rounded-xl border border-violet-500/20 bg-violet-500/10 text-violet-300">
                      <Sparkles className="h-4 w-4" />
                    </div>
                    <div>
                      <CardTitle className="text-sm">Attached guidance</CardTitle>
                      <CardDescription>Curated skills and custom files shipping with this agent.</CardDescription>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid grid-cols-2 gap-3">
                    <div className="rounded-2xl border border-border/60 bg-background/60 p-3">
                      <p className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground/70">Catalog skills</p>
                      <p className="mt-1 text-xl font-semibold text-foreground">{selectedCatalogSkills.length}</p>
                    </div>
                    <div className="rounded-2xl border border-border/60 bg-background/60 p-3">
                      <p className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground/70">Markdown files</p>
                      <p className="mt-1 text-xl font-semibold text-foreground">{skillFileDrafts.length}</p>
                    </div>
                  </div>
                  <div className="space-y-2">
                    <p className="text-xs font-medium text-foreground">Selected catalog skills</p>
                    {selectedCatalogSkills.length > 0 ? (
                      <div className="flex flex-wrap gap-2">
                        {selectedCatalogSkills.map((skill) => (
                          <Badge key={skill.id} variant="secondary" className="rounded-full px-3 py-1">{skill.name}</Badge>
                        ))}
                      </div>
                    ) : (
                      <p className="text-sm text-muted-foreground">No curated skills attached yet.</p>
                    )}
                  </div>
                </CardContent>
              </Card>
            </div>

            <Accordion type="single" collapsible className="rounded-2xl border border-border/70 bg-background/50 px-4">
              <AccordionItem value="advanced-files" className="border-none">
                <AccordionTrigger className="py-4 text-sm font-medium">Advanced file editors</AccordionTrigger>
                <AccordionContent className="space-y-4">
                  <TextFileBundleEditor
                    title="Skill files"
                    description="Custom Markdown skill documents mounted into the runtime."
                    entries={skillFileDrafts}
                    addLabel="Add custom skill file"
                    emptyMessage="No skill documents attached. Use the library above or add a custom file manually."
                    pathHint="Repo-relative Markdown path, e.g. .github/skills/reviewer/SKILL.md"
                    contentHint="Full skill document including optional frontmatter."
                    onAdd={() => setSkillFileDrafts((current) => [...current, createSkillFileDraft()])}
                    onChange={setSkillFileDrafts}
                  />
                  <TextFileBundleEditor
                    title="OpenCode config files"
                    description="Preseed the OpenCode config root with provider settings or runtime configuration."
                    entries={opencodeConfigFileDrafts}
                    addLabel="Add OpenCode file"
                    emptyMessage="No OpenCode config files attached."
                    pathHint="Path relative to OpenCode config root, e.g. config.json"
                    contentHint="JSON or plain text configuration."
                    onAdd={() => setOpenCodeConfigFileDrafts((current) => [...current, createOpenCodeConfigFileDraft()])}
                    onChange={setOpenCodeConfigFileDrafts}
                  />
                </AccordionContent>
              </AccordionItem>
            </Accordion>
          </TabsContent>

          {/* ─── Advanced ─── */}
          <TabsContent value="advanced" className="animate-fade-in space-y-4">
            <Card className={PANEL_CARD_CLASS}>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">Infrastructure</CardTitle>
                <CardDescription>Storage and sandbox isolation settings.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-1.5">
                    <Label className="text-xs">Storage size</Label>
                    <Input value={storageSize} onChange={(e) => setStorageSize(e.target.value)} placeholder="1Gi" />
                  </div>
                </div>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={enableGvisor}
                    onChange={(e) => setEnableGvisor(e.target.checked)}
                    className="h-4 w-4 rounded border-input"
                  />
                  <span className="text-sm">Enable gVisor runtime class</span>
                </label>
              </CardContent>
            </Card>
          </TabsContent>

          {/* ─── Intelligence ─── */}
          <TabsContent value="intelligence" className="animate-fade-in space-y-5">

            {/* Section A — Collector Sidecar Toggle */}
            <Card className={PANEL_CARD_CLASS}>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm flex items-center gap-2"><Radar className="h-4 w-4" /> Collector Sidecar</CardTitle>
                <CardDescription>Attach the intelligence collector MCP sidecar to this agent so it can query cluster state.</CardDescription>
              </CardHeader>
              <CardContent>
                <label className="flex items-center gap-3 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={hasCollectorSidecar}
                    onChange={handleToggleCollectorSidecar}
                    className="h-4 w-4 rounded border-input"
                    disabled={usingSavedConnections}
                  />
                  <span className="text-sm">{hasCollectorSidecar ? "Collector sidecar attached" : "Attach collector sidecar"}</span>
                  {hasCollectorSidecar && <Badge variant="default" className="text-[10px]">Active</Badge>}
                </label>
                <p className="mt-2 text-[11px] text-muted-foreground">
                  Adds <code className="px-1 py-0.5 rounded bg-muted text-[10px]">{COLLECTOR_SIDECAR_IMAGE}</code> as an MCP sidecar.
                  {usingSavedConnections ? " Clear saved MCP connections to use this legacy sidecar toggle." : " Save changes to apply."}
                </p>
              </CardContent>
            </Card>

            {/* Section B — Prompt with Intelligence */}
            <Card className={PANEL_CARD_CLASS}>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm flex items-center gap-2"><Sparkles className="h-4 w-4" /> Prompt with Intelligence</CardTitle>
                <CardDescription>Fetch live cluster intelligence and inject it into the agent chat as context.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex flex-wrap items-end gap-3">
                  <div className="space-y-1.5 min-w-[180px]">
                    <Label className="text-xs">Collector</Label>
                    <Select value={intelCollectors[0]?.id || "__none__"} disabled>
                      <SelectTrigger><SelectValue placeholder="No collectors" /></SelectTrigger>
                      <SelectContent>
                        {intelCollectors.length === 0 && <SelectItem value="__none__">No collectors registered</SelectItem>}
                        {intelCollectors.map((c) => <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                  <Button
                    size="sm"
                    disabled={promptLoading || intelCollectors.length === 0}
                    onClick={handleFetchPromptContext}
                  >
                    {promptLoading ? <LoaderCircle className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Play className="mr-1.5 h-3.5 w-3.5" />}
                    Fetch Context
                  </Button>
                  {promptResult && onInjectPrompt && (
                    <Button size="sm" variant="outline" onClick={() => { onInjectPrompt(promptResult); setPromptResult(""); }}>
                      <Wand2 className="mr-1.5 h-3.5 w-3.5" /> Inject into Chat
                    </Button>
                  )}
                </div>
                {promptResult && (
                  <div className="mt-2 max-h-48 overflow-auto rounded-xl border border-border/60 bg-muted/30 p-3 text-xs font-mono whitespace-pre-wrap">
                    {promptResult}
                  </div>
                )}
                {intelCollectors.length === 0 && (
                  <p className="text-[11px] text-muted-foreground">No intelligence collectors are registered. Deploy the collector DaemonSet first.</p>
                )}
              </CardContent>
            </Card>

            {/* Section C — Scheduled Collections */}
            <Card className={PANEL_CARD_CLASS}>
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle className="text-sm flex items-center gap-2"><Calendar className="h-4 w-4" /> Scheduled Collections</CardTitle>
                    <CardDescription>Cron-based recurring intelligence collection tasks for this agent.</CardDescription>
                  </div>
                  <Button size="sm" variant="ghost" onClick={() => void loadIntelligenceData()} disabled={intelLoading}>
                    <RefreshCw className={`h-3.5 w-3.5 ${intelLoading ? "animate-spin" : ""}`} />
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                {/* Existing schedules */}
                {intelSchedules.filter((s) => s.agent_name === agent.name).length > 0 ? (
                  <div className="space-y-2 overflow-x-auto">
                    {intelSchedules.filter((s) => s.agent_name === agent.name).map((sched) => (
                      <div key={sched.id} className="flex items-center justify-between rounded-xl border border-border/60 bg-background/70 px-3 py-2">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span className="font-medium text-sm truncate">{sched.name}</span>
                            <Badge variant={sched.enabled ? "default" : "secondary"} className="text-[10px]">{sched.enabled ? "Active" : "Paused"}</Badge>
                          </div>
                          <p className="text-[11px] text-muted-foreground mt-0.5">
                            <code className="px-1 py-0.5 rounded bg-muted">{sched.cron}</code>
                            {sched.builtin && <span className="ml-2">Script: {sched.builtin}</span>}
                            {sched.next_run && <span className="ml-2">Next: {new Date(sched.next_run).toLocaleString()}</span>}
                          </p>
                        </div>
                        <Button size="icon" variant="ghost" className="h-7 w-7 shrink-0" onClick={() => void handleDeleteSchedule(sched.id)} aria-label="Delete schedule">
                          <X className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground">No scheduled collections for this agent.</p>
                )}

                {/* Create schedule form */}
                <Separator />
                <div className="space-y-3">
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">New Schedule</p>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="space-y-1.5">
                      <Label className="text-xs">Name</Label>
                      <Input value={schedName} onChange={(e) => setSchedName(e.target.value)} placeholder="e.g. health-check-30m" />
                    </div>
                    <div className="space-y-1.5">
                      <Label className="text-xs">Cron expression</Label>
                      <Input value={schedCron} onChange={(e) => setSchedCron(e.target.value)} placeholder="*/30 * * * *" className="font-mono text-xs" />
                    </div>
                    <div className="space-y-1.5">
                      <Label className="text-xs">Collector</Label>
                      <Select value={schedCollector || "__auto__"} onValueChange={(v) => setSchedCollector(v === "__auto__" ? "" : v)}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="__auto__">Auto (any available)</SelectItem>
                          {intelCollectors.map((c) => <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>)}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-1.5">
                      <Label className="text-xs">Built-in script</Label>
                      <Select value={schedBuiltin} onValueChange={setSchedBuiltin}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="node_health">node_health</SelectItem>
                          <SelectItem value="pod_resources">pod_resources</SelectItem>
                          <SelectItem value="cluster_overview">cluster_overview</SelectItem>
                          <SelectItem value="network_info">network_info</SelectItem>
                          <SelectItem value="security_posture">security_posture</SelectItem>
                          <SelectItem value="storage_info">storage_info</SelectItem>
                          <SelectItem value="logs_collector">logs_collector</SelectItem>
                          <SelectItem value="helm_releases">helm_releases</SelectItem>
                          <SelectItem value="configmap_secrets">configmap_secrets</SelectItem>
                          <SelectItem value="crd_inventory">crd_inventory</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input type="checkbox" checked={schedEnabled} onChange={(e) => setSchedEnabled(e.target.checked)} className="h-4 w-4 rounded border-input" />
                      <span className="text-xs">Enabled</span>
                    </label>
                    <Button size="sm" onClick={() => void handleCreateSchedule()} disabled={!schedName.trim() || !schedCron.trim()}>
                      <Plus className="mr-1.5 h-3.5 w-3.5" /> Create Schedule
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Section D — Alert Rules */}
            <Card className={PANEL_CARD_CLASS}>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm flex items-center gap-2"><Bell className="h-4 w-4" /> Alert Rules</CardTitle>
                <CardDescription>Trigger notifications or auto-invoke this agent when collection output matches a condition.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {/* Existing alerts */}
                {intelAlerts.length > 0 ? (
                  <div className="space-y-2 overflow-x-auto">
                    {intelAlerts.map((al) => (
                      <div key={al.id} className="flex items-center justify-between rounded-xl border border-border/60 bg-background/70 px-3 py-2">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span className="font-medium text-sm truncate">{al.name}</span>
                            <Badge variant={al.enabled ? "default" : "secondary"} className="text-[10px]">{al.enabled ? "Active" : "Disabled"}</Badge>
                            <Badge variant="outline" className="text-[10px]">{al.action === "invoke_agent" ? "Auto-invoke" : "Notify"}</Badge>
                          </div>
                          <p className="text-[11px] text-muted-foreground mt-0.5">
                            {al.condition_type} = <code className="px-1 py-0.5 rounded bg-muted">{al.condition_value}</code>
                            {al.trigger_count > 0 && <span className="ml-2">Fired {al.trigger_count}x</span>}
                          </p>
                        </div>
                        <Button size="icon" variant="ghost" className="h-7 w-7 shrink-0" onClick={() => void handleDeleteAlert(al.id)} aria-label="Delete alert">
                          <X className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground">No alert rules defined for this agent.</p>
                )}

                {/* Create alert form */}
                <Separator />
                <div className="space-y-3">
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">New Alert Rule</p>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="space-y-1.5">
                      <Label className="text-xs">Name</Label>
                      <Input value={alertName} onChange={(e) => setAlertName(e.target.value)} placeholder="e.g. crash-loop-detect" />
                    </div>
                    <div className="space-y-1.5">
                      <Label className="text-xs">Linked schedule</Label>
                      <Select value={alertScheduleId || "__any__"} onValueChange={(v) => setAlertScheduleId(v === "__any__" ? "" : v)}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="__any__">Any schedule</SelectItem>
                          {intelSchedules.map((s) => <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>)}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-1.5">
                      <Label className="text-xs">Condition type</Label>
                      <Select value={alertCondType} onValueChange={(v) => setAlertCondType(v as typeof alertCondType)}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="contains">Contains</SelectItem>
                          <SelectItem value="not_contains">Not contains</SelectItem>
                          <SelectItem value="exit_code">Exit code</SelectItem>
                          <SelectItem value="regex">Regex</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-1.5">
                      <Label className="text-xs">Condition value</Label>
                      <Input value={alertCondValue} onChange={(e) => setAlertCondValue(e.target.value)} placeholder={alertCondType === "exit_code" ? "1" : "CrashLoopBackOff"} />
                    </div>
                    <div className="space-y-1.5">
                      <Label className="text-xs">Action</Label>
                      <Select value={alertAction} onValueChange={(v) => setAlertAction(v as typeof alertAction)}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="notify">Notify only</SelectItem>
                          <SelectItem value="invoke_agent">Auto-invoke agent</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                  {alertAction === "invoke_agent" && (
                    <div className="space-y-1.5">
                      <Label className="text-xs">Prompt template <span className="text-muted-foreground">(use {"{{output}}"} for collected data)</span></Label>
                      <Textarea
                        value={alertPromptTemplate}
                        onChange={(e) => setAlertPromptTemplate(e.target.value)}
                        rows={3}
                        className="font-mono text-xs"
                      />
                    </div>
                  )}
                  <Button size="sm" onClick={() => void handleCreateAlert()} disabled={!alertName.trim() || !alertCondValue.trim()}>
                    <Plus className="mr-1.5 h-3.5 w-3.5" /> Create Alert
                  </Button>
                </div>

                {/* Alert History */}
                {intelHistory.length > 0 && (
                  <>
                    <Separator />
                    <div className="space-y-2">
                      <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Recent Alert History</p>
                      <div className="max-h-48 overflow-auto space-y-1.5">
                        {intelHistory.slice(0, 10).map((h) => (
                          <div key={h.id} className="rounded-lg border border-border/40 bg-muted/20 px-3 py-1.5 text-[11px]">
                            <div className="flex items-center gap-2">
                              <Bell className="h-3 w-3 text-amber-400 shrink-0" />
                              <span className="font-medium">{h.alert_name}</span>
                              <span className="text-muted-foreground">{new Date(h.triggered_at).toLocaleString()}</span>
                              <Badge variant="outline" className="text-[9px] ml-auto">{h.action_taken}</Badge>
                            </div>
                            {h.snippet && <p className="mt-1 text-muted-foreground truncate">{h.snippet}</p>}
                          </div>
                        ))}
                      </div>
                    </div>
                  </>
                )}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>

        {displayError && (
          <div className="mt-4 rounded-2xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive" role="alert">
            {displayError}
          </div>
        )}

      </CardContent>

      {/* Sticky action bar */}
      <div className="sticky bottom-0 z-10 border-t border-border/70 bg-background/90 backdrop-blur-md px-6 py-3">
        <div className="flex flex-wrap items-center justify-between gap-4">
          {systemPromptError ? (
            <p className="max-w-2xl text-xs leading-5 text-destructive">
              {systemPromptError}
            </p>
          ) : (
            <p className="max-w-2xl text-xs leading-5 text-muted-foreground">
              Saving updates the spec and triggers an operator reconcile.
            </p>
          )}
          <div className="flex gap-2">
            {canMutate && (
              <>
                <Button onClick={handleSaveClick} disabled={!model.trim() || isSaving || Boolean(systemPromptError)} className="relative min-w-[140px]">
                  {isDirty && !isSaving && (
                    <span className="absolute -top-1 -right-1 h-2.5 w-2.5 rounded-full bg-amber-500 animate-[breathe-pulse_2s_ease-in-out_infinite]" />
                  )}
                  {isSaving ? <LoaderCircle className="mr-1.5 h-4 w-4 animate-spin" /> : <Save className="mr-1.5 h-4 w-4" />}
                  {isSaving ? "Saving..." : "Save changes"}
                </Button>
                {onClone && (
                  <Button variant="outline" onClick={onClone}>
                    <Copy className="mr-1.5 h-4 w-4" /> Clone
                  </Button>
                )}
                <Button variant="destructive" onClick={() => setDeleteDialogOpen(true)} disabled={isDeleting}>
                  {isDeleting ? <LoaderCircle className="mr-1.5 h-4 w-4 animate-spin" /> : <Trash2 className="mr-1.5 h-4 w-4" />}
                  {isDeleting ? "Deleting..." : "Delete"}
                </Button>
              </>
            )}
            {!canMutate && (
              <p className="text-xs text-muted-foreground italic">Read-only — operator role required to edit</p>
            )}
          </div>
        </div>
      </div>

      <ConfirmDialog
        open={deleteDialogOpen}
        onOpenChange={setDeleteDialogOpen}
        title={`Delete ${agent.name}?`}
        description="This will permanently remove the agent, its runtime pod, and all attached resources. This action cannot be undone."
        confirmLabel="Delete agent"
        variant="destructive"
        onConfirm={onDelete}
      />
    </Card>
  );
}
