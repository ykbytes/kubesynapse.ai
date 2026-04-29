import { useCallback, useEffect, useRef, useState } from "react";
import { Highlight, themes, type Language } from "prism-react-renderer";
import { Copy, Check, Info, AlertTriangle, Lightbulb, Settings, Bug } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { CodeBlockProps, CalloutProps, DocsTableProps, QuickRefCardProps, StepGuideProps, SectionHeadingProps } from "./types";

/* ── Custom Prism theme matching kubesynapse dark palette ── */
export const KubeSynapseTheme: typeof themes.nightOwl = {
  plain: {
    color: "#adbac7",
    backgroundColor: "transparent",
  },
  styles: [
    { types: ["comment", "prolog", "doctype", "cdata"], style: { color: "#768390", fontStyle: "italic" } },
    { types: ["namespace"], style: { opacity: 0.7 } },
    { types: ["string", "attr-value"], style: { color: "#96d0ff" } },
    { types: ["punctuation", "operator"], style: { color: "#768390" } },
    { types: ["entity", "url", "symbol", "number", "boolean", "variable", "constant", "property", "regex", "inserted"], style: { color: "#6cb6ff" } },
    { types: ["atrule", "keyword", "attr-name", "selector"], style: { color: "#f47067" } },
    { types: ["function", "deleted", "tag"], style: { color: "#dcbdfb" } },
    { types: ["function-variable"], style: { color: "#f69d50" } },
    { types: ["tag", "selector", "keyword"], style: { color: "#8ddb8c" } },
    { types: ["class-name", "maybe-class-name", "builtin"], style: { color: "#f69d50", fontWeight: "600" } },
    { types: ["important"], style: { color: "#f47067", fontWeight: "bold" } },
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
    <div className="group relative my-4 overflow-hidden rounded-xl border border-border/60 bg-slate-950 shadow-sm">
      <div className="flex items-center justify-between border-b border-white/10 px-3 py-1.5">
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-medium uppercase tracking-wider text-slate-400">{lang}</span>
          <span className="text-[11px] text-slate-600">|</span>
          <span className="text-[11px] text-slate-500">{lines.length} lines</span>
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 text-slate-400 hover:text-slate-100"
          onClick={handleCopy}
          aria-label={copied ? "Copied" : "Copy code"}
        >
          {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
        </Button>
      </div>
      <Highlight theme={KubeSynapseTheme} code={code.trimEnd()} language={language}>
        {({ className, style, tokens, getLineProps, getTokenProps }) => (
          <pre className={cn(className, "overflow-x-auto p-4 text-sm leading-relaxed")} style={{ ...style, margin: 0 }}>
            <code className="font-mono">
              {tokens.map((line, i) => {
                const lineProps = getLineProps({ line });
                return (
                  <div key={i} {...lineProps} className="table-row">
                    {showLineNumbers && (
                      <span className="table-cell select-none pr-4 text-right text-slate-600" style={{ minWidth: "2.5rem" }}>
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
    info: { icon: Info, container: "border-blue-500/20 bg-blue-500/10", title: "text-blue-300", iconColor: "text-blue-400" },
    warning: { icon: AlertTriangle, container: "border-amber-500/20 bg-amber-500/10", title: "text-amber-300", iconColor: "text-amber-400" },
    tip: { icon: Lightbulb, container: "border-emerald-500/20 bg-emerald-500/10", title: "text-emerald-300", iconColor: "text-emerald-400" },
    config: { icon: Settings, container: "border-purple-500/20 bg-purple-500/10", title: "text-purple-300", iconColor: "text-purple-400" },
    troubleshoot: { icon: Bug, container: "border-rose-500/20 bg-rose-500/10", title: "text-rose-300", iconColor: "text-rose-400" },
  };
  const v = variants[variant];
  const Icon = v.icon;

  return (
    <div className={cn("my-4 rounded-xl border px-4 py-3", v.container)}>
      <div className="flex items-start gap-3">
        <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", v.iconColor)} aria-hidden="true" />
        <div className="space-y-1">
          {title && <p className={cn("text-sm font-semibold", v.title)}>{title}</p>}
          <div className="text-sm leading-6 text-foreground/90">{children}</div>
        </div>
      </div>
    </div>
  );
}

/* ── DocsTable ── */
export function DocsTable({ headers, rows }: DocsTableProps) {
  return (
    <div className="my-4 overflow-hidden rounded-xl border border-border/60 shadow-sm">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-muted/80">
            <tr>
              {headers.map((h, i) => (
                <th key={i} className="px-3 py-2 text-left font-semibold text-foreground">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, ri) => (
              <tr key={ri} className={ri % 2 === 0 ? "bg-card/30" : ""}>
                {row.map((cell, ci) => (
                  <td key={ci} className="px-3 py-2 text-foreground/75">{cell}</td>
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
    <div className="rounded-xl border border-border/60 bg-card/30 p-3">
      <h3 className="mb-2 text-sm font-semibold text-foreground">{title}</h3>
      <div className="space-y-1">
        {items.map((item, i) => (
          <div key={i} className="flex items-center justify-between text-sm">
            <span className="text-foreground/75">{item.label}</span>
            <span className="font-mono font-medium text-foreground">{item.value}</span>
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
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-sm font-semibold text-primary">
            {i + 1}
          </div>
          <div className="min-w-0">
            <h4 className="mb-1 font-semibold text-foreground">{step.title}</h4>
            <div className="text-sm leading-6 text-muted-foreground">{step.children}</div>
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
    <div className={cn("flex items-center gap-2", level === 2 && "mb-3")}>
      {Icon && <Icon className="h-5 w-5 text-primary" aria-hidden="true" />}
      <Tag className={cn("font-semibold text-foreground", sizeClass)}>{children}</Tag>
    </div>
  );
}
