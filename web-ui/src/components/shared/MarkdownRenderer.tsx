import { memo, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { CopyButton } from "./CopyButton";
import { MermaidDiagram } from "./MermaidDiagram";
import type { Components } from "react-markdown";

interface MarkdownRendererProps {
  content: string;
  className?: string;
}

/** Extract language from className like "language-python" → "python" */
function extractLang(className?: string): string | null {
  if (!className) return null;
  const match = className.match(/language-(\S+)/);
  return match ? match[1] : null;
}

const components: Components = {
  // Fenced code blocks: ```lang ... ```
  pre({ children }) {
    return <>{children}</>;
  },
  code({ className, children, ...props }) {
    const lang = extractLang(className);
    const codeString = String(children).replace(/\n$/, "");
    // Block code (has language class from rehype-highlight, or is inside pre)
    const isBlock = !!lang || (codeString.includes("\n"));
    if (isBlock) {
      if (lang === "mermaid") {
        return (
          <div className="group relative my-3 overflow-hidden rounded-xl border border-border/50 bg-card/70">
            <div className="flex items-center justify-between border-b border-border/30 bg-muted/40 px-4 py-1.5">
              <span className="text-[11px] font-medium text-muted-foreground/70 select-none">
                mermaid
              </span>
              <CopyButton value={codeString} className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity" />
            </div>
            <div className="p-4">
              <MermaidDiagram chart={codeString} className="my-0 border-0 bg-transparent p-0 shadow-none" />
            </div>
          </div>
        );
      }
      return (
        <div className="mk-code-block group relative my-3 overflow-hidden rounded-xl border border-border/50 bg-card/70">
          <div className="flex items-center justify-between border-b border-border/30 bg-muted/40 px-4 py-1.5">
            <span className="text-[11px] font-medium text-muted-foreground/70 select-none">
              {lang || "text"}
            </span>
            <CopyButton value={codeString} className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity" />
          </div>
          <div className="overflow-x-auto p-4">
            <code className={`${className ?? ""} text-[13px] leading-relaxed font-mono text-foreground/90`} {...props}>
              {children}
            </code>
          </div>
        </div>
      );
    }
    // Inline code
    return (
      <code className="mk-inline-code rounded-md bg-muted/80 border border-border/40 px-1.5 py-0.5 text-[13px] font-mono text-primary/90" {...props}>
        {children}
      </code>
    );
  },
  a({ href, children, ...props }) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="text-primary hover:text-primary/80 underline underline-offset-2 decoration-primary/30 hover:decoration-primary/60 transition-colors"
        {...props}
      >
        {children}
      </a>
    );
  },
  table({ children, ...props }) {
    return (
      <div className="my-3 overflow-x-auto rounded-lg border border-border/50">
        <table className="mk-table w-full text-sm" {...props}>{children}</table>
      </div>
    );
  },
  thead({ children, ...props }) {
    return <thead className="bg-muted/80 text-left text-xs font-semibold text-foreground/80" {...props}>{children}</thead>;
  },
  th({ children, ...props }) {
    return <th className="px-3 py-2 font-semibold" {...props}>{children}</th>;
  },
  td({ children, ...props }) {
    return <td className="border-t border-border/30 px-3 py-2 text-foreground/75" {...props}>{children}</td>;
  },
  blockquote({ children, ...props }) {
    return (
      <blockquote className="my-3 border-l-3 border-primary/40 bg-primary/5 pl-4 pr-3 py-2 text-muted-foreground italic rounded-r-lg" {...props}>
        {children}
      </blockquote>
    );
  },
  ul({ children, ...props }) {
    return <ul className="my-2 ml-1 list-none space-y-1" {...props}>{children}</ul>;
  },
  ol({ children, ...props }) {
    return <ol className="my-2 ml-1 list-none space-y-1 [counter-reset:md-ol]" {...props}>{children}</ol>;
  },
  li({ children, ...props }) {
    // @ts-expect-error ordered exists via parent context
    const isOrdered = props.node?.parentNode?.tagName === "ol" || props.ordered;
    return (
      <li
        className={`relative pl-6 leading-relaxed ${
          isOrdered
            ? "[counter-increment:md-ol] before:content-[counter(md-ol)_'.'] before:absolute before:left-0 before:text-muted-foreground/60 before:text-[13px] before:font-medium"
            : "before:content-[''] before:absolute before:left-1.5 before:top-[0.6em] before:h-1.5 before:w-1.5 before:rounded-full before:bg-primary/40"
        }`}
        {...props}
      >
        {children}
      </li>
    );
  },
  h1({ children, ...props }) {
    return <h1 className="mt-5 mb-3 text-xl font-bold tracking-tight" {...props}>{children}</h1>;
  },
  h2({ children, ...props }) {
    return <h2 className="mt-4 mb-2 text-lg font-semibold tracking-tight" {...props}>{children}</h2>;
  },
  h3({ children, ...props }) {
    return <h3 className="mt-3 mb-1.5 text-base font-semibold" {...props}>{children}</h3>;
  },
  h4({ children, ...props }) {
    return <h4 className="mt-2 mb-1 text-sm font-semibold" {...props}>{children}</h4>;
  },
  hr() {
    return <hr className="my-4 border-border/40" />;
  },
  p({ children, ...props }) {
    return <p className="my-2 leading-relaxed [&:first-child]:mt-0 [&:last-child]:mb-0" {...props}>{children}</p>;
  },
  strong({ children, ...props }) {
    return <strong className="font-semibold text-foreground" {...props}>{children}</strong>;
  },
  img({ src, alt, ...props }) {
    return <img src={src} alt={alt ?? ""} className="my-3 max-w-full rounded-lg border border-border/30" loading="lazy" {...props} />;
  },
};

const remarkPlugins = [remarkGfm];
const rehypePlugins = [rehypeHighlight];

export const MarkdownRenderer = memo(function MarkdownRenderer({ content, className }: MarkdownRendererProps) {
  // Memoize to avoid re-parsing identical content
  const trimmed = useMemo(() => content.trim(), [content]);

  if (!trimmed) return null;

  return (
    <div className={`markdown-body text-sm leading-relaxed ${className ?? ""}`}>
      <ReactMarkdown
        remarkPlugins={remarkPlugins}
        rehypePlugins={rehypePlugins}
        components={components}
      >
        {trimmed}
      </ReactMarkdown>
    </div>
  );
});
