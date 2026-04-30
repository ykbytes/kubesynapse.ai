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
    <div className="group relative my-5 overflow-hidden rounded-lg border border-border bg-[oklch(0.11_0.005_264)]">
      <div className="flex items-center justify-between border-b border-border/60 px-4 py-2">
        <div className="flex items-center gap-2.5">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/70">{lang}</span>
          <span className="text-[11px] text-border">|</span>
          <span className="text-[11px] text-muted-foreground/60">{lines.length} lines</span>
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 text-muted-foreground/60 hover:text-foreground"
          onClick={handleCopy}
          aria-label={copied ? "Copied" : "Copy code"}
        >
          {copied ? <Check className="h-3.5 w-3.5 text-success" /> : <Copy className="h-3.5 w-3.5" />}
        </Button>
      </div>
      <Highlight theme={KubeSynapseTheme} code={code.trimEnd()} language={language}>
        {({ className, style, tokens, getLineProps, getTokenProps }) => (
          <pre className={cn(className, "overflow-x-auto p-4 text-[13px] leading-7")} style={{ ...style, margin: 0 }}>
            <code className="font-mono">
              {tokens.map((line, i) => {
                const lineProps = getLineProps({ line });
                return (
                  <div key={i} {...lineProps} className="table-row">
                    {showLineNumbers && (
                      <span className="table-cell select-none pr-4 text-right text-muted-foreground/40" style={{ minWidth: "2.5rem" }}>
                        {i + 1}
                      </span>
                    )}
                    <span className="table-cell">
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
    <div className={cn("my-5 rounded-r-lg border-l-[3px] px-5 py-4", v.bg, v.border)}>
      <div className="flex items-start gap-3">
        <Icon className={cn("mt-0.5 h-5 w-5 shrink-0", v.iconColor)} aria-hidden="true" />
        <div className="space-y-1.5">
          {title && <p className={cn("text-sm font-bold", v.titleColor)}>{title}</p>}
          <div className="text-sm leading-7 text-foreground/85">{children}</div>
        </div>
      </div>
    </div>
  );
}

/* ── DocsTable ── */
export function DocsTable({ headers, rows }: DocsTableProps) {
  return (
    <div className="my-5 overflow-hidden rounded-lg border border-border">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b-2 border-border bg-card">
              {headers.map((h, i) => (
                <th key={i} className="px-4 py-3 text-left text-xs font-bold uppercase tracking-wider text-muted-foreground">{h}</th>
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
                    "px-4 py-3",
                    ci === 0 ? "font-medium text-foreground" : "text-foreground/80"
                  )}>{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ── QuickRefCard ── */
export function QuickRefCard({ title, items }: QuickRefCardProps) {
  return (
    <div className="rounded-lg border border-border bg-card p-5">
      <h3 className="mb-4 text-sm font-bold text-foreground">{title}</h3>
      <div className="space-y-3">
        {items.map((item, i) => (
          <div key={i} className="flex items-center justify-between">
            <span className="text-sm text-muted-foreground">{item.label}</span>
            <code className="rounded-md bg-muted px-2.5 py-1 font-mono text-xs font-semibold text-foreground">{item.value}</code>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── StepGuide ── */
export function StepGuide({ steps }: StepGuideProps) {
  return (
    <div className="space-y-6">
      {steps.map((step, i) => (
        <div key={i} className="flex gap-4">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/15 text-sm font-bold text-primary">
            {i + 1}
          </div>
          <div className="min-w-0">
            <h4 className="mb-1.5 font-bold text-foreground">{step.title}</h4>
            <div className="text-sm leading-7 text-muted-foreground">{step.children}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

/* ── SectionHeading ── */
export function SectionHeading({ icon: Icon, children, level = 3 }: SectionHeadingProps) {
  const Tag = `h${level}` as const;
  const sizeClass = level === 2 ? "text-xl" : level === 3 ? "text-lg" : "text-base";
  return (
    <div className={cn("flex items-center gap-2.5", level === 2 && "mb-4")}>
      {Icon && <Icon className="h-5 w-5 text-primary" aria-hidden="true" />}
      <Tag className={cn("font-bold text-foreground", sizeClass)}>{children}</Tag>
    </div>
  );
}
