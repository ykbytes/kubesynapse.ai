import { AlertTriangle, CheckCircle, Loader2, XCircle, Play, Square, RefreshCw, Terminal } from "lucide-react";
import { useEffect, useRef } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ActivityTimeline } from "./ActivityTimeline";
import type {
  AgentDetail,
  AgentDiscoveryPeer,
  GatewayHealth,
  InvocationSummary,
  UiActivity,
} from "@/types";

// ── Agent Inspector (main agents view) ──

interface AgentInspectorDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  health: GatewayHealth | null;
  gatewayError: string;
  workspaceError: string;
  selectedAgentName: string;
  selectedAgentDetail: AgentDetail | null;
  discoverablePeers: AgentDiscoveryPeer[];
  discoveryLoading: boolean;
  discoveryError: string;
  namespace: string;
  logs: string;
  logsLoading: boolean;
  logsStreaming: boolean;
  activity: UiActivity[];
  summary: InvocationSummary | null;
  approvalReason: string;
  approvalBusy: boolean;
  onApprovalReasonChange: (value: string) => void;
  onApprove: () => void;
  onDeny: () => void;
  onLoadLogs: () => void;
  onStreamLogs: () => void;
  onStopLogStream: () => void;
}

export function AgentInspectorDrawer({
  open,
  onOpenChange,
  health,
  gatewayError,
  workspaceError,
  selectedAgentName,
  selectedAgentDetail,
  discoverablePeers,
  discoveryLoading,
  discoveryError,
  namespace,
  logs,
  logsLoading,
  logsStreaming,
  activity,
  summary,
  approvalReason,
  approvalBusy,
  onApprovalReasonChange,
  onApprove,
  onDeny,
  onLoadLogs,
  onStreamLogs,
  onStopLogStream,
}: AgentInspectorDrawerProps) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-[480px] p-0 flex flex-col">
        <SheetHeader className="px-4 py-3 border-b border-border">
          <SheetTitle className="text-base">
            {selectedAgentName ? `Inspector — ${selectedAgentName}` : "Inspector"}
          </SheetTitle>
        </SheetHeader>

        {/* Approval banner */}
        {summary?.approvalName && (
          <div className="mx-4 mt-3 rounded-md border border-amber-500/30 bg-amber-500/10 p-3">
            <div className="flex items-center gap-2 text-sm font-medium text-amber-400">
              <AlertTriangle className="h-4 w-4" />
              Approval Required: {summary.approvalName}
            </div>
            <div className="mt-2 flex gap-2">
              <Input
                placeholder="Reason (optional)"
                value={approvalReason}
                onChange={(e) => onApprovalReasonChange(e.target.value)}
                className="h-9 text-xs"
                aria-label="Approval reason"
              />
              <Button size="sm" className="h-8" onClick={onApprove} disabled={approvalBusy}>
                Approve
              </Button>
              <Button size="sm" variant="destructive" className="h-8" onClick={onDeny} disabled={approvalBusy}>
                Deny
              </Button>
            </div>
          </div>
        )}

        <Tabs defaultValue="overview" className="flex flex-1 flex-col overflow-hidden">
          <TabsList className="mx-4 mt-2 w-auto">
            <TabsTrigger value="overview" aria-label="Agent overview">Overview</TabsTrigger>
            <TabsTrigger value="activity" aria-label="Activity log">Activity</TabsTrigger>
            <TabsTrigger value="logs" aria-label="Pod logs">Logs</TabsTrigger>
            <TabsTrigger value="raw" aria-label="Raw JSON">Raw</TabsTrigger>
          </TabsList>

          {/* Overview Tab */}
          <TabsContent value="overview" className="flex-1 overflow-hidden">
            <ScrollArea className="h-full">
              <div className="space-y-4 p-4">
                {/* Gateway */}
                <Section title="Gateway">
                  <KV label="Status" value={gatewayError ? "offline" : health?.status ?? "loading"} />
                  <KV label="Auth" value={health?.auth_mode ?? "unknown"} />
                  <KV label="NATS" value={health?.nats_url ?? "—"} />
                  <KV label="Qdrant" value={health?.qdrant_url ?? "—"} />
                </Section>

                {(gatewayError || workspaceError) && (
                  <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-xs text-destructive-foreground">
                    {gatewayError || workspaceError}
                  </div>
                )}

                {/* Agent config */}
                {selectedAgentDetail && (
                  <Section title="Agent Config">
                    <KV label="Model" value={selectedAgentDetail.model} />
                    <KV label="Runtime" value={selectedAgentDetail.runtime_kind} />
                    <KV label="Status" value={selectedAgentDetail.status} />
                    <KV label="Policy" value={selectedAgentDetail.policy_ref ?? "none"} />
                    <KV label="Storage" value={selectedAgentDetail.storage_size ?? "default"} />
                    <KV label="gVisor" value={selectedAgentDetail.enable_gvisor ? "enabled" : "disabled"} />
                    <KV label="Namespace" value={namespace} />
                    {selectedAgentDetail.created_at && <KV label="Created" value={selectedAgentDetail.created_at} />}
                  </Section>
                )}

                {/* MCP Servers */}
                {selectedAgentDetail && selectedAgentDetail.mcp_servers.length > 0 && (
                  <Section title="MCP Servers">
                    <div className="flex flex-wrap gap-1">
                      {selectedAgentDetail.mcp_servers.map((s) => (
                        <Badge key={s} variant="secondary" className="text-xs">{s}</Badge>
                      ))}
                    </div>
                  </Section>
                )}

                {/* Skills */}
                {selectedAgentDetail && selectedAgentDetail.skill_summaries.length > 0 && (
                  <Section title={`Skills (${selectedAgentDetail.skill_summaries.length})`}>
                    {selectedAgentDetail.skill_summaries.map((skill) => (
                      <div key={skill.path} className="rounded-md border border-border p-2 text-xs space-y-1">
                        <div className="flex items-center gap-2">
                          <span className="font-medium">{skill.name}</span>
                          {skill.valid ? (
                            <CheckCircle className="h-3 w-3 text-emerald-500" />
                          ) : (
                            <XCircle className="h-3 w-3 text-red-500" />
                          )}
                        </div>
                        {skill.description && <p className="text-muted-foreground">{skill.description}</p>}
                      </div>
                    ))}
                  </Section>
                )}

                {/* Discoverable Peers */}
                <Section title="Discoverable Peers">
                  {discoveryLoading && <p className="text-xs text-muted-foreground">Discovering...</p>}
                  {discoveryError && <p className="text-xs text-destructive">{discoveryError}</p>}
                  {!discoveryLoading && discoverablePeers.length === 0 && !discoveryError && (
                    <p className="text-xs text-muted-foreground">No peers discovered.</p>
                  )}
                  {discoverablePeers.map((peer) => (
                    <div key={`${peer.namespace}/${peer.name}`} className="flex items-center gap-2 text-xs">
                      <span className={`h-1.5 w-1.5 rounded-full ${peer.reachable ? "bg-emerald-500" : "bg-red-500"}`} />
                      <span className="font-mono">{peer.namespace}/{peer.name}</span>
                      {peer.model && <span className="text-muted-foreground">({peer.model})</span>}
                    </div>
                  ))}
                </Section>

                {/* Invocation Summary */}
                {summary && (
                  <Section title="Last Invocation">
                    <KV label="Thread" value={summary.threadId || "—"} />
                    <KV label="Status" value={summary.status} />
                    {summary.policyName && <KV label="Policy" value={summary.policyName} />}
                    {summary.toolName && <KV label="Tool" value={summary.toolName} />}
                    {summary.approvalName && <KV label="Approval" value={summary.approvalName} />}
                    {summary.warnings.length > 0 && (
                      <div className="text-xs text-amber-400">
                        {summary.warnings.map((w, i) => (
                          <p key={i}>{w}</p>
                        ))}
                      </div>
                    )}
                  </Section>
                )}
              </div>
            </ScrollArea>
          </TabsContent>

          {/* Activity Tab */}
          <TabsContent value="activity" className="flex-1 overflow-hidden">
            <div className="flex flex-col h-full p-4">
              {activity.length === 0 ? (
                <p className="py-8 text-center text-xs text-muted-foreground">
                  No activity events yet. Send a chat message to see events.
                </p>
              ) : (
                <ActivityTimeline
                  activity={activity}
                  showFilters={true}
                  showSummary={true}
                  autoScroll={false}
                  heightClass="flex-1"
                  className="flex-1 flex flex-col"
                />
              )}
            </div>
          </TabsContent>

          {/* Logs Tab */}
          <TabsContent value="logs" className="flex-1 overflow-hidden">
            <LogsPanel
              logs={logs}
              logsLoading={logsLoading}
              logsStreaming={logsStreaming}
              selectedAgentName={selectedAgentName}
              onLoadLogs={onLoadLogs}
              onStreamLogs={onStreamLogs}
              onStopLogStream={onStopLogStream}
            />
          </TabsContent>

          {/* Raw Tab */}
          <TabsContent value="raw" className="flex-1 overflow-hidden">
            <ScrollArea className="h-full">
              <div className="space-y-4 p-4">
                {selectedAgentDetail && (
                  <Section title="Agent Detail (JSON)">
                    <pre className="overflow-x-auto text-[11px] font-mono text-muted-foreground whitespace-pre-wrap">
                      {JSON.stringify(selectedAgentDetail, null, 2)}
                    </pre>
                  </Section>
                )}
                {summary && (
                  <Section title="Invocation Summary (JSON)">
                    <pre className="overflow-x-auto text-[11px] font-mono text-muted-foreground whitespace-pre-wrap">
                      {JSON.stringify(summary, null, 2)}
                    </pre>
                  </Section>
                )}
              </div>
            </ScrollArea>
          </TabsContent>
        </Tabs>
      </SheetContent>
    </Sheet>
  );
}

