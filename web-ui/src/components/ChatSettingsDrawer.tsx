import { memo } from "react";
import { Settings2, Plus, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
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
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import type { AgentDiscoveryPeer, RuntimeKind, SpecialistSubagentDraft } from "../types";

/* ------------------------------------------------------------------ */
/*  Collapsible section (local to drawer)                             */
/* ------------------------------------------------------------------ */
function DrawerSection({
  title,
  badge,
  children,
}: {
  title: string;
  badge?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{title}</h4>
        {badge && (
          <Badge variant="outline" className="text-[10px]">{badge}</Badge>
        )}
      </div>
      {children}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Props                                                             */
/* ------------------------------------------------------------------ */
interface ChatSettingsDrawerProps {
  runtimeKind: RuntimeKind;
  /* A2A routing */
  a2aTargetAgent: string;
  a2aTargetNamespace: string;
  a2aTimeoutSeconds: string;
  onA2ATargetAgentChange: (value: string) => void;
  onA2ATargetNamespaceChange: (value: string) => void;
  onA2ATimeoutSecondsChange: (value: string) => void;
  /* Specialist team */
  specialistSubagents: SpecialistSubagentDraft[];
  specialistTeamConfigured: boolean;
  subagentStrategy: "sequential" | "parallel";
  onSubagentStrategyChange: (value: "sequential" | "parallel") => void;
  onAddSpecialistSubagent: () => void;
  onUpdateSpecialistSubagent: (id: string, patch: Partial<SpecialistSubagentDraft>) => void;
  onRemoveSpecialistSubagent: (id: string) => void;
  onClearSpecialistTeam: () => void;
  /* Discovery */
  discoveryPeers: AgentDiscoveryPeer[];
  discoveryLoading: boolean;
  discoveryError: string;
  /* Goose */
  gooseMaxTurns: string;
  gooseWorkingDirectory: string;
  gooseSystemPrompt: string;
  onGooseMaxTurnsChange: (value: string) => void;
  onGooseWorkingDirectoryChange: (value: string) => void;
  /* OpenCode */
  opencodeOutputFormat: string;
  opencodeAutonomous: boolean;
  opencodeMaxTurns: string;
  opencodeWorkingDirectory: string;
  onOpenCodeOutputFormatChange: (value: string) => void;
  onOpenCodeAutonomousChange: (value: boolean) => void;
  onOpenCodeMaxTurnsChange: (value: string) => void;
  onOpenCodeWorkingDirectoryChange: (value: string) => void;
}

export const ChatSettingsDrawer = memo(function ChatSettingsDrawer(props: ChatSettingsDrawerProps) {
  const {
    runtimeKind,
    a2aTargetAgent, a2aTargetNamespace, a2aTimeoutSeconds,
    onA2ATargetAgentChange, onA2ATargetNamespaceChange, onA2ATimeoutSecondsChange,
    specialistSubagents, specialistTeamConfigured, subagentStrategy,
    onSubagentStrategyChange, onAddSpecialistSubagent, onUpdateSpecialistSubagent,
    onRemoveSpecialistSubagent, onClearSpecialistTeam,
    discoveryPeers, discoveryLoading, discoveryError,
    gooseMaxTurns, gooseWorkingDirectory, gooseSystemPrompt,
    onGooseMaxTurnsChange, onGooseWorkingDirectoryChange,
    opencodeOutputFormat, opencodeAutonomous, opencodeMaxTurns, opencodeWorkingDirectory,
    onOpenCodeOutputFormatChange, onOpenCodeAutonomousChange,
    onOpenCodeMaxTurnsChange, onOpenCodeWorkingDirectoryChange,
  } = props;

  const reachablePeers = discoveryPeers.filter((peer) => peer.reachable);
  const activePeerValue = a2aTargetAgent && a2aTargetNamespace ? `${a2aTargetNamespace}/${a2aTargetAgent}` : "";
  const a2aMode = Boolean(a2aTargetAgent && a2aTargetNamespace);
  const specialistMode = specialistTeamConfigured;
  const hasAnySettings = runtimeKind === "langgraph" || runtimeKind === "goose" || runtimeKind === "opencode";

  if (!hasAnySettings) return null;

  // Count active configs for the badge
  const activeCount = (a2aMode ? 1 : 0) + (specialistMode ? 1 : 0) + (opencodeAutonomous ? 1 : 0);

  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 gap-1.5 rounded-full px-2.5 text-xs text-muted-foreground hover:text-foreground"
        >
          <Settings2 className="h-3.5 w-3.5" />
          Settings
          {activeCount > 0 && (
            <Badge variant="default" className="ml-0.5 px-1 py-0 text-[10px]">
              {activeCount}
            </Badge>
          )}
        </Button>
      </SheetTrigger>
      <SheetContent side="right" className="w-[min(28rem,100vw)] p-0">
        <SheetHeader className="border-b border-border/60 px-5 py-4">
          <SheetTitle className="text-sm font-semibold">
            Runtime settings
            <Badge variant="outline" className="ml-2 text-[10px]">{runtimeKind}</Badge>
          </SheetTitle>
        </SheetHeader>
        <ScrollArea className="h-[calc(100vh-4.5rem)]">
          <div className="space-y-6 px-5 py-5">
            {/* ── LangGraph: A2A + Specialist ── */}
            {runtimeKind === "langgraph" && (
              <>
                <DrawerSection title="Explicit A2A route" badge={`${reachablePeers.length} reachable`}>
                  {specialistMode && (
                    <p className="text-xs text-amber-400">Clear the specialist team to use single-hop A2A routing.</p>
                  )}
                  <div className="space-y-1.5">
                    <Label className="text-xs">Discoverable peer</Label>
                    <Select
                      disabled={specialistMode}
                      value={reachablePeers.some((p) => `${p.namespace}/${p.name}` === activePeerValue) ? activePeerValue : "__direct__"}
                      onValueChange={(v) => {
                        if (!v || v === "__direct__") { onA2ATargetNamespaceChange(""); onA2ATargetAgentChange(""); return; }
                        const idx = v.indexOf("/");
                        onA2ATargetNamespaceChange(v.slice(0, idx));
                        onA2ATargetAgentChange(v.slice(idx + 1));
                      }}
                    >
                      <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Direct reply from selected agent" /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="__direct__">Direct reply from selected agent</SelectItem>
                        {reachablePeers.map((peer) => {
                          const value = `${peer.namespace}/${peer.name}`;
                          return <SelectItem key={value} value={value}>{value} · {peer.runtime_kind ?? "runtime"} · {peer.model ?? "model"}</SelectItem>;
                        })}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="grid gap-2 sm:grid-cols-3">
                    <div className="space-y-1">
                      <Label className="text-[11px]">Target namespace</Label>
                      <Input className="h-7 text-xs" disabled={specialistMode} placeholder="team-b" value={a2aTargetNamespace} onChange={(e) => onA2ATargetNamespaceChange(e.target.value)} />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-[11px]">Target agent</Label>
                      <Input className="h-7 text-xs" disabled={specialistMode} placeholder="reviewer" value={a2aTargetAgent} onChange={(e) => onA2ATargetAgentChange(e.target.value)} />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-[11px]">Timeout (s)</Label>
                      <Input className="h-7 text-xs" disabled={specialistMode} type="number" min="1" placeholder="default" value={a2aTimeoutSeconds} onChange={(e) => onA2ATimeoutSecondsChange(e.target.value)} />
                    </div>
                  </div>
                  {discoveryLoading && <p className="text-[11px] text-muted-foreground">Loading discoverable peers...</p>}
                  {discoveryError && <p className="text-xs text-destructive">{discoveryError}</p>}
                </DrawerSection>

                <DrawerSection title="Specialist team" badge={`${specialistSubagents.length} member${specialistSubagents.length === 1 ? "" : "s"}`}>
                  {a2aMode && <p className="text-xs text-amber-400">Clear the explicit A2A route to coordinate a specialist team.</p>}
                  <div className="flex items-center gap-2">
                    <div className="space-y-1 flex-1">
                      <Label className="text-[11px]">Strategy</Label>
                      <Select disabled={a2aMode} value={subagentStrategy} onValueChange={(v) => onSubagentStrategyChange(v as "sequential" | "parallel")}>
                        <SelectTrigger className="h-7 text-xs"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="sequential">Sequential</SelectItem>
                          <SelectItem value="parallel">Parallel</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="flex gap-1.5 self-end">
                      <Button variant="outline" size="sm" className="h-7 text-xs" disabled={a2aMode} onClick={onAddSpecialistSubagent}>
                        <Plus className="mr-1 h-3 w-3" /> Add
                      </Button>
                      <Button variant="ghost" size="sm" className="h-7 text-xs" disabled={a2aMode || specialistSubagents.length === 0} onClick={onClearSpecialistTeam}>Clear</Button>
                    </div>
                  </div>
                  {specialistSubagents.length === 0 ? (
                    <p className="text-[11px] text-muted-foreground">Add specialists to coordinate planner, researcher, coder, or domain agents.</p>
                  ) : (
                    <div className="space-y-2">
                      {specialistSubagents.map((subagent, index) => (
                        <Card key={subagent.id} className="shadow-none">
                          <CardContent className="p-3 space-y-2">
                            <div className="flex items-center justify-between">
                              <span className="text-xs font-medium">Specialist {index + 1}</span>
                              <Button variant="ghost" size="icon" className="h-7 w-7 hover:bg-destructive/20 hover:text-destructive" disabled={a2aMode} onClick={() => onRemoveSpecialistSubagent(subagent.id)} aria-label="Remove specialist">
                                <X className="h-3.5 w-3.5" />
                              </Button>
                            </div>
                            <div className="grid gap-2 sm:grid-cols-2">
                              <div className="space-y-1"><Label className="text-[11px]">Namespace</Label><Input className="h-7 text-xs" disabled={a2aMode} placeholder="team-b" value={subagent.namespace} onChange={(e) => onUpdateSpecialistSubagent(subagent.id, { namespace: e.target.value })} /></div>
                              <div className="space-y-1"><Label className="text-[11px]">Agent</Label><Input className="h-7 text-xs" disabled={a2aMode} placeholder="analysis-agent" value={subagent.name} onChange={(e) => onUpdateSpecialistSubagent(subagent.id, { name: e.target.value })} /></div>
                              <div className="space-y-1"><Label className="text-[11px]">Role</Label><Input className="h-7 text-xs" disabled={a2aMode} placeholder="incident analyst" value={subagent.role} onChange={(e) => onUpdateSpecialistSubagent(subagent.id, { role: e.target.value })} /></div>
                              <div className="space-y-1"><Label className="text-[11px]">Timeout (s)</Label><Input className="h-7 text-xs" disabled={a2aMode} type="number" min="1" placeholder="default" value={subagent.timeoutSeconds} onChange={(e) => onUpdateSpecialistSubagent(subagent.id, { timeoutSeconds: e.target.value })} /></div>
                            </div>
                            <div className="space-y-1"><Label className="text-[11px]">Delegated task</Label><Textarea rows={2} className="text-xs" disabled={a2aMode} placeholder="Inspect the failing workflow and explain the root cause." value={subagent.task} onChange={(e) => onUpdateSpecialistSubagent(subagent.id, { task: e.target.value })} /></div>
                            <div className="grid gap-2 sm:grid-cols-2">
                              <div className="space-y-1"><Label className="text-[11px]">Shared files</Label><Textarea rows={2} className="text-xs font-mono" disabled={a2aMode} placeholder={"src/app.py | main logic\nnotes/incident.md | notes"} value={subagent.inputFilesText} onChange={(e) => onUpdateSpecialistSubagent(subagent.id, { inputFilesText: e.target.value })} /></div>
                              <div className="space-y-1"><Label className="text-[11px]">Result artifact path</Label><Input className="h-7 text-xs font-mono" disabled={a2aMode} placeholder="artifacts/analysis.md" value={subagent.resultFilePath} onChange={(e) => onUpdateSpecialistSubagent(subagent.id, { resultFilePath: e.target.value })} /></div>
                            </div>
                            <label className="flex items-center gap-1.5 cursor-pointer text-xs">
                              <input type="checkbox" checked={subagent.shareSandboxSession} disabled={a2aMode} onChange={(e) => onUpdateSpecialistSubagent(subagent.id, { shareSandboxSession: e.target.checked })} className="h-3.5 w-3.5 rounded border-input" />
                              Share sandbox session
                            </label>
                          </CardContent>
                        </Card>
                      ))}
                    </div>
                  )}
                </DrawerSection>
              </>
            )}

            {/* ── Goose controls ── */}
            {runtimeKind === "goose" && (
              <DrawerSection title="Goose run controls" badge="safe subset">
                <div className="grid gap-2 sm:grid-cols-2">
                  <div className="space-y-1"><Label className="text-[11px]">Max turns</Label><Input className="h-7 text-xs" type="number" min="1" placeholder="runtime default" value={gooseMaxTurns} onChange={(e) => onGooseMaxTurnsChange(e.target.value)} /></div>
                  <div className="space-y-1"><Label className="text-[11px]">Working directory</Label><Input className="h-7 text-xs font-mono" placeholder="workspace/subdir" value={gooseWorkingDirectory} onChange={(e) => onGooseWorkingDirectoryChange(e.target.value)} /></div>
                </div>
                <div className="space-y-1">
                  <Label className="text-[11px]">Agent system prompt (read-only)</Label>
                  <Textarea rows={3} readOnly className="text-xs opacity-70" value={gooseSystemPrompt} />
                </div>
                <p className="text-[11px] text-amber-400">Goose system overrides are locked. Edit the agent definition to change this prompt.</p>
              </DrawerSection>
            )}

            {/* ── OpenCode controls ── */}
            {runtimeKind === "opencode" && (
              <DrawerSection title="OpenCode run controls" badge="autonomous">
                <div className="grid gap-2 sm:grid-cols-2">
                  <div className="space-y-1">
                    <Label className="text-[11px]">Output format</Label>
                    <Select value={opencodeOutputFormat} onValueChange={onOpenCodeOutputFormatChange}>
                      <SelectTrigger className="h-7 text-xs"><SelectValue placeholder="text (default)" /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="text">text</SelectItem>
                        <SelectItem value="json">json</SelectItem>
                        <SelectItem value="stream-json">stream-json</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1"><Label className="text-[11px]">Max turns</Label><Input className="h-7 text-xs" type="number" min="1" placeholder="runtime default" value={opencodeMaxTurns} onChange={(e) => onOpenCodeMaxTurnsChange(e.target.value)} /></div>
                </div>
                <div className="grid gap-2 sm:grid-cols-2">
                  <div className="space-y-1"><Label className="text-[11px]">Working directory</Label><Input className="h-7 text-xs font-mono" placeholder="workspace/subdir" value={opencodeWorkingDirectory} onChange={(e) => onOpenCodeWorkingDirectoryChange(e.target.value)} /></div>
                  <div className="flex items-center gap-2 pt-4">
                    <label className="flex items-center gap-1.5 cursor-pointer text-xs">
                      <input type="checkbox" checked={opencodeAutonomous} onChange={(e) => onOpenCodeAutonomousChange(e.target.checked)} className="h-3.5 w-3.5 rounded border-input" />
                      Autonomous mode
                    </label>
                  </div>
                </div>
                <p className="text-[11px] text-amber-400">Autonomous mode enables multi-turn execution with context-overflow recovery and automatic agent selection.</p>
              </DrawerSection>
            )}
          </div>
        </ScrollArea>
      </SheetContent>
    </Sheet>
  );
});
