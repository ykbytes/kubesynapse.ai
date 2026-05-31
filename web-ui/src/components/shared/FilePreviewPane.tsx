import { memo, useCallback, useEffect, useMemo, useState } from "react";
import Editor, { DiffEditor, type Monaco } from "@monaco-editor/react";
import { AlertTriangle, Download, Eye, FileCode2, FileDiff, FileSearch, FileText, Image as ImageIcon, LoaderCircle, Type, Waypoints, WrapText } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useTheme } from "@/contexts/ThemeContext";
import type { AgentArtifactPreview, AgentFileEntry } from "@/lib/api";
import type { UnifiedDiffFile } from "@/lib/unifiedDiff";
import { CopyButton } from "./CopyButton";
import { MarkdownRenderer } from "./MarkdownRenderer";
import { MermaidDiagram } from "./MermaidDiagram";

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

const EDITOR_THEME_DARK = "kubesynapse-control-dark";
const EDITOR_THEME_LIGHT = "kubesynapse-control-light";

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

type MarkdownViewMode = "rendered" | "source" | "split";
type EditorWordWrap = "on" | "off";

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
    case ".mmd":
    case ".mermaid":
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
    case ".cfg":
    case ".conf":
    case ".properties":
      return "ini";
    case ".yaml":
    case ".yml":
      return "yaml";
    case ".dockerfile":
      return "dockerfile";
    case ".toml":
      return "ini";
    case ".j2":
    case ".jinja":
    case ".jinja2":
    case ".tpl":
    case ".tmpl":
      return "plaintext";
    case ".tf":
    case ".hcl":
      return "plaintext";
    case ".service":
    case ".timer":
    case ".socket":
    case ".target":
      return "ini";
    case ".csv":
    case ".tsv":
      return "plaintext";
    case ".swift":
      return "swift";
    case ".r":
      return "r";
    case ".c":
    case ".h":
      return "c";
    case ".cpp":
    case ".hpp":
    case ".cc":
    case ".cxx":
      return "cpp";
    default:
      return "plaintext";
  }
}

