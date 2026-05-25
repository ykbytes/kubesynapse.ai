import React, { useEffect, useRef, useState } from "react";
import mermaid from "mermaid";
import { Loader2 } from "lucide-react";

let mermaidInitialized = false;

function initMermaid() {
  if (mermaidInitialized) return;
  mermaid.initialize({
    startOnLoad: false,
    theme: "dark",
    securityLevel: "strict",
    fontFamily: "'IBM Plex Sans', ui-sans-serif, system-ui, sans-serif",
    darkMode: true,
    themeVariables: {
      primaryColor: "#2b2d35",
      primaryTextColor: "#f4f4f6",
      primaryBorderColor: "#4b4e5a",
      lineColor: "#8b8e97",
      secondaryColor: "#373942",
      tertiaryColor: "#32343c",
      fontFamily: "'IBM Plex Sans', ui-sans-serif, system-ui, sans-serif",
    },
  });
  mermaidInitialized = true;
}

interface MermaidDiagramProps {
  chart: string;
  className?: string;
}

export const MermaidDiagram: React.FC<MermaidDiagramProps> = ({ chart, className }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [svg, setSvg] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    initMermaid();
    let cancelled = false;

    async function render() {
      try {
        setLoading(true);
        setError(null);
        const id = `mermaid-${Math.random().toString(36).slice(2)}`;
        const { svg } = await mermaid.render(id, chart.trim());
        if (!cancelled) {
          setSvg(svg);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to render diagram");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    render();
    return () => {
      cancelled = true;
    };
  }, [chart]);

  return (
    <div
      className={`my-4 overflow-hidden rounded-xl border border-border/60 bg-card/40 p-3 shadow-sm sm:p-4 ${className ?? ""}`}
    >
      {loading && (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-hidden="true" />
          <span className="ml-2 text-sm text-muted-foreground">Rendering diagram…</span>
        </div>
      )}
      {error && (
        <div className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive">
          <strong>Diagram error:</strong> {error}
        </div>
      )}
      {!loading && !error && (
        <div className="overflow-x-auto">
          <div
            ref={containerRef}
            className="mermaid flex min-w-max justify-start [&>svg]:h-auto [&>svg]:max-w-none lg:justify-center"
            dangerouslySetInnerHTML={{ __html: svg }}
            aria-label="Mermaid diagram"
          />
        </div>
      )}
    </div>
  );
};

export default MermaidDiagram;
