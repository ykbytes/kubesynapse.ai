import { useRef, useMemo, useState, useEffect } from "react";
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
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import {
  UserCheck,
  Repeat,
  MousePointerClick,
  Settings,
  Activity,
  GitBranch,
  ShieldCheck,
  ArrowUp,
  ArrowDown,
  Clock,
  Copy,
  AlertTriangle,
  PanelRightClose,
  PanelRightOpen,
  Info,
  CheckCircle2,
  XCircle,
  LoaderCircle,
  ChevronDown,
  ChevronRight,
  FileText,
  Wrench,
  ListChecks,
  Circle,
  Timer,
  Zap,
  Package,
  Trash2,
  Sparkles,
  BarChart3,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import {
  extractPlaceholders,
  validatePlaceholders,
  getTransitiveUpstream,
  availablePlaceholders,
} from "@/lib/template-utils";
import { getRuntimeSignal } from "@/lib/agentSignals";
import {
  groupToolCalls,
  toolCallPreview,
  dominantStatus,
  type ToolCallGroup,
} from "@/lib/tool-utils";

interface PropertiesPanelProps {
  selectedNode: ComposerNode | null;
  agents: AgentInfo[];
  edges: Edge[];
  nodes: ComposerNode[];
  collapsed: boolean;
  onToggleCollapse: () => void;
  onNodeDataChange: (nodeId: string, patch: Partial<AgentStepNodeData>) => void;
  onSelectNode?: (nodeId: string) => void;
  onDeleteNode?: (nodeId: string) => void;
}

function humanizeStepStatus(status: string): string {
  return status
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

function shouldAutoOpenExecutionTab(status?: string | null): boolean {
  return status === "running" || status === "failed" || status === "denied" || status === "waiting_approval";
}

function shouldPreferExecutionTab(status?: string | null): boolean {
  return Boolean(status && status !== "pending");
}

function getStepStatusBadge(status?: string | null): { label: string; className: string; icon: React.ReactNode | null } | null {
  if (!status) return null;
  switch (status) {
    case "completed":
      return {
        label: "Completed",
        className: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20",
        icon: <CheckCircle2 className="h-2.5 w-2.5" />,
      };
    case "running":
      return {
        label: "Running",
        className: "text-amber-400 bg-amber-500/10 border-amber-500/20",
        icon: <LoaderCircle className="h-2.5 w-2.5 animate-spin" />,
      };
    case "failed":
      return {
        label: "Failed",
        className: "text-red-400 bg-red-500/10 border-red-500/20",
        icon: <XCircle className="h-2.5 w-2.5" />,
      };
    case "denied":
      return {
        label: "Denied",
        className: "text-red-400 bg-red-500/10 border-red-500/20",
        icon: <AlertTriangle className="h-2.5 w-2.5" />,
      };
    case "waiting_approval":
      return {
        label: "Waiting Approval",
        className: "text-orange-400 bg-orange-500/10 border-orange-500/20",
        icon: <UserCheck className="h-2.5 w-2.5" />,
      };
    case "continued":
      return {
        label: "Continued",
        className: "text-amber-400 bg-amber-500/10 border-amber-500/20",
        icon: <AlertTriangle className="h-2.5 w-2.5" />,
      };
    case "cancelled":
      return {
        label: "Cancelled",
        className: "text-orange-400 bg-orange-500/10 border-orange-500/20",
        icon: <XCircle className="h-2.5 w-2.5" />,
      };
    case "skipped":
      return {
        label: "Skipped",
        className: "text-muted-foreground bg-muted/50 border-border/40",
        icon: <Circle className="h-2.5 w-2.5" />,
      };
    case "queued":
      return {
        label: "Queued",
        className: "text-muted-foreground bg-muted/50 border-border/40",
        icon: <Clock className="h-2.5 w-2.5" />,
      };
    default:
      return {
        label: humanizeStepStatus(status),
        className: "text-muted-foreground bg-muted/50 border-border/40",
        icon: null,
      };
  }
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
  const selectedAgent = agents.find((agent) => agent.name === data.agentRef);
  const selectedRuntimeSignal = getRuntimeSignal(selectedAgent?.runtime_kind ?? data.runtimeKind);
  const SelectedRuntimeIcon = selectedRuntimeSignal.icon;

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
            {agents.map((a) => {
              const runtimeSignal = getRuntimeSignal(a.runtime_kind);
              const RuntimeIcon = runtimeSignal.icon;
              return (
                <SelectItem key={a.name} value={a.name}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate">{a.name}</span>
                    <span className={cn("inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[9px]", runtimeSignal.tone)}>
                      <RuntimeIcon className="h-3 w-3" />
                      {runtimeSignal.shortLabel}
                    </span>
                  </div>
                </SelectItem>
              );
            })}
          </SelectContent>
        </Select>
        {selectedAgent && (
          <div className="flex items-center gap-1.5 pt-1">
            <span className={cn("inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[9px]", selectedRuntimeSignal.tone)}>
              <SelectedRuntimeIcon className="h-3 w-3" />
              {selectedRuntimeSignal.shortLabel}
            </span>
            {selectedAgent.model && (
              <span className="text-[10px] text-muted-foreground font-mono truncate">{selectedAgent.model}</span>
            )}
          </div>
        )}
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
            onNodeDataChange(node.id, { stepType: v as "agent" | "loop" | "conditional" | "review" })
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
            <SelectItem value="review">
              <span className="flex items-center gap-1.5">
                <ShieldCheck className="h-3 w-3" /> Review
              </span>
            </SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Advanced Configuration Accordion */}
      <Accordion type="multiple" className="space-y-2">
        {/* Loop Configuration */}
        {data.stepType === "loop" && (
          <AccordionItem value="loop" className="border rounded-md px-2 bg-blue-500/[0.06]">
            <AccordionTrigger className="text-[10px] text-blue-500 font-semibold py-2 hover:no-underline">
              <span className="flex items-center gap-1"><Repeat className="h-3 w-3" /> Loop Config</span>
            </AccordionTrigger>
            <AccordionContent className="space-y-2 pb-2">
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
            </AccordionContent>
          </AccordionItem>
        )}

        {/* Conditional Configuration */}
        {data.stepType === "conditional" && (
          <AccordionItem value="conditional" className="border rounded-md px-2 bg-purple-500/[0.06]">
            <AccordionTrigger className="text-[10px] text-purple-500 font-semibold py-2 hover:no-underline">
              <span className="flex items-center gap-1"><GitBranch className="h-3 w-3" /> Conditional Config</span>
            </AccordionTrigger>
            <AccordionContent className="space-y-2 pb-2">
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
            </AccordionContent>
          </AccordionItem>
        )}

        {/* Review Configuration */}
        {data.stepType === "review" && (
          <AccordionItem value="review" className="border rounded-md px-2 bg-rose-500/[0.06]">
            <AccordionTrigger className="text-[10px] text-rose-400 font-semibold py-2 hover:no-underline">
              <span className="flex items-center gap-1"><ShieldCheck className="h-3 w-3" /> Review Config</span>
            </AccordionTrigger>
            <AccordionContent className="space-y-2 pb-2">
              <div className="space-y-1">
                <Label className="text-[10px]">Review Criteria</Label>
                <Textarea
                  value={data.reviewCriteria ?? ""}
                  onChange={(e) =>
                    onNodeDataChange(node.id, { reviewCriteria: e.target.value || null })
                  }
                  className="text-xs min-h-[56px]"
                  rows={3}
                  placeholder="Describe what the reviewing agent should evaluate, e.g. 'Ensure the output is valid YAML and all required keys are present.'"
                />
                <p className="text-[9px] text-muted-foreground/60 leading-tight">
                  The review agent evaluates the previous step output against these criteria and returns an approved / rejected verdict.
                </p>
              </div>
            </AccordionContent>
          </AccordionItem>
        )}

        {/* Verify Output */}
        <AccordionItem value="verify" className="border rounded-md px-2">
          <AccordionTrigger className="text-[10px] font-semibold py-2 hover:no-underline">
            <span className="flex items-center gap-1"><ShieldCheck className="h-3 w-3" /> {data.verify != null ? "Verify Output" : "No Verification"}</span>
          </AccordionTrigger>
          <AccordionContent className="space-y-2 pb-2">
            <Button
              variant={data.verify ? "secondary" : "outline"}
              size="sm"
              className="h-7 text-xs gap-1.5 w-full justify-start cursor-pointer"
              onClick={() => onNodeDataChange(node.id, { verify: data.verify ? null : "" })}
            >
              {data.verify != null ? "Disable Verification" : "Enable Verification"}
            </Button>
            {data.verify != null && (
              <div className="space-y-1">
                <Textarea
                  value={data.verify}
                  onChange={(e) =>
                    onNodeDataChange(node.id, { verify: e.target.value })
                  }
                  className="text-xs min-h-[48px]"
                  rows={2}
                  placeholder="Describe what to verify about this step's output, e.g. 'Confirm the generated YAML contains a valid Deployment manifest.'"
                />
                <p className="text-[9px] text-muted-foreground/60 leading-tight">
                  An additional verification pass runs after this step. Leave the prompt specific so the verifier can make a clear pass/fail decision.
                </p>
              </div>
            )}
          </AccordionContent>
        </AccordionItem>
      </Accordion>
    </div>
  );
}