function configureMonaco(monaco: Monaco): void {
  monaco.editor.defineTheme(EDITOR_THEME_DARK, {
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

  monaco.editor.defineTheme(EDITOR_THEME_LIGHT, {
    base: "vs",
    inherit: true,
    rules: [
      { token: "comment", foreground: "6B7280" },
      { token: "string", foreground: "0F766E" },
      { token: "keyword", foreground: "2563EB" },
      { token: "number", foreground: "B45309" },
      { token: "type", foreground: "7C3AED" },
    ],
    colors: {
      "editor.background": "#FFFFFF",
      "editor.foreground": "#111827",
      "editorLineNumber.foreground": "#9CA3AF",
      "editorLineNumber.activeForeground": "#4B5563",
      "editor.selectionBackground": "#BFDBFE",
      "editor.inactiveSelectionBackground": "#DBEAFE",
      "editor.lineHighlightBackground": "#F3F4F6",
      "editorIndentGuide.background1": "#E5E7EB",
      "editorIndentGuide.activeBackground1": "#14B8A6",
      "diffEditor.insertedTextBackground": "#DCFCE733",
      "diffEditor.removedTextBackground": "#FEE2E233",
      "diffEditor.insertedLineBackground": "#DCFCE722",
      "diffEditor.removedLineBackground": "#FEE2E222",
      "diffEditor.diagonalFill": "#F8FAFC",
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
  const { theme } = useTheme();
  const [markdownViewMode, setMarkdownViewMode] = useState<MarkdownViewMode>("rendered");
  const [wordWrapEnabled, setWordWrapEnabled] = useState(true);
  const [fontSize, setFontSize] = useState<12 | 13 | 14 | 15>(13);
  const editorLanguage = useMemo(() => (file ? inferEditorLanguage(file.path) : "plaintext"), [file]);
  const handleBeforeMount = useCallback((monaco: Monaco) => {
    configureMonaco(monaco);
  }, []);
  const canRenderTextDiff = Boolean(
    file &&
    diffFile &&
    diffOriginalText !== null &&
    preview?.text !== undefined &&
    (preview.kind === "text" || preview.kind === "markdown" || preview.kind === "mermaid"),
  );
  const canRenderMarkdownSource = preview?.kind === "markdown" || preview?.kind === "mermaid";
  const showDiffEditor = canRenderTextDiff && previewMode === "diff";
  const showRenderedMarkdown = canRenderMarkdownSource && markdownViewMode !== "source";
  const showMarkdownSource = !showDiffEditor && (preview?.kind === "text" || (canRenderMarkdownSource && markdownViewMode !== "rendered"));
  const wordWrap: EditorWordWrap = wordWrapEnabled ? "on" : "off";
  const editorTheme = theme === "light" ? EDITOR_THEME_LIGHT : EDITOR_THEME_DARK;
  const editorOptions = useMemo(() => ({
    ...EDITOR_OPTIONS,
    fontSize,
    wordWrap,
  }), [fontSize, wordWrap]);
  const diffEditorOptions = useMemo(() => ({
    ...DIFF_EDITOR_OPTIONS,
    fontSize,
    wordWrap,
  }), [fontSize, wordWrap]);

  useEffect(() => {
    setMarkdownViewMode("rendered");
  }, [file?.path]);

  return (
    <div className="flex min-h-[22rem] min-w-0 flex-1 flex-col bg-[linear-gradient(180deg,color-mix(in_oklab,var(--color-primary)_8%,transparent),transparent_10rem)] lg:min-h-0">
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
                {preview?.kind === "markdown" && (
                  <Badge variant="outline" className="px-1.5 py-0 text-[10px] normal-case text-sky-300">
                    markdown preview
                  </Badge>
                )}
                {preview?.kind === "mermaid" && (
                  <Badge variant="outline" className="px-1.5 py-0 text-[10px] normal-case text-cyan-300">
                    mermaid diagram
                  </Badge>
                )}
              </div>
            )}
          </div>
          {file && (
            <div className="flex flex-wrap items-center gap-1.5">
              {preview?.text && <CopyButton value={preview.text} className="h-8 w-8 rounded-md border border-border/70 bg-card/72" />}
              {canRenderMarkdownSource && !showDiffEditor && (
                <Button
                  type="button"
                  size="sm"
                  variant={markdownViewMode === "source" ? "secondary" : "outline"}
                  className="h-8 gap-1.5 px-3 text-[11px]"
                  onClick={() => setMarkdownViewMode("source")}
                >
                  <FileCode2 className="h-3.5 w-3.5" />
                  Raw source
                </Button>
              )}
              <Button type="button" size="sm" className="h-8 gap-1.5 px-3 text-[11px]" onClick={onDownload}>
                <Download className="h-3.5 w-3.5" />
                Download
              </Button>
            </div>
          )}
        </div>
        {file && (
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[11px] text-muted-foreground">
            <span>Last modified {formatModified(file.modified)}</span>
            <div className="flex flex-wrap items-center gap-2">
              {canRenderMarkdownSource && !showDiffEditor && (
                <div className="flex items-center gap-1 rounded-full border border-border/70 bg-muted/20 p-1">
                  <Button
                    type="button"
                    size="sm"
                    variant={markdownViewMode === "rendered" ? "secondary" : "ghost"}
                    className="h-6 gap-1 rounded-full px-2 text-[10px]"
                    onClick={() => setMarkdownViewMode("rendered")}
                  >
                    {preview?.kind === "mermaid" ? <Waypoints className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
                    {preview?.kind === "mermaid" ? "Diagram" : "Rendered"}
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant={markdownViewMode === "source" ? "secondary" : "ghost"}
                    className="h-6 gap-1 rounded-full px-2 text-[10px]"
                    onClick={() => setMarkdownViewMode("source")}
                  >
                    <FileCode2 className="h-3 w-3" />
                    Source
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant={markdownViewMode === "split" ? "secondary" : "ghost"}
                    className="h-6 gap-1 rounded-full px-2 text-[10px]"
                    onClick={() => setMarkdownViewMode("split")}
                  >
                    <FileDiff className="h-3 w-3" />
                    Split
                  </Button>
                </div>
              )}
              {!showDiffEditor && (preview?.kind === "text" || canRenderMarkdownSource) && (
                <div className="flex items-center gap-1 rounded-full border border-border/70 bg-muted/20 p-1">
                  <Button
                    type="button"
                    size="sm"
                    variant={wordWrapEnabled ? "secondary" : "ghost"}
                    className="h-6 gap-1 rounded-full px-2 text-[10px]"
                    onClick={() => setWordWrapEnabled((current) => !current)}
                  >
                    <WrapText className="h-3 w-3" />
                    Wrap
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    className="h-6 gap-1 rounded-full px-2 text-[10px]"
                    onClick={() => setFontSize((current) => current > 12 ? ((current - 1) as 12 | 13 | 14 | 15) : current)}
                    disabled={fontSize === 12}
                  >
                    <Type className="h-3 w-3" />
                    A-
                  </Button>
                  <Badge variant="outline" className="px-1.5 py-0 text-[10px] normal-case">
                    {fontSize}px
                  </Badge>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    className="h-6 gap-1 rounded-full px-2 text-[10px]"
                    onClick={() => setFontSize((current) => current < 15 ? ((current + 1) as 12 | 13 | 14 | 15) : current)}
                    disabled={fontSize === 15}
                  >
                    <Type className="h-3 w-3" />
                    A+
                  </Button>
                </div>
              )}
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
            options={diffEditorOptions}
            original={diffOriginalText ?? ""}
            originalLanguage={editorLanguage}
            originalModelPath={`original://${file.path}`}
            theme={editorTheme}
          />
        )}

        {file && !loading && !error && preview?.kind === "mermaid" && !showDiffEditor && showRenderedMarkdown && markdownViewMode !== "split" && (
          <ScrollArea className="h-full">
            <div className="px-5 py-4">
              <MermaidDiagram chart={preview.text ?? ""} />
            </div>
          </ScrollArea>
        )}

        {file && !loading && !error && preview?.kind === "markdown" && !showDiffEditor && showRenderedMarkdown && markdownViewMode !== "split" && (
          <ScrollArea className="h-full">
            <div className="px-5 py-4">
              <MarkdownRenderer content={preview.text ?? ""} />
            </div>
          </ScrollArea>
        )}

        {file && !loading && !error && canRenderMarkdownSource && markdownViewMode === "split" && !showDiffEditor && (
          <div className="grid h-full min-h-0 gap-0 lg:grid-cols-2">
            <div className="min-h-0 border-b border-border/60 lg:border-b-0 lg:border-r">
              <ScrollArea className="h-full">
                <div className="px-5 py-4">
                  {preview.kind === "mermaid"
                    ? <MermaidDiagram chart={preview.text ?? ""} />
                    : <MarkdownRenderer content={preview.text ?? ""} />}
                </div>
              </ScrollArea>
            </div>
            <div className="min-h-0">
              <Editor
                beforeMount={handleBeforeMount}
                height="100%"
                language={editorLanguage}
                loading={<div className="flex h-full items-center justify-center text-xs text-muted-foreground">Loading editor…</div>}
                options={editorOptions}
                path={file.path}
            theme={editorTheme}
            value={preview.text ?? ""}
          />
        </div>
          </div>
        )}

        {file && !loading && !error && showMarkdownSource && !showDiffEditor && (!canRenderMarkdownSource || markdownViewMode !== "split") && (
          <Editor
            beforeMount={handleBeforeMount}
            height="100%"
            language={editorLanguage}
            loading={<div className="flex h-full items-center justify-center text-xs text-muted-foreground">Loading editor…</div>}
            options={editorOptions}
            path={file.path}
            theme={editorTheme}
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
