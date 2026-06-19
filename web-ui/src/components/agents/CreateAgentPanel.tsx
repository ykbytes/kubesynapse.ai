import { useWorkspace } from "@/contexts/WorkspaceContext";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  Bot,
  Check,
  GitBranch,
  Globe,
  LoaderCircle,
  Lock,
  Package,
  PlusCircle,
  RefreshCw,
  Search,
  Wand2,
  X,
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
import { ModelSelector } from "@/components/settings/ModelSelector";
import { McpServerBadgeIcon } from "@/components/shared/McpServerBadgeIcon";
import { fetchCatalogSkillDetail, fetchMcpConnections, fetchSkillsCatalog, refreshSkillsCatalog, apiErrorMessage } from "../../lib/api";
import { A2A_ALLOWED_CALLERS_PLACEHOLDER } from "../../lib/a2a";
import { createOpenCodeConfigFileDraft } from "../../lib/opencodeConfig";
import {
  MCP_SERVERS_PLACEHOLDER,
  MCP_SIDECARS_PLACEHOLDER,
  parseMcpServersText,
  parseMcpSidecarsText,
} from "../../lib/mcp";
import { createSkillFileDraft } from "../../lib/skills";
import type { AgentInfo, CatalogSkill, CatalogSkillDetail, GitFormState, McpConnection, RuntimeKind, TextFileDraft, WorkflowInfo } from "../../types";
import { A2ACallerPicker } from "./A2ACallerPicker";
import { TextFileBundleEditor } from "../shared/TextFileBundleEditor";
import { ErrorBanner } from "../shared/ErrorBanner";
import { ErrorDialog } from "../shared/ErrorDialog";
import { SYSTEM_PROMPT_MAX_CHARS, systemPromptLengthError } from "../../lib/agentPrompt";
import { getRuntimeSignal } from "../../lib/agentSignals";

type ConnectionFilterValue = "all" | "selected" | "remote" | "hub" | "sidecar";

