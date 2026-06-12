import { useState, useRef } from "react";
import { Copy, Download, FileText, ChevronDown, ChevronUp, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Highlight } from "prism-react-renderer";
import { KubeSynapseTheme } from "@/components/docs/shared";

interface ManifestViewerProps {
  manifest: Record<string, unknown> | string;
  resourceName?: string;
  resourceKind?: string;
  className?: string;
}

export function ManifestViewer({
  manifest,
  resourceName = "Resource",
  resourceKind = "Unknown",
  className,
}: ManifestViewerProps) {
  const [viewMode, setViewMode] = useState<"yaml" | "json">("yaml");
  const [isExpanded, setIsExpanded] = useState(false);
  const contentRef = useRef<HTMLDivElement>(null);

  const manifestStr =
    typeof manifest === "string" ? manifest : JSON.stringify(manifest, null, 2);

  const yamlStr = convertToYaml(manifestStr);
  const jsonStr = typeof manifest === "string" ? JSON.stringify(JSON.parse(manifest), null, 2) : JSON.stringify(manifest, null, 2);

  const displayStr = viewMode === "yaml" ? yamlStr : jsonStr;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(displayStr);
      toast.success("Manifest copied to clipboard");
    } catch {
      toast.error("Failed to copy manifest");
    }
  };

  const handleDownload = () => {
    const element = document.createElement("a");
    const file = new Blob([displayStr], { type: "text/plain" });
    element.href = URL.createObjectURL(file);
    element.download = `${resourceName}.${viewMode === "yaml" ? "yaml" : "json"}`;
    document.body.appendChild(element);
    element.click();
    document.body.removeChild(element);
    toast.success(`Manifest downloaded as ${element.download}`);
  };

  return (
    <Card className={cn("border-primary/20 bg-gradient-to-br from-primary/5 to-transparent", className)}>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FileText className="h-4 w-4 text-primary" />
            <div className="flex flex-col gap-1">
              <CardTitle className="text-sm font-semibold">Kubernetes Manifest</CardTitle>
              <CardDescription className="text-xs">
                {resourceKind} • {resourceName}
              </CardDescription>
            </div>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setIsExpanded(!isExpanded)}
            className="text-muted-foreground hover:text-foreground"
          >
            {isExpanded ? (
              <ChevronUp className="h-4 w-4" />
            ) : (
              <ChevronDown className="h-4 w-4" />
            )}
          </Button>
        </div>
      </CardHeader>

      {isExpanded && (
        <CardContent className="space-y-3">
          <div className="flex items-center justify-between gap-2">
            <Tabs value={viewMode} onValueChange={(v) => setViewMode(v as "yaml" | "json")} className="w-full">
              <TabsList className="grid w-full grid-cols-2">
                <TabsTrigger value="yaml">YAML</TabsTrigger>
                <TabsTrigger value="json">JSON</TabsTrigger>
              </TabsList>
            </Tabs>
          </div>

          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handleCopy}
              className="flex-1 gap-1"
            >
              <Copy className="h-3.5 w-3.5" />
              Copy
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handleDownload}
              className="flex-1 gap-1"
            >
              <Download className="h-3.5 w-3.5" />
              Download
            </Button>
          </div>

          <div
            ref={contentRef}
            className="relative max-h-96 overflow-auto rounded-lg border border-border/40 bg-black/5 dark:bg-black/30"
          >
            <Highlight code={displayStr} language={viewMode === "yaml" ? "yaml" : "json"} theme={KubeSynapseTheme}>
              {({ className: highlightClassName, style, tokens, getLineProps, getTokenProps }) => (
                <pre
                  className={cn(
                    highlightClassName,
                    "!bg-transparent !p-3 text-xs leading-relaxed [&_line]:py-0.5"
                  )}
                  style={style}
                >
                  {tokens.map((line, i) => (
                    <div key={i} {...getLineProps({ line, key: i })}>
                      <span className="mr-3 inline-block w-6 select-none text-right text-xs opacity-40">
                        {i + 1}
                      </span>
                      {line.map((token, k) => (
                        <span key={k} {...getTokenProps({ token, key: k })} />
                      ))}
                    </div>
                  ))}
                </pre>
              )}
            </Highlight>
          </div>

          <div className="flex items-start gap-2 rounded-lg border border-amber-200/30 bg-amber-50/50 p-2 dark:border-amber-900/30 dark:bg-amber-950/20">
            <AlertCircle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-amber-600 dark:text-amber-400" />
            <p className="text-xs text-amber-700 dark:text-amber-300">
              This manifest is read-only. To modify, use kubectl or your configuration management tool.
            </p>
          </div>
        </CardContent>
      )}
    </Card>
  );
}

// Simple JSON to YAML converter for display
function convertToYaml(jsonStr: string): string {
  try {
    const obj = JSON.parse(jsonStr);
    return jsonToYaml(obj);
  } catch {
    return jsonStr;
  }
}

function jsonToYaml(obj: unknown, indent = 0): string {
  const spaces = " ".repeat(indent);

  if (obj === null || obj === undefined) return "null";
  if (typeof obj === "boolean") return obj ? "true" : "false";
  if (typeof obj === "number") return String(obj);
  if (typeof obj === "string") {
    if (obj.includes("\n") || obj.includes(":") || obj.includes("#")) {
      return `|-\n${obj.split("\n").map((l) => `${spaces}  ${l}`).join("\n")}`;
    }
    return obj;
  }

  if (Array.isArray(obj)) {
    if (obj.length === 0) return "[]";
    return obj.map((item) => `${spaces}- ${jsonToYaml(item, indent + 2)}`).join("\n");
  }

  if (typeof obj === "object") {
    const lines: string[] = [];
    for (const [key, value] of Object.entries(obj as Record<string, unknown>)) {
      const valueStr = jsonToYaml(value, indent + 2);
      if (valueStr.includes("\n")) {
        lines.push(`${spaces}${key}:\n${spaces}  ${valueStr.split("\n").join(`\n${spaces}  `)}`);
      } else {
        lines.push(`${spaces}${key}: ${valueStr}`);
      }
    }
    return lines.join("\n");
  }

  return String(obj);
}
