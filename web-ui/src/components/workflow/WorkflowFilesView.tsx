import { useCallback, useMemo, useState } from "react";
import { Download, FolderOpen } from "lucide-react";
import { Button } from "@/components/ui/button";
import { FileExplorer } from "../shared/FileExplorer";
import { useConnection } from "@/contexts/ConnectionContext";
import {
  downloadAgentArtifact,
  downloadAgentArtifactZip,
  listAgentArtifacts,
  previewAgentArtifact,
} from "@/lib/api";

interface WorkflowFilesViewProps {
  agents: string[];
  liveUpdatesEnabled: boolean;
}

export function WorkflowFilesView({ agents, liveUpdatesEnabled }: WorkflowFilesViewProps) {
  const { token, namespace } = useConnection();
  const dedupedAgents = useMemo(() => Array.from(new Set(agents.filter(Boolean))), [agents]);
  const [activeAgent, setActiveAgent] = useState(dedupedAgents[0] ?? "");
  const [zipping, setZipping] = useState(false);

  const resolvedActiveAgent = dedupedAgents.includes(activeAgent)
    ? activeAgent
    : (dedupedAgents[0] ?? "");

  const loadFiles = useCallback(async () => {
    if (!token || !resolvedActiveAgent) return { files: [], truncated: false, roots: [] };
    return listAgentArtifacts(token, namespace ?? "default", resolvedActiveAgent);
  }, [namespace, resolvedActiveAgent, token]);

  const handleDownload = useCallback(
    async (path: string, filename?: string) => {
      if (!token || !resolvedActiveAgent) return;
      await downloadAgentArtifact(token, namespace ?? "default", resolvedActiveAgent, path, filename);
    },
    [namespace, resolvedActiveAgent, token],
  );

  const handlePreview = useCallback(
    async (path: string) => {
      if (!token || !resolvedActiveAgent) {
        throw new Error("Enter a gateway token before previewing files.");
      }
      return previewAgentArtifact(token, namespace ?? "default", resolvedActiveAgent, path);
    },
    [namespace, resolvedActiveAgent, token],
  );

  const handleDownloadZip = useCallback(async () => {
    if (!token || !resolvedActiveAgent) return;
    setZipping(true);
    try {
      await downloadAgentArtifactZip(token, namespace ?? "default", resolvedActiveAgent);
    } finally {
      setZipping(false);
    }
  }, [namespace, resolvedActiveAgent, token]);

  if (dedupedAgents.length === 0) {
    return (
      <div className="flex min-h-[28rem] items-center justify-center rounded-lg border border-dashed border-border/60 bg-card/45 p-8 text-center">
        <div>
          <FolderOpen className="mx-auto h-8 w-8 text-muted-foreground/60" />
          <h3 className="mt-3 text-sm font-semibold text-foreground">No runtime files yet</h3>
          <p className="mt-1 max-w-md text-sm text-muted-foreground">
            Files will appear here after a workflow run produces agent workspace artifacts.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-[34rem] flex-col overflow-hidden rounded-lg border border-border/70 bg-card/60">
      <div className="flex flex-wrap items-center gap-2 border-b border-border/60 px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <FolderOpen className="h-4 w-4 text-primary" />
          <div>
            <h2 className="text-sm font-semibold text-foreground">Files</h2>
            <p className="text-xs text-muted-foreground">Browse artifacts by workflow agent.</p>
          </div>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {dedupedAgents.map((agent) => (
            <Button
              key={agent}
              type="button"
              size="sm"
              variant={agent === resolvedActiveAgent ? "secondary" : "ghost"}
              className="h-8 rounded-md px-3 text-xs"
              onClick={() => setActiveAgent(agent)}
            >
              {agent}
            </Button>
          ))}
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8 rounded-md text-xs"
            disabled={zipping || !resolvedActiveAgent}
            onClick={handleDownloadZip}
          >
            <Download className="mr-1.5 h-3.5 w-3.5" />
            {zipping ? "Downloading..." : "ZIP"}
          </Button>
        </div>
      </div>
      <div className="min-h-0 flex-1">
        <FileExplorer
          agentName={resolvedActiveAgent}
          onLoad={loadFiles}
          onDownload={handleDownload}
          onDownloadAll={handleDownloadZip}
          onPreview={handlePreview}
          liveUpdatesEnabled={liveUpdatesEnabled}
        />
      </div>
    </div>
  );
}