// ── Resource Inspector (workflows / evals) ──

interface ResourceInspectorDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  selectedName: string;
  status: string;
  summary?: Record<string, unknown> | null;
  spec: Record<string, unknown> | null;
  details: Record<string, unknown> | null;
  emptyMessage: string;
  pendingApprovalName?: string;
  approvalReason: string;
  approvalBusy: boolean;
  onApprovalReasonChange: (value: string) => void;
  onApprove: () => void;
  onDeny: () => void;
}

export function ResourceInspectorDrawer({
  open,
  onOpenChange,
  title,
  selectedName,
  status,
  summary,
  spec,
  details,
  emptyMessage,
  pendingApprovalName,
  approvalReason,
  approvalBusy,
  onApprovalReasonChange,
  onApprove,
  onDeny,
}: ResourceInspectorDrawerProps) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-[480px] p-0 flex flex-col">
        <SheetHeader className="px-4 py-3 border-b border-border">
          <SheetTitle className="text-base">{title}</SheetTitle>
        </SheetHeader>

        {/* Approval banner */}
        {pendingApprovalName && (
          <div className="mx-4 mt-3 rounded-md border border-amber-500/30 bg-amber-500/10 p-3">
            <div className="flex items-center gap-2 text-sm font-medium text-amber-400">
              <AlertTriangle className="h-4 w-4" />
              Approval: {pendingApprovalName}
            </div>
            <div className="mt-2 flex gap-2">
              <Input
                placeholder="Reason (optional)"
                value={approvalReason}
                onChange={(e) => onApprovalReasonChange(e.target.value)}
                className="h-9 text-xs"
                aria-label="Approval reason"
              />
              <Button size="sm" className="h-8" onClick={onApprove} disabled={approvalBusy}>Approve</Button>
              <Button size="sm" variant="destructive" className="h-8" onClick={onDeny} disabled={approvalBusy}>Deny</Button>
            </div>
          </div>
        )}

        <ScrollArea className="flex-1">
          <div className="space-y-4 p-4">
            {!selectedName ? (
              <p className="py-8 text-center text-sm text-muted-foreground">{emptyMessage}</p>
            ) : (
              <>
                <Section title="Overview">
                  <KV label="Name" value={selectedName} />
                  <KV label="Status" value={status} />
                </Section>

                {summary && (
                  <Section title="Summary">
                    <pre className="overflow-x-auto text-[11px] font-mono text-muted-foreground whitespace-pre-wrap">
                      {JSON.stringify(summary, null, 2)}
                    </pre>
                  </Section>
                )}

                {spec && (
                  <Section title="Spec">
                    <pre className="overflow-x-auto text-[11px] font-mono text-muted-foreground whitespace-pre-wrap">
                      {JSON.stringify(spec, null, 2)}
                    </pre>
                  </Section>
                )}

                {details && (
                  <Section title="Status Details">
                    <pre className="overflow-x-auto text-[11px] font-mono text-muted-foreground whitespace-pre-wrap">
                      {JSON.stringify(details, null, 2)}
                    </pre>
                  </Section>
                )}
              </>
            )}
          </div>
        </ScrollArea>
      </SheetContent>
    </Sheet>
  );
}

