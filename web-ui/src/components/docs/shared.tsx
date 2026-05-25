import { useCallback, useEffect, useRef, useState } from "react";
import { Highlight, themes, type Language } from "prism-react-renderer";
import { Copy, Check, Info, AlertTriangle, Lightbulb, Settings, Bug } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { CodeBlockProps, CalloutProps, DocsTableProps, QuickRefCardProps, StepGuideProps, SectionHeadingProps } from "./types";

/* ── Custom Prism theme matching kubesynapse dark palette ── */
export const KubeSynapseTheme: typeof themes.nightOwl = {
  plain: {
    color: "#d0d7de",
    backgroundColor: "transparent",
  },
  styles: [
    { types: ["comment", "prolog", "doctype", "cdata"], style: { color: "#8b949e", fontStyle: "italic" } },
    { types: ["namespace"], style: { opacity: 0.8 } },
    { types: ["string", "attr-value"], style: { color: "#a5d6ff" } },
    { types: ["punctuation", "operator"], style: { color: "#8b949e" } },
    { types: ["entity", "url", "symbol", "number", "boolean", "variable", "constant", "property", "regex", "inserted"], style: { color: "#79c0ff" } },
    { types: ["atrule", "keyword", "attr-name", "selector"], style: { color: "#ff7b72" } },
    { types: ["function", "deleted", "tag"], style: { color: "#d2a8ff" } },
    { types: ["function-variable"], style: { color: "#ffa657" } },
    { types: ["tag", "selector", "keyword"], style: { color: "#7ee787" } },
    { types: ["class-name", "maybe-class-name", "builtin"], style: { color: "#ffa657", fontWeight: "600" } },
    { types: ["important"], style: { color: "#ff7b72", fontWeight: "bold" } },
    { types: ["bold"], style: { fontWeight: "bold" } },
    { types: ["italic"], style: { fontStyle: "italic" } },
  ],
};

/* ── CodeBlock ── */
export function CodeBlock({ code, lang = "bash", showLineNumbers = true }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    return () => clearTimeout(timerRef.current);
  }, []);

  const handleCopy = useCallback(async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setCopied(false), 1500);
  }, [code]);

  const language = (lang === "yaml" || lang === "yml" ? "yaml" : lang === "json" ? "json" : lang === "bash" || lang === "shell" || lang === "sh" ? "bash" : "text") as Language;
  const lines = code.split("\n");

  return (
    <div className="group relative my-5 max-w-full overflow-hidden rounded-lg border border-border bg-[oklch(0.11_0.005_264)]">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/60 px-3 py-2 sm:px-4">
        <div className="flex flex-wrap items-center gap-2.5">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-foreground">{lang}</span>
          <span className="text-[11px] text-border">|</span>
          <span className="text-[11px] text-foreground">{lines.length} lines</span>
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 text-foreground/70 hover:text-foreground"
          onClick={handleCopy}
          aria-label={copied ? "Copied" : "Copy code"}
        >
          {copied ? <Check className="h-3.5 w-3.5 text-success" /> : <Copy className="h-3.5 w-3.5" />}
        </Button>
      </div>
      <Highlight theme={KubeSynapseTheme} code={code.trimEnd()} language={language}>
        {({ className, style, tokens, getLineProps, getTokenProps }) => (
          <pre className={cn(className, "max-w-full overflow-x-auto p-3 text-[12px] leading-6 sm:p-4 sm:text-[13px] sm:leading-7")} style={{ ...style, margin: 0 }}>
            <code className="font-mono">
              {tokens.map((line, i) => {
                const lineProps = getLineProps({ line });
                return (
                  <div key={i} {...lineProps} className="table-row">
                    {showLineNumbers && (
                      <span className="hidden select-none pr-4 text-right text-foreground/80 sm:table-cell" style={{ minWidth: "2.5rem" }}>
                        {i + 1}
                      </span>
                    )}
                    <span className="table-cell min-w-0">
                      {line.map((token, key) => (
                        <span key={key} {...getTokenProps({ token })} />
                      ))}
                    </span>
                  </div>
                );
              })}
            </code>
          </pre>
        )}
      </Highlight>
    </div>
  );
}

