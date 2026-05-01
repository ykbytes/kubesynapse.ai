import { useCallback, useMemo, useState } from "react";
import { ArrowUpRight, Download, FolderOpen, TerminalSquare } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { FileExplorer } from "../FileExplorer";
import { RunHistoryPanel, phaseIcon, phaseColor, phaseAccent, durationSeconds, formatDuration, formatTimestampFull } from "../composer/RunHistoryPanel";
import { useConnection } from "@/contexts/ConnectionContext";
import { useWorkspace } from "@/contexts/WorkspaceContext";
import {
  listAgentArtifacts,
  downloadAgentArtifact,
  downloadAgentArtifactZip,
  previewAgentArtifact,
  type WorkflowRunRecord,
} from "@/lib/api";
import type { WorkflowInfo } from "../../types";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ */
/*  Agent file browser (reused from original)                          */
/* ------------------------------------------------------------------ */

function AgentFileBrowserTabs({
  agents,
  liveUpdatesEnabled,
}: {
  agents: string[];
  liveUpdatesEnabled: boolean;
}) {
  const { token, namespace } = useConnection();
  const [activeAgent, setActiveAgent] = useState(agents[0] ?? "");
  const [zipping, setZipping] = useState(false);
  const dedupedAgents = useMemo(() => Array.from(new Set(agents.filter(Boolean))), [agents]);

  const resolvedActiveAgent = dedupedAgents.includes(activeAgent)
    ? activeAgent
    : (dedupedAgents[0] ?? "");

  const loadFiles = useCallback(async () => {
    if (!token || !resolvedActiveAgent) return { files: [], truncated: false, roots: [] };
    return listAgentArtifacts(token, namespace ?? "default", resolvedActiveAgent);
  }, [token, namespace, resolvedActiveAgent]);

  const handleDownload = useCallback(
    async (path: string, filename?: string) => {
      if (!token || !resolvedActiveAgent) return;
      await downloadAgentArtifact(token, namespace ?? "default", resolvedActiveAgent, path, filename);
    },
    [token, namespace, resolvedActiveAgent],
  );

  const handlePreview = useCallback(
    async (path: string) => {
      if (!token || !resolvedActiveAgent) {
        throw new Error("Enter a gateway token before previewing files.");
      }
      return previewAgentArtifact(token, namespace ?? "default", resolvedActiveAgent, path);
    },
    [token, namespace, resolvedActiveAgent],
  );

  const handleDownloadZip = useCallback(async () => {
    if (!token || !resolvedActiveAgent) return;
    setZipping(true);
    try {
      await downloadAgentArtifactZip(token, namespace ?? "default", resolvedActiveAgent);
    } finally {
      setZipping(false);
    }
  }, [token, namespace, resolvedActiveAgent]);

  return (
    <div className="flex h-full flex-col gap-3">
      {/* Header */}
      <div className="flex items-center gap-2">
        <FolderOpen className="h-4 w-4 text-primary" />
        <span className="text-xs font-semibold text-foreground">Workspace Files</span>
        {dedupedAgents.length > 1 && (
          <div className="flex gap-1 flex-wrap">
            {dedupedAgents.map((agent) => (
              <Button
                key={agent}
                size="sm"
                variant={agent === resolvedActiveAgent ? "secondary" : "ghost"}
                className="h-6 rounded-lg text-[10px] px-2"
                onClick={() => setActiveAgent(agent)}
              >
                {agent}
              </Button>
            ))}
          </div>
        )}
        <Button
          size="sm"
          variant="ghost"
          className="h-7 rounded-lg text-[10px] ml-auto"
          disabled={zipping || !resolvedActiveAgent}
          onClick={handleDownloadZip}
        >
          <Download className="h-3 w-3 mr-1" />
          {zipping ? "Downloading\u2026" : "ZIP"}
        </Button>
      </div>
      {/* File explorer fills remaining space */}
      {resolvedActiveAgent && (
        <div className="flex-1 min-h-0">
          <FileExplorer
            agentName={resolvedActiveAgent}
            onLoad={loadFiles}
            onDownload={handleDownload}
            onPreview={handlePreview}
            liveUpdatesEnabled={liveUpdatesEnabled}
          />
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main view                                                          */
/* ------------------------------------------------------------------ */

interface WorkflowHistoryViewProps {
  workflow: WorkflowInfo;
  selectedHistoryRun: WorkflowRunRecord | null;
  setSelectedHistoryRun: (run: WorkflowRunRecord | null) => void;
  activeRunAgents: string[];
  isActive: boolean;
}

export function WorkflowHistoryView({
  workflow,
  selectedHistoryRun,
  setSelectedHistoryRun,
  activeRunAgents,
  isActive,
}: WorkflowHistoryViewProps) {
  const { openObservatoryForWorkflowRun } = useWorkspace();

  const visibleAgents = useMemo(
    () => Array.from(new Set(activeRunAgents.filter(Boolean))),
    [activeRunAgents],
  );

  const run = selectedHistoryRun;
  const dur = durationSeconds(run);
  const handleOpenObservatory = useCallback(() => {
    openObservatoryForWorkflowRun(workflow.name, run?.run_id ?? null);
  }, [openObservatoryForWorkflowRun, run?.run_id, workflow.name]);

  return (
    <div className="grid grid-cols-[minmax(240px,280px)_1fr] gap-4 h-[calc(100vh-11rem)] animate-fade-in">
      {/* -------- Left: Run list sidebar -------- */}
      <RunHistoryPanel
        workflowName={workflow.name}
        collapsible={false}
        onSelectRun={setSelectedHistoryRun}
      />

      {/* -------- Right: Run header + tabbed content -------- */}
      <div className="flex flex-col gap-3 min-h-0">
        {/* Run details header */}
        {run ? (
          <div className={cn(
            "rounded-xl border border-border/60 bg-background/70 px-4 py-3 border-l-[3px]",
            phaseAccent(run.phase),
          )}>
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  {phaseIcon(run.phase)}
                  <Badge variant="outline" className={cn("h-5 border px-2 text-[10px] capitalize", phaseColor(run.phase))}>
                    {run.phase}
                  </Badge>
                  {run.run_id && (
                    <span className="max-w-[20rem] truncate font-mono text-[11px] text-muted-foreground">{run.run_id}</span>
                  )}
                  <span className="text-xs text-muted-foreground">
                    {run.completed_steps ?? 0}/{run.total_steps ?? "?"} steps
                  </span>
                  {dur != null && (
                    <span className="text-xs font-medium text-foreground">{formatDuration(dur)}</span>
                  )}
                  {run.archived_log_available && (
                    <Badge variant="outline" className="border-emerald-500/20 bg-emerald-500/10 text-[10px] text-emerald-600 dark:text-emerald-300">
                      archived
                    </Badge>
                  )}
                </div>
                <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
                  <span>Created {formatTimestampFull(run.created_at)}</span>
                  <span>Started {formatTimestampFull(run.started_at)}</span>
                  {run.completed_at && <span>Completed {formatTimestampFull(run.completed_at)}</span>}
                  {run.triggered_by && <span>Triggered by {run.triggered_by}</span>}
                </div>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-8 shrink-0 rounded-lg text-xs"
                onClick={handleOpenObservatory}
              >
                <ArrowUpRight className="mr-1.5 h-3.5 w-3.5" />
                Open in Observatory
              </Button>
            </div>
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-border/50 bg-background/50 px-4 py-4 text-center text-xs text-muted-foreground">
            Run the workflow to see execution history here.
          </div>
        )}

        <div className="rounded-xl border border-border/60 bg-card/40 p-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                <TerminalSquare className="h-3.5 w-3.5 text-primary" />
                Deep trace analysis lives in Observatory
              </div>
              <p className="mt-1 text-sm text-foreground">
                Use the workflow page for recent runs and workspace files. Open Observatory for trace logs,
                replay, step timing, LLM/tool call inspection, and run-to-run comparison.
              </p>
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-8 shrink-0 rounded-lg text-xs"
              onClick={handleOpenObservatory}
            >
              <ArrowUpRight className="mr-1.5 h-3.5 w-3.5" />
              Open Observatory
            </Button>
          </div>
        </div>

        <div className="flex-1 min-h-0">
          {visibleAgents.length > 0 ? (
            <AgentFileBrowserTabs agents={visibleAgents} liveUpdatesEnabled={isActive} />
          ) : (
            <div className="flex h-full items-center justify-center rounded-xl border border-dashed border-border/50 bg-background/50 px-4 py-4 text-center text-xs text-muted-foreground">
              No workflow workspace files are available yet.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
