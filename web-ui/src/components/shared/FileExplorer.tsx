import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import type { AgentArtifactPreview, AgentFileEntry, AgentFileListResult } from "@/lib/api";
import { parseUnifiedDiff, reconstructOriginalText, resolveDiffForArtifactPath, type UnifiedDiffFile } from "@/lib/unifiedDiff";
import { FilePreviewPane } from "./FilePreviewPane";

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
  onDownloadAll?: () => Promise<void>;
  onPreview: (path: string) => Promise<AgentArtifactPreview>;
  onLoadDiff?: () => Promise<string>;
  preferredView?: "all" | "changed";
  liveUpdatesEnabled?: boolean;
}

type ExplorerViewMode = "all" | "changed";
type PreviewMode = "preview" | "diff";
type FileChangeKind = "add" | "del" | "mix";

const IMAGE_EXTS = new Set([".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico"]);
const MEDIA_PREVIEW_EXTS = new Set([".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico", ".pdf"]);
const TEXT_PREVIEW_MAX_BYTES = 2 * 1024 * 1024;
const MEDIA_PREVIEW_MAX_BYTES = 10 * 1024 * 1024;
const LIVE_REFRESH_INTERVAL_MS = 4500;

function buildTree(files: AgentFileEntry[]): TreeNode {
  const root: TreeNode = { name: "/", path: "/", isDir: true, children: new Map() };
  for (const file of files) {
    const parts = file.path.replace(/^\//, "").split("/");
    let node = root;
    for (let i = 0; i < parts.length; i += 1) {
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

function getExtension(name: string): string {
  const normalized = name.toLowerCase();
  if (normalized === "dockerfile") return ".dockerfile";
  if (normalized.startsWith(".")) return normalized;
  const extensionIndex = normalized.lastIndexOf(".");
  return extensionIndex >= 0 ? normalized.slice(extensionIndex) : "";
}

function isMediaPreviewable(name: string): boolean {
  return MEDIA_PREVIEW_EXTS.has(getExtension(name));
}

function normalizeExplorerPath(path: string): string {
  return path.replace(/\\/g, "/").replace(/^\/+/, "").replace(/\/+$/, "");
}

function mergeChangeKind(current: FileChangeKind | undefined, next: FileChangeKind): FileChangeKind {
  if (!current || current === next) return next;
  return "mix";
}

function statusToChangeKind(status: UnifiedDiffFile["status"]): FileChangeKind {
  if (status === "added") return "add";
  if (status === "deleted") return "del";
  return "mix";
}

function buildChangeKindMap(diffFiles: UnifiedDiffFile[]): Map<string, FileChangeKind> {
  const kinds = new Map<string, FileChangeKind>();

  for (const diffFile of diffFiles) {
    const rawPath = diffFile.newPath ?? diffFile.oldPath ?? diffFile.path;
    const normalizedPath = normalizeExplorerPath(rawPath);
    if (!normalizedPath) continue;

    const kind = statusToChangeKind(diffFile.status);
    kinds.set(normalizedPath, mergeChangeKind(kinds.get(normalizedPath), kind));

    const parts = normalizedPath.split("/");
    for (let index = 0; index < parts.length - 1; index += 1) {
      const directoryPath = parts.slice(0, index + 1).join("/");
      kinds.set(directoryPath, mergeChangeKind(kinds.get(directoryPath), kind));
    }
  }

  return kinds;
}

function buildVisibleChangedPaths(files: AgentFileEntry[], diffFiles: UnifiedDiffFile[]): Set<string> {
  const visible = new Set<string>();

  for (const file of files) {
    const diff = resolveDiffForArtifactPath(file.path, diffFiles);
    if (!diff) continue;

    const normalizedPath = normalizeExplorerPath(file.path);
    visible.add(normalizedPath);

    const parts = normalizedPath.split("/");
    for (let index = 0; index < parts.length - 1; index += 1) {
      visible.add(parts.slice(0, index + 1).join("/"));
    }
  }

  return visible;
}

function changeKindClass(kind: FileChangeKind): string {
  switch (kind) {
    case "add":
      return "border-emerald-500/25 bg-emerald-500/10 text-emerald-300";
    case "del":
      return "border-red-500/25 bg-red-500/10 text-red-300";
    default:
      return "border-cyan-500/25 bg-cyan-500/10 text-cyan-200";
  }
}

function fileIcon(name: string) {
  const ext = getExtension(name);
  if (IMAGE_EXTS.has(ext)) return Image;
  if (ext === ".pdf" || ext === ".md" || ext === ".markdown" || ext === ".mdx" || ext === ".txt" || ext === ".html") return FileText;
  return File;
}

const TreeNodeRow = memo(function TreeNodeRow({
  node,
  depth,
  filter,
  visiblePaths,
  changeKinds,
  selectedPath,
  downloadingPath,
  onSelect,
  onDownload,
}: {
  node: TreeNode;
  depth: number;
  filter: string;
  visiblePaths: Set<string> | null;
  changeKinds: Map<string, FileChangeKind>;
  selectedPath: string | null;
  downloadingPath: string | null;
  onSelect: (path: string) => void;
  onDownload: (path: string, filename: string) => void;
}) {
  const [open, setOpen] = useState(depth < 2);
  const sortedChildren = useMemo(() => {
    const entries = Array.from(node.children.values());
    entries.sort((left, right) => {
      if (left.isDir !== right.isDir) return left.isDir ? -1 : 1;
      return left.name.localeCompare(right.name);
    });
    return entries;
  }, [node.children]);

  const visibleChildren = useMemo(() => {
    const matchesNode = (candidate: TreeNode): boolean => {
      const normalizedCandidatePath = normalizeExplorerPath(candidate.path);
      const inCurrentView = !visiblePaths || visiblePaths.has(normalizedCandidatePath) || Array.from(candidate.children.values()).some(matchesNode);
      if (!inCurrentView) return false;
      if (!filter) return true;
      if (candidate.name.toLowerCase().includes(filter)) return true;
      return candidate.isDir && Array.from(candidate.children.values()).some(matchesNode);
    };

    return sortedChildren.filter(matchesNode);
  }, [filter, sortedChildren, visiblePaths]);
  const changeKind = useMemo(() => changeKinds.get(normalizeExplorerPath(node.path)) ?? null, [changeKinds, node.path]);

  if (node.isDir) {
    if (visibleChildren.length === 0 && (filter || visiblePaths)) return null;
    const FolderIcon = open ? FolderOpen : Folder;
    return (
      <>
        <button
          type="button"
          onClick={() => setOpen((current) => !current)}
          className="flex w-full items-center gap-1.5 rounded-lg px-2 py-1 text-xs transition-colors hover:bg-muted/50"
          style={{ paddingLeft: `${depth * 16 + 8}px` }}
        >
          <span className="transition-transform duration-150" style={{ transform: open ? "rotate(90deg)" : "rotate(0deg)" }}>
            <ChevronRight className="h-3 w-3 text-muted-foreground" />
          </span>
          <FolderIcon className="h-3.5 w-3.5 text-amber-500/80" />
          <span className="truncate font-medium text-foreground">{node.name}</span>
          {changeKind && (
            <span className={`rounded-full border px-1 py-0 text-[9px] leading-none ${changeKindClass(changeKind)}`}>
              {changeKind === "add" ? "+" : changeKind === "del" ? "-" : "~"}
            </span>
          )}
          <Badge variant="outline" className="ml-auto px-1 py-0 text-[9px]">
            {node.children.size}
          </Badge>
        </button>
        {open && visibleChildren.map((child) => (
          <TreeNodeRow
            key={child.path}
            node={child}
            depth={depth + 1}
            filter={filter}
            visiblePaths={visiblePaths}
            changeKinds={changeKinds}
            selectedPath={selectedPath}
            downloadingPath={downloadingPath}
            onSelect={onSelect}
            onDownload={onDownload}
          />
        ))}
      </>
    );
  }

  const FileIcon = fileIcon(node.name);
  const isDownloading = downloadingPath === node.path;
  const isSelected = selectedPath === node.path;

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onSelect(node.path)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect(node.path);
        }
      }}
      className={`group flex w-full items-center gap-1.5 rounded-lg px-2 py-1 text-xs transition-colors ${
        isSelected ? "bg-primary/10 text-foreground shadow-[inset_0_0_0_1px_rgba(45,212,191,0.24)]" : "hover:bg-muted/50"
      }`}
      style={{ paddingLeft: `${depth * 16 + 8}px` }}
      aria-pressed={isSelected}
    >
      <span className="w-3" />
      <FileIcon className={`h-3.5 w-3.5 shrink-0 ${isSelected ? "text-primary" : "text-muted-foreground"}`} />
      <span className="truncate flex-1 text-foreground">{node.name}</span>
      {changeKind && (
        <span className={`rounded-full border px-1 py-0 text-[9px] leading-none ${changeKindClass(changeKind)}`}>
          {changeKind === "add" ? "+" : changeKind === "del" ? "-" : "~"}
        </span>
      )}
      {node.file && <span className="shrink-0 text-[10px] text-muted-foreground">{formatSize(node.file.size)}</span>}
      <button
        type="button"
        onClick={(event) => {
          event.stopPropagation();
          onDownload(node.path, node.name);
        }}
        disabled={isDownloading}
        className="shrink-0 rounded p-0.5 text-primary opacity-0 transition-opacity hover:bg-primary/10 group-hover:opacity-100 disabled:opacity-50"
        title="Download"
        aria-label="Download file"
      >
        {isDownloading ? <LoaderCircle className="h-3 w-3 animate-spin" /> : <Download className="h-3 w-3" />}
      </button>
    </div>
  );
});