/* ── Callout ── */
export function Callout({ children, variant = "info", title }: CalloutProps) {
  const variants = {
    info: { icon: Info, bg: "bg-info/8", border: "border-l-info", iconColor: "text-info", titleColor: "text-info" },
    warning: { icon: AlertTriangle, bg: "bg-warning/8", border: "border-l-warning", iconColor: "text-warning", titleColor: "text-warning" },
    tip: { icon: Lightbulb, bg: "bg-success/8", border: "border-l-success", iconColor: "text-success", titleColor: "text-success" },
    config: { icon: Settings, bg: "bg-[oklch(0.684_0.138_308/0.08)]", border: "border-l-[oklch(0.684_0.138_308)]", iconColor: "text-[oklch(0.684_0.138_308)]", titleColor: "text-[oklch(0.76_0.10_308)]" },
    troubleshoot: { icon: Bug, bg: "bg-destructive/8", border: "border-l-destructive", iconColor: "text-destructive", titleColor: "text-destructive" },
  };
  const v = variants[variant];
  const Icon = v.icon;

  return (
    <div className={cn("my-5 rounded-r-lg border-l-[3px] px-4 py-3.5 sm:px-5 sm:py-4", v.bg, v.border)}>
      <div className="flex items-start gap-3">
        <Icon className={cn("mt-0.5 h-5 w-5 shrink-0", v.iconColor)} aria-hidden="true" />
        <div className="min-w-0 space-y-1.5">
          {title && <p className={cn("text-sm font-bold", v.titleColor)}>{title}</p>}
          <div className="text-sm leading-6 text-foreground sm:leading-7">{children}</div>
        </div>
      </div>
    </div>
  );
}

/* ── DocsTable ── */
export function DocsTable({ headers, rows }: DocsTableProps) {
  return (
    <div className="my-5 max-w-full">
      <div className="space-y-3 sm:hidden">
        {rows.map((row, ri) => (
          <div key={ri} className="overflow-hidden rounded-lg border border-border bg-card/60">
            {row.map((cell, ci) => (
              <div
                key={ci}
                className={cn(
                  "grid grid-cols-[6.5rem_minmax(0,1fr)] gap-3 px-3 py-2.5",
                  ci > 0 && "border-t border-border/60",
                )}
              >
                <span className="text-[10px] font-bold uppercase tracking-wider text-foreground">
                  {headers[ci]}
                </span>
                <span className={cn("min-w-0 break-words text-xs", ci === 0 ? "font-medium text-foreground" : "text-foreground")}>
                  {cell}
                </span>
              </div>
            ))}
          </div>
        ))}
      </div>

      <div className="hidden overflow-hidden rounded-lg border border-border sm:block">
        <div className="max-w-full overflow-x-auto">
          <table className="w-full min-w-[34rem] text-sm">
            <thead>
              <tr className="border-b-2 border-border bg-card">
                {headers.map((h, i) => (
                  <th key={i} className="whitespace-nowrap px-4 py-3 text-left text-xs font-bold uppercase tracking-wider text-foreground">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, ri) => (
                <tr key={ri} className={cn(
                  "border-b border-border/60 transition-colors hover:bg-muted/50",
                  ri % 2 === 1 && "bg-card/50"
                )}>
                  {row.map((cell, ci) => (
                    <td key={ci} className={cn(
                      "align-top break-words px-4 py-3",
                      ci === 0 ? "font-medium text-foreground" : "text-foreground"
                    )}>{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

/* ── QuickRefCard ── */
export function QuickRefCard({ title, items }: QuickRefCardProps) {
  return (
    <div className="rounded-lg border border-border bg-card p-4 sm:p-5">
      <h3 className="mb-3 text-sm font-bold text-foreground sm:mb-4">{title}</h3>
      <div className="space-y-3">
        {items.map((item, i) => (
          <div key={i} className="flex flex-col items-start gap-1 sm:flex-row sm:items-center sm:justify-between">
            <span className="text-sm text-foreground">{item.label}</span>
            <code className="block w-full max-w-full break-all whitespace-normal rounded-md bg-muted px-2.5 py-1 font-mono text-xs font-semibold text-foreground sm:w-auto sm:overflow-x-auto sm:whitespace-nowrap sm:break-normal">{item.value}</code>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── StepGuide ── */
export function StepGuide({ steps }: StepGuideProps) {
  return (
    <div className="space-y-5 sm:space-y-6">
      {steps.map((step, i) => (
        <div key={i} className="flex gap-3 sm:gap-4">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/15 text-xs font-bold text-primary sm:h-8 sm:w-8 sm:text-sm">
            {i + 1}
          </div>
          <div className="min-w-0">
            <h4 className="mb-1.5 font-bold text-foreground">{step.title}</h4>
            <div className="text-sm leading-7 text-foreground">{step.children}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

/* ── SectionHeading ── */
export function SectionHeading({ icon: Icon, children, level = 3 }: SectionHeadingProps) {
  const Tag = `h${level}` as const;
  const sizeClass = level === 2 ? "text-lg sm:text-xl" : level === 3 ? "text-base sm:text-lg" : "text-sm sm:text-base";
  return (
    <div className={cn("flex flex-wrap items-center gap-2", level === 2 && "mb-4")}>
      {Icon && <Icon className="h-4 w-4 text-primary sm:h-5 sm:w-5" aria-hidden="true" />}
      <Tag className={cn("font-bold text-foreground", sizeClass)}>{children}</Tag>
    </div>
  );
}
