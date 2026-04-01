import { memo, useCallback, useMemo } from "react";
import Editor, { DiffEditor, type Monaco } from "@monaco-editor/react";
import { AlertTriangle, Download, FileDiff, FileSearch, FileText, Image as ImageIcon, LoaderCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { AgentArtifactPreview, AgentFileEntry } from "@/lib/api";
import type { UnifiedDiffFile } from "@/lib/unifiedDiff";
import { MarkdownRenderer } from "./MarkdownRenderer";

interface FilePreviewPaneProps {
  file: AgentFileEntry | null;
  preview: AgentArtifactPreview | null;
  previewUrl: string | null;
  diffFile: UnifiedDiffFile | null;
  diffOriginalText: string | null;
  previewMode: "preview" | "diff";
  refreshing: boolean;
  loading: boolean;
  error: string;
  onPreviewModeChange: (mode: "preview" | "diff") => void;
  onRetry: () => void;
  onDownload: () => void;
}

const EDITOR_THEME = "kubesynth-control";

const EDITOR_OPTIONS = {
  automaticLayout: true,
  contextmenu: false,
  cursorBlinking: "solid",
  cursorStyle: "line-thin",
  domReadOnly: true,
  fontFamily: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace',
  fontLigatures: true,
  fontSize: 13,
  glyphMargin: false,
  lineNumbers: "on",
  minimap: { enabled: false },
  padding: { top: 14, bottom: 14 },
  readOnly: true,
  renderLineHighlight: "all",
  roundedSelection: true,
  scrollBeyondLastLine: false,
  scrollbar: {
    alwaysConsumeMouseWheel: false,
    horizontalScrollbarSize: 10,
    verticalScrollbarSize: 10,
  },
  smoothScrolling: true,
  wordWrap: "on",
} as const;

const DIFF_EDITOR_OPTIONS = {
  ...EDITOR_OPTIONS,
  enableSplitViewResizing: true,
  originalEditable: false,
  renderOverviewRuler: false,
  renderSideBySide: true,
} as const;

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatModified(seconds: number | undefined): string {
  if (!seconds || !Number.isFinite(seconds)) return "Unknown";
  return new Date(seconds * 1000).toLocaleString();
}

function inferEditorLanguage(path: string): string {
  const fileName = path.split(/[\\/]/).pop()?.toLowerCase() ?? "";
  const extension = fileName === "dockerfile"
    ? ".dockerfile"
    : fileName.startsWith(".")
      ? fileName
      : fileName.includes(".")
        ? fileName.slice(fileName.lastIndexOf("."))
        : "";

  switch (extension) {
    case ".js":
    case ".jsx":
    case ".mjs":
    case ".cjs":
      return "javascript";
    case ".ts":
    case ".tsx":
      return "typescript";
    case ".css":
      return "css";
    case ".scss":
      return "scss";
    case ".html":
    case ".htm":
      return "html";
    case ".json":
      return "json";
    case ".md":
    case ".markdown":
    case ".mdx":
      return "markdown";
    case ".xml":
      return "xml";
    case ".sql":
      return "sql";
    case ".sh":
    case ".bash":
    case ".zsh":
      return "shell";
    case ".ps1":
    case ".psm1":
      return "powershell";
    case ".py":
      return "python";
    case ".rb":
      return "ruby";
    case ".go":
      return "go";
    case ".rs":
      return "rust";
    case ".java":
      return "java";
    case ".kt":
      return "kotlin";
    case ".php":
      return "php";
    case ".ini":
    case ".env":
      return "ini";
    case ".yaml":
    case ".yml":
      return "yaml";
    case ".dockerfile":
      return "dockerfile";
    default:
      return "plaintext";
  }
}

function configureMonaco(monaco: Monaco): void {
  monaco.editor.defineTheme(EDITOR_THEME, {
    base: "vs-dark",
    inherit: true,
    rules: [
      { token: "comment", foreground: "6B7280" },
      { token: "string", foreground: "B6F4E7" },
      { token: "keyword", foreground: "7DD3FC" },
      { token: "number", foreground: "FBBF24" },
      { token: "type", foreground: "A5B4FC" },
    ],
    colors: {
      "editor.background": "#101318",
      "editor.foreground": "#E5EEF5",
      "editorLineNumber.foreground": "#5A6473",
      "editorLineNumber.activeForeground": "#8EA6B8",
      "editor.selectionBackground": "#164E63",
      "editor.inactiveSelectionBackground": "#13323D",
      "editor.lineHighlightBackground": "#141A22",
      "editorIndentGuide.background1": "#202733",
      "editorIndentGuide.activeBackground1": "#2DD4BF",
      "diffEditor.insertedTextBackground": "#0A7A5A33",
      "diffEditor.removedTextBackground": "#A12C3C33",
      "diffEditor.insertedLineBackground": "#0A7A5A22",
      "diffEditor.removedLineBackground": "#A12C3C22",
      "diffEditor.diagonalFill": "#0F141B",
    },
  });
}

function statusBadgeClass(status: UnifiedDiffFile["status"]): string {
  switch (status) {
    case "added":
      return "border-emerald-500/30 bg-emerald-500/10 text-emerald-300";
    case "deleted":
      return "border-red-500/30 bg-red-500/10 text-red-300";
    default:
      return "border-cyan-500/30 bg-cyan-500/10 text-cyan-200";
  }
}

export const FilePreviewPane = memo(function FilePreviewPane({
  file,
  preview,
  previewUrl,
  diffFile,
  diffOriginalText,
  previewMode,
  refreshing,
  loading,
  error,
  onPreviewModeChange,
  onRetry,
  onDownload,
}: FilePreviewPaneProps) {
  const editorLanguage = useMemo(() => (file ? inferEditorLanguage(file.path) : "plaintext"), [file]);
  const handleBeforeMount = useCallback((monaco: Monaco) => {
    configureMonaco(monaco);
  }, []);
  const canRenderTextDiff = Boolean(
    file &&
    diffFile &&
    diffOriginalText !== null &&
    preview?.text !== undefined &&
    (preview.kind === "text" || preview.kind === "markdown"),
  );
  const showDiffEditor = canRenderTextDiff && previewMode === "diff";

  return (
    <div className="flex min-h-[22rem] min-w-0 flex-1 flex-col bg-[linear-gradient(180deg,rgba(45,212,191,0.06),rgba(0,0,0,0)_10rem)] lg:min-h-0">
      <div className="border-b border-border/60 px-4 py-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2 text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
              <span>Preview</span>
              {file && <Badge variant="outline" className="px-1.5 py-0 text-[10px] normal-case">{formatSize(file.size)}</Badge>}
              {preview?.kind && <Badge variant="outline" className="px-1.5 py-0 text-[10px] normal-case">{preview.kind}</Badge>}
            </div>
            <div className="mt-2 truncate text-sm font-semibold text-foreground">
              {file?.name ?? "Select a file"}
            </div>
            <div className="mt-1 truncate font-mono text-[11px] text-muted-foreground">
              {file?.path ?? "Choose a file from the workspace tree to preview it here."}
            </div>
            {file && (
              <div className="mt-2 flex flex-wrap items-center gap-2">
                {diffFile && (
                  <Badge variant="outline" className={`px-1.5 py-0 text-[10px] normal-case ${statusBadgeClass(diffFile.status)}`}>
                    {diffFile.status}
                  </Badge>
                )}
                {diffFile && (diffFile.addedCount > 0 || diffFile.removedCount > 0) && (
                  <>
                    {diffFile.addedCount > 0 && (
                      <Badge variant="outline" className="border-emerald-500/25 bg-emerald-500/10 px-1.5 py-0 text-[10px] normal-case text-emerald-300">
                        +{diffFile.addedCount}
                      </Badge>
                    )}
                    {diffFile.removedCount > 0 && (
                      <Badge variant="outline" className="border-red-500/25 bg-red-500/10 px-1.5 py-0 text-[10px] normal-case text-red-300">
                        -{diffFile.removedCount}
                      </Badge>
                    )}
                  </>
                )}
                {refreshing && (
                  <Badge variant="outline" className="gap-1 px-1.5 py-0 text-[10px] normal-case text-primary">
                    <LoaderCircle className="h-3 w-3 animate-spin" />
                    Syncing
                  </Badge>
                )}
              </div>
            )}
          </div>
          {file && (
            <Button type="button" size="sm" className="h-8 gap-1.5 px-3 text-[11px]" onClick={onDownload}>
              <Download className="h-3.5 w-3.5" />
              Download
            </Button>
          )}
        </div>
        {file && (
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[11px] text-muted-foreground">
            <span>Last modified {formatModified(file.modified)}</span>
            {canRenderTextDiff && (
              <div className="flex items-center gap-1 rounded-full border border-border/70 bg-muted/20 p-1">
                <Button
                  type="button"
                  size="sm"
                  variant={previewMode === "preview" ? "secondary" : "ghost"}
                  className="h-6 gap-1 rounded-full px-2 text-[10px]"
                  onClick={() => onPreviewModeChange("preview")}
                >
                  <FileText className="h-3 w-3" />
                  Preview
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant={previewMode === "diff" ? "secondary" : "ghost"}
                  className="h-6 gap-1 rounded-full px-2 text-[10px]"
                  onClick={() => onPreviewModeChange("diff")}
                >
                  <FileDiff className="h-3 w-3" />
                  Split diff
                </Button>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="min-h-0 flex-1">
        {!file && (
          <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-border/70 bg-muted/30 text-primary">
              <FileSearch className="h-5 w-5" />
            </div>
            <div>
              <div className="text-sm font-medium text-foreground">Workspace preview is ready</div>
              <div className="mt-1 max-w-sm text-xs leading-relaxed text-muted-foreground">
                Browse the runtime workspace on the left and select a file to inspect it without leaving the app.
              </div>
            </div>
          </div>
        )}

        {file && loading && (
          <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center text-muted-foreground">
            <LoaderCircle className="h-5 w-5 animate-spin text-primary" />
            <div>
              <div className="text-sm font-medium text-foreground">Loading preview</div>
              <div className="mt-1 text-xs">Fetching the latest file contents from the runtime workspace.</div>
            </div>
          </div>
        )}

        {file && !loading && error && (
          <div className="flex h-full flex-col items-center justify-center gap-4 p-6 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-destructive/30 bg-destructive/10 text-destructive">
              <AlertTriangle className="h-5 w-5" />
            </div>
            <div>
              <div className="text-sm font-medium text-foreground">Preview failed</div>
              <div className="mt-1 max-w-md text-xs leading-relaxed text-muted-foreground">{error}</div>
            </div>
            <Button type="button" variant="outline" size="sm" className="h-8 px-3 text-[11px]" onClick={onRetry}>
              Try again
            </Button>
          </div>
        )}

        {file && !loading && !error && preview?.kind === "image" && previewUrl && (
          <ScrollArea className="h-full">
            <div className="flex min-h-full items-start justify-center p-4">
              <img src={previewUrl} alt={file.name} className="max-h-[70vh] w-auto max-w-full rounded-2xl border border-border/70 bg-card object-contain shadow-lg shadow-black/20" />
            </div>
          </ScrollArea>
        )}

        {file && !loading && !error && preview?.kind === "pdf" && previewUrl && (
          <iframe title={file.name} src={previewUrl} className="h-full w-full border-0 bg-background" />
        )}

        {file && !loading && !error && showDiffEditor && (
          <DiffEditor
            beforeMount={handleBeforeMount}
            height="100%"
            loading={<div className="flex h-full items-center justify-center text-xs text-muted-foreground">Loading editor…</div>}
            modified={preview?.text ?? ""}
            modifiedLanguage={editorLanguage}
            modifiedModelPath={`modified://${file.path}`}
            options={DIFF_EDITOR_OPTIONS}
            original={diffOriginalText ?? ""}
            originalLanguage={editorLanguage}
            originalModelPath={`original://${file.path}`}
            theme={EDITOR_THEME}
          />
        )}

        {file && !loading && !error && preview?.kind === "markdown" && !showDiffEditor && (
          <ScrollArea className="h-full">
            <div className="px-5 py-4">
              <MarkdownRenderer content={preview.text ?? ""} />
            </div>
          </ScrollArea>
        )}

        {file && !loading && !error && preview?.kind === "text" && !showDiffEditor && (
          <Editor
            beforeMount={handleBeforeMount}
            height="100%"
            language={editorLanguage}
            loading={<div className="flex h-full items-center justify-center text-xs text-muted-foreground">Loading editor…</div>}
            options={EDITOR_OPTIONS}
            path={file.path}
            theme={EDITOR_THEME}
            value={preview.text ?? ""}
          />
        )}

        {file && !loading && !error && preview?.kind === "unsupported" && (
          <div className="flex h-full flex-col items-center justify-center gap-4 p-6 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-border/70 bg-muted/30 text-primary">
              {preview.contentType.startsWith("image/") ? <ImageIcon className="h-5 w-5" /> : <FileText className="h-5 w-5" />}
            </div>
            <div>
              <div className="text-sm font-medium text-foreground">Preview unavailable</div>
              <div className="mt-1 max-w-md text-xs leading-relaxed text-muted-foreground">
                {preview.message ?? "This file type is available for download, but it does not have an in-app preview yet."}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
});