// ── Shared sub-components ──

// ── Log Viewer Panel (extracted for clarity) ──

interface LogsPanelProps {
  logs: string;
  logsLoading: boolean;
  logsStreaming: boolean;
  selectedAgentName: string;
  onLoadLogs: () => void;
  onStreamLogs: () => void;
  onStopLogStream: () => void;
}

function LogsPanel({
  logs,
  logsLoading,
  logsStreaming,
  selectedAgentName,
  onLoadLogs,
  onStreamLogs,
  onStopLogStream,
}: LogsPanelProps) {
  const logEndRef = useRef<HTMLDivElement>(null);
  const autoScrollRef = useRef(true);

  // Auto-scroll to bottom when streaming and new content arrives
  useEffect(() => {
    if (logsStreaming && autoScrollRef.current && logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs, logsStreaming]);

  const lineCount = logs ? logs.split("\n").filter(Boolean).length : 0;

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 border-b border-border px-4 py-2 flex-wrap">
        {logsStreaming ? (
          <Button size="sm" variant="destructive" className="h-7 text-xs gap-1" onClick={onStopLogStream}>
            <Square className="h-3 w-3" /> Stop
          </Button>
        ) : (
          <>
            <Button size="sm" variant="outline" className="h-7 text-xs gap-1" onClick={onStreamLogs} disabled={logsLoading || !selectedAgentName} title="Stream live logs from the agent pod">
              <Play className="h-3 w-3" /> Stream
            </Button>
            <Button size="sm" variant="outline" className="h-7 text-xs gap-1" onClick={onLoadLogs} disabled={logsLoading || logsStreaming || !selectedAgentName} title="Fetch recent log snapshot (500 lines)">
              {logsLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
              {logsLoading ? "Loading…" : "Snapshot"}
            </Button>
          </>
        )}

        {logsStreaming && (
          <span className="flex items-center gap-1.5 text-[10px] text-green-500">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500" />
            </span>
            Live
          </span>
        )}

        {selectedAgentName && (
          <span className="text-[10px] text-muted-foreground ml-auto">
            {selectedAgentName} · {lineCount} lines
          </span>
        )}
      </div>

      <div className="flex-1 overflow-auto bg-black/5 dark:bg-black/20"
        aria-label="Log output"
        role="log"
        onScroll={(e) => {
          const el = e.currentTarget;
          const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
          autoScrollRef.current = atBottom;
        }}
      >
        {logs ? (
          <pre className="p-4 text-[11px] leading-relaxed font-mono text-muted-foreground whitespace-pre-wrap break-all select-text">
            {logs}
            <div ref={logEndRef} />
          </pre>
        ) : (
          <div className="flex flex-col items-center justify-center h-full gap-2 py-12">
            <Terminal className="h-8 w-8 text-muted-foreground/30" />
            <p className="text-xs text-muted-foreground text-center max-w-[200px]">
              Click <strong>Stream</strong> to tail live logs or <strong>Snapshot</strong> to fetch recent output.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{title}</h4>
      <Separator />
      <div className="space-y-1.5">{children}</div>
    </div>
  );
}

function KV({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 text-xs">
      <span className="text-muted-foreground shrink-0">{label}</span>
      <span className="truncate font-medium text-foreground text-right">{value}</span>
    </div>
  );
}
