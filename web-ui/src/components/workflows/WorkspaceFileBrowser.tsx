import { useCallback, useEffect, useRef, useState } from "react";
import {
  ChevronRight,
  Download,
  File,
  FileText,
  Folder,
  FolderOpen,
  LoaderCircle,
  Package,
  RefreshCw,
  Archive,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useConnection } from "@/contexts/ConnectionContext";
import { downloadAgentArtifact, downloadAgentArtifactZip, listAgentArtifacts, previewAgentArtifact } from "@/lib/api";
import type { AgentArtifactPreview, AgentFileEntry } from "@/lib/api";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

// ─── Types ───

interface TreeNode {
  name: string;
  path: string;
  isDir: boolean;
  children: Map<string, TreeNode>;
  file?: AgentFileEntry;
}

interface WorkspaceFileBrowserProps {
  agentName: string;
  collapsed: boolean;
  onToggle: () => void;
}

// ─── Helpers ───

function buildTree(files: AgentFileEntry[]): TreeNode {
  const root: TreeNode = { name: "/workspace", path: "/workspace", isDir: true, children: new Map() };
  for (const file of files) {
    const parts = file.path.replace(/\\/g, "/").split("/").filter(Boolean);
    let node = root;
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      const isLast = i === parts.length - 1;
      if (!node.children.has(part)) {
        node.children.set(part, {
          name: part,
          path: parts.slice(0, i + 1).join("/"),
          isDir: !isLast,
          children: new Map(),
          file: isLast ? file : undefined,
        });
      }
      const child = node.children.get(part)!;
      if (isLast) child.file = file;
      node = child;
    }
  }
  return root;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function isTextPreviewable(name: string): boolean {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  return ["md", "txt", "json", "yaml", "yml", "ts", "tsx", "js", "jsx", "py", "css", "html", "xml", "sh", "toml", "ini", "cfg", "log", "env", "dockerfile", "gitignore"].includes(ext);
}

// ─── Tree Node ───

function TreeNodeItem({
  node,
  depth,
  onSelect,
  selectedPath,
}: {
  node: TreeNode;
  depth: number;
  onSelect: (path: string) => void;
  selectedPath: string | null;
}) {
  const [expanded, setExpanded] = useState(depth < 2);
  const hasChildren = node.children.size > 0;
  const isSelected = selectedPath === node.path;

  const icon = node.isDir
    ? expanded
      ? <FolderOpen className="h-4 w-4 text-amber-400 shrink-0" />
      : <Folder className="h-4 w-4 text-amber-400 shrink-0" />
    : isTextPreviewable(node.name)
      ? <FileText className="h-4 w-4 text-sky-400 shrink-0" />
      : <File className="h-4 w-4 text-[oklch(0.62_0.01_264)] shrink-0" />;

  return (
    <div>
      <div
        className={cn(
          "flex items-center gap-1.5 rounded-md px-2 py-1 cursor-pointer text-xs transition-colors hover:bg-[oklch(0.28_0.015_264)]",
          isSelected && "bg-[oklch(0.708_0.101_188/0.15)] text-[oklch(0.92_0.004_264)]",
          !isSelected && "text-[oklch(0.72_0.01_264)]",
        )}
        style={{ paddingLeft: `${depth * 14 + 8}px` }}
        onClick={() => {
          if (node.isDir) setExpanded(!expanded);
          if (!node.isDir) onSelect(node.path);
        }}
      >
        {node.isDir && (
          <ChevronRight className={cn("h-3 w-3 shrink-0 transition-transform", expanded && "rotate-90")} />
        )}
        {icon}
        <span className="truncate flex-1">{node.name}</span>
        {node.file && (
          <span className="text-[10px] text-[oklch(0.50_0.01_264)] tabular-nums shrink-0">
            {formatSize(node.file.size)}
          </span>
        )}
      </div>
      {expanded && hasChildren && (
        <div>
          {Array.from(node.children.values())
            .sort((a, b) => {
              if (a.isDir !== b.isDir) return a.isDir ? -1 : 1;
              return a.name.localeCompare(b.name);
            })
            .map((child) => (
              <TreeNodeItem
                key={child.path}
                node={child}
                depth={depth + 1}
                onSelect={onSelect}
                selectedPath={selectedPath}
              />
            ))}
        </div>
      )}
    </div>
  );
}