export const FileExplorer = memo(function FileExplorer({
  agentName,
  onLoad,
  onDownload,
  onDownloadAll,
  onPreview,
  onLoadDiff,
  preferredView = "all",
  liveUpdatesEnabled = false,
}: FileExplorerProps) {
  const [data, setData] = useState<AgentFileListResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("");
  const [viewMode, setViewMode] = useState<ExplorerViewMode>(preferredView);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [preview, setPreview] = useState<AgentArtifactPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewRefreshing, setPreviewRefreshing] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const [previewNonce, setPreviewNonce] = useState(0);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewMode, setPreviewMode] = useState<PreviewMode>(preferredView === "changed" ? "diff" : "preview");
  const [manualPreviewMode, setManualPreviewMode] = useState(false);
  const [diffFiles, setDiffFiles] = useState<UnifiedDiffFile[]>([]);
  const [diffLoading, setDiffLoading] = useState(false);
  const [diffRefreshing, setDiffRefreshing] = useState(false);
  const [diffError, setDiffError] = useState("");
  const [downloadingPath, setDownloadingPath] = useState<string | null>(null);
  const [downloadingAll, setDownloadingAll] = useState(false);
  const hasDataRef = useRef(false);
  const hasDiffRef = useRef(false);
  const previewPathRef = useRef<string | null>(null);
  const previewErrorRef = useRef(false);

  const loadFiles = useCallback(async ({ background = hasDataRef.current }: { background?: boolean } = {}) => {
    if (background) {
      setRefreshing(true);
    } else {
      setLoading(true);
      setError("");
    }

    try {
      const result = await onLoad();
      hasDataRef.current = true;
      setData(result);
      return result;
    } catch (err: unknown) {
      if (!background) {
        setError(err instanceof Error ? err.message : String(err));
      }
      return null;
    } finally {
      if (background) {
        setRefreshing(false);
      } else {
        setLoading(false);
      }
    }
  }, [onLoad]);

  const loadDiff = useCallback(async ({ background = hasDiffRef.current }: { background?: boolean } = {}) => {
    if (!onLoadDiff) {
      hasDiffRef.current = false;
      setDiffFiles([]);
      setDiffError("");
      setDiffLoading(false);
      setDiffRefreshing(false);
      return [] as UnifiedDiffFile[];
    }

    if (background) {
      setDiffRefreshing(true);
    } else {
      setDiffLoading(true);
      setDiffError("");
    }

    try {
      const parsed = parseUnifiedDiff(await onLoadDiff());
      hasDiffRef.current = parsed.length > 0;
      setDiffFiles(parsed);
      return parsed;
    } catch (err: unknown) {
      if (!background) {
        setDiffError(err instanceof Error ? err.message : String(err));
      }
      return [] as UnifiedDiffFile[];
    } finally {
      if (background) {
        setDiffRefreshing(false);
      } else {
        setDiffLoading(false);
      }
    }
  }, [onLoadDiff]);

  const refreshAll = useCallback(async ({ background = hasDataRef.current }: { background?: boolean } = {}) => {
    await Promise.allSettled([
      loadFiles({ background }),
      loadDiff({ background }),
    ]);
  }, [loadDiff, loadFiles]);

  useEffect(() => {
    hasDataRef.current = false;
    hasDiffRef.current = false;
    setData(null);
    setSelectedPath(null);
    setPreview(null);
    setPreviewError("");
    setPreviewLoading(false);
    setPreviewRefreshing(false);
    setPreviewMode(preferredView === "changed" ? "diff" : "preview");
    setManualPreviewMode(false);
    setDiffFiles([]);
    setDiffError("");
    setViewMode(preferredView);
    void refreshAll({ background: false });
  }, [agentName, preferredView, refreshAll]);

  useEffect(() => {
    setViewMode(preferredView);
  }, [preferredView]);

  useEffect(() => {
    previewPathRef.current = preview?.path ?? null;
  }, [preview?.path]);

  useEffect(() => {
    previewErrorRef.current = Boolean(previewError);
  }, [previewError]);

  useEffect(() => {
    if (!liveUpdatesEnabled) return;

    const tick = () => {
      if (document.hidden) return;
      void refreshAll({ background: true });
    };

    tick();
    const intervalId = window.setInterval(tick, LIVE_REFRESH_INTERVAL_MS);
    return () => window.clearInterval(intervalId);
  }, [liveUpdatesEnabled, refreshAll]);

  const tree = useMemo(() => (data ? buildTree(data.files) : null), [data]);
  const lowerFilter = filter.toLowerCase();
  const changeKinds = useMemo(() => buildChangeKindMap(diffFiles), [diffFiles]);
  const visibleChangedPaths = useMemo(() => buildVisibleChangedPaths(data?.files ?? [], diffFiles), [data?.files, diffFiles]);
  const changeCount = diffFiles.length;
  const selectedFile = useMemo(
    () => data?.files.find((file) => file.path === selectedPath) ?? null,
    [data, selectedPath],
  );
  const selectedFilePath = selectedFile?.path ?? null;
  const selectedFileName = selectedFile?.name ?? null;
  const selectedFileSize = selectedFile?.size ?? 0;
  const selectedPreviewSignature = selectedFile ? `${selectedFile.path}:${selectedFile.modified ?? 0}:${selectedFile.size}` : null;
  const selectedDiff = useMemo(
    () => (selectedFile ? resolveDiffForArtifactPath(selectedFile.path, diffFiles) : null),
    [diffFiles, selectedFile],
  );
  const diffOriginalText = useMemo(() => {
    if (!selectedDiff || preview?.text === undefined) return null;
    if (preview.kind !== "text" && preview.kind !== "markdown" && preview.kind !== "mermaid") return null;
    return reconstructOriginalText(preview.text, selectedDiff);
  }, [preview, selectedDiff]);

  useEffect(() => {
    if (!data?.files.length) {
      setSelectedPath(null);
      return;
    }

    const availableFiles = viewMode === "changed"
      ? data.files.filter((file) => visibleChangedPaths.has(normalizeExplorerPath(file.path)))
      : data.files;

    if (availableFiles.length === 0) {
      setSelectedPath(null);
      return;
    }

    if (selectedPath && availableFiles.some((file) => file.path === selectedPath)) {
      return;
    }
    setSelectedPath(availableFiles[0].path);
  }, [data, selectedPath, viewMode, visibleChangedPaths]);

  useEffect(() => {
    setManualPreviewMode(false);
    setPreviewMode(viewMode === "changed" ? "diff" : "preview");
  }, [selectedPath, viewMode]);

  useEffect(() => {
    if (manualPreviewMode || viewMode !== "changed") return;
    if (selectedDiff && diffOriginalText !== null) {
      setPreviewMode("diff");
    }
  }, [diffOriginalText, manualPreviewMode, selectedDiff, viewMode]);

  useEffect(() => {
    if (!preview?.blob) {
      setPreviewUrl(null);
      return;
    }
    const objectUrl = URL.createObjectURL(preview.blob);
    setPreviewUrl(objectUrl);
    return () => {
      URL.revokeObjectURL(objectUrl);
    };
  }, [preview]);

  useEffect(() => {
    if (!selectedFilePath || !selectedFileName) {
      setPreview(null);
      setPreviewError("");
      setPreviewLoading(false);
      setPreviewRefreshing(false);
      return;
    }

    const maxBytes = isMediaPreviewable(selectedFileName) ? MEDIA_PREVIEW_MAX_BYTES : TEXT_PREVIEW_MAX_BYTES;
    if (selectedFileSize > maxBytes) {
      setPreviewLoading(false);
      setPreviewRefreshing(false);
      setPreviewError("");
      setPreview({
        path: selectedFilePath,
        name: selectedFileName,
        size: selectedFileSize,
        contentType: "application/octet-stream",
        kind: "unsupported",
        message: `Preview is capped at ${formatSize(maxBytes)} for this file type. Download the file to inspect the full contents.`,
      });
      return;
    }

    let cancelled = false;
  const refreshInPlace = previewPathRef.current === selectedFilePath && !previewErrorRef.current;

    if (refreshInPlace) {
      setPreviewRefreshing(true);
    } else {
      setPreviewLoading(true);
      setPreviewError("");
      setPreview(null);
    }

    void onPreview(selectedFilePath)
      .then((result) => {
        if (!cancelled) {
          setPreviewError("");
          setPreview(result);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setPreviewError(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setPreviewLoading(false);
          setPreviewRefreshing(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [onPreview, previewNonce, selectedFileName, selectedFilePath, selectedFileSize, selectedPreviewSignature]);

  const handleDownload = useCallback(
    async (path: string, filename: string) => {
      try {
        setDownloadingPath(path);
        await onDownload(path, filename);
      } finally {
        setDownloadingPath((current) => (current === path ? null : current));
      }
    },
    [onDownload],
  );

  const handleDownloadAll = useCallback(async () => {
    if (!onDownloadAll) return;
    try {
      setDownloadingAll(true);
      await onDownloadAll();
    } finally {
      setDownloadingAll(false);
    }
  }, [onDownloadAll]);

  const handleSelect = useCallback((path: string) => {
    if (path === selectedPath) return;
    setManualPreviewMode(false);
    setPreviewMode(viewMode === "changed" ? "diff" : "preview");
    setSelectedPath(path);
  }, [selectedPath, viewMode]);

  const handleRetryPreview = useCallback(() => {
    setPreviewNonce((current) => current + 1);
  }, []);

  const handlePreviewModeChange = useCallback((mode: PreviewMode) => {
    setManualPreviewMode(true);
    setPreviewMode(mode);
  }, []);

  const handleRefresh = useCallback(() => {
    void refreshAll({ background: hasDataRef.current });
  }, [refreshAll]);

  const handleDownloadSelected = useCallback(() => {
    if (!selectedFile) return;
    void handleDownload(selectedFile.path, selectedFile.name);
  }, [handleDownload, selectedFile]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-border/60 px-3 py-2">
        {onLoadDiff && (
          <div className="flex items-center gap-1 rounded-full border border-border/70 bg-muted/20 p-1">
            <Button
              type="button"
              size="sm"
              variant={viewMode === "changed" ? "secondary" : "ghost"}
              className="h-6 gap-1 rounded-full px-2 text-[10px]"
              onClick={() => setViewMode("changed")}
            >
              Changed
              <Badge variant="outline" className="ml-1 px-1 py-0 text-[9px]">{changeCount}</Badge>
            </Button>
            <Button
              type="button"
              size="sm"
              variant={viewMode === "all" ? "secondary" : "ghost"}
              className="h-6 rounded-full px-2 text-[10px]"
              onClick={() => setViewMode("all")}
            >
              All files
            </Button>
          </div>
        )}
        <div className="relative min-w-[12rem] flex-1">
          <Search className="absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="h-7 pl-7 text-xs"
            placeholder="Filter files..."
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
          />
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          onClick={handleRefresh}
          disabled={loading || refreshing || diffLoading || diffRefreshing}
          title="Refresh"
          aria-label="Refresh files"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading || refreshing || diffLoading || diffRefreshing ? "animate-spin" : ""}`} />
        </Button>
        {onDownloadAll && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-7 gap-1.5 px-2 text-[10px]"
            onClick={() => void handleDownloadAll()}
            disabled={downloadingAll || Boolean(!data || data.files.length === 0)}
          >
            {downloadingAll ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
            {downloadingAll ? "Downloading…" : "Download All (ZIP)"}
          </Button>
        )}
      </div>

      <div className="grid min-h-0 flex-1 lg:grid-cols-[minmax(19rem,22rem)_minmax(0,1fr)]">
        <div className="min-h-0 border-b border-border/60 bg-muted/10 lg:border-b-0 lg:border-r">
          <ScrollArea className="h-full">
            <div className="py-1">
              {loading && !data && (
                <div className="flex items-center justify-center gap-2 py-8 text-xs text-muted-foreground">
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                  Loading files...
                </div>
              )}

              {error && (
                <div className="px-3 py-4 text-center text-xs text-destructive">
                  {error}
                </div>
              )}

              {viewMode === "changed" && diffError && (
                <div className="px-3 py-3 text-center text-xs text-amber-400">
                  {diffError}
                </div>
              )}

              {data && data.files.length === 0 && (
                <div className="px-3 py-8 text-center text-xs text-muted-foreground">
                  No files found in the agent workspace.
                </div>
              )}

              {data && viewMode === "changed" && !diffLoading && changeCount === 0 && !diffError && (
                <div className="px-3 py-8 text-center text-xs text-muted-foreground">
                  No changed files are available for this session yet.
                </div>
              )}

              {tree && Array.from(tree.children.values())
                .sort((left, right) => {
                  if (left.isDir !== right.isDir) return left.isDir ? -1 : 1;
                  return left.name.localeCompare(right.name);
                })
                .map((child) => (
                  <TreeNodeRow
                    key={child.path}
                    node={child}
                    depth={0}
                    filter={lowerFilter}
                    visiblePaths={viewMode === "changed" ? visibleChangedPaths : null}
                    changeKinds={changeKinds}
                    selectedPath={selectedPath}
                    downloadingPath={downloadingPath}
                    onSelect={handleSelect}
                    onDownload={handleDownload}
                  />
                ))}

              {data?.truncated && (
                <div className="px-3 py-2 text-center text-[10px] text-amber-500">
                  File list truncated — showing first {data.files.length} files.
                </div>
              )}
            </div>
          </ScrollArea>
        </div>

        <FilePreviewPane
          file={selectedFile}
          preview={preview}
          previewUrl={previewUrl}
          diffFile={selectedDiff}
          diffOriginalText={diffOriginalText}
          previewMode={previewMode}
          refreshing={refreshing || diffRefreshing || previewRefreshing}
          loading={previewLoading}
          error={previewError}
          onPreviewModeChange={handlePreviewModeChange}
          onRetry={handleRetryPreview}
          onDownload={handleDownloadSelected}
        />
      </div>

      {data && (
        <div className="flex items-center justify-between border-t border-border/60 px-3 py-1.5 text-[10px] text-muted-foreground">
          <span>
            {data.files.length} file{data.files.length !== 1 ? "s" : ""}
            {onLoadDiff && ` • ${changeCount} changed`}
          </span>
          <span className="truncate pl-2">{data.roots.join(", ")}</span>
        </div>
      )}
    </div>
  );
});
