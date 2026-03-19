import {
  Bot,
  Brain,
  Code,
  Copy,
  Database,
  FileText,
  GitBranch,
  Globe,
  LoaderCircle,
  Mail,
  Monitor,
  Package,
  Save,
  Search,
  Server,
  Settings,
  Sparkles,
  Trash2,
  Wrench,
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
  buildGooseConfigFiles,
  createGooseConfigFileDraft,
  gooseConfigFileDraftsFromFiles,
} from "../lib/gooseConfig";
import {
  buildOpenCodeConfigFiles,
  createOpenCodeConfigFileDraft,
  opencodeConfigFileDraftsFromFiles,
} from "../lib/opencodeConfig";
import {
  MCP_SERVERS_PLACEHOLDER,
  MCP_SIDECARS_PLACEHOLDER,
  parseMcpServersText,
  parseMcpSidecarsText,
  stringifyMcpServers,
  stringifyMcpSidecars,
} from "../lib/mcp";
import { buildSkillFiles, createSkillFileDraft, skillFileDraftsFromFiles } from "../lib/skills";
import { fetchCatalogSkillDetail, fetchMcpToolCategories, fetchMcpHubServers, fetchSkillsCatalog } from "../lib/api";
import type {
  AgentDetail,
  AgentInfo,
  CatalogSkill,
  CatalogSkillDetail,
  GitConfig,
  GitHubConfig,
  McpHubServer,
  McpToolCategory,
  PolicyInfo,
  RuntimeKind,
  TextFileDraft,
  UpdateAgentPayload,
  WorkflowInfo,
} from "../types";
import { A2ACallerPicker } from "./A2ACallerPicker";
import { TextFileBundleEditor } from "./TextFileBundleEditor";
import { ToolConfigDrawer } from "./ToolConfigDrawer";
import { useConnection } from "@/contexts/ConnectionContext";

const TOOL_ICONS: Record<string, typeof Code> = {
  "code-exec": Code,
  "web-search": Globe,
  documents: FileText,
  browser: Monitor,
  database: Database,
  git: GitBranch,
  kubernetes: Server,
  messaging: Mail,
  rag: Brain,
};

const SKILL_CATEGORY_STYLES: Record<string, string> = {
  design: "border-fuchsia-500/30 bg-fuchsia-500/10 text-fuchsia-200",
  development: "border-sky-500/30 bg-sky-500/10 text-sky-200",
  document: "border-amber-500/30 bg-amber-500/10 text-amber-200",
  communication: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
  productivity: "border-cyan-500/30 bg-cyan-500/10 text-cyan-200",
};

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

