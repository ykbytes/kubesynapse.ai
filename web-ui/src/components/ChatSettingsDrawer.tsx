import { memo, useMemo } from "react";
import { Settings2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { FACTORY_MODE_OPTIONS, factoryModeLabel } from "@/lib/factoryModes";
import { deriveAgentVisualSignals, type AgentSignalSource } from "../lib/agentSignals";
import { cn } from "../lib/utils";
import type { AgentDiscoveryPeer, FactoryMode, RuntimeKind } from "../types";

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
  signalSource?: AgentSignalSource;
  /* A2A routing */
  a2aTargetAgent: string;
  a2aTargetNamespace: string;
  a2aTimeoutSeconds: string;
  onA2ATargetAgentChange: (value: string) => void;
  onA2ATargetNamespaceChange: (value: string) => void;
  onA2ATimeoutSecondsChange: (value: string) => void;
  /* Discovery */
  discoveryPeers: AgentDiscoveryPeer[];
  discoveryLoading: boolean;
  discoveryError: string;
  /* OpenCode */
  opencodeOutputFormat: string;
  opencodeAutonomous: boolean;
  opencodeMaxTurns: string;
  opencodeWorkingDirectory: string;
  showFactoryMode?: boolean;
  factoryMode?: FactoryMode;
  onOpenCodeOutputFormatChange: (value: string) => void;
  onOpenCodeAutonomousChange: (value: boolean) => void;
  onOpenCodeMaxTurnsChange: (value: string) => void;
  onOpenCodeWorkingDirectoryChange: (value: string) => void;
  onFactoryModeChange?: (value: FactoryMode) => void;
}

