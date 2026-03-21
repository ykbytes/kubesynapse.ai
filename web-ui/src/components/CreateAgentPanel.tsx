import { useEffect, useMemo, useRef, useState } from "react";
import {
  Bot,
  Brain,
  Code,
  Database,
  FileText,
  GitBranch,
  Globe,
  LoaderCircle,
  Lock,
  Mail,
  Monitor,
  Package,
  PlusCircle,
  RefreshCw,
  Search,
  Server,
  Sparkles,
  Wand2,
  Wrench,
} from "lucide-react";

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
import { ModelSelector } from "@/components/ModelSelector";
import { fetchCatalogSkillDetail, fetchMcpToolCategories, fetchSkillsCatalog, refreshSkillsCatalog } from "../lib/api";
import { A2A_ALLOWED_CALLERS_PLACEHOLDER } from "../lib/a2a";
import { createGooseConfigFileDraft } from "../lib/gooseConfig";
import { createOpenCodeConfigFileDraft } from "../lib/opencodeConfig";
import {
  MCP_SERVERS_PLACEHOLDER,
  MCP_SIDECARS_PLACEHOLDER,
  parseMcpServersText,
  parseMcpSidecarsText,
  stringifyMcpSidecars,
} from "../lib/mcp";
import { createSkillFileDraft } from "../lib/skills";
import type { AgentInfo, CatalogSkill, CatalogSkillDetail, GitFormState, GitHubFormState, McpToolCategory, RuntimeKind, TextFileDraft, WorkflowInfo } from "../types";
import { A2ACallerPicker } from "./A2ACallerPicker";
import { TextFileBundleEditor } from "./TextFileBundleEditor";

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

interface CreateAgentPanelProps {
  token: string;
  isEmptyWorkspace: boolean;
  name: string;
  model: string;
  systemPrompt: string;
  runtimeKind: RuntimeKind;
  mcpServersText: string;
  mcpSidecarsText: string;
  a2aAllowedCallersText: string;
  agents: AgentInfo[];
  workflows: WorkflowInfo[];
  skillFileDrafts: TextFileDraft[];
  gooseConfigFileDrafts: TextFileDraft[];
  opencodeConfigFileDrafts: TextFileDraft[];
  isCreating: boolean;
  error: string;
  onMcpServersTextChange: (value: string) => void;
  onMcpSidecarsTextChange: (value: string) => void;
  onNameChange: (value: string) => void;
  onModelChange: (value: string) => void;
  onSystemPromptChange: (value: string) => void;
  onRuntimeKindChange: (value: RuntimeKind) => void;
  onA2AAllowedCallersTextChange: (value: string) => void;
  onSkillFileDraftsChange: (value: TextFileDraft[]) => void;
  onGooseConfigFileDraftsChange: (value: TextFileDraft[]) => void;
  onOpenCodeConfigFileDraftsChange: (value: TextFileDraft[]) => void;
  gitForm: GitFormState;
  onGitFormChange: (value: GitFormState) => void;
  githubForm: GitHubFormState;
  onGitHubFormChange: (value: GitHubFormState) => void;
  onCreate: () => void;
}

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
    nextDrafts[existingIndex] = {
      ...nextDrafts[existingIndex],
      path: normalizedPath,
      content,
    };
  }

  return nextDrafts;
}

function removeSkillDrafts(drafts: TextFileDraft[], detail: CatalogSkillDetail): TextFileDraft[] {
  const managedPaths = new Set(Object.keys(detail.assets).map(normalizeDraftPath));
  return drafts.filter((draft) => !managedPaths.has(normalizeDraftPath(draft.path)));
}

function hasSkillAttached(detail: CatalogSkillDetail | undefined, draftPaths: Set<string>): boolean {
  if (!detail) {
    return false;
  }
  return Object.keys(detail.assets).every((path) => draftPaths.has(normalizeDraftPath(path)));
}

function buildManagedSidecarSpec(tool: McpToolCategory): Record<string, unknown> {
  return {
    name: tool.id,
    image: tool.sidecar_image,
    port: tool.default_port,
  };
}