// ─── Main Component ───

export function WorkspaceFileBrowser({ agentName, collapsed, onToggle }: WorkspaceFileBrowserProps) {
  const { token, namespace } = useConnection();
  const [files, setFiles] = useState<AgentFileEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [preview, setPreview] = useState<AgentArtifactPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [zipping, setZipping] = useState(false);
  const loadedRef = useRef(false);

  const tree = buildTree(files);

  const loadFiles = useCallback(async () => {
    if (!token || !agentName) return;
    setLoading(true); setError("");
    try {
      const result = await listAgentArtifacts(token, namespace, agentName);
      setFiles(result.files ?? []);
      loadedRef.current = true;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load files");
    } finally { setLoading(false); }
  }, [token, namespace, agentName]);

  useEffect(() => {
    if (!collapsed && !loadedRef.current) loadFiles();
  }, [collapsed, loadFiles]);

  const handleSelect = useCallback(async (path: string) => {
    setSelectedPath(path);
    if (!token || !agentName) return;
    setPreviewLoading(true);
    try {
      const result = await previewAgentArtifact(token, namespace, agentName, path);
      setPreview(result);
    } catch {
      setPreview(null);
    } finally { setPreviewLoading(false); }
  }, [token, namespace, agentName]);

  const handleDownload = useCallback(async (path: string) => {
    if (!token || !agentName) return;
    try {
      const name = path.split("/").pop() ?? path;
      await downloadAgentArtifact(token, namespace, agentName, path, name);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Download failed");
    }
  }, [token, namespace, agentName]);

  const handleDownloadZip = useCallback(async () => {
    if (!token || !agentName) return;
    setZipping(true);
    try {
      await downloadAgentArtifactZip(token, namespace, agentName);
      toast.success("Workspace archive downloaded");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "ZIP download failed");
    } finally { setZipping(false); }
  }, [token, namespace, agentName]);

  if (collapsed) {
    return (
      <div className="border-t bg-[oklch(0.16_0.009_264)] shrink-0">
        <button
          onClick={onToggle}
          className="flex w-full items-center gap-2 px-3 py-2 text-xs font-medium text-[oklch(0.62_0.01_264)] hover:text-[oklch(0.82_0.01_264)] hover:bg-[oklch(0.22_0.012_264)] transition-colors"
        >
          <ChevronRight className="h-3 w-3" />
          <Package className="h-3.5 w-3.5" />
          Workspace Files
        </button>
      </div>
    );
  }

  return (
    <div className="border-t bg-[oklch(0.16_0.009_264)] flex flex-col shrink-0" style={{ height: "40vh", maxHeight: "400px" }}>
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[oklch(0.22_0.012_264)] px-3 py-2 shrink-0">
        <button
          onClick={onToggle}
          className="flex items-center gap-2 text-xs font-semibold text-[oklch(0.82_0.01_264)] hover:text-[oklch(0.95_0.004_264)] transition-colors"
        >
          <ChevronRight className="h-3 w-3 rotate-90" />
          <Package className="h-3.5 w-3.5" />
          Workspace Files
          {files.length > 0 && (
            <span className="rounded-full bg-[oklch(0.25_0.012_264)] px-1.5 py-0.5 text-[10px] text-[oklch(0.62_0.01_264)]">
              {files.length}
            </span>
          )}
        </button>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={loadFiles}
            disabled={loading}
            title="Refresh"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={handleDownloadZip}
            disabled={zipping || files.length === 0}
            title="Download workspace as ZIP"
          >
            <Archive className={cn("h-3.5 w-3.5", zipping && "animate-pulse")} />
          </Button>
        </div>
      </div>

      {/* Body: tree + preview */}
      <div className="flex flex-1 min-h-0">
        {/* File tree */}
        <div className="w-56 border-r border-[oklch(0.22_0.012_264)] flex flex-col">
          {loading ? (
            <div className="flex flex-1 items-center justify-center">
              <LoaderCircle className="h-5 w-5 animate-spin text-[oklch(0.50_0.01_264)]" />
            </div>
          ) : error ? (
            <div className="flex flex-1 items-center justify-center p-3">
              <p className="text-xs text-red-400 text-center">{error}</p>
            </div>
          ) : files.length === 0 ? (
            <div className="flex flex-1 items-center justify-center p-3">
              <p className="text-xs text-[oklch(0.50_0.01_264)] text-center">No files yet.<br />Run the workflow first.</p>
            </div>
          ) : (
            <ScrollArea className="flex-1">
              <div className="py-1">
                {Array.from(tree.children.values())
                  .sort((a, b) => {
                    if (a.isDir !== b.isDir) return a.isDir ? -1 : 1;
                    return a.name.localeCompare(b.name);
                  })
                  .map((child) => (
                    <TreeNodeItem
                      key={child.path}
                      node={child}
                      depth={0}
                      onSelect={handleSelect}
                      selectedPath={selectedPath}
                    />
                  ))}
              </div>
            </ScrollArea>
          )}
        </div>

        {/* Preview */}
        <div className="flex-1 flex flex-col min-w-0">
          {previewLoading ? (
            <div className="flex flex-1 items-center justify-center">
              <LoaderCircle className="h-5 w-5 animate-spin text-[oklch(0.50_0.01_264)]" />
            </div>
          ) : preview ? (
            <>
              <div className="flex items-center justify-between border-b border-[oklch(0.22_0.012_264)] px-3 py-1.5 shrink-0">
                <span className="text-[11px] font-medium text-[oklch(0.78_0.01_264)] truncate">{preview.path}</span>
                <div className="flex items-center gap-1">
                  <span className="text-[10px] text-[oklch(0.50_0.01_264)]">{formatSize(preview.size)}</span>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6"
                    onClick={() => handleDownload(preview.path)}
                    title="Download file"
                  >
                    <Download className="h-3 w-3" />
                  </Button>
                </div>
              </div>
              <ScrollArea className="flex-1">
                {preview.contentType?.startsWith("image/") && preview.blob ? (
                  <div className="flex items-center justify-center p-4">
                    <img
                      src={URL.createObjectURL(preview.blob)}
                      alt={preview.path}
                      className="max-w-full max-h-full object-contain rounded-lg"
                    />
                  </div>
                ) : preview.text != null ? (
                  <pre className="p-3 text-xs font-mono text-[oklch(0.82_0.01_264)] whitespace-pre-wrap break-words">
                    {preview.text.slice(0, 50000)}
                    {preview.text.length > 50000 && (
                      <span className="text-[oklch(0.50_0.01_264)]">{"\n\n... truncated (file too large)"}</span>
                    )}
                  </pre>
                ) : (
                  <div className="flex flex-1 items-center justify-center p-3">
                    <p className="text-xs text-[oklch(0.50_0.01_264)]">Binary file — download to view</p>
                  </div>
                )}
              </ScrollArea>
            </>
          ) : selectedPath ? (
            <div className="flex flex-1 items-center justify-center">
              <p className="text-xs text-[oklch(0.50_0.01_264)]">Could not preview this file</p>
            </div>
          ) : (
            <div className="flex flex-1 items-center justify-center">
              <div className="text-center">
                <Package className="h-8 w-8 mx-auto text-[oklch(0.35_0.01_264)] mb-2" />
                <p className="text-xs text-[oklch(0.50_0.01_264)]">Select a file to preview</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