/* ── Execution Tab ── */

/* ── Collapsible section wrapper with framer-motion animation ── */
function ExecSection({
  icon: Icon,
  label,
  count,
  defaultOpen = false,
  tone,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  count?: number | null;
  defaultOpen?: boolean;
  tone?: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={cn("border rounded-lg overflow-hidden", tone ?? "border-border/40")}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 w-full px-2.5 py-1.5 text-[10px] font-semibold text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
      >
        <Icon className="h-3 w-3 shrink-0" />
        <span className="flex-1 text-left">{label}</span>
        {count != null && count > 0 && (
          <span className="rounded-full bg-muted px-1.5 py-0.5 text-[9px] font-mono leading-none tabular-nums">
            {count}
          </span>
        )}
        <motion.span
          animate={{ rotate: open ? 180 : 0 }}
          transition={{ duration: 0.2 }}
          className="shrink-0"
        >
          <ChevronDown className="h-3 w-3" />
        </motion.span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="content"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: [0.4, 0, 0.2, 1] }}
            className="overflow-hidden"
          >
            <div className="px-2.5 pb-2.5 pt-0.5">
              {children}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/* ── Live elapsed timer hook ── */
function useElapsedTimer(startedAt?: string | null, isRunning?: boolean): string {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!startedAt || !isRunning) return;
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, [startedAt, isRunning]);
  if (!startedAt) return "—";
  const start = new Date(startedAt).getTime();
  if (Number.isNaN(start)) return "—";
  const elapsed = Date.now() - start;
  const ms = Math.max(0, elapsed);
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const m = Math.floor(ms / 60_000);
  const s = Math.round((ms % 60_000) / 1000);
  return `${m}m ${s}s`;
}