export function CreateAgentPanel({
  token,
  isEmptyWorkspace,
  name,
  model,
  systemPrompt,
  runtimeKind,
  mcpServersText,
  mcpSidecarsText,
  a2aAllowedCallersText,
  agents: workspaceAgents,
  workflows: workspaceWorkflows,
  skillFileDrafts,
  gooseConfigFileDrafts,
  opencodeConfigFileDrafts,
  isCreating,
  error,
  onMcpServersTextChange,
  onMcpSidecarsTextChange,
  onNameChange,
  onModelChange,
  onSystemPromptChange,
  onRuntimeKindChange,
  onA2AAllowedCallersTextChange,
  onSkillFileDraftsChange,
  onGooseConfigFileDraftsChange,
  onOpenCodeConfigFileDraftsChange,
  gitForm,
  onGitFormChange,
  githubForm,
  onGitHubFormChange,
  onCreate,
}: CreateAgentPanelProps) {
  const [catalogSkills, setCatalogSkills] = useState<CatalogSkill[]>([]);
  const [catalogTools, setCatalogTools] = useState<McpToolCategory[]>([]);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [catalogError, setCatalogError] = useState("");
  const [skillSearch, setSkillSearch] = useState("");
  const [skillCategory, setSkillCategory] = useState("");
  const [skillDetailsById, setSkillDetailsById] = useState<Record<string, CatalogSkillDetail>>({});
  const [skillBusyId, setSkillBusyId] = useState("");
  const [nameBlurred, setNameBlurred] = useState(false);
  const [modelBlurred, setModelBlurred] = useState(false);

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

    Promise.all([fetchSkillsCatalog(token), fetchMcpToolCategories(token)])
      .then(([skills, tools]) => {
        if (cancelled) {
          return;
        }
        setCatalogSkills(skills);
        setCatalogTools(tools);
      })
      .catch((nextError) => {
        if (!cancelled) {
          setCatalogError(nextError instanceof Error ? nextError.message : String(nextError));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setCatalogLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [token]);

  const sidecarState = useMemo(() => {
    try {
      return {
        items: runtimeKind !== "goose" ? parseMcpSidecarsText(mcpSidecarsText) : [],
        error: "",
      };
    } catch (nextError) {
      return {
        items: [] as Array<Record<string, unknown>>,
        error: nextError instanceof Error ? nextError.message : String(nextError),
      };
    }
  }, [mcpSidecarsText, runtimeKind]);

  const selectedToolIds = useMemo(() => {
    const ids = new Set<string>();
    for (const sidecar of sidecarState.items) {
      const sidecarName = sidecar.name;
      if (typeof sidecarName === "string" && sidecarName.trim()) {
        ids.add(sidecarName.trim());
      }
    }
    return ids;
  }, [sidecarState.items]);

  const draftPaths = useMemo(
    () => new Set(skillFileDrafts.map((draft) => normalizeDraftPath(draft.path)).filter(Boolean)),
    [skillFileDrafts],
  );

  const skillFileDraftsRef = useRef(skillFileDrafts);
  skillFileDraftsRef.current = skillFileDrafts;
  const draftPathsRef = useRef(draftPaths);
  draftPathsRef.current = draftPaths;

  const filteredSkills = useMemo(() => {
    const query = skillSearch.trim().toLowerCase();
    return catalogSkills.filter((skill) => {
      if (skillCategory && skill.category !== skillCategory) {
        return false;
      }
      if (!query) {
        return true;
      }
      return (
        skill.name.toLowerCase().includes(query) ||
        skill.description.toLowerCase().includes(query) ||
        skill.tags.some((tag) => tag.toLowerCase().includes(query))
      );
    });
  }, [catalogSkills, skillCategory, skillSearch]);

  const selectedCatalogSkills = useMemo(
    () => catalogSkills.filter((skill) => hasSkillAttached(skillDetailsById[skill.id], draftPaths)),
    [catalogSkills, draftPaths, skillDetailsById],
  );

  const skillCategories = useMemo(
    () => [...new Set(catalogSkills.map((skill) => skill.category).filter(Boolean))].sort((left, right) => left.localeCompare(right)),
    [catalogSkills],
  );

  const sharedMcpServers = useMemo(
    () => (runtimeKind === "langgraph" ? parseMcpServersText(mcpServersText) : []),
    [mcpServersText, runtimeKind],
  );

  async function ensureSkillDetail(skillId: string): Promise<CatalogSkillDetail> {
    const cached = skillDetailsById[skillId];
    if (cached) {
      return cached;
    }
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
      onSkillFileDraftsChange(attached ? removeSkillDrafts(currentDrafts, detail) : mergeSkillDrafts(currentDrafts, detail));
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
      const [skills, tools] = await Promise.all([fetchSkillsCatalog(token), fetchMcpToolCategories(token)]);
      setCatalogSkills(skills);
      setCatalogTools(tools);
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
      onSkillFileDraftsChange(drafts);
    } catch (nextError) {
      setCatalogError(nextError instanceof Error ? nextError.message : String(nextError));
    } finally {
      setCatalogLoading(false);
    }
  }

  function handleToggleTool(tool: McpToolCategory) {
    if (!tool.sidecar_image) {
      return;
    }
    const nextSidecars = sidecarState.items.filter((sidecar) => {
      const sidecarName = sidecar.name;
      return !(typeof sidecarName === "string" && sidecarName.trim() === tool.id);
    });

    if (!selectedToolIds.has(tool.id)) {
      nextSidecars.push(buildManagedSidecarSpec(tool));
    }

    onMcpSidecarsTextChange(stringifyMcpSidecars(nextSidecars));
  }

  return (
    <Card className="border-border/70 bg-card/95 shadow-[0_24px_80px_-48px_rgba(0,0,0,0.65)]">
      <CardHeader className="pb-4">
        <div className="flex flex-wrap items-start gap-4">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-primary/20 bg-primary/10 text-primary shadow-inner shadow-primary/10">
            <Bot className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1 space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <CardTitle className="text-lg">
                {isEmptyWorkspace ? "Create your first agent" : "Create a new agent"}
              </CardTitle>
              <Badge variant="secondary">guided setup</Badge>
            </div>
            <CardDescription className="max-w-3xl text-sm leading-6">
              Start with the core identity, then attach curated skills and managed toolkits. Advanced file and routing controls stay available when you need them, but the default path stays fast and clean.
            </CardDescription>
          </div>
          <div className="grid min-w-[240px] gap-2 rounded-2xl border border-border/60 bg-background/70 p-3 text-xs text-muted-foreground sm:grid-cols-3">
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
            <TabsTrigger value="repository">Repository</TabsTrigger>
          </TabsList>

          <TabsContent value="basics" className="animate-fade-in space-y-5">
            <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
              <div className="grid gap-4 sm:grid-cols-2">
                <Card className="shadow-none">
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm">Agent identity</CardTitle>
                    <CardDescription>Name and model define how this agent appears and routes requests.</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="space-y-1.5">
                      <Label className="text-xs">Agent name</Label>
                      <Input
                        value={name}
                        onChange={(e) => onNameChange(e.target.value)}
                        onBlur={() => setNameBlurred(true)}
                        placeholder="workspace-assistant"
                        aria-invalid={nameBlurred && !name.trim()}
                        className={nameBlurred && !name.trim() ? "border-destructive focus-visible:ring-destructive" : ""}
                      />
                      {nameBlurred && !name.trim() && (
                        <p className="text-[11px] text-destructive">Agent name is required.</p>
                      )}
                    </div>
                    <div className="space-y-1.5">
                      <Label className="text-xs">Model</Label>
                      <ModelSelector
                        value={model}
                        onChange={(v) => { onModelChange(v); setModelBlurred(true); }}
                        invalid={modelBlurred && !model.trim()}
                      />
                      {modelBlurred && !model.trim() ? (
                        <p className="text-[11px] text-destructive">Model is required.</p>
                      ) : (
                        <p className="text-[11px] text-muted-foreground">Pick a model route from the LiteLLM proxy.</p>
                      )}
                    </div>
                  </CardContent>
                </Card>

                <Card className="shadow-none">
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm">Runtime profile</CardTitle>
                    <CardDescription>Choose the runtime first. Capability options adapt to the selected engine.</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <div className="grid gap-2">
                      {(["langgraph", "goose", "codex", "opencode"] as RuntimeKind[]).map((rt) => {
                        const active = runtimeKind === rt;
                        return (
                          <button
                            key={rt}
                            type="button"
                            onClick={() => onRuntimeKindChange(rt)}
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
                                    ? "Best for tool-rich agents with MCP sidecars, multi-tool routing, and enterprise integrations. Choose this when you need database, browser, or custom MCP tools."
                                    : rt === "goose"
                                      ? "Best for Goose-native workflows with config-driven extensions and conversational behavior. Choose this for Goose ecosystem tools and prompts."
                                      : rt === "opencode"
                                        ? "Best for autonomous multi-turn coding tasks. Features structured output, session persistence, context-overflow recovery, and automatic plan-then-build execution."
                                        : "Best for Codex-driven repository implementation with structured stage prompts. Choose this for large-scale code generation from specs."}
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
                  <CardTitle className="text-sm">Launch checklist</CardTitle>
                  <CardDescription>Keep creation fast: name the agent, choose a model, then add only the skills and tools it truly needs.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-3 text-sm text-muted-foreground">
                  <div className="rounded-2xl border border-border/60 bg-background/60 p-3">
                    <p className="font-medium text-foreground">Recommended path</p>
                    <p className="mt-1 leading-6">Use curated skills for behavior, curated toolkits for execution, and keep advanced raw editors for custom overrides only.</p>
                  </div>
                  <div className="rounded-2xl border border-border/60 bg-background/60 p-3">
                    <p className="font-medium text-foreground">Creation stays reversible</p>
                    <p className="mt-1 leading-6">You can still attach custom skill files, enterprise MCP endpoints, and raw sidecar specs before saving.</p>
                  </div>
                </CardContent>
              </Card>
            </div>
          </TabsContent>

          <TabsContent value="behavior" className="animate-fade-in space-y-4">
            <Card className="shadow-none">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">System behavior</CardTitle>
                <CardDescription>Describe how the agent should think, respond, and constrain itself.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-1.5">
                  <Label className="text-xs">System prompt</Label>
                  <Textarea
                    rows={7}
                    value={systemPrompt}
                    onChange={(e) => onSystemPromptChange(e.target.value)}
                    placeholder="You are a senior software engineer. Follow these guidelines: (1) Think step-by-step before acting. (2) Read existing code before making changes. (3) Verify your work by running tests. (4) Be concise and factual — do not fabricate information."
                  />
                </div>
                <Separator />
                <div className="space-y-1.5">
                  <Label className="text-xs">Allowed caller agents (A2A)</Label>
                  <A2ACallerPicker
                    value={a2aAllowedCallersText}
                    onChange={onA2AAllowedCallersTextChange}
                    agents={workspaceAgents}
                    workflows={workspaceWorkflows}
                    currentAgentName={name || undefined}
                    placeholder={A2A_ALLOWED_CALLERS_PLACEHOLDER}
                  />
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="tools" className="animate-fade-in space-y-4">
            {runtimeKind !== "goose" ? (
              <>
                <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
                  <Card className="shadow-none">
                    <CardHeader className="pb-3">
                      <div className="flex items-center gap-2">
                        <div className="flex h-8 w-8 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary">
                          <Wrench className="h-4 w-4" />
                        </div>
                        <div>
                          <CardTitle className="text-sm">Managed toolkits</CardTitle>
                          <CardDescription>Attach deployable sidecars directly from the platform catalog.</CardDescription>
                        </div>
                      </div>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      {catalogError ? (
                        <div className="rounded-xl border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                          {catalogError}
                        </div>
                      ) : null}
                      {sidecarState.error ? (
                        <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
                          The raw sidecar JSON is invalid. Fix it in Advanced routing before using the managed picker again.
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
                          );
                        })}
                      </div>
                      {catalogLoading ? (
                        <div className="flex items-center justify-center py-3 text-sm text-muted-foreground">
                          <LoaderCircle className="mr-2 h-4 w-4 animate-spin" /> Loading platform toolkits...
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
                          <CardTitle className="text-sm">Selected capability set</CardTitle>
                          <CardDescription>Review what will ship with the agent before creation.</CardDescription>
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
                                <Badge key={tool.id} variant="secondary" className="rounded-full px-3 py-1">
                                  {tool.name}
                                </Badge>
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
                            {sharedMcpServers.map((serverName) => (
                              <Badge key={serverName} variant="outline" className="rounded-full px-3 py-1">
                                {serverName}
                              </Badge>
                            ))}
                          </div>
                        ) : (
                          <p className="text-sm text-muted-foreground">None configured. Use Advanced routing if you need shared MCP endpoints.</p>
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
                                onChange={(e) => onMcpServersTextChange(e.target.value)}
                                placeholder={MCP_SERVERS_PLACEHOLDER}
                                className="font-mono text-xs"
                              />
                              <p className="text-[11px] text-muted-foreground">One shared enterprise MCP server per line.</p>
                            </>
                          ) : (
                            <div className="rounded-xl border border-dashed border-border/70 bg-background/60 px-3 py-3 text-[11px] text-muted-foreground">
                              Codex agents can attach pod-local MCP sidecars here, but shared gateway-routed MCP servers are still LangGraph-only.
                            </div>
                          )}
                        </div>
                        <div className="space-y-1.5">
                          <Label className="text-xs">Raw sidecar JSON</Label>
                          <Textarea
                            rows={7}
                            value={mcpSidecarsText}
                            onChange={(e) => onMcpSidecarsTextChange(e.target.value)}
                            placeholder={MCP_SIDECARS_PLACEHOLDER}
                            className="font-mono text-xs"
                          />
                          <p className="text-[11px] text-muted-foreground">Keeps full access to custom sidecar specs and manual overrides.</p>
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

          <TabsContent value="files" className="animate-fade-in space-y-4">
            <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
              <Card className="shadow-none">
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <div className="flex h-8 w-8 items-center justify-center rounded-xl border border-sky-500/20 bg-sky-500/10 text-sky-300">
                        <Package className="h-4 w-4" />
                      </div>
                      <div>
                        <CardTitle className="text-sm">Skill library</CardTitle>
                        <CardDescription>Attach curated skills from the catalog with one click. Each skill adds its bundled Markdown files to the agent.</CardDescription>
                      </div>
                    </div>
                    <div className="flex items-center gap-1">
                      <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => void handleAutoSelectSkills()} disabled={catalogLoading || !token.trim()} title="Auto-attach all skills">
                        <Wand2 className="h-3.5 w-3.5" />
                      </Button>
                      <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => void handleRefreshCatalog()} disabled={catalogLoading || !token.trim()} title="Refresh catalog">
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
                        {skillCategories.map((category) => (
                          <SelectItem key={category} value={category}>
                            {category}
                          </SelectItem>
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
                                  <Badge variant="outline" className={SKILL_CATEGORY_STYLES[skill.category] ?? ""}>
                                    {skill.category}
                                  </Badge>
                                </div>
                                <p className="text-sm leading-6 text-muted-foreground">{skill.description}</p>
                                <div className="flex flex-wrap gap-2">
                                  {skill.tags.slice(0, 4).map((tag) => (
                                    <Badge key={tag} variant="secondary" className="rounded-full px-2.5 py-0.5 text-[10px]">
                                      {tag}
                                    </Badge>
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
                      <CardDescription>See which curated skills and custom files will ship with the agent.</CardDescription>
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
                          <Badge key={skill.id} variant="secondary" className="rounded-full px-3 py-1">
                            {skill.name}
                          </Badge>
                        ))}
                      </div>
                    ) : (
                      <p className="text-sm text-muted-foreground">No curated skills attached yet.</p>
                    )}
                  </div>
                  <div className="rounded-2xl border border-border/60 bg-background/60 p-3 text-sm text-muted-foreground">
                    Curated skills are added as ordinary Markdown files, so you can still inspect and edit them before creation.
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
                    description="Custom Markdown skill documents mounted into the runtime. Use this for advanced edits or entirely custom skills."
                    entries={skillFileDrafts}
                    addLabel="Add custom skill file"
                    emptyMessage="No skill documents attached. Use the library above or add a custom file manually."
                    pathHint="Repo-relative Markdown path, e.g. .github/skills/reviewer/SKILL.md"
                    contentHint="Full skill document including optional frontmatter for tools, MCP, A2A, or Goose extensions."
                    onAdd={() => onSkillFileDraftsChange([...skillFileDrafts, createSkillFileDraft()])}
                    onChange={onSkillFileDraftsChange}
                  />
                  {runtimeKind === "goose" ? (
                    <TextFileBundleEditor
                      title="Goose config files"
                      description="Preseed the Goose config root with prompts or runtime settings."
                      entries={gooseConfigFileDrafts}
                      addLabel="Add Goose file"
                      emptyMessage="No Goose config files attached. Add config.yaml or prompt fragments as needed."
                      pathHint="Path relative to Goose config root, e.g. config.yaml"
                      contentHint="YAML, Markdown, or plain text. Secrets stay in environment variables."
                      onAdd={() => onGooseConfigFileDraftsChange([...gooseConfigFileDrafts, createGooseConfigFileDraft()])}
                      onChange={onGooseConfigFileDraftsChange}
                    />
                  ) : null}
                  {runtimeKind === "opencode" ? (
                    <TextFileBundleEditor
                      title="OpenCode config files"
                      description="Preseed the OpenCode config root with provider settings or runtime configuration."
                      entries={opencodeConfigFileDrafts}
                      addLabel="Add OpenCode file"
                      emptyMessage="No OpenCode config files attached. Add config.json or provider settings as needed."
                      pathHint="Path relative to OpenCode config root, e.g. config.json"
                      contentHint="JSON or plain text configuration. Secrets stay in environment variables."
                      onAdd={() => onOpenCodeConfigFileDraftsChange([...opencodeConfigFileDrafts, createOpenCodeConfigFileDraft()])}
                      onChange={onOpenCodeConfigFileDraftsChange}
                    />
                  ) : null}
                </AccordionContent>
              </AccordionItem>
            </Accordion>
          </TabsContent>

          <TabsContent value="repository" className="animate-fade-in space-y-4">
            <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
              <Card className="shadow-none">
                <CardHeader className="pb-3">
                  <div className="flex items-center gap-2">
                    <div className="flex h-8 w-8 items-center justify-center rounded-xl border border-orange-500/20 bg-orange-500/10 text-orange-300">
                      <GitBranch className="h-4 w-4" />
                    </div>
                    <div>
                      <CardTitle className="text-sm">Git repository</CardTitle>
                      <CardDescription>Connect a git repo so the agent can clone, commit, and push code changes autonomously.</CardDescription>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="flex items-center gap-3">
                    <input
                      type="checkbox"
                      id="git-enabled"
                      checked={gitForm.enabled}
                      onChange={(e) => onGitFormChange({ ...gitForm, enabled: e.target.checked })}
                      className="h-4 w-4 rounded border-border"
                    />
                    <Label htmlFor="git-enabled" className="text-sm font-medium">Enable git integration</Label>
                  </div>

                  {gitForm.enabled && (
                    <div className="space-y-4">
                      <div className="grid gap-4 sm:grid-cols-2">
                        <div className="space-y-2">
                          <Label htmlFor="git-repo-url">Repository URL</Label>
                          <Input
                            id="git-repo-url"
                            placeholder="https://github.com/org/repo.git"
                            value={gitForm.repoUrl}
                            onChange={(e) => onGitFormChange({ ...gitForm, repoUrl: e.target.value })}
                          />
                        </div>
                        <div className="space-y-2">
                          <Label htmlFor="git-default-branch">Default branch</Label>
                          <Input
                            id="git-default-branch"
                            placeholder="main"
                            value={gitForm.defaultBranch}
                            onChange={(e) => onGitFormChange({ ...gitForm, defaultBranch: e.target.value })}
                          />
                        </div>
                      </div>

                      <div className="space-y-2">
                        <Label htmlFor="git-branch">Agent working branch <span className="text-muted-foreground text-xs">(optional)</span></Label>
                        <Input
                          id="git-branch"
                          placeholder="e.g. agent/backend — if set, sidecar checks out this branch at startup"
                          value={gitForm.branch}
                          onChange={(e) => onGitFormChange({ ...gitForm, branch: e.target.value })}
                        />
                      </div>

                      <Separator />

                      <div className="grid gap-4 sm:grid-cols-2">
                        <div className="space-y-2">
                          <Label htmlFor="git-auth-method">Authentication method</Label>
                          <Select value={gitForm.authMethod} onValueChange={(v) => onGitFormChange({ ...gitForm, authMethod: v as "token" | "basic" | "ssh" })}>
                            <SelectTrigger id="git-auth-method">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="token">Personal access token</SelectItem>
                              <SelectItem value="basic">Username & password</SelectItem>
                              <SelectItem value="ssh">SSH key</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>
                        <div className="space-y-2">
                          <Label htmlFor="git-push-policy">Push policy</Label>
                          <Select value={gitForm.pushPolicy} onValueChange={(v) => onGitFormChange({ ...gitForm, pushPolicy: v as "after-each-commit" | "end-of-session" | "on-approval" | "never" })}>
                            <SelectTrigger id="git-push-policy">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="after-each-commit">After each commit</SelectItem>
                              <SelectItem value="end-of-session">End of session</SelectItem>
                              <SelectItem value="on-approval">On approval</SelectItem>
                              <SelectItem value="never">Never (local only)</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>
                      </div>

                      <Card className="border-border/60 shadow-none">
                        <CardHeader className="pb-3">
                          <div className="flex items-center gap-2">
                            <Lock className="h-4 w-4 text-muted-foreground" />
                            <CardTitle className="text-sm">Credentials</CardTitle>
                          </div>
                          <CardDescription>Credentials are stored as a Kubernetes Secret and never exposed after creation.</CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-3">
                          {gitForm.authMethod === "token" && (
                            <div className="space-y-2">
                              <Label htmlFor="git-token">Personal access token</Label>
                              <Input
                                id="git-token"
                                type="password"
                                placeholder="ghp_..."
                                value={gitForm.token}
                                onChange={(e) => onGitFormChange({ ...gitForm, token: e.target.value })}
                              />
                            </div>
                          )}
                          {gitForm.authMethod === "basic" && (
                            <div className="grid gap-3 sm:grid-cols-2">
                              <div className="space-y-2">
                                <Label htmlFor="git-username">Username</Label>
                                <Input
                                  id="git-username"
                                  placeholder="git-user"
                                  value={gitForm.username}
                                  onChange={(e) => onGitFormChange({ ...gitForm, username: e.target.value })}
                                />
                              </div>
                              <div className="space-y-2">
                                <Label htmlFor="git-password">Password</Label>
                                <Input
                                  id="git-password"
                                  type="password"
                                  placeholder="••••••••"
                                  value={gitForm.password}
                                  onChange={(e) => onGitFormChange({ ...gitForm, password: e.target.value })}
                                />
                              </div>
                            </div>
                          )}
                          {gitForm.authMethod === "ssh" && (
                            <div className="space-y-2">
                              <Label htmlFor="git-ssh-key">SSH private key</Label>
                              <Textarea
                                id="git-ssh-key"
                                rows={5}
                                placeholder={"-----BEGIN OPENSSH PRIVATE KEY-----\n...\n-----END OPENSSH PRIVATE KEY-----"}
                                value={gitForm.sshPrivateKey}
                                className="font-mono text-xs"
                                onChange={(e) => onGitFormChange({ ...gitForm, sshPrivateKey: e.target.value })}
                              />
                            </div>
                          )}
                        </CardContent>
                      </Card>
                    </div>
                  )}
                </CardContent>
              </Card>

              <Card className="shadow-none">
                <CardHeader className="pb-3">
                  <div className="flex items-center gap-2">
                    <div className="flex h-8 w-8 items-center justify-center rounded-xl border border-sky-500/20 bg-sky-500/10 text-sky-300">
                      <Globe className="h-4 w-4" />
                    </div>
                    <div>
                      <CardTitle className="text-sm">GitHub MCP access</CardTitle>
                      <CardDescription>Attach a per-agent GitHub personal access token for the shared GitHub MCP adapter.</CardDescription>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="flex items-center gap-3">
                    <input
                      type="checkbox"
                      id="github-enabled"
                      checked={githubForm.enabled}
                      disabled={runtimeKind !== "langgraph"}
                      onChange={(e) => onGitHubFormChange({ ...githubForm, enabled: e.target.checked })}
                      className="h-4 w-4 rounded border-border"
                    />
                    <Label htmlFor="github-enabled" className="text-sm font-medium">Enable shared GitHub MCP access</Label>
                  </div>

                  {runtimeKind !== "langgraph" ? (
                    <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
                      GitHub MCP access is currently wired only for LangGraph agents. Switch the runtime to LangGraph to enable it.
                    </div>
                  ) : null}

                  <div className="rounded-2xl border border-border/60 bg-background/60 p-4 text-sm text-muted-foreground">
                    The platform creates a per-agent Kubernetes Secret, injects the token only into that agent runtime, and forwards it to the shared GitHub adapter on each GitHub MCP call. Your AgentPolicy still needs to allow the <span className="font-mono text-foreground">github</span> MCP server.
                  </div>

                  {runtimeKind === "langgraph" && githubForm.enabled ? (
                    <Card className="border-border/60 shadow-none">
                      <CardHeader className="pb-3">
                        <div className="flex items-center gap-2">
                          <Lock className="h-4 w-4 text-muted-foreground" />
                          <CardTitle className="text-sm">GitHub token</CardTitle>
                        </div>
                        <CardDescription>Use a PAT with only the scopes the agent needs for repository, issue, or pull request operations.</CardDescription>
                      </CardHeader>
                      <CardContent className="space-y-2">
                        <Label htmlFor="github-token">Personal access token</Label>
                        <Input
                          id="github-token"
                          type="password"
                          placeholder="github_pat_..."
                          value={githubForm.token}
                          onChange={(e) => onGitHubFormChange({ ...githubForm, token: e.target.value })}
                        />
                      </CardContent>
                    </Card>
                  ) : null}
                </CardContent>
              </Card>
            </div>
          </TabsContent>
        </Tabs>

        {error && (
          <div className="mt-4 rounded-2xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {error}
          </div>
        )}

        <div className="mt-5 flex flex-wrap items-center justify-between gap-4 border-t border-border pt-4">
          <p className="max-w-2xl text-xs leading-5 text-muted-foreground">
            Creation keeps all existing functionality intact. The guided pickers write into the same MCP sidecar specs and skill files that the runtime already understands.
          </p>
          <Button onClick={onCreate} disabled={!name.trim() || !model.trim() || isCreating} className="min-w-[160px]">
            {isCreating ? <LoaderCircle className="mr-1.5 h-4 w-4 animate-spin" /> : <PlusCircle className="mr-1.5 h-4 w-4" />}
            {isCreating ? "Creating..." : "Create agent"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}