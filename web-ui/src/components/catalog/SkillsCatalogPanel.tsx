import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { Search, Package, LoaderCircle, ChevronLeft, Plus, Check, Bot } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { fetchSkillsCatalog, fetchCatalogSkillDetail, listAgents, updateAgent } from "@/lib/api";
import type { CatalogSkill, CatalogSkillDetail, AgentInfo } from "@/types";
import { cn } from "@/lib/utils";

const CATEGORY_COLORS: Record<string, string> = {
  design: "border-violet-500/20 bg-violet-500/10 text-violet-400",
  development: "border-sky-500/20 bg-sky-500/10 text-sky-400",
  document: "border-amber-500/20 bg-amber-500/10 text-amber-400",
  communication: "border-emerald-500/20 bg-emerald-500/10 text-emerald-400",
  productivity: "border-cyan-500/20 bg-cyan-500/10 text-cyan-400",
};

/* ── Props ── */

interface SkillsCatalogPanelProps {
  token: string;
  namespace: string;
  onAttachSkill?: (skillId: string, files: Record<string, string>) => void;
}

/* ── Component ── */

export function SkillsCatalogPanel({ token, namespace, onAttachSkill }: SkillsCatalogPanelProps) {
  const [skills, setSkills] = useState<CatalogSkill[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [selectedSkill, setSelectedSkill] = useState<CatalogSkillDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [attachModalOpen, setAttachModalOpen] = useState(false);
  const [attachSkillDetail, setAttachSkillDetail] = useState<CatalogSkillDetail | null>(null);
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [selectedAgentNames, setSelectedAgentNames] = useState<Set<string>>(new Set());
  const [agentsLoading, setAgentsLoading] = useState(false);
  const [attaching, setAttaching] = useState(false);

  useEffect(() => {
    if (!token) {
      setSkills([]);
      return;
    }
    setLoading(true);
    setError("");
    fetchSkillsCatalog(token, categoryFilter || undefined, searchQuery || undefined)
      .then((skillsData) => setSkills(skillsData))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [token, categoryFilter, searchQuery]);

  async function handleViewSkill(skillId: string) {
    setDetailLoading(true);
    try {
      const detail = await fetchCatalogSkillDetail(token, skillId);
      setSelectedSkill(detail);
    } catch (e) {
      setError(String(e));
    } finally {
      setDetailLoading(false);
    }
  }

  const loadAgents = useCallback(async () => {
    if (!token) return;
    setAgentsLoading(true);
    try {
      const list = await listAgents(token, namespace);
      setAgents(list);
    } catch {
      setAgents([]);
    } finally {
      setAgentsLoading(false);
    }
  }, [token, namespace]);

  async function handleOpenAttachModal(skillId: string) {
    try {
      const detail = await fetchCatalogSkillDetail(token, skillId);
      setAttachSkillDetail(detail);
      setSelectedAgentNames(new Set());
      setAttachModalOpen(true);
      void loadAgents();
    } catch (e) {
      toast.error("Failed to load skill details");
    }
  }

  function toggleAgent(name: string) {
    setSelectedAgentNames((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  async function handleAttachToAgents() {
    if (!attachSkillDetail || selectedAgentNames.size === 0) return;
    setAttaching(true);
    let successCount = 0;
    let failCount = 0;
    for (const agentName of selectedAgentNames) {
      try {
        const skillFiles = attachSkillDetail.assets;
        await updateAgent(token, namespace, agentName, {
          model: agents.find((a) => a.name === agentName)?.model ?? "",
          skills: { files: skillFiles },
        });
        successCount++;
      } catch {
        failCount++;
      }
    }
    setAttaching(false);
    setAttachModalOpen(false);
    if (successCount > 0) {
      toast.success(`Skill attached to ${successCount} agent${successCount > 1 ? "s" : ""}`);
    }
    if (failCount > 0) {
      toast.error(`Failed to attach to ${failCount} agent${failCount > 1 ? "s" : ""}`);
    }
  }

  const categories = [...new Set(skills.map((s) => s.category))].sort();

  // ─── Skill detail view ───
  if (selectedSkill) {
    return (
      <div className="flex h-full flex-col overflow-hidden">
        <div className="flex shrink-0 items-center gap-3 border-b border-border/30 px-4 py-3">
          <Button variant="ghost" size="sm" onClick={() => setSelectedSkill(null)} className="h-7 text-xs">
            <ChevronLeft className="size-3.5" /> Back
          </Button>
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-sm font-medium text-foreground">{selectedSkill.name}</h3>
            <p className="truncate text-xs text-muted-foreground">{selectedSkill.description}</p>
          </div>
          <Button
            size="sm"
            className="h-7 text-xs"
            onClick={() => void handleOpenAttachModal(selectedSkill.id)}
          >
            <Plus className="size-3.5" />
            Attach to Agents
          </Button>
        </div>

        <ScrollArea className="flex-1 min-h-0">
          <div className="space-y-4 p-4">
            <div className="flex flex-wrap gap-2">
              <Badge variant="outline" className={CATEGORY_COLORS[selectedSkill.category] ?? ""}>
                {selectedSkill.category}
              </Badge>
              {selectedSkill.tags.map((tag) => (
                <Badge key={tag} variant="secondary" className="text-xs">{tag}</Badge>
              ))}
            </div>

            <div>
              <h4 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Files ({selectedSkill.files.length})
              </h4>
              <div className="space-y-2">
                {selectedSkill.files.map((file) => (
                  <div key={file} className="rounded-lg border border-border/30 bg-muted/15 p-3">
                    <p className="text-xs font-mono text-foreground">{file}</p>
                    {selectedSkill.assets[file] && (
                      <pre className="mt-2 max-h-48 overflow-auto text-xs text-muted-foreground whitespace-pre-wrap break-words">
                        {selectedSkill.assets[file].slice(0, 2000)}
                        {selectedSkill.assets[file].length > 2000 && "\n... (truncated)"}
                      </pre>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </ScrollArea>

        <AttachToAgentsModal
          open={attachModalOpen}
          onClose={() => setAttachModalOpen(false)}
          skill={attachSkillDetail}
          agents={agents}
          selectedAgentNames={selectedAgentNames}
          onToggleAgent={toggleAgent}
          onAttach={handleAttachToAgents}
          attaching={attaching}
          agentsLoading={agentsLoading}
          onCreateNew={() => {
            if (attachSkillDetail && onAttachSkill) {
              onAttachSkill(attachSkillDetail.id, attachSkillDetail.assets);
            }
            setAttachModalOpen(false);
          }}
        />
      </div>
    );
  }

  // ─── Skills list view ───
  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Filter bar */}
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border/30 px-4 py-2.5">
        <div className="relative flex-1 min-w-[12rem]">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search skills..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="h-8 pl-8 text-sm"
          />
        </div>
        <Select value={categoryFilter || "__all__"} onValueChange={(v) => setCategoryFilter(v === "__all__" ? "" : v)}>
          <SelectTrigger className="h-8 w-[140px] text-xs">
            <SelectValue placeholder="All categories" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">All categories</SelectItem>
            {categories.map((cat) => (
              <SelectItem key={cat} value={cat}>{cat}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Skills list */}
      <ScrollArea className="flex-1 min-h-0">
        <div className="space-y-2 p-4">
          {error && (
            <div className="rounded-lg border border-red-500/20 bg-red-500/5 px-3 py-2 text-sm text-red-400">
              {error}
            </div>
          )}

          {!token ? (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <Package className="size-8 text-muted-foreground/20" />
              <p className="mt-3 text-sm text-muted-foreground">Connect to a gateway to browse the skills catalog.</p>
            </div>
          ) : loading ? (
            <div className="space-y-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="rounded-lg border border-border/30 p-3">
                  <Skeleton className="h-4 w-32" />
                  <Skeleton className="mt-2 h-3 w-full" />
                </div>
              ))}
            </div>
          ) : skills.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <Package className="size-8 text-muted-foreground/20" />
              <p className="mt-3 text-sm text-muted-foreground">No skills found.</p>
            </div>
          ) : (
            skills.map((skill) => (
              <div
                key={skill.id}
                className="group flex items-center gap-3 rounded-lg border border-border/30 bg-muted/15 p-3 transition-all hover:border-border/50 hover:bg-muted/25 cursor-pointer"
                onClick={() => void handleViewSkill(skill.id)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") void handleViewSkill(skill.id);
                }}
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <p className="truncate text-sm font-medium text-foreground">{skill.name}</p>
                    <Badge variant="outline" className={cn("text-[10px]", CATEGORY_COLORS[skill.category] ?? "")}>
                      {skill.category}
                    </Badge>
                  </div>
                  <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground/70">{skill.description}</p>
                  <div className="mt-1.5 flex items-center gap-2">
                    <span className="text-[10px] text-muted-foreground/50">
                      {skill.files.length} file{skill.files.length !== 1 ? "s" : ""}
                    </span>
                    {skill.tags.slice(0, 3).map((tag) => (
                      <Badge key={tag} variant="secondary" className="text-[10px] px-1 py-0">{tag}</Badge>
                    ))}
                  </div>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 shrink-0 text-xs opacity-0 transition-opacity group-hover:opacity-100"
                  onClick={(e) => {
                    e.stopPropagation();
                    void handleOpenAttachModal(skill.id);
                  }}
                >
                  <Plus className="size-3" />
                  Attach
                </Button>
              </div>
            ))
          )}
        </div>
      </ScrollArea>

      {detailLoading && (
        <div className="absolute inset-0 flex items-center justify-center bg-background/50">
          <LoaderCircle className="size-5 animate-spin text-muted-foreground" />
        </div>
      )}

      <AttachToAgentsModal
        open={attachModalOpen}
        onClose={() => setAttachModalOpen(false)}
        skill={attachSkillDetail}
        agents={agents}
        selectedAgentNames={selectedAgentNames}
        onToggleAgent={toggleAgent}
        onAttach={handleAttachToAgents}
        attaching={attaching}
        agentsLoading={agentsLoading}
        onCreateNew={() => {
          if (attachSkillDetail && onAttachSkill) {
            onAttachSkill(attachSkillDetail.id, attachSkillDetail.assets);
          }
          setAttachModalOpen(false);
        }}
      />
    </div>
  );
}

// ─── Attach to Agents Modal ──────────────────────────────────────────────────

function AttachToAgentsModal({
  open,
  onClose,
  skill,
  agents,
  selectedAgentNames,
  onToggleAgent,
  onAttach,
  attaching,
  agentsLoading,
  onCreateNew,
}: {
  open: boolean;
  onClose: () => void;
  skill: CatalogSkillDetail | null;
  agents: AgentInfo[];
  selectedAgentNames: Set<string>;
  onToggleAgent: (name: string) => void;
  onAttach: () => void;
  attaching: boolean;
  agentsLoading: boolean;
  onCreateNew: () => void;
}) {
  if (!skill) return null;

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg p-0">
        <DialogHeader className="border-b border-border/40 p-4">
          <DialogTitle className="text-sm">Attach skill to agents</DialogTitle>
          <DialogDescription className="text-xs">
            Select one or more agents to attach <strong className="text-foreground">{skill.name}</strong> to.
            The skill files will be merged into each agent's skill configuration.
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[400px] overflow-y-auto p-4">
          {agentsLoading ? (
            <div className="flex items-center justify-center py-8">
              <LoaderCircle className="size-5 animate-spin text-muted-foreground" />
            </div>
          ) : agents.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-8 text-center">
              <Bot className="size-8 text-muted-foreground/20" />
              <p className="mt-2 text-sm text-muted-foreground">No agents available in this namespace.</p>
            </div>
          ) : (
            <div className="space-y-1.5">
              {agents.map((agent) => {
                const isSelected = selectedAgentNames.has(agent.name);
                return (
                  <button
                    key={agent.name}
                    type="button"
                    onClick={() => onToggleAgent(agent.name)}
                    className={cn(
                      "flex w-full items-center gap-3 rounded-lg border p-3 text-left transition-all",
                      isSelected
                        ? "border-primary/30 bg-primary/5 ring-1 ring-primary/15"
                        : "border-border/30 bg-muted/15 hover:bg-muted/25",
                    )}
                  >
                    <div className={cn(
                      "flex size-5 shrink-0 items-center justify-center rounded-md border transition-colors",
                      isSelected ? "border-primary bg-primary text-primary-foreground" : "border-border/50",
                    )}>
                      {isSelected && <Check className="size-3" />}
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-foreground">{agent.name}</p>
                      <p className="truncate text-xs text-muted-foreground/60">{agent.model}</p>
                    </div>
                    <Badge variant="outline" className="shrink-0 text-[10px] capitalize">
                      {agent.runtime_kind ?? "opencode"}
                    </Badge>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <div className="flex items-center justify-between gap-2 border-t border-border/40 p-4">
          <Button variant="ghost" size="sm" className="text-xs" onClick={onCreateNew}>
            <Plus className="size-3.5" />
            Create new agent
          </Button>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" className="h-8 text-xs" onClick={onClose}>
              Cancel
            </Button>
            <Button
              size="sm"
              className="h-8 text-xs"
              disabled={selectedAgentNames.size === 0 || attaching}
              onClick={onAttach}
            >
              {attaching ? (
                <LoaderCircle className="size-3.5 animate-spin" />
              ) : (
                <>Attach to {selectedAgentNames.size} agent{selectedAgentNames.size === 1 ? "" : "s"}</>
              )}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