export const ChatSettingsDrawer = memo(function ChatSettingsDrawer(props: ChatSettingsDrawerProps) {
  const {
    runtimeKind, signalSource,
    a2aTargetAgent, a2aTargetNamespace, a2aTimeoutSeconds,
    onA2ATargetAgentChange, onA2ATargetNamespaceChange, onA2ATimeoutSecondsChange,
    discoveryPeers, discoveryLoading, discoveryError,
    opencodeOutputFormat, opencodeAutonomous, opencodeMaxTurns, opencodeWorkingDirectory,
    showFactoryMode, factoryMode,
    onOpenCodeOutputFormatChange, onOpenCodeAutonomousChange,
    onOpenCodeMaxTurnsChange, onOpenCodeWorkingDirectoryChange,
    onFactoryModeChange,
  } = props;

  const reachablePeers = discoveryPeers.filter((peer) => peer.reachable);
  const activePeerValue = a2aTargetAgent && a2aTargetNamespace ? `${a2aTargetNamespace}/${a2aTargetAgent}` : "";
  const a2aMode = Boolean(a2aTargetAgent && a2aTargetNamespace);
  const hasAnySettings = runtimeKind === "opencode";
  const agentSignals = deriveAgentVisualSignals(signalSource ?? { runtime_kind: runtimeKind });
  const RuntimeIcon = agentSignals.runtime.icon;
  const AccessIcon = agentSignals.access.icon;
  const peerSignalsByKey = useMemo(
    () => new Map(discoveryPeers.map((peer) => [`${peer.namespace}/${peer.name}`, deriveAgentVisualSignals({ runtime_kind: peer.runtime_kind })])),
    [discoveryPeers],
  );

  if (!hasAnySettings) return null;

  // Count active configs for the badge
  const activeCount = (a2aMode ? 1 : 0) + (opencodeAutonomous ? 1 : 0);

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
          <SheetTitle className="text-sm font-semibold">Runtime settings</SheetTitle>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px]", agentSignals.runtime.tone)}>
              <RuntimeIcon className="h-3 w-3" />
              {agentSignals.runtime.shortLabel}
            </span>
            <span className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px]", agentSignals.access.tone)}>
              <AccessIcon className="h-3 w-3" />
              {agentSignals.access.label}
            </span>
            {agentSignals.capabilities.slice(0, 3).map((capability) => {
              const CapabilityIcon = capability.icon;
              return (
                <span key={capability.id} className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px]", capability.tone)}>
                  <CapabilityIcon className="h-3 w-3" />
                  {capability.shortLabel}
                </span>
              );
            })}
          </div>
        </SheetHeader>
        <ScrollArea className="h-[calc(100vh-4.5rem)]">
          <div className="space-y-6 px-5 py-5">
            {/* ── A2A routing ── */}
            {runtimeKind === "opencode" && (
              <>
                <DrawerSection title="Explicit A2A route" badge={`${reachablePeers.length} reachable`}>
                  <div className="space-y-1.5">
                    <Label className="text-xs">Discoverable peer</Label>
                    <Select
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
                          const peerSignals = peerSignalsByKey.get(value) ?? deriveAgentVisualSignals({ runtime_kind: peer.runtime_kind });
                          const PeerRuntimeIcon = peerSignals.runtime.icon;
                          return (
                            <SelectItem key={value} value={value}>
                              <div className="flex items-center gap-2 text-xs">
                                <span className="font-mono">{value}</span>
                                <span className={cn("inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10px]", peerSignals.runtime.tone)}>
                                  <PeerRuntimeIcon className="h-3 w-3" />
                                  {peerSignals.runtime.shortLabel}
                                </span>
                                {peer.model && <span className="text-[10px] text-muted-foreground">{peer.model}</span>}
                              </div>
                            </SelectItem>
                          );
                        })}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="grid gap-2 sm:grid-cols-3">
                    <div className="space-y-1">
                      <Label className="text-[11px]">Target namespace</Label>
                      <Input className="h-7 text-xs" placeholder="team-b" value={a2aTargetNamespace} onChange={(e) => onA2ATargetNamespaceChange(e.target.value)} />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-[11px]">Target agent</Label>
                      <Input className="h-7 text-xs" placeholder="reviewer" value={a2aTargetAgent} onChange={(e) => onA2ATargetAgentChange(e.target.value)} />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-[11px]">Timeout (s)</Label>
                      <Input className="h-7 text-xs" type="number" min="1" placeholder="default" value={a2aTimeoutSeconds} onChange={(e) => onA2ATimeoutSecondsChange(e.target.value)} />
                    </div>
                  </div>
                  {discoveryLoading && <p className="text-[11px] text-muted-foreground">Loading discoverable peers...</p>}
                  {discoveryError && <p className="text-xs text-destructive">{discoveryError}</p>}
                </DrawerSection>

                <p className="-mt-4 text-[11px] text-muted-foreground">
                  OpenCode can send explicit single-hop A2A requests to any reachable peer.
                </p>
              </>
            )}

            {/* ── OpenCode controls ── */}
            {runtimeKind === "opencode" && (
              <>
                {showFactoryMode && factoryMode && onFactoryModeChange && (
                  <DrawerSection title="Factory operating mode" badge={factoryModeLabel(factoryMode)}>
                    <div className="space-y-1">
                      <Label className="text-[11px]">Bundle posture</Label>
                      <Select value={factoryMode} onValueChange={(value) => onFactoryModeChange(value as FactoryMode)}>
                        <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Select a factory mode" /></SelectTrigger>
                        <SelectContent>
                          {FACTORY_MODE_OPTIONS.map((option) => (
                            <SelectItem key={option.value} value={option.value}>
                              <div className="flex flex-col gap-0.5 py-0.5 text-left">
                                <span className="text-xs font-medium">{option.label}</span>
                                <span className="text-[10px] text-muted-foreground">{option.description}</span>
                              </div>
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <p className="text-[11px] text-muted-foreground">This changes the factory authoring posture. Runtime controls below still apply separately.</p>
                  </DrawerSection>
                )}

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
              </>
            )}
          </div>
        </ScrollArea>
      </SheetContent>
    </Sheet>
  );
});