function buildManagedSidecarSpec(tool: McpToolCategory): Record<string, unknown> {
  return { name: tool.id, image: tool.sidecar_image, port: tool.default_port };
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
    gooseConfigFiles: Record<string, unknown>,
    opencodeConfigFiles: Record<string, unknown>,
  ) => void;
  onDelete: () => void;
  onClone?: () => void;
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
}: AgentManagementPanelProps) {
  const { canMutate } = useConnection();
  const [model, setModel] = useState(agent.model);
  const [systemPrompt, setSystemPrompt] = useState(agent.system_prompt);
  const [policyRef, setPolicyRef] = useState(agent.policy_ref ?? "");
  const [storageSize, setStorageSize] = useState(agent.storage_size ?? "1Gi");
  const [runtimeKind, setRuntimeKind] = useState<RuntimeKind>(agent.runtime_kind ?? "langgraph");
  const [enableGvisor, setEnableGvisor] = useState(agent.enable_gvisor);
  const [mcpServersText, setMcpServersText] = useState(stringifyMcpServers(agent.mcp_servers));
  const [mcpSidecarsText, setMcpSidecarsText] = useState(stringifyMcpSidecars(agent.mcp_sidecars));
  const [a2aAllowedCallersText, setA2aAllowedCallersText] = useState(stringifyA2APeerRefs(agent.a2a_config.allowed_callers));
  const [skillFileDrafts, setSkillFileDrafts] = useState(skillFileDraftsFromFiles(agent.skills.files));
  const [gooseConfigFileDrafts, setGooseConfigFileDrafts] = useState(gooseConfigFileDraftsFromFiles(agent.goose_config_files));
  const [opencodeConfigFileDrafts, setOpenCodeConfigFileDrafts] = useState(opencodeConfigFileDraftsFromFiles(agent.opencode_config_files));
  const [localError, setLocalError] = useState("");
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  // Track whether any field has been edited
  const isDirty = useMemo(() => {
    return (
      model !== agent.model ||
      systemPrompt !== agent.system_prompt ||
      policyRef !== (agent.policy_ref ?? "") ||
      storageSize !== (agent.storage_size ?? "1Gi") ||
      runtimeKind !== (agent.runtime_kind ?? "langgraph") ||
      enableGvisor !== agent.enable_gvisor ||
      mcpServersText !== stringifyMcpServers(agent.mcp_servers) ||
      mcpSidecarsText !== stringifyMcpSidecars(agent.mcp_sidecars) ||
      a2aAllowedCallersText !== stringifyA2APeerRefs(agent.a2a_config.allowed_callers) ||
      JSON.stringify(skillFileDrafts) !== JSON.stringify(skillFileDraftsFromFiles(agent.skills.files)) ||
      JSON.stringify(gooseConfigFileDrafts) !== JSON.stringify(gooseConfigFileDraftsFromFiles(agent.goose_config_files)) ||
      JSON.stringify(opencodeConfigFileDrafts) !== JSON.stringify(opencodeConfigFileDraftsFromFiles(agent.opencode_config_files))
    );
  }, [
    model, systemPrompt, policyRef, storageSize, runtimeKind, enableGvisor,
    mcpServersText, mcpSidecarsText, a2aAllowedCallersText,
    skillFileDrafts, gooseConfigFileDrafts, opencodeConfigFileDrafts,
    agent,
  ]);

  // Catalog state
  const [catalogSkills, setCatalogSkills] = useState<CatalogSkill[]>([]);
  const [catalogTools, setCatalogTools] = useState<McpToolCategory[]>([]);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [catalogError, setCatalogError] = useState("");
  const [skillSearch, setSkillSearch] = useState("");
  const [skillCategory, setSkillCategory] = useState("");
  const [skillDetailsById, setSkillDetailsById] = useState<Record<string, CatalogSkillDetail>>({});
  const [skillBusyId, setSkillBusyId] = useState("");

  // Tool config drawer state
  const [configDrawerTool, setConfigDrawerTool] = useState<McpToolCategory | McpHubServer | null>(null);
  const [mcpHubServers, setMcpHubServers] = useState<McpHubServer[]>([]);
  const [gitConfig, setGitConfig] = useState<GitConfig | null>(agent.git_config ?? null);
  const [githubConfig, setGithubConfig] = useState<GitHubConfig | null>(agent.github_config ?? null);

  useEffect(() => {
    setModel(agent.model);
    setSystemPrompt(agent.system_prompt);
    setPolicyRef(agent.policy_ref ?? "");
    setStorageSize(agent.storage_size ?? "1Gi");
    setRuntimeKind(agent.runtime_kind ?? "langgraph");
    setEnableGvisor(agent.enable_gvisor);
    setMcpServersText(stringifyMcpServers(agent.mcp_servers));
    setMcpSidecarsText(stringifyMcpSidecars(agent.mcp_sidecars));
    setA2aAllowedCallersText(stringifyA2APeerRefs(agent.a2a_config.allowed_callers));
    setSkillFileDrafts(skillFileDraftsFromFiles(agent.skills.files));
    setGooseConfigFileDrafts(gooseConfigFileDraftsFromFiles(agent.goose_config_files));
    setOpenCodeConfigFileDrafts(opencodeConfigFileDraftsFromFiles(agent.opencode_config_files));
    setLocalError("");
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agent.name]);

  // Fetch catalog tools and skills
  useEffect(() => {
    if (!token.trim()) {
      setCatalogSkills([]);
      setCatalogTools([]);
      setCatalogError("");
      return;
    }
    let cancelled = false;
    setCatalogLoading(true);
    setCatalogError("");
    Promise.all([fetchSkillsCatalog(token), fetchMcpToolCategories(token), fetchMcpHubServers(token)])
      .then(([skills, tools, hubServers]) => {
        if (!cancelled) {
          setCatalogSkills(skills);
          setCatalogTools(tools);
          setMcpHubServers(hubServers);
        }
      })
      .catch((nextError) => {
        if (!cancelled) setCatalogError(nextError instanceof Error ? nextError.message : String(nextError));
      })
      .finally(() => {
        if (!cancelled) setCatalogLoading(false);
      });
    return () => { cancelled = true; };
  }, [token]);

  useEffect(() => {
    setLocalError("");
  }, [
    model, systemPrompt, policyRef, storageSize, runtimeKind, enableGvisor,
    mcpServersText, mcpSidecarsText, a2aAllowedCallersText, skillFileDrafts, gooseConfigFileDrafts, opencodeConfigFileDrafts,
  ]);

  // Sidecar parsing
  const sidecarState = useMemo(() => {
    try {
      return { items: runtimeKind !== "goose" ? parseMcpSidecarsText(mcpSidecarsText) : [], error: "" };
    } catch (nextError) {
      return { items: [] as Array<Record<string, unknown>>, error: nextError instanceof Error ? nextError.message : String(nextError) };
    }
  }, [mcpSidecarsText, runtimeKind]);

  const selectedToolIds = useMemo(() => {
    const ids = new Set<string>();
    for (const sidecar of sidecarState.items) {
      const sidecarName = sidecar.name;
      if (typeof sidecarName === "string" && sidecarName.trim()) ids.add(sidecarName.trim());
    }
    return ids;
  }, [sidecarState.items]);

  const sharedMcpServers = useMemo(
    () => (runtimeKind === "langgraph" ? parseMcpServersText(mcpServersText) : []),
    [mcpServersText, runtimeKind],
  );

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

  function handleToggleTool(tool: McpToolCategory) {
    if (!tool.sidecar_image) return;
    const nextSidecars = sidecarState.items.filter((sidecar) => {
      const sidecarName = sidecar.name;
      return !(typeof sidecarName === "string" && sidecarName.trim() === tool.id);
    });
    if (!selectedToolIds.has(tool.id)) nextSidecars.push(buildManagedSidecarSpec(tool));
    setMcpSidecarsText(stringifyMcpSidecars(nextSidecars));
  }

  function handleSaveClick() {
    try {
      const skillFiles = buildSkillFiles(skillFileDrafts);
      const gooseConfigFiles = runtimeKind === "goose" ? buildGooseConfigFiles(gooseConfigFileDrafts) : {};
      const opencodeConfigFiles = runtimeKind === "opencode" ? buildOpenCodeConfigFiles(opencodeConfigFileDrafts) : {};
      const mcpServers = runtimeKind === "langgraph" ? parseMcpServersText(mcpServersText) : [];
      const mcpSidecars = runtimeKind !== "goose" ? parseMcpSidecarsText(mcpSidecarsText) : [];
      onSave(
        {
          model: model.trim(),
          system_prompt: systemPrompt,
          policy_ref: policyRef.trim() || undefined,
          storage_size: storageSize.trim() || undefined,
          runtime_kind: runtimeKind,
          enable_gvisor: enableGvisor,
          mcp_servers: mcpServers,
          mcp_sidecars: mcpSidecars,
          git_config: gitConfig,
          github_config: githubConfig,
        },
        a2aAllowedCallersText,
        skillFiles,
        gooseConfigFiles,
        opencodeConfigFiles,
      );
    } catch (nextError) {
      setLocalError(nextError instanceof Error ? nextError.message : String(nextError));
    }
  }

  function handleToolConfigSaved(specUpdates?: { git_config?: GitConfig | null; github_config?: GitHubConfig | null }) {
    if (specUpdates?.git_config !== undefined) setGitConfig(specUpdates.git_config);
    if (specUpdates?.github_config !== undefined) setGithubConfig(specUpdates.github_config);
  }

  const displayError = localError || error;

  return (
    <Card className="border-border/70 bg-card/95 shadow-[0_24px_80px_-48px_rgba(0,0,0,0.65)]">
      <CardHeader className="pb-4">
        <div className="flex flex-wrap items-start gap-4">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-primary/20 bg-primary/10 text-primary shadow-inner shadow-primary/10">
            <Bot className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1 space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <CardTitle className="text-lg">{agent.name}</CardTitle>
              <Badge variant={agent.status === "running" ? "default" : "secondary"}>{agent.status}</Badge>
            </div>
            <CardDescription className="max-w-3xl text-sm leading-6">
              Agent settings &middot; saving updates the spec and triggers an operator reconcile.
            </CardDescription>
          </div>
          <div className="grid min-w-[240px] gap-2 rounded-2xl border border-border/60 bg-background/70 p-3 text-xs text-muted-foreground lg:grid-cols-3">
            <div>
              <p className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground/70">Runtime</p>
              <p className="mt-1 font-medium text-foreground">{runtimeKind === "langgraph" ? "LangGraph" : runtimeKind === "goose" ? "Goose" : runtimeKind === "opencode" ? "OpenCode" : "Codex"}</p>
            </div>
            <div>
              <p className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground/70">Skills</p>
              <p className="mt-1 font-medium text-foreground">{skillFileDrafts.length} files</p>
            </div>
            <div>
              <p className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground/70">Tools</p>
              <p className="mt-1 font-medium text-foreground">{selectedToolIds.size} sidecars</p>
            </div>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="basics" className="space-y-5">
          <TabsList className="h-auto flex-wrap justify-start gap-1 rounded-2xl border border-border/60 bg-background/70 p-1.5">
            <TabsTrigger value="basics">Basics</TabsTrigger>
            <TabsTrigger value="behavior">Behavior</TabsTrigger>
            <TabsTrigger value="tools">Capabilities</TabsTrigger>
            <TabsTrigger value="files">Skills & Files</TabsTrigger>
            <TabsTrigger value="advanced">Advanced</TabsTrigger>
          </TabsList>

          {/* ─── Basics ─── */}
          <TabsContent value="basics" className="animate-fade-in space-y-5">
            <div className="grid gap-4">
              <div className="grid gap-4">
                <Card className="shadow-none">
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

                <Card className="shadow-none">
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm">Runtime profile</CardTitle>
                    <CardDescription>Capability options adapt to the selected engine.</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <div className="grid gap-2">
                      {(["langgraph", "goose", "codex", "opencode"] as RuntimeKind[]).map((rt) => {
                        const active = runtimeKind === rt;
                        return (
                          <button
                            key={rt}
                            type="button"
                            onClick={() => setRuntimeKind(rt)}
                            className={`rounded-2xl border px-4 py-3 text-left transition ${
                              active
                                ? "border-primary/40 bg-primary/10 text-foreground shadow-inner shadow-primary/10"
                                : "border-border/70 bg-background/60 text-muted-foreground hover:border-primary/30 hover:bg-accent/40 hover:text-foreground"
                            }`}
                          >
                            <div className="flex items-center justify-between gap-3">
                              <div>
                                <p className="font-medium text-sm">{rt === "langgraph" ? "LangGraph runtime" : rt === "goose" ? "Goose runtime" : rt === "opencode" ? "OpenCode runtime" : "Codex runtime"}</p>
                                <p className="mt-1 text-xs leading-5">
                                  {rt === "langgraph"
                                    ? "Best for tool-rich agents, MCP routing, and sidecar-based capabilities."
                                    : rt === "goose"
                                      ? "Best for Goose-native workflows and config-driven conversational behavior."
                                      : rt === "opencode"
                                        ? "Best for autonomous multi-turn coding with structured output, session management, and context-overflow recovery."
                                        : "Best for Codex CLI orchestration and Spec Kit style multi-stage implementation pipelines."}
                                </p>
                              </div>
                              {active ? <Badge>Selected</Badge> : null}
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  </CardContent>
                </Card>
              </div>

              <Card className="shadow-none">
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
            <Card className="shadow-none">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">System behavior</CardTitle>
                <CardDescription>Describe how the agent should think, respond, and constrain itself.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-1.5">
                  <Label className="text-xs">System prompt</Label>
                  <Textarea rows={8} value={systemPrompt} onChange={(e) => setSystemPrompt(e.target.value)} />
                </div>
                <Separator />
                <div className="space-y-1.5">
                  <Label className="text-xs">Allowed caller agents (A2A)</Label>
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
            {runtimeKind !== "goose" ? (
              <>
                <div className="grid gap-4 min-[1900px]:grid-cols-[1.15fr_0.85fr]">
                  <Card className="shadow-none">
                    <CardHeader className="pb-3">
                      <div className="flex items-center gap-2">
                        <div className="flex h-8 w-8 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary">
                          <Wrench className="h-4 w-4" />
                        </div>
                        <div>
                          <CardTitle className="text-sm">Managed toolkits</CardTitle>
                          <CardDescription>Attach or remove deployable sidecars from the platform catalog.</CardDescription>
                        </div>
                      </div>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      {catalogError ? (
                        <div className="rounded-xl border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">{catalogError}</div>
                      ) : null}
                      {sidecarState.error ? (
                        <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
                          The raw sidecar JSON is invalid. Fix it in Advanced routing before using the managed picker.
                        </div>
                      ) : null}
                      <div className="grid gap-3 md:grid-cols-2">
                        {catalogTools.map((tool) => {
                          const Icon = TOOL_ICONS[tool.id] ?? Wrench;
                          const selected = selectedToolIds.has(tool.id);
                          return (
                            <div
                              key={tool.id}
                              className={`rounded-2xl border p-4 transition ${
                                selected
                                  ? "border-primary/40 bg-primary/10 shadow-inner shadow-primary/10"
                                  : "border-border/70 bg-background/60 hover:border-primary/20 hover:bg-accent/40"
                              }`}
                            >
                              <div className="flex items-start gap-3">
                                <div className="mt-0.5 flex h-10 w-10 items-center justify-center rounded-xl border border-border/70 bg-card text-primary">
                                  <Icon className="h-4 w-4" />
                                </div>
                                <div className="min-w-0 flex-1">
                                  <div className="flex flex-wrap items-center gap-2">
                                    <p className="font-medium text-foreground">{tool.name}</p>
                                    <Badge variant={selected ? "default" : "outline"}>Port {tool.default_port}</Badge>
                                  </div>
                                  <p className="mt-1 text-sm leading-6 text-muted-foreground">{tool.description}</p>
                                </div>
                              </div>
                              <div className="mt-4 flex items-center justify-between gap-3">
                                <p className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground/70">{tool.id}</p>
                                <div className="flex items-center gap-2">
                                  {selected && (tool.config_schema?.length ?? 0) > 0 && (
                                    <Button
                                      variant="outline"
                                      size="sm"
                                      onClick={() => setConfigDrawerTool(tool)}
                                    >
                                      <Settings className="mr-1 h-3 w-3" />
                                      Configure
                                    </Button>
                                  )}
                                  <Button
                                    variant={selected ? "secondary" : "default"}
                                    size="sm"
                                    onClick={() => handleToggleTool(tool)}
                                    disabled={!tool.sidecar_image || Boolean(sidecarState.error)}
                                  >
                                    {selected ? "Remove" : "Add toolkit"}
                                  </Button>
                                </div>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                      {catalogLoading ? (
                        <div className="flex items-center justify-center py-3 text-sm text-muted-foreground">
                          <LoaderCircle className="mr-2 h-4 w-4 animate-spin" /> Loading platform toolkits...
                        </div>
                      ) : null}
                      {!catalogLoading && catalogTools.length === 0 && !catalogError ? (
                        <div className="rounded-2xl border border-dashed border-border/70 bg-background/40 px-4 py-8 text-center text-sm text-muted-foreground">
                          No managed toolkits available in the catalog. Use the advanced section below to configure sidecars manually.
                        </div>
                      ) : null}
                    </CardContent>
                  </Card>

                  <Card className="shadow-none">
                    <CardHeader className="pb-3">
                      <div className="flex items-center gap-2">
                        <div className="flex h-8 w-8 items-center justify-center rounded-xl border border-emerald-500/20 bg-emerald-500/10 text-emerald-300">
                          <Sparkles className="h-4 w-4" />
                        </div>
                        <div>
                          <CardTitle className="text-sm">Active capability set</CardTitle>
                          <CardDescription>Tools currently attached to this agent.</CardDescription>
                        </div>
                      </div>
                    </CardHeader>
                    <CardContent className="space-y-4">
                      <div className="grid grid-cols-2 gap-3">
                        <div className="rounded-2xl border border-border/60 bg-background/60 p-3">
                          <p className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground/70">Sidecars</p>
                          <p className="mt-1 text-xl font-semibold text-foreground">{selectedToolIds.size}</p>
                        </div>
                        <div className="rounded-2xl border border-border/60 bg-background/60 p-3">
                          <p className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground/70">Shared MCP</p>
                          <p className="mt-1 text-xl font-semibold text-foreground">{sharedMcpServers.length}</p>
                        </div>
                      </div>
                      <div className="space-y-2">
                        <p className="text-xs font-medium text-foreground">Attached toolkits</p>
                        {selectedToolIds.size > 0 ? (
                          <div className="flex flex-wrap gap-2">
                            {catalogTools
                              .filter((tool) => selectedToolIds.has(tool.id))
                              .map((tool) => (
                                <Badge key={tool.id} variant="secondary" className="rounded-full px-3 py-1">{tool.name}</Badge>
                              ))}
                          </div>
                        ) : (
                          <p className="text-sm text-muted-foreground">No managed sidecars selected yet.</p>
                        )}
                      </div>
                      <div className="space-y-2">
                        <p className="text-xs font-medium text-foreground">Enterprise MCP endpoints</p>
                        {sharedMcpServers.length > 0 ? (
                          <div className="flex flex-wrap gap-2">
                            {sharedMcpServers.map((serverName) => {
                              const hubServer = mcpHubServers.find((s) => s.id === serverName);
                              return (
                                <Badge
                                  key={serverName}
                                  variant="outline"
                                  className={`rounded-full px-3 py-1 ${hubServer ? "cursor-pointer hover:bg-accent" : ""}`}
                                  onClick={hubServer ? () => setConfigDrawerTool(hubServer) : undefined}
                                  {...(hubServer ? { role: "button" as const, tabIndex: 0, onKeyDown: (e: React.KeyboardEvent) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setConfigDrawerTool(hubServer); } } } : {})}
                                >
                                  {hubServer ? hubServer.name : serverName}
                                  {hubServer && <Settings className="ml-1 h-3 w-3" />}
                                </Badge>
                              );
                            })}
                          </div>
                        ) : (
                          <p className="text-sm text-muted-foreground">None configured. Use Advanced routing to add shared MCP endpoints.</p>
                        )}
                      </div>
                    </CardContent>
                  </Card>
                </div>

                <Accordion type="single" collapsible className="rounded-2xl border border-border/70 bg-background/50 px-4">
                  <AccordionItem value="advanced-routing" className="border-none">
                    <AccordionTrigger className="py-4 text-sm font-medium">Advanced routing & raw overrides</AccordionTrigger>
                    <AccordionContent className="space-y-4">
                      <div className="grid gap-4 xl:grid-cols-2">
                        <div className="space-y-1.5">
                          <Label className="text-xs">Shared MCP servers</Label>
                          {runtimeKind === "langgraph" ? (
                            <>
                              <Textarea
                                rows={4}
                                value={mcpServersText}
                                onChange={(e) => setMcpServersText(e.target.value)}
                                placeholder={MCP_SERVERS_PLACEHOLDER}
                                className="font-mono text-xs"
                              />
                              <p className="text-[11px] text-muted-foreground">One shared enterprise MCP server per line.</p>
                            </>
                          ) : (
                            <div className="rounded-xl border border-dashed border-border/70 bg-background/60 px-3 py-3 text-[11px] text-muted-foreground">
                              Codex agents can keep local sidecars here, but shared gateway-routed MCP servers remain LangGraph-only.
                            </div>
                          )}
                        </div>
                        <div className="space-y-1.5">
                          <Label className="text-xs">Raw sidecar JSON</Label>
                          <Textarea
                            rows={7}
                            value={mcpSidecarsText}
                            onChange={(e) => setMcpSidecarsText(e.target.value)}
                            placeholder={MCP_SIDECARS_PLACEHOLDER}
                            className="font-mono text-xs"
                          />
                          <p className="text-[11px] text-muted-foreground">Full access to custom sidecar specs and manual overrides.</p>
                        </div>
                      </div>
                    </AccordionContent>
                  </AccordionItem>
                </Accordion>
              </>
            ) : (
              <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
                Goose runtimes do not support shared MCP servers or sidecars yet. Switch to LangGraph or Codex to use sidecar-based MCP tools.
              </div>
            )}
          </TabsContent>

          {/* ─── Skills & Files ─── */}
          <TabsContent value="files" className="animate-fade-in space-y-4">
            <div className="grid gap-4 min-[1900px]:grid-cols-[1.15fr_0.85fr]">
              <Card className="shadow-none">
                <CardHeader className="pb-3">
                  <div className="flex items-center gap-2">
                    <div className="flex h-8 w-8 items-center justify-center rounded-xl border border-sky-500/20 bg-sky-500/10 text-sky-300">
                      <Package className="h-4 w-4" />
                    </div>
                    <div>
                      <CardTitle className="text-sm">Skill library</CardTitle>
                      <CardDescription>Attach curated skills from the catalog with one click.</CardDescription>
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

              <Card className="shadow-none">
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
                  {runtimeKind === "goose" ? (
                    <TextFileBundleEditor
                      title="Goose config files"
                      description="Preseed the Goose config root with prompts or runtime settings."
                      entries={gooseConfigFileDrafts}
                      addLabel="Add Goose file"
                      emptyMessage="No Goose config files attached."
                      pathHint="Path relative to Goose config root, e.g. config.yaml"
                      contentHint="YAML, Markdown, or plain text."
                      onAdd={() => setGooseConfigFileDrafts((current) => [...current, createGooseConfigFileDraft()])}
                      onChange={setGooseConfigFileDrafts}
                    />
                  ) : null}
                  {runtimeKind === "opencode" ? (
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
                  ) : null}
                </AccordionContent>
              </AccordionItem>
            </Accordion>
          </TabsContent>

          {/* ─── Advanced ─── */}
          <TabsContent value="advanced" className="animate-fade-in space-y-4">
            <Card className="shadow-none">
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
        </Tabs>

        {displayError && (
          <div className="mt-4 rounded-2xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive" role="alert">
            {displayError}
          </div>
        )}

        <div className="mt-5 flex flex-wrap items-center justify-between gap-4 border-t border-border pt-4">
          <p className="max-w-2xl text-xs leading-5 text-muted-foreground">
            Saving updates the spec and triggers an operator reconcile.
          </p>
          <div className="flex gap-2">
            {canMutate && (
              <>
                <Button onClick={handleSaveClick} disabled={!model.trim() || isSaving} className="relative min-w-[140px]">
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
      </CardContent>

      <ConfirmDialog
        open={deleteDialogOpen}
        onOpenChange={setDeleteDialogOpen}
        title={`Delete ${agent.name}?`}
        description="This will permanently remove the agent, its runtime pod, and all attached resources. This action cannot be undone."
        confirmLabel="Delete agent"
        variant="destructive"
        onConfirm={onDelete}
      />

      <ToolConfigDrawer
        open={configDrawerTool !== null}
        onOpenChange={(open) => { if (!open) setConfigDrawerTool(null); }}
        tool={configDrawerTool}
        agent={agent}
        token={token}
        namespace={agent.namespace}
        onConfigSaved={handleToolConfigSaved}
      />
    </Card>
  );
}
