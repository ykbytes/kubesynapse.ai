import { useCallback, useMemo, useState } from "react";
import { Download, FolderOpen } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { FileExplorer } from "../FileExplorer";
import { WorkflowLogPanel } from "../WorkflowLogPanel";
import { RunHistoryPanel } from "../composer/RunHistoryPanel";
import { useConnection } from "@/contexts/ConnectionContext";
import {
  listAgentArtifacts,
  downloadAgentArtifact,
  downloadAgentArtifactZip,
  previewAgentArtifact,
  type WorkflowRunRecord,
} from "@/lib/api";
import type { WorkflowInfo } from "../../types";

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
    [token, namespace, resolvedActiveAgent]
  );

  const handlePreview = useCallback(
    async (path: string) => {
      if (!token || !resolvedActiveAgent) {
        throw new Error("Enter a gateway token before previewing files.");
      }
      return previewAgentArtifact(token, namespace ?? "default", resolvedActiveAgent, path);
    },
    [token, namespace, resolvedActiveAgent]
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
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        {dedupedAgents.length > 1 && (
          <div className="flex gap-1 flex-1 flex-wrap">
            {dedupedAgents.map((agent) => (
              <Button
                key={agent}
                size="sm"
                variant={agent === resolvedActiveAgent ? "secondary" : "ghost"}
                className="h-7 rounded-lg text-xs"
                onClick={() => setActiveAgent(agent)}
              >
                {agent}
              </Button>
            ))}
          </div>
        )}
        <Button
          size="sm"
          variant="outline"
          className="h-7 rounded-lg text-xs ml-auto"
          disabled={zipping || !resolvedActiveAgent}
          onClick={handleDownloadZip}
        >
          <Download className="h-3.5 w-3.5 mr-1.5" />
          {zipping ? "Downloading…" : "Download All (ZIP)"}
        </Button>
      </div>
      {resolvedActiveAgent && (
        <FileExplorer
          agentName={resolvedActiveAgent}
          onLoad={loadFiles}
          onDownload={handleDownload}
          onPreview={handlePreview}
          liveUpdatesEnabled={liveUpdatesEnabled}
        />
      )}
    </div>
  );
}

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
  const visibleAgents = useMemo(
    () => Array.from(new Set(activeRunAgents.filter(Boolean))),
    [activeRunAgents]
  );

  return (
    <div className="grid gap-6 2xl:grid-cols-[minmax(0,1.14fr)_minmax(24rem,0.86fr)] animate-fade-in">
      <RunHistoryPanel
        workflowName={workflow.name}
        collapsible={false}
        onSelectRun={setSelectedHistoryRun}
      />

      <div className="space-y-6">
        <WorkflowLogPanel workflow={workflow} selectedRun={selectedHistoryRun} />

        {visibleAgents.length > 0 && (
          <Card className="border-border/65 bg-background/75 shadow-sm backdrop-blur-sm">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-sm">
                <FolderOpen className="h-4 w-4" />
                Agent workspace files
              </CardTitle>
              <CardDescription className="text-xs">
                Browse files created during this workflow run.
              </CardDescription>
            </CardHeader>
            <CardContent className="p-4">
              <AgentFileBrowserTabs
                agents={visibleAgents}
                liveUpdatesEnabled={isActive}
              />
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
