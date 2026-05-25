import { useState, useCallback, useRef, useEffect } from "react";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import {
  Maximize2,
  Eye,
  Pencil,
  Columns2,
  Bold,
  Italic,
  Code2,
  Heading1,
  Heading2,
  List,
  ListOrdered,
  Link,
  Quote,
  Minus,
} from "lucide-react";

/* ---------- simple markdown-to-html renderer ---------- */

function renderMarkdown(src: string): string {
  if (!src) return '<p class="text-muted-foreground/50 italic">Nothing to preview</p>';

  let html = src
    // Escape HTML
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  // Fenced code blocks
  html = html.replace(
    /```(\w*)\n([\s\S]*?)```/g,
    (_m, lang, code) =>
      `<pre class="rounded-lg border border-border/60 bg-background/80 p-3 text-xs font-mono overflow-x-auto my-2"><code${lang ? ` data-lang="${lang}"` : ""}>${code.trimEnd()}</code></pre>`,
  );

  // Inline code
  html = html.replace(
    /`([^`\n]+)`/g,
    '<code class="rounded bg-primary/10 px-1 py-0.5 text-[0.85em] font-mono text-primary">$1</code>',
  );

  // Headings (must come before bold since # starts lines)
  html = html.replace(/^### (.+)$/gm, '<h3 class="text-sm font-semibold mt-4 mb-1">$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2 class="text-base font-semibold mt-4 mb-1">$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1 class="text-lg font-bold mt-4 mb-2">$1</h1>');

  // Horizontal rule
  html = html.replace(/^---$/gm, '<hr class="border-border/50 my-3" />');

  // Bold + italic
  html = html.replace(/\*\*\*(.+?)\*\*\*/g, "<strong><em>$1</em></strong>");
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*(.+?)\*/g, "<em>$1</em>");

  // Links (reject javascript: / data: / vbscript: protocols to prevent XSS)
  html = html.replace(
    /\[([^\]]+)\]\(([^)]+)\)/g,
    (_m: string, label: string, href: string) => {
      const normalized = href.replace(/[\s\x00-\x1f]/g, "").toLowerCase();
      if (/^(javascript|data|vbscript)\s*:/i.test(normalized)) {
        return `<span class="text-muted-foreground line-through">${label}</span>`;
      }
      return `<a class="text-primary underline underline-offset-2" href="${href}" target="_blank" rel="noopener noreferrer">${label}</a>`;
    },
  );

  // Blockquotes
  html = html.replace(
    /^&gt; (.+)$/gm,
    '<blockquote class="border-l-2 border-primary/40 pl-3 text-muted-foreground italic my-1">$1</blockquote>',
  );

  // Unordered lists
  html = html.replace(
    /^[\-\*] (.+)$/gm,
    '<li class="ml-4 list-disc text-sm">$1</li>',
  );

  // Ordered lists
  html = html.replace(
    /^\d+\. (.+)$/gm,
    '<li class="ml-4 list-decimal text-sm">$1</li>',
  );

  // Wrap consecutive <li> in <ul>/<ol>
  html = html.replace(
    /(<li class="ml-4 list-disc[^"]*">[\s\S]*?<\/li>(\n|$))+/g,
    (block) => `<ul class="my-1 space-y-0.5">${block}</ul>`,
  );
  html = html.replace(
    /(<li class="ml-4 list-decimal[^"]*">[\s\S]*?<\/li>(\n|$))+/g,
    (block) => `<ol class="my-1 space-y-0.5">${block}</ol>`,
  );

  // Paragraphs: wrap loose lines
  html = html
    .split("\n\n")
    .map((block) => {
      const trimmed = block.trim();
      if (!trimmed) return "";
      // Don't wrap blocks that are already wrapped in block-level elements
      if (/^<(h[1-6]|pre|ul|ol|blockquote|hr|div)/.test(trimmed)) return trimmed;
      return `<p class="my-1">${trimmed.replace(/\n/g, "<br />")}</p>`;
    })
    .join("\n");

  return html;
}

/* ---------- toolbar insert helpers ---------- */

interface InsertAction {
  icon: typeof Bold;
  label: string;
  prefix: string;
  suffix: string;
  block?: boolean;
}

const TOOLBAR_ACTIONS: InsertAction[] = [
  { icon: Bold, label: "Bold", prefix: "**", suffix: "**" },
  { icon: Italic, label: "Italic", prefix: "*", suffix: "*" },
  { icon: Code2, label: "Inline code", prefix: "`", suffix: "`" },
  { icon: Heading1, label: "Heading 1", prefix: "# ", suffix: "", block: true },
  { icon: Heading2, label: "Heading 2", prefix: "## ", suffix: "", block: true },
  { icon: List, label: "Bullet list", prefix: "- ", suffix: "", block: true },
  { icon: ListOrdered, label: "Numbered list", prefix: "1. ", suffix: "", block: true },
  { icon: Quote, label: "Blockquote", prefix: "> ", suffix: "", block: true },
  { icon: Link, label: "Link", prefix: "[", suffix: "](url)" },
  { icon: Minus, label: "Horizontal rule", prefix: "\n---\n", suffix: "", block: true },
];

/* ---------- component ---------- */

type ViewMode = "edit" | "preview" | "split";

interface ExpandableMarkdownEditorProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  label?: string;
  /** Initial textarea rows in compact mode */
  rows?: number;
  /** Extra className for the compact wrapper */
  className?: string;
  /** Extra className for the compact Textarea */
  textareaClassName?: string;
  /** Dialog title when expanded */
  dialogTitle?: string;
  /** Dialog description when expanded */
  dialogDescription?: string;
  /** If true, show a minimal inline variant (single-line until expanded) */
  compact?: boolean;
  /** Controlled open state — when provided, renders only the dialog (no inline textarea). */
  open?: boolean;
  /** Callback when controlled dialog is closed. */
  onOpenChange?: (open: boolean) => void;
}

export function ExpandableMarkdownEditor({
  value,
  onChange,
  placeholder,
  label,
  rows = 4,
  className,
  textareaClassName,
  dialogTitle = "Markdown Editor",
  dialogDescription,
  compact = false,
  open: controlledOpen,
  onOpenChange: controlledOnOpenChange,
}: ExpandableMarkdownEditorProps) {
  const [internalExpanded, setInternalExpanded] = useState(false);
  const isControlled = controlledOpen !== undefined;
  const expanded = isControlled ? controlledOpen : internalExpanded;
  const setExpanded = isControlled
    ? (v: boolean) => controlledOnOpenChange?.(v)
    : setInternalExpanded;
  const [viewMode, setViewMode] = useState<ViewMode>("edit");
  const editorRef = useRef<HTMLTextAreaElement>(null);

  // Auto-focus the expanded editor
  useEffect(() => {
    if (expanded && viewMode !== "preview") {
      requestAnimationFrame(() => editorRef.current?.focus());
    }
  }, [expanded, viewMode]);

  const insertAtCursor = useCallback(
    (action: InsertAction) => {
      const ta = editorRef.current;
      if (!ta) return;
      const start = ta.selectionStart;
      const end = ta.selectionEnd;
      const selected = value.slice(start, end);
      const replacement = action.block && start > 0 && value[start - 1] !== "\n"
        ? `\n${action.prefix}${selected || "text"}${action.suffix}`
        : `${action.prefix}${selected || "text"}${action.suffix}`;
      const updated = value.slice(0, start) + replacement + value.slice(end);
      onChange(updated);
      requestAnimationFrame(() => {
        const newPos = start + action.prefix.length + (action.block && start > 0 && value[start - 1] !== "\n" ? 1 : 0);
        const selectedLen = (selected || "text").length;
        ta.selectionStart = newPos;
        ta.selectionEnd = newPos + selectedLen;
        ta.focus();
      });
    },
    [value, onChange],
  );

  const wordCount = value.trim() ? value.trim().split(/\s+/).length : 0;
  const lineCount = value ? value.split("\n").length : 0;

  /* ---- controlled (dialog-only) mode ---- */
  if (isControlled) {
    return renderDialog();
  }

  /* ---- compact mode ---- */
  if (compact) {
    return (
      <>
        <div className={`relative group ${className ?? ""}`}>
          <Textarea
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder={placeholder}
            rows={rows}
            className={`pr-8 ${textareaClassName ?? ""}`}
          />
          <Button
            variant="ghost"
            size="icon"
            className="absolute top-1.5 right-1.5 h-6 w-6 opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity cursor-pointer"
            onClick={() => setExpanded(true)}
            title="Expand to full editor"
          >
            <Maximize2 className="h-3 w-3" />
          </Button>
        </div>
        {renderDialog()}
      </>
    );
  }

  /* ---- default mode with label ---- */
  return (
    <>
      <div className={`space-y-1.5 ${className ?? ""}`}>
        {label && (
          <div className="flex items-center justify-between">
            <Label className="text-xs">{label}</Label>
            <Button
              variant="ghost"
              size="sm"
              className="h-5 px-1.5 text-[10px] text-muted-foreground gap-1 cursor-pointer hover:text-foreground"
              onClick={() => setExpanded(true)}
              title="Expand to full markdown editor"
            >
              <Maximize2 className="h-3 w-3" />
              Expand
            </Button>
          </div>
        )}
        <div className="relative group">
          <Textarea
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder={placeholder}
            rows={rows}
            className={textareaClassName}
          />
          {!label && (
            <Button
              variant="ghost"
              size="icon"
              className="absolute top-1.5 right-1.5 h-6 w-6 opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity cursor-pointer"
              onClick={() => setExpanded(true)}
              title="Expand to full editor"
            >
              <Maximize2 className="h-3 w-3" />
            </Button>
          )}
        </div>
      </div>
      {renderDialog()}
    </>
  );

  /* ---- expanded dialog ---- */
  function renderDialog() {
    return (
      <Dialog open={expanded} onOpenChange={setExpanded}>
        <DialogContent className="max-w-5xl w-[95vw] h-[85vh] flex flex-col p-0 gap-0">
          {/* Header */}
          <div className="flex items-center justify-between px-5 pt-5 pb-3 border-b border-border/40">
            <DialogHeader className="space-y-0.5 flex-1">
              <DialogTitle className="text-sm font-semibold">
                {dialogTitle}
              </DialogTitle>
              {dialogDescription && (
                <DialogDescription className="text-[11px]">
                  {dialogDescription}
                </DialogDescription>
              )}
            </DialogHeader>

            {/* View mode toggle */}
            <div className="flex items-center gap-0.5 rounded-lg border border-border/50 bg-background/60 p-0.5">
              {([
                { mode: "edit" as ViewMode, icon: Pencil, tip: "Edit" },
                { mode: "split" as ViewMode, icon: Columns2, tip: "Split" },
                { mode: "preview" as ViewMode, icon: Eye, tip: "Preview" },
              ] as const).map(({ mode, icon: Icon, tip }) => (
                <Button
                  key={mode}
                  variant={viewMode === mode ? "secondary" : "ghost"}
                  size="icon"
                  className={`h-7 w-7 cursor-pointer ${viewMode === mode ? "bg-secondary" : ""}`}
                  onClick={() => setViewMode(mode)}
                  title={tip}
                >
                  <Icon className="h-3.5 w-3.5" />
                </Button>
              ))}
            </div>
          </div>

          {/* Formatting toolbar — visible in edit and split modes */}
          {viewMode !== "preview" && (
            <div className="flex items-center gap-0.5 px-5 py-1.5 border-b border-border/30 bg-background/40">
              {TOOLBAR_ACTIONS.map((action) => (
                <Button
                  key={action.label}
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 cursor-pointer"
                  onClick={() => insertAtCursor(action)}
                  title={action.label}
                >
                  <action.icon className="h-3.5 w-3.5" />
                </Button>
              ))}
              <div className="flex-1" />
              <div className="flex items-center gap-3 text-[10px] text-muted-foreground/60 font-mono select-none">
                <span>{lineCount} lines</span>
                <span>{wordCount} words</span>
                <span>{value.length} chars</span>
              </div>
            </div>
          )}

          {/* Editor body */}
          <div className="flex-1 flex min-h-0">
            {/* Edit pane */}
            {viewMode !== "preview" && (
              <div className={`flex-1 min-w-0 flex flex-col ${viewMode === "split" ? "border-r border-border/30" : ""}`}>
                {viewMode === "split" && (
                  <div className="px-3 py-1 text-[9px] text-muted-foreground/60 uppercase tracking-wider font-medium border-b border-border/20 select-none">
                    Markdown
                  </div>
                )}
                <textarea
                  ref={editorRef}
                  value={value}
                  onChange={(e) => onChange(e.target.value)}
                  placeholder={placeholder}
                  className="flex-1 w-full resize-none bg-transparent p-4 text-sm font-mono leading-relaxed placeholder:text-muted-foreground/40 focus:outline-none"
                  spellCheck
                />
              </div>
            )}

            {/* Preview pane */}
            {viewMode !== "edit" && (
              <div className={`flex-1 min-w-0 flex flex-col ${viewMode === "split" ? "" : ""}`}>
                {viewMode === "split" && (
                  <div className="px-3 py-1 text-[9px] text-muted-foreground/60 uppercase tracking-wider font-medium border-b border-border/20 select-none">
                    Preview
                  </div>
                )}
                <ScrollArea className="flex-1">
                  <div
                    className="p-4 text-sm leading-relaxed prose-invert max-w-none"
                    dangerouslySetInnerHTML={{ __html: renderMarkdown(value) }}
                  />
                </ScrollArea>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between px-5 py-2.5 border-t border-border/40 bg-background/40">
            <div className="flex items-center gap-2">
              <Badge variant="outline" className="text-[10px] font-mono">
                Markdown
              </Badge>
              {viewMode === "preview" && (
                <span className="text-[10px] text-muted-foreground/60 font-mono">
                  {wordCount} words · {value.length} chars
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-muted-foreground/50">
                Press Esc to close
              </span>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    );
  }
}
