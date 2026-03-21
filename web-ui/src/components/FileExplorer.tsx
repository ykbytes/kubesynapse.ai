import { memo, useCallback, useEffect, useMemo, useState } from "react";
import {
  ChevronRight,
  Download,
  File,
  FileText,
  Folder,
  FolderOpen,
  Image,
  LoaderCircle,
  RefreshCw,
  Search,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { AgentFileEntry, AgentFileListResult } from "@/lib/api";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface TreeNode {
  name: string;
  path: string;
  isDir: boolean;
  children: Map<string, TreeNode>;
  file?: AgentFileEntry;
}

interface FileExplorerProps {
  agentName: string;
  onLoad: () => Promise<AgentFileListResult>;
  onDownload: (path: string, filename?: string) => Promise<void>;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function buildTree(files: AgentFileEntry[]): TreeNode {
  const root: TreeNode = { name: "/", path: "/", isDir: true, children: new Map() };
  for (const file of files) {
    const parts = file.path.replace(/^\//, "").split("/");
    let node = root;
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      const isLast = i === parts.length - 1;
      if (!node.children.has(part)) {
        const childPath = "/" + parts.slice(0, i + 1).join("/");
        node.children.set(part, {
          name: part,
          path: childPath,
          isDir: !isLast,
          children: new Map(),
          file: isLast ? file : undefined,
        });
      }
      node = node.children.get(part)!;
      if (!isLast) node.isDir = true;
    }
  }
  return root;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const IMAGE_EXTS = new Set([".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"]);
const DOC_EXTS = new Set([".pdf", ".md", ".txt", ".doc", ".docx", ".csv", ".html"]);

function fileIcon(name: string) {
  const ext = name.includes(".") ? "." + name.split(".").pop()!.toLowerCase() : "";
  if (IMAGE_EXTS.has(ext)) return Image;
  if (DOC_EXTS.has(ext)) return FileText;
  return File;
}

/* ------------------------------------------------------------------ */
/*  Tree node component                                                */
/* ------------------------------------------------------------------ */

const TreeNodeRow = memo(function TreeNodeRow({
  node,
  depth,
  filter,
  downloadingPath,
  onDownload,
}: {
  node: TreeNode;
  depth: number;
  filter: string;
  downloadingPath: string | null;
  onDownload: (path: string, filename: string) => void;
}) {
  const [open, setOpen] = useState(depth < 2);
  const sortedChildren = useMemo(() => {
    const entries = Array.from(node.children.values());
    entries.sort((a, b) => {
      if (a.isDir !== b.isDir) return a.isDir ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    return entries;
  }, [node.children]);

  const visibleChildren = useMemo(() => {
    if (!filter) return sortedChildren;
    return sortedChildren.filter((child) => {
      if (child.name.toLowerCase().includes(filter)) return true;
      if (child.isDir) {
        // Keep dirs that have matching descendants
        const check = (n: TreeNode): boolean => {
          if (n.name.toLowerCase().includes(filter)) return true;
          for (const c of n.children.values()) if (check(c)) return true;
          return false;
        };
        return check(child);
      }
      return false;
    });
  }, [sortedChildren, filter]);

  if (node.isDir) {
    if (visibleChildren.length === 0 && filter) return null;
    const FolderIcon = open ? FolderOpen : Folder;
    return (
      <>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="flex w-full items-center gap-1.5 px-2 py-1 text-xs hover:bg-muted/50 rounded transition-colors"
          style={{ paddingLeft: `${depth * 16 + 8}px` }}
        >
          <span
            className="transition-transform duration-150"
            style={{ transform: open ? "rotate(90deg)" : "rotate(0deg)" }}
          >
            <ChevronRight className="h-3 w-3 text-muted-foreground" />
          </span>
          <FolderIcon className="h-3.5 w-3.5 text-amber-500/80" />
          <span className="truncate font-medium text-foreground">{node.name}</span>
          <Badge variant="outline" className="ml-auto text-[9px] px-1 py-0">
            {node.children.size}
          </Badge>
        </button>
        {open &&
          visibleChildren.map((child) => (
            <TreeNodeRow
              key={child.path}
              node={child}
              depth={depth + 1}
              filter={filter}
              downloadingPath={downloadingPath}
              onDownload={onDownload}
            />
          ))}
      </>
    );
  }

  // File row
  const FileIcon = fileIcon(node.name);
  const isDownloading = downloadingPath === node.path;
  return (
    <div
      className="group flex w-full items-center gap-1.5 px-2 py-1 text-xs hover:bg-muted/50 rounded transition-colors"
      style={{ paddingLeft: `${depth * 16 + 8}px` }}
    >
      <span className="w-3" />
      <FileIcon className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
      <span className="truncate flex-1 text-foreground">{node.name}</span>
      {node.file && (
        <span className="text-[10px] text-muted-foreground shrink-0">{formatSize(node.file.size)}</span>
      )}
      <button
        type="button"
        onClick={() => onDownload(node.path, node.name)}
        disabled={isDownloading}
        className="opacity-0 group-hover:opacity-100 transition-opacity shrink-0 p-0.5 rounded hover:bg-primary/10 text-primary disabled:opacity-50"
        title="Download"
      >
        {isDownloading ? (
          <LoaderCircle className="h-3 w-3 animate-spin" />
        ) : (
          <Download className="h-3 w-3" />
        )}
      </button>
    </div>
  );
});

/* ------------------------------------------------------------------ */
/*  Main component                                                     */
/* ------------------------------------------------------------------ */

export const FileExplorer = memo(function FileExplorer({
  agentName,
  onLoad,
  onDownload,
}: FileExplorerProps) {
  const [data, setData] = useState<AgentFileListResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("");
  const [downloadingPath, setDownloadingPath] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const result = await onLoad();
      setData(result);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [onLoad]);

  useEffect(() => {
    void load();
  }, [load, agentName]);

  const tree = useMemo(() => (data ? buildTree(data.files) : null), [data]);

  const handleDownload = useCallback(
    async (path: string, filename: string) => {
      try {
        setDownloadingPath(path);
        await onDownload(path, filename);
      } finally {
        setDownloadingPath((cur) => (cur === path ? null : cur));
      }
    },
    [onDownload],
  );

  const lowerFilter = filter.toLowerCase();

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-border/60 px-3 py-2">
        <div className="relative flex-1">
          <Search className="absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="h-7 pl-7 text-xs"
            placeholder="Filter files..."
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          onClick={() => void load()}
          disabled={loading}
          title="Refresh"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
        </Button>
      </div>

      {/* Content */}
      <ScrollArea className="flex-1 min-h-0">
        <div className="py-1">
          {loading && !data && (
            <div className="flex items-center justify-center gap-2 py-8 text-xs text-muted-foreground">
              <LoaderCircle className="h-4 w-4 animate-spin" />
              Loading files...
            </div>
          )}
          {error && (
            <div className="px-3 py-4 text-xs text-destructive text-center">
              {error}
            </div>
          )}
          {data && data.files.length === 0 && (
            <div className="px-3 py-8 text-xs text-muted-foreground text-center">
              No files found in the agent workspace.
            </div>
          )}
          {tree &&
            Array.from(tree.children.values())
              .sort((a, b) => {
                if (a.isDir !== b.isDir) return a.isDir ? -1 : 1;
                return a.name.localeCompare(b.name);
              })
              .map((child) => (
                <TreeNodeRow
                  key={child.path}
                  node={child}
                  depth={0}
                  filter={lowerFilter}
                  downloadingPath={downloadingPath}
                  onDownload={handleDownload}
                />
              ))}
          {data?.truncated && (
            <div className="px-3 py-2 text-[10px] text-amber-500 text-center">
              File list truncated — showing first {data.files.length} files.
            </div>
          )}
        </div>
      </ScrollArea>

      {/* Footer */}
      {data && (
        <div className="border-t border-border/60 px-3 py-1.5 text-[10px] text-muted-foreground flex items-center justify-between">
          <span>{data.files.length} file{data.files.length !== 1 ? "s" : ""}</span>
          <span className="truncate ml-2">{data.roots.join(", ")}</span>
        </div>
      )}
    </div>
  );
});