/* ── Status icon component ── */
function StatusIndicator({ status }: { status: string }) {
  const config: Record<string, { icon: React.ReactNode; ring: string; bg: string; label: string }> = {
    running: {
      icon: <LoaderCircle className="h-5 w-5 text-amber-400 animate-spin" />,
      ring: "ring-amber-500/30",
      bg: "bg-amber-500/10",
      label: "Running",
    },
    completed: {
      icon: <CheckCircle2 className="h-5 w-5 text-emerald-400" style={{ animation: "task-check-pop 0.4s ease-out both" }} />,
      ring: "ring-emerald-500/30",
      bg: "bg-emerald-500/10",
      label: "Completed",
    },
    failed: {
      icon: <XCircle className="h-5 w-5 text-red-400" />,
      ring: "ring-red-500/30",
      bg: "bg-red-500/10",
      label: "Failed",
    },
    denied: {
      icon: <AlertTriangle className="h-5 w-5 text-red-400" />,
      ring: "ring-red-500/30",
      bg: "bg-red-500/10",
      label: "Denied",
    },
    waiting_approval: {
      icon: <UserCheck className="h-5 w-5 text-orange-400" />,
      ring: "ring-orange-500/30",
      bg: "bg-orange-500/10",
      label: "Waiting Approval",
    },
    continued: {
      icon: <AlertTriangle className="h-5 w-5 text-amber-400" />,
      ring: "ring-amber-500/30",
      bg: "bg-amber-500/10",
      label: "Continued",
    },
    cancelled: {
      icon: <XCircle className="h-5 w-5 text-orange-400" />,
      ring: "ring-orange-500/30",
      bg: "bg-orange-500/10",
      label: "Cancelled",
    },
    skipped: {
      icon: <Circle className="h-5 w-5 text-muted-foreground/50" />,
      ring: "ring-border/30",
      bg: "bg-muted/30",
      label: "Skipped",
    },
    pending: {
      icon: <Circle className="h-5 w-5 text-muted-foreground/40" />,
      ring: "ring-border/30",
      bg: "bg-muted/30",
      label: "Pending",
    },
    queued: {
      icon: <Clock className="h-5 w-5 text-muted-foreground" />,
      ring: "ring-border/30",
      bg: "bg-muted/30",
      label: "Queued",
    },
  };
  const c = config[status] ?? {
    icon: <Circle className="h-5 w-5 text-muted-foreground/40" />,
    ring: "ring-border/30",
    bg: "bg-muted/30",
    label: humanizeStepStatus(status),
  };
  return (
    <motion.div
      key={status}
      initial={{ scale: 0.8, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      transition={{ type: "spring", stiffness: 400, damping: 25 }}
      className={cn("flex items-center gap-2.5 rounded-xl p-2.5 ring-1", c.ring, c.bg)}
    >
      <div className="relative">
        {c.icon}
        {status === "running" && (
          <span
            className="absolute inset-0 rounded-full text-amber-500/40"
            style={{ animation: "status-pulse-ring 1.5s ease-out infinite" }}
          />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-xs font-semibold capitalize">{c.label}</div>
      </div>
    </motion.div>
  );
}

/* ── Timing bar ── */
function TimingBar({ state, elapsed }: { state: { status: string; startedAt?: string | null; completedAt?: string | null; latencyMs?: number | null; approvalWaitMs?: number | null; attempts?: number }; elapsed: string }) {
  const isRunning = state.status === "running";
  const isDone = state.status === "completed";
  const isContinued = state.status === "continued";
  const isFailed = state.status === "failed" || state.status === "denied";
  const isStopped = state.status === "cancelled" || state.status === "skipped";
  const isTerminal = isDone || isContinued || isFailed || isStopped;
  const barColor = isDone
    ? "bg-emerald-500"
    : isFailed
      ? "bg-red-500"
      : isStopped
        ? "bg-orange-500"
        : "bg-amber-500";

  // Estimate progress (indeterminate for running, 100% for done/failed)
  const pct = isTerminal ? 100 : undefined;

  return (
    <div className="space-y-1.5">
      {/* Progress bar */}
      <div className="h-1.5 w-full rounded-full bg-muted/50 overflow-hidden">
        {pct != null ? (
          <motion.div
            className={cn("h-full rounded-full", barColor)}
            initial={{ width: 0 }}
            animate={{ width: `${pct}%` }}
            transition={{ duration: 0.6, ease: "easeOut" }}
          />
        ) : (
          <div
            className={cn("h-full rounded-full w-full", barColor)}
            style={{
              backgroundImage: `linear-gradient(90deg, transparent 0%, oklch(0.75 0.15 85 / 0.6) 50%, transparent 100%)`,
              backgroundSize: "200% 100%",
              animation: "running-shimmer 1.5s linear infinite",
            }}
          />
        )}
      </div>

      {/* Timing details */}
      <div className="flex items-center justify-between text-[10px]">
        <div className="flex items-center gap-1 text-muted-foreground">
          <Timer className="h-3 w-3 shrink-0" />
          {state.startedAt && (
            <span className="font-mono">{new Date(state.startedAt).toLocaleTimeString()}</span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          {state.attempts != null && state.attempts > 1 && (
            <span className="text-[9px] text-amber-400 font-medium">attempt {state.attempts}</span>
          )}
          <span className={cn("font-mono font-semibold tabular-nums", isRunning ? "text-amber-400" : isDone ? "text-emerald-400" : isFailed ? "text-red-400" : isTerminal ? "text-orange-400" : "text-muted-foreground")}>
            {state.latencyMs != null && !isRunning
              ? state.latencyMs < 1000 ? `${state.latencyMs}ms` : `${(state.latencyMs / 1000).toFixed(1)}s`
              : elapsed}
          </span>
        </div>
      </div>

      {/* Approval wait segment */}
      {state.approvalWaitMs != null && (
        <div className="flex items-center gap-1 text-[9px] text-orange-400">
          <UserCheck className="h-2.5 w-2.5 shrink-0" />
          <span>Approval wait: <span className="font-mono">{(state.approvalWaitMs / 1000).toFixed(1)}s</span></span>
        </div>
      )}
    </div>
  );
}

/* ── Plan tasks checklist ── */
function PlanChecklist({ planProgress }: { planProgress: { items: { text: string; done: boolean }[]; completedItems: number; totalItems: number } }) {
  const pct = planProgress.totalItems > 0 ? Math.round((planProgress.completedItems / planProgress.totalItems) * 100) : 0;
  // Find the first non-done item (currently executing)
  const activeIdx = planProgress.items.findIndex((i) => !i.done);

  return (
    <div className="space-y-2">
      {/* Mini progress bar */}
      <div className="flex items-center gap-2">
        <div className="h-1 flex-1 rounded-full bg-muted/50 overflow-hidden">
          <motion.div
            className="h-full rounded-full bg-sky-500"
            initial={{ width: 0 }}
            animate={{ width: `${pct}%` }}
            transition={{ duration: 0.4, ease: "easeOut" }}
          />
        </div>
        <span className="text-[9px] font-mono text-muted-foreground tabular-nums">{planProgress.completedItems}/{planProgress.totalItems}</span>
      </div>

      {/* Task list */}
      <div className="space-y-0.5">
        {planProgress.items.map((item, i) => {
          const isActive = i === activeIdx;
          return (
            <motion.div
              key={i}
              initial={{ opacity: 0, x: 8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.03, duration: 0.2 }}
              className={cn(
                "flex items-start gap-1.5 rounded-md px-1.5 py-1 text-[10px] transition-colors",
                isActive && "bg-sky-500/10",
              )}
            >
              {item.done ? (
                <CheckCircle2
                  className="h-3 w-3 shrink-0 mt-px text-emerald-400"
                  style={{ animation: "task-check-pop 0.3s ease-out both" }}
                />
              ) : isActive ? (
                <LoaderCircle className="h-3 w-3 shrink-0 mt-px text-sky-400 animate-spin" />
              ) : (
                <Circle className="h-3 w-3 shrink-0 mt-px text-muted-foreground/30" />
              )}
              <span className={cn(
                "leading-tight",
                item.done ? "text-muted-foreground line-through" : isActive ? "text-foreground font-medium" : "text-muted-foreground/60",
              )}>
                {item.text}
              </span>
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}

/* ── Tool call timeline ── */
function ToolCallTimeline({ toolCalls }: { toolCalls: { tool?: string | null; status?: string | null; inputPreview?: string | null; preview?: string | null }[] }) {
  const [expandedGroup, setExpandedGroup] = useState<string | null>(null);
  const [expandedCall, setExpandedCall] = useState<number | null>(null);

  const groups = groupToolCalls(toolCalls);

  if (groups.length === 0) return null;

  return (
    <div className="space-y-1">
      {groups.map((group) => {
        const meta = group.meta;
        const Icon = meta.icon;
        const isExpanded = expandedGroup === group.tool;
        const calls = toolCalls.filter((tc) => (tc.tool ?? "").toLowerCase() === group.tool.toLowerCase());

        return (
          <div key={group.tool} className="rounded-md border border-border/30 bg-background/40 overflow-hidden">
            {/* Group header */}
            <button
              type="button"
              onClick={() => setExpandedGroup(isExpanded ? null : group.tool)}
              className="flex items-center gap-2 w-full px-2 py-1.5 text-left cursor-pointer hover:bg-accent/40 transition-colors"
            >
              <Icon className={cn("h-3 w-3 shrink-0", meta.color)} />
              <span className="text-[10px] font-medium flex-1 truncate">{meta.label}</span>
              {group.count > 1 && (
                <span className="text-[9px] font-mono text-muted-foreground/60 tabular-nums">x{group.count}</span>
              )}
              <StatusDot status={dominantStatus(group.statuses)} />
              <ChevronRight className={cn("h-2.5 w-2.5 text-muted-foreground/40 shrink-0 transition-transform", isExpanded && "rotate-90")} />
            </button>

            {/* Group preview */}
            {!isExpanded && group.inputPreviews.length > 0 && (
              <div className="px-2 pb-1.5">
                <span className="text-[9px] text-muted-foreground/60 truncate block">
                  {toolCallPreview(group.tool, group.inputPreviews[0])}
                </span>
              </div>
            )}

            {/* Expanded individual calls */}
            <AnimatePresence>
              {isExpanded && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: "auto", opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.2 }}
                  className="overflow-hidden"
                >
                  <div className="border-t border-border/20 divide-y divide-border/10">
                    {calls.map((tc, ci) => {
                      const isCallExpanded = expandedCall === ci;
                      return (
                        <div key={ci}>
                          <button
                            type="button"
                            onClick={() => setExpandedCall(isCallExpanded ? null : ci)}
                            className="flex items-center gap-2 w-full px-3 py-1 text-left cursor-pointer hover:bg-accent/30 transition-colors"
                          >
                            <StatusDot status={tc.status ?? "unknown"} />
                            <span className="text-[9px] font-mono text-muted-foreground truncate flex-1">
                              #{ci + 1}
                            </span>
                            <span className="text-[9px] text-muted-foreground/60 truncate max-w-[120px]">
                              {toolCallPreview(tc.tool, tc.inputPreview)}
                            </span>
                          </button>
                          <AnimatePresence>
                            {isCallExpanded && (tc.inputPreview || tc.preview) && (
                              <motion.div
                                initial={{ height: 0, opacity: 0 }}
                                animate={{ height: "auto", opacity: 1 }}
                                exit={{ height: 0, opacity: 0 }}
                                transition={{ duration: 0.15 }}
                                className="overflow-hidden"
                              >
                                <div className="px-3 pb-1.5 space-y-1">
                                  {tc.inputPreview && (
                                    <div className="rounded border bg-muted/20 p-1.5">
                                      <div className="text-[8px] uppercase tracking-wider text-muted-foreground/50 mb-0.5">Input</div>
                                      <pre className="text-[9px] font-mono text-muted-foreground whitespace-pre-wrap break-words max-h-16 overflow-auto">{tc.inputPreview}</pre>
                                    </div>
                                  )}
                                  {tc.preview && (
                                    <div className="rounded border bg-muted/20 p-1.5">
                                      <div className="text-[8px] uppercase tracking-wider text-muted-foreground/50 mb-0.5">Output</div>
                                      <pre className="text-[9px] font-mono text-muted-foreground whitespace-pre-wrap break-words max-h-16 overflow-auto">{tc.preview}</pre>
                                    </div>
                                  )}
                                </div>
                              </motion.div>
                            )}
                          </AnimatePresence>
                        </div>
                      );
                    })}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        );
      })}
    </div>
  );
}

function StatusDot({ status }: { status: string }) {
  const cls = status === "completed" || status === "success"
    ? "bg-emerald-500"
    : status === "error" || status === "failed"
      ? "bg-red-500"
      : status === "running"
        ? "bg-amber-500"
        : "bg-muted-foreground/40";
  return <span className={cn("h-1.5 w-1.5 rounded-full shrink-0", cls)} />;
}

/* ── Artifacts list ── */
function ArtifactsList({ artifacts }: { artifacts: { path?: string | null; name?: string | null; tool?: string | null; status?: string | null; type?: string | null; preview?: string | null }[] }) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);

  function typeIcon(type?: string | null, path?: string | null) {
    const ext = path?.split(".").pop()?.toLowerCase();
    if (type === "code" || ext === "ts" || ext === "tsx" || ext === "py" || ext === "js") return <FileText className="h-3 w-3 text-sky-400" />;
    if (type === "report" || ext === "md") return <FileText className="h-3 w-3 text-violet-400" />;
    if (ext === "json" || ext === "yaml" || ext === "yml") return <FileText className="h-3 w-3 text-amber-400" />;
    return <Package className="h-3 w-3 text-muted-foreground" />;
  }

  return (
    <div className="space-y-1">
      {artifacts.map((a, i) => {
        const isExpanded = expandedIdx === i;
        const displayName = a.name || a.path?.split("/").pop() || "artifact";
        return (
          <motion.div
            key={i}
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: i * 0.03, duration: 0.2 }}
          >
            <button
              type="button"
              onClick={() => setExpandedIdx(isExpanded ? null : i)}
              className={cn(
                "w-full text-left rounded-md border p-1.5 transition-colors cursor-pointer",
                isExpanded ? "bg-card border-border" : "border-border/30 hover:border-border hover:bg-card/50",
              )}
            >
              <div className="flex items-center gap-1.5">
                {typeIcon(a.type, a.path)}
                <span className="text-[10px] font-medium truncate flex-1">{displayName}</span>
                {a.status && (
                  <span className={cn(
                    "text-[8px] uppercase tracking-wider font-semibold px-1 py-0.5 rounded",
                    a.status === "created" ? "text-emerald-400 bg-emerald-500/10" : "text-muted-foreground bg-muted/50",
                  )}>
                    {a.status}
                  </span>
                )}
                {a.preview && (
                  <ChevronRight className={cn("h-2.5 w-2.5 text-muted-foreground/40 shrink-0 transition-transform", isExpanded && "rotate-90")} />
                )}
              </div>
              {a.path && a.path !== displayName && (
                <div className="text-[9px] font-mono text-muted-foreground/40 truncate mt-0.5">{a.path}</div>
              )}
              {a.tool && (
                <div className="text-[9px] text-muted-foreground/40 mt-0.5">via {a.tool}</div>
              )}
            </button>
            <AnimatePresence>
              {isExpanded && a.preview && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: "auto", opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.2 }}
                  className="overflow-hidden"
                >
                  <pre className="mt-0.5 rounded border bg-muted/20 p-1.5 text-[9px] font-mono text-muted-foreground whitespace-pre-wrap break-words max-h-24 overflow-auto">
                    {a.preview}
                  </pre>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        );
      })}
    </div>
  );
}

/* ── Overview Tab ── */

function OverviewTab({ data }: { data: AgentStepNodeData }) {
  const rawState = data.stepState;
  const isRunning = rawState?.status === "running";
  const elapsed = useElapsedTimer(rawState?.startedAt, isRunning);

  if (!rawState?.status) {
    return (
      <div className="flex flex-col items-center justify-center py-10 text-center text-muted-foreground/60">
        <motion.div
          initial={{ scale: 0.8, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ type: "spring", stiffness: 300, damping: 25 }}
        >
          <Activity className="h-6 w-6 mb-3 mx-auto" />
        </motion.div>
        <p className="text-[10px]">No execution data yet.</p>
        <p className="text-[10px] mt-0.5">Run the workflow to see live step progress.</p>
      </div>
    );
  }

  const state = rawState;

  const statusConfig: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
    completed: {
      label: "Completed",
      color: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20",
      icon: <CheckCircle2 className="h-4 w-4 text-emerald-400" />,
    },
    running: {
      label: "Running",
      color: "text-amber-400 bg-amber-500/10 border-amber-500/20",
      icon: <LoaderCircle className="h-4 w-4 text-amber-400 animate-spin" />,
    },
    failed: {
      label: "Failed",
      color: "text-red-400 bg-red-500/10 border-red-500/20",
      icon: <XCircle className="h-4 w-4 text-red-400" />,
    },
    waiting_approval: {
      label: "Waiting Approval",
      color: "text-orange-400 bg-orange-500/10 border-orange-500/20",
      icon: <UserCheck className="h-4 w-4 text-orange-400" />,
    },
    queued: {
      label: "Queued",
      color: "text-muted-foreground bg-muted/50 border-border/40",
      icon: <Clock className="h-4 w-4 text-muted-foreground" />,
    },
  };
  const sc = statusConfig[state.status] ?? {
    label: state.status,
    color: "text-muted-foreground bg-muted/50 border-border/40",
    icon: <Circle className="h-4 w-4 text-muted-foreground" />,
  };

  const toolGroups = groupToolCalls(state.toolCalls);
  const totalTools = state.toolCallCount ?? toolGroups.reduce((s, g) => s + g.count, 0);
  const totalArtifacts = state.artifactCount ?? state.artifacts?.length ?? 0;
  const warningCount = state.warnings?.length ?? 0;
  const hasErrors = !!state.error || !!state.failureClass;
  const hasVerify = !!state.verificationResult;
  const hasReview = !!state.reviewResult;

  function suggestedAction(): { action: string; reason: string } | null {
    if (state.status === "failed") return { action: "Inspect error and tool activity", reason: state.error ? state.error.slice(0, 120) : "Step failed" };
    if (state.status === "waiting_approval") return { action: "Review output and approve or deny", reason: "Step is blocked on human decision" };
    if (state.status === "running") return { action: "Step is in progress", reason: `Elapsed: ${elapsed}` };
    if (hasVerify && !state.verificationResult!.passed) return { action: "Verification failed — review activity", reason: state.verificationResult!.criteria ?? "Verification criteria not met" };
    if (hasReview && !state.reviewResult!.approved) return { action: "Review was rejected — check feedback", reason: "Step output did not pass review" };
    if (warningCount > 0) return { action: `${warningCount} warning${warningCount > 1 ? "s" : ""} to review`, reason: "Open Activity tab for details" };
    if (state.status === "completed") return { action: "Step completed successfully", reason: `${totalTools} tool calls, ${totalArtifacts} artifacts in ${state.latencyMs != null ? `${(state.latencyMs / 1000).toFixed(1)}s` : "—"}` };
    return null;
  }
  const action = suggestedAction();

  return (
    <div className="p-2.5 space-y-3">
      {/* Status hero */}
      <div className={cn("rounded-xl border p-3 space-y-2", sc.color.split(" ").slice(1).join(" "))}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            {sc.icon}
            <span className="text-xs font-semibold">{sc.label}</span>
          </div>
          <span className="text-xs tabular-nums text-muted-foreground">
            {state.latencyMs != null
              ? state.latencyMs < 1000 ? `${state.latencyMs}ms` : `${(state.latencyMs / 1000).toFixed(1)}s`
              : elapsed}
          </span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {totalTools > 0 && <MetricChip icon={Wrench} label={`${totalTools} tool${totalTools !== 1 ? "s" : ""}`} />}
          {totalArtifacts > 0 && <MetricChip icon={FileText} label={`${totalArtifacts} file${totalArtifacts !== 1 ? "s" : ""}`} />}
          {warningCount > 0 && <MetricChip icon={AlertTriangle} label={`${warningCount} warning${warningCount !== 1 ? "s" : ""}`} tone="warning" />}
          {hasErrors && <MetricChip icon={XCircle} label="Has errors" tone="error" />}
          {hasVerify && (
            <MetricChip
              icon={ShieldCheck}
              label={state.verificationResult!.passed ? "Verified" : "Verify failed"}
              tone={state.verificationResult!.passed ? "success" : "error"}
            />
          )}
          {hasReview && (
            <MetricChip
              icon={ShieldCheck}
              label={state.reviewResult!.approved ? "Approved" : "Rejected"}
              tone={state.reviewResult!.approved ? "success" : "warning"}
            />
          )}
          {state.attempts != null && state.attempts > 1 && (
            <MetricChip icon={Repeat} label={`Attempt ${state.attempts}`} tone="warning" />
          )}
          {state.approvalWaitMs != null && (
            <MetricChip icon={UserCheck} label={`Wait ${(state.approvalWaitMs / 1000).toFixed(0)}s`} tone="warning" />
          )}
        </div>
      </div>

      {/* What happened */}
      {state.responsePreview && (
        <div className="rounded-lg border border-border/40 bg-background/60 p-2.5">
          <div className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/60 mb-1">What happened</div>
          <p className="text-[10px] leading-relaxed text-muted-foreground line-clamp-3">
            {state.responsePreview}
          </p>
        </div>
      )}

      {/* Suggested next action */}
      {action && (
        <div className="flex items-start gap-2 rounded-lg border border-primary/20 bg-primary/5 p-2.5">
          <Sparkles className="h-3.5 w-3.5 mt-0.5 text-primary shrink-0" />
          <div>
            <div className="text-[10px] font-medium text-foreground">{action.action}</div>
            <div className="text-[9px] text-muted-foreground mt-0.5">{action.reason}</div>
          </div>
        </div>
      )}

      {/* Tool mix summary */}
      {toolGroups.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/60">Tool activity</div>
          {toolGroups.slice(0, 6).map((group) => (
            <ToolMixRow key={group.tool} group={group} />
          ))}
          {toolGroups.length > 6 && (
            <div className="text-[9px] text-muted-foreground/60 text-center">
              +{toolGroups.length - 6} more tool types
            </div>
          )}
        </div>
      )}

      {/* Important outputs */}
      {state.verificationResult && (
        <div className={cn(
          "rounded-lg border p-2.5",
          state.verificationResult.passed
            ? "border-emerald-500/20 bg-emerald-500/5"
            : "border-red-500/20 bg-red-500/5",
        )}>
          <div className="flex items-center gap-1.5 text-[10px] font-medium">
            <ShieldCheck className={cn("h-3 w-3", state.verificationResult.passed ? "text-emerald-400" : "text-red-400")} />
            <span>Verification: {state.verificationResult.passed ? "PASSED" : "FAILED"}</span>
          </div>
          {state.verificationResult.criteria && (
            <div className="text-[9px] text-muted-foreground mt-1">{state.verificationResult.criteria}</div>
          )}
        </div>
      )}

      {state.reviewResult && (
        <div className={cn(
          "rounded-lg border p-2.5",
          state.reviewResult.approved
            ? "border-emerald-500/20 bg-emerald-500/5"
            : "border-amber-500/20 bg-amber-500/5",
        )}>
          <div className="flex items-center gap-1.5 text-[10px] font-medium">
            <ShieldCheck className={cn("h-3 w-3", state.reviewResult.approved ? "text-emerald-400" : "text-amber-400")} />
            <span>Review: {state.reviewResult.verdict ?? (state.reviewResult.approved ? "APPROVED" : "REJECTED")}</span>
          </div>
        </div>
      )}
    </div>
  );
}

function MetricChip({ icon: Icon, label, tone }: { icon: React.ComponentType<{ className?: string }>; label: string; tone?: "success" | "warning" | "error" }) {
  const toneStyles = {
    success: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20",
    warning: "text-amber-400 bg-amber-500/10 border-amber-500/20",
    error: "text-red-400 bg-red-500/10 border-red-500/20",
  };
  const cls = tone ? toneStyles[tone] : "text-muted-foreground bg-muted/30 border-border/40";
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[9px] font-medium leading-none", cls)}>
      <Icon className="h-2.5 w-2.5" />
      {label}
    </span>
  );
}

function ToolMixRow({ group }: { group: ToolCallGroup }) {
  const meta = group.meta;
  const Icon = meta.icon;
  const status = dominantStatus(group.statuses);
  const statusColors: Record<string, string> = {
    completed: "text-emerald-400",
    error: "text-red-400",
    failed: "text-red-400",
    running: "text-amber-400",
  };

  return (
    <div className="flex items-center gap-2 rounded-md border border-border/30 bg-background/40 px-2 py-1.5">
      <Icon className={cn("h-3 w-3 shrink-0", meta.color)} />
      <span className="text-[10px] font-medium flex-1 truncate">{meta.label}</span>
      {group.count > 1 && (
        <span className="text-[9px] font-mono text-muted-foreground/60 tabular-nums">x{group.count}</span>
      )}
      <span className={cn("text-[9px] font-medium", statusColors[status] ?? "text-muted-foreground")}>
        {status}
      </span>
    </div>
  );
}

function ActivityTab({ data }: { data: AgentStepNodeData }) {
  const state = data.stepState;
  const isRunning = state?.status === "running";
  const elapsed = useElapsedTimer(state?.startedAt, isRunning);

  if (!state?.status) {
    return (
      <div className="flex flex-col items-center justify-center py-10 text-center text-muted-foreground/60">
        <motion.div
          initial={{ scale: 0.8, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ type: "spring", stiffness: 300, damping: 25 }}
        >
          <Activity className="h-6 w-6 mb-3 mx-auto" />
        </motion.div>
        <p className="text-[10px]">No execution data yet.</p>
        <p className="text-[10px] mt-0.5">Run the workflow to see live step progress.</p>
      </div>
    );
  }

  const copyError = () => {
    if (state.error) {
      navigator.clipboard.writeText(state.error);
      toast.success("Error copied to clipboard");
    }
  };

  const hasToolCalls = state.toolCalls && state.toolCalls.length > 0;
  const hasArtifacts = state.artifacts && state.artifacts.length > 0;
  const hasPlan = state.planProgress && state.planProgress.items.length > 0;
  const hasLoop = data.loopConfig && state.loopProgress;
  const hasVerification = !!state.verificationResult;
  const hasReview = !!state.reviewResult;
  const hasError = !!state.error;
  const hasIterFailures = state.iterationFailures && state.iterationFailures.length > 0;
  const hasOutput = state.execution && Object.keys(state.execution).length > 0;
  const hasWarnings = state.warnings && state.warnings.length > 0;

  return (
    <div className="p-2.5 space-y-2">
      {/* ── Animated Status Header ── */}
      <StatusIndicator status={state.status} />

      {/* ── Timing Bar ── */}
      {state.startedAt && (
        <TimingBar state={state} elapsed={elapsed} />
      )}

      {/* ── Failure class badge ── */}
      {state.failureClass && (
        <motion.div
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex items-center gap-1.5 text-[9px]"
        >
          <span className="rounded-full border border-red-500/20 bg-red-500/10 px-1.5 py-0.5 font-mono text-red-400">
            {state.failureClass}
          </span>
        </motion.div>
      )}

      {/* ── Error Section ── */}
      {hasError && (
        <ExecSection icon={AlertTriangle} label="Error" defaultOpen tone="border-red-500/30">
          <div className="space-y-1">
            <div className="flex justify-end">
              <button
                type="button"
                onClick={copyError}
                className="text-[9px] text-muted-foreground hover:text-foreground flex items-center gap-0.5 cursor-pointer"
                title="Copy error to clipboard"
              >
                <Copy className="h-2.5 w-2.5" /> Copy
              </button>
            </div>
            <div className="rounded-md border border-red-500/20 bg-red-500/5 p-2 text-[10px] text-red-300 font-mono max-h-28 overflow-auto break-words">
              {state.error}
            </div>
          </div>
        </ExecSection>
      )}

      {/* ── Plan Progress ── */}
      {hasPlan && (
        <ExecSection
          icon={ListChecks}
          label="Plan Progress"
          count={state.planProgress!.totalItems}
          defaultOpen={isRunning || state.planProgress!.completedItems < state.planProgress!.totalItems}
        >
          <PlanChecklist planProgress={state.planProgress!} />
        </ExecSection>
      )}

      {/* ── Tool Calls Timeline ── */}
      {(hasToolCalls || (state.toolCallCount != null && state.toolCallCount > 0)) && (
        <ExecSection
          icon={Wrench}
          label="Tool Calls"
          count={state.toolCallCount ?? state.toolCalls?.length ?? 0}
          defaultOpen={isRunning}
        >
          {hasToolCalls ? (
            <ToolCallTimeline toolCalls={state.toolCalls!} />
          ) : (
            <div className="text-[10px] text-muted-foreground/50 text-center py-2">
              <Wrench className="h-3.5 w-3.5 mx-auto mb-1 opacity-40" />
              {state.toolCallCount} tool call{state.toolCallCount !== 1 ? "s" : ""} recorded
            </div>
          )}
        </ExecSection>
      )}

      {/* ── Artifacts ── */}
      {(hasArtifacts || (state.artifactCount != null && state.artifactCount > 0)) && (
        <ExecSection
          icon={Package}
          label="Artifacts"
          count={state.artifactCount ?? state.artifacts?.length ?? 0}
          defaultOpen={false}
        >
          {hasArtifacts ? (
            <ArtifactsList artifacts={state.artifacts!} />
          ) : (
            <div className="text-[10px] text-muted-foreground/50 text-center py-2">
              <Package className="h-3.5 w-3.5 mx-auto mb-1 opacity-40" />
              {state.artifactCount} artifact{state.artifactCount !== 1 ? "s" : ""} generated
            </div>
          )}
        </ExecSection>
      )}

      {/* ── Loop Progress ── */}
      {hasLoop && (
        <ExecSection icon={Repeat} label="Loop Progress" defaultOpen={isRunning} tone="border-blue-500/30">
          <div className="space-y-1.5">
            <div className="grid grid-cols-2 gap-1.5 text-[10px]">
              <span className="text-muted-foreground">Iteration</span>
              <span className="font-mono text-right">{state.loopProgress!.iteration}/{state.loopProgress!.maxIterations}</span>
              <span className="text-muted-foreground">Items</span>
              <span className="font-mono text-right">{state.loopProgress!.completedItems}/{state.loopProgress!.totalItems}</span>
            </div>
            {/* Loop progress bar */}
            <div className="h-1 w-full rounded-full bg-muted/50 overflow-hidden">
              <motion.div
                className="h-full rounded-full bg-blue-500"
                initial={{ width: 0 }}
                animate={{ width: `${state.loopProgress!.totalItems > 0 ? Math.round((state.loopProgress!.completedItems / state.loopProgress!.totalItems) * 100) : 0}%` }}
                transition={{ duration: 0.4 }}
              />
            </div>
            {/* Checklist items if present */}
            {state.loopProgress!.checklistItems && state.loopProgress!.checklistItems.length > 0 && (
              <div className="space-y-0.5 mt-1">
                {state.loopProgress!.checklistItems.map((ci, i) => (
                  <div key={i} className="flex items-center gap-1.5 text-[9px]">
                    {ci.done ? (
                      <CheckCircle2 className="h-2.5 w-2.5 text-emerald-400 shrink-0" />
                    ) : (
                      <Circle className="h-2.5 w-2.5 text-muted-foreground/30 shrink-0" />
                    )}
                    <span className={cn(ci.done ? "text-muted-foreground line-through" : "text-foreground/80")}>{ci.text}</span>
                  </div>
                ))}
              </div>
            )}
            {state.loopProgress!.circuitBreakerState && (
              <div className="text-[9px] text-amber-400 flex items-center gap-1 mt-1">
                <Zap className="h-2.5 w-2.5 shrink-0" />
                Circuit breaker: {state.loopProgress!.circuitBreakerState.state} ({state.loopProgress!.circuitBreakerState.consecutiveNoProgress}/{state.loopProgress!.circuitBreakerState.threshold})
              </div>
            )}
            {state.loopProgress!.exitReason && (
              <div className="text-[9px] text-muted-foreground mt-1">Exit: {state.loopProgress!.exitReason}</div>
            )}
          </div>
        </ExecSection>
      )}

      {/* ── Verification ── */}
      {hasVerification && (
        <ExecSection
          icon={ShieldCheck}
          label={`Verification: ${state.verificationResult!.passed ? "PASSED" : "FAILED"}`}
          defaultOpen={!state.verificationResult!.passed}
          tone={state.verificationResult!.passed ? "border-emerald-500/30" : "border-red-500/30"}
        >
          <div className="space-y-1">
            {state.verificationResult!.criteria && (
              <div className="text-[9px] text-muted-foreground">Criteria: {state.verificationResult!.criteria}</div>
            )}
            {state.verificationResult!.response && (
              <div className="text-[9px] whitespace-pre-wrap max-h-24 overflow-auto rounded border bg-muted/20 p-1.5">{state.verificationResult!.response}</div>
            )}
            {state.verificationResult!.verifyAttempt != null && state.verificationResult!.verifyAttempt > 1 && (
              <div className="text-[9px] text-muted-foreground">Attempt: {state.verificationResult!.verifyAttempt}</div>
            )}
          </div>
        </ExecSection>
      )}

      {/* ── Review ── */}
      {hasReview && (
        <ExecSection
          icon={ShieldCheck}
          label={`Review: ${state.reviewResult!.verdict}`}
          defaultOpen={!state.reviewResult!.approved}
          tone={state.reviewResult!.approved ? "border-emerald-500/30" : "border-amber-500/30"}
        >
          <div className="space-y-1">
            {state.reviewResult!.criteria && (
              <div className="text-[9px] text-muted-foreground">Criteria: {state.reviewResult!.criteria}</div>
            )}
            {state.reviewResult!.response && (
              <div className="text-[9px] whitespace-pre-wrap max-h-24 overflow-auto rounded border bg-muted/20 p-1.5">{state.reviewResult!.response}</div>
            )}
          </div>
        </ExecSection>
      )}

      {/* ── Warnings ── */}
      {hasWarnings && (
        <ExecSection icon={AlertTriangle} label="Warnings" count={state.warnings!.length} defaultOpen tone="border-amber-500/30">
          <div className="space-y-0.5">
            {state.warnings!.map((w, i) => (
              <div key={i} className="flex items-start gap-1 text-[9px] text-amber-400">
                <AlertTriangle className="h-2.5 w-2.5 shrink-0 mt-px" />
                <span className="break-words">{w}</span>
              </div>
            ))}
          </div>
        </ExecSection>
      )}

      {/* ── Iteration Failures ── */}
      {hasIterFailures && (
        <ExecSection icon={XCircle} label="Iteration Failures" count={state.iterationFailures!.length} defaultOpen={false} tone="border-red-500/30">
          <div className="space-y-1 max-h-32 overflow-auto">
            {state.iterationFailures!.map((f, i) => (
              <div key={i} className="text-[9px] border-b border-red-500/10 pb-1 last:border-0">
                <span className="text-muted-foreground">#{f.iteration}</span>
                {f.failureClass && <span className="ml-1 text-red-400">({f.failureClass})</span>}
                <span className="ml-1 text-red-300 break-words">{f.error}</span>
              </div>
            ))}
          </div>
        </ExecSection>
      )}

      {/* ── Output ── */}
      {hasOutput && (
        <ExecSection icon={FileText} label="Output" defaultOpen={false}>
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
        </ExecSection>
      )}

      {/* ── Empty state when no rich data ── */}
      {!hasToolCalls && !state.toolCallCount && !hasArtifacts && !state.artifactCount && !hasPlan && !hasLoop && !hasError && !hasVerification && !hasReview && !hasWarnings && !hasOutput && (
        <div className="flex flex-col items-center py-3 text-center">
          <Zap className="h-4 w-4 text-muted-foreground/30 mb-1.5" />
          <p className="text-[10px] text-muted-foreground/50">Waiting for execution data…</p>
        </div>
      )}
    </div>
  );
}

/* ── Dependencies Tab (renamed from Connections) ── */

function DependenciesTab({
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
  onDeleteNode,
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
      <div className="w-80 border-l bg-muted/20 flex flex-col items-center justify-center p-4 shrink-0 gap-2 transition-[width] duration-200 ease-out">
        <MousePointerClick className="h-6 w-6 text-muted-foreground/40" />
        <p className="text-xs text-muted-foreground text-center">
          Click a step node on the canvas to edit its properties
        </p>
      </div>
    );
  }

  const d = selectedNode.data as AgentStepNodeData;

  /* Auto-switch to Overview tab when step starts running or fails */
  const stepStatus = d.stepState?.status;
  const [activeTab, setActiveTab] = useState(() => (shouldPreferExecutionTab(stepStatus) ? "overview" : "config"));
  const prevStatusRef = useRef<string | undefined>(undefined);
  const nodeId = selectedNode.id;
  const prevNodeRef = useRef(nodeId);

  useEffect(() => {
    if (prevNodeRef.current !== nodeId) {
      prevNodeRef.current = nodeId;
      prevStatusRef.current = undefined;
      setActiveTab(shouldPreferExecutionTab(stepStatus) ? "overview" : "config");
      return;
    }

    const prev = prevStatusRef.current;
    prevStatusRef.current = stepStatus ?? undefined;
    if (activeTab === "config" && stepStatus && shouldAutoOpenExecutionTab(stepStatus) && prev !== stepStatus) {
      setActiveTab("overview");
    }
  }, [nodeId, stepStatus, activeTab]);

  const statusBadge = getStepStatusBadge(stepStatus);
  const showExecutionDot = stepStatus === "running" || stepStatus === "waiting_approval" || stepStatus === "failed" || stepStatus === "denied";
  const executionDotClass = stepStatus === "failed" || stepStatus === "denied"
    ? "bg-red-500"
    : stepStatus === "waiting_approval"
      ? "bg-orange-500"
      : "bg-amber-500";

  return (
    <div className="w-80 border-l bg-muted/20 flex flex-col overflow-hidden shrink-0 transition-[width] duration-200 ease-out">
      {/* Header */}
      <div className="px-3 py-2 text-xs font-semibold border-b flex items-center gap-2">
        <Settings className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="truncate flex-1">{d.stepName}</span>
        {statusBadge && (
          <span className={cn(
            "inline-flex items-center gap-0.5 rounded-full border px-1.5 py-0.5 text-[8px] font-medium leading-none",
            statusBadge.className,
          )}>
            {statusBadge.icon}
            {statusBadge.label}
          </span>
        )}
        {onDeleteNode && selectedNode.type === "agentStep" && (
          <Button
            variant="ghost"
            size="icon"
            className="h-5 w-5 shrink-0 cursor-pointer text-muted-foreground hover:text-destructive"
            onClick={() => onDeleteNode(selectedNode.id)}
            title="Delete step"
          >
            <Trash2 className="h-3 w-3" />
          </Button>
        )}
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

      <Tabs value={activeTab} onValueChange={setActiveTab} className="flex-1 flex flex-col min-h-0">
        <TabsList className="bg-secondary/30 mx-2 mt-2 rounded-lg p-0.5 h-auto shrink-0">
          <TabsTrigger value="overview" className="text-[10px] px-2 py-1 gap-1 cursor-pointer relative">
            <BarChart3 className="h-3 w-3" /> Overview
            {showExecutionDot && (
              <span className={cn("absolute -top-0.5 -right-0.5 h-1.5 w-1.5 rounded-full animate-pulse", executionDotClass)} />
            )}
          </TabsTrigger>
          <TabsTrigger value="activity" className="text-[10px] px-2 py-1 gap-1 cursor-pointer">
            <Activity className="h-3 w-3" /> Activity
          </TabsTrigger>
          <TabsTrigger value="config" className="text-[10px] px-2 py-1 gap-1 cursor-pointer">
            <Settings className="h-3 w-3" /> Config
          </TabsTrigger>
          <TabsTrigger value="dependencies" className="text-[10px] px-2 py-1 gap-1 cursor-pointer">
            <GitBranch className="h-3 w-3" /> Dependencies
          </TabsTrigger>
        </TabsList>

        <ScrollArea className="flex-1 min-h-0">
          <TabsContent value="overview" className="mt-0">
            <OverviewTab data={d} />
          </TabsContent>
          <TabsContent value="activity" className="mt-0">
            <ActivityTab data={d} />
          </TabsContent>
          <TabsContent value="config" className="mt-0">
            <ConfigTab node={selectedNode} data={d} agents={agents} edges={edges} onNodeDataChange={onNodeDataChange} />
          </TabsContent>
          <TabsContent value="dependencies" className="mt-0">
            <DependenciesTab node={selectedNode} edges={edges} nodes={nodes} onSelectNode={onSelectNode} />
          </TabsContent>
        </ScrollArea>
      </Tabs>
    </div>
  );
}
