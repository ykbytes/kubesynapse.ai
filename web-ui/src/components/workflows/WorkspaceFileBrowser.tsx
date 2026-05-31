import { useCallback, useEffect, useState } from "react";
import { Archive, ChevronRight, Maximize2, MessageSquare, Minimize2, Package, RefreshCw } from "lucide-react";

import { FileExplorer } from "@/components/shared/FileExplorer";
import { Button } from "@/components/ui/button";
import { useChat } from "@/contexts/ChatContext";
import { useConnection } from "@/contexts/ConnectionContext";
import { useTheme } from "@/contexts/ThemeContext";
import { useWorkspace } from "@/contexts/WorkspaceContext";
import { downloadAgentArtifact, downloadAgentArtifactZip, listAgentArtifacts, previewAgentArtifact } from "@/lib/api";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

interface WorkspaceFileBrowserProps {
  agentName: string;
  collapsed: boolean;
  onToggle: () => void;
}

function buildChatPrompt(path: string): string {
  return [
    `Please inspect the workspace file \`${path}\` and help me with it.`,
    "Start by summarizing what it contains and any important implementation details, then wait for my next question.",
  ].join("\n\n");
}

export function WorkspaceFileBrowser({ agentName, collapsed, onToggle }: WorkspaceFileBrowserProps) {
  const { token, namespace } = useConnection();
  const { theme } = useTheme();
  const { setPrompt } = useChat();
  const { navigateToResource } = useWorkspace();
  const [expanded, setExpanded] = useState(false);
  const [zipping, setZipping] = useState(false);
  const [refreshNonce, setRefreshNonce] = useState(0);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);

  useEffect(() => {
    setExpanded(false);
    setZipping(false);
    setRefreshNonce(0);
    setSelectedPath(null);
  }, [agentName]);

  useEffect(() => {
    if (!collapsed) return;
    setExpanded(false);
  }, [collapsed]);

  useEffect(() => {
    if (!expanded) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setExpanded(false);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [expanded]);

  const handleLoad = useCallback(async () => {
    if (!token || !agentName) return { files: [], truncated: false, roots: [] };
    return listAgentArtifacts(token, namespace, agentName);
  }, [agentName, namespace, token]);

  const handlePreview = useCallback(async (path: string) => {
    if (!token || !agentName) {
      throw new Error("Enter a gateway token before previewing files.");
    }
    setSelectedPath(path);
    return previewAgentArtifact(token, namespace, agentName, path);
  }, [agentName, namespace, token]);

  const handleDownload = useCallback(async (path: string, filename?: string) => {
    if (!token || !agentName) return;
    await downloadAgentArtifact(token, namespace, agentName, path, filename);
  }, [agentName, namespace, token]);

  const handleDownloadZip = useCallback(async () => {
    if (!token || !agentName) return;
    setZipping(true);
    try {
      await downloadAgentArtifactZip(token, namespace, agentName);
      toast.success("Workspace archive downloaded");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "ZIP download failed");
    } finally {
      setZipping(false);
    }
  }, [agentName, namespace, token]);

  const handleAddToChat = useCallback(() => {
    if (!agentName || !selectedPath) return;
    setPrompt(buildChatPrompt(selectedPath));
    navigateToResource("chat", agentName);
    toast.success("File added to chat");
  }, [agentName, navigateToResource, selectedPath, setPrompt]);

  if (collapsed) {
    return (
      <div className="shrink-0 border-t bg-card">
        <button
          onClick={onToggle}
          className="flex w-full items-center gap-2 px-3 py-2 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent/60 hover:text-foreground"
        >
          <ChevronRight className="h-3 w-3" />
          <Package className="h-3.5 w-3.5" />
          Workspace Files
        </button>
      </div>
    );
  }

  const panel = (
    <div
      className={cn(
        "flex flex-col overflow-hidden border-border/70 bg-card text-card-foreground",
        expanded
          ? "fixed inset-x-4 bottom-4 top-16 z-50 rounded-xl border shadow-2xl shadow-black/20"
          : "border-t shrink-0",
      )}
      style={expanded ? undefined : { height: "48vh", maxHeight: "520px" }}
    >
      <div className="flex items-center justify-between border-b border-border/60 px-3 py-2 shrink-0">
        <button
          onClick={() => {
            setExpanded(false);
            onToggle();
          }}
          className="flex items-center gap-2 text-xs font-semibold text-foreground transition-colors hover:text-primary"
        >
          <ChevronRight className="h-3 w-3 rotate-90" />
          <Package className="h-3.5 w-3.5" />
          Workspace Files
        </button>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            className="h-7 gap-1.5 px-2 text-[10px]"
            onClick={handleAddToChat}
            disabled={!selectedPath}
            title="Open chat with this file"
          >
            <MessageSquare className="h-3.5 w-3.5" />
            Add to chat
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={() => setRefreshNonce((current) => current + 1)}
            title="Refresh"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={handleDownloadZip}
            disabled={zipping}
            title="Download workspace as ZIP"
          >
            <Archive className={cn("h-3.5 w-3.5", zipping && "animate-pulse")} />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={() => setExpanded((current) => !current)}
            title={expanded ? "Restore" : "Maximize"}
          >
            {expanded ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
          </Button>
        </div>
      </div>

      <div className="min-h-0 flex-1" key={`${agentName}:${refreshNonce}`}>
        <FileExplorer
          agentName={agentName}
          onLoad={handleLoad}
          onDownload={handleDownload}
          onDownloadAll={handleDownloadZip}
          onPreview={handlePreview}
        />
      </div>
    </div>
  );

  return expanded ? (
    <>
      <div className={cn(
        "fixed inset-0 z-40 backdrop-blur-sm",
        theme === "light" ? "bg-black/20" : "bg-black/55",
      )} onClick={() => setExpanded(false)} aria-hidden="true" />
      {panel}
    </>
  ) : panel;
}