interface CreateAgentPanelProps {
  token: string;
  namespace: string;
  isEmptyWorkspace: boolean;
  name: string;
  model: string;
  systemPrompt: string;
  runtimeKind: RuntimeKind;
  mcpConnectionIds: string[];
  mcpServersText: string;
  mcpSidecarsText: string;
  a2aAllowedCallersText: string;
  agents: AgentInfo[];
  workflows: WorkflowInfo[];
  skillFileDrafts: TextFileDraft[];
  opencodeConfigFileDrafts: TextFileDraft[];
  isCreating: boolean;
  error: string;
  onMcpConnectionIdsChange: (value: string[]) => void;
  onMcpServersTextChange: (value: string) => void;
  onMcpSidecarsTextChange: (value: string) => void;
  onNameChange: (value: string) => void;
  onModelChange: (value: string) => void;
  onSystemPromptChange: (value: string) => void;
  onA2AAllowedCallersTextChange: (value: string) => void;
  onSkillFileDraftsChange: (value: TextFileDraft[]) => void;
  onOpenCodeConfigFileDraftsChange: (value: TextFileDraft[]) => void;
  onRuntimeKindChange: (value: RuntimeKind) => void;
  gitForm: GitFormState;
  onGitFormChange: (value: GitFormState) => void;
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

export function CreateAgentPanel({
  token,
  namespace,
  isEmptyWorkspace,
  name,
  model,
  systemPrompt,
  runtimeKind,
  mcpConnectionIds,
  mcpServersText,
  mcpSidecarsText,
  a2aAllowedCallersText,
  agents: workspaceAgents,
  workflows: workspaceWorkflows,
  skillFileDrafts,
  opencodeConfigFileDrafts,
  isCreating,
  error,
  onMcpConnectionIdsChange,
  onMcpServersTextChange,
  onMcpSidecarsTextChange,
  onNameChange,
  onModelChange,
  onSystemPromptChange,
  onA2AAllowedCallersTextChange,
  onSkillFileDraftsChange,
  onOpenCodeConfigFileDraftsChange,
  onRuntimeKindChange,
  gitForm,
  onGitFormChange,
  onCreate,
}: CreateAgentPanelProps) {
  const ws = useWorkspace();
  const [catalogSkills, setCatalogSkills] = useState<CatalogSkill[]>([]);
  const [mcpConnections, setMcpConnections] = useState<McpConnection[]>([]);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [catalogError, setCatalogError] = useState("");
  const [skillSearch, setSkillSearch] = useState("");
  const [skillCategory, setSkillCategory] = useState("");
  const [skillDetailsById, setSkillDetailsById] = useState<Record<string, CatalogSkillDetail>>({});
  const [skillBusyId, setSkillBusyId] = useState("");
  const [nameBlurred, setNameBlurred] = useState(false);
  const [modelBlurred, setModelBlurred] = useState(false);
  const [localError, setLocalError] = useState("");
  const [errorDialogOpen, setErrorDialogOpen] = useState(false);

  useEffect(() => {
    if (error) setErrorDialogOpen(true);
  }, [error]);
  const [connectionSearch, setConnectionSearch] = useState("");
  const [connectionFilter, setConnectionFilter] = useState<ConnectionFilterValue>("all");

  const systemPromptError = useMemo(() => systemPromptLengthError(systemPrompt), [systemPrompt]);
  const displayError = localError || systemPromptError || error;

  useEffect(() => {
    if (!systemPromptError && localError) {
      setLocalError("");
    }
  }, [localError, systemPromptError]);

  useEffect(() => {
    if (!token.trim()) {
      setCatalogSkills([]);
      setMcpConnections([]);
      setCatalogError("");
      return;
    }

    let cancelled = false;
    setCatalogLoading(true);
    setCatalogError("");

    Promise.all([fetchSkillsCatalog(token), fetchMcpConnections(token, namespace)])
      .then(([skills, connections]) => {
        if (cancelled) {
          return;
        }
        setCatalogSkills(skills);
        setMcpConnections(connections);
      })
      .catch((nextError) => {
        if (!cancelled) {
          setCatalogError(apiErrorMessage(nextError));
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
  }, [token, namespace]);

  const sidecarState = useMemo(() => {
    try {
      return {
        items: parseMcpSidecarsText(mcpSidecarsText),
        error: "",
      };
    } catch (nextError) {
      return {
        items: [] as Array<Record<string, unknown>>,
        error: nextError instanceof Error ? nextError.message : String(nextError),
      };
    }
  }, [mcpSidecarsText, runtimeKind]);

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

  const selectedConnections = useMemo(
    () => mcpConnections.filter((connection) => mcpConnectionIds.includes(connection.id)),
    [mcpConnections, mcpConnectionIds],
  );
  const quickSidecars = useMemo(
    () =>
      mcpConnections.filter(
        (c) =>
          c.transport === "sidecar" &&
          c.attachable &&
          c.support_level === "ready" &&
          c.validation.status === "valid",
      ),
    [mcpConnections],
  );
  const legacySharedServers = useMemo(() => parseMcpServersText(mcpServersText), [mcpServersText]);
  const legacyOverrideCount = legacySharedServers.length + sidecarState.items.length;
  const hasLegacyOverrides = legacyOverrideCount > 0;
  const legacyOverridesConflict = selectedConnections.length > 0 && hasLegacyOverrides;
  const filteredConnections = useMemo(() => {
    const query = connectionSearch.trim().toLowerCase();
    return [...mcpConnections]
      .filter((connection) => {
        if (connectionFilter === "selected" && !mcpConnectionIds.includes(connection.id)) {
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
        const leftSelected = mcpConnectionIds.includes(left.id);
        const rightSelected = mcpConnectionIds.includes(right.id);
        if (leftSelected !== rightSelected) {
          return leftSelected ? -1 : 1;
        }
        if (left.attachable !== right.attachable) {
          return left.attachable ? -1 : 1;
        }
        return left.name.localeCompare(right.name);
      });
  }, [connectionFilter, connectionSearch, mcpConnectionIds, mcpConnections]);

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
      const skills = await fetchSkillsCatalog(token);
      setCatalogSkills(skills);
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

  function handleToggleSavedConnection(connectionId: string) {
    const connection = mcpConnections.find((item) => item.id === connectionId);
    if (!connection) {
      return;
    }
    if (!connection.attachable) {
      setCatalogError(connection.status_reason ?? `${connection.name} is saved but cannot be attached to agents yet.`);
      return;
    }
    if (mcpConnectionIds.includes(connectionId)) {
      onMcpConnectionIdsChange(mcpConnectionIds.filter((id) => id !== connectionId));
      setCatalogError("");
      return;
    }
    onMcpConnectionIdsChange([...mcpConnectionIds, connectionId]);
    setCatalogError("");
  }

  function handleOpenMcpManagement() {
    ws.setAgentCreateMode(false);
    ws.setCatalogTab("mcp");
    ws.setActiveView("catalog");
    setCatalogError("");
  }

  function handleCreateClick() {
    if (systemPromptError) {
      setLocalError(systemPromptError);
      return;
    }
    setLocalError("");
    onCreate();
  }

  return (
    <Card className="border-border/70 bg-card/95 shadow-[0_24px_80px_-48px_rgba(0,0,0,0.65)]">
      <CardHeader className="pb-3">
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border border-primary/20 bg-primary/10 text-primary shadow-inner shadow-primary/10">
            <Bot className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1 space-y-2">
            <div className="flex flex-wrap items-start gap-2">
              <CardTitle className="min-w-0 break-words text-base leading-tight">
                {isEmptyWorkspace ? "Create your first agent" : "Create a new agent"}
              </CardTitle>
              <Badge variant="secondary">guided setup</Badge>
            </div>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
              <span>{getRuntimeSignal(runtimeKind).label} runtime</span>
              <span>{skillFileDrafts.length} skill file{skillFileDrafts.length === 1 ? "" : "s"}</span>
              <span>{selectedConnections.length} saved MCP connection{selectedConnections.length === 1 ? "" : "s"}</span>
              {hasLegacyOverrides ? (
                <span>{legacyOverrideCount} legacy override{legacyOverrideCount === 1 ? "" : "s"}</span>
              ) : null}
            </div>
            <CardDescription className="max-w-none break-words text-sm leading-5">
              Start with identity, then attach only the skills and managed MCP connections this OpenCode agent actually needs.
            </CardDescription>
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
            <div className="grid gap-4">
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
                    <CardDescription>Choose the agent runtime that fits your use case.</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <div className="space-y-1.5">
                      <Label className="text-xs">Runtime kind</Label>
                       <Select value={runtimeKind} onValueChange={(v) => onRuntimeKindChange(v as RuntimeKind)}>
                         <SelectTrigger className="h-8 text-xs">
                           <SelectValue />
                         </SelectTrigger>
                         <SelectContent>
                           {(["opencode"] as RuntimeKind[]).map((kind) => {
                             const signal = getRuntimeSignal(kind);
                             return (
                               <SelectItem key={kind} value={kind} className="text-xs">
                                <span className="inline-flex items-center gap-1.5">
                                  <signal.icon className="h-3.5 w-3.5" />
                                  {signal.label}
                                </span>
                              </SelectItem>
                            );
                          })}
                          <div className="border-t border-border/40 mt-1 pt-1 px-2">
                            <p className="text-[9px] text-muted-foreground/60 mb-1">Alpha (not recommended for production)</p>
                          </div>
                          {(["pi", "mistral-vibe"] as RuntimeKind[]).map((kind) => {
                            const signal = getRuntimeSignal(kind);
                            return (
                              <SelectItem key={kind} value={kind} className="text-xs opacity-60">
                                <span className="inline-flex items-center gap-1.5">
                                  <signal.icon className="h-3.5 w-3.5" />
                                  {signal.label}
                                  <Badge variant="outline" className="h-3 px-1 text-[9px]">Alpha</Badge>
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
                          Best for autonomous multi-turn coding tasks with structured output, session persistence, context-overflow recovery, shared MCP routing, and managed sidecars.
                        </p>
                      </div>
                    ) : (
                      <div className="rounded-2xl border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-left text-foreground">
                        <p className="font-medium text-sm">{runtimeKind === "pi" ? "Pi" : "Mistral Vibe"} runtime <span className="text-[10px] font-normal text-amber-400 ml-1">(alpha)</span></p>
                        <p className="mt-1 text-xs leading-5 text-muted-foreground">
                          This runtime is in alpha. OpenCode is recommended for production workloads.
                        </p>
                      </div>
                    )}
                  </CardContent>
                </Card>
              </div>
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
                    onChange={(e) => {
                      if (localError) {
                        setLocalError("");
                      }
                      onSystemPromptChange(e.target.value);
                    }}
                    placeholder="You are a senior software engineer. Follow these guidelines: (1) Think step-by-step before acting. (2) Read existing code before making changes. (3) Verify your work by running tests. (4) Be concise and factual — do not fabricate information."
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
            <>
              {/* Quick-Capabilities Section */}
              {quickSidecars.length > 0 && (
                <div className="space-y-2">
                  <p className="text-xs font-medium text-muted-foreground">Quick sidecars</p>
                  <div className="flex flex-wrap gap-2">
                    {quickSidecars.map((connection) => {
                      const selected = mcpConnectionIds.includes(connection.id);
                      return (
                        <button
                          key={connection.id}
                          type="button"
                          onClick={() => handleToggleSavedConnection(connection.id)}
                          className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs transition ${
                            selected
                              ? "border-primary bg-primary text-primary-foreground"
                              : "border-border/60 bg-background/60 text-muted-foreground hover:border-primary/30 hover:text-foreground"
                          }`}
                          aria-pressed={selected}
                        >
                          <McpServerBadgeIcon
                            serverId={connection.server_id}
                            serverName={connection.server_name ?? connection.server_id}
                            transport={connection.transport}
                            size="xs"
                          />
                          <span>{connection.name}</span>
                          {selected && <Check className="h-3 w-3" />}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Attached Tools Bar */}
              <div className="space-y-2">
                <p className="text-xs font-medium text-muted-foreground">Attached</p>
                {selectedConnections.length > 0 ? (
                  <div className="flex flex-wrap gap-2">
                    {selectedConnections.map((connection) => (
                      <button
                        key={connection.id}
                        type="button"
                        onClick={() => handleToggleSavedConnection(connection.id)}
                        className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] transition hover:opacity-80 ${
                          connection.transport === "remote"
                            ? "border-sky-500/30 bg-sky-500/10 text-sky-300"
                            : connection.transport === "hub"
                              ? "border-violet-500/30 bg-violet-500/10 text-violet-300"
                              : "border-amber-500/30 bg-amber-500/10 text-amber-300"
                        }`}
                        aria-label={`Remove ${connection.name}`}
                      >
                        <span>{connection.name}</span>
                        <X className="h-3 w-3" />
                      </button>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground">No tools attached</p>
                )}
              </div>

              {/* Simplified Connection List */}
              <div className="space-y-3 rounded-2xl border border-border/70 bg-card/55 p-4">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                  <div className="relative flex-1">
                    <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      value={connectionSearch}
                      onChange={(event) => setConnectionSearch(event.target.value)}
                      placeholder="Search connections..."
                      className="pl-9"
                    />
                  </div>
                  <div className="inline-flex rounded-lg border border-border/60 bg-background/60 p-0.5">
                    {(["all", "selected", "remote", "hub", "sidecar"] as ConnectionFilterValue[]).map((f) => (
                      <button
                        key={f}
                        type="button"
                        onClick={() => setConnectionFilter(f)}
                        className={`px-2.5 py-1 text-xs rounded-md transition ${
                          connectionFilter === f ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
                        }`}
                      >
                        {f === "all" ? "All" : f === "selected" ? "Selected" : f.charAt(0).toUpperCase() + f.slice(1)}
                      </button>
                    ))}
                  </div>
                </div>

                {catalogError ? (
                  <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                    {catalogError}
                  </div>
                ) : null}
                {sidecarState.error ? (
                  <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
                    The raw sidecar JSON is invalid. Fix it in Legacy raw overrides before mixing it with saved connections.
                  </div>
                ) : null}

                {catalogLoading ? (
                  <div className="flex items-center justify-center rounded-lg border border-dashed border-border/70 bg-background/40 px-4 py-6 text-sm text-muted-foreground">
                    <LoaderCircle className="mr-2 h-4 w-4 animate-spin" /> Loading saved MCP connections...
                  </div>
                ) : mcpConnections.length > 0 ? (
                  filteredConnections.length > 0 ? (
                    <ScrollArea className="max-h-[320px] pr-2">
                      <div className="space-y-2">
                        {filteredConnections.map((connection) => {
                          const selected = mcpConnectionIds.includes(connection.id);
                          const blocked = !connection.attachable;
                          return (
                            <div
                              key={connection.id}
                              className={`flex items-center gap-3 rounded-xl border px-3 py-2.5 transition ${
                                selected
                                  ? "border-primary/25 bg-primary/[0.06]"
                                  : blocked
                                    ? "border-border/40 bg-background/30 opacity-60"
                                    : "border-border/50 bg-background/60"
                              }`}
                            >
                              <McpServerBadgeIcon
                                serverId={connection.server_id}
                                serverName={connection.server_name ?? connection.server_id}
                                transport={connection.transport}
                                size="sm"
                              />
                              <div className="min-w-0 flex-1">
                                <div className="flex items-center gap-2">
                                  <span className="text-sm font-medium text-foreground">{connection.name}</span>
                                  {blocked && (
                                    <Badge variant="outline" className="border-amber-500/30 bg-amber-500/10 text-[10px] text-amber-300">
                                      Needs setup
                                    </Badge>
                                  )}
                                </div>
                                <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                                  <span>{connection.server_name ?? connection.server_id}</span>
                                  <span className="text-muted-foreground/40">·</span>
                                  <span className={`capitalize ${
                                    connection.transport === "remote"
                                      ? "text-sky-300"
                                      : connection.transport === "hub"
                                        ? "text-violet-300"
                                        : "text-amber-300"
                                  }`}>{connection.transport}</span>
                                  <span className="text-muted-foreground/40">·</span>
                                  <span className={connection.support_level === "ready" ? "text-emerald-500" : connection.support_level === "limited" ? "text-amber-500" : "text-slate-400"}>
                                    {connection.support_level}
                                  </span>
                                </div>
                              </div>
                              <Button
                                size="sm"
                                variant={selected ? "secondary" : "outline"}
                                disabled={blocked}
                                onClick={() => handleToggleSavedConnection(connection.id)}
                                className="shrink-0 text-xs h-8"
                              >
                                {selected ? (
                                  <>
                                    <Check className="mr-1 h-3.5 w-3.5" />
                                    Attached
                                  </>
                                ) : (
                                  "Attach"
                                )}
                              </Button>
                            </div>
                          );
                        })}
                      </div>
                    </ScrollArea>
                  ) : (
                    <div className="rounded-lg border border-dashed border-border/70 bg-background/40 px-4 py-6 text-sm text-muted-foreground">
                      No saved MCP connections match the current search or transport filter.
                    </div>
                  )
                ) : (
                  <div className="rounded-lg border border-dashed border-border/70 bg-background/40 px-4 py-6 text-sm text-muted-foreground">
                    <p>No saved MCP connections exist in this namespace yet.</p>
                    <p className="mt-1 text-xs leading-5">Create them in the MCP page first, then return here to bind them to the agent.</p>
                    <Button variant="outline" size="sm" className="mt-3" onClick={handleOpenMcpManagement}>
                      Create saved connection
                    </Button>
                  </div>
                )}

                {mcpConnections.length > 0 && (
                  <Button variant="ghost" size="sm" className="text-xs text-muted-foreground" onClick={handleOpenMcpManagement}>
                    <PlusCircle className="mr-1.5 h-3.5 w-3.5" />
                    Add connection
                  </Button>
                )}
              </div>

              {legacyOverridesConflict ? (
                <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
                  This agent currently mixes saved MCP connections with legacy raw overrides. Keep only one path for the same MCP so the runtime does not see duplicate routes.
                </div>
              ) : hasLegacyOverrides ? (
                <div className="rounded-2xl border border-amber-500/20 bg-amber-500/5 px-4 py-3 text-sm text-muted-foreground">
                  Legacy raw overrides are active. Prefer moving them into saved MCP connections so they can be validated, reused, and shown clearly in the namespace connection list.
                </div>
              ) : null}

              <Accordion type="single" collapsible className="rounded-2xl border border-border/70 bg-background/50 px-4">
                <AccordionItem value="advanced-routing" className="border-none">
                  <AccordionTrigger className="py-3 text-xs font-medium text-muted-foreground hover:text-foreground">Legacy raw overrides</AccordionTrigger>
                  <AccordionContent className="space-y-4">
                    <div className="rounded-xl border border-border/60 bg-background/60 px-3 py-3 text-[11px] leading-5 text-muted-foreground">
                      Use this only when you are migrating older agents or attaching an MCP endpoint that is not modeled yet as a saved connection. The saved-connection binding above is the preferred path.
                    </div>
                    <div className="grid gap-4 xl:grid-cols-2">
                      <div className="space-y-1.5">
                        <div className="flex items-center justify-between gap-2">
                          <Label className="text-xs">Legacy shared MCP endpoints</Label>
                          {legacySharedServers.length > 0 ? (
                            <Button variant="ghost" size="sm" className="h-7 px-2 text-[11px]" onClick={() => onMcpServersTextChange("")}>
                              Clear
                            </Button>
                          ) : null}
                        </div>
                        <>
                          <Textarea
                            rows={4}
                            value={mcpServersText}
                            onChange={(e) => onMcpServersTextChange(e.target.value)}
                            placeholder={MCP_SERVERS_PLACEHOLDER}
                            className="font-mono text-xs"
                          />
                          <p className="text-[11px] text-muted-foreground">One legacy shared MCP endpoint per line. Prefer creating a saved connection instead so namespace reuse and validation work automatically.</p>
                        </>
                      </div>
                      <div className="space-y-1.5">
                        <div className="flex items-center justify-between gap-2">
                          <Label className="text-xs">Legacy raw sidecar JSON</Label>
                          {mcpSidecarsText.trim() ? (
                            <Button variant="ghost" size="sm" className="h-7 px-2 text-[11px]" onClick={() => onMcpSidecarsTextChange("")}>
                              Clear
                            </Button>
                          ) : null}
                        </div>
                        <Textarea
                          rows={7}
                          value={mcpSidecarsText}
                          onChange={(e) => onMcpSidecarsTextChange(e.target.value)}
                          placeholder={MCP_SIDECARS_PLACEHOLDER}
                          className="font-mono text-xs"
                        />
                        <p className="text-[11px] text-muted-foreground">Full access to custom sidecar specs and manual overrides. Keep this for expert-only edge cases that are not represented in the managed catalog yet.</p>
                      </div>
                    </div>
                  </AccordionContent>
                </AccordionItem>
              </Accordion>
            </>
          </TabsContent>

          <TabsContent value="files" className="animate-fade-in space-y-4">
            <div className="grid gap-4 xl:grid-cols-[1fr_280px]">
              <Card className="shadow-none">
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

                  <div className="max-h-[480px] overflow-y-auto pr-1">
                    <div className="space-y-2">
                      {filteredSkills.map((skill) => {
                        const detail = skillDetailsById[skill.id];
                        const attached = hasSkillAttached(detail, draftPaths);
                        return (
                          <div
                            key={skill.id}
                            className={`rounded-lg border p-3 transition ${
                              attached
                                ? "border-primary/20 bg-primary/5"
                                : "border-border/30 bg-muted/15 hover:bg-muted/25"
                            }`}
                          >
                            <div className="flex items-start justify-between gap-3">
                              <div className="min-w-0 flex-1">
                                <p className="text-sm font-medium text-foreground">{skill.name}</p>
                                <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
                                  {skill.description}
                                </p>
                                <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                                  <Badge variant="outline" className="text-[10px] px-1.5 py-0 capitalize">
                                    {skill.category}
                                  </Badge>
                                  {skill.tags.slice(0, 3).map((tag) => (
                                    <Badge key={tag} variant="secondary" className="text-[10px] px-1.5 py-0">
                                      {tag}
                                    </Badge>
                                  ))}
                                </div>
                              </div>
                              <Button
                                variant={attached ? "secondary" : "default"}
                                size="sm"
                                className="h-7 shrink-0 text-xs"
                                onClick={() => void handleToggleSkill(skill.id)}
                                disabled={skillBusyId === skill.id || !token.trim()}
                              >
                                {skillBusyId === skill.id ? <LoaderCircle className="mr-1 size-3.5 animate-spin" /> : null}
                                {attached ? "Remove" : "Attach"}
                              </Button>
                            </div>
                          </div>
                        );
                      })}
                      {!catalogLoading && filteredSkills.length === 0 ? (
                        <div className="rounded-lg border border-dashed border-border/40 py-8 text-center text-sm text-muted-foreground">
                          No skills match the current filters.
                        </div>
                      ) : null}
                    </div>
                  </div>
                </CardContent>
              </Card>

              {/* Compact sidebar */}
              <div className="space-y-3">
                <Card className="shadow-none">
                  <CardContent className="p-4">
                    <div className="grid grid-cols-2 gap-2">
                      <div className="rounded-lg border border-border/30 bg-muted/15 p-2.5">
                        <p className="text-[10px] uppercase tracking-wide text-muted-foreground/60">Skills</p>
                        <p className="mt-0.5 text-lg font-semibold text-foreground">{selectedCatalogSkills.length}</p>
                      </div>
                      <div className="rounded-lg border border-border/30 bg-muted/15 p-2.5">
                        <p className="text-[10px] uppercase tracking-wide text-muted-foreground/60">Files</p>
                        <p className="mt-0.5 text-lg font-semibold text-foreground">{skillFileDrafts.length}</p>
                      </div>
                    </div>
                    <div className="mt-3 space-y-1.5">
                      {selectedCatalogSkills.length > 0 ? (
                        selectedCatalogSkills.map((skill) => (
                          <div key={skill.id} className="flex items-center gap-1.5">
                            <span className="size-1.5 shrink-0 rounded-full bg-primary/40" />
                            <span className="truncate text-xs text-foreground/70">{skill.name}</span>
                          </div>
                        ))
                      ) : (
                        <p className="text-xs text-muted-foreground/50">No skills attached yet.</p>
                      )}
                    </div>
                  </CardContent>
                </Card>
              </div>
            </div>

            <Accordion type="single" collapsible className="rounded-xl border border-border/40 bg-muted/15 px-4">
              <AccordionItem value="advanced-files" className="border-none">
                <AccordionTrigger className="py-4 text-sm font-medium">Advanced file editors</AccordionTrigger>
                <AccordionContent className="space-y-4">
                  <TextFileBundleEditor
                    title="Skill files"
                    description="Custom Markdown skill documents mounted into the runtime. Use this for advanced edits or entirely custom skills."
                    entries={skillFileDrafts}
                    addLabel="Add custom skill file"
                    emptyMessage="No skill documents attached. Use the library above or add a custom file manually."
                    pathHint="Repo-relative Markdown path, e.g. skills/reviewer/SKILL.md"
                    contentHint="Full skill document including optional frontmatter for tools, MCP, or A2A metadata."
                    onAdd={() => onSkillFileDraftsChange([...skillFileDrafts, createSkillFileDraft()])}
                    onChange={onSkillFileDraftsChange}
                  />
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
                      <CardDescription>GitHub runtime credentials are not available in the OpenCode-only deployment path.</CardDescription>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="rounded-2xl border border-border/60 bg-background/60 p-4 text-sm text-muted-foreground">
                    OpenCode agents can still use ordinary git repository credentials and shared MCP servers, but the legacy per-agent <span className="font-mono text-foreground">github_config</span> secret path is no longer accepted by the gateway.
                  </div>
                </CardContent>
              </Card>
            </div>
          </TabsContent>
        </Tabs>

        {displayError && (
          <div className="mt-4">
            <ErrorBanner error={displayError} onDismiss={() => setLocalError("")} />
          </div>
        )}

        <div className="mt-5 flex flex-wrap items-center justify-between gap-4 border-t border-border pt-4">
          {systemPromptError ? (
            <p className="max-w-2xl text-xs leading-5 text-destructive">
              {systemPromptError}
            </p>
          ) : (
            <p className="max-w-2xl text-xs leading-5 text-muted-foreground">
              Creation keeps all existing functionality intact. The guided pickers write into the same MCP sidecar specs and skill files that the runtime already understands.
            </p>
          )}
          <Button onClick={handleCreateClick} disabled={!name.trim() || !model.trim() || isCreating || Boolean(systemPromptError)} className="min-w-[160px]">
            {isCreating ? <LoaderCircle className="mr-1.5 h-4 w-4 animate-spin" /> : <PlusCircle className="mr-1.5 h-4 w-4" />}
            {isCreating ? "Creating..." : "Create agent"}
          </Button>
        </div>
      </CardContent>
      <ErrorDialog
        error={error || localError ? new Error(error || localError) : null}
        open={errorDialogOpen}
        onClose={() => setErrorDialogOpen(false)}
      />
    </Card>
  );
}
