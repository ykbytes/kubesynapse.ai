import { useRef, useMemo } from "react";
import {
  type ComposerNode,
  type AgentStepNodeData,
  TRIGGER_NODE_ID,
} from "@/lib/composer-utils";
import type { AgentInfo } from "@/types";
import type { Edge } from "@xyflow/react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  UserCheck,
  Repeat,
  MousePointerClick,
  Settings,
  Activity,
  GitBranch,
  ArrowUp,
  ArrowDown,
  Clock,
  Copy,
  AlertTriangle,
  PanelRightClose,
  PanelRightOpen,
  Info,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import {
  extractPlaceholders,
  validatePlaceholders,
  getTransitiveUpstream,
  availablePlaceholders,
} from "@/lib/template-utils";

interface PropertiesPanelProps {
  selectedNode: ComposerNode | null;
  agents: AgentInfo[];
  edges: Edge[];
  nodes: ComposerNode[];
  collapsed: boolean;
  onToggleCollapse: () => void;
  onNodeDataChange: (nodeId: string, patch: Partial<AgentStepNodeData>) => void;
  onSelectNode?: (nodeId: string) => void;
}

/* ── Config Tab ── */

function ConfigTab({
  node,
  data,
  agents,
  edges,
  onNodeDataChange,
}: {
  node: ComposerNode;
  data: AgentStepNodeData;
  agents: AgentInfo[];
  edges: Edge[];
  onNodeDataChange: (nodeId: string, patch: Partial<AgentStepNodeData>) => void;
}) {
  const promptRef = useRef<HTMLTextAreaElement>(null);
  const backdropRef = useRef<HTMLDivElement>(null);

  // Compute upstream steps for this node
  const upstreamSteps = useMemo(
    () => getTransitiveUpstream(node.id, edges, TRIGGER_NODE_ID),
    [node.id, edges],
  );

  // Build available placeholder chips
  const chips = useMemo(
    () => availablePlaceholders(upstreamSteps),
    [upstreamSteps],
  );

  // Validate placeholders in the current prompt
  const validationResults = useMemo(() => {
    const phs = extractPlaceholders(data.prompt);
    return validatePlaceholders(phs, upstreamSteps);
  }, [data.prompt, upstreamSteps]);

  const invalidResults = validationResults.filter((r) => !r.valid);

  // Build highlighted backdrop HTML
  const highlightedHtml = useMemo(() => {
    const text = data.prompt;
    if (!text) return "";
    // Escape HTML, then wrap {{ ... }} in styled spans
    const escaped = text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
    return escaped.replace(
      /\{\{\s*([^{}]+?)\s*\}\}/g,
      (match) => {
        // Check if this placeholder is invalid
        const expr = match.replace(/^\{\{\s*/, "").replace(/\s*\}\}$/, "");
        const isInvalid = invalidResults.some((r) => r.expression === expr);
        const cls = isInvalid
          ? "bg-red-500/20 text-red-400 rounded px-0.5"
          : "bg-primary/15 text-primary rounded px-0.5";
        return `<span class="${cls}">${match}</span>`;
      },
    );
  }, [data.prompt, invalidResults]);

  // Sync scroll between textarea and backdrop
  const handleScroll = () => {
    if (backdropRef.current && promptRef.current) {
      backdropRef.current.scrollTop = promptRef.current.scrollTop;
      backdropRef.current.scrollLeft = promptRef.current.scrollLeft;
    }
  };

  // Insert placeholder at cursor position
  const insertPlaceholder = (text: string) => {
    const textarea = promptRef.current;
    if (!textarea) {
      onNodeDataChange(node.id, { prompt: data.prompt + text });
      return;
    }
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const before = data.prompt.slice(0, start);
    const after = data.prompt.slice(end);
    onNodeDataChange(node.id, { prompt: before + text + after });
    // Restore cursor after the inserted text
    requestAnimationFrame(() => {
      textarea.selectionStart = textarea.selectionEnd = start + text.length;
      textarea.focus();
    });
  };
  return (
    <div className="p-3 space-y-3">
      {/* Step Name */}
      <div className="space-y-1">
        <Label className="text-[10px]">Step Name</Label>
        <Input
          value={data.stepName}
          onChange={(e) => onNodeDataChange(node.id, { stepName: e.target.value })}
          className="h-7 text-xs"
        />
      </div>

      {/* Agent */}
      <div className="space-y-1">
        <Label className="text-[10px]">Agent</Label>
        <Select
          value={data.agentRef}
          onValueChange={(v) => {
            const agent = agents.find((a) => a.name === v);
            onNodeDataChange(node.id, {
              agentRef: v,
              runtimeKind: agent?.runtime_kind ?? null,
            });
          }}
        >
          <SelectTrigger className="h-7 text-xs">
            <SelectValue placeholder="Select agent" />
          </SelectTrigger>
          <SelectContent>
            {agents.map((a) => (
              <SelectItem key={a.name} value={a.name}>
                <span className="flex items-center gap-2">
                  {a.name}
                  {a.runtime_kind && (
                    <span className="text-[9px] text-muted-foreground font-mono">{a.runtime_kind}</span>
                  )}
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Prompt */}
      <div className="space-y-1">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1">
            <Label className="text-[10px]">Prompt</Label>
            <Popover>
              <PopoverTrigger asChild>
                <button
                  type="button"
                  className="text-muted-foreground/50 hover:text-muted-foreground transition-colors cursor-pointer"
                  title="Available template variables"
                >
                  <Info className="h-3 w-3" />
                </button>
              </PopoverTrigger>
              <PopoverContent side="left" className="w-64 text-xs space-y-2">
                <p className="font-semibold text-[11px]">Template Variables</p>
                <p className="text-muted-foreground text-[10px] leading-relaxed">
                  Use <code className="font-mono text-primary bg-primary/10 rounded px-1">{`{{variable}}`}</code> placeholders in your prompt. They are resolved at runtime by the operator.
                </p>
                <div className="space-y-1.5 pt-1">
                  <div className="flex items-start gap-2">
                    <code className="font-mono text-[9px] text-primary bg-primary/10 rounded px-1 shrink-0 mt-0.5">{`{{input}}`}</code>
                    <span className="text-[10px] text-muted-foreground">Workflow input (from toolbar or trigger dialog)</span>
                  </div>
                  <div className="flex items-start gap-2">
                    <code className="font-mono text-[9px] text-primary bg-primary/10 rounded px-1 shrink-0 mt-0.5">{`{{previous_output}}`}</code>
                    <span className="text-[10px] text-muted-foreground">Output of the preceding step</span>
                  </div>
                  {upstreamSteps.length > 0 && (
                    <>
                      <div className="border-t border-border/50 my-1.5" />
                      <p className="text-[9px] font-medium text-muted-foreground uppercase tracking-wider">Upstream Steps</p>
                      {upstreamSteps.map((s) => (
                        <div key={s} className="flex items-start gap-2">
                          <code className="font-mono text-[9px] text-primary bg-primary/10 rounded px-1 shrink-0 mt-0.5">{`{{${s}.output}}`}</code>
                          <span className="text-[10px] text-muted-foreground">Output of &ldquo;{s}&rdquo;</span>
                        </div>
                      ))}
                    </>
                  )}
                </div>
              </PopoverContent>
            </Popover>
          </div>
          <span className="text-[9px] text-muted-foreground/60">{data.prompt.length} chars</span>
        </div>

        {/* Syntax-highlighted prompt editor (overlay technique) */}
        <div className="relative">
          {/* Backdrop with highlighted tokens */}
          <div
            ref={backdropRef}
            className="absolute inset-0 text-xs min-h-[60px] p-2 font-sans whitespace-pre-wrap break-words overflow-hidden pointer-events-none border border-transparent rounded-md leading-[1.625]"
            aria-hidden="true"
            dangerouslySetInnerHTML={{ __html: highlightedHtml + "\n" }}
          />
          {/* Transparent textarea on top */}
          <Textarea
            ref={promptRef}
            value={data.prompt}
            onChange={(e) => onNodeDataChange(node.id, { prompt: e.target.value })}
            onScroll={handleScroll}
            className="text-xs min-h-[60px] resize-y bg-transparent! caret-foreground relative z-[1]"
            style={{ color: "transparent", WebkitTextFillColor: "transparent" }}
            rows={3}
          />
        </div>

        {/* Validation warnings */}
        {invalidResults.length > 0 && (
          <div className="space-y-0.5">
            {invalidResults.map((r, i) => (
              <div key={i} className="flex items-start gap-1 text-[9px] text-amber-400">
                <AlertTriangle className="h-3 w-3 shrink-0 mt-px" />
                <span>
                  <code className="font-mono bg-amber-500/10 rounded px-0.5">{`{{${r.expression}}}`}</code>{" "}
                  {r.reason}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Placeholder chips */}
        <div className="flex flex-wrap gap-1 pt-0.5">
          {chips.map((c) => (
            <button
              key={c.insert}
              type="button"
              onClick={() => insertPlaceholder(c.insert)}
              className="inline-flex items-center gap-0.5 rounded-full border border-primary/20 bg-primary/5 px-1.5 py-0.5 text-[9px] font-mono text-primary hover:bg-primary/15 transition-colors cursor-pointer"
              title={c.description}
            >
              {c.label}
            </button>
          ))}
        </div>
      </div>

      {/* Require Approval toggle */}
      <Button
        variant={data.requireApproval ? "secondary" : "outline"}
        size="sm"
        className="h-7 text-xs gap-1.5 w-full justify-start cursor-pointer"
        onClick={() => onNodeDataChange(node.id, { requireApproval: !data.requireApproval })}
      >
        <UserCheck className="h-3 w-3" />
        {data.requireApproval ? "Approval Required" : "No Approval"}
      </Button>

      {/* Step Type */}
      <div className="space-y-1">
        <Label className="text-[10px]">Step Type</Label>
        <Select
          value={data.stepType}
          onValueChange={(v) =>
            onNodeDataChange(node.id, { stepType: v as "agent" | "loop" | "conditional" })
          }
        >
          <SelectTrigger className="h-7 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="agent">Agent</SelectItem>
            <SelectItem value="loop">
              <span className="flex items-center gap-1.5">
                <Repeat className="h-3 w-3" /> Loop
              </span>
            </SelectItem>
            <SelectItem value="conditional">
              <span className="flex items-center gap-1.5">
                <GitBranch className="h-3 w-3" /> Conditional
              </span>
            </SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Loop Configuration */}
      {data.stepType === "loop" && (
        <div className="space-y-2 border rounded-md p-2 bg-blue-500/10">
          <Label className="text-[10px] text-blue-500 font-semibold">Loop Config</Label>
          <div className="space-y-1">
            <Label className="text-[10px]">Max Iterations</Label>
            <Input
              type="number"
              min={1}
              max={10000}
              value={data.loopConfig?.maxIterations ?? ""}
              onChange={(e) => {
                const raw = e.target.value;
                if (!raw) {
                  onNodeDataChange(node.id, {
                    loopConfig: { ...data.loopConfig, maxIterations: undefined },
                  });
                  return;
                }
                const val = parseInt(raw, 10);
                if (isNaN(val) || val < 1) return;
                onNodeDataChange(node.id, {
                  loopConfig: { ...data.loopConfig, maxIterations: Math.min(val, 10000) },
                });
              }}
              placeholder="e.g. 10"
              className="h-7 text-xs"
            />
          </div>
          <div className="space-y-1">
            <Label className="text-[10px]">Plan Source</Label>
            <Select
              value={data.loopConfig?.planSource ?? "prompt"}
              onValueChange={(v) =>
                onNodeDataChange(node.id, {
                  loopConfig: { ...data.loopConfig, planSource: v as "inline" | "prompt" },
                })
              }
            >
              <SelectTrigger className="h-7 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="prompt">Prompt</SelectItem>
                <SelectItem value="inline">Inline</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {data.loopConfig?.planSource === "inline" && (
            <div className="space-y-1">
              <Label className="text-[10px]">Plan</Label>
              <Textarea
                value={data.loopConfig?.plan ?? ""}
                onChange={(e) =>
                  onNodeDataChange(node.id, {
                    loopConfig: { ...data.loopConfig, plan: e.target.value },
                  })
                }
                className="text-xs min-h-[40px]"
                rows={2}
                placeholder="Inline plan..."
              />
            </div>
          )}
        </div>
      )}

      {/* Conditional Configuration */}
      {data.stepType === "conditional" && (
        <div className="space-y-2 border rounded-md p-2 bg-purple-500/10">
          <Label className="text-[10px] text-purple-500 font-semibold">Conditional Config</Label>
          <div className="space-y-1">
            <Label className="text-[10px]">Condition Expression</Label>
            <Input
              value={data.conditionExpr ?? ""}
              onChange={(e) => onNodeDataChange(node.id, { conditionExpr: e.target.value })}
              className="h-7 text-xs font-mono"
              placeholder='e.g. contains("success")'
            />
            <p className="text-[9px] text-muted-foreground/60 leading-tight">
              Operators: contains, equals, not_equals, starts_with, ends_with, length_gt, length_lt, is_empty, not_empty, matches. Combine with and/or/not.
            </p>
          </div>
          <div className="space-y-1">
            <Label className="text-[10px]">Then Steps (comma-separated)</Label>
            <Input
              value={(data.thenSteps ?? []).join(", ")}
              onChange={(e) => {
                const steps = e.target.value.split(",").map((s) => s.trim()).filter(Boolean);
                onNodeDataChange(node.id, { thenSteps: steps.length ? steps : null });
              }}
              className="h-7 text-xs"
              placeholder="step-a, step-b"
            />
          </div>
          <div className="space-y-1">
            <Label className="text-[10px]">Else Steps (comma-separated)</Label>
            <Input
              value={(data.elseSteps ?? []).join(", ")}
              onChange={(e) => {
                const steps = e.target.value.split(",").map((s) => s.trim()).filter(Boolean);
                onNodeDataChange(node.id, { elseSteps: steps.length ? steps : null });
              }}
              className="h-7 text-xs"
              placeholder="step-c, step-d"
            />
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Execution Tab ── */

function ExecutionTab({ data }: { data: AgentStepNodeData }) {
  const state = data.stepState;
  if (!state?.status) {
    return (
      <div className="flex flex-col items-center justify-center py-8 text-center text-muted-foreground/60">
        <Activity className="h-5 w-5 mb-2" />
        <p className="text-[10px]">No execution data yet.</p>
        <p className="text-[10px]">Run the workflow to see step progress here.</p>
      </div>
    );
  }

  const statusMap: Record<string, string> = {
    completed: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20",
    running: "text-amber-400 bg-amber-500/10 border-amber-500/20",
    failed: "text-red-400 bg-red-500/10 border-red-500/20",
    waiting_approval: "text-orange-400 bg-orange-500/10 border-orange-500/20",
  };

  const copyError = () => {
    if (state.error) {
      navigator.clipboard.writeText(state.error);
      toast.success("Error copied to clipboard");
    }
  };

  return (
    <div className="p-3 space-y-3">
      {/* Status badge */}
      <div className="flex items-center gap-2">
        <span className={cn("rounded-full border px-2 py-1 text-xs font-medium", statusMap[state.status] ?? "text-muted-foreground bg-muted/50")}>
          {state.status}
        </span>
        {state.attempts != null && state.attempts > 1 && (
          <span className="text-[10px] text-muted-foreground">attempt {state.attempts}</span>
        )}
      </div>

      {/* Timing */}
      <div className="space-y-1.5 text-[10px]">
        {state.startedAt && (
          <div className="flex items-center gap-1.5 text-muted-foreground">
            <Clock className="h-3 w-3 shrink-0" />
            <span>Started: <span className="font-mono">{new Date(state.startedAt).toLocaleTimeString()}</span></span>
          </div>
        )}
        {state.completedAt && (
          <div className="flex items-center gap-1.5 text-muted-foreground">
            <Clock className="h-3 w-3 shrink-0" />
            <span>Completed: <span className="font-mono">{new Date(state.completedAt).toLocaleTimeString()}</span></span>
          </div>
        )}
        {state.latencyMs != null && (
          <div className="flex items-center gap-1.5 text-muted-foreground">
            <Clock className="h-3 w-3 shrink-0" />
            <span>Latency: <span className="font-mono font-medium text-foreground/80">{state.latencyMs < 1000 ? `${state.latencyMs}ms` : `${(state.latencyMs / 1000).toFixed(1)}s`}</span></span>
          </div>
        )}
        {state.approvalWaitMs != null && (
          <div className="flex items-center gap-1.5 text-orange-400">
            <UserCheck className="h-3 w-3 shrink-0" />
            <span>Approval wait: <span className="font-mono">{(state.approvalWaitMs / 1000).toFixed(1)}s</span></span>
          </div>
        )}
      </div>

      {/* Error */}
      {state.error && (
        <div className="space-y-1">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-medium text-red-400 flex items-center gap-1">
              <AlertTriangle className="h-3 w-3" /> Error
            </span>
            <button
              type="button"
              onClick={copyError}
              className="text-[9px] text-muted-foreground hover:text-foreground flex items-center gap-0.5 cursor-pointer"
              title="Copy error to clipboard"
            >
              <Copy className="h-2.5 w-2.5" /> Copy
            </button>
          </div>
          <div className="rounded-md border border-red-500/20 bg-red-500/5 p-2 text-[10px] text-red-300 font-mono max-h-24 overflow-auto break-words">
            {state.error}
          </div>
        </div>
      )}

      {/* Loop progress */}
      {data.loopConfig && state.loopProgress && (
        <div className="space-y-1.5 border rounded-md p-2 bg-blue-500/5">
          <Label className="text-[10px] text-blue-400 font-semibold">Loop Progress</Label>
          <div className="grid grid-cols-2 gap-1.5 text-[10px]">
            <span className="text-muted-foreground">Iteration</span>
            <span className="font-mono text-right">{state.loopProgress.iteration}/{state.loopProgress.maxIterations}</span>
            <span className="text-muted-foreground">Items</span>
            <span className="font-mono text-right">{state.loopProgress.completedItems}/{state.loopProgress.totalItems}</span>
          </div>
          {state.loopProgress.circuitBreakerState && (
            <div className="text-[9px] text-amber-400 mt-1">
              Circuit breaker: {state.loopProgress.circuitBreakerState.state} ({state.loopProgress.circuitBreakerState.consecutiveNoProgress}/{state.loopProgress.circuitBreakerState.threshold})
            </div>
          )}
          {state.loopProgress.exitReason && (
            <div className="text-[9px] text-muted-foreground mt-1">
              Exit: {state.loopProgress.exitReason}
            </div>
          )}
        </div>
      )}

      {/* Step output / execution data */}
      {state.execution && Object.keys(state.execution).length > 0 && (
        <div className="space-y-1">
          <Label className="text-[10px] text-muted-foreground font-semibold">Output</Label>
          <div className="relative">
            <pre className="rounded-md border bg-muted/30 p-2 text-[10px] font-mono max-h-40 overflow-auto break-words whitespace-pre-wrap">
              {typeof state.execution === "string" ? state.execution : JSON.stringify(state.execution, null, 2)}
            </pre>
            <button
              type="button"
              onClick={() => {
                navigator.clipboard.writeText(
                  typeof state.execution === "string" ? state.execution : JSON.stringify(state.execution, null, 2),
                );
                toast.success("Output copied to clipboard");
              }}
              className="absolute top-1 right-1 text-[9px] text-muted-foreground hover:text-foreground flex items-center gap-0.5 cursor-pointer rounded px-1 py-0.5 bg-background/80"
              title="Copy output"
            >
              <Copy className="h-2.5 w-2.5" /> Copy
            </button>
          </div>
        </div>
      )}

      {/* Worker job info */}
      {state.workerJob && Object.keys(state.workerJob).length > 0 && (
        <div className="space-y-1">
          <Label className="text-[10px] text-muted-foreground font-semibold">Worker Job</Label>
          <pre className="rounded-md border bg-muted/30 p-2 text-[10px] font-mono max-h-24 overflow-auto break-words whitespace-pre-wrap">
            {JSON.stringify(state.workerJob, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

/* ── Connections Tab ── */

function ConnectionsTab({
  node,
  edges,
  nodes,
  onSelectNode,
}: {
  node: ComposerNode;
  edges: Edge[];
  nodes: ComposerNode[];
  onSelectNode?: (nodeId: string) => void;
}) {
  const upstream = edges
    .filter((e) => e.target === node.id && e.source !== TRIGGER_NODE_ID)
    .map((e) => e.source);
  const downstream = edges
    .filter((e) => e.source === node.id)
    .map((e) => e.target);
  const triggerConnected = edges.some(
    (e) => e.target === node.id && e.source === TRIGGER_NODE_ID,
  );

  function nodeLabel(id: string) {
    const n = nodes.find((x) => x.id === id);
    if (!n) return id;
    if (n.type === "trigger") return "Trigger";
    return (n.data as AgentStepNodeData).stepName || id;
  }

  return (
    <div className="p-3 space-y-4">
      {/* Upstream */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
          <ArrowDown className="h-3 w-3" /> Depends on
        </div>
        {triggerConnected && (
          <button
            type="button"
            className="flex items-center gap-1.5 w-full rounded-md border bg-primary/5 border-primary/20 px-2 py-1 text-[10px] text-primary cursor-pointer hover:bg-primary/10 transition-colors"
            onClick={() => onSelectNode?.(TRIGGER_NODE_ID)}
          >
            Trigger (start)
          </button>
        )}
        {upstream.map((id) => (
          <button
            key={id}
            type="button"
            className="flex items-center gap-1.5 w-full rounded-md border bg-card px-2 py-1 text-[10px] cursor-pointer hover:bg-accent transition-colors"
            onClick={() => onSelectNode?.(id)}
          >
            {nodeLabel(id)}
          </button>
        ))}
        {!triggerConnected && upstream.length === 0 && (
          <p className="text-[10px] text-muted-foreground/60 italic">No dependencies</p>
        )}
      </div>

      {/* Downstream */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
          <ArrowUp className="h-3 w-3" /> Triggers
        </div>
        {downstream.map((id) => (
          <button
            key={id}
            type="button"
            className="flex items-center gap-1.5 w-full rounded-md border bg-card px-2 py-1 text-[10px] cursor-pointer hover:bg-accent transition-colors"
            onClick={() => onSelectNode?.(id)}
          >
            {nodeLabel(id)}
          </button>
        ))}
        {downstream.length === 0 && (
          <p className="text-[10px] text-muted-foreground/60 italic">No downstream steps</p>
        )}
      </div>
    </div>
  );
}

/* ── Main panel ── */

export function PropertiesPanel({
  selectedNode,
  agents,
  edges,
  nodes,
  collapsed,
  onToggleCollapse,
  onNodeDataChange,
  onSelectNode,
}: PropertiesPanelProps) {
  // Collapsed strip
  if (collapsed) {
    return (
      <div className="w-10 border-l bg-muted/20 flex flex-col items-center py-2 gap-2 shrink-0 transition-[width] duration-200 ease-out">
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 shrink-0 cursor-pointer"
          onClick={onToggleCollapse}
          title="Expand properties (Ctrl+J)"
        >
          <PanelRightOpen className="h-3.5 w-3.5" />
        </Button>
        <span className="text-[9px] font-semibold text-muted-foreground uppercase tracking-wider [writing-mode:vertical-lr] select-none">
          Properties
        </span>
      </div>
    );
  }

  if (!selectedNode || selectedNode.id === TRIGGER_NODE_ID) {
    return (
      <div className="w-72 border-l bg-muted/20 flex flex-col items-center justify-center p-4 shrink-0 gap-2 transition-[width] duration-200 ease-out">
        <MousePointerClick className="h-6 w-6 text-muted-foreground/40" />
        <p className="text-xs text-muted-foreground text-center">
          Click a step node on the canvas to edit its properties
        </p>
      </div>
    );
  }

  const d = selectedNode.data as AgentStepNodeData;

  return (
    <div className="w-72 border-l bg-muted/20 flex flex-col overflow-hidden shrink-0 transition-[width] duration-200 ease-out">
      {/* Header */}
      <div className="px-3 py-2 text-xs font-semibold border-b flex items-center gap-2">
        <Settings className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="truncate flex-1">{d.stepName}</span>
        <Button
          variant="ghost"
          size="icon"
          className="h-5 w-5 shrink-0 cursor-pointer text-muted-foreground hover:text-foreground"
          onClick={onToggleCollapse}
          title="Collapse properties (Ctrl+J)"
        >
          <PanelRightClose className="h-3 w-3" />
        </Button>
      </div>

      <Tabs defaultValue="config" className="flex-1 flex flex-col min-h-0">
        <TabsList className="bg-secondary/30 mx-2 mt-2 rounded-lg p-0.5 h-auto shrink-0">
          <TabsTrigger value="config" className="text-[10px] px-2 py-1 gap-1 cursor-pointer">
            <Settings className="h-3 w-3" /> Config
          </TabsTrigger>
          <TabsTrigger value="execution" className="text-[10px] px-2 py-1 gap-1 cursor-pointer">
            <Activity className="h-3 w-3" /> Execution
          </TabsTrigger>
          <TabsTrigger value="connections" className="text-[10px] px-2 py-1 gap-1 cursor-pointer">
            <GitBranch className="h-3 w-3" /> Links
          </TabsTrigger>
        </TabsList>

        <ScrollArea className="flex-1 min-h-0">
          <TabsContent value="config" className="mt-0">
            <ConfigTab node={selectedNode} data={d} agents={agents} edges={edges} onNodeDataChange={onNodeDataChange} />
          </TabsContent>
          <TabsContent value="execution" className="mt-0">
            <ExecutionTab data={d} />
          </TabsContent>
          <TabsContent value="connections" className="mt-0">
            <ConnectionsTab node={selectedNode} edges={edges} nodes={nodes} onSelectNode={onSelectNode} />
          </TabsContent>
        </ScrollArea>
      </Tabs>
    </div>
  );
}